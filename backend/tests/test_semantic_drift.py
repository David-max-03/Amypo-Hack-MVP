"""Semantic drift: a variation may change the requested dimension, but must keep the
seed's core educational intent.

Nothing here is specific to one topic. The same contract, prompt and PS8 checks are
exercised on seeds from ten domains, and the negative cases substitute one task for
another the way a drifting model does.
"""

from __future__ import annotations

import json

import pytest

from backend.app import pipeline
from backend.app.decision.decision_engine import decide
from backend.app.ps8 import contract as seed_contract
from backend.app.ps8 import methods, prompt_builder, seed_parser, strategies, variation_planner
from backend.app.ps8.validation import validators
from backend.app.ps8.validation.engine import validate_candidate
from backend.tests.conftest import FakeOllama, make_candidate

# key -> (pipeline domain, seed, the term(s) the contract must require)
SEEDS: dict[str, tuple[str, str, list[str]]] = {
    "programming": ("programming", "Write a function to check whether a number is prime.", ["prime"]),
    "algorithms": ("programming", "Implement binary search on a sorted array of integers.", ["binary", "search"]),
    "data_structures": ("programming", "Implement a stack that supports push, pop and retrieving the minimum element.", ["minimum"]),
    "database": ("programming", "Write a SQL query to find duplicate email addresses in a users table.", ["duplicate"]),
    "operating_systems": ("programming", "Explain how round-robin CPU scheduling decides which process runs next.", ["round", "robin"]),
    "computer_networks": ("programming", "Explain how TCP congestion control uses slow start and congestion avoidance.", ["tcp", "congestion"]),
    "ai_ml": ("programming", "Explain how the k-nearest neighbours algorithm classifies a new data point.", ["nearest", "neighbours"]),
    "web_development": ("programming", "Write an HTML form that collects a user's name and email address.", ["form", "email"]),
    "software_engineering": ("programming", "Explain the difference between unit testing and integration testing.", ["testing", "integration"]),
    "mathematics": ("mathematics", "Find the derivative of f(x) = 3x^2 + 5x - 7.", ["derivative"]),
}

# Faithful variations: (seed key, strategy, question). Each changes one dimension.
FAITHFUL: list[tuple[str, str, str]] = [
    ("programming", "scenario", "A cryptography startup needs a routine that decides if a given integer key candidate is a prime number. Write the function is_prime(n) and return True or False."),
    ("programming", "structure", "The following function is meant to test primality but returns True for 9. Find and fix the bug.\ndef is_prime(n):\n    for i in range(2, 3): ..."),
    ("algorithms", "scenario", "A library catalogue stores ISBNs in ascending order. Write a function that uses binary search to locate a given ISBN and returns its index or -1."),
    ("algorithms", "constraint", "Implement binary search recursively on a sorted list of floating point temperatures; do not use loops."),
    ("data_structures", "scenario", "Design a stack for a text editor's undo history that supports push, pop and getMin, each in O(1) time."),
    ("data_structures", "constraint", "Implement a stack with push, pop and a function that returns the smallest element currently stored, using only one auxiliary stack."),
    ("database", "scenario", "An HR database has an employees table. Write a SQL query to find duplicate phone numbers, without using a subquery."),
    ("database", "parameter", "Write a SQL query to find repeated email addresses among customers, returning each email and how many times it occurs."),
    ("operating_systems", "parameter", "A system uses round-robin scheduling with a time quantum of 3 ms and four processes. Explain which process runs after each quantum expires."),
    ("operating_systems", "representation", "Describe how a round robin scheduler with a time quantum chooses the next process from the ready queue, and what happens when a quantum expires."),
    ("computer_networks", "scenario", "A video streaming server sends data over TCP. Explain how slow start and congestion avoidance adjust the congestion window as packets are acknowledged or lost."),
    ("computer_networks", "parameter", "Explain how TCP's congestion control changes the congestion window during slow start versus congestion avoidance when ssthresh is 16 segments."),
    ("ai_ml", "scenario", "A fruit-sorting machine uses k-nearest neighbours with k=3. Explain how it assigns a class to a new fruit from its weight and colour."),
    ("ai_ml", "representation", "Describe how the KNN classifier labels an unseen sample by majority vote of its closest training examples."),
    ("web_development", "scenario", "Write an HTML form for a gym membership sign-up that collects the member's full name and email address."),
    ("web_development", "constraint", "Create an HTML form with labelled input fields for a visitor's name and email, using only semantic HTML and no JavaScript."),
    ("software_engineering", "scenario", "A payments team is planning its test suite. Explain how unit tests differ from integration tests, with one example of each for a checkout service."),
    ("software_engineering", "structure", "Compare unit testing with integration testing in terms of scope, speed and the kinds of defects each finds."),
    ("mathematics", "parameter", "Find the derivative of g(x) = 4x^3 - 2x + 9."),
    ("mathematics", "representation", "Differentiate h(t) = 5t^2 + 3t - 1 with respect to t."),
    ("mathematics", "scenario", "A particle's position is s(t) = 3t^2 + 5t - 7 metres. Find its velocity by differentiating s(t)."),
]

