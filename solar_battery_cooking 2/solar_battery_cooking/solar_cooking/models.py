"""Typed configuration models for pipeline runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GenerationConfig:
    """Inputs used to generate synthetic time-series scenario data.

    Notes:
    - `meal_mode='db'` pulls meal slots from meal CSV.
    - `meal_mode='tier'` uses legacy synthetic meal tiers.
    """
    start: str = "2026-01-01"
    days: int = 1
    dt_minutes: int = 15
    seed: int = 42
    solar_profile_model: str = "synthetic"
    location_name: str | None = "Nigeria"
    location_profiles_path: str = "data/reference/location_profiles.csv"
    latitude_deg: float | None = None
    longitude_deg: float | None = None
    pv_tilt_deg: float = 25.0
    pv_azimuth_deg: float = 180.0
    weather_profile_mode: str = "monthly_climatology"
    weather_profile_path: str = "data/reference/weather_profiles.csv"
    latitude_hint: str = "temperate"
    p_cold: float = 0.25
    p_medium: float = 0.50
    p_high: float = 0.25
    meal_mode: str = "db"
    meal_db_path: str = "data/reference/meal_database.csv"
    solar_day: str = "mixed"
    solar_day_seq: str | None = None
    solar_conditions_path: str = "data/reference/solar_day_conditions.csv"


@dataclass(frozen=True)
class RuleConfig:
    """Parameters for the rule-based battery dispatch simulation."""
    pv_kw: float = 4.0
    batt_kwh: float = 8.0
    ch_kw: float = 3.0
    dis_kw: float = 3.0
    charge_eff: float = 0.92
    discharge_eff: float = 0.92
    soc_init: float = 0.5


@dataclass(frozen=True)
class LPConfig:
    """Parameters for LP/MILP optimization modes.

    `mode` options:
    - `fixed`: fixed PV+battery sizes.
    - `plan`: optimize PV+battery sizes.
    - `meal_opt`: optimize dispatch + meal choices.
    """
    mode: str = "fixed"  # fixed | plan | meal_opt
    pv_kw_fixed: float | None = 4.0
    batt_kwh_fixed: float | None = 8.0
    pv_capex: float = 900.0
    batt_capex: float = 500.0
    charge_eff: float = 0.92
    discharge_eff: float = 0.92
    c_rate: float = 0.5
    soc_init: float = 0.5
    cyclic_soc: bool = True
    shed_penalty: float = 10_000.0
    solver: str = "PULP_CBC_CMD"
    meal_db_path: str = "data/reference/meal_database.csv"
    nutrition_targets_path: str = "configs/meal_targets.json"
    meal_cost_weight: float = 1.0


@dataclass(frozen=True)
class RunArtifacts:
    """Output file locations from a completed pipeline run."""
    data_csv: Path
    dispatch_csv: Path
    outdir: Path
    prefix: str
    meal_plan_csv: Path | None = None
