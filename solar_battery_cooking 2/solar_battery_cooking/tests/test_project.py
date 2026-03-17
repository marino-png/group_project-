from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from compare_costs import compare_dispatch_costs
from data_generator import build_dataset
from main import _build_generation_config, _build_rule_settings
from lp_optimization import (
    OptParams,
    load_daily_nutrition_targets,
    solve_lp,
    solve_lp_with_meal_optimization,
)
from rule_based_sim import SystemParams, simulate_rule_based
from visualize import plot_daily_power_flows, plot_dispatch


class ValidationTests(unittest.TestCase):
    def test_main_config_json_merges_with_cli_overrides(self) -> None:
        payload = {
            "generation": {
                "start": "2026-01-02",
                "days": 2,
                "dt_minutes": 15,
                "seed": 10,
                "solar_profile_model": "suspos",
                "location_name": "Nigeria",
                "location_profiles_path": "data/reference/location_profiles.csv",
                "latitude_deg": None,
                "longitude_deg": None,
                "pv_tilt_deg": 30.0,
                "pv_azimuth_deg": 180.0,
                "weather_profile_mode": "monthly_climatology",
                "weather_profile_path": "data/reference/weather_profiles.csv",
                "latitude_hint": "temperate",
                "p_cold": 0.3,
                "p_medium": 0.4,
                "p_high": 0.3,
                "meal_mode": "db",
                "meal_db_path": "data/reference/meal_database.csv",
                "solar_day": "cloudy",
                "solar_day_seq": None,
                "solar_conditions_path": "data/reference/solar_day_conditions.csv",
            },
            "rule": {
                "outdir": "outputs/test_rule_json",
                "prefix": "json_rule",
                "pv_kw": 4.5,
                "batt_kwh": 9.0,
                "ch_kw": 3.0,
                "dis_kw": 3.0,
                "charge_eff": 0.92,
                "discharge_eff": 0.92,
                "soc_init": 0.5,
            },
        }
        args = SimpleNamespace(days=1, pv_kw=5.0)
        gen_cfg = _build_generation_config(args, payload)
        rule_cfg, outdir, prefix = _build_rule_settings(args, payload)

        self.assertEqual(gen_cfg.days, 1)
        self.assertEqual(gen_cfg.solar_day, "cloudy")
        self.assertEqual(gen_cfg.solar_profile_model, "suspos")
        self.assertEqual(gen_cfg.location_name, "Nigeria")
        self.assertAlmostEqual(rule_cfg.pv_kw, 5.0)
        self.assertAlmostEqual(rule_cfg.batt_kwh, 9.0)
        self.assertEqual(outdir, Path("outputs/test_rule_json"))
        self.assertEqual(prefix, "json_rule")

    def test_location_name_can_resolve_without_explicit_coordinates(self) -> None:
        df = build_dataset(
            start="2026-01-01",
            days=1,
            dt_minutes=60,
            seed=1,
            solar_profile_model="suspos",
            location_name="Nigeria",
            location_profiles_path="data/reference/location_profiles.csv",
            latitude_hint="tropical",
            p_cold=0.25,
            p_medium=0.50,
            p_high=0.25,
        )
        self.assertEqual(str(df["location_name"].iloc[0]), "Nigeria")
        self.assertAlmostEqual(float(df["latitude_deg"].iloc[0]), 9.0820, places=3)
        self.assertAlmostEqual(float(df["longitude_deg"].iloc[0]), 8.6753, places=3)

    def test_data_generator_rejects_zero_probability_sum(self) -> None:
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            build_dataset(
                start="2026-01-01",
                days=1,
                dt_minutes=15,
                seed=1,
                solar_profile_model="synthetic",
                latitude_hint="temperate",
                p_cold=0.0,
                p_medium=0.0,
                p_high=0.0,
                meal_mode="tier",
            )

    def test_main_config_json_rejects_unknown_rule_key(self) -> None:
        payload = {"rule": {"unknown_key": 1}}
        args = SimpleNamespace()
        with self.assertRaisesRegex(ValueError, "Unknown keys in section 'rule'"):
            _build_rule_settings(args, payload)

    def test_rule_based_rejects_invalid_soc_init(self) -> None:
        df = build_dataset(
            start="2026-01-01",
            days=1,
            dt_minutes=15,
            seed=1,
            solar_profile_model="synthetic",
            latitude_hint="temperate",
            p_cold=0.25,
            p_medium=0.50,
            p_high=0.25,
        )
        bad = SystemParams(
            pv_capacity_kw=2.0,
            batt_capacity_kwh=3.0,
            batt_charge_kw=1.5,
            batt_discharge_kw=1.5,
            charge_eff=0.92,
            discharge_eff=0.92,
            soc_init=1.2,
        )
        with self.assertRaisesRegex(ValueError, "soc_init"):
            simulate_rule_based(df, bad)

    def test_lp_rejects_invalid_soc_init(self) -> None:
        df = build_dataset(
            start="2026-01-01",
            days=1,
            dt_minutes=15,
            seed=1,
            solar_profile_model="synthetic",
            latitude_hint="temperate",
            p_cold=0.25,
            p_medium=0.50,
            p_high=0.25,
        )
        bad = OptParams(
            pv_capex_per_kw=0.0,
            batt_capex_per_kwh=0.0,
            charge_eff=0.92,
            discharge_eff=0.92,
            c_rate_per_h=0.5,
            soc_init_frac=1.2,
            cyclic_soc=False,
            shed_penalty_per_kwh=10_000.0,
        )
        with self.assertRaisesRegex(ValueError, "soc_init"):
            solve_lp(df, bad, pv_kw_fixed=2.0, batt_kwh_fixed=3.0)