# Drift: (seed key, what the candidate asks instead). Well-formed, on a neighbouring
# or unrelated task - exactly what must not pass as a variation.
DRIFTED: list[tuple[str, str]] = [
    # a different task altogether
    ("programming", "A music app stores its play queue as a singly linked list of track nodes. Implement a routine that reverses the queue without modifying the original nodes."),
    ("algorithms", "Implement a stack using an array with push and pop operations."),
    ("algorithms", "A playlist is stored as a linked list. Write a function that reverses it."),
    ("database", "Implement binary search on a sorted array of integers."),
    ("database", "Given a list of integers, write a Python function to find all duplicate elements and return them as a new list."),
    ("computer_networks", "Explain how a B-tree index speeds up lookups in a relational database."),
    ("ai_ml", "Explain how linear regression predicts a continuous value for a new data point."),
    ("web_development", "Write a CSS animation that makes a button fade in over two seconds."),
    ("operating_systems", "Explain how virtual memory uses paging."),
    ("software_engineering", "Explain the difference between a process and a thread."),
    ("mathematics", "Solve the equation 3x^2 + 5x - 7 = 0."),
    # a sibling concept in the same area, in nearly the same words
    ("programming", "Write a function to check whether a number is even."),
    ("programming", "Write a function to check whether a string is a palindrome."),
    ("algorithms", "Implement linear search on an unsorted array of integers."),
    ("data_structures", "Implement a queue that supports enqueue and dequeue using two stacks."),
    ("data_structures", "Implement a stack that supports push and pop."),
    ("database", "Write a SQL query to find the three highest salaries in an employees table."),
    ("operating_systems", "Explain how the shortest-job-first scheduling algorithm decides which process runs next."),
    ("computer_networks", "Explain how the TCP three-way handshake establishes a connection."),
    ("ai_ml", "Explain how the k-means algorithm groups data points into clusters."),
    ("web_development", "Write an HTML table that lists three products and their prices."),
    ("software_engineering", "Explain the difference between black-box testing and white-box testing."),
    ("software_engineering", "Differentiate between the two main types of software testing: regression testing and refactoring testing."),
    ("mathematics", "Find the integral of f(x) = 3x^2 + 5x - 7."),
    ("mathematics", "A local bakery sells cupcakes at a rate of f(x) = 4x^2 + 6x + 2 per hour. How many cupcakes are being sold per hour at the 3-hour mark?"),
]

PROSE_ANSWER = "The complete answer is stated here in full sentences, with the working shown."


def _seed(key: str):
    domain, text, _ = SEEDS[key]
    return seed_parser.heuristic_parse(text, domain)


def _candidate(seed, question: str, strategy: str = "scenario", answer_key: str = PROSE_ANSWER):
    """A candidate as the builder produces it: metadata the model is not asked for is
    copied from the seed, which is why copied fields can never prove anything."""
    return make_candidate(
        question, answer_key=answer_key, domain=seed.domain, strategy=strategy,
        topic=seed.topic, question_type=seed.question_type,
        learning_objective=seed.learning_objective,
    )


@pytest.fixture(scope="module", autouse=True)
def _warm():
    from backend.app.core.embeddings import embeddings

    embeddings.warm_up()


