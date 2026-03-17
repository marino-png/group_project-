"""
Converted to Python from MATLAB.
Original file: Example.m (MATLAB)

This script demonstrates how to call sunpos() and how to plot a daily sun path.
"""

from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt

from sunpos import sunpos


def main() -> None:
    # Define location (same as MATLAB example)
    lat = 51.512028   # degrees
    lon = -0.116361   # degrees

    # Example 1: evaluate sun position for a single timestamp
    ts = [2020, 5, 15, 18, 47, 5.4]
    sp = sunpos(ts, lat, lon)

    # Print selected outputs (vectorized arrays; index 0 for the single timestamp)
    print("Example 1 (single timestamp)")
    print(f"  Azimuth [deg] : {sp.Azimuth[0]:.4f}")
    print(f"  Zenith  [deg] : {sp.Zenith[0]:.4f}")
    print(f"  SunVec        : {sp.SunVec[0]}")

    # Example 2: sun path angles over a day (hourly)
    hours = np.arange(1, 25, dtype=float)
    ts_day = np.column_stack(
        (
            np.full_like(hours, 2024.0),
            np.full_like(hours, 6.0),
            np.full_like(hours, 1.0),
            hours,
            np.zeros_like(hours),
            np.zeros_like(hours),
        )
    )
    sp_day = sunpos(ts_day, lat, lon)

    # Plot elevation angle = 90 - Zenith
    elevation = 90.0 - sp_day.Zenith
    plt.plot(sp_day.Azimuth, elevation, ".-")
    plt.xlabel("Azimuth angle, from North [degrees]")
    plt.ylabel("Elevation angle, from Horizon [degrees]")
    plt.grid(True)
    plt.title("Daily Sun Path (PSA+)")

    plt.show()


if __name__ == "__main__":
    main()
