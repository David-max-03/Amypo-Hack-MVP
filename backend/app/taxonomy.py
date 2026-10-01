"""The ONE shared domain / difficulty configuration.

Every screen - Generate & Verify, PS2 Verifier, Question Bank, Review Queue, Reports -
reads its domain and difficulty options from GET /api/v1/taxonomy, which serves this
module. Nothing else defines these lists.

Subject areas are what the user picks. Each maps to a *pipeline domain*, the domain
PS8 and PS2 validate against: all computer-science areas run through the existing
"programming" pipeline domain, so the data-structure anchor, the domain-drift check
and the reference corpus (whose programming entries are tagged "programming") keep
working exactly as before. The subject area itself is recorded on every result so
the bank, review queue and reports can filter by it.
"""

from __future__ import annotations

from .ps8 import domains as domain_registry

CS_GROUP = "Computer Science"
OTHER_GROUP = "Other domains"

_CS_AREAS: list[tuple[str, str]] = [
    ("algorithms", "Algorithms"),
    ("data_structures", "Data Structures"),
    ("web_development", "Web Development"),
    ("databases", "Database"),
    ("operating_systems", "Operating Systems"),
    ("computer_networks", "Computer Networks"),
    ("computer_architecture", "Computer Architecture"),
    ("oop", "OOP"),
    ("software_engineering", "Software Engineering"),
    ("ai_ml", "AI / Machine Learning"),
    ("cloud_computing", "Cloud Computing"),
    ("cybersecurity", "Cybersecurity"),
    ("programming_languages", "Programming Languages"),
    ("system_design", "System Design"),
    # Existing results were generated before subject areas existed; they belong here.
    ("programming", "Programming (general)"),
]

DIFFICULTIES: list[dict[str, str]] = [
    {"id": "easy", "label": "Easy"},
    {"id": "medium", "label": "Medium"},
    {"id": "hard", "label": "Hard"},
    {"id": "expert", "label": "Expert"},
]

DEFAULT_SUBJECT_AREA = "programming"


def subject_areas() -> list[dict[str, str]]:
    areas = [
        {"id": sid, "label": label, "pipeline_domain": "programming", "group": CS_GROUP}
        for sid, label in _CS_AREAS
    ]
    for d in domain_registry.list_domains():
        if d.id != "programming":
            areas.append({"id": d.id, "label": d.label, "pipeline_domain": d.id, "group": OTHER_GROUP})
    return areas


def pipeline_domain_for(subject_area: str | None) -> str | None:
    """The PS8/PS2 domain for a subject area, or None if it is not a known area."""
    for area in subject_areas():
        if area["id"] == subject_area:
            return area["pipeline_domain"]
    return None


def as_dict() -> dict:
    return {
        "subject_areas": subject_areas(),
        "difficulties": DIFFICULTIES,
        "default_subject_area": DEFAULT_SUBJECT_AREA,
        "groups": [CS_GROUP, OTHER_GROUP],
    }
