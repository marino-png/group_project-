"""Compare rule-based and LP dispatch costs on the same meal time series."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def _col_or_zeros(df: pd.DataFrame, col: str) -> np.ndarray:
    """Return numeric column values or a zero vector when column is absent."""
    if col in df.columns:
        return df[col].to_numpy(dtype=float)
    return np.zeros(len(df), dtype=float)


def compute_dispatch_cost(
    dispatch: pd.DataFrame,
    *,
    pv_capex_per_kw: float = 0.0,
    batt_capex_per_kwh: float = 0.0,
    unmet_penalty_per_kwh: float = 10_000.0,
    curtail_penalty_per_kwh: float = 0.0,
    include_meal_cost: bool = True,
) -> dict[str, float]:
    """Compute a compact cost breakdown for one dispatch dataframe.

    Dispatch outputs from rule and LP have slightly different optional columns.
    This helper normalizes them into one consistent economic summary.
    """
    if len(dispatch) == 0:
        raise ValueError("Dispatch dataframe is empty.")

    shed = _col_or_zeros(dispatch, "shed_kwh")
    lost = _col_or_zeros(dispatch, "lost_load_kwh")
    curtail = _col_or_zeros(dispatch, "curtail_kwh")

    pv_size = float(dispatch["pv_size_kw"].iloc[0]) if "pv_size_kw" in dispatch.columns else 0.0
    batt_size = float(dispatch["batt_size_kwh"].iloc[0]) if "batt_size_kwh" in dispatch.columns else 0.0

    unmet_kwh = float((shed + lost).sum())
    unmet_cost = unmet_kwh * float(unmet_penalty_per_kwh)
    curtail_cost = float(curtail.sum()) * float(curtail_penalty_per_kwh)
    capex_cost = pv_size * float(pv_capex_per_kw) + batt_size * float(batt_capex_per_kwh)
    if include_meal_cost and "meal_cost_usd_per_step" in dispatch.columns:
        meal_cost = float(dispatch["meal_cost_usd_per_step"].sum())
    elif include_meal_cost and "chosen_meal_cost_usd" in dispatch.columns:
        meal_cost = float(dispatch["chosen_meal_cost_usd"].sum())
    else:
        meal_cost = 0.0
    total_cost = capex_cost + unmet_cost + curtail_cost + meal_cost

    return {
        "pv_size_kw": pv_size,
        "batt_size_kwh": batt_size,
        "unmet_kwh": unmet_kwh,
        "curtail_kwh": float(curtail.sum()),
        "capex_cost": capex_cost,
        "unmet_cost": unmet_cost,
        "curtail_cost": curtail_cost,
        "meal_cost": meal_cost,
        "total_cost": total_cost,
    }


def compare_dispatch_costs(
    rule_dispatch: pd.DataFrame,
    lp_dispatch: pd.DataFrame,
    *,
    pv_capex_per_kw: float = 0.0,
    batt_capex_per_kwh: float = 0.0,
    unmet_penalty_per_kwh: float = 10_000.0,
    curtail_penalty_per_kwh: float = 0.0,
    include_meal_cost: bool = True,
) -> pd.DataFrame:
    """Return side-by-side rule/LP cost rows plus an LP-minus-rule delta row."""
    rule_cost = compute_dispatch_cost(
        rule_dispatch,
        pv_capex_per_kw=pv_capex_per_kw,
        batt_capex_per_kwh=batt_capex_per_kwh,
        unmet_penalty_per_kwh=unmet_penalty_per_kwh,
        curtail_penalty_per_kwh=curtail_penalty_per_kwh,
        include_meal_cost=include_meal_cost,
    )
    lp_cost = compute_dispatch_cost(
        lp_dispatch,
        pv_capex_per_kw=pv_capex_per_kw,
        batt_capex_per_kwh=batt_capex_per_kwh,
        unmet_penalty_per_kwh=unmet_penalty_per_kwh,
        curtail_penalty_per_kwh=curtail_penalty_per_kwh,
        include_meal_cost=include_meal_cost,
    )

    table = pd.DataFrame([rule_cost, lp_cost], index=["rule", "lp"])
    table.loc["lp_minus_rule"] = table.loc["lp"] - table.loc["rule"]
    return table


def main() -> None:
    """CLI entry point for one-shot CSV cost comparison."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rule", required=True, help="Rule-based dispatch CSV")
    p.add_argument("--lp", required=True, help="LP dispatch CSV")
    p.add_argument("--out", default="outputs/cost_comparison.csv", help="Output comparison CSV")
    p.add_argument("--pv-capex", type=float, default=0.0, help="Cost per kW of PV")
    p.add_argument("--batt-capex", type=float, default=0.0, help="Cost per kWh of battery")
    p.add_argument(
        "--unmet-penalty",
        type=float,
        default=10_000.0,
        help="Penalty per kWh of unmet demand",
    )
    p.add_argument(
        "--curtail-penalty",
        type=float,
        default=0.0,
        help="Penalty per kWh of curtailed PV",
    )
    p.add_argument(
        "--exclude-meal-cost",
        action="store_true",
        help="Ignore meal monetary cost columns even if present in dispatch files.",
    )
    args = p.parse_args()

    rule = pd.read_csv(args.rule, parse_dates=["timestamp"], index_col="timestamp")
    lp = pd.read_csv(args.lp, parse_dates=["timestamp"], index_col="timestamp")
    comp = compare_dispatch_costs(
        rule,
        lp,
        pv_capex_per_kw=float(args.pv_capex),
        batt_capex_per_kwh=float(args.batt_capex),
        unmet_penalty_per_kwh=float(args.unmet_penalty),
        curtail_penalty_per_kwh=float(args.curtail_penalty),
        include_meal_cost=not bool(args.exclude_meal_cost),
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    comp.to_csv(out_path, index_label="case")
    print(f"Wrote cost comparison to {out_path}")
    print(comp.to_string(float_format=lambda x: f"{x:,.4f}"))


if __name__ == "__main__":
    main()
