"""Variation Planner (PS8).

Decides which controlled strategy each requested variation should use, before any
generation happens. Planning up front (rather than letting the model choose) is what
makes the output diverse in a *measurable* way: each candidate is committed to
changing a specific axis, and we can show judges which one.
"""

from __future__ import annotations

from ..schemas import SeedMetadata, VariationPlanItem
from . import methods, strategies

# Strategies that do not make sense for some question types. A fill-in-the-blank
# question, for instance, has little "structure" to invert meaningfully.
_TYPE_EXCLUSIONS: dict[str, set[str]] = {
    "fill_in_the_blank": {"structure"},
    "true_false": {"structure", "representation"},
}


def eligible_strategies_for_type(question_type: str) -> list[strategies.Strategy]:
    excluded = _TYPE_EXCLUSIONS.get(question_type, set())
    eligible = [s for s in strategies.list_strategies() if s.id not in excluded]
    # Never return an empty plan space.
    return eligible or strategies.list_strategies()


def _eligible_strategies(seed: SeedMetadata) -> list[strategies.Strategy]:
    return eligible_strategies_for_type(seed.question_type)


def plan_variations(
    seed: SeedMetadata, count: int, *, difficulty_shift: str | None = None
) -> list[VariationPlanItem]:
    """Produce `count` planned variations, rotating through eligible strategies.

    Round-robin rotation guarantees that with N>=5 requested variations every
    strategy is exercised at least once before any repeats, which directly lowers
    the near-duplicate rate PS8 is scored on. Coding seeds also rotate a solution
    method, so variations differ in how they are solved, not only how they read.
    """
    if count < 1:
        return []

    eligible = _eligible_strategies(seed)
    # Methods rotate independently of strategies. With 5 strategies and 4 methods the
    # cycle lengths are coprime, so every strategy x method pairing occurs before
    # any pairing repeats.
    # Only methods that apply to this seed are planned; a seed with none simply has no
    # method axis, exactly like a non-coding seed.
    method_pool = methods.applicable_methods(seed)
    from .validation.validators import seed_data_structure

    structure = seed_data_structure(seed)
    plan: list[VariationPlanItem] = []

    for i in range(count):
        strategy = eligible[i % len(eligible)]
        instruction = strategy.instruction

        # On the second and later pass through the rotation, push for a different
        # angle so repeats of the same strategy do not collapse into each other.
        cycle = i // len(eligible)
        if cycle > 0:
            instruction = (
                f"{instruction}\n\nThis is variation #{i + 1} using this strategy. "
                f"Take a completely different angle from any earlier "
                f"{strategy.label.lower()} you produced - a different setting, "
                "different entities and different specifics."
            )

        change = list(strategy.change)
        preserve = list(strategy.preserve)
        if difficulty_shift:
            # An explicit shift was requested, so difficulty is no longer preserved.
            preserve = [p for p in preserve if p != "difficulty"]
            change.append(f"difficulty -> {difficulty_shift}")

        method = method_pool[i % len(method_pool)] if method_pool else None
        if method is not None and not method.is_default:
            preserve = [p for p in preserve if p != "solution method"]
            if "solution method" not in change:
                change.append("solution method")

        plan.append(
            VariationPlanItem(
                index=i,
                strategy=strategy.id,
                strategy_label=strategy.label,
                instruction=instruction,
                preserve=preserve,
                change=change,
                method=method.id if method else None,
                method_label=method.label if method else "",
                method_instruction=method.instruction_for(structure) if method else "",
                dimension=strategy.dimension,
                must_not_change=list(strategy.must_not_change),
            )
        )

    return plan