class PlotAndCostTests(unittest.TestCase):
    def test_solar_condition_changes_pv_energy(self) -> None:
        sunny = build_dataset(
            start="2026-01-01",
            days=1,
            dt_minutes=15,
            seed=4,
            solar_profile_model="synthetic",
            latitude_hint="temperate",
            p_cold=0.25,
            p_medium=0.50,
            p_high=0.25,
            solar_day="sunny",
        )
        cloudy = build_dataset(
            start="2026-01-01",
            days=1,
            dt_minutes=15,
            seed=4,
            solar_profile_model="synthetic",
            latitude_hint="temperate",
            p_cold=0.25,
            p_medium=0.50,
            p_high=0.25,
            solar_day="cloudy",
        )
        self.assertGreater(sunny["pv_kwh_per_kw"].sum(), cloudy["pv_kwh_per_kw"].sum())

    def test_plot_dispatch_handles_missing_supply_columns(self) -> None:
        df = build_dataset(
            start="2026-01-01",
            days=1,
            dt_minutes=15,
            seed=1,
            solar_profile_model="synthetic",
            latitude_hint="temperate",
            p_cold=0.25,
            p_medium=0.50,
            p_high=0.25,
        )
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            plot_dispatch(df, outdir=outdir, prefix="smoke")
            self.assertTrue((outdir / "smoke_supply_stack.png").exists())
            generated = plot_daily_power_flows(df, outdir=outdir, prefix="smoke")
            self.assertGreaterEqual(len(generated), 1)

    def test_compare_costs_rule_vs_lp_same_meal(self) -> None:
        df = build_dataset(
            start="2026-01-01",
            days=1,
            dt_minutes=15,
            seed=2,
            solar_profile_model="synthetic",
            latitude_hint="temperate",
            p_cold=0.25,
            p_medium=0.50,
            p_high=0.25,
        )
        rb = simulate_rule_based(
            df,
            SystemParams(
                pv_capacity_kw=4.0,
                batt_capacity_kwh=8.0,
                batt_charge_kw=3.0,
                batt_discharge_kw=3.0,
                charge_eff=0.92,
                discharge_eff=0.92,
                soc_init=0.5,
            ),
        )
        lp, _ = solve_lp(
            df,
            OptParams(
                pv_capex_per_kw=0.0,
                batt_capex_per_kwh=0.0,
                charge_eff=0.92,
                discharge_eff=0.92,
                c_rate_per_h=0.5,
                soc_init_frac=0.5,
                cyclic_soc=True,
                shed_penalty_per_kwh=10_000.0,
            ),
            pv_kw_fixed=4.0,
            batt_kwh_fixed=8.0,
        )
        comp = compare_dispatch_costs(rb, lp)
        self.assertIn("rule", comp.index)
        self.assertIn("lp", comp.index)
        self.assertIn("lp_minus_rule", comp.index)
        self.assertTrue(np.isfinite(comp.loc["rule", "total_cost"]))
        self.assertTrue(np.isfinite(comp.loc["lp", "total_cost"]))
        self.assertAlmostEqual(
            comp.loc["lp_minus_rule", "total_cost"],
            comp.loc["lp", "total_cost"] - comp.loc["rule", "total_cost"],
            places=9,
        )

    def test_rule_reports_unmet_when_capacity_too_small(self) -> None:
        df = build_dataset(
            start="2026-01-01",
            days=1,
            dt_minutes=15,
            seed=3,
            solar_profile_model="synthetic",
            latitude_hint="temperate",
            p_cold=0.0,
            p_medium=0.0,
            p_high=1.0,
            meal_mode="tier",
        )
        rb = simulate_rule_based(
            df,
            SystemParams(
                pv_capacity_kw=0.2,
                batt_capacity_kwh=0.2,
                batt_charge_kw=0.2,
                batt_discharge_kw=0.2,
                charge_eff=0.92,
                discharge_eff=0.92,
                soc_init=0.5,
            ),
        )
        self.assertGreater(float(rb["lost_load_kwh"].sum()), 0.0)

    def test_lp_meal_optimization_outputs_plan(self) -> None:
        df = build_dataset(
            start="2026-01-01",
            days=1,
            dt_minutes=15,
            seed=5,
            solar_profile_model="synthetic",
            latitude_hint="temperate",
            p_cold=0.25,
            p_medium=0.50,
            p_high=0.25,
            meal_mode="db",
        )
        nutrition_targets = load_daily_nutrition_targets("configs/meal_targets.json")
        out, summary, meal_plan = solve_lp_with_meal_optimization(
            df,
            OptParams(
                pv_capex_per_kw=0.0,
                batt_capex_per_kwh=0.0,
                charge_eff=0.92,
                discharge_eff=0.92,
                c_rate_per_h=0.5,
                soc_init_frac=0.5,
                cyclic_soc=True,
                shed_penalty_per_kwh=10_000.0,
            ),
            meal_db_path="data/reference/meal_database.csv",
            nutrition_targets=nutrition_targets,
            pv_kw_fixed=4.0,
            batt_kwh_fixed=8.0,
        )
        self.assertFalse(meal_plan.empty)
        self.assertIn("chosen_meal_id", out.columns)
        self.assertIn("meal_cost", summary)

    def test_suspos_profile_varies_with_location(self) -> None:
        nigeria = build_dataset(
            start="2026-06-21",
            days=1,
            dt_minutes=60,
            seed=1,
            solar_profile_model="suspos",
            location_name="Nigeria",
            location_profiles_path="data/reference/location_profiles.csv",
            pv_tilt_deg=30.0,
            pv_azimuth_deg=180.0,
            weather_profile_mode="monthly_climatology",
            weather_profile_path="data/reference/weather_profiles.csv",
            latitude_hint="tropical",
            p_cold=0.25,
            p_medium=0.50,
            p_high=0.25,
        )
        abuja = build_dataset(
            start="2026-06-21",
            days=1,
            dt_minutes=60,
            seed=1,
            solar_profile_model="suspos",
            location_name="Abuja",
            location_profiles_path="data/reference/location_profiles.csv",
            pv_tilt_deg=25.0,
            pv_azimuth_deg=180.0,
            weather_profile_mode="monthly_climatology",
            weather_profile_path="data/reference/weather_profiles.csv",
            latitude_hint="tropical",
            p_cold=0.25,
            p_medium=0.50,
            p_high=0.25,
        )
        self.assertGreater(float(nigeria["pv_kw_per_kwp"].max()), 0.0)
        self.assertGreater(float(abuja["pv_kw_per_kwp"].max()), 0.0)
        self.assertNotAlmostEqual(
            float(nigeria["pv_kwh_per_kw"].sum()),
            float(abuja["pv_kwh_per_kw"].sum()),
            places=4,
        )

    def test_weather_profile_reduces_rainy_season_output_for_nigeria(self) -> None:
        dry = build_dataset(
            start="2026-01-15",
            days=1,
            dt_minutes=60,
            seed=1,
            solar_profile_model="suspos",
            location_name="Nigeria",
            location_profiles_path="data/reference/location_profiles.csv",
            weather_profile_mode="monthly_climatology",
            weather_profile_path="data/reference/weather_profiles.csv",
            latitude_hint="tropical",
            p_cold=0.25,
            p_medium=0.50,
            p_high=0.25,
        )
        rainy = build_dataset(
            start="2026-07-15",
            days=1,
            dt_minutes=60,
            seed=1,
            solar_profile_model="suspos",
            location_name="Nigeria",
            location_profiles_path="data/reference/location_profiles.csv",
            weather_profile_mode="monthly_climatology",
            weather_profile_path="data/reference/weather_profiles.csv",
            latitude_hint="tropical",
            p_cold=0.25,
            p_medium=0.50,
            p_high=0.25,
        )
        self.assertGreater(float(dry["pv_kwh_per_kw"].sum()), float(rainy["pv_kwh_per_kw"].sum()))


if __name__ == "__main__":
    unittest.main()
