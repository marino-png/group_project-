# Project Structure and Extension Guide

## Architecture Overview

This repository is organized as a data-first, islanded (no-grid) modeling stack.

Primary entry point:
- `main.py`: minimal CLI to run `rule` and `lp` workflows end-to-end.

Modular package:
- `solar_cooking/models.py`: typed dataclass configs
- `solar_cooking/pipeline.py`: `run_rule_case` and `run_lp_case` orchestration
- `solar_cooking/__init__.py`: package exports

Core engines:
- `data_generator.py`: scenario timeseries generation
- `rule_based_sim.py`: deterministic dispatch
- `lp_optimization.py`: LP/MILP dispatch and planning
- `visualize.py`: figure generation
- `compare_costs.py`: rule vs LP cost comparison

## Configuration Files

- `configs/main_params.json`: unified run config for generation + rule + lp
- `configs/meal_targets.json`: nutrition constraints for meal optimization

Use:

```bash
python main.py rule --config configs/main_params.json
python main.py lp --config configs/main_params.json
```

## Data-First Extension Points

- `data/reference/solar_day_conditions.csv`: solar condition names and PV multipliers
- `data/reference/meal_database.csv`: meal catalog with cooking energy, nutrition, cost

Add/change data in these files first, then rerun models. Most scenario changes should not require code edits.

## Typical Workflow

1. Edit solar presets in `data/reference/solar_day_conditions.csv`.
2. Edit/add meals in `data/reference/meal_database.csv`.
3. Adjust run parameters in `configs/main_params.json`.
4. Run rule case for sufficiency screening.
5. Run LP case (`fixed`, `plan`, or `meal_opt`) for optimized benchmark/planning.
6. Review CSV outputs and generated figures in `outputs/.../figures`.

## Data Schema Notes

Meal DB required columns:
- `meal_id`
- `meal_name`
- `meal_type`
- `cook_energy_kwh`
- `calories_kcal`
- `protein_g`
- `carbs_g`
- `fat_g`
- `fiber_g`
- `meal_cost_usd`

Expected `meal_type` values:
- `breakfast`
- `lunch`
- `dinner`
- `any`

Optional numeric columns are supported and can be constrained through `configs/meal_targets.json`.

## Scenario Placeholders

- `examples/scenarios/sunny_day_example.json`
- `examples/scenarios/cloudy_day_example.json`
- `examples/scenarios/mixed_three_day_example.json`
