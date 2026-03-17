"""Rule-based simulation for a solar + battery cooking system.

This model mimics a simple real-time controller:
  1) Use PV to serve cooking load directly.
  2) If PV is still available, charge the battery (subject to power and SoC limits).
  3) If PV is insufficient, discharge the battery (subject to power and SoC limits).
  4) Any remaining deficit is unmet load.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SystemParams:
    pv_capacity_kw: float
    batt_capacity_kwh: float
    batt_charge_kw: float
    batt_discharge_kw: float
    charge_eff: float
    discharge_eff: float
    soc_init: float  # fraction 0..1


def _validate_params(params: SystemParams) -> None:
    """Validate physical/algorithmic parameter bounds for simulation."""
    if not (0.0 <= params.soc_init <= 1.0):
        raise ValueError("soc_init must be between 0 and 1.")
    if params.pv_capacity_kw < 0 or params.batt_capacity_kwh < 0:
        raise ValueError("pv_capacity_kw and batt_capacity_kwh must be non-negative.")
    if params.batt_charge_kw < 0 or params.batt_discharge_kw < 0:
        raise ValueError("batt_charge_kw and batt_discharge_kw must be non-negative.")
    if not (0.0 <= params.charge_eff <= 1.0):
        raise ValueError("charge_eff must be between 0 and 1.")
    if not (0.0 <= params.discharge_eff <= 1.0):
        raise ValueError("discharge_eff must be between 0 and 1.")


def simulate_rule_based(df: pd.DataFrame, params: SystemParams) -> pd.DataFrame:
    """Run chronological rule dispatch on an input scenario dataframe.

    Dispatch priority:
    1) PV -> load
    2) PV -> battery
    3) Battery -> load
    4) remaining demand -> unmet
    """
    _validate_params(params)

    required = {"pv_kw_per_kwp", "demand_kwh", "dt_hours"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Input dataframe missing columns: {sorted(missing)}")

    dt_h = float(df["dt_hours"].iloc[0])
    if not np.allclose(df["dt_hours"].to_numpy(), dt_h):
        raise ValueError("This simple simulator expects constant dt_hours.")
    if dt_h <= 0:
        raise ValueError("dt_hours must be positive.")

    # Convert PV from kW/kWp to kWh in the timestep.
    pv_kwh = (df["pv_kw_per_kwp"].to_numpy() * params.pv_capacity_kw) * dt_h
    load_kwh = df["demand_kwh"].to_numpy()
    n = len(df)

    soc = np.zeros(n + 1, dtype=float)
    soc[0] = params.soc_init * params.batt_capacity_kwh

    pv_to_load = np.zeros(n)
    pv_to_batt = np.zeros(n)
    batt_to_load = np.zeros(n)
    lost_load = np.zeros(n)
    curtail_kwh = np.zeros(n)

    e_batt_max = params.batt_capacity_kwh
    e_ch_max = params.batt_charge_kw * dt_h
    e_dis_max = params.batt_discharge_kw * dt_h

    for t in range(n):
        soc_t = soc[t]
        pv_e = pv_kwh[t]
        load_e = load_kwh[t]

        # 1) PV directly to load.
        pv2l = min(pv_e, load_e)
        pv_to_load[t] = pv2l
        pv_e_rem = pv_e - pv2l
        load_rem = load_e - pv2l

        # 2) Charge battery with remaining PV.
        if pv_e_rem > 1e-12 and e_batt_max > 0:
            # PV energy used for charging is limited by charge power and SoC headroom.
            # soc increases by pv_used * charge_eff.
            pv_for_charge = min(pv_e_rem, e_ch_max, (e_batt_max - soc_t) / max(params.charge_eff, 1e-9))
            pv_for_charge = max(0.0, pv_for_charge)
            pv_to_batt[t] = pv_for_charge
            soc_t = soc_t + pv_for_charge * params.charge_eff
            pv_e_rem = pv_e_rem - pv_for_charge

        # 3) Discharge battery to cover remaining load.
        if load_rem > 1e-12 and e_batt_max > 0:
            # Battery energy withdrawn is limited by discharge power and SoC.
            # Delivered to load is withdrawn * discharge_eff.
            batt_withdraw = min(soc_t, e_dis_max, load_rem / max(params.discharge_eff, 1e-9))
            batt_withdraw = max(0.0, batt_withdraw)
            batt_delivered = batt_withdraw * params.discharge_eff
            batt_to_load[t] = batt_delivered
            soc_t = soc_t - batt_withdraw
            load_rem = load_rem - batt_delivered

        # 4) Remaining deficit is unmet load.
        if load_rem > 1e-9:
            lost_load[t] = load_rem

        # Any remaining PV after charging is curtailed.
        curtail_kwh[t] = max(0.0, pv_e_rem)

        soc[t + 1] = soc_t

    out = df.copy()
    out["pv_kwh"] = pv_kwh
    out["pv_to_load_kwh"] = pv_to_load
    out["pv_to_batt_kwh"] = pv_to_batt
    out["batt_to_load_kwh"] = batt_to_load
    out["lost_load_kwh"] = lost_load
    out["curtail_kwh"] = curtail_kwh
    out["soc_kwh"] = soc[1:]
    out["soc_frac"] = np.where(e_batt_max > 0, out["soc_kwh"] / e_batt_max, 0.0)
    out["pv_size_kw"] = params.pv_capacity_kw
    out["batt_size_kwh"] = params.batt_capacity_kwh
    return out


def summarize(sim: pd.DataFrame) -> dict[str, float]:
    """Compute compact reliability and energy balance metrics."""
    total_load = float(sim["demand_kwh"].sum())
    served_by_pv = float(sim["pv_to_load_kwh"].sum())
    served_by_batt = float(sim["batt_to_load_kwh"].sum())
    lost = float(sim["lost_load_kwh"].sum())
    curtail = float(sim["curtail_kwh"].sum())
    pv_gen = float(sim["pv_kwh"].sum())

    if total_load > 0:
        self_suff = (served_by_pv + served_by_batt) / total_load
        unmet_share = lost / total_load
    else:
        self_suff = 0.0
        unmet_share = 0.0

    capacity_sufficient = 1.0 if lost <= 1e-9 else 0.0

    return {
        "total_load_kwh": total_load,
        "pv_generation_kwh": pv_gen,
        "served_by_pv_kwh": served_by_pv,
        "served_by_batt_kwh": served_by_batt,
        "lost_load_kwh": lost,
        "curtailment_kwh": curtail,
        "self_sufficiency": self_suff,
        "unmet_share": unmet_share,
        "capacity_sufficient_flag": capacity_sufficient,
    }


def main() -> None:
    """CLI entry point for rule-based simulation."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in", dest="inp", type=str, default="data/timeseries.csv", help="Input CSV")
    p.add_argument("--out", type=str, default="outputs/rule_based_dispatch.csv", help="Output CSV")
    p.add_argument("--pv-kw", type=float, default=3.0, help="PV capacity (kW)")
    p.add_argument("--batt-kwh", type=float, default=5.0, help="Battery energy capacity (kWh)")
    p.add_argument("--ch-kw", type=float, default=2.5, help="Battery max charge power (kW)")
    p.add_argument("--dis-kw", type=float, default=2.5, help="Battery max discharge power (kW)")
    p.add_argument("--charge-eff", type=float, default=0.92, help="Charge efficiency (0..1)")
    p.add_argument("--discharge-eff", type=float, default=0.92, help="Discharge efficiency (0..1)")
    p.add_argument("--soc-init", type=float, default=0.5, help="Initial SoC fraction (0..1)")
    args = p.parse_args()

    df = pd.read_csv(args.inp, parse_dates=["timestamp"], index_col="timestamp")
    params = SystemParams(
        pv_capacity_kw=float(args.pv_kw),
        batt_capacity_kwh=float(args.batt_kwh),
        batt_charge_kw=float(args.ch_kw),
        batt_discharge_kw=float(args.dis_kw),
        charge_eff=float(args.charge_eff),
        discharge_eff=float(args.discharge_eff),
        soc_init=float(args.soc_init),
    )

    out = simulate_rule_based(df, params)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index_label="timestamp")

    s = summarize(out)
    print(f"Wrote dispatch to {out_path}")
    print("Summary")
    for k, v in s.items():
        if k.endswith("_kwh"):
            print(f"  {k}: {v:,.2f}")
        else:
            print(f"  {k}: {v:.3f}")

    if s["lost_load_kwh"] > 1e-9:
        print("WARNING: System capacity is insufficient; some demand was unmet.")


if __name__ == "__main__":
    main()