# ======================================================================
# Seed Contract
# ======================================================================
class TestSeedContract:
    @pytest.mark.parametrize("key", list(SEEDS))
    def test_contract_names_what_must_stay_the_same(self, key):
        seed = _seed(key)
        contract = seed_contract.build_contract(seed)
        assert contract.task == seed.raw_seed and contract.domain == seed.domain
        assert contract.learning_objective == seed.learning_objective
        assert contract.task_type == seed.question_type
        assert contract.required_elements == SEEDS[key][2]
        assert len(contract.required_elements) <= 2
        assert contract.immutable_elements and contract.allowed_variation_dimensions
        # Every required element is a word of the seed itself, never an outside label.
        seed_words = set(seed_contract.candidate_terms(seed.raw_seed))
        assert set(contract.required_elements) <= seed_words

    def test_the_concept_term_is_measured_not_looked_up(self):
        # An invented subject that appears in no vocabulary anywhere in the code base.
        seed = seed_parser.heuristic_parse(
            "Explain how a zorblax regulator stabilises quenching in a thermal lattice.", "science"
        )
        contract = seed_contract.build_contract(seed)
        assert contract.required_elements
        assert contract.required_elements[0] in {"zorblax", "regulator", "quenching", "lattice", "thermal"}
        weights = contract.element_weights
        assert max(weights, key=weights.get) in {"zorblax", "quenching", "lattice"}
        assert "explain" not in weights and "how" not in weights

    def test_salience_puts_the_concept_above_the_instruction_words(self):
        ranked = [t for t, _ in seed_contract.term_salience("Write a function to check whether a number is prime.")]
        assert ranked[0] == "prime" and "check" not in ranked and "whether" not in ranked

    def test_named_technology_constraints_and_parameters_are_extracted(self):
        seed = seed_parser.heuristic_parse(
            "Write a Python function that sorts 3 arrays of at most 100 integers in O(n log n) time "
            "without using the built-in sort.", "programming",
        )
        contract = seed_contract.build_contract(seed)
        assert "Python" in contract.named_elements
        assert contract.parameters == ["3", "100"]
        joined = " | ".join(contract.constraints)
        assert "without using the built-in sort" in joined and "at most 100 integers" in joined
        assert "o(n log n) time" in joined
        assert seed_contract.build_contract(_seed("database")).named_elements == ["SQL"]
        assert seed_contract.build_contract(_seed("computer_networks")).named_elements == ["TCP"]

    def test_fields_that_cannot_be_determined_stay_empty(self):
        contract = seed_contract.build_contract(_seed("software_engineering"))
        assert contract.named_elements == [] and contract.constraints == []
        assert contract.parameters == [] and contract.structure_anchor is None

    def test_a_structure_is_immutable_only_when_it_carries_the_concept(self):
        linked = seed_parser.heuristic_parse("Write a function to reverse a singly linked list.", "programming")
        assert seed_contract.build_contract(linked).structure_anchor == "linked list"
        # "on a sorted array" is incidental to binary search.
        assert seed_contract.build_contract(_seed("algorithms")).structure_anchor is None

    def test_contract_is_cached_and_attached_by_the_pipeline(self, monkeypatch, temp_data_dir):
        seed = _seed("programming")
        assert seed_contract.build_contract(seed) is seed_contract.build_contract(seed)
        fake = FakeOllama([json.dumps({"question": FAITHFUL[0][2], "answer_key": "def is_prime(n):\n    return n > 1 and all(n % i for i in range(2, int(n ** 0.5) + 1))"})])
        monkeypatch.setattr("backend.app.ps8.generation_engine.ollama", fake)
        parsed, _r, _s, timings, _w = pipeline.run_pipeline(
            seed.raw_seed, "programming", 1, use_llm_parser=False, persist=False, enable_regeneration=False
        )
        assert parsed.contract is not None and parsed.contract.required_elements == ["prime"]
        assert "ps8.seed_contract" in timings


# ======================================================================
# Strategy Contract and the method axis
# ======================================================================
class TestStrategyContract:
    @pytest.mark.parametrize("strategy", strategies.list_strategies(), ids=lambda s: s.id)
    def test_every_strategy_states_its_dimension_and_its_limits(self, strategy):
        assert strategy.dimension and strategy.change and strategy.preserve
        assert "learning objective" in strategy.preserve and "core concept" in strategy.preserve
        prohibited = " ".join(strategy.must_not_change)
        for forbidden in ("core learning objective", "task the learner performs", "domain"):
            assert forbidden in prohibited

    def test_no_strategy_invites_a_different_subject(self):
        for strategy in strategies.list_strategies():
            text = strategy.instruction.lower()
            assert "different underlying data structure" not in text
            assert "inverse transformation" not in text
            assert "application domain" not in text

    def test_plan_items_carry_the_strategy_contract(self):
        for item in variation_planner.plan_variations(_seed("programming"), 5):
            assert item.dimension and item.must_not_change == strategies.PROHIBITED_CHANGES

    @pytest.mark.parametrize("key,expected", [
        ("programming", ["iterative", "recursive"]),
        ("algorithms", ["iterative", "recursive"]),
        ("data_structures", []),      # a design with operations, not one routine
        ("database", []),             # a query has no control flow to vary
        ("web_development", []),      # markup
        ("operating_systems", []),    # not code
        ("mathematics", []),
    ])
    def test_a_method_is_planned_only_where_it_applies(self, key, expected):
        seed = _seed(key)
        assert [m.id for m in methods.applicable_methods(seed)] == expected
        planned = {p.method for p in variation_planner.plan_variations(seed, 8)}
        assert planned == (set(expected) or {None})

    def test_the_linked_list_seed_keeps_all_four_methods(self):
        seed = seed_parser.heuristic_parse("Write a function to reverse a singly linked list.", "programming")
        assert [m.id for m in methods.applicable_methods(seed)] == ["iterative", "recursive", "auxiliary", "rebuild"]


