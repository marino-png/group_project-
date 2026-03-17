"""Synthetic data generator for solar plus battery cooking demand.

Creates a time series with:
  - pv_kw_per_kwp: PV AC output in kW per installed kWp (0..~1)
  - demand_kwh: cooking energy demand in kWh per timestep (5 people, 3 meals/day)
  - meal: meal label (breakfast/lunch/dinner/none)
  - meal_tier: cold/medium/high

Design goals:
  - Realistic-enough shapes for teaching and prototyping.
  - Fully reproducible via --seed.
  - Simple to understand and easy to modify.

Usage:
  python data_generator.py --days 1 --dt-min 15 --solar-day mixed --out data/timeseries.csv
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from meal_database import candidate_meals, load_meal_database
from location_profiles import resolve_location
from solar_conditions import (
    condition_factor_map,
    load_solar_conditions,
    resolve_daily_condition_sequence,
)
from suspos import sunpos
from weather_profiles import monthly_weather_factor_map

@dataclass(frozen=True)
class MealTier:
    name: str
    energy_kwh_min: float
    energy_kwh_max: float
    examples: tuple[str, ...]

    def sample_energy(self, rng: np.random.Generator) -> float:
        if self.energy_kwh_max <= 0:
            return 0.0
        return float(rng.uniform(self.energy_kwh_min, self.energy_kwh_max))

    def sample_dish(self, rng: np.random.Generator) -> str:
        return str(rng.choice(self.examples))


TIERS: dict[str, MealTier] = {
    "cold": MealTier(
        name="cold",
        energy_kwh_min=0.0,
        energy_kwh_max=0.0,
        examples=("salad", "sandwiches", "overnight oats", "cold cereal"),
    ),
    "medium": MealTier(
        name="medium",
        energy_kwh_min=0.5,
        energy_kwh_max=1.5,
        examples=(
            "toast and kettle",
            "microwave meals",
            "quick stir fry",
            "boil pasta",
            "rice cooker",
        ),
    ),
    "high": MealTier(
        name="high",
        energy_kwh_min=2.0,
        energy_kwh_max=3.5,
        examples=(
            "oven roast",
            "slow cooked stew",
            "multi pot dinner",
            "batch baking",
        ),
    ),
}

def _solar_profile_kw_per_kwp(
    index: pd.DatetimeIndex,
    rng: np.random.Generator,
    latitude_hint: str = "temperate",
) -> pd.Series:
    """Create a PV shape in kW/kWp.

    This is not a physical PV model. It is a compact synthetic profile:
      - daylight length varies mildly with day-of-year
      - within-day shape uses a smooth sine hump
      - clouds are autocorrelated to create runs of clear/overcast periods
    """

    doy = index.dayofyear.to_numpy()
    hour = index.hour.to_numpy()
    minute = index.minute.to_numpy()
    tod = hour + minute / 60.0

    # Rough seasonal amplitude and day length, depending on a qualitative climate hint.
    if latitude_hint == "tropical":
        amp = 0.95 + 0.05 * np.sin(2 * np.pi * (doy - 80) / 365.0)
        daylight = 12.0 + 0.5 * np.sin(2 * np.pi * (doy - 80) / 365.0)
    elif latitude_hint == "high_latitude":
        amp = 0.70 + 0.30 * np.sin(2 * np.pi * (doy - 80) / 365.0)
        daylight = 10.0 + 4.0 * np.sin(2 * np.pi * (doy - 80) / 365.0)
    else:  # temperate
        amp = 0.75 + 0.25 * np.sin(2 * np.pi * (doy - 80) / 365.0)
        daylight = 11.0 + 2.0 * np.sin(2 * np.pi * (doy - 80) / 365.0)

    daylight = np.clip(daylight, 7.5, 16.5)
    sunrise = 12.0 - daylight / 2.0
    sunset = 12.0 + daylight / 2.0

    # Clear-sky shape: sine hump between sunrise and sunset.
    x = (tod - sunrise) / (sunset - sunrise)
    clear = np.where((x >= 0) & (x <= 1), np.sin(np.pi * x), 0.0)
    clear = clear * amp

    # Autocorrelated cloud factor in [0.25, 1.05] (slightly above 1 to mimic cool, clear days).
    n = len(index)
    clouds = np.empty(n, dtype=float)
    clouds[0] = float(rng.uniform(0.5, 1.0))
    rho = 0.94  # persistence
    noise = rng.normal(0.0, 0.08, size=n)
    for i in range(1, n):
        clouds[i] = rho * clouds[i - 1] + (1 - rho) * 0.85 + noise[i]
    clouds = np.clip(clouds, 0.25, 1.05)

    pv = clear * clouds
    return pd.Series(pv, index=index, name="pv_kw_per_kwp")


def _panel_normal_vector(*, tilt_deg: float, azimuth_deg: float) -> np.ndarray:
    """Return panel normal as [east, north, up] unit vector."""
    tilt_rad = np.deg2rad(float(tilt_deg))
    azimuth_rad = np.deg2rad(float(azimuth_deg))
    return np.array(
        [
            np.sin(azimuth_rad) * np.sin(tilt_rad),
            np.cos(azimuth_rad) * np.sin(tilt_rad),
            np.cos(tilt_rad),
        ],
        dtype=float,
    )


def _solar_profile_from_suspos(
    index: pd.DatetimeIndex,
    *,
    latitude_deg: float,
    longitude_deg: float,
    pv_tilt_deg: float,
    pv_azimuth_deg: float,
) -> pd.Series:
    """Build a PV profile from solar geometry using the PSA+ sun position model.

    The output is a simple clear-sky proxy in kW/kWp:
    - solar position comes from `suspos.sunpos`
    - panel incidence is computed against a fixed-tilt panel normal
    - low sun angles are softly penalized to mimic larger air-mass losses
    """
    if not -90.0 <= float(latitude_deg) <= 90.0:
        raise ValueError("latitude_deg must be between -90 and 90.")
    if not -180.0 <= float(longitude_deg) <= 180.0:
        raise ValueError("longitude_deg must be between -180 and 180.")
    if not 0.0 <= float(pv_tilt_deg) <= 90.0:
        raise ValueError("pv_tilt_deg must be between 0 and 90.")

    ts = np.column_stack(
        [
            index.year.to_numpy(),
            index.month.to_numpy(),
            index.day.to_numpy(),
            index.hour.to_numpy(),
            index.minute.to_numpy(),
            index.second.to_numpy(),
        ]
    )
    result = sunpos(ts, lat_deg=float(latitude_deg), lon_deg=float(longitude_deg))
    sun_up = np.clip(result.SunVec[:, 2], 0.0, 1.0)
    panel_normal = _panel_normal_vector(tilt_deg=pv_tilt_deg, azimuth_deg=pv_azimuth_deg)
    incidence = np.clip(result.SunVec @ panel_normal, 0.0, 1.0)

    # A compact clear-sky proxy: direct incidence plus a small diffuse term.
    pv = incidence * np.power(np.maximum(sun_up, 1e-9), 0.2) + 0.12 * sun_up
    pv = np.clip(pv, 0.0, 1.0)
    return pd.Series(pv, index=index, name="pv_kw_per_kwp")


def _build_solar_profile(
    index: pd.DatetimeIndex,
    *,
    rng: np.random.Generator,
    solar_profile_model: str,
    latitude_deg: float | None,
    longitude_deg: float | None,
    pv_tilt_deg: float,
    pv_azimuth_deg: float,
    latitude_hint: str,
) -> pd.Series:
    """Create PV profile using either the legacy synthetic model or `suspos`."""
    if solar_profile_model == "synthetic":
        return _solar_profile_kw_per_kwp(index, rng=rng, latitude_hint=latitude_hint)
    if solar_profile_model == "suspos":
        if latitude_deg is None or longitude_deg is None:
            raise ValueError("latitude_deg and longitude_deg are required when solar_profile_model='suspos'.")
        return _solar_profile_from_suspos(
            index,
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
            pv_tilt_deg=pv_tilt_deg,
            pv_azimuth_deg=pv_azimuth_deg,
        )
    raise ValueError("solar_profile_model must be either 'synthetic' or 'suspos'.")


def _apply_weather_profile(
    pv: pd.Series,
    *,
    weather_profile_mode: str,
    location_name: str | None,
    weather_profile_path: str | None,
) -> pd.Series:
    """Apply optional weather attenuation to a PV profile."""
    if weather_profile_mode == "none":
        return pv
    if weather_profile_mode != "monthly_climatology":
        raise ValueError("weather_profile_mode must be either 'none' or 'monthly_climatology'.")

    month_map = monthly_weather_factor_map(
        location_name=location_name,
        weather_profile_path=weather_profile_path,
    )
    if not month_map:
        return pv
    factors = pv.index.month.map(lambda month: month_map.get(int(month), 1.0)).astype(float)
    out = (pv * factors).clip(lower=0.0)
    out.name = pv.name
    return out


def _apply_solar_conditions(
    pv: pd.Series,
    *,
    days: int,
    solar_day: str,
    solar_day_seq: str | None,
    solar_conditions_path: str | None,
) -> pd.Series:
    """Apply day-condition multipliers (sunny/mixed/cloudy/...) to PV profile."""
    cond_df = load_solar_conditions(solar_conditions_path)
    cond_map = condition_factor_map(cond_df)
    seq = resolve_daily_condition_sequence(days, solar_day=solar_day, solar_day_seq=solar_day_seq)
    unique_dates = pd.Index(pv.index.date).unique()
    if len(unique_dates) != days:
        # Fallback: align sequence with whatever number of day buckets exists.
        seq = [seq[i % len(seq)] for i in range(len(unique_dates))]

    # Multiply each calendar day slice by its condition-specific scalar.
    out = pv.copy()
    for i, date in enumerate(unique_dates):
        cond = seq[i % len(seq)].lower()
        if cond not in cond_map:
            known = ", ".join(sorted(cond_map))
            raise ValueError(f"Unknown solar day condition '{cond}'. Known values: {known}")
        mask = (out.index.date == date)
        out.loc[mask] = out.loc[mask] * cond_map[cond]
    return out.clip(lower=0.0)


def _assign_meals_from_db(
    index: pd.DatetimeIndex,
    *,
    rng: np.random.Generator,
    dt_minutes: int,
    meal_db_path: str | None,
) -> pd.DataFrame:
    """Create meal demand by sampling from a maintainable meal CSV database.

    For each daily meal slot, a single meal is sampled from valid candidates and
    its cooking energy is spread across a short random contiguous cooking window.
    """
    meal_db = load_meal_database(meal_db_path)
    demand_kwh = np.zeros(len(index), dtype=float)
    meal = np.full(len(index), "none", dtype=object)
    meal_tier = np.full(len(index), "none", dtype=object)
    dish = np.full(len(index), "none", dtype=object)
    meal_slot_id = np.full(len(index), "none", dtype=object)
    meal_id = np.full(len(index), "none", dtype=object)
    meal_name = np.full(len(index), "none", dtype=object)
    meal_type = np.full(len(index), "none", dtype=object)
    calories_kcal = np.zeros(len(index), dtype=float)
    protein_g = np.zeros(len(index), dtype=float)
    carbs_g = np.zeros(len(index), dtype=float)
    fat_g = np.zeros(len(index), dtype=float)
    fiber_g = np.zeros(len(index), dtype=float)
    micronutrient_score = np.zeros(len(index), dtype=float)
    meal_cost_usd = np.zeros(len(index), dtype=float)

    windows: dict[str, tuple[float, float]] = {
        "breakfast": (7.0, 8.0),
        "lunch": (12.0, 13.0),
        "dinner": (18.0, 19.0),
    }

    for date in pd.Index(index.date).unique():
        day_mask = (index.date == date)
        day_pos = np.where(day_mask)[0]
        if len(day_pos) == 0:
            continue
        day_index = index[day_pos]
        tod = day_index.hour + day_index.minute / 60.0

        for slot_name, (start_h, end_h) in windows.items():
            in_window = (tod >= start_h) & (tod < end_h)
            window_positions = np.where(in_window)[0]
            if len(window_positions) == 0:
                continue

            slot_id = f"{date}_{slot_name}"
            window_global_idx = day_pos[window_positions]
            meal[window_global_idx] = slot_name
            meal_tier[window_global_idx] = "db"
            meal_slot_id[window_global_idx] = slot_id
            meal_type[window_global_idx] = slot_name

            # Candidate meals are filtered by slot type (`breakfast/lunch/dinner/any`).
            choices = candidate_meals(meal_db, slot_name)
            row = choices.iloc[int(rng.integers(0, len(choices)))]

            meal_id[window_global_idx] = str(row["meal_id"])
            meal_name[window_global_idx] = str(row["meal_name"])
            dish[window_global_idx] = str(row["meal_name"])
            calories_kcal[window_global_idx] = float(row["calories_kcal"])
            protein_g[window_global_idx] = float(row["protein_g"])
            carbs_g[window_global_idx] = float(row["carbs_g"])
            fat_g[window_global_idx] = float(row["fat_g"])
            fiber_g[window_global_idx] = float(row["fiber_g"])
            micronutrient_score[window_global_idx] = float(row.get("micronutrient_score", 0.0))
            meal_cost_usd[window_global_idx] = float(row["meal_cost_usd"])

            energy_kwh = float(row["cook_energy_kwh"])
            if energy_kwh <= 0:
                continue

            db_duration = max(1, int(round(float(row.get("cook_duration_min", 30.0)) / dt_minutes)))
            duration_steps = min(db_duration, len(window_positions))
            start_offset = int(rng.integers(0, len(window_positions) - duration_steps + 1))
            cook_positions = window_positions[start_offset : start_offset + duration_steps]
            cook_global_idx = day_pos[cook_positions]
            demand_kwh[cook_global_idx] += energy_kwh / duration_steps

    return pd.DataFrame(
        {
            "demand_kwh": demand_kwh,
            "meal": meal,
            "meal_tier": meal_tier,
            "dish": dish,
            "meal_slot_id": meal_slot_id,
            "meal_id": meal_id,
            "meal_name": meal_name,
            "meal_type": meal_type,
            "calories_kcal": calories_kcal,
            "protein_g": protein_g,
            "carbs_g": carbs_g,
            "fat_g": fat_g,
            "fiber_g": fiber_g,
            "micronutrient_score": micronutrient_score,
            "meal_cost_usd": meal_cost_usd,
        },
        index=index,
    )


def _assign_meals(
    index: pd.DatetimeIndex,
    rng: np.random.Generator,
    dt_minutes: int,
    p_cold: float,
    p_medium: float,
    p_high: float,
) -> pd.DataFrame:
    """Create a cooking demand series with three meal windows per day.

    For each day:
      - breakfast window: 07:00-08:00
      - lunch window: 12:00-13:00
      - dinner window: 18:00-19:00

    Inside each window, one dish is selected and its energy is delivered over a
    random duration (15..45 minutes) starting at a random offset within the window.
    """

    demand_kwh = np.zeros(len(index), dtype=float)
    meal = np.full(len(index), "none", dtype=object)
    meal_tier = np.full(len(index), "none", dtype=object)
    dish = np.full(len(index), "none", dtype=object)
    meal_slot_id = np.full(len(index), "none", dtype=object)
    meal_id = np.full(len(index), "none", dtype=object)
    meal_name_col = np.full(len(index), "none", dtype=object)
    meal_type = np.full(len(index), "none", dtype=object)
    calories_kcal = np.zeros(len(index), dtype=float)
    protein_g = np.zeros(len(index), dtype=float)
    carbs_g = np.zeros(len(index), dtype=float)
    fat_g = np.zeros(len(index), dtype=float)
    fiber_g = np.zeros(len(index), dtype=float)
    micronutrient_score = np.zeros(len(index), dtype=float)
    meal_cost_usd = np.zeros(len(index), dtype=float)

    # Normalize tier probabilities so callers can pass rough ratios.
    probs = np.array([p_cold, p_medium, p_high], dtype=float)
    if not np.all(np.isfinite(probs)):
        raise ValueError("Meal probabilities must be finite numbers.")
    if np.any(probs < 0):
        raise ValueError("Meal probabilities must be non-negative.")
    prob_sum = probs.sum()
    if prob_sum <= 0:
        raise ValueError("At least one meal probability must be greater than zero.")
    probs = probs / prob_sum
    tier_names = np.array(["cold", "medium", "high"], dtype=object)

    windows: dict[str, tuple[float, float]] = {
        "breakfast": (7.0, 8.0),
        "lunch": (12.0, 13.0),
        "dinner": (18.0, 19.0),
    }

    for date in pd.Index(index.date).unique():
        day_mask = (index.date == date)
        day_pos = np.where(day_mask)[0]
        if len(day_pos) == 0:
            continue
        day_index = index[day_pos]
        tod = day_index.hour + day_index.minute / 60.0

        for meal_label, (start_h, end_h) in windows.items():
            tier = str(rng.choice(tier_names, p=probs))
            tier_obj = TIERS[tier]
            energy_kwh = tier_obj.sample_energy(rng)
            dish_name = tier_obj.sample_dish(rng)

            in_window = (tod >= start_h) & (tod < end_h)
            window_positions = np.where(in_window)[0]
            if len(window_positions) == 0:
                continue

            window_global_idx = day_pos[window_positions]
            slot_id = f"{date}_{meal_label}"
            meal[window_global_idx] = meal_label
            meal_tier[window_global_idx] = tier
            dish[window_global_idx] = dish_name
            meal_slot_id[window_global_idx] = slot_id
            meal_id[window_global_idx] = f"{tier}_{meal_label}"
            meal_name_col[window_global_idx] = dish_name
            meal_type[window_global_idx] = meal_label

            if energy_kwh <= 0:
                continue

            min_steps = max(1, int(round(15 / dt_minutes)))
            max_steps = max(min_steps, int(round(45 / dt_minutes)))
            duration_steps = int(rng.integers(min_steps, max_steps + 1))
            duration_steps = min(duration_steps, len(window_positions))
            start_offset = int(rng.integers(0, len(window_positions) - duration_steps + 1))
            cook_positions = window_positions[start_offset : start_offset + duration_steps]
            cook_global_idx = day_pos[cook_positions]
            demand_kwh[cook_global_idx] += energy_kwh / duration_steps

    return pd.DataFrame(
        {
            "demand_kwh": demand_kwh,
            "meal": meal,
            "meal_tier": meal_tier,
            "dish": dish,
            "meal_slot_id": meal_slot_id,
            "meal_id": meal_id,
            "meal_name": meal_name_col,
            "meal_type": meal_type,
            "calories_kcal": calories_kcal,
            "protein_g": protein_g,
            "carbs_g": carbs_g,
            "fat_g": fat_g,
            "fiber_g": fiber_g,
            "micronutrient_score": micronutrient_score,
            "meal_cost_usd": meal_cost_usd,
        },
        index=index,
    )


def build_dataset(
    *,
    start: str,
    days: int,
    dt_minutes: int,
    seed: int,
    solar_profile_model: str = "synthetic",
    location_name: str | None = None,
    location_profiles_path: str | None = None,
    latitude_deg: float | None = None,
    longitude_deg: float | None = None,
    pv_tilt_deg: float = 25.0,
    pv_azimuth_deg: float = 180.0,
    weather_profile_mode: str = "monthly_climatology",
    weather_profile_path: str | None = None,
    latitude_hint: str,
    p_cold: float,
    p_medium: float,
    p_high: float,
    meal_mode: str = "db",
    meal_db_path: str | None = None,
    solar_day: str = "mixed",
    solar_day_seq: str | None = None,
    solar_conditions_path: str | None = None,
) -> pd.DataFrame:
    """Build a complete synthetic dataset for rule/LP workflows.

    Output columns include:
    - PV traces (`pv_kw_per_kwp`, `pv_kwh_per_kw`)
    - demand/meal fields
    - timestep metadata (`dt_hours`, `day_id`)
    """
    if days <= 0:
        raise ValueError("days must be a positive integer.")
    if dt_minutes <= 0:
        raise ValueError("dt_minutes must be a positive integer.")

    start_ts = pd.Timestamp(start)
    periods = int(days * 24 * 60 / dt_minutes)
    index = pd.date_range(start=start_ts, periods=periods, freq=f"{dt_minutes}min")
    rng = np.random.default_rng(seed)
    latitude_deg, longitude_deg, resolved_location_name = resolve_location(
        location_name,
        latitude_deg=latitude_deg,
        longitude_deg=longitude_deg,
        location_profiles_path=location_profiles_path,
    )

    # 1) Baseline PV shape, then condition scaling.
    pv = _build_solar_profile(
        index,
        rng=rng,
        solar_profile_model=solar_profile_model,
        latitude_deg=latitude_deg,
        longitude_deg=longitude_deg,
        pv_tilt_deg=pv_tilt_deg,
        pv_azimuth_deg=pv_azimuth_deg,
        latitude_hint=latitude_hint,
    )
    pv = _apply_weather_profile(
        pv,
        weather_profile_mode=weather_profile_mode,
        location_name=resolved_location_name or location_name,
        weather_profile_path=weather_profile_path,
    )
    pv = _apply_solar_conditions(
        pv,
        days=days,
        solar_day=solar_day,
        solar_day_seq=solar_day_seq,
        solar_conditions_path=solar_conditions_path,
    )
    # 2) Meal demand from database or legacy tier generator.
    if meal_mode == "db":
        meals = _assign_meals_from_db(
            index,
            rng=rng,
            dt_minutes=dt_minutes,
            meal_db_path=meal_db_path,
        )
    elif meal_mode == "tier":
        meals = _assign_meals(
            index,
            rng=rng,
            dt_minutes=dt_minutes,
            p_cold=p_cold,
            p_medium=p_medium,
            p_high=p_high,
        )
    else:
        raise ValueError("meal_mode must be either 'db' or 'tier'.")

    df = pd.concat([pv, meals], axis=1)
    # 3) Add helper fields used by optimizers and downstream reporting.
    df["dt_hours"] = dt_minutes / 60.0
    # Helpful derived series for optimization.
    df["pv_kwh_per_kw"] = df["pv_kw_per_kwp"] * df["dt_hours"]
    df["day_id"] = df.index.date.astype(str)
    df["location_name"] = resolved_location_name or (location_name or "custom")
    if latitude_deg is not None:
        df["latitude_deg"] = float(latitude_deg)
    if longitude_deg is not None:
        df["longitude_deg"] = float(longitude_deg)
    return df


def main() -> None:
    """CLI entry point for synthetic data generation."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", type=str, default="2026-01-01", help="Start timestamp")
    p.add_argument("--days", type=int, default=1, help="Number of days")
    p.add_argument("--dt-min", type=int, default=15, help="Timestep in minutes")
    p.add_argument("--seed", type=int, default=42, help="Random seed")
    p.add_argument(
        "--solar-profile-model",
        type=str,
        default="synthetic",
        choices=["synthetic", "suspos"],
        help="Solar input model: legacy synthetic curve or suspos-based geometry",
    )
    p.add_argument("--location-name", type=str, default="Nigeria", help="Named location preset")
    p.add_argument(
        "--location-profiles-path",
        type=str,
        default="data/reference/location_profiles.csv",
        help="Named location preset CSV",
    )
    p.add_argument("--latitude-deg", type=float, default=None, help="Latitude in degrees for suspos mode")
    p.add_argument("--longitude-deg", type=float, default=None, help="Longitude in degrees for suspos mode")
    p.add_argument("--pv-tilt-deg", type=float, default=25.0, help="PV tilt from horizontal in degrees")
    p.add_argument(
        "--pv-azimuth-deg",
        type=float,
        default=180.0,
        help="PV azimuth in degrees clockwise from north (180=south-facing)",
    )
    p.add_argument(
        "--weather-profile-mode",
        type=str,
        choices=["none", "monthly_climatology"],
        default="monthly_climatology",
        help="Weather attenuation mode applied on top of the solar geometry profile",
    )
    p.add_argument(
        "--weather-profile-path",
        type=str,
        default="data/reference/weather_profiles.csv",
        help="Monthly weather attenuation CSV",
    )
    p.add_argument(
        "--latitude-hint",
        type=str,
        default="temperate",
        choices=["tropical", "temperate", "high_latitude"],
        help="Qualitative solar seasonality",
    )
    p.add_argument("--p-cold", type=float, default=0.25, help="Probability of cold meals")
    p.add_argument("--p-medium", type=float, default=0.50, help="Probability of medium meals")
    p.add_argument("--p-high", type=float, default=0.25, help="Probability of high meals")
    p.add_argument(
        "--meal-mode",
        type=str,
        choices=["db", "tier"],
        default="db",
        help="Meal demand source: db (CSV meal database) or tier (legacy synthetic tiers)",
    )
    p.add_argument(
        "--meal-db",
        type=str,
        default="data/reference/meal_database.csv",
        help="Meal database CSV path (used with --meal-mode db)",
    )
    p.add_argument(
        "--solar-day",
        type=str,
        default="mixed",
        help="Single solar day condition name (e.g., sunny, cloudy, mixed)",
    )
    p.add_argument(
        "--solar-day-seq",
        type=str,
        default=None,
        help="Comma-separated daily solar condition sequence, e.g. sunny,mixed,cloudy",
    )
    p.add_argument(
        "--solar-conditions-db",
        type=str,
        default="data/reference/solar_day_conditions.csv",
        help="Solar condition preset CSV",
    )
    p.add_argument("--out", type=str, default="data/timeseries.csv", help="Output CSV")
    args = p.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = build_dataset(
        start=args.start,
        days=args.days,
        dt_minutes=args.dt_min,
        seed=args.seed,
        solar_profile_model=args.solar_profile_model,
        location_name=args.location_name,
        location_profiles_path=args.location_profiles_path,
        latitude_deg=args.latitude_deg,
        longitude_deg=args.longitude_deg,
        pv_tilt_deg=args.pv_tilt_deg,
        pv_azimuth_deg=args.pv_azimuth_deg,
        weather_profile_mode=args.weather_profile_mode,
        weather_profile_path=args.weather_profile_path,
        latitude_hint=args.latitude_hint,
        p_cold=args.p_cold,
        p_medium=args.p_medium,
        p_high=args.p_high,
        meal_mode=args.meal_mode,
        meal_db_path=args.meal_db,
        solar_day=args.solar_day,
        solar_day_seq=args.solar_day_seq,
        solar_conditions_path=args.solar_conditions_db,
    )
    df.to_csv(out_path, index_label="timestamp")
    print(f"Wrote {len(df):,} rows to {out_path}")


if __name__ == "__main__":
    main()
