# generate_solar_profile.py
# -*- coding: utf-8 -*-

"""
Generate a simple PV power profile from solar position using local sunpos.py.

Usage examples:
    python generate_solar_profile.py
    python generate_solar_profile.py --lat 9.0765 --lon 7.3986 --date 2026-01-01
    python generate_solar_profile.py --lat 6.5244 --lon 3.3792 --pv-capacity 2.5 --weather cloudy
    python generate_solar_profile.py --lat 9.0765 --lon 7.3986 --step-min 15 --out solar_profile.csv

Expected local dependency:
    - sunpos.py  (must expose a function named `sunpos`)
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# Import your existing sunpos.py
# Keep this file in the same folder as sunpos.py
from suspos import sunpos


@dataclass
class PVConfig:
    lat: float
    lon: float
    date_str: str
    step_min: int
    pv_capacity_kw: float
    weather: str
    panel_tilt_deg: float
    panel_azimuth_deg: float
    use_tilt_model: bool
    output_csv: str


WEATHER_MULTIPLIERS = {
    "clear": 1.00,
    "partly_cloudy": 0.75,
    "cloudy": 0.50,
    "rainy": 0.30,
}


def parse_args() -> PVConfig:
    parser = argparse.ArgumentParser(
        description="Generate a simple PV profile from solar position."
    )
    parser.add_argument("--lat", type=float, default=9.0765, help="Latitude in degrees")
    parser.add_argument("--lon", type=float, default=7.3986, help="Longitude in degrees")
    parser.add_argument("--date", type=str, default="2026-01-01", help="Date as YYYY-MM-DD")
    parser.add_argument("--step-min", type=int, default=15, help="Time step in minutes")
    parser.add_argument(
        "--pv-capacity",
        type=float,
        default=2.0,
        help="Installed PV capacity in kW",
    )
    parser.add_argument(
        "--weather",
        type=str,
        default="clear",
        choices=list(WEATHER_MULTIPLIERS.keys()),
        help="Simple weather multiplier",
    )
    parser.add_argument(
        "--panel-tilt",
        type=float,
        default=10.0,
        help="Panel tilt angle in degrees",
    )
    parser.add_argument(
        "--panel-azimuth",
        type=float,
        default=180.0,
        help="Panel azimuth in degrees (0=N, 90=E, 180=S, 270=W)",
    )
    parser.add_argument(
        "--use-tilt-model",
        action="store_true",
        help="Use a simple panel orientation model instead of cos(zenith)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="solar_profile.csv",
        help="Output CSV filename",
    )

    args = parser.parse_args()
    return PVConfig(
        lat=args.lat,
        lon=args.lon,
        date_str=args.date,
        step_min=args.step_min,
        pv_capacity_kw=args.pv_capacity,
        weather=args.weather,
        panel_tilt_deg=args.panel_tilt,
        panel_azimuth_deg=args.panel_azimuth,
        use_tilt_model=args.use_tilt_model,
        output_csv=args.out,
    )


def build_time_index(date_str: str, step_min: int) -> list[datetime]:
    start = datetime.strptime(date_str, "%Y-%m-%d")
    end = start + timedelta(days=1)
    timestamps = []
    t = start
    while t < end:
        timestamps.append(t)
        t += timedelta(minutes=step_min)
    return timestamps


def clamp_nonnegative(x: float) -> float:
    return max(0.0, x)


def deg2rad(x: float) -> float:
    return math.radians(x)


def solar_factor_from_zenith(zenith_deg: float) -> float:
    """
    Simplest relative PV factor:
        pv_factor = max(0, cos(zenith))
    This is enough for a first integration.
    """
    return clamp_nonnegative(math.cos(deg2rad(zenith_deg)))


def solar_vector_from_az_zen(azimuth_deg: float, zenith_deg: float) -> np.ndarray:
    """
    Build a simple unit sun vector in local coordinates:
    x = east, y = north, z = up
    azimuth convention assumed:
        0° = north, 90° = east, 180° = south, 270° = west
    """
    az = deg2rad(azimuth_deg)
    ze = deg2rad(zenith_deg)
    elevation = math.pi / 2 - ze

    x = math.cos(elevation) * math.sin(az)   # east
    y = math.cos(elevation) * math.cos(az)   # north
    z = math.sin(elevation)                  # up
    vec = np.array([x, y, z], dtype=float)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def panel_normal_vector(panel_tilt_deg: float, panel_azimuth_deg: float) -> np.ndarray:
    """
    Panel normal vector in local coordinates:
    x = east, y = north, z = up

    panel_tilt_deg:
        0° = flat facing sky
        90° = vertical

    panel_azimuth_deg:
        0° = north, 90° = east, 180° = south, 270° = west
    """
    tilt = deg2rad(panel_tilt_deg)
    az = deg2rad(panel_azimuth_deg)

    # Horizontal projection magnitude = sin(tilt)
    x = math.sin(tilt) * math.sin(az)   # east
    y = math.sin(tilt) * math.cos(az)   # north
    z = math.cos(tilt)                  # up

    vec = np.array([x, y, z], dtype=float)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def solar_factor_with_tilt(
    azimuth_deg: float,
    zenith_deg: float,
    panel_tilt_deg: float,
    panel_azimuth_deg: float,
) -> float:
    """
    Simple incidence-angle model:
        factor = max(0, dot(sun_vec, panel_normal))
    """
    sun_vec = solar_vector_from_az_zen(azimuth_deg, zenith_deg)
    panel_vec = panel_normal_vector(panel_tilt_deg, panel_azimuth_deg)
    return clamp_nonnegative(float(np.dot(sun_vec, panel_vec)))


def call_suspos_for_timestamp(ts: datetime, lat: float, lon: float) -> tuple[float, float]:
    """
    Call local sunpos.py and return (azimuth_deg, zenith_deg).

    Supports:
    - SunPosResult dataclass with .Azimuth / .Zenith
    - tuple/list fallback
    """
    TS = [ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second]
    result = sunpos(TS, lat, lon)

    # Case 1: your converted sunpos.py returns SunPosResult
    if hasattr(result, "Azimuth") and hasattr(result, "Zenith"):
        az = result.Azimuth
        ze = result.Zenith

        # These are usually numpy arrays of shape (1,)
        if isinstance(az, np.ndarray):
            az = float(az[0])
        else:
            az = float(az)

        if isinstance(ze, np.ndarray):
            ze = float(ze[0])
        else:
            ze = float(ze)

        return az, ze

    # Case 2: fallback if result is tuple/list
    if isinstance(result, (list, tuple)):
        if len(result) < 2:
            raise ValueError("sunpos() returned too few values.")
        return float(result[0]), float(result[1])

    raise TypeError(
        f"Unsupported return type from sunpos(): {type(result)}. "
        "Expected object with .Azimuth/.Zenith or tuple/list."
    )


def generate_profile(cfg: PVConfig) -> pd.DataFrame:
    timestamps = build_time_index(cfg.date_str, cfg.step_min)
    weather_mult = WEATHER_MULTIPLIERS[cfg.weather]

    rows = []
    for ts in timestamps:
        azimuth_deg, zenith_deg = call_suspos_for_timestamp(ts, cfg.lat, cfg.lon)
        elevation_deg = 90.0 - zenith_deg

        if cfg.use_tilt_model:
            pv_factor_raw = solar_factor_with_tilt(
                azimuth_deg=azimuth_deg,
                zenith_deg=zenith_deg,
                panel_tilt_deg=cfg.panel_tilt_deg,
                panel_azimuth_deg=cfg.panel_azimuth_deg,
            )
        else:
            pv_factor_raw = solar_factor_from_zenith(zenith_deg)

        pv_factor = pv_factor_raw * weather_mult
        pv_power_kw = cfg.pv_capacity_kw * pv_factor

        rows.append(
            {
                "timestamp": ts,
                "date": ts.date().isoformat(),
                "time": ts.strftime("%H:%M:%S"),
                "lat": cfg.lat,
                "lon": cfg.lon,
                "azimuth_deg": azimuth_deg,
                "zenith_deg": zenith_deg,
                "elevation_deg": elevation_deg,
                "weather_multiplier": weather_mult,
                "pv_factor_raw": pv_factor_raw,
                "pv_factor": pv_factor,
                "pv_capacity_kw": cfg.pv_capacity_kw,
                "pv_power_kw": pv_power_kw,
            }
        )

    df = pd.DataFrame(rows)
    return df


def save_profile(df: pd.DataFrame, output_csv: str) -> Path:
    out_path = Path(output_csv).resolve()
    df.to_csv(out_path, index=False)
    return out_path


def print_summary(df: pd.DataFrame, step_min: int) -> None:
    dt_hours = step_min / 60.0
    energy_kwh = df["pv_power_kw"].sum() * dt_hours

    print("\nSolar profile generated successfully.")
    print(f"Rows: {len(df)}")
    print(f"Peak PV power (kW): {df['pv_power_kw'].max():.3f}")
    print(f"Daily PV energy (kWh): {energy_kwh:.3f}")

    nonzero = df[df["pv_power_kw"] > 0]
    if not nonzero.empty:
        print(f"First solar output: {nonzero.iloc[0]['timestamp']}")
        print(f"Last solar output : {nonzero.iloc[-1]['timestamp']}")
    else:
        print("No solar output for this date/location/config.")


def main() -> None:
    cfg = parse_args()
    df = generate_profile(cfg)
    out_path = save_profile(df, cfg.output_csv)
    print_summary(df, cfg.step_min)
    print(f"Saved to: {out_path}")


if __name__ == "__main__":
    main()