# ======================================================================
# Generation prompt
# ======================================================================
class TestGenerationPrompt:
    @pytest.mark.parametrize("key", list(SEEDS))
    def test_prompt_is_a_structured_contract(self, key):
        seed = _seed(key)
        contract = seed_contract.build_contract(seed)
        for item in variation_planner.plan_variations(seed, 5):
            prompt = prompt_builder.build_generation_prompt(seed, item)
            for section in ("ORIGINAL SEED:", "SEED CONTRACT", "IMMUTABLE", "CURRENT VARIATION STRATEGY",
                            "YOU MAY CHANGE:", "YOU MUST PRESERVE:", "YOU MUST NOT CHANGE:"):
                assert section in prompt
            assert seed.raw_seed in prompt and contract.learning_objective in prompt
            assert "It is still explicitly about: " + ", ".join(contract.required_elements) in prompt
            assert "the core learning objective" in prompt
            assert item.strategy_label in prompt and item.dimension in prompt

    @pytest.mark.parametrize("key", list(SEEDS))
    def test_prompt_never_mentions_a_subject_the_seed_does_not(self, key):
        """The prompt used to carry linked-list examples into every coding seed."""
        seed = _seed(key)
        for item in variation_planner.plan_variations(seed, 8):
            prompt = prompt_builder.build_generation_prompt(seed, item).lower()
            for foreign in ("linked list", "listnode", "reverse(head)", ".next", "new_head"):
                assert foreign not in prompt, f"{foreign!r} leaked into the {key} prompt"
            # ...nor the subject of any other seed in the matrix.
            for other, (_d, _t, terms) in SEEDS.items():
                if other == key:
                    continue
                own = set(seed_contract.candidate_terms(seed.raw_seed))
                for term in terms:
                    if term not in own and term not in {"form", "search", "testing"}:
                        assert f" {term} " not in f" {prompt} ", f"{term!r} ({other}) leaked into {key}"

    @pytest.mark.parametrize("key", list(SEEDS))
    def test_prompt_tells_the_model_how_not_to_copy_the_seed(self, key):
        """A question that repeats the seed's sentence and appends the change is a
        near-copy; each strategy says what its question opens with instead."""
        seed = _seed(key)
        opening_words = " ".join(seed.raw_seed.split()[:6])
        for item in variation_planner.plan_variations(seed, 5):
            prompt = prompt_builder.build_generation_prompt(seed, item)
            strategy = strategies.get_strategy(item.strategy)
            assert "HOW TO WRITE IT" in prompt and strategy.opening in prompt
            assert f'Do not begin with "{opening_words}"' in prompt
            assert "specifics of its own" in prompt and "at least two sentences" in prompt

    def test_every_strategy_opens_with_what_it_introduces(self):
        openings = {s.id: s.opening for s in strategies.list_strategies()}
        assert all(o.startswith("Open with") for o in openings.values())
        assert len(set(openings.values())) == len(openings)  # one per strategy, not a shared line

    def test_named_technology_and_seed_constraints_are_listed_as_immutable(self):
        seed = _seed("database")
        prompt = prompt_builder.build_generation_prompt(seed, variation_planner.plan_variations(seed, 1)[0])
        assert "It keeps the technology / named concept of the seed: SQL." in prompt
        constrained = seed_parser.heuristic_parse(
            "Write a function to reverse a singly linked list in-place.", "programming"
        )
        plan = variation_planner.plan_variations(constrained, 2)
        assert "It keeps the seed's stated constraints: in-place." in prompt_builder.build_generation_prompt(constrained, plan[0])
        # The constraint strategy is the one that may change them.
        assert plan[1].strategy == "constraint"
        assert "stated constraints" not in prompt_builder.build_generation_prompt(constrained, plan[1])


