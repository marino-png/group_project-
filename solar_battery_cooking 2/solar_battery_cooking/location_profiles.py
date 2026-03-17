"""Location presets and name-to-coordinate helpers for solar input generation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def default_location_profiles_path() -> Path:
    """Default location preset CSV path."""
    return Path(__file__).resolve().parent / "data" / "reference" / "location_profiles.csv"


def load_location_profiles(path: str | Path | None = None) -> pd.DataFrame:
    """Load and validate named location presets."""
    cfg_path = Path(path) if path else default_location_profiles_path()
    if not cfg_path.exists():
        raise FileNotFoundError(f"Location profiles file not found: {cfg_path}")
    df = pd.read_csv(cfg_path)
    required = {"name", "latitude_deg", "longitude_deg"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Location profiles file missing columns: {sorted(missing)}")
    df["name"] = df["name"].astype(str).str.strip()
    df["name_key"] = df["name"].str.lower()
    df["latitude_deg"] = pd.to_numeric(df["latitude_deg"], errors="coerce")
    df["longitude_deg"] = pd.to_numeric(df["longitude_deg"], errors="coerce")
    if df[["latitude_deg", "longitude_deg"]].isna().any().any():
        raise ValueError("Location profile latitude/longitude must be numeric.")
    return df.reset_index(drop=True)


def resolve_location(
    location_name: str | None,
    *,
    latitude_deg: float | None,
    longitude_deg: float | None,
    location_profiles_path: str | Path | None = None,
) -> tuple[float | None, float | None, str | None]:
    """Resolve a location name to coordinates, with explicit coordinates taking precedence."""
    if latitude_deg is not None or longitude_deg is not None:
        if latitude_deg is None or longitude_deg is None:
            raise ValueError("latitude_deg and longitude_deg must be provided together.")
        return float(latitude_deg), float(longitude_deg), location_name

    if not location_name:
        return None, None, None

    df = load_location_profiles(location_profiles_path)
    key = str(location_name).strip().lower()
    match = df[df["name_key"] == key]
    if match.empty:
        known = ", ".join(df["name"].tolist())
        raise ValueError(f"Unknown location '{location_name}'. Known locations: {known}")
    row = match.iloc[0]
    return float(row["latitude_deg"]), float(row["longitude_deg"]), str(row["name"])
