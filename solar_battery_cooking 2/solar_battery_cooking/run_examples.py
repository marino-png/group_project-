"""Run a few end to end examples.

This script produces:
  - synthetic demand and PV data (1 day, 15 minute steps)
  - rule based simulation outputs
  - LP economic dispatch outputs (fixed sizes)
  - LP meal-choice optimisation outputs
  - LP capacity planning outputs (sizes optimised)
  - rule vs LP cost comparison on the same meal series
  - plots for quick inspection

It is intended as a smoke test and a convenient way to generate example output
files for a report or demo.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from compare_costs import compare_dispatch_costs
from data_generator import build_dataset
from lp_optimization import (
    OptParams,
    load_daily_nutrition_targets,
    solve_lp,
    solve_lp_with_meal_optimization,
)
from rule_based_sim import SystemParams, simulate_rule_based
from visualize import plot_daily_meal_summary, plot_daily_power_flows, plot_dispatch


def main() -> None:
    """Run a compact end-to-end benchmark pipeline and write example artifacts."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--solar-day", type=str, default="mixed", help="Solar day condition preset.")
    p.add_argument(
        "--solar-day-seq",
        type=str,
        default=None,
        help="Optional comma-separated sequence of solar day conditions.",
    )
    p.add_argument(
        "--meal-db",
        type=str,
        default="data/reference/meal_database.csv",
        help="Meal database path.",
    )
    p.add_argument(
        "--nutrition-targets",
        type=str,
        default="configs/meal_targets.json",
        help="Daily nutrition target JSON for meal optimisation.",
    )
    args = p.parse_args()

    base = Path(__file__).resolve().parent
    data_dir = base / "data"
    out_dir = base / "outputs"
    fig_dir = base / "figures"
    data_dir.mkdir(exist_ok=True)
    out_dir.mkdir(exist_ok=True)
    fig_dir.mkdir(exist_ok=True)

    # Test case: 1 day, 15 minute steps.
    df_15m = build_dataset(
        start="2026-01-01",
        days=1,
        dt_minutes=15,
        seed=10,
        latitude_hint="temperate",
        p_cold=0.25,
        p_medium=0.50,
        p_high=0.25,
        meal_mode="db",
        meal_db_path=args.meal_db,
        solar_day=args.solar_day,
        solar_day_seq=args.solar_day_seq,
        solar_conditions_path="data/reference/solar_day_conditions.csv",
    )
    df_15m.to_csv(data_dir / "timeseries.csv", index_label="timestamp")
    df_15m.to_csv(data_dir / "timeseries_1d_15m.csv", index_label="timestamp")

    # Shared fixed-size scenario for rule vs LP comparisons.
    scenario = dict(name="test", pv_kw=4.0, batt_kwh=8.0, p_kw=3.0)

    params = SystemParams(
        pv_capacity_kw=scenario["pv_kw"],
        batt_capacity_kwh=scenario["batt_kwh"],
        batt_charge_kw=scenario["p_kw"],
        batt_discharge_kw=scenario["p_kw"],
        charge_eff=0.92,
        discharge_eff=0.92,
        soc_init=0.5,
    )
    rb = simulate_rule_based(df_15m, params)
    rb_path = out_dir / "rule_based_dispatch.csv"
    rb.to_csv(rb_path, index_label="timestamp")
    plot_dispatch(rb, outdir=fig_dir, prefix="rule")
    plot_daily_power_flows(rb, outdir=fig_dir, prefix="rule")
    plot_daily_meal_summary(rb, outdir=fig_dir, prefix="rule")

    # LP dispatch with fixed sizes.
    opt_params = OptParams(
        pv_capex_per_kw=0.0,  # capex not used when dispatching fixed sizes
        batt_capex_per_kwh=0.0,
        charge_eff=0.92,
        discharge_eff=0.92,
        c_rate_per_h=0.5,
        soc_init_frac=0.5,
        cyclic_soc=True,
        shed_penalty_per_kwh=10_000.0,
    )
    lp, _ = solve_lp(
        df_15m,
        opt_params,
        pv_kw_fixed=scenario["pv_kw"],
        batt_kwh_fixed=scenario["batt_kwh"],
    )
    lp_path = out_dir / "lp_dispatch_fixed_sizes.csv"
    lp.to_csv(lp_path, index_label="timestamp")
    plot_dispatch(lp, outdir=fig_dir, prefix="lp_fixed")
    plot_daily_power_flows(lp, outdir=fig_dir, prefix="lp_fixed")
    plot_daily_meal_summary(lp, outdir=fig_dir, prefix="lp_fixed")

    # Joint meal + dispatch optimization.
    nutrition_targets = load_daily_nutrition_targets(args.nutrition_targets)
    lp_meal, meal_summary, meal_plan = solve_lp_with_meal_optimization(
        df_15m,
        opt_params,
        meal_db_path=args.meal_db,
        nutrition_targets=nutrition_targets,
        meal_cost_weight=1.0,
        pv_kw_fixed=scenario["pv_kw"],
        batt_kwh_fixed=scenario["batt_kwh"],
    )
    lp_meal_path = out_dir / "lp_dispatch_meal_optimized.csv"
    lp_meal_plan_path = out_dir / "lp_meal_plan_optimized.csv"
    lp_meal.to_csv(lp_meal_path, index_label="timestamp")
    meal_plan.to_csv(lp_meal_plan_path, index=False)
    plot_dispatch(lp_meal, outdir=fig_dir, prefix="lp_meal")
    plot_daily_power_flows(lp_meal, outdir=fig_dir, prefix="lp_meal")
    plot_daily_meal_summary(lp_meal, outdir=fig_dir, prefix="lp_meal")

    # LP capacity planning on the same 1-day case.
    plan_params = OptParams(
        pv_capex_per_kw=25.0,
        batt_capex_per_kwh=18.0,
        charge_eff=0.92,
        discharge_eff=0.92,
        c_rate_per_h=0.5,
        soc_init_frac=0.5,
        cyclic_soc=True,
        shed_penalty_per_kwh=10_000.0,
    )
    lp_plan, plan_summary = solve_lp(df_15m, plan_params)
    plan_path = out_dir / "lp_capacity_planning.csv"
    lp_plan.to_csv(plan_path, index_label="timestamp")
    plot_dispatch(lp_plan, outdir=fig_dir, prefix="lp_plan")
    plot_daily_power_flows(lp_plan, outdir=fig_dir, prefix="lp_plan")
    plot_daily_meal_summary(lp_plan, outdir=fig_dir, prefix="lp_plan")

    # Cost model comparison on the same generated day.
    comp = compare_dispatch_costs(rb, lp)
    comp_path = out_dir / "cost_comparison_rule_vs_lp.csv"
    comp.to_csv(comp_path, index_label="case")
    comp_meal = compare_dispatch_costs(rb, lp_meal)
    comp_meal_path = out_dir / "cost_comparison_rule_vs_lp_meal_opt.csv"
    comp_meal.to_csv(comp_meal_path, index_label="case")

    # Write tiny one line summary files for quick reference.
    (out_dir / "lp_capacity_planning_summary.txt").write_text(
        f"PV_size_kw={plan_summary['pv_size_kw']:.3f}, Batt_size_kwh={plan_summary['batt_size_kwh']:.3f}\n"
    )
    (out_dir / "cost_comparison_rule_vs_lp_summary.txt").write_text(
        f"rule_total_cost={comp.loc['rule', 'total_cost']:.6f}, lp_total_cost={comp.loc['lp', 'total_cost']:.6f}, lp_minus_rule={comp.loc['lp_minus_rule', 'total_cost']:.6f}\n"
    )
    (out_dir / "lp_meal_optimized_summary.txt").write_text(
        f"meal_cost={meal_summary['meal_cost']:.6f}, daily_calories_kcal={meal_summary['daily_calories_kcal']:.2f}, daily_protein_g={meal_summary['daily_protein_g']:.2f}\n"
    )

    print("Done.")
    print(f"Data in: {data_dir}")
    print(f"Outputs in: {out_dir}")
    print(f"Figures in: {fig_dir}")


if __name__ == "__main__":
    main()