# ======================================================================
# PS8: concept / learning-objective preservation
# ======================================================================
class TestDriftDetection:
    @pytest.mark.parametrize("key,strategy,question", FAITHFUL, ids=lambda v: v if len(str(v)) < 24 else None)
    def test_faithful_variations_keep_the_objective(self, key, strategy, question):
        seed = _seed(key)
        result = validators.validate_concept(_candidate(seed, question, strategy), seed)
        assert result.preserved, result.reasons
        assert result.missing_elements == []

    @pytest.mark.parametrize("key,question", DRIFTED, ids=lambda v: v if len(str(v)) < 24 else None)
    def test_a_different_task_is_never_a_variation(self, key, question):
        seed = _seed(key)
        candidate = _candidate(seed, question)
        result = validators.validate_concept(candidate, seed)
        assert not result.preserved
        assert any(r.startswith(("learning objective changed", "concept not preserved")) for r in result.reasons)

        # ...and it fails PS8 as a whole, so the decision can never be a normal PASS,
        # however reliable PS2 finds its statements.
        structural = validate_candidate(candidate, seed)
        assert not structural.concept_preserved and not structural.passed
        assert decide(structural, None).decision != "PASS"

    def test_similar_wording_does_not_rescue_a_different_concept(self):
        seed = _seed("programming")
        even = validators.validate_concept(_candidate(seed, "Write a function to check whether a number is even."), seed)
        # Similarity to the seed is far above the floor - on that signal alone (all
        # there was before the contract) this was accepted as a variation.
        from backend.app.config import settings

        assert even.semantic_similarity >= settings.concept_min_semantic + 0.3
        assert not even.preserved and even.missing_elements == ["prime"]

    def test_different_wording_does_not_condemn_the_same_concept(self):
        seed = _seed("mathematics")
        result = validators.validate_concept(
            _candidate(seed, "Differentiate h(t) = 5t^2 + 3t - 1 with respect to t."), seed
        )
        assert result.preserved and result.element_matches["derivative"].startswith("synonym: differentiate")

    def test_acronyms_abbreviations_and_identifiers_count_as_the_term(self):
        knn = _seed("ai_ml")
        r = validators.validate_concept(_candidate(knn, FAITHFUL[13][2]), knn)
        assert r.element_matches == {"nearest": "acronym", "neighbours": "acronym"}
        stack = _seed("data_structures")
        assert validators.validate_concept(_candidate(stack, FAITHFUL[4][2]), stack).element_matches == {"minimum": "present"}

    def test_a_seed_word_cannot_stand_in_for_another_seed_word(self):
        seed = _seed("computer_networks")
        r = validators.validate_concept(_candidate(seed, "Explain how the TCP three-way handshake establishes a connection."), seed)
        assert r.element_matches["tcp"] == "present" and r.element_matches["congestion"] == "missing"

    def test_the_concept_may_live_in_the_answer_key(self):
        seed = _seed("software_engineering")
        question = ("A developer tests each module on its own, then tests that the modules work together. "
                    "Name the two kinds of testing being performed and say how they differ.")
        without = validators.validate_concept(_candidate(seed, question), seed)
        assert without.missing_elements == ["integration"]
        answered = _candidate(seed, question, answer_key="Unit testing checks one module alone; integration testing checks modules together.")
        with_key = validators.validate_concept(answered, seed)
        assert with_key.preserved and with_key.element_matches["integration"] == "in answer key"

    def test_a_coding_seed_keeps_its_named_technology(self):
        seed = _seed("database")
        python = validators.validate_concept(
            _candidate(seed, "Given a list of integers, write a Python function to find all duplicate elements."), seed
        )
        assert "SQL" in python.missing_elements
        # A descriptive seed's modifier ("CPU") is not demanded of every variation.
        rr = _seed("operating_systems")
        assert validators.validate_concept(_candidate(rr, FAITHFUL[9][2]), rr).preserved

    def test_known_limit_a_concept_described_but_never_named_is_sent_back(self):
        """Documented behaviour, not a goal: with no term and no synonym to match, the
        check cannot tell a definition from a different task, so it asks for the
        concept to be named. The candidate is regenerated, never silently dropped."""
        seed = _seed("programming")
        r = validators.validate_concept(_candidate(
            seed, "Write a function that determines whether a positive integer has no divisors other than 1 and itself."), seed)
        assert not r.preserved and r.missing_elements == ["prime"]


