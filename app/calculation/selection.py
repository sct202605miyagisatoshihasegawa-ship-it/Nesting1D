from dataclasses import dataclass
from typing import Any, Sequence


DEFAULT_WASTE_TOLERANCE_MM = 0
DEFAULT_REMNANT_TOLERANCE_MM = 0


class NoFullySatisfiedCandidateError(ValueError):
    """Raised when no candidate can satisfy every required part."""


@dataclass(frozen=True)
class SelectionCandidate:
    stocks: tuple[Any, ...]
    unused: tuple[Any, ...]
    inventory_completed: tuple[tuple[int, int], ...]
    fully_satisfied: bool
    additional_new_stock_count: int
    waste_length_mm: int
    remnant_length_mm: int
    remnant_count: int
    pattern_count: int
    dimension_change_count: int
    stable_tie_break_key: tuple[str, ...]


def _validate_tolerance(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name}は0以上の整数で指定してください")


def select_candidate(
    candidates: Sequence[SelectionCandidate],
    *,
    waste_tolerance_mm: int = DEFAULT_WASTE_TOLERANCE_MM,
    remnant_tolerance_mm: int = DEFAULT_REMNANT_TOLERANCE_MM,
) -> SelectionCandidate:
    """Select one candidate without mutating the supplied candidates."""
    _validate_tolerance(waste_tolerance_mm, "waste_tolerance_mm")
    _validate_tolerance(remnant_tolerance_mm, "remnant_tolerance_mm")

    satisfied = [candidate for candidate in candidates if candidate.fully_satisfied]
    if not satisfied:
        raise NoFullySatisfiedCandidateError("必要部材を完全充足する候補がありません")

    minimum_purchase = min(
        candidate.additional_new_stock_count for candidate in satisfied
    )
    minimum_purchase_candidates = [
        candidate
        for candidate in satisfied
        if candidate.additional_new_stock_count == minimum_purchase
    ]

    minimum_waste = min(
        candidate.waste_length_mm for candidate in minimum_purchase_candidates
    )
    waste_equivalent = [
        candidate
        for candidate in minimum_purchase_candidates
        if candidate.waste_length_mm - minimum_waste <= waste_tolerance_mm
    ]

    minimum_remnant = min(
        candidate.remnant_length_mm for candidate in waste_equivalent
    )
    remnant_equivalent = [
        candidate
        for candidate in waste_equivalent
        if candidate.remnant_length_mm - minimum_remnant <= remnant_tolerance_mm
    ]

    minimum_remnant_count = min(
        candidate.remnant_count for candidate in remnant_equivalent
    )
    materially_equivalent = [
        candidate
        for candidate in remnant_equivalent
        if candidate.remnant_count == minimum_remnant_count
    ]

    return min(
        materially_equivalent,
        key=lambda candidate: (
            candidate.pattern_count,
            candidate.dimension_change_count,
            candidate.stable_tie_break_key,
        ),
    )
