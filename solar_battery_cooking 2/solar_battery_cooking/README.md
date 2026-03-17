# Solar + Battery + Meal Co-Optimisation

This project models **islanded cooking energy systems** only (no grid import/export in code, optimization, or plots).
It combines solar generation, battery dispatch, and meal data to study:
- capacity sufficiency of PV + battery
- dispatch quality (rule-based vs LP)
- meal-energy and nutrition-aware optimization

## Quick Start

Install dependencies:

```bash
pip install -r requirements.txt
```

Run with the default 1-day, 15-minute test case:

```bash
python main.py rule
python main.py lp
python main.py lp --mode meal_opt
python main.py rule --latitude-deg 51.5074 --longitude-deg -0.1278
```

Clean all generated artifacts from previous runs:

```bash
bash clean.sh
```

## Main Entry Point

`main.py` is the primary interface.

- `rule`: data generation + rule dispatch + plots
- `lp`: data generation + LP solve + plots
  - `--mode fixed`: fixed PV/battery sizes
  - `--mode plan`: optimize PV/battery capacities
  - `--mode meal_opt`: optimize dispatch + meal choices

Outputs are written to:
- `outputs/main_rule`
- `outputs/main_lp`

## Central Parameter JSON

Use `configs/main_params.json` to define all parameters in one place:
- `generation`: time horizon, timestep, solar condition, meal data source
- `rule`: rule-based parameters and output naming
- `lp`: LP/MILP parameters and output naming

Solar generation now supports two input models:
- `solar_profile_model="suspos"`: compute solar geometry from latitude/longitude via `suspos.py`
- `solar_profile_model="synthetic"`: keep the legacy teaching/demo profile

Location resolution:
- `location_name` can now resolve a named preset such as `Nigeria`, `Abuja`, `Lagos`, or `Kano`
- explicit `latitude_deg` and `longitude_deg` still override named presets

For `suspos`, provide:
- `location_name` or (`latitude_deg` + `longitude_deg`)
- optional panel orientation via `pv_tilt_deg` and `pv_azimuth_deg`

Weather adjustment:
- `weather_profile_mode="monthly_climatology"` applies a monthly attenuation factor after the `suspos` clear-sky geometry
- default reference data includes monthly profiles for `Nigeria`, `Abuja`, `Lagos`, and `Kano`

Run with config:

```bash
python main.py rule --config configs/main_params.json
python main.py lp --config configs/main_params.json
python main.py rule --location-name Nigeria --solar-profile-model suspos
python main.py rule --location-name Lagos --solar-profile-model suspos --weather-profile-mode monthly_climatology
python main.py rule --latitude-deg 35.6762 --longitude-deg 139.6503 --pv-tilt-deg 25 --pv-azimuth-deg 180
```

Override specific values from CLI:

```bash
python main.py lp --config configs/main_params.json --mode meal_opt --prefix lp_meal
```

Unknown keys in `rule`/`lp` config sections now fail fast with a clear error.

## Project Components

- `main.py`: minimal CLI for rule and LP runs.
- `solar_cooking/`: modular package API.
  - `models.py`: typed configs (`GenerationConfig`, `RuleConfig`, `LPConfig`)
  - `pipeline.py`: orchestration (`run_rule_case`, `run_lp_case`)
- `data_generator.py`: synthetic timeseries generator from solar/meal references.
- `suspos.py`: PSA+ solar-position model used by the location-based PV input path.
- `location_profiles.py`: resolves named regions/cities to coordinates.
- `weather_profiles.py`: applies monthly weather attenuation to PV output.
- `rule_based_sim.py`: chronological dispatch (PV -> battery -> unmet).
- `lp_optimization.py`: LP/MILP solvers.
- `visualize.py`: supply stack, SoC, daily power flow, and daily meal plots.
- `compare_costs.py`: compares rule vs LP cost metrics on same-meal dispatch outputs.

## Data And Config Files

- `data/reference/solar_day_conditions.csv`: solar day condition multipliers.
- `data/reference/meal_database.csv`: maintainable meal catalog.
- `configs/meal_targets.json`: nutrition constraints for meal optimization.
- `configs/main_params.json`: unified run parameters.

## Dataset Maintenance

Add solar condition:
1. Edit `data/reference/solar_day_conditions.csv`.
2. Add a new `condition` + `pv_multiplier` row.
3. Use `--solar-day <condition>` or `solar_day` in JSON.

Add meal:
1. Edit `data/reference/meal_database.csv`.
2. Add required fields and set `enabled=1` if present.
3. Regenerate and rerun.

Change nutrition targets:
1. Edit `configs/meal_targets.json`.
2. Update `daily_targets`.
3. Run `main.py lp --mode meal_opt`.

## Visual Outputs

Typical files include:
- `<prefix>_supply_stack.png`
- `<prefix>_soc.png`
- `<prefix>_daily_flow_<date>.png`
- `<prefix>_daily_meals_<date>.png` (meal columns required)

## Notes

- Scope is intentionally off-grid/islanded.
- This is an extension-oriented prototype, not a calibrated digital twin.