# ======================================================================
# PS8: strategy compliance
# ======================================================================
class TestStrategyCompliance:
    def test_scenario_without_a_new_setting_fails(self):
        seed = _seed("web_development")
        copy = validators.validate_strategy(_candidate(seed, "Write an HTML form that collects a user's name and email address, please.", "scenario"), seed)
        assert copy.followed is False and copy.reasons[0].startswith("strategy not followed")
        real = validators.validate_strategy(_candidate(seed, FAITHFUL[14][2], "scenario"), seed)
        assert real.followed is True

    def test_parameter_variation_must_change_the_values(self):
        seed = _seed("mathematics")
        same = validators.validate_strategy(_candidate(seed, "Find the derivative of g(x) = 3x^2 + 5x - 7.", "parameter"), seed)
        assert same.followed is False and "reuses the seed's" in same.reasons[0]
        changed = validators.validate_strategy(_candidate(seed, "Find the derivative of g(x) = 4x^3 - 2x + 9.", "parameter"), seed)
        assert changed.followed is True

    @pytest.mark.parametrize("strategy,question,expected", [
        ("constraint", "Implement binary search recursively; do not use loops.", True),
        ("constraint", "Implement binary search, using recursion rather than a loop.", None),
        ("structure", "The following function has a bug. Find and fix it.", True),
        ("structure", "Implement binary search on a sorted array.", None),
        ("representation", "Which of the following is the derivative of 3x^2?\nA) 6x\nB) 3x", True),
        ("representation", "Find the derivative of 3x^2.", None),
    ])
    def test_unverifiable_changes_are_reported_not_failed(self, strategy, question, expected):
        seed = _seed("algorithms")
        result = validators.validate_strategy(_candidate(seed, question, strategy), seed)
        assert result.followed is expected and result.reasons == []

    def test_a_failed_strategy_fails_ps8_and_is_recorded(self):
        seed = _seed("mathematics")
        structural = validate_candidate(
            _candidate(seed, "Find the derivative of the function g(x) = 3x^2 + 5x - 7 and simplify it.", "parameter"), seed
        )
        assert structural.strategy_followed is False and not structural.passed
        assert structural.checks["strategy"]["id"] == "parameter"
        assert structural.checks["contract"]["required_elements"] == ["derivative"]


# ======================================================================
# Answer keys for code that is not a function
# ======================================================================
class TestCodeArtifacts:
    @pytest.mark.parametrize("key,answer", [
        ("database", "SELECT email, COUNT(*) FROM users GROUP BY email HAVING COUNT(*) > 1;"),
        ("database", "select email from users group by email having count(*) > 1"),
        ("web_development", "<form>\n  <label>Name <input name=\"name\" required></label>\n  <label>Email <input type=\"email\" name=\"email\" required></label>\n</form>"),
    ])
    def test_a_query_or_markup_is_a_real_answer(self, key, answer):
        seed = _seed(key)
        assert seed.question_type == "coding"
        result = validators.validate_answer_key(_candidate(seed, SEEDS[key][1], answer_key=answer), seed)
        assert result.substantive and result.has_code

    @pytest.mark.parametrize("key", ["database", "web_development", "programming"])
    def test_a_description_is_still_not_an_answer(self, key):
        seed = _seed(key)
        prose = "The solution should group the rows and keep only the groups that occur more than once."
        result = validators.validate_answer_key(_candidate(seed, SEEDS[key][1], answer_key=prose), seed)
        assert not result.substantive and result.has_code is False


