"""
Converted to Python from MATLAB.
Original file: sunpos.m (MATLAB)
Original author & reference (per source file header): A. Bonanos; algorithm described in
Blanco, Milidonis, Bonanos (2020) "Updating the PSA sun position algorithm" (Solar Energy).

This module implements the PSA+ solar position algorithm as present in the provided MATLAB code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Union

import numpy as np

ArrayLike = Union[Sequence[float], np.ndarray]


@dataclass(frozen=True)
class SunPosResult:
    """Result container mirroring the MATLAB struct fields (vectorized).

    Fields are NumPy arrays (shape (N,)) except SunVec (shape (N,3)).

    Note: The original MATLAB example accesses .Azimuth and .Zenith.
    For compatibility with other variants, aliases ZenithAngle(_rad) are also provided.
    """

    ELong: np.ndarray
    ELong_deg: np.ndarray
    EObl: np.ndarray
    EObl_deg: np.ndarray
    RightAscension: np.ndarray
    Declination: np.ndarray
    HourAngle: np.ndarray
    Zenith_rad: np.ndarray
    Azimuth_rad: np.ndarray
    Zenith: np.ndarray
    Azimuth: np.ndarray
    SunVec: np.ndarray

    # ---- Aliases to match sample-output naming variations ----
    @property
    def ZenithAngle_rad(self) -> np.ndarray:  # noqa: N802
        return self.Zenith_rad

    @property
    def ZenithAngle(self) -> np.ndarray:  # noqa: N802
        return self.Zenith


def _as_ts_matrix(ts: ArrayLike) -> np.ndarray:
    """Coerce TS into an (N,6) float array."""
    arr = np.asarray(ts, dtype=float)
    if arr.ndim == 1:
        if arr.shape[0] != 6:
            raise ValueError(f"TS must have 6 elements, got shape {arr.shape}")
        arr = arr.reshape(1, 6)
    elif arr.ndim == 2:
        if arr.shape[1] != 6:
            raise ValueError(f"TS must be Nx6, got shape {arr.shape}")
    else:
        raise ValueError(f"TS must be 1D or 2D array-like, got ndim={arr.ndim}")
    return arr


def _elapsed_julian_days(ts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Port of the MATLAB nested function ElapsedJulianDays(TS).

    Returns:
        EJD: elapsed Julian days since 2000-01-01 12:00 (J2000.0)
        DecimalHours: decimal hours of day in local time (as in the MATLAB code)
    """
    year = ts[:, 0]
    month = ts[:, 1]
    day = ts[:, 2]
    hour = ts[:, 3]
    minute = ts[:, 4]
    second = ts[:, 5]

    decimal_hours = hour + minute / 60.0 + second / 3600.0

    # MATLAB fix() rounds toward zero. np.trunc does the same element-wise.
    fix = np.trunc

    a = fix((month - 14.0) / 12.0)
    julian_date = (
        fix((1461.0 * (year + 4800.0 + a)) / 4.0)
        + fix((367.0 * (month - 2.0 - 12.0 * a)) / 12.0)
        - fix(3.0 * (fix((year + 4900.0 + a) / 100.0)) / 4.0)
        + day
        - 32075.5
        + decimal_hours / 24.0
    )

    ejd = julian_date - 2451545.0  # elapsed days since J2000.0 (2000-01-01 12:00)
    return ejd, decimal_hours


def sunpos(ts: ArrayLike, lat_deg: float, lon_deg: float) -> SunPosResult:
    """Evaluate PSA+ sun position algorithm.

    Args:
        ts: timestamp(s) as [Year, Month, Day, Hour, Minute, Second] for one row,
            or an Nx6 matrix for multiple timestamps. Matches the MATLAB code.
        lat_deg: latitude in degrees.
        lon_deg: longitude in degrees (East positive, West negative), consistent with MATLAB code.

    Returns:
        SunPosResult with fields compatible with the MATLAB struct.

    Notes:
        - This is a direct port of the provided MATLAB implementation.
        - The algorithm uses a fixed set of empirical coefficients (validity range: 2020–2050 per reference).
    """
    ts_mat = _as_ts_matrix(ts)
    ejd, decimal_hours = _elapsed_julian_days(ts_mat)

    # Ecliptic coordinates
    d_omega = 2.267127827e00 - 9.300339267e-04 * ejd
    d_mean_longitude = 4.895036035e00 + 1.720279602e-02 * ejd
    d_mean_anomaly = 6.239468336e00 + 1.720200135e-02 * ejd

    e_long = (
        d_mean_longitude
        + 3.338320972e-02 * np.sin(d_mean_anomaly)
        + 3.497596876e-04 * np.sin(2.0 * d_mean_anomaly)
        - 1.544353226e-04
        - 8.689729360e-06 * np.sin(d_omega)
    )
    e_long_deg = np.rad2deg(e_long)

    e_obl = 4.090904909e-01 - 6.213605399e-09 * ejd + 4.418094944e-05 * np.cos(d_omega)
    e_obl_deg = np.rad2deg(e_obl)

    # Celestial coordinates
    y1 = np.cos(e_obl) * np.sin(e_long)
    x1 = np.cos(e_long)
    right_ascension = np.arctan2(y1, x1)
    right_ascension = np.where(right_ascension < 0.0, right_ascension + 2.0 * np.pi, right_ascension)
    declination = np.arcsin(np.sin(e_obl) * np.sin(e_long))

    # Topocentric coordinates
    gmst = 6.697096103e00 + 6.570984737e-02 * ejd + decimal_hours
    lmst = np.deg2rad(gmst * 15.0 + lon_deg)
    hour_angle = lmst - right_ascension

    lat_rad = np.deg2rad(lat_deg)

    zenith_rad = np.arccos(
        np.cos(lat_rad) * np.cos(hour_angle) * np.cos(declination) + np.sin(declination) * np.sin(lat_rad)
    )

    y2 = -np.sin(hour_angle)
    x2 = np.tan(declination) * np.cos(lat_rad) - np.sin(lat_rad) * np.cos(hour_angle)
    azimuth_rad = np.arctan2(y2, x2)
    azimuth_rad = np.where(azimuth_rad < 0.0, azimuth_rad + 2.0 * np.pi, azimuth_rad)

    # Parallax correction
    zenith_rad = zenith_rad + (6371.01 / 149597870.7) * np.sin(zenith_rad)

    zenith = np.rad2deg(zenith_rad)
    azimuth = np.rad2deg(azimuth_rad)

    sunvec = np.column_stack(
        (
            np.sin(azimuth_rad) * np.sin(zenith_rad),  # east
            np.cos(azimuth_rad) * np.sin(zenith_rad),  # north
            np.cos(zenith_rad),  # zenith (up)
        )
    )

    return SunPosResult(
        ELong=e_long,
        ELong_deg=e_long_deg,
        EObl=e_obl,
        EObl_deg=e_obl_deg,
        RightAscension=right_ascension,
        Declination=declination,
        HourAngle=hour_angle,
        Zenith_rad=zenith_rad,
        Azimuth_rad=azimuth_rad,
        Zenith=zenith,
        Azimuth=azimuth,
        SunVec=sunvec,
    )
