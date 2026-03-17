"""Minimal entry point for modular project runs.

Examples:
  python main.py rule
  python main.py lp
  python main.py lp --mode meal_opt
  python main.py rule --config configs/main_params.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from solar_cooking import GenerationConfig, LPConfig, RuleConfig, run_lp_case, run_rule_case


def _add_generation_args(p: argparse.ArgumentParser) -> None:
    """Attach shared data-generation arguments to a subcommand parser."""
    p.add_argument("--start", type=str, default=None)
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--dt-min", dest="dt_minutes", type=int, default=None)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument(
        "--solar-profile-model",
        type=str,
        default=None,
        choices=["synthetic", "suspos"],
    )
    p.add_argument("--location-name", type=str, default=None)
    p.add_argument("--location-profiles-path", type=str, default=None)
    p.add_argument("--latitude-deg", type=float, default=None)
    p.add_argument("--longitude-deg", type=float, default=None)
    p.add_argument("--pv-tilt-deg", type=float, default=None)
    p.add_argument("--pv-azimuth-deg", type=float, default=None)
    p.add_argument(
        "--weather-profile-mode",
        type=str,
        default=None,
        choices=["none", "monthly_climatology"],
    )
    p.add_argument("--weather-profile-path", type=str, default=None)
    p.add_argument(
        "--latitude-hint",
        type=str,
        default=None,
        choices=["tropical", "temperate", "high_latitude"],
    )
    p.add_argument("--meal-mode", type=str, default=None, choices=["db", "tier"])
    p.add_argument("--meal-db", "--meal-db-path", dest="meal_db_path", type=str, default=None)
    p.add_argument("--solar-day", type=str, default=None)
    p.add_argument("--solar-day-seq", type=str, default=None)
    p.add_argument(
        "--solar-conditions-db",
        "--solar-conditions-path",
        dest="solar_conditions_path",
        type=str,
        default=None,
    )


def _load_config(config_path: str | None) -> dict[str, Any]:
    """Load optional JSON config file and validate top-level shape."""
    if not config_path:
        return {}
    path = Path(config_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Config file must contain a top-level JSON object.")
    return payload


def _read_section(payload: dict[str, Any], name: str) -> dict[str, Any]:
    """Return a section object from JSON config, defaulting to an empty mapping."""
    section = payload.get(name, {})
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ValueError(f"Config section '{name}' must be a JSON object.")
    return section


def _merge_values(
    defaults: dict[str, Any],
    from_config: dict[str, Any],
    from_cli: dict[str, Any],
    *,
    section_name: str,
) -> dict[str, Any]:
    """Merge defaults <- config <- CLI while validating unknown keys.

    Merge priority:
    1) Dataclass defaults
    2) Values from config JSON
    3) Explicit CLI arguments
    """
    unknown = (set(from_config) | set(from_cli)) - set(defaults)
    if unknown:
        keys = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown keys for section '{section_name}': {keys}")
    merged = dict(defaults)
    merged.update(from_config)
    merged.update({k: v for k, v in from_cli.items() if v is not None})
    return merged


def _pick_known_keys(section: dict[str, Any], allowed: set[str], *, section_name: str) -> dict[str, Any]:
    """Fail fast on unknown keys and return only supported keys."""
    unknown = set(section) - allowed
    if unknown:
        keys = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown keys in section '{section_name}': {keys}")
    return {k: v for k, v in section.items() if k in allowed}


def _build_generation_config(args: argparse.Namespace, payload: dict[str, Any]) -> GenerationConfig:
    """Build `GenerationConfig` from defaults, JSON, and CLI overrides."""
    defaults = asdict(GenerationConfig())
    from_config = _read_section(payload, "generation")
    from_cli = {k: getattr(args, k, None) for k in defaults}
    values = _merge_values(defaults, from_config, from_cli, section_name="generation")
    return GenerationConfig(**values)


def _build_rule_settings(args: argparse.Namespace, payload: dict[str, Any]) -> tuple[RuleConfig, Path, str]:
    """Build rule config plus output path settings."""
    section = _read_section(payload, "rule")
    run_defaults: dict[str, Any] = {"outdir": "outputs/main_rule", "prefix": "rule"}
    rule_defaults = asdict(RuleConfig())
    allowed = set(run_defaults) | set(rule_defaults)
    section_known = _pick_known_keys(section, allowed, section_name="rule")

    run_values = _merge_values(
        run_defaults,
        {k: v for k, v in section_known.items() if k in run_defaults},
        {"outdir": getattr(args, "outdir", None), "prefix": getattr(args, "prefix", None)},
        section_name="rule.run",
    )
    rule_values = _merge_values(
        rule_defaults,
        {k: v for k, v in section_known.items() if k in rule_defaults},
        {k: getattr(args, k, None) for k in rule_defaults},
        section_name="rule",
    )
    return RuleConfig(**rule_values), Path(run_values["outdir"]), str(run_values["prefix"])


def _build_lp_settings(
    args: argparse.Namespace,
    payload: dict[str, Any],
    gen_cfg: GenerationConfig,
) -> tuple[LPConfig, Path, str]:
    """Build LP config plus output path settings.

    Also keeps meal DB path aligned with generation settings unless explicitly
    overridden in the LP section/CLI.
    """
    section = _read_section(payload, "lp")
    run_defaults: dict[str, Any] = {"outdir": "outputs/main_lp", "prefix": "lp"}
    lp_defaults = asdict(LPConfig())
    allowed = set(run_defaults) | set(lp_defaults)
    section_known = _pick_known_keys(section, allowed, section_name="lp")

    run_values = _merge_values(
        run_defaults,
        {k: v for k, v in section_known.items() if k in run_defaults},
        {"outdir": getattr(args, "outdir", None), "prefix": getattr(args, "prefix", None)},
        section_name="lp.run",
    )
    lp_values = _merge_values(
        lp_defaults,
        {k: v for k, v in section_known.items() if k in lp_defaults},
        {k: getattr(args, k, None) for k in lp_defaults},
        section_name="lp",
    )

    # Keep meal DB aligned with generation unless LP-specific value is explicitly provided.
    explicit_lp_meal_db = "meal_db_path" in section_known or getattr(args, "meal_db_path", None) is not None
    if not explicit_lp_meal_db:
        lp_values["meal_db_path"] = gen_cfg.meal_db_path

    if lp_values["mode"] == "plan":
        lp_values["pv_kw_fixed"] = None
        lp_values["batt_kwh_fixed"] = None

    return LPConfig(**lp_values), Path(run_values["outdir"]), str(run_values["prefix"])


def _print_results(name: str, artifacts, summary: dict[str, float], metrics: dict[str, float]) -> None:
    """Print run artifacts and aggregated metrics in a compact CLI format."""
    print(f"{name} run complete")
    print(f"  data_csv: {artifacts.data_csv}")
    print(f"  dispatch_csv: {artifacts.dispatch_csv}")
    if artifacts.meal_plan_csv:
        print(f"  meal_plan_csv: {artifacts.meal_plan_csv}")
    print(f"  figures_dir: {artifacts.outdir / 'figures'}")
    print("Summary")
    for k, v in summary.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.6f}")
        else:
            print(f"  {k}: {v}")
    print("Metrics")
    for k, v in metrics.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.6f}")
        else:
            print(f"  {k}: {v}")


def main() -> None:
    """Parse command line, run selected workflow, and print artifacts/metrics."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rule = sub.add_parser("rule", help="Run rule-based case and visualizations")
    p_rule.add_argument("--config", type=str, default=None, help="JSON file with generation/rule/lp sections")
    _add_generation_args(p_rule)
    p_rule.add_argument("--outdir", type=str, default=None)
    p_rule.add_argument("--prefix", type=str, default=None)
    p_rule.add_argument("--pv-kw", dest="pv_kw", type=float, default=None)
    p_rule.add_argument("--batt-kwh", dest="batt_kwh", type=float, default=None)
    p_rule.add_argument("--ch-kw", dest="ch_kw", type=float, default=None)
    p_rule.add_argument("--dis-kw", dest="dis_kw", type=float, default=None)
    p_rule.add_argument("--charge-eff", dest="charge_eff", type=float, default=None)
    p_rule.add_argument("--discharge-eff", dest="discharge_eff", type=float, default=None)
    p_rule.add_argument("--soc-init", dest="soc_init", type=float, default=None)

    p_lp = sub.add_parser("lp", help="Run LP case and visualizations")
    p_lp.add_argument("--config", type=str, default=None, help="JSON file with generation/rule/lp sections")
    _add_generation_args(p_lp)
    p_lp.add_argument("--outdir", type=str, default=None)
    p_lp.add_argument("--prefix", type=str, default=None)
    p_lp.add_argument("--mode", type=str, default=None, choices=["fixed", "plan", "meal_opt"])
    p_lp.add_argument("--pv-kw-fixed", dest="pv_kw_fixed", type=float, default=None)
    p_lp.add_argument("--batt-kwh-fixed", dest="batt_kwh_fixed", type=float, default=None)
    p_lp.add_argument("--pv-capex", dest="pv_capex", type=float, default=None)
    p_lp.add_argument("--batt-capex", dest="batt_capex", type=float, default=None)
    p_lp.add_argument("--charge-eff", dest="charge_eff", type=float, default=None)
    p_lp.add_argument("--discharge-eff", dest="discharge_eff", type=float, default=None)
    p_lp.add_argument("--c-rate", dest="c_rate", type=float, default=None)
    p_lp.add_argument("--soc-init", dest="soc_init", type=float, default=None)
    p_lp.add_argument("--cyclic-soc", action=argparse.BooleanOptionalAction, default=None)
    p_lp.add_argument("--shed-penalty", dest="shed_penalty", type=float, default=None)
    p_lp.add_argument("--solver", type=str, default=None)
    p_lp.add_argument(
        "--nutrition-targets",
        dest="nutrition_targets_path",
        type=str,
        default=None,
    )
    p_lp.add_argument("--meal-cost-weight", dest="meal_cost_weight", type=float, default=None)

    args = parser.parse_args()
    # Optional config file is merged with CLI flags (CLI wins).
    payload = _load_config(args.config)
    gen_cfg = _build_generation_config(args, payload)

    if args.cmd == "rule":
        rule_cfg, outdir, prefix = _build_rule_settings(args, payload)
        artifacts, summary, metrics = run_rule_case(
            gen_cfg=gen_cfg,
            rule_cfg=rule_cfg,
            outdir=outdir,
            prefix=prefix,
        )
        _print_results("Rule", artifacts, summary, metrics)
        return

    lp_cfg, outdir, prefix = _build_lp_settings(args, payload, gen_cfg)
    artifacts, summary, metrics = run_lp_case(
        gen_cfg=gen_cfg,
        lp_cfg=lp_cfg,
        outdir=outdir,
        prefix=prefix,
    )
    _print_results("LP", artifacts, summary, metrics)


if __name__ == "__main__":
    main()
