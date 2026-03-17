# Reference Data Files

## `meal_database.csv`
CSV meal catalog used by:
- `data_generator.py` (when `meal_mode=db`)
- `lp_optimization.py` meal optimization mode
- `main.py` via `configs/main_params.json`

The bundled default database is now oriented to a Nigeria household scenario,
including meals such as akamu and akara, yam and egg sauce, jollof rice,
egusi soup, amala with gbegiri/ewedu, and rice with stew.

Required columns:
- `meal_id`
- `meal_name`
- `meal_type` (`breakfast`, `lunch`, `dinner`, or `any`)
- `cook_energy_kwh`
- `calories_kcal`
- `protein_g`
- `carbs_g`
- `fat_g`
- `fiber_g`
- `meal_cost_usd`

Optional columns can be added.
- Numeric optional columns can be constrained in `configs/meal_targets.json`.
- If an `enabled` column exists, use `1` for active meals and `0` to disable meals without deleting rows.

Maintenance tips:
- Keep `meal_id` unique and stable.
- Use consistent units across all rows.

## `solar_day_conditions.csv`
Solar day presets used by `data_generator.py`.

Required columns:
- `condition`
- `pv_multiplier`

`pv_multiplier` scales the synthetic PV shape to represent conditions like sunny/cloudy/storm.

Maintenance tips:
- Keep `condition` names lowercase/simple so they are easy to reference in CLI and JSON.
- Add new rows instead of editing historical conditions when you need versioned scenarios.

## `location_profiles.csv`
Named region/city presets used to resolve `location_name` into coordinates.

Required columns:
- `name`
- `latitude_deg`
- `longitude_deg`

## `weather_profiles.csv`
Monthly weather attenuation presets applied after `suspos` solar geometry.

Required columns:
- `location`
- `month`
- `weather_factor`
