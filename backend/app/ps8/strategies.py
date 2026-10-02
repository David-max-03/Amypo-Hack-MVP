"""Strategies Manager - the controlled variation strategies PS8 is built around.

The technical documentation names five strategies: scenario, parameter, constraint,
structure and representation. Each one is a contract: the single dimension it varies,
what it may change along that dimension, what it must preserve, and what it must not
change under any circumstances. The last list is the same for every strategy - no
strategy is ever a licence to assess something else.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Off limits to every strategy. A variation that changes any of these is a different
# question, not a variation.
PROHIBITED_CHANGES: list[str] = [
    "the core learning objective",
    "the task the learner performs",
    "the subject, concept, algorithm, data structure or technology the seed is about",
    "the domain",
]


@dataclass(frozen=True)
class Strategy:
    id: str
    label: str
    # The one dimension this strategy varies.
    dimension: str
    instruction: str
    # How a question using this strategy opens. A question that opens with the seed's
    # own sentence and appends the change reads as a copy of the seed; opening with
    # the thing this strategy introduces is what makes it a question of its own.
    opening: str = ""
    preserve: list[str] = field(default_factory=list)
    change: list[str] = field(default_factory=list)
    must_not_change: list[str] = field(default_factory=lambda: list(PROHIBITED_CHANGES))
    # Domains this strategy suits best; empty means "any domain".
    best_for: list[str] = field(default_factory=list)


STRATEGIES: dict[str, Strategy] = {
    "scenario": Strategy(
        id="scenario",
        label="Scenario Variation",
        dimension="the real-world setting the task is placed in",
        instruction=(
            "Place the SAME task inside a different real-world setting. Invent a concrete "
            "situation (a specific organisation, product, dataset or user) in which "
            "someone needs exactly what the seed asks for. Only the setting, the names "
            "and the story change - do not reuse the seed's setting or framing, and do "
            "not change what the learner has to do or what it is done to."
        ),
        opening=(
            "Open with the new setting: one or two sentences describing the situation and who needs the task done. Ask for the task only after that."
        ),
        preserve=["learning objective", "core concept", "task", "difficulty"],
        change=["real-world setting", "entities and naming", "surface narrative"],
    ),
    "parameter": Strategy(
        id="parameter",
        label="Parameter Variation",
        dimension="the concrete values the task is posed with",
        instruction=(
            "Keep the task exactly as it is but change its concrete parameters: the "
            "numeric values, input sizes, data types, ranges, units or boundary values. "
            "Adjust the answer key so it is correct for the NEW values, not the seed's."
        ),
        opening=(
            "Open with the concrete data the task is posed on - the specific values, sizes or inputs you chose - and build the question around them."
        ),
        preserve=["learning objective", "core concept", "task type", "difficulty"],
        change=["numeric values", "input sizes", "data types", "boundary conditions"],
    ),
    "constraint": Strategy(
        id="constraint",
        label="Constraint Variation",
        dimension="the constraints the solution must respect",
        instruction=(
            "Keep the task but add, remove or swap one explicit constraint on HOW it may "
            "be solved or answered - for example a resource or complexity limit, a "
            "forbidden tool, operation or technique, a required form for the answer, or "
            "a restriction on the inputs. State the constraint plainly in the question. "
            "It must genuinely change how the same problem is solved, while keeping the "
            "difficulty equivalent."
        ),
        opening=(
            "Open with a short concrete situation that explains why the constraint exists, then ask for the task under that constraint."
        ),
        preserve=["learning objective", "core concept", "task", "difficulty"],
        change=["solution method", "allowed operations", "resource or complexity requirements"],
    ),
    "structure": Strategy(
        id="structure",
        label="Structure Variation",
        dimension="what is given to the learner versus what is asked of them",
        instruction=(
            "Change the shape of the task - what is given versus what is asked - while "
            "keeping it about the same thing. For example give a flawed solution to "
            "the seed's task and ask the learner to find and correct the error, give a "
            "partial solution to complete, or give a worked solution and ask the learner "
            "to trace or justify it."
        ),
        opening=(
            "Open with the material the learner is given - the flawed, partial or worked solution - and ask what to do with it."
        ),
        preserve=["learning objective", "core concept", "difficulty"],
        change=["what is given", "what is asked", "form of the task"],
    ),
    "representation": Strategy(
        id="representation",
        label="Representation Variation",
        dimension="how the problem and its data are presented",
        instruction=(
            "Change how the same problem is presented: a different input or output "
            "format, a table or worked example instead of prose, or a different question "
            "format (for example multiple choice instead of an open task). What the "
            "question is about must stay exactly the same - change the presentation, "
            "not the subject."
        ),
        opening=(
            "Open with the new presentation itself - the table, the options, or the input and output format - and ask the question in terms of it."
        ),
        preserve=["learning objective", "core concept", "task", "difficulty"],
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
