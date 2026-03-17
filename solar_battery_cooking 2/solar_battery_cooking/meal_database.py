"""Meal database utilities.

The meal database is intended to be CSV-first so non-developers can maintain it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = [
    "meal_id",
    "meal_name",
    "meal_type",
    "cook_energy_kwh",
    "calories_kcal",
    "protein_g",
    "carbs_g",
    "fat_g",
    "fiber_g",
    "meal_cost_usd",
]

OPTIONAL_NUMERIC_COLUMNS = [
    "micronutrient_score",
    "iron_mg",
    "calcium_mg",
    "vitamin_c_mg",
    "cook_duration_min",
]


def default_meal_db_path() -> Path:
    """Default meal CSV path bundled with the project."""
    return Path(__file__).resolve().parent / "data" / "reference" / "meal_database.csv"


def load_meal_database(path: str | Path | None = None) -> pd.DataFrame:
    """Load, validate, and normalize meal database rows.

    Guarantees:
    - required columns exist
    - numeric fields are numeric
    - disabled meals are filtered out
    """
    db_path = Path(path) if path else default_meal_db_path()
    if not db_path.exists():
        raise FileNotFoundError(f"Meal database not found: {db_path}")

    df = pd.read_csv(db_path)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Meal database missing required columns: {missing}")

    # `enabled` is optional; default to active when column is absent.
    if "enabled" not in df.columns:
        df["enabled"] = True
    df["enabled"] = df["enabled"].astype(bool)

    for col in REQUIRED_COLUMNS:
        if col in {"meal_id", "meal_name", "meal_type"}:
            df[col] = df[col].astype(str).str.strip()
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in OPTIONAL_NUMERIC_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    if (df["cook_energy_kwh"] < 0).any():
        raise ValueError("cook_energy_kwh must be non-negative for all meals.")

    # Keep only enabled rows and reset index for reliable positional sampling.
    df = df.loc[df["enabled"]].copy().reset_index(drop=True)
    if df.empty:
        raise ValueError("Meal database has no enabled meals.")
    return df


def candidate_meals(df: pd.DataFrame, meal_type: str) -> pd.DataFrame:
    """Return meals valid for a slot type (`meal_type` or `any`)."""
    mt = str(meal_type).strip().lower()
    out = df.loc[df["meal_type"].str.lower().isin([mt, "any"])]
    if out.empty:
        raise ValueError(f"No candidate meals found for meal_type={meal_type!r}")
    return out.reset_index(drop=True)
