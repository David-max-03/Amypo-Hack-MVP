"""Supported domains.

PS8 requires at least five selectable domains. Each carries the keyword signals the
heuristic seed parser uses to classify a seed, plus an example the UI can prefill.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Domain:
    id: str
    label: str
    description: str
    example_seed: str
    keywords: list[str] = field(default_factory=list)
    default_question_type: str = "descriptive"


DOMAINS: dict[str, Domain] = {
    "programming": Domain(
        id="programming",
        label="Programming",
        description="Data structures, algorithms, coding and software design tasks.",
        example_seed="Write a function to reverse a singly linked list.",
        keywords=[
            "function", "algorithm", "code", "array", "list", "linked", "tree", "graph",
            "stack", "queue", "hash", "sort", "search", "recursion", "pointer", "string",
            "complexity", "loop", "class", "object", "api", "database", "sql", "python",
            "java", "javascript", "compile", "debug", "implement", "binary", "traversal",
        ],
        default_question_type="coding",
    ),
    "mathematics": Domain(
        id="mathematics",
        label="Mathematics",
        description="Algebra, calculus, probability, statistics and discrete mathematics.",
        example_seed="Find the derivative of f(x) = 3x^2 + 5x - 7.",
        keywords=[
            "derivative", "integral", "equation", "solve", "matrix", "vector", "probability",
            "theorem", "proof", "geometry", "algebra", "calculus", "polynomial", "limit",
            "mean", "median", "variance", "statistics", "triangle", "angle", "fraction",
            "logarithm", "series", "prime", "factor",
        ],
        default_question_type="numerical",
    ),
    "science": Domain(
        id="science",
        label="Science",
        description="Physics, chemistry and biology concepts and applications.",
        example_seed="Explain why water has a higher boiling point than methane.",
        keywords=[
            "atom", "molecule", "cell", "energy", "force", "reaction", "electron", "photo",
            "gravity", "velocity", "acceleration", "enzyme", "dna", "chemical", "bond",
            "organism", "physics", "chemistry", "biology", "experiment", "hypothesis",
            "temperature", "pressure", "mass", "compound",
            # States of matter and thermal properties - common in science seeds and
            # absent from every other domain's vocabulary.
            "boiling", "melting", "freezing", "evaporation", "condensation",
            "liquid", "solid", "gas", "water", "methane", "hydrogen", "oxygen",
            "carbon", "nitrogen", "acid", "base", "ph", "solubility", "density",
            "photosynthesis", "respiration", "protein", "nucleus", "proton", "neutron",
        ],
    ),
    "business": Domain(
        id="business",
        label="Business",
        description="Management, finance, marketing, economics and operations.",
        example_seed=(
            "Calculate the break-even point for a product priced at $50 with $20 variable cost."
        ),
        keywords=[
            "revenue", "profit", "cost", "market", "customer", "strategy", "finance",
            "investment", "supply", "demand", "budget", "roi", "margin", "pricing",
            "management", "stakeholder", "business", "economics", "inventory", "sales",
        ],
    ),
    "language": Domain(
        id="language",
        label="Language",
        description="Grammar, comprehension, composition and literary analysis.",
        example_seed="Identify the subject and predicate in: 'The old library closed last winter.'",
        keywords=[
            "grammar", "sentence", "verb", "noun", "adjective", "tense", "clause",
            "paragraph", "essay", "comprehension", "vocabulary", "synonym", "antonym",
            "punctuation", "literary", "metaphor", "narrative", "passage", "pronoun",
        ],
    ),
    "health": Domain(
        id="health",
        label="Health",
        description="Anatomy, nutrition, public health and clinical fundamentals.",
        example_seed="Describe how insulin regulates blood glucose levels.",
        keywords=[
            "patient", "disease", "symptom", "treatment", "diagnosis", "nutrition",
            "vitamin", "blood", "heart", "muscle", "immune", "infection", "hygiene",
            "health", "clinical", "dose", "therapy", "anatomy", "insulin", "glucose",
        ],
    ),
    "general_knowledge": Domain(
        id="general_knowledge",
        label="General Knowledge",
        description="History, geography, civics and current affairs.",
        example_seed="Name the river that flows through Paris and explain its historical importance.",
        keywords=[
            "history", "capital", "country", "river", "president", "war", "century",
            "continent", "government", "constitution", "culture", "geography", "empire",
        ],
    ),
}

DEFAULT_DOMAIN = "programming"


def get_domain(domain_id: str) -> Domain:
    return DOMAINS.get((domain_id or "").strip().lower(), DOMAINS[DEFAULT_DOMAIN])


def is_supported(domain_id: str) -> bool:
    return (domain_id or "").strip().lower() in DOMAINS


def list_domains() -> list[Domain]:
    return list(DOMAINS.values())


def infer_domain(text: str) -> str:
    """Classify a seed by keyword hits. Ties resolve to the first-declared domain."""
    from ..core.text_utils import token_set  # local import avoids an import cycle

    tokens = token_set(text)
    best, best_score = DEFAULT_DOMAIN, 0
    for domain in DOMAINS.values():
        score = sum(1 for kw in domain.keywords if kw in tokens)
        if score > best_score:
            best, best_score = domain.id, score
    return best