class TestPlaceholderAnswerKey:
    """The JSON template shows a hint where the answer goes; a weak model sometimes
    returns the hint itself."""

    @pytest.mark.parametrize("key", ["software_engineering", "programming", "mathematics"])
    def test_the_prompts_own_placeholder_is_not_an_answer(self, key):
        seed = _seed(key)
        for hint in prompt_builder.ANSWER_HINTS.values():
            for text in (hint, hint.capitalize(), hint + "."):
                result = validators.validate_answer_key(_candidate(seed, SEEDS[key][1], answer_key=text), seed)
                assert not result.substantive and "placeholder" in result.reasons[0]

    def test_the_hints_checked_are_the_ones_in_the_prompt(self):
        coding, prose = _seed("programming"), _seed("software_engineering")
        plan = variation_planner.plan_variations(coding, 1)[0]
        assert prompt_builder.ANSWER_HINTS["coding"] in prompt_builder.build_generation_prompt(coding, plan)
        plan = variation_planner.plan_variations(prose, 1)[0]
        assert prompt_builder.ANSWER_HINTS["other"] in prompt_builder.build_generation_prompt(prose, plan)

    def test_a_placeholder_answer_is_regenerated_with_the_answer_instruction(self, monkeypatch, temp_data_dir):
        seed_text = SEEDS["software_engineering"][1]
        question = ("A payments team is planning its test suite for a checkout service. Explain how unit testing "
                    "differs from integration testing, with one example of each.")
        fake = FakeOllama([
            json.dumps({"question": question, "answer_key": prompt_builder.ANSWER_HINTS["other"]}),
            json.dumps({"question": question, "answer_key": "Unit testing checks one function in isolation; integration testing checks that modules work together."}),
        ])
        monkeypatch.setattr("backend.app.ps8.generation_engine.ollama", fake)
        _s, results, _sum, _t, _w = pipeline.run_pipeline(seed_text, "programming", 1, use_llm_parser=False, persist=False)
        item = results[0]
        assert fake.calls == 2 and item.regeneration_history[0]["decision"] == "REJECT"
        assert any("placeholder" in r for r in item.regeneration_history[0]["structural_reasons"])
        assert "MUST state the final answer explicitly" in fake.prompts[1]
        assert item.structural_validation.checks["answer_key"]["substantive"]


# ======================================================================
# Failure-aware regeneration
# ======================================================================
class TestFailureAwareRegeneration:
    def _fixes(self, key, reasons, reliability=(), shift=None):
        seed = _seed(key)
        plan = variation_planner.plan_variations(seed, 1)[0]
        return " ".join(prompt_builder.failure_instructions(seed, plan, list(reasons), list(reliability), difficulty_shift=shift))

    def test_objective_change_asks_to_restore_the_objective(self):
        seed = _seed("database")
        drifted = _candidate(seed, "Given a list of integers, write a Python function to find all duplicate elements.")
        reasons = validators.validate_concept(drifted, seed).reasons
        text = self._fixes("database", reasons)
        assert "changed the underlying task" in text
        assert "Preserve the original learning objective" in text and "duplicate, SQL" in text
        # The reason mentions "similarity"; that must not be read as "too similar".
        assert "more meaningfully different" not in text

    def test_too_similar_asks_for_a_bigger_change_along_the_strategy(self):
        text = self._fixes("programming", ["semantic similarity too high: 0.91 against the seed question (threshold 0.86)"])
        assert "Preserve the core learning objective" in text and "more meaningfully different" in text
        assert "changed the underlying task" not in text
        paraphrase = self._fixes("programming", ["not a meaningful variation: 0.88 semantic similarity to the seed reads as a paraphrase (max 0.80)"])
        assert "more meaningfully different" in paraphrase

    def test_too_similar_repeats_how_the_question_must_open(self):
        seed = _seed("database")
        plan = variation_planner.plan_variations(seed, 2)[1]  # constraint
        text = " ".join(prompt_builder.failure_instructions(
            seed, plan, ["semantic similarity too high: 0.95 against the seed question (threshold 0.86)"], []))
        assert strategies.get_strategy("constraint").opening in text
        assert "Do not start the way the seed or the rejected question starts" in text
        assert "keeping it explicitly about duplicate, SQL" in text

    def test_difficulty_mismatch_says_which_way_to_move(self):
        hard = self._fixes("programming", ["difficulty mismatch: candidate is 'hard' (0.85) but target is 'easy' (0.25) - 0.60 harder than the allowed tolerance of 0.20"])
        assert "adjusting the complexity" in hard and "too hard" in hard and "'medium'" in hard
        easy = self._fixes("programming", ["difficulty mismatch: candidate is 'easy' (0.25) but target is 'hard' (0.85) - 0.60 easier than the allowed tolerance of 0.20"], shift="hard")
        assert "too easy" in easy and "'hard'" in easy

    def test_each_other_failure_has_its_own_instruction(self):
        assert "did not apply the requested strategy" in self._fixes("mathematics", ["strategy not followed: a parameter variation must change the concrete values"])
        assert "moved too far from the seed" in self._fixes("mathematics", ["variation drifted too far: only 0.05 semantic similarity to the seed (min 0.10)"])
        assert "runnable reference solution" in self._fixes("programming", ["answer key describes a solution instead of giving one: a coding question needs code"])
        assert "cannot be certain is true" in self._fixes("mathematics", [], ["3 claim(s) could not be grounded in the local reference corpus"])
        assert "mutually consistent" in self._fixes("mathematics", [], ["contradicts the reference corpus entry"])

    def test_regeneration_prompt_carries_the_reason_and_the_instruction(self):
        seed = _seed("algorithms")
        plan = variation_planner.plan_variations(seed, 1)[0]
        reasons = validators.validate_concept(_candidate(seed, "Implement linear search on an unsorted array of integers."), seed).reasons
        prompt = prompt_builder.build_regeneration_prompt(
            seed, plan, rejected_question="Implement linear search on an unsorted array of integers.",
            structural_reasons=reasons, reliability_reasons=[], flagged_spans=[],
        )
        assert "WHY IT WAS REJECTED" in prompt and "learning objective changed" in prompt
        assert "no longer mentions binary" in prompt
        assert "WHAT YOU MUST DO DIFFERENTLY" in prompt and "keep the question explicitly about binary, search" in prompt
        assert "Address every problem listed above" not in prompt  # never the generic fallback here


