"""Strategies Manager - the controlled variation strategies PS8 is built around.

The technical documentation names five strategies: scenario, parameter, constraint,
structure and representation. Each one says what must be *preserved* (so the question
still tests the same thing) and what must *change* (so it is not a paraphrase).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Strategy:
    id: str
    label: str
    instruction: str
    preserve: list[str] = field(default_factory=list)
    change: list[str] = field(default_factory=list)
    # Domains this strategy suits best; empty means "any domain".
    best_for: list[str] = field(default_factory=list)


STRATEGIES: dict[str, Strategy] = {
    "scenario": Strategy(
        id="scenario",
        label="Scenario Variation",
        instruction=(
            "Re-set the question inside a completely different real-world scenario or "
            "application domain. Invent a concrete situation (a specific industry, "
            "product, dataset or user) that makes the same underlying task necessary. "
            "The story must be new - do not reuse the seed's setting, nouns or framing."
        ),
        preserve=["learning objective", "core concept", "difficulty"],
        change=["real-world setting", "entities and naming", "surface narrative"],
    ),
    "parameter": Strategy(
        id="parameter",
        label="Parameter Variation",
        instruction=(
            "Keep the task type but change the concrete parameters: the input sizes, "
            "numeric values, data types, ranges, units or boundary values. Adjust the "
            "answer key so it is correct for the NEW numbers, not the seed's."
        ),
        preserve=["learning objective", "core concept", "task type", "difficulty"],
        change=["numeric values", "input sizes", "data types", "boundary conditions"],
    ),
    "constraint": Strategy(
        id="constraint",
        label="Constraint Variation",
        instruction=(
            "Add, remove or swap an explicit constraint that forces a different solution "
            "path - for example a space/time complexity bound, a forbidden library or "
            "operation, an in-place requirement, or a single-pass restriction. The "
            "constraint must genuinely change how the problem is solved, while keeping "
            "the difficulty equivalent."
        ),
        preserve=["learning objective", "core concept", "difficulty"],
        change=["solution method", "allowed operations", "complexity requirements"],
    ),
    "structure": Strategy(
        id="structure",
        label="Structure Variation",
        instruction=(
            "Change the structural shape of the task: what is given versus what is asked. "
            "For example ask the learner to debug a faulty implementation, complete a "
            "partial one, generalise the task, or produce the inverse transformation "
            "instead of the forward one."
        ),
        preserve=["learning objective", "core concept", "difficulty"],
        change=["what is given", "what is asked", "direction of the task"],
    ),
    "representation": Strategy(
        id="representation",
        label="Representation Variation",
        instruction=(
            "Change how the problem and its data are represented - a different underlying "
            "data structure, a different input/output format, a table or diagram instead "
            "of prose, or a different question format (for example MCQ instead of an "
            "open coding task) while still assessing the same objective."
        ),
        preserve=["learning objective", "core concept", "difficulty"],
        change=["data representation", "input/output format", "question format"],
    ),
}

# Round-robin order. Rotating strategies is what pushes the duplicate rate down:
# consecutive candidates are forced to differ along a different axis.
STRATEGY_ORDER: list[str] = ["scenario", "constraint", "parameter", "structure", "representation"]


def get_strategy(strategy_id: str) -> Strategy:
    try:
        return STRATEGIES[strategy_id]
    except KeyError:
        raise KeyError(
            f"Unknown variation strategy {strategy_id!r}. "
            f"Supported: {', '.join(sorted(STRATEGIES))}"
        ) from None


def list_strategies() -> list[Strategy]:
    return [STRATEGIES[s] for s in STRATEGY_ORDER]


def strategy_for_index(index: int) -> Strategy:
    """Deterministic round-robin pick, so a run is reproducible and explainable."""
    return STRATEGIES[STRATEGY_ORDER[index % len(STRATEGY_ORDER)]]
