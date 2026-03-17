"""Solar day condition presets (e.g., sunny, mixed, cloudy)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def default_solar_conditions_path() -> Path:
    """Default solar condition preset CSV path."""
    return Path(__file__).resolve().parent / "data" / "reference" / "solar_day_conditions.csv"


def load_solar_conditions(path: str | Path | None = None) -> pd.DataFrame:
    """Load and validate solar day condition multipliers."""
    cfg_path = Path(path) if path else default_solar_conditions_path()
    if not cfg_path.exists():
        raise FileNotFoundError(f"Solar conditions file not found: {cfg_path}")
    df = pd.read_csv(cfg_path)
    required = {"condition", "pv_multiplier"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Solar conditions file missing columns: {sorted(missing)}")
    df["condition"] = df["condition"].astype(str).str.strip().str.lower()
    df["pv_multiplier"] = pd.to_numeric(df["pv_multiplier"], errors="coerce")
    if df["pv_multiplier"].isna().any():
        raise ValueError("pv_multiplier must be numeric for all rows.")
    if (df["pv_multiplier"] < 0).any():
        raise ValueError("pv_multiplier must be non-negative.")
    return df.reset_index(drop=True)


def resolve_daily_condition_sequence(days: int, *, solar_day: str, solar_day_seq: str | None) -> list[str]:
    """Expand single/sequence condition input into a day-by-day list."""
    if solar_day_seq:
        seq = [x.strip().lower() for x in solar_day_seq.split(",") if x.strip()]
        if not seq:
            raise ValueError("solar_day_seq is empty after parsing.")
    else:
        seq = [str(solar_day).strip().lower()]
    if days <= 0:
        raise ValueError("days must be positive.")
    return [seq[i % len(seq)] for i in range(days)]


def condition_factor_map(df: pd.DataFrame) -> dict[str, float]:
    """Map condition name -> pv_multiplier for fast lookup."""
    return {str(row["condition"]).lower(): float(row["pv_multiplier"]) for _, row in df.iterrows()}
