"""Sample-day composer (spec §5 timing, §7.4 ranked foods; knowledge in compose.yaml).

1. Template: the day type's meals (COMPOSE.MEALS.*), each with an energy share. Protein meals aim
   for TIMING.PROTEIN_PER_MEAL; the pre-session meal aims for TIMING.PRE_SESSION_CARBS.
2. Fill: each meal role (protein, carb, vegetable, fruit, fat) takes the best-ranked food from
   its groups (foods.rank, so hard filters, pre-race exclusions and the taste re-rank all apply)
   that isn't already in the day. Foods missing kcal or a macro are skipped, never counted as 0.
3. Repair: every food starts at its minimum portion; portions then move one step at a time to
   whichever change most reduces the error (COMPOSE.SEARCH). The error is a sum of squares of
   linear terms over box-bounded portions, so this greedy descent doesn't stall in a bad corner.

compose() is pure: the caller passes the plan, profile, preferences, constraints, KB and foods.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, get_args

from nuri_reco import explain, foods
from nuri_reco.foods import Food
from nuri_reco.kb import KnowledgeBase, Rule
from nuri_reco.models import (
    Constraints,
    DayType,
    FoodContext,
    FoodRecommendation,
    Macro,
    Meal,
    MealItem,
    Nutrients,
    PlanResponse,
    Preferences,
    Profile,
    SampleDay,
)

MACROS: tuple[Macro, ...] = get_args(Macro)
Totals = dict[str, float]
# foods.json per-100 g field for each macro.
FIELDS = {"kcal": "energy_kcal", "protein_g": "protein_g", "carb_g": "carb_g", "fat_g": "fat_g"}


def _x(rule: Rule) -> dict[str, Any]:
    return rule.model_extra or {}


@dataclass
class _Meal:
    slot: str
    kcal_share: float
    protein_target: float | None
    carb_range: tuple[float, float] | None
    fiber_cap: float | None


@dataclass
class _Item:
    meal: int
    role: str
    food: Food
    rec: FoodRecommendation
    per_g: dict[str, float]
    # Fiber per gram; None when unknown (it then can't go in a fiber-capped meal).
    fiber_per_g: float | None
    low: float
    high: float
    grams: float


def _template(kb: KnowledgeBase, day_type: str) -> Rule:
    for rule in kb.compose.templates:
        if day_type in _x(rule)["day_types"]:
            return rule
    raise ValueError(f"no meal template for day type {day_type!r}")


def _timing(kb: KnowledgeBase, rule_id: str) -> dict[str, Any]:
    return _x(kb.rules[rule_id])


def _meals(template: Rule, profile: Profile, kb: KnowledgeBase) -> list[_Meal]:
    per_meal = _timing(kb, "TIMING.PROTEIN_PER_MEAL")
    bounds = per_meal["protein_g_per_meal"]
    protein = min(
        max(per_meal["protein_g_per_kg_per_meal"] * profile.weight_kg, bounds["min"]),
        bounds["max"],
    )
    pre = _timing(kb, "TIMING.PRE_SESSION_CARBS")["carb_g_per_kg"]
    carbs = (pre["min"] * profile.weight_kg, pre["max"] * profile.weight_kg)
    fiber_cap = _x(template).get("pre_session_max_fiber_g")
    return [
        _Meal(
            slot=m["slot"],
            kcal_share=m["kcal_pct"] / 100,
            protein_target=protein if m["protein_meal"] else None,
            carb_range=carbs if m["slot"] == "pre_session" else None,
            fiber_cap=fiber_cap if m["slot"] == "pre_session" else None,
        )
        for m in _x(template)["meals"]
    ]


def _per_g(food: Food) -> dict[str, float] | None:
    """kcal and macros per gram, or None if any is missing (invariant 7)."""
    per_100g = food["per_100g"]
    values = {m: per_100g[FIELDS[m]] for m in MACROS}
    if any(v is None for v in values.values()):
        return None
    return {m: float(v) / 100 for m, v in values.items()}


def _fits_role(role: str, per_g: dict[str, float], roles: dict[str, Any]) -> bool:
    kcal = per_g["kcal"]
    if kcal <= 0:
        return False
    if role == "protein":
        return per_g["protein_g"] / kcal * 100 >= float(roles["protein_min_g_per_100kcal"])
    if role == "carb":
        return per_g["carb_g"] * 4 / kcal * 100 >= float(roles["carb_min_pct_energy"])
    if role == "fat":
        return per_g["fat_g"] * 9 / kcal * 100 >= float(roles["fat_min_pct_energy"])
    return True


def _portion_range(
    food: Food, per_g: dict[str, float], portions: dict[str, Any]
) -> tuple[float, float]:
    g = portions["groups_g"].get(food["group"], portions["default_g"])
    high = float(g["max"])
    if per_g["kcal"] > 0:
        high = min(high, portions["max_item_kcal"] / per_g["kcal"])
    return float(g["min"]), max(high, float(g["min"]))


class _Picker:
    """Hands out the best-ranked unused food for a meal role, one at a time."""

    def __init__(
        self,
        meals: list[_Meal],
        ranked: dict[str, list[FoodRecommendation]],
        by_key: dict[str, Food],
        kb: KnowledgeBase,
    ) -> None:
        self.meals, self.ranked, self.by_key = meals, ranked, by_key
        self.roles, self.portions = _x(kb.compose.roles), _x(kb.compose.portions)
        self.heads = _x(kb.rules["FOOD.RANK.DIVERSITY_RULES"])["two_word_heads"]
        self.used: set[str] = set()

    def next(self, meal: int, role: str, fiber_g: float = 0.0) -> _Item | None:
        """The next food for a meal role; `fiber_g` is the fiber already in the meal."""
        slot, cap = self.meals[meal].slot, self.meals[meal].fiber_cap
        groups = self.roles["slots"][slot][role]
        for rec in self.ranked[self.roles["rank_slots"][slot]]:
            food = self.by_key[rec.key]
            name = foods.base_name(food, self.heads)
            if food["group"] not in groups or name in self.used:
                continue
            per_g = _per_g(food)
            if per_g is None or not _fits_role(role, per_g, self.roles):
                continue
            fiber = food["per_100g"]["fiber_g"]
            fiber_per_g = None if fiber is None else float(fiber) / 100
            low, high = _portion_range(food, per_g, self.portions)
            if cap is not None and (fiber_per_g is None or fiber_g + low * fiber_per_g > cap):
                continue
            self.used.add(name)
            return _Item(meal, role, food, rec, per_g, fiber_per_g, low, high, low)
        return None

    def fill(self) -> list[_Item]:
        items: list[_Item] = []
        for i, meal in enumerate(self.meals):
            fiber = 0.0
            for role in self.roles["slots"][meal.slot]:
                item = self.next(i, role, fiber)
                if item is not None:
                    items.append(item)
                    fiber += item.low * (item.fiber_per_g or 0.0)
        return items


class _Error:
    """The COMPOSE.SEARCH error for a set of portions; totals are kept so a move is cheap."""

    def __init__(
        self, items: list[_Item], meals: list[_Meal], targets: dict[str, float], kb: KnowledgeBase
    ) -> None:
        self.items, self.meals, self.targets = items, meals, targets
        self.w: dict[str, float] = _x(kb.compose.search)["weights"]
        self.day: Totals = {m: sum(it.grams * it.per_g[m] for it in items) for m in MACROS}
        self.meal: list[Totals] = [
            {m: sum(it.grams * it.per_g[m] for it in items if it.meal == i) for m in MACROS}
            for i in range(len(meals))
        ]
        self.fiber = [
            sum(it.grams * (it.fiber_per_g or 0.0) for it in items if it.meal == i)
            for i in range(len(meals))
        ]

    def allowed(self, item: _Item, delta: float) -> bool:
        """Within the food's portion range and the meal's fiber cap."""
        if not item.low <= item.grams + delta <= item.high:
            return False
        cap = self.meals[item.meal].fiber_cap
        if cap is None or delta <= 0:
            return True
        return self.fiber[item.meal] + delta * (item.fiber_per_g or 0.0) <= cap

    def _meal_terms(self, i: int, totals: Totals) -> float:
        meal, kcal_target = self.meals[i], self.targets["kcal"]
        err = (
            self.w["meal_share"]
            * ((totals["kcal"] - meal.kcal_share * kcal_target) / kcal_target) ** 2
        )
        if meal.protein_target:
            short = max(0.0, meal.protein_target - totals["protein_g"]) / meal.protein_target
            err += self.w["meal_protein"] * short**2
        if meal.carb_range:
            low, high = meal.carb_range
            miss = max(0.0, low - totals["carb_g"], totals["carb_g"] - high) / low
            err += self.w["pre_session_carbs"] * miss**2
        return err

    def _day_terms(self, totals: Totals) -> float:
        return self.w["day"] * sum(
            ((totals[m] - self.targets[m]) / self.targets[m]) ** 2 for m in MACROS
        )

    def total(self) -> float:
        return self._day_terms(self.day) + sum(
            self._meal_terms(i, t) for i, t in enumerate(self.meal)
        )

    def after(self, item: _Item, delta: float) -> float:
        """The error if `item` moved by `delta` grams."""
        day: Totals = {m: self.day[m] + delta * item.per_g[m] for m in MACROS}
        meal: Totals = {m: self.meal[item.meal][m] + delta * item.per_g[m] for m in MACROS}
        return (
            self._day_terms(day)
            + sum(self._meal_terms(i, t) for i, t in enumerate(self.meal) if i != item.meal)
            + self._meal_terms(item.meal, meal)
        )

    def add(self, item: _Item) -> None:
        self.items.append(item)
        item.grams, grams = 0.0, item.grams
        self.move(item, grams)

    def remove(self, item: _Item) -> None:
        self.move(item, -item.grams)
        self.items.remove(item)

    def move(self, item: _Item, delta: float) -> None:
        item.grams += delta
        for m in MACROS:
            self.day[m] += delta * item.per_g[m]
            self.meal[item.meal][m] += delta * item.per_g[m]
        self.fiber[item.meal] += delta * (item.fiber_per_g or 0.0)


def _descend(error: _Error, search: dict[str, Any], steps_left: int) -> int:
    """Greedy portion moves, coarse steps first; returns the steps left."""
    current = error.total()
    for step in search["steps_g"]:
        while steps_left > 0:
            best: tuple[float, _Item, float] | None = None
            for item in error.items:
                for delta in (step, -step):
                    if not error.allowed(item, delta):
                        continue
                    value = error.after(item, delta)
                    if value < current - 1e-12 and (best is None or value < best[0]):
                        best = (value, item, delta)
            if best is None:
                break
            current, item, delta = best
            error.move(item, delta)
            steps_left -= 1
    return steps_left


def _capped(error: _Error, step: float, exhausted: set[tuple[int, str]]) -> _Item | None:
    """The food at its maximum portion whose next step would cut the error most, skipping
    meal roles with no foods left to add."""
    current, best = error.total(), None
    for item in error.items:
        if error.allowed(item, step) or (item.meal, item.role) in exhausted:
            continue
        gain = current - error.after(item, step)
        if gain > 1e-12 and (best is None or gain > best[0]):
            best = (gain, item)
    return best[1] if best else None


def _prune(error: _Error) -> bool:
    """Drop the food whose removal cuts the error most (a minimum portion can overshoot)."""
    current, best = error.total(), None
    for item in error.items:
        value = error.after(item, -item.grams)
        if value < current - 1e-12 and (best is None or value < best[0]):
            best = (value, item)
    if best is None:
        return False
    error.remove(best[1])
    return True


def _repair(error: _Error, picker: _Picker, kb: KnowledgeBase) -> None:
    search = _x(kb.compose.search)
    steps_left = _descend(error, search, search["max_steps"])
    exhausted: set[tuple[int, str]] = set()
    added = 0
    while added < search["max_added_foods"]:
        capped = _capped(error, search["steps_g"][-1], exhausted)
        if capped is None:
            break
        item = picker.next(capped.meal, capped.role, error.fiber[capped.meal])
        if item is None:
            exhausted.add((capped.meal, capped.role))
            continue
        error.add(item)
        added += 1
        steps_left = _descend(error, search, steps_left)
    while _prune(error):
        steps_left = _descend(error, search, steps_left)


def _nutrients(items: Sequence[_Item]) -> Nutrients:
    fiber: float | None = 0.0
    for it in items:
        per_100g = it.food["per_100g"]["fiber_g"]
        fiber = None if fiber is None or per_100g is None else fiber + it.grams * per_100g / 100
    totals = {m: round(sum(it.grams * it.per_g[m] for it in items), 1) for m in MACROS}
    return Nutrients(**totals, fiber_g=None if fiber is None else round(fiber, 1))


def compose(
    plan: PlanResponse,
    profile: Profile,
    preferences: Preferences,
    constraints: Constraints,
    kb: KnowledgeBase,
    food_table: Sequence[Food],
    *,
    day_type: DayType,
    phase: str | None = None,
) -> SampleDay:
    """A sample day for one phase (the first by default) and day type of a full plan."""
    if not plan.phases:
        raise ValueError("the plan has no phases to compose a day for")
    chosen = next((p for p in plan.phases if p.name == phase), None) if phase else plan.phases[0]
    if chosen is None:
        raise ValueError(f"the plan has no phase named {phase!r}")
    day_targets = chosen.targets_by_day_type.get(day_type)
    if day_targets is None:
        raise ValueError(f"phase {chosen.name!r} has no targets for day type {day_type!r}")

    template = _template(kb, day_type)
    meals = _meals(template, profile, kb)
    roles = _x(kb.compose.roles)
    # Rank against this phase, so the goal row and pattern lens match the day being built.
    phase_plan = plan.model_copy(update={"phases": [chosen]})
    ranked = {
        slot: foods.rank(
            FoodContext(meal_slot=slot, day_type=day_type),
            phase_plan,
            preferences,
            constraints,
            kb,
            food_table,
            limit=len(food_table),
        )
        for slot in dict.fromkeys(roles["rank_slots"][m.slot] for m in meals)
    }
    by_key = {f["key"]: f for f in food_table}
    picker = _Picker(meals, ranked, by_key, kb)
    items = picker.fill()
    targets = day_targets.model_dump()
    error = _Error(items, meals, targets, kb)
    _repair(error, picker, kb)
    items = error.items

    tol = _x(kb.compose.tolerance)
    t = _x(template)
    out_meals: list[Meal] = []
    for i, meal in enumerate(meals):
        mine = [it for it in items if it.meal == i]
        if not mine:
            continue
        nutrients = _nutrients(mine)
        if meal.carb_range:
            why = explain.text(kb, "COMPOSE.ROLES", "meal_pre_session")
            extra = t["pre_session_rule_ids"]
        elif meal.protein_target:
            n = sum(1 for m in meals if m.protein_target)
            why = explain.text(
                kb, "COMPOSE.ROLES", "meal_protein", protein=nutrients.protein_g, n=n
            )
            extra = t["protein_rule_ids"]
        else:
            why, extra = explain.text(kb, "COMPOSE.ROLES", "meal"), []
        out_meals.append(
            Meal(
                slot=meal.slot,
                items=[
                    MealItem(
                        key=it.rec.key,
                        fdc_id=it.rec.fdc_id,
                        name=it.rec.name,
                        grams=it.grams,
                        role=it.role,
                        nutrients=_nutrients([it]),
                        why=it.rec.why,
                        rule_ids=[*it.rec.rule_ids, "COMPOSE.ROLES", "COMPOSE.PORTIONS"],
                    )
                    for it in mine
                ],
                nutrients=nutrients,
                protein_target_g=None
                if meal.protein_target is None
                else round(meal.protein_target, 1),
                carb_target_g=None
                if meal.carb_range is None
                else (round(meal.carb_range[0], 1), round(meal.carb_range[1], 1)),
                why=why,
                rule_ids=[template.id, "COMPOSE.ROLES", *extra],
            )
        )

    day = _nutrients(items)
    deviation = {m: round((getattr(day, m) - targets[m]) / targets[m] * 100, 1) for m in MACROS}
    off = [m for m in MACROS if abs(deviation[m]) > tol["pct"]]
    if off:
        labels = " and ".join(tol["labels"][m] for m in off)
        why = explain.text(kb, "COMPOSE.TOLERANCE", "missed", macros=labels, pct=tol["pct"])
    else:
        why = explain.text(kb, "COMPOSE.TOLERANCE", "within", pct=tol["pct"])
    return SampleDay(
        phase=chosen.name,
        day_type=day_type,
        meals=out_meals,
        nutrients=day,
        targets=day_targets,
        tolerance_pct=tol["pct"],
        deviation_pct=deviation,
        within_tolerance=not off,
        why=why,
        rule_ids=[
            "COMPOSE.TOLERANCE",
            template.id,
            "COMPOSE.ROLES",
            "COMPOSE.PORTIONS",
            "COMPOSE.SEARCH",
            *chosen.rule_ids,
        ],
    )
