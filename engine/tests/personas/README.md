# Golden personas

Spec §11.2. Each file is a `PlanRequest` plus an `expect` object. `tests/test_personas.py` checks
the files are valid now; the engine is checked against `expect` in runbook Task 11. The files
double as API examples and demo presets.

| File                     | Persona                                                                    | Expect                                                                                                |
| ------------------------ | -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `maya.json`              | 30F, 168 cm, 70 kg, moderate, lifts, lose fat                              | `ok`; 1,710–1,890 kcal, 133–147 g protein; weights 20/20/5/15/15/15/10                                |
| `novice_recomp.json`     | 34M, 92 kg (BMI 29), beginner lifter, lose fat + build muscle              | `ok`; recomp, deficit 0–20%                                                                           |
| `marathon_fatloss.json`  | Spec §10 example request: lose fat + marathon, pescatarian, peanut allergy | `ok`; deficit only in base, maintenance+ from peak; weights 20/20/13/13/13/13/8 → 20/20/17/12/12/12/7 |
| `wedding_8wk.json`       | 29F, 72 kg, wants −9 kg in 8 weeks                                         | `clamped`; projected kg and reachable date                                                            |
| `hybrid.json`            | 28M, strength + endurance                                                  | `ok`; maintenance, Matrix C carbs by day type                                                         |
| `glp1_t2d_strength.json` | 52F on a GLP-1 + metformin, T2D, lifts                                     | `rd_review`; protein ≥ 25, micro/carb/fiber ≥ 20                                                      |
| `vegan_muscle.json`      | 26M vegan, build muscle                                                    | `ok`; leucine-blending rule, B12 warning                                                              |
| `under18.json`           | 16-year-old, lose fat                                                      | `blocked`, no targets (`GUARD.UNDER_18`)                                                              |
| `pregnant.json`          | Pregnant, lose fat                                                         | `blocked`, no targets (`GUARD.PREGNANCY`)                                                             |
| `goal_bmi_low.json`      | Goal 50 kg at 168 cm (BMI 17.7)                                            | `blocked`, no targets (`GUARD.ED_RISK`)                                                               |

## `expect` fields

- `status`: expected `PlanResponse.status`.
- `no_targets`: the plan returns no phases or targets (blocked cases).
- `phases[]`: `name` (omit for every phase), allowed `energy` directions, `targets` that hold on
  every day type, and `targets_by_day_type`. Target keys are `PlanResponse` day-target fields
  (`kcal`, `protein_g`, …) or derived values (`carb_g_per_kg`, `deficit_pct_tdee`), each a
  `{min, max}` range.
- `deficit_only_in`: the only phases allowed to run a deficit.
- `feasibility`: expected status and whether `projected_kg` / `reachable_date` are present.
- `required_rule_ids`: must appear in the plan's `rule_ids`.
- `required_warnings` / `required_blocks`: rule ids that must appear in `safety.warnings` /
  `safety.blocks`.
- `loam_score_weights[]`: exact weights per phase (`phase` omitted = every phase), in the order
  energy, protein, carb, fiber, micro, pattern, moderation.
- `loam_score_weight_minimums`: medical floors (spec §7b.2).
