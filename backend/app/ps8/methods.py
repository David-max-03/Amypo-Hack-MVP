"""Solution methods - the second variation axis, alongside strategies.

PS8 asks for variations that change "the underlying numbers or method", not just the
scenario. Strategies change how a question is framed; a method changes how it is
*solved*. Each planned coding variation is assigned one method, the prompt requires
it, and the validator checks the answer key actually uses it.

Every method carries evidence checks, so a method label is a verified claim rather
than whatever the model said it did. Only coding questions have a method axis for
now: code is where "did it use recursion?" can be checked mechanically.

A method is only planned when it applies to the seed (`applicable_methods`). Asking
for "a non-destructive rebuild" of a primality test, or "a recursive solution" to a
SQL query, cannot be satisfied without changing what the question is about - so
those seeds simply have fewer methods, or none.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

_DEFINED_NAME_RE = re.compile(
    r"(?:\bdef|\bfunction|\bfn|\bfunc)\s+(\w+)\s*\("  # Python / JS / Rust / Go
    r"|\b(\w+)\s*\([^)]*\)\s*(?:throws\s+\w+\s*)?\{"  # C-family definitions
)
_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function"}

# Test scaffolding must not count as evidence: `assert reverse(ListNode(1))` both
# "calls reverse" and "allocates a node", which made iterative in-place answers
# pass as recursive or non-destructive.
_SCAFFOLD_SECTION_RE = re.compile(r"^\s*(#|//)\s*(test|example|usage|driver)", re.I)
_SCAFFOLD_LINE_RE = re.compile(
    r"^\s*(assert\b|print\s*\(|console\.log|System\.out|if\s+__name__)"
)


def solution_code(answer_key: str) -> str:
    """The answer key minus its test cases, examples and driver code."""
    kept: list[str] = []
    for line in answer_key.splitlines():
        if _SCAFFOLD_SECTION_RE.match(line):
            break
        if not _SCAFFOLD_LINE_RE.match(line):
            kept.append(line)
    return "\n".join(kept)


def _python_body(code: str, def_start: int) -> str | None:
    """The indented body of the Python function defined at `def_start`, if Python."""
    line_start = code.rfind("\n", 0, def_start) + 1
    header = code[line_start:def_start]
    if header.strip():  # not a `def` at the start of its line
        return None
    indent = len(header)
    lines = code[def_start:].splitlines()[1:]
    body: list[str] = []
    for line in lines:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    return "\n".join(body)


def _is_recursive(answer_key: str) -> bool:
    """Does some function defined in the solution call itself from its own body?"""
    code = solution_code(answer_key)
    for match in _DEFINED_NAME_RE.finditer(code):
        name = match.group(1) or match.group(2)
        if not name or name in _KEYWORDS:
            continue
        body = _python_body(code, match.start()) if match.group(1) else None
        if body is None:
            body = code[match.end() :]
        if re.search(rf"\b{re.escape(name)}\s*\(", body):
            return True
    return False


def _uses_loop(answer_key: str) -> bool:
    return bool(re.search(r"\b(while|for)\b", solution_code(answer_key)))


def _uses_auxiliary_store(answer_key: str) -> bool:
    return bool(
        re.search(
            r"\bstack\b|\.append\(|\.push\(|\.pop\(|\bdeque\b|ArrayList|Stack<|"
            r"=\s*\[\]|\blist\(|\bvector<",
            solution_code(answer_key),
        )
    )


# `x.next = something` that is not a freshly built node rewires existing nodes.
# `tail.next = ListNode(v)` (building forward) is allowed; `curr.next = prev` is not.
_REWIRES_LINK_RE = re.compile(r"\.next\s*=(?!=)(?!\s*(?:new\s+)?\w*Node\s*\()")


def _builds_new_nodes(answer_key: str) -> bool:
    """Does the solution copy input values into new nodes without rewiring the input?

    A dummy/sentinel node (`ListNode(0)`) is not a rebuild; a node built from an
    input value (`ListNode(head.val, out)`) or an explicit copy is - as long as the
    solution never re-points an existing node's `next`.
    """
    code = solution_code(answer_key)
    copies = re.search(
        r"\b(?:new\s+)?\w*Node\s*\(\s*\w+\.\w+|\bcopy\(|\bdeepcopy\(", code
    )
    return bool(copies) and not _REWIRES_LINK_RE.search(code)


# Node-linked structures: the ones the auxiliary-store and rebuild methods are about.
_LINKED_STRUCTURES = frozenset({"linked list", "binary tree", "graph"})


@dataclass(frozen=True)
class Method:
    id: str
    label: str
    instruction: str
    # Default methods are what a seed answer would normally use, so they earn no
    # extra similarity allowance - only a genuine change of method does.
    is_default: bool
    answer_evidence: Callable[[str], bool]
    # How the question text signals the method, so the learner is asked for it.
    question_pattern: str | None = None
    # Structures the method presupposes: it is only planned for a seed that operates
    # on one of them. None means any procedural coding seed.
    needs_structure: frozenset[str] | None = None
    # A worked construction per structure, appended to the instruction for seeds on
    # that structure (a 7B model follows a shown construction far better than a rule).
    examples: dict[str, str] | None = None

    def instruction_for(self, structure: str | None) -> str:
        example = (self.examples or {}).get(structure or "")
        return f"{self.instruction} {example}" if example else self.instruction

    def evidenced_in_answer(self, answer_key: str) -> bool:
        return self.answer_evidence(answer_key)

    def evidenced_in_question(self, question: str) -> bool:
        if self.question_pattern is None:
            return True
        return bool(re.search(self.question_pattern, question, re.I))


CODING_METHODS: list[Method] = [
    Method(
        id="iterative",
        label="Iterative solution",
        instruction="The intended solution is iterative: it uses a loop, not recursion.",
        is_default=True,
        answer_evidence=_uses_loop,
    ),
    Method(
        id="recursive",
        label="Recursive solution",
        instruction=(
            "The question must explicitly require a recursive solution (no loops), and "
            "the answer_key must be a function that calls itself."
        ),
        is_default=False,
        answer_evidence=_is_recursive,
        question_pattern=r"recurs",
    ),
    Method(
        id="auxiliary",
        label="Auxiliary stack / array solution",
        instruction=(
            "The question must require solving it with an explicit auxiliary data "
            "structure - a stack, array or list that holds the elements - and the "
            "answer_key must use one."
        ),
        is_default=False,
        answer_evidence=_uses_auxiliary_store,
        question_pattern=r"\bstack\b|\barray\b|\b(auxiliary|extra|additional)\b",
        needs_structure=_LINKED_STRUCTURES,
    ),
    Method(
        id="rebuild",
        label="Non-destructive rebuild",
        # The abstract version of this instruction failed every time live: Qwen 7B
        # wrote in-place pointer rewiring. Showing the exact construction works better.
        instruction=(
            "The question must state that the original input must NOT be modified and "
            "that a brand-new structure is returned. The answer_key must never assign "
            "to a `.next` of an input node. Instead it creates a NEW node for every "
            "element, copying the value,"
        ),
        examples={
            "linked list": (
                "e.g. for a linked list:\n"
                "    new_head = None\n"
                "    node = head\n"
                "    while node:\n"
                "        new_head = ListNode(node.val, new_head)\n"
                "        node = node.next\n"
                "    return new_head"
            ),
        },
        needs_structure=frozenset({"linked list"}),
        is_default=False,
        answer_evidence=_builds_new_nodes,
        question_pattern=r"unmodified|unchanged|not (be )?modif|without modifying|"
        r"\bnew\b.*\b(list|copy|structure)\b|\bcopy\b|preserv|immutable|intact",
    ),
]

_BY_ID = {m.id: m for m in CODING_METHODS}


def methods_for(question_type: str) -> list[Method]:
    """Methods to rotate through for a seed of this question type (may be empty)."""
    return CODING_METHODS if question_type == "coding" else []


# A coding seed is one of three shapes. Only a procedure - "write a function that
# computes X" - has a solution method to vary.
_ARTIFACT_RE = re.compile(
    r"\b(sql|query|queries|html|css|xml|markup|stylesheet|schema|regex|regular expression|"
    r"yaml|dockerfile|shell command|configuration file)\b",
    re.I,
)
_STRUCTURE_DESIGN_RE = re.compile(
    r"\b(that supports?|supporting|with (?:the )?operations?|data structure that|"
    r"class that|design (?:a|an) (?:class|data structure|api|interface))\b",
    re.I,
)


def task_shape(seed_text: str, question_type: str) -> str:
    """procedure | structure | artifact | non_code - what kind of thing the seed asks for."""
    if question_type != "coding":
        return "non_code"
    if _ARTIFACT_RE.search(seed_text or ""):
        return "artifact"  # a query, a page, a pattern: declarative, no control flow to vary
    if _STRUCTURE_DESIGN_RE.search(seed_text or ""):
        return "structure"  # "a stack that supports push and pop": a design, not one routine
    return "procedure"


def applicable_methods(seed) -> list[Method]:
    """Methods that can be asked of this seed without changing what it is about."""
    if task_shape(seed.raw_seed, seed.question_type) != "procedure":
        return []
    from .validation.validators import seed_data_structure  # local: avoids a cycle

    structure = seed_data_structure(seed)
    return [
        m for m in CODING_METHODS
        if m.needs_structure is None or structure in m.needs_structure
    ]


def get_method(method_id: str | None) -> Method | None:
    return _BY_ID.get(method_id) if method_id else None
