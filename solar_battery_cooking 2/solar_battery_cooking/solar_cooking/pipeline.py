"""High-level pipeline helpers for rule and LP runs."""

from __future__ import annotations

from pathlib import Path

from data_generator import build_dataset
from lp_optimization import (
    OptParams,
    load_daily_nutrition_targets,
    solve_lp,
    solve_lp_with_meal_optimization,
)
from rule_based_sim import SystemParams, simulate_rule_based, summarize
from visualize import compute_metrics, plot_daily_meal_summary, plot_daily_power_flows, plot_dispatch

from .models import GenerationConfig, LPConfig, RuleConfig, RunArtifacts


def _ensure_dir(path: Path) -> None:
    """Create directory (and parents) if missing."""
    path.mkdir(parents=True, exist_ok=True)


def _build_dataset(gen_cfg: GenerationConfig):
    """Build scenario dataframe from a typed generation config."""
    return build_dataset(
        start=gen_cfg.start,
        days=gen_cfg.days,
        dt_minutes=gen_cfg.dt_minutes,
        seed=gen_cfg.seed,
        solar_profile_model=gen_cfg.solar_profile_model,
        location_name=gen_cfg.location_name,
        location_profiles_path=gen_cfg.location_profiles_path,
        latitude_deg=gen_cfg.latitude_deg,
        longitude_deg=gen_cfg.longitude_deg,
        pv_tilt_deg=gen_cfg.pv_tilt_deg,
        pv_azimuth_deg=gen_cfg.pv_azimuth_deg,
        weather_profile_mode=gen_cfg.weather_profile_mode,
        weather_profile_path=gen_cfg.weather_profile_path,
        latitude_hint=gen_cfg.latitude_hint,
        p_cold=gen_cfg.p_cold,
        p_medium=gen_cfg.p_medium,
        p_high=gen_cfg.p_high,
        meal_mode=gen_cfg.meal_mode,
        meal_db_path=gen_cfg.meal_db_path,
        solar_day=gen_cfg.solar_day,
        solar_day_seq=gen_cfg.solar_day_seq,
        solar_conditions_path=gen_cfg.solar_conditions_path,
    )


def run_rule_case(
    *,
    gen_cfg: GenerationConfig,
    rule_cfg: RuleConfig,
    outdir: str | Path = "outputs/main_rule",
    prefix: str = "rule",
) -> tuple[RunArtifacts, dict[str, float], dict[str, float]]:
    """Run end-to-end rule workflow: generate data, simulate, save, and plot."""
    outdir = Path(outdir)
    fig_dir = outdir / "figures"
    _ensure_dir(outdir)
    _ensure_dir(fig_dir)

    # 1) Build synthetic scenario.
    df = _build_dataset(gen_cfg)
    data_csv = outdir / f"{prefix}_timeseries.csv"
    df.to_csv(data_csv, index_label="timestamp")

    # 2) Run rule-based dispatch.
    sim = simulate_rule_based(
        df,
        SystemParams(
            pv_capacity_kw=rule_cfg.pv_kw,
            batt_capacity_kwh=rule_cfg.batt_kwh,
            batt_charge_kw=rule_cfg.ch_kw,
            batt_discharge_kw=rule_cfg.dis_kw,
            charge_eff=rule_cfg.charge_eff,
            discharge_eff=rule_cfg.discharge_eff,
            soc_init=rule_cfg.soc_init,
        ),
    )
    dispatch_csv = outdir / f"{prefix}_dispatch.csv"
    sim.to_csv(dispatch_csv, index_label="timestamp")

    # 3) Produce standard figures.
    plot_dispatch(sim, outdir=fig_dir, prefix=prefix)
    plot_daily_power_flows(sim, outdir=fig_dir, prefix=prefix)
    plot_daily_meal_summary(sim, outdir=fig_dir, prefix=prefix)

    artifacts = RunArtifacts(
        data_csv=data_csv,
        dispatch_csv=dispatch_csv,
        outdir=outdir,
        prefix=prefix,
    )
    return artifacts, summarize(sim), compute_metrics(sim)


def run_lp_case(
    *,
    gen_cfg: GenerationConfig,
    lp_cfg: LPConfig,
    outdir: str | Path = "outputs/main_lp",
    prefix: str = "lp",
) -> tuple[RunArtifacts, dict[str, float], dict[str, float]]:
    """Run end-to-end LP workflow: generate data, optimize, save, and plot."""
    outdir = Path(outdir)
    fig_dir = outdir / "figures"
    _ensure_dir(outdir)
    _ensure_dir(fig_dir)

    # 1) Build synthetic scenario.
    df = _build_dataset(gen_cfg)
    data_csv = outdir / f"{prefix}_timeseries.csv"
    df.to_csv(data_csv, index_label="timestamp")

    # 2) Map user-facing LP config to solver parameter object.
    params = OptParams(
        pv_capex_per_kw=lp_cfg.pv_capex,
        batt_capex_per_kwh=lp_cfg.batt_capex,
        charge_eff=lp_cfg.charge_eff,
        discharge_eff=lp_cfg.discharge_eff,
        c_rate_per_h=lp_cfg.c_rate,
        soc_init_frac=lp_cfg.soc_init,
        cyclic_soc=lp_cfg.cyclic_soc,
        shed_penalty_per_kwh=lp_cfg.shed_penalty,
    )

    meal_plan_csv: Path | None = None
    # 3) Solve by selected LP mode.
    if lp_cfg.mode == "meal_opt":
        nutrition = load_daily_nutrition_targets(lp_cfg.nutrition_targets_path)
        out, summary, meal_plan = solve_lp_with_meal_optimization(
            df,
            params,
            meal_db_path=lp_cfg.meal_db_path,
            nutrition_targets=nutrition,
            meal_cost_weight=lp_cfg.meal_cost_weight,
            pv_kw_fixed=lp_cfg.pv_kw_fixed,
            batt_kwh_fixed=lp_cfg.batt_kwh_fixed,
            solver_name=lp_cfg.solver,
        )
        meal_plan_csv = outdir / f"{prefix}_meal_plan.csv"
        meal_plan.to_csv(meal_plan_csv, index=False)
    elif lp_cfg.mode == "plan":
        out, summary = solve_lp(
            df,
            params,
            pv_kw_fixed=None,
            batt_kwh_fixed=None,
            solver_name=lp_cfg.solver,
        )
    else:  # fixed
        out, summary = solve_lp(
            df,
            params,
            pv_kw_fixed=lp_cfg.pv_kw_fixed,
            batt_kwh_fixed=lp_cfg.batt_kwh_fixed,
            solver_name=lp_cfg.solver,
        )

    dispatch_csv = outdir / f"{prefix}_dispatch.csv"
    out.to_csv(dispatch_csv, index_label="timestamp")

    # 4) Produce standard figures.
    plot_dispatch(out, outdir=fig_dir, prefix=prefix)
    plot_daily_power_flows(out, outdir=fig_dir, prefix=prefix)
    plot_daily_meal_summary(out, outdir=fig_dir, prefix=prefix)

    artifacts = RunArtifacts(
        data_csv=data_csv,
        dispatch_csv=dispatch_csv,
        outdir=outdir,
        prefix=prefix,
        meal_plan_csv=meal_plan_csv,
    )
    return artifacts, summary, compute_metrics(out)
