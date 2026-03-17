"""Linear programming capacity planning and economic dispatch.

This script solves a single optimisation problem over the full time horizon.

Two common uses:
  1) Dispatch only: PV and battery sizes are fixed, and the optimiser chooses
     charge or discharge to minimise unmet-load penalties.
  2) Capacity planning: PV and battery sizes are decision variables, and the
     optimiser trades capital cost against reliability penalties.

Model overview (energy units in kWh per timestep):
  - PV potential is pv_kwh_per_kw[t] * PV_size_kw
  - PV can serve load, charge the battery, or be curtailed
  - Battery state updates with charge and discharge efficiencies
  - Demand must be met by PV direct, battery discharge, or
    optional load shedding (heavily penalised).

Dependencies: PuLP.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from meal_database import candidate_meals, load_meal_database

_VENDOR_DIR = Path(__file__).resolve().parent / ".vendor"
if _VENDOR_DIR.exists():
    vendor_str = str(_VENDOR_DIR)
    if vendor_str not in sys.path:
        sys.path.insert(0, vendor_str)

@dataclass(frozen=True)
class OptParams:
    """Core optimization parameters shared by LP and MILP variants."""
    pv_capex_per_kw: float
    batt_capex_per_kwh: float
    charge_eff: float
    discharge_eff: float
    c_rate_per_h: float
    soc_init_frac: float
    cyclic_soc: bool
    shed_penalty_per_kwh: float


def _validate_params(
    params: OptParams, *, pv_kw_fixed: float | None, batt_kwh_fixed: float | None
) -> None:
    """Validate optimization and optional fixed-size parameters."""
    if not (0.0 <= params.soc_init_frac <= 1.0):
        raise ValueError("soc_init must be between 0 and 1.")
    if not (0.0 <= params.charge_eff <= 1.0):
        raise ValueError("charge_eff must be between 0 and 1.")
    if not (0.0 <= params.discharge_eff <= 1.0):
        raise ValueError("discharge_eff must be between 0 and 1.")
    if params.c_rate_per_h < 0:
        raise ValueError("c_rate must be non-negative.")
    if params.pv_capex_per_kw < 0 or params.batt_capex_per_kwh < 0:
        raise ValueError("capex values must be non-negative.")
    if params.shed_penalty_per_kwh < 0:
        raise ValueError("shed_penalty must be non-negative.")
    if pv_kw_fixed is not None and pv_kw_fixed < 0:
        raise ValueError("pv_kw_fixed must be non-negative.")
    if batt_kwh_fixed is not None and batt_kwh_fixed < 0:
        raise ValueError("batt_kwh_fixed must be non-negative.")


def load_daily_nutrition_targets(path: str | None) -> dict[str, dict[str, float | None]]:
    """Load optional daily nutrient bounds from JSON.

    Expected structure:
      {"daily_targets": {"nutrient_name": {"min": ..., "max": ...}, ...}}
    """
    if not path:
        return {}
    payload = json.loads(Path(path).read_text())
    targets = payload.get("daily_targets", {})
    if not isinstance(targets, dict):
        raise ValueError("daily_targets must be a mapping in the nutrition config.")
    out: dict[str, dict[str, float | None]] = {}
    for nutrient, bounds in targets.items():
        if not isinstance(bounds, dict):
            raise ValueError(f"Bounds for nutrient {nutrient!r} must be an object.")
        lo = bounds.get("min")
        hi = bounds.get("max")
        out[str(nutrient)] = {
            "min": float(lo) if lo is not None else None,
            "max": float(hi) if hi is not None else None,
        }
    return out


def _meal_slots_from_df(df: pd.DataFrame) -> list[dict[str, object]]:
    """Extract unique meal slots and their timestep indices from dataset."""
    if "meal_slot_id" not in df.columns:
        raise ValueError("Dataset must contain meal_slot_id for meal optimization.")
    slots: list[dict[str, object]] = []
    for slot_id in pd.unique(df["meal_slot_id"]):
        sid = str(slot_id)
        if sid == "none":
            continue
        idx = np.where(df["meal_slot_id"].to_numpy(dtype=object) == sid)[0]
        if len(idx) == 0:
            continue
        meal_type = str(df["meal"].iloc[idx[0]]) if "meal" in df.columns else "any"
        day_id = str(df.index[idx[0]].date())
        slots.append(
            {
                "slot_id": sid,
                "meal_type": meal_type,
                "day_id": day_id,
                "timesteps": idx,
            }
        )
    if not slots:
        raise ValueError("No meal slots found. Generate data with meal windows first.")
    return slots


def solve_lp(
    df: pd.DataFrame,
    params: OptParams,
    *,
    pv_kw_fixed: float | None = None,
    batt_kwh_fixed: float | None = None,
    solver_name: str = "PULP_CBC_CMD",
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Solve LP dispatch/sizing and return dispatch dataframe + summary."""

    try:
        import pulp  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "PuLP is required. Install it with: pip install pulp"
        ) from e

    _validate_params(params, pv_kw_fixed=pv_kw_fixed, batt_kwh_fixed=batt_kwh_fixed)

    required = {"pv_kwh_per_kw", "demand_kwh", "dt_hours"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Input dataframe missing columns: {sorted(missing)}")

    dt_h = float(df["dt_hours"].iloc[0])
    if not np.allclose(df["dt_hours"].to_numpy(), dt_h):
        raise ValueError("This simple LP expects constant dt_hours.")
    if dt_h <= 0:
        raise ValueError("dt_hours must be positive.")

    T = len(df)
    pv_per_kw = df["pv_kwh_per_kw"].to_numpy()
    demand = df["demand_kwh"].to_numpy()

    prob = pulp.LpProblem("pv_battery_cooking", pulp.LpMinimize)

    # Size decision variables (become constants when fixed sizes are provided).
    pv_size = pulp.LpVariable("PV_size_kw", lowBound=0)
    batt_size = pulp.LpVariable("Batt_size_kwh", lowBound=0)

    if pv_kw_fixed is not None:
        prob += pv_size == float(pv_kw_fixed)
    if batt_kwh_fixed is not None:
        prob += batt_size == float(batt_kwh_fixed)

    # Per timestep decision variables (kWh per timestep).
    pv_to_load = pulp.LpVariable.dicts("pv_to_load", range(T), lowBound=0)
    pv_to_batt = pulp.LpVariable.dicts("pv_to_batt", range(T), lowBound=0)
    pv_curtail = pulp.LpVariable.dicts("pv_curtail", range(T), lowBound=0)

    batt_discharge = pulp.LpVariable.dicts("batt_discharge", range(T), lowBound=0)
    batt_to_load = pulp.LpVariable.dicts("batt_to_load", range(T), lowBound=0)

    shed = pulp.LpVariable.dicts("shed", range(T), lowBound=0)

    soc = pulp.LpVariable.dicts("soc", range(T + 1), lowBound=0)

    # Initial SoC is a fraction of the chosen battery size.
    prob += soc[0] == params.soc_init_frac * batt_size
    prob += soc[0] <= batt_size

    # Constraints.
    for t in range(T):
        # PV split.
        prob += (
            pv_to_load[t] + pv_to_batt[t] + pv_curtail[t]
            == pv_per_kw[t] * pv_size
        )

        # Demand balance.
        prob += (
            pv_to_load[t] + batt_to_load[t] + shed[t]
            == demand[t]
        )

        # Battery discharge efficiency: delivered = withdrawn * eff.
        prob += batt_to_load[t] == batt_discharge[t] * params.discharge_eff

        # SoC update: soc[t+1] = soc[t] + charged - discharged.
        prob += (
            soc[t + 1]
            == soc[t] + pv_to_batt[t] * params.charge_eff - batt_discharge[t]
        )

        # SoC bounds.
        prob += soc[t + 1] <= batt_size
        prob += soc[t + 1] >= 0

        # Charge or discharge power limit using a single c rate.
        # Pmax = c_rate_per_h * batt_size_kwh (kW). Convert to kWh per step.
        e_rate = params.c_rate_per_h * batt_size * dt_h
        prob += pv_to_batt[t] <= e_rate
        prob += batt_discharge[t] <= e_rate

    if params.cyclic_soc:
        prob += soc[T] == soc[0]

    # Objective.
    capex = params.pv_capex_per_kw * pv_size + params.batt_capex_per_kwh * batt_size
    shed_cost = pulp.lpSum(shed[t] * params.shed_penalty_per_kwh for t in range(T))
    prob += capex + shed_cost

    # Solve.
    solver_cls = getattr(pulp, solver_name, pulp.PULP_CBC_CMD)
    try:
        solver = solver_cls(msg=False)
    except TypeError:  # pragma: no cover
        solver = solver_cls()
    status = prob.solve(solver)
    status_str = pulp.LpStatus.get(status, str(status))
    if status_str not in {"Optimal", "Feasible"}:
        raise RuntimeError(f"LP did not solve to Optimal/Feasible. Status: {status_str}")

    pv_size_val = float(pulp.value(pv_size))
    batt_size_val = float(pulp.value(batt_size))

    # Extract dispatch.
    out = df.copy()
    out["pv_to_load_kwh"] = [float(pulp.value(pv_to_load[t])) for t in range(T)]
    out["pv_to_batt_kwh"] = [float(pulp.value(pv_to_batt[t])) for t in range(T)]
    out["curtail_kwh"] = [float(pulp.value(pv_curtail[t])) for t in range(T)]
    out["batt_discharge_kwh"] = [float(pulp.value(batt_discharge[t])) for t in range(T)]
    out["batt_to_load_kwh"] = [float(pulp.value(batt_to_load[t])) for t in range(T)]
    out["shed_kwh"] = [float(pulp.value(shed[t])) for t in range(T)]
    out["soc_kwh"] = [float(pulp.value(soc[t + 1])) for t in range(T)]
    out["soc_frac"] = np.where(batt_size_val > 0, out["soc_kwh"] / batt_size_val, 0.0)

    # Helpful constants for downstream reporting.
    out["pv_size_kw"] = pv_size_val
    out["batt_size_kwh"] = batt_size_val

    # Derived PV generation.
    out["pv_kwh"] = out["pv_kwh_per_kw"] * pv_size_val

    summary = {
        "status": 1.0,
        "pv_size_kw": pv_size_val,
        "batt_size_kwh": batt_size_val,
        "objective": float(pulp.value(prob.objective)),
        "capex_cost": float(pulp.value(capex)),
        "shed_kwh": float(out["shed_kwh"].sum()),
    }
    return out, summary


def solve_lp_with_meal_optimization(
    df: pd.DataFrame,
    params: OptParams,
    *,
    meal_db_path: str | None = None,
    nutrition_targets: dict[str, dict[str, float | None]] | None = None,
    meal_cost_weight: float = 1.0,
    pv_kw_fixed: float | None = None,
    batt_kwh_fixed: float | None = None,
    solver_name: str = "PULP_CBC_CMD",
) -> tuple[pd.DataFrame, dict[str, float], pd.DataFrame]:
    """Solve joint dispatch + meal-choice MILP and return dispatch, summary, meal plan."""
    try:
        import pulp  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("PuLP is required. Install it with: pip install pulp") from e

    _validate_params(params, pv_kw_fixed=pv_kw_fixed, batt_kwh_fixed=batt_kwh_fixed)
    nutrition_targets = nutrition_targets or {}

    required = {"pv_kwh_per_kw", "dt_hours", "meal_slot_id", "meal"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Input dataframe missing columns for meal optimisation: {sorted(missing)}")

    dt_h = float(df["dt_hours"].iloc[0])
    if not np.allclose(df["dt_hours"].to_numpy(), dt_h):
        raise ValueError("This meal optimisation LP expects constant dt_hours.")
    if dt_h <= 0:
        raise ValueError("dt_hours must be positive.")

    T = len(df)
    pv_per_kw = df["pv_kwh_per_kw"].to_numpy(dtype=float)
    base_demand = (
        df["demand_kwh"].to_numpy(dtype=float)
        if "demand_kwh" in df.columns
        else np.zeros(T, dtype=float)
    )
    slots = _meal_slots_from_df(df)
    meal_db = load_meal_database(meal_db_path)

    prob = pulp.LpProblem("pv_battery_cooking_meal_choice", pulp.LpMinimize)

    pv_size = pulp.LpVariable("PV_size_kw", lowBound=0)
    batt_size = pulp.LpVariable("Batt_size_kwh", lowBound=0)
    if pv_kw_fixed is not None:
        prob += pv_size == float(pv_kw_fixed)
    if batt_kwh_fixed is not None:
        prob += batt_size == float(batt_kwh_fixed)

    pv_to_load = pulp.LpVariable.dicts("pv_to_load", range(T), lowBound=0)
    pv_to_batt = pulp.LpVariable.dicts("pv_to_batt", range(T), lowBound=0)
    pv_curtail = pulp.LpVariable.dicts("pv_curtail", range(T), lowBound=0)
    batt_discharge = pulp.LpVariable.dicts("batt_discharge", range(T), lowBound=0)
    batt_to_load = pulp.LpVariable.dicts("batt_to_load", range(T), lowBound=0)
    shed = pulp.LpVariable.dicts("shed", range(T), lowBound=0)
    soc = pulp.LpVariable.dicts("soc", range(T + 1), lowBound=0)

    prob += soc[0] == params.soc_init_frac * batt_size
    prob += soc[0] <= batt_size

    # Mark timesteps that belong to meal slots; base demand outside slots is fixed.
    in_slot = np.zeros(T, dtype=bool)
    for slot in slots:
        in_slot[np.array(slot["timesteps"], dtype=int)] = True

    demand_expr: list[object] = [float(base_demand[t]) if not in_slot[t] else 0.0 for t in range(T)]
    meal_choice_rows: list[dict[str, object]] = []
    meal_cost_terms: list[object] = []
    nutrient_day_terms: dict[str, dict[str, list[object]]] = {}

    # Create binary meal-choice variables per slot and inject chosen meal energy into demand.
    for s_idx, slot in enumerate(slots):
        meal_type = str(slot["meal_type"])
        day_id = str(slot["day_id"])
        timesteps = np.array(slot["timesteps"], dtype=int)
        candidates = candidate_meals(meal_db, meal_type)
        choose_vars: list[tuple[object, pd.Series]] = []
        for _, row in candidates.iterrows():
            meal_var_name = str(row["meal_id"]).replace("-", "_")
            v = pulp.LpVariable(f"choose_{s_idx}_{meal_var_name}", cat="Binary")
            choose_vars.append((v, row))

            per_step_kwh = float(row["cook_energy_kwh"]) / max(1, len(timesteps))
            for t in timesteps:
                demand_expr[t] = demand_expr[t] + per_step_kwh * v
            meal_cost_terms.append(v * float(row["meal_cost_usd"]))

            for nutrient in nutrition_targets.keys():
                if nutrient not in row.index:
                    continue
                nutrient_day_terms.setdefault(day_id, {}).setdefault(nutrient, []).append(
                    v * float(row[nutrient])
                )

        prob += pulp.lpSum(v for v, _ in choose_vars) == 1
        meal_choice_rows.append(
            {
                "slot_id": str(slot["slot_id"]),
                "day_id": day_id,
                "meal_type": meal_type,
                "timesteps": timesteps,
                "choices": choose_vars,
            }
        )

    # Apply optional daily nutrition bounds.
    for day_id, by_nutrient in nutrient_day_terms.items():
        for nutrient, terms in by_nutrient.items():
            lo = nutrition_targets.get(nutrient, {}).get("min")
            hi = nutrition_targets.get(nutrient, {}).get("max")
            total_expr = pulp.lpSum(terms)
            if lo is not None:
                prob += total_expr >= float(lo)
            if hi is not None:
                prob += total_expr <= float(hi)

    for t in range(T):
        prob += pv_to_load[t] + pv_to_batt[t] + pv_curtail[t] == pv_per_kw[t] * pv_size
        prob += pv_to_load[t] + batt_to_load[t] + shed[t] == demand_expr[t]
        prob += batt_to_load[t] == batt_discharge[t] * params.discharge_eff
        prob += soc[t + 1] == soc[t] + pv_to_batt[t] * params.charge_eff - batt_discharge[t]
        prob += soc[t + 1] <= batt_size
        prob += soc[t + 1] >= 0

        e_rate = params.c_rate_per_h * batt_size * dt_h
        prob += pv_to_batt[t] <= e_rate
        prob += batt_discharge[t] <= e_rate
    if params.cyclic_soc:
        prob += soc[T] == soc[0]

    capex = params.pv_capex_per_kw * pv_size + params.batt_capex_per_kwh * batt_size
    shed_cost = pulp.lpSum(shed[t] * params.shed_penalty_per_kwh for t in range(T))
    meal_cost = pulp.lpSum(meal_cost_terms) * float(meal_cost_weight)
    prob += capex + shed_cost + meal_cost

    solver_cls = getattr(pulp, solver_name, pulp.PULP_CBC_CMD)
    try:
        solver = solver_cls(msg=False)
    except TypeError:  # pragma: no cover
        solver = solver_cls()
    status = prob.solve(solver)
    status_str = pulp.LpStatus.get(status, str(status))
    if status_str not in {"Optimal", "Feasible"}:
        raise RuntimeError(f"LP meal optimisation not Optimal/Feasible. Status: {status_str}")

    pv_size_val = float(pulp.value(pv_size))
    batt_size_val = float(pulp.value(batt_size))
    optimized_demand = np.array([float(pulp.value(demand_expr[t])) for t in range(T)], dtype=float)

    out = df.copy()
    out["demand_kwh"] = optimized_demand
    out["pv_to_load_kwh"] = [float(pulp.value(pv_to_load[t])) for t in range(T)]
    out["pv_to_batt_kwh"] = [float(pulp.value(pv_to_batt[t])) for t in range(T)]
    out["curtail_kwh"] = [float(pulp.value(pv_curtail[t])) for t in range(T)]
    out["batt_discharge_kwh"] = [float(pulp.value(batt_discharge[t])) for t in range(T)]
    out["batt_to_load_kwh"] = [float(pulp.value(batt_to_load[t])) for t in range(T)]
    out["shed_kwh"] = [float(pulp.value(shed[t])) for t in range(T)]
    out["soc_kwh"] = [float(pulp.value(soc[t + 1])) for t in range(T)]
    out["soc_frac"] = np.where(batt_size_val > 0, out["soc_kwh"] / batt_size_val, 0.0)
    out["pv_size_kw"] = pv_size_val
    out["batt_size_kwh"] = batt_size_val
    out["pv_kwh"] = out["pv_kwh_per_kw"] * pv_size_val

    # Materialize selected meals back to per-timestep table for reporting/plots.
    chosen_meal_id = np.full(T, "none", dtype=object)
    chosen_meal_name = np.full(T, "none", dtype=object)
    chosen_meal_type = np.full(T, "none", dtype=object)
    chosen_meal_cost_step = np.zeros(T, dtype=float)
    chosen_meal_cost_slot = np.zeros(T, dtype=float)
    chosen_calories = np.zeros(T, dtype=float)
    chosen_protein = np.zeros(T, dtype=float)
    chosen_fiber = np.zeros(T, dtype=float)
    chosen_micronutrient = np.zeros(T, dtype=float)
    meal_plan_rows: list[dict[str, object]] = []
    for slot in meal_choice_rows:
        selected = None
        for v, row in slot["choices"]:
            if float(pulp.value(v)) > 0.5:
                selected = row
                break
        if selected is None:
            selected = slot["choices"][0][1]
        idx = np.array(slot["timesteps"], dtype=int)
        chosen_meal_id[idx] = str(selected["meal_id"])
        chosen_meal_name[idx] = str(selected["meal_name"])
        chosen_meal_type[idx] = str(slot["meal_type"])
        slot_cost = float(selected["meal_cost_usd"])
        chosen_meal_cost_step[idx] = slot_cost / max(1, len(idx))
        chosen_meal_cost_slot[idx] = slot_cost
        chosen_calories[idx] = float(selected.get("calories_kcal", 0.0))
        chosen_protein[idx] = float(selected.get("protein_g", 0.0))
        chosen_fiber[idx] = float(selected.get("fiber_g", 0.0))
        chosen_micronutrient[idx] = float(selected.get("micronutrient_score", 0.0))
        meal_plan_rows.append(
            {
                "slot_id": slot["slot_id"],
                "day_id": slot["day_id"],
                "meal_type": slot["meal_type"],
                "meal_id": str(selected["meal_id"]),
                "meal_name": str(selected["meal_name"]),
                "cook_energy_kwh": float(selected["cook_energy_kwh"]),
                "meal_cost_usd": float(selected["meal_cost_usd"]),
                "calories_kcal": float(selected.get("calories_kcal", 0.0)),
                "protein_g": float(selected.get("protein_g", 0.0)),
                "fiber_g": float(selected.get("fiber_g", 0.0)),
                "micronutrient_score": float(selected.get("micronutrient_score", 0.0)),
            }
        )
    out["chosen_meal_id"] = chosen_meal_id
    out["chosen_meal_name"] = chosen_meal_name
    out["meal_slot_id"] = out["meal_slot_id"] if "meal_slot_id" in out.columns else "none"
    out["meal"] = out["meal"] if "meal" in out.columns else chosen_meal_type
    out["meal_id"] = chosen_meal_id
    out["meal_name"] = chosen_meal_name
    out["meal_type"] = chosen_meal_type
    out["meal_cost_usd"] = chosen_meal_cost_slot
    out["meal_cost_usd_per_step"] = chosen_meal_cost_step
    out["calories_kcal"] = chosen_calories
    out["protein_g"] = chosen_protein
    out["fiber_g"] = chosen_fiber
    out["micronutrient_score"] = chosen_micronutrient

    meal_plan = pd.DataFrame(meal_plan_rows)
    summary = {
        "status": 1.0,
        "pv_size_kw": pv_size_val,
        "batt_size_kwh": batt_size_val,
        "objective": float(pulp.value(prob.objective)),
        "capex_cost": float(pulp.value(capex)),
        "shed_kwh": float(out["shed_kwh"].sum()),
        "meal_cost": float(meal_plan["meal_cost_usd"].sum()) if not meal_plan.empty else 0.0,
        "daily_calories_kcal": float(meal_plan["calories_kcal"].sum()) if not meal_plan.empty else 0.0,
        "daily_protein_g": float(meal_plan["protein_g"].sum()) if not meal_plan.empty else 0.0,
        "daily_fiber_g": float(meal_plan["fiber_g"].sum()) if not meal_plan.empty else 0.0,
    }
    return out, summary, meal_plan


def main() -> None:
    """CLI entry point for LP/MILP optimization."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in", dest="inp", type=str, default="data/timeseries.csv", help="Input CSV")
    p.add_argument(
        "--out",
        type=str,
        default="outputs/lp_dispatch.csv",
        help="Output CSV with dispatch and SoC",
    )

    # Capacity planning parameters.
    p.add_argument("--pv-capex", type=float, default=900.0, help="PV capex (cost per kW)")
    p.add_argument(
        "--batt-capex", type=float, default=500.0, help="Battery capex (cost per kWh)"
    )
    p.add_argument("--charge-eff", type=float, default=0.92, help="Charge efficiency (0..1)")
    p.add_argument(
        "--discharge-eff", type=float, default=0.92, help="Discharge efficiency (0..1)"
    )
    p.add_argument(
        "--c-rate",
        type=float,
        default=0.5,
        help="Battery C rate (1/h). 0.5 means 2 hour full charge or discharge",
    )
    p.add_argument("--soc-init", type=float, default=0.5, help="Initial SoC fraction (0..1)")
    p.add_argument("--cyclic-soc", action="store_true", help="Enforce soc_end == soc_start")
    p.add_argument(
        "--shed-penalty",
        type=float,
        default=10_000.0,
        help="Penalty per kWh of unmet load (keeps meals cooked)",
    )

    # Optional fixed sizes.
    p.add_argument("--pv-kw-fixed", type=float, default=None, help="Fix PV size (kW)")
    p.add_argument("--batt-kwh-fixed", type=float, default=None, help="Fix battery size (kWh)")
    p.add_argument(
        "--optimize-meals",
        action="store_true",
        help="Optimise meal choices from a meal database jointly with dispatch and sizing.",
    )
    p.add_argument(
        "--meal-db",
        type=str,
        default="data/reference/meal_database.csv",
        help="Meal database CSV path used with --optimize-meals",
    )
    p.add_argument(
        "--nutrition-targets",
        type=str,
        default="configs/meal_targets.json",
        help="JSON file with daily nutrition bounds used with --optimize-meals",
    )
    p.add_argument(
        "--meal-cost-weight",
        type=float,
        default=1.0,
        help="Weight applied to meal monetary cost in the LP objective.",
    )
    p.add_argument(
        "--meal-plan-out",
        type=str,
        default="outputs/meal_plan_optimized.csv",
        help="Output CSV for selected meals when --optimize-meals is used.",
    )
    p.add_argument(
        "--solver",
        type=str,
        default="PULP_CBC_CMD",
        help="PuLP solver class name (default uses CBC)",
    )
    args = p.parse_args()

    df = pd.read_csv(args.inp, parse_dates=["timestamp"], index_col="timestamp")
    params = OptParams(
        pv_capex_per_kw=float(args.pv_capex),
        batt_capex_per_kwh=float(args.batt_capex),
        charge_eff=float(args.charge_eff),
        discharge_eff=float(args.discharge_eff),
        c_rate_per_h=float(args.c_rate),
        soc_init_frac=float(args.soc_init),
        cyclic_soc=bool(args.cyclic_soc),
        shed_penalty_per_kwh=float(args.shed_penalty),
    )

    if args.optimize_meals:
        nutrition_targets = load_daily_nutrition_targets(args.nutrition_targets)
        out, summary, meal_plan = solve_lp_with_meal_optimization(
            df,
            params,
            meal_db_path=args.meal_db,
            nutrition_targets=nutrition_targets,
            meal_cost_weight=float(args.meal_cost_weight),
            pv_kw_fixed=args.pv_kw_fixed,
            batt_kwh_fixed=args.batt_kwh_fixed,
            solver_name=args.solver,
        )
    else:
        out, summary = solve_lp(
            df,
            params,
            pv_kw_fixed=args.pv_kw_fixed,
            batt_kwh_fixed=args.batt_kwh_fixed,
            solver_name=args.solver,
        )
        meal_plan = None

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index_label="timestamp")

    if meal_plan is not None:
        meal_plan_path = Path(args.meal_plan_out)
        meal_plan_path.parent.mkdir(parents=True, exist_ok=True)
        meal_plan.to_csv(meal_plan_path, index=False)

    print(f"Wrote LP dispatch to {out_path}")
    if meal_plan is not None:
        print(f"Wrote meal plan to {meal_plan_path}")
    print("Sizes")
    print(f"  PV_size_kw: {summary['pv_size_kw']:.3f}")
    print(f"  Batt_size_kwh: {summary['batt_size_kwh']:.3f}")
    print("Costs over horizon")
    print(f"  capex_cost: {summary['capex_cost']:.2f}")
    print(f"  shed_kwh: {summary['shed_kwh']:.6f}")
    if meal_plan is not None:
        print(f"  meal_cost: {summary['meal_cost']:.2f}")
        print(f"  daily_calories_kcal: {summary['daily_calories_kcal']:.2f}")
        print(f"  daily_protein_g: {summary['daily_protein_g']:.2f}")


if __name__ == "__main__":
    main()
