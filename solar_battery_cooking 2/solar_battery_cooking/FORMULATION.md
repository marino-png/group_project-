# LP Formulation (Islanded, No-Grid)

This file describes the optimization implemented in `lp_optimization.py`.

Scope:
- islanded system only
- no grid import/export variables
- all energy variables are timestep energy in kWh

## Problem Modes

- `fixed`: optimize dispatch with fixed `S_pv`, `S_b`.
- `plan`: optimize dispatch and capacities `S_pv`, `S_b`.
- `meal_opt`: optimize dispatch and discrete meal selections (MILP).

## Indices

- timesteps `t = 0..T-1`

## Inputs

From generated data:
- `L_t`: cooking demand in kWh at timestep `t`
- `G_t`: PV availability per installed kW in kWh/kW at timestep `t` (`pv_kwh_per_kw[t]`)

Model parameters:
- `η_c`: charge efficiency
- `η_d`: discharge efficiency
- `r`: battery C-rate (1/h)
- `Δt`: timestep duration (h)
- `M`: unmet-load penalty per kWh

Optional economic parameters:
- `C_pv`: PV capacity cost coefficient
- `C_b`: battery capacity cost coefficient

## Decision Variables

Sizing:
- `S_pv` (kW), PV size
- `S_b` (kWh), battery size

Dispatch per timestep:
- `x_t`: PV to load
- `y_t`: PV to battery
- `z_t`: curtailed PV
- `d_t`: battery withdrawal (before discharge efficiency)
- `b_t`: battery to load
- `u_t`: unmet load
- `e_t`: battery state of charge

Meal optimization extension:
- binary meal selection variables per meal slot and candidate meal

## Constraints

PV split:

`x_t + y_t + z_t = G_t * S_pv`

Load balance:

`x_t + b_t + u_t = L_t`

Battery discharge efficiency:

`b_t = η_d * d_t`

State transition:

`e_{t+1} = e_t + η_c * y_t - d_t`

Battery bounds:

`0 ≤ e_t ≤ S_b`

Charge/discharge power bounds:

`y_t ≤ r * S_b * Δt`

`d_t ≤ r * S_b * Δt`

Optional cyclic SoC:

`e_T = e_0`

Meal extension constraints:
- exactly one meal per slot (breakfast/lunch/dinner) from meal DB candidates
- selected meal energy contributes to demand
- optional daily nutrition bounds from `configs/meal_targets.json`

## Objectives

Base objective:

`min C_pv * S_pv + C_b * S_b + Σ_t M * u_t`

In meal optimization mode, meal monetary cost is also included with weight:

`+ w_meal * (total meal cost)`

## Relation To Rule-Based Model

`rule_based_sim.py` uses deterministic chronological dispatch with fixed capacities.
It does not optimize decisions, and it reports unmet demand directly when capacity is insufficient.
