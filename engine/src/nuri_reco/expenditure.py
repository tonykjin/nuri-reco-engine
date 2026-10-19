"""Energy expenditure estimates (PRD §8.1, Loam Score page §3).

Cold start: Mifflin-St Jeor RMR x activity factor. The adaptive estimator (measured intake +
trend weight, meaningful by week 3-4) replaces it later.
"""

from typing import Protocol

from nuri_reco.kb import KnowledgeBase
from nuri_reco.models import Profile


class Expenditure(Protocol):
    """Estimates maintenance energy (TDEE, kcal/day) for a profile."""

    method: str

    def tdee(self, profile: Profile) -> float: ...


class ColdStartExpenditure:
    method = "mifflin_st_jeor"

    def __init__(self, kb: KnowledgeBase) -> None:
        self._msj = kb.targets.mifflin_st_jeor.model_extra or {}
        self._factors = (kb.targets.activity_factors.model_extra or {})["factors"]

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


class AdaptiveExpenditure:
    """Expenditure from logged intake and trend weight (runbook Task 22). Not implemented yet."""

    method = "adaptive"

    def tdee(self, profile: Profile) -> float:
        raise NotImplementedError("adaptive expenditure arrives in Task 22")