# ======================================================================
# End to end: drift is rejected, regenerated with the reason, never passed
# ======================================================================
SQL_ANSWER = "SELECT phone, COUNT(*) FROM contacts GROUP BY phone HAVING COUNT(*) > 1;"
PYTHON_ANSWER = "def duplicates(xs):\n    seen, out = set(), []\n    for x in xs:\n        if x in seen:\n            out.append(x)\n        seen.add(x)\n    return out"


def _reply(question: str, answer: str) -> str:
    # Only the fields the generation prompt asks for; the rest is filled from the seed.
    return json.dumps({"question": question, "answer_key": answer, "difficulty": "medium", "test_cases": []})


class TestPipelineNeverPassesDrift:
    def _run(self, monkeypatch, replies, key="database", **kw):
        fake = FakeOllama(replies)
        monkeypatch.setattr("backend.app.ps8.generation_engine.ollama", fake)
        domain, text, _ = SEEDS[key]
        _seed_md, results, _s, _t, _w = pipeline.run_pipeline(
            text, domain, 1, use_llm_parser=False, persist=False, **kw
        )
        return fake, results

    def test_a_drifted_candidate_is_rejected_not_passed(self, monkeypatch, temp_data_dir):
        _fake, results = self._run(
            monkeypatch,
            [_reply("Given a list of integers, write a Python function to find all duplicate elements and return them as a new list.", PYTHON_ANSWER)],
            enable_regeneration=False,
        )
        item = results[0]
        assert item.decision == "REJECT"
        assert not item.structural_validation.concept_preserved
        assert any("learning objective changed" in r for r in item.decision_reasons)
        assert item.reliability_verification is not None  # PS2 still ran; it does not own this check

    def test_regeneration_is_told_what_changed_and_recovers(self, monkeypatch, temp_data_dir):
        good = ("A support desk keeps customer records in a contacts table with a phone column. "
                "Write a SQL query that returns every duplicate phone number together with how many times it appears.")
        fake, results = self._run(
            monkeypatch,
            [_reply("Given a list of integers, write a Python function to find all duplicate elements and return them as a new list.", PYTHON_ANSWER),
             _reply(good, SQL_ANSWER)],
        )
        item = results[0]
        assert fake.calls == 2 and item.attempts == 2
        retry = fake.prompts[1]
        assert "REGENERATION" in retry and "learning objective changed" in retry
        assert "changed the underlying task" in retry and "duplicate, SQL" in retry
        assert item.structural_validation.concept_preserved
        assert item.regeneration_history[0]["decision"] == "REJECT"
        assert item.candidate.question == good

    def test_drift_on_every_attempt_ends_in_review_never_pass(self, monkeypatch, temp_data_dir):
        drift = _reply("Given a list of integers, write a Python function to find all duplicate elements and return them as a new list.", PYTHON_ANSWER)
        _fake, results = self._run(monkeypatch, [drift, drift, drift])
        item = results[0]
        assert item.attempts == 3 and item.decision == "REVIEW"
        assert not item.structural_validation.passed

    @pytest.mark.parametrize("key,question", [d for d in DRIFTED if d[0] in ("operating_systems", "mathematics", "ai_ml", "computer_networks")][:8],
                             ids=lambda v: v if len(str(v)) < 24 else None)
    def test_non_code_drift_is_rejected_too(self, monkeypatch, temp_data_dir, key, question):
        _fake, results = self._run(monkeypatch, [_reply(question, PROSE_ANSWER)], key=key, enable_regeneration=False)
        assert results[0].decision == "REJECT"
