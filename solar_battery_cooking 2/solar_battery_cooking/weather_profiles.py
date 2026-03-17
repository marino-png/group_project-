"""Monthly weather attenuation profiles for location-aware solar generation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def default_weather_profiles_path() -> Path:
    """Default weather profile CSV path."""
    return Path(__file__).resolve().parent / "data" / "reference" / "weather_profiles.csv"


def load_weather_profiles(path: str | Path | None = None) -> pd.DataFrame:
    """Load and validate monthly weather attenuation factors."""
    cfg_path = Path(path) if path else default_weather_profiles_path()
    if not cfg_path.exists():
        raise FileNotFoundError(f"Weather profiles file not found: {cfg_path}")
    df = pd.read_csv(cfg_path)
    required = {"location", "month", "weather_factor"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Weather profiles file missing columns: {sorted(missing)}")
    df["location"] = df["location"].astype(str).str.strip()
    df["location_key"] = df["location"].str.lower()
    df["month"] = pd.to_numeric(df["month"], errors="coerce")
    df["weather_factor"] = pd.to_numeric(df["weather_factor"], errors="coerce")
    if df[["month", "weather_factor"]].isna().any().any():
        raise ValueError("Weather profile month and weather_factor must be numeric.")
    if not df["month"].between(1, 12).all():
        raise ValueError("Weather profile month must be between 1 and 12.")
    if (df["weather_factor"] < 0).any():
        raise ValueError("weather_factor must be non-negative.")
    return df.reset_index(drop=True)


def monthly_weather_factor_map(
    *,
    location_name: str | None,
    weather_profile_path: str | Path | None = None,
) -> dict[int, float]:
    """Return month -> attenuation factor for a location, or an empty mapping if unavailable."""
    if not location_name:
        return {}
    df = load_weather_profiles(weather_profile_path)
    match = df[df["location_key"] == str(location_name).strip().lower()]
    if match.empty:
        return {}
    return {int(row["month"]): float(row["weather_factor"]) for _, row in match.iterrows()}
