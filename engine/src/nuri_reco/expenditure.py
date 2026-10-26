"""Energy expenditure estimates (PRD §8.1, Loam Score page §3, spec §2 Monitor & Evaluate).

Cold start: Mifflin-St Jeor RMR x activity factor. Adaptive: measured from logged intake and the
weight slope (energy balance, expenditure.yaml), blended in during week 3 and used alone from
week 4 (GOAL.METHOD). Trend weight (an EMA of weigh-ins) is reported alongside.
"""

import datetime as dt
import math
from typing import Literal, Protocol

from pydantic import Field

from nuri_reco.kb import KnowledgeBase
from nuri_reco.models import DailyLog, PlanRequest, Profile, StrictModel

ExpenditureMethod = Literal["mifflin_st_jeor", "blended", "adaptive"]


class Expenditure(Protocol):
    """Estimates maintenance energy (TDEE, kcal/day) for a profile."""

    method: str
    # The rules behind the estimate, cited by the targets that use it.
    rule_ids: list[str]

    def tdee(self, profile: Profile) -> float: ...


class ColdStartExpenditure:
    method = "mifflin_st_jeor"

    def __init__(self, kb: KnowledgeBase) -> None:
        self._msj = kb.targets.mifflin_st_jeor.model_extra or {}
        self._factors = (kb.targets.activity_factors.model_extra or {})["factors"]
        self.rule_ids = [kb.targets.mifflin_st_jeor.id, kb.targets.activity_factors.id]

    def rmr(self, profile: Profile) -> float:
        c = self._msj["coefficients"]
        return float(
            c["weight_kg"] * profile.weight_kg
            + c["height_cm"] * profile.height_cm
            + c["age_years"] * profile.age
            + self._msj["sex_constant"][profile.sex]
        )

    def activity_factor(self, profile: Profile) -> float:
        try:
            return float(self._factors[profile.activity])
        except KeyError:
            known = ", ".join(self._factors)
            raise ValueError(
                f"unknown activity {profile.activity!r}; expected one of {known}"
            ) from None

    def tdee(self, profile: Profile) -> float:
        return self.rmr(profile) * self.activity_factor(profile)


class Measured(StrictModel):
    """What the logs say, before blending with the cold-start estimate."""

    # Weeks of logs, counted from the first log (0 with no logs).
    week: int = Field(ge=0)
    window_start: dt.date | None = None
    window_end: dt.date | None = None
    intake_days: int = 0
    weigh_in_days: int = 0
    avg_intake_kcal: float | None = None
    weight_slope_kg_per_day: float | None = None
    trend_weight_kg: float | None = None
    # None when the window has too few logs (expenditure.yaml EXPENDITURE.ENERGY_BALANCE).
    tdee_kcal: float | None = None


class AdaptiveEstimate(Measured):
    method: ExpenditureMethod
    cold_start_tdee_kcal: float
    measured_pct: float = Field(ge=0, le=100)
    estimate_kcal: float
    rule_ids: list[str] = Field(min_length=1)


def trend_weights(history: list[DailyLog], smoothing: float) -> list[tuple[dt.date, float]]:
    """EMA trend weight on each weigh-in day; a day without a weigh-in leaves it unchanged."""
    out: list[tuple[dt.date, float]] = []
    trend: float | None = None
    for log in history:
        if log.weight_kg is None:
            continue
        trend = log.weight_kg if trend is None else trend + smoothing * (log.weight_kg - trend)
        out.append((log.date, trend))
    return out


def _slope(points: list[tuple[float, float]]) -> float:
    """Least-squares slope of y on x."""
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    return sum((x - mx) * (y - my) for x, y in points) / sxx


class AdaptiveExpenditure:
    """Expenditure from logged intake and weigh-ins (energy balance), behind the Protocol."""

    def __init__(self, kb: KnowledgeBase, history: list[DailyLog]) -> None:
        e = kb.expenditure
        self._kb = kb
        self._cold = ColdStartExpenditure(kb)
        self._takeover = e.takeover.model_extra or {}
        self.measured = self._measure(sorted(history, key=lambda d: d.date))
        self.measured_pct = self._measured_pct()
        self.kind: ExpenditureMethod = (
            "mifflin_st_jeor"
            if self.measured_pct == 0
            else "adaptive"
            if self.measured_pct == 100
            else "blended"
        )
        self.method: str = self.kind
        ids = [e.takeover.id, e.trend_weight.id]
        if self.measured_pct > 0:
            ids += [e.energy_balance.id, e.energy_density.id]
        if self.measured_pct < 100:
            ids = [*self._cold.rule_ids, *ids]
        self.rule_ids = ids

    def _measure(self, history: list[DailyLog]) -> Measured:
        e = self._kb.expenditure
        balance = e.energy_balance.model_extra or {}
        if not history:
            return Measured(week=0)
        first, last = history[0].date, history[-1].date
        week = math.ceil(((last - first).days + 1) / self._takeover["days_per_week"])
        start = last - dt.timedelta(days=balance["window_days"] - 1)
        window = [d for d in history if d.date >= start]
        intake = [d.intake_kcal for d in window if d.intake_kcal is not None]
        weights = [((d.date - start).days, d.weight_kg) for d in window if d.weight_kg is not None]
        trend = trend_weights(history, (e.trend_weight.model_extra or {})["smoothing"])
        avg = sum(intake) / len(intake) if intake else None
        out = Measured(
            week=week,
            window_start=max(start, first),
            window_end=last,
            intake_days=len(intake),
            weigh_in_days=len(weights),
            avg_intake_kcal=avg,
            trend_weight_kg=trend[-1][1] if trend else None,
        )
        enough = (
            len(intake) >= balance["min_intake_days"]
            and len(weights) >= balance["min_weigh_in_days"]
        )
        if avg is None or len(weights) < 2 or not enough:
            return out
        slope = _slope([(float(x), y) for x, y in weights])
        kcal_per_kg = (e.energy_density.model_extra or {})["kcal_per_kg"]
        tdee = avg - slope * kcal_per_kg
        # A non-positive result means the logs can't be right; keep the cold-start estimate.
        return out.model_copy(
            update={"weight_slope_kg_per_day": slope, "tdee_kcal": tdee if tdee > 0 else None}
        )

    def _measured_pct(self) -> float:
        t = self._takeover
        if self.measured.tdee_kcal is None or self.measured.week < t["blend_from_week"]:
            return 0.0
        if self.measured.week < t["measured_from_week"]:
            return float(t["blend_measured_pct"])
        return 100.0

    def estimate(self, profile: Profile) -> AdaptiveEstimate:
        cold = self._cold.tdee(profile)
        share = self.measured_pct / 100
        measured = self.measured.tdee_kcal if self.measured.tdee_kcal is not None else cold
        return AdaptiveEstimate(
            **self.measured.model_dump(),
            method=self.kind,
            cold_start_tdee_kcal=cold,
            measured_pct=self.measured_pct,
            estimate_kcal=(1 - share) * cold + share * measured,
            rule_ids=self.rule_ids,
        )

    def tdee(self, profile: Profile) -> float:
        return self.estimate(profile).estimate_kcal


def for_request(request: PlanRequest, kb: KnowledgeBase) -> Expenditure:
    """Adaptive when the request carries logs up to its as_of date; cold start otherwise."""
    history = [d for d in request.history if d.date <= request.as_of]
    if not history:
        return ColdStartExpenditure(kb)
    return AdaptiveExpenditure(kb, history)
