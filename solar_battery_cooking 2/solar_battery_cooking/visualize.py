"""Visualize dispatch results and compute a few teaching metrics.

This script is designed to work with outputs from:
  - rule_based_sim.py
  - lp_optimization.py

It produces:
  - a stacked supply plot (PV direct, battery discharge)
  - a battery SoC plot

Example
  python visualize.py --dispatch outputs/rule_based_dispatch.csv --outdir figures
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def _series_or_zeros(dispatch: pd.DataFrame, col: str) -> np.ndarray:
    """Return a dispatch column as float array, or zeros if missing."""
    if col in dispatch.columns:
        return dispatch[col].to_numpy(dtype=float)
    return np.zeros(len(dispatch), dtype=float)


def _pv_generation_kwh(dispatch: pd.DataFrame) -> np.ndarray:
    """Return PV generation per timestep in kWh.

    Uses explicit `pv_kwh` when available; otherwise reconstructs from split
    components for compatibility with older/newer output files.
    """
    if "pv_kwh" in dispatch.columns:
        return dispatch["pv_kwh"].to_numpy(dtype=float)
    return (
        _series_or_zeros(dispatch, "pv_to_load_kwh")
        + _series_or_zeros(dispatch, "pv_to_batt_kwh")
        + _series_or_zeros(dispatch, "curtail_kwh")
    )


def compute_metrics(dispatch: pd.DataFrame) -> dict[str, float]:
    """Return a few easy to interpret metrics from a dispatch dataframe."""

    total_load = float(dispatch["demand_kwh"].sum())
    served_pv = float(dispatch["pv_to_load_kwh"].sum()) if "pv_to_load_kwh" in dispatch.columns else 0.0
    served_batt = float(dispatch["batt_to_load_kwh"].sum()) if "batt_to_load_kwh" in dispatch.columns else 0.0
    shed = float(dispatch["shed_kwh"].sum()) if "shed_kwh" in dispatch.columns else 0.0
    lost = float(dispatch["lost_load_kwh"].sum()) if "lost_load_kwh" in dispatch.columns else 0.0
    curtail = float(dispatch["curtail_kwh"].sum()) if "curtail_kwh" in dispatch.columns else 0.0

    if total_load > 0:
        self_suff = (served_pv + served_batt) / total_load
        unmet_share = (shed + lost) / total_load
    else:
        self_suff = 0.0
        unmet_share = 0.0

    return {
        "total_load_kwh": total_load,
        "served_by_pv_kwh": served_pv,
        "served_by_batt_kwh": served_batt,
        "unmet_kwh": shed + lost,
        "curtailment_kwh": curtail,
        "self_sufficiency": self_suff,
        "unmet_share": unmet_share,
    }


def _slice_by_date(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    """Optionally restrict dataframe to a [start, end] timestamp interval."""
    if start is None and end is None:
        return df
    start_ts = pd.Timestamp(start) if start else df.index.min()
    end_ts = pd.Timestamp(end) if end else df.index.max()
    return df.loc[(df.index >= start_ts) & (df.index <= end_ts)].copy()


def _plot_dispatch_panels(dispatch: pd.DataFrame, out_path: Path, *, title_suffix: str = "") -> None:
    """Render a simple three-panel daily energy overview."""
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    t = dispatch.index
    location_name = "Unknown location"
    if "location_name" in dispatch.columns and not dispatch["location_name"].empty:
        location_name = str(dispatch["location_name"].iloc[0])
    pv_available = _pv_generation_kwh(dispatch)
    demand = dispatch["demand_kwh"].to_numpy(dtype=float)
    pv_to_load = _series_or_zeros(dispatch, "pv_to_load_kwh")
    pv_to_batt = _series_or_zeros(dispatch, "pv_to_batt_kwh")
    batt_to_load = _series_or_zeros(dispatch, "batt_to_load_kwh")
    unmet = _series_or_zeros(dispatch, "shed_kwh") + _series_or_zeros(dispatch, "lost_load_kwh")
    charge = pv_to_batt
    discharge = batt_to_load

    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

    axes[0].fill_between(t, pv_available, color="#f6c945", alpha=0.55, label="Solar energy collected")
    axes[0].plot(t, pv_available, color="#c79200", linewidth=1.8)
    axes[0].step(t, demand, where="mid", color="#d95f02", linewidth=2.0, label="Cooking demand")
    axes[0].set_ylabel("Energy per step (kWh)")
    axes[0].set_title(f"{location_name}: daily solar collection vs cooking demand{title_suffix}")
    axes[0].legend(loc="upper right")
    axes[0].grid(axis="y", alpha=0.25)

    axes[1].bar(t, charge, width=0.018, color="#2ca25f", alpha=0.85, label="Battery charging")
    axes[1].bar(t, -discharge, width=0.018, color="#de2d26", alpha=0.85, label="Battery discharging")
    if np.any(unmet > 0):
        axes[1].bar(t, unmet, width=0.018, color="#222222", alpha=0.75, label="Unmet load")
    axes[1].axhline(0.0, color="#666666", linewidth=1.0)
    axes[1].set_ylabel("Energy per step (kWh)")
    axes[1].set_title(f"{location_name}: battery charging and discharging")
    axes[1].legend(loc="upper right")
    axes[1].grid(axis="y", alpha=0.25)

    if "soc_frac" in dispatch.columns:
        soc = dispatch["soc_frac"].to_numpy(dtype=float)
        axes[2].fill_between(t, soc, color="#6baed6", alpha=0.35)
        axes[2].plot(t, soc, color="#2171b5", label="Battery SoC", linewidth=2.0)
        axes[2].axhline(float(np.min(soc)), color="#2171b5", linestyle="--", linewidth=1.4, label="Lowest SoC")
        axes[2].set_ylabel("SoC fraction")
    elif "soc_kwh" in dispatch.columns:
        soc = dispatch["soc_kwh"].to_numpy(dtype=float)
        axes[2].fill_between(t, soc, color="#6baed6", alpha=0.35)
        axes[2].plot(t, soc, color="#2171b5", label="Battery energy", linewidth=2.0)
        axes[2].axhline(float(np.min(soc)), color="#2171b5", linestyle="--", linewidth=1.4, label="Lowest battery energy")
        axes[2].set_ylabel("SoC (kWh)")
    else:
        zeros = np.zeros(len(dispatch), dtype=float)
        axes[2].plot(t, zeros, color="#2171b5", label="Battery SoC", linewidth=2.0)
        axes[2].axhline(0.0, color="#2171b5", linestyle="--", linewidth=1.4, label="Lowest SoC")
        axes[2].set_ylabel("SoC fraction")
    axes[2].set_title(f"{location_name}: battery state of charge")
    axes[2].legend(loc="upper right")
    axes[2].tick_params(axis="x", rotation=30)
    axes[2].grid(axis="y", alpha=0.25)
    axes[2].set_xlabel("Time of day")

    locator = mdates.HourLocator(byhour=[0, 6, 9, 12, 15, 18, 21])
    formatter = mdates.DateFormatter("%H:%M")
    axes[2].xaxis.set_major_locator(locator)
    axes[2].xaxis.set_major_formatter(formatter)
    axes[2].tick_params(axis="x", rotation=0)

    fig.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def plot_dispatch(dispatch: pd.DataFrame, outdir: Path, prefix: str) -> None:
    """Create high-level supply stack and SoC plots for a dispatch dataframe."""
    outdir.mkdir(parents=True, exist_ok=True)
    _plot_dispatch_panels(dispatch, outdir / f"{prefix}_supply_stack.png")
    _plot_dispatch_panels(dispatch, outdir / f"{prefix}_soc.png")


def plot_daily_power_flows(dispatch: pd.DataFrame, outdir: Path, prefix: str) -> list[Path]:
    """Plot daily supply/storage/demand power flows and return generated file paths."""
    outdir.mkdir(parents=True, exist_ok=True)

    generated: list[Path] = []
    grouped = dispatch.groupby(dispatch.index.date, sort=True)
    for day, day_df in grouped:
        out_path = outdir / f"{prefix}_daily_flow_{day}.png"
        _plot_dispatch_panels(day_df, out_path, title_suffix=f" ({day})")
        generated.append(out_path)

    return generated


def plot_daily_meal_summary(dispatch: pd.DataFrame, outdir: Path, prefix: str) -> list[Path]:
    """Create daily meal-energy and nutrient summary charts when meal fields are present."""
    import matplotlib.pyplot as plt

    needed = {"meal_slot_id", "meal_name"}
    if not needed.issubset(dispatch.columns):
        return []

    outdir.mkdir(parents=True, exist_ok=True)
    daily_paths: list[Path] = []
    slot_df = dispatch.loc[dispatch["meal_slot_id"].astype(str) != "none"].copy()
    if slot_df.empty:
        return []
    if "day_id" not in slot_df.columns:
        slot_df["day_id"] = slot_df.index.date.astype(str)

    slot_summary = (
        slot_df.groupby(["day_id", "meal_slot_id", "meal", "meal_name"], as_index=False)
        .agg(
            demand_kwh=("demand_kwh", "sum"),
            calories_kcal=("calories_kcal", "max"),
            protein_g=("protein_g", "max"),
            fiber_g=("fiber_g", "max"),
            meal_cost_usd=("meal_cost_usd", "max"),
        )
        .sort_values(["day_id", "meal_slot_id"])
    )

    for day_id, day in slot_summary.groupby("day_id"):
        x = np.arange(len(day))
        labels = [f"{m}\n{n}" for m, n in zip(day["meal"], day["meal_name"])]

        fig, axes = plt.subplots(2, 1, figsize=(11, 7))
        axes[0].bar(x, day["demand_kwh"], color="tab:orange")
        axes[0].set_ylabel("Cooking energy (kWh)")
        axes[0].set_title(f"Daily meal cooking energy ({day_id})")
        axes[0].set_xticks(x, labels=labels, rotation=0)

        width = 0.2
        axes[1].bar(x - width, day["calories_kcal"], width=width, label="Calories (kcal)")
        axes[1].bar(x, day["protein_g"], width=width, label="Protein (g)")
        axes[1].bar(x + width, day["fiber_g"], width=width, label="Fiber (g)")
        axes[1].set_title("Meal nutrition summary")
        axes[1].set_xticks(x, labels=labels, rotation=0)
        axes[1].legend(loc="upper left")
        fig.tight_layout()

        out_path = outdir / f"{prefix}_daily_meals_{day_id}.png"
        fig.savefig(out_path, dpi=160)
        plt.close(fig)
        daily_paths.append(out_path)
    return daily_paths


def main() -> None:
    """CLI entry point for visualization/metric reporting."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dispatch", type=str, required=True, help="Dispatch CSV")
    p.add_argument("--start", type=str, default=None, help="Start timestamp slice")
    p.add_argument("--end", type=str, default=None, help="End timestamp slice")
    p.add_argument("--outdir", type=str, default="figures", help="Directory for plots")
    p.add_argument("--prefix", type=str, default="dispatch", help="Filename prefix")
    args = p.parse_args()

    df = pd.read_csv(args.dispatch, parse_dates=["timestamp"], index_col="timestamp")
    df = _slice_by_date(df, args.start, args.end)
    metrics = compute_metrics(df)

    outdir = Path(args.outdir)
    plot_dispatch(df, outdir=outdir, prefix=args.prefix)
    daily_paths = plot_daily_power_flows(df, outdir=outdir, prefix=args.prefix)
    meal_paths = plot_daily_meal_summary(df, outdir=outdir, prefix=args.prefix)

    print("Metrics")
    for k, v in metrics.items():
        if k.endswith("_kwh"):
            print(f"  {k}: {v:,.2f}")
        else:
            print(f"  {k}: {v:.3f}")
    print(f"Plots saved under: {outdir.resolve()}")
    print(f"Daily flow plots generated: {len(daily_paths)}")
    if meal_paths:
        print(f"Daily meal summary plots generated: {len(meal_paths)}")


if __name__ == "__main__":
    main()
