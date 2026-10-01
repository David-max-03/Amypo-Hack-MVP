# BUILD_STATUS — Stage 2 Acceptance Test

**Code Titans · HackWithAMYPO 2026 · PS8 + PS2 integrated track**

**Run:** 2026-09-29, 23:30–23:41 IST, on the **Docker stack rebuilt from the current code**
(`docker compose build` + `up -d --force-recreate`), using host Ollama with `qwen2.5-coder:7b`.

- **Code check:** all 38 `backend/app` source files in the running container are byte-identical
  (SHA-256) to the repository, including the PS2 false-positive changes. See
  `01_container_code_check.txt`.
- **Every number below comes from this run only.** Raw outputs are in
  [`docs/acceptance/`](docs/acceptance/). Results from earlier runs have been moved to
  `docs/acceptance/superseded/` and are not used here.
- **Environment caveat for all timings:** Apple M5 (16 GB) **on battery with macOS Low Power
  Mode on**; Ollama `OLLAMA_NUM_PARALLEL=4`; backend `AMYPO_GENERATION_CONCURRENCY=4`.

Status key: **PASS** = met and demonstrated in this run · **PARTIAL** = works, with a stated gap
· **FAIL** = not met.

---

## PS8 Stage 2 requirements

> Official Stage 2 bar: *"A working variation engine that generates at least 10–15 valid
> variations for one domain from a single seed question, with a basic /generate endpoint …
> built without external APIs."*

| Requirement | Status | Evidence | Test command | Actual result |
|---|---|---|---|---|
| **≥ 10 valid variations from one seed, one domain** | **PASS** | `05_generate_count10.json` | `POST /api/v1/generate` `{"seed_question":"Write a function to reverse a singly linked list.","domain":"programming","count":10}` (via nginx :5173) | generated **10**, structurally accepted **10**, rejected 0 |
| `/generate` honours the PS8 API contract | **PASS** | `05_generate_count10.json` | same | every variation has `question`, `answer_key` and a numeric `difficulty`; top-level `duplicate_rate` present |
| Near-duplicate rate < 10 % | **PASS** | `05_generate_count10.json` | same | `duplicate_rate: 0.0` |
| Difficulty equivalence | **PARTIAL** | `05_generate_count10.json` → `checks.difficulty` | same | 10/10 `matched: true` (seed `medium` 0.51; every variation `medium` 0.55, delta 0.04). **Gap:** the estimator gave all 10 the same score, so the check does not tell variations apart |
| Controlled variation strategies | **PASS** | `05_generate_count10.json` | same | scenario 2 · parameter 2 · constraint 2 · structure 2 · representation 2 |
| Different solution methods | **PASS** | `05_generate_count10.json` → `checks.method` | same | iterative 3 · recursive 3 · auxiliary 2 · rebuild 2; method verified in the answer code 10/10 |
| Answer key for every variation | **PARTIAL** | `05_generate_count10.json` → `checks.answer_key` | same | 10/10 answer keys are code (`has_code: true`). **Gap:** keys are **not executed** against their test cases |
| Regeneration from rejection feedback (`/generate`) | **PASS** | `05_generate_count10.json` | same | `regeneration_attempts: 4`, `regenerated_accepted: 4`; each replacement was re-validated before acceptance |
| Generation time | **PASS** (Stage 2) | `05_generate_count10.env.txt`, `timings_ms` | same | **318.8 s** wall: seed parse 12.2 s · generation 225.0 s · regeneration 80.9 s · validation 0.7 s (battery + Low Power Mode) |
| ≥ 5 domains · `GET /domains` | **PASS** | test `test_domains_meets_the_ps8_minimum_of_five` | `pytest` | passes (7 domains) |
| `GET /health` | **PASS** | `02_health.json` | `GET /api/v1/health` | `status: ok`; Ollama at `host.docker.internal:11434` reachable with the model available; MiniLM loaded, `load_error: null`; corpus 36 entries |
| No paid / external LLM APIs | **PASS** | `02_health.json` | same | generation is local Ollama; embeddings are local MiniLM |
| Low-confidence review queue | **PASS** | `08_generate_and_verify_count3.json` | `POST /api/v1/generate-and-verify` (count 3) | 2 of 3 routed to `REVIEW` (see the integrated section below) |
| One-command Docker startup | **PASS** | `01_container_code_check.txt`, `02_health.json` | `AMYPO_GENERATION_CONCURRENCY=4 docker compose up -d --force-recreate` | both containers running; health `ok` |

---

## PS2 Stage 2 requirements

> Official Stage 2 bar: *"A working analyzer that produces a reliability score and at least one
> flagged span for a subset of the benchmark response set … built without external APIs."*

| Requirement | Status | Evidence | Test command | Actual result |
|---|---|---|---|---|
| **Produces a reliability score** | **PASS** | `04_verify_10_correct_questions.json` | `POST /api/v1/verify` (via nginx :5173) on the **same 10 correct questions** (`03_input_10_correct_questions.json`, sha256 prefix `dc723467e9a65d8f`) | 10/10 scored; `reliability_score` 0.4832–0.8213; `hallucination_probability` 0.0750–0.3937 |
| **No correct question labelled misleading (same 10)** | **PASS** | `04_verify_10_correct_questions.json` | same | trustworthy **1** · partially_reliable **6** · misleading **0** · fabricated **0** · unverifiable **3**; 0 contradictions detected |
| No correct question labelled misleading (**10 new** questions) | **PARTIAL** | `06_verify_10_new_questions.json` | `/verify` on the 10 questions generated in this run (`05_…json`) | trustworthy 0 · partially_reliable 2 · **misleading 1** · fabricated 0 · unverifiable 7. The 1 is a **false positive**: numbered test-case comments in the answer key (`# 1. Reversing a list with no duplicates` / `# 2. … with duplicates`) are not masked as code and were read as contradicting claims |
| **≥ 1 flagged span on problematic responses** | **PASS** | `07_verify_problematic_fixtures.json` | `/verify` on the 6 fixtures in `data/demo/problematic_responses.json` | fabricated citation `partially_reliable`, 4 spans · corpus contradiction `misleading`, 2 · self-contradiction `misleading`, 1 · wrong-but-plausible (Dijkstra) `misleading`, 2 · unverifiable `unverifiable`, 1 |
| No flag on a correct grounded response | **PASS** | `07_verify_problematic_fixtures.json` | fixture `demo-05-grounded-control` | `trustworthy`, reliability 0.9791, **0 spans** |
| Flagged-span / hallucination tests | **PASS** | `09_test_suite.txt` | `pytest -k "Flagged or flagged or fabricat or hallucinat or grounded_control or ContradictionsStillCaught or NoFalsePositives"` (in container) | 19 passed |
| Run on a subset of the **organiser benchmark** | **PARTIAL** | — | — | benchmark set **not received**; tested on our 6 fixtures plus 20 generated questions |
| `/verify` API contract | **PASS** | `04_…json`, `07_…json` | same | `reliability_score`, `hallucination_probability`, `verdict` and `flagged_spans[{text, reason}]` all present |
| Response analysis time < 10 s | **PASS** | `04_…json`, `06_…json`, `07_…json` (`wall_ms`) | same | 28.0–514.2 ms per generated question; 13.5–75.9 ms per fixture |
| Contradiction detection | **PASS** | `07_…json` | fixtures demo-02, demo-03, demo-04 | corpus contradictions and the O(log n) vs O(n) self-contradiction are flagged → `misleading` |
| Unverifiable ≠ false | **PASS** | `07_…json`, `08_…json` | fixture demo-06; pipeline | demo-06 → `unverifiable`; in the pipeline, `unverifiable` → `REVIEW` |
| Explainability: every span has a reason | **PASS** (API) · **PARTIAL** (dashboard) | all PS2 evidence files | — | every flagged span carries a `reason`; the UI's span view has **not been checked in a browser** |
| Reliability score consistent with verdict | **PARTIAL** | `07_…json` | fixtures demo-02/03/04 | verdict `misleading` with `reliability_score` 0.81–0.86 |
| Detection accuracy (precision / recall) | **FAIL** (not measured) | — | — | no labelled benchmark run; **no accuracy figure is claimed** |

---

## Integrated pipeline: REVIEW and regeneration

`POST /api/v1/generate-and-verify` `{"seed_question":"Write a function to reverse a singly linked list.","domain":"programming","count":3,"persist":false}`
→ HTTP 200, **191.0 s**. Evidence: `08_generate_and_verify_count3.json`.

| Requirement | Status | Actual result |
|---|---|---|
| PASS / REVIEW / REJECT decisions | **PASS** | final: **PASS 1 · REVIEW 2 · REJECT 0**; mean reliability 0.5766; 4 flagged spans; `duplicate_rate` 0.3333 (over all 3 final candidates, including the one that hit the retry cap) |
| REVIEW, unverifiable | **PASS** | candidate 1 (iterative): PS8 passed; PS2 `unverifiable`, reliability 0.4055 → `REVIEW` |
| Rejection → regeneration → re-validation → PASS | **PASS** | candidate 3 (auxiliary): attempt 1 **REJECT** (*"semantic similarity too high: 0.91 against the seed"*) → regenerated with those reasons → PS8 passed, PS2 reliability **0.7477** (`partially_reliable`) → **PASS**, `attempts: 2` |
| Retry cap → REVIEW, not a loop or a silent drop | **PASS** | candidate 2 (recursive): REJECT at 0.88, then again at 0.86 (both re-validated), then **REVIEW** at the cap, `attempts: 3` |
| Regeneration tests | **PASS** | `pytest -k "regenerat or max_attempts or retried or both_gates or missing_reliability or high_hallucination"` in the container: **17 passed** |

---

## Automated test suite

| Requirement | Status | Evidence | Test command | Actual result |
|---|---|---|---|---|
| Full suite, local | **PASS** | `09_test_suite.txt` | `.venv/bin/python -m pytest` | **183 passed** in 10.02 s (Python 3.12.14) |
| Full suite, inside the backend container | **PASS** | `09_test_suite.txt` | `docker compose exec backend python -m pytest` | **183 passed** in 10.41 s |

---

## Remaining limitations (from this run)

1. **One code-related PS2 false positive remains:** numbered comments such as `# 1. …` in an
   answer key are not masked (1 of the 10 new questions was labelled `misleading`).
2. **PS2 missed a genuinely flawed question.** The same new question demands "no additional
   memory, including local variables" and "a constant amount of recursion depth". That is
   impossible for recursive reversal, and its answer uses a local variable.
3. **`unverifiable` is common** (3/10 and 7/10) because scenario details are not in the
   36-entry corpus. These route to REVIEW.
4. **Verdict / score mismatch:** `misleading` responses keep reliability 0.81–0.86.
5. **Difficulty estimator is flat:** all variations scored 0.55.
6. **Answer keys are not executed.**
7. **Organiser benchmark and harness not received:** PS2 accuracy is unmeasured.
8. **Frontend not checked in a browser.**
9. **Speed:** timings were taken on battery with Low Power Mode on. The Stage 3 target (60
   variations in < 5 min) is not met; see `docs/MODEL_CARD.md`.

---

## Demo script (3–5 min)

Pre-flight: AC power, Low Power Mode off, `OLLAMA_NUM_PARALLEL=4 ollama serve`,
`AMYPO_GENERATION_CONCURRENCY=4 docker compose up -d`, and `/api/v1/health` → `ok`.
Generating 10 took 318.8 s on battery in this run, so **start step 2 before recording, or cut
to the result**.

```
START
  └─ GET /api/v1/health → "ok", Ollama reachable, MiniLM loaded, corpus 36
1. SEED QUESTION → "Write a function to reverse a singly linked list." (programming)
2. GENERATE 10 VARIATIONS → POST /api/v1/generate count=10
     → 10/10 accepted, 5 strategies × 4 methods, answer keys are code
3. STRUCTURAL VALIDATION → one variation's checks: concept anchor · difficulty ·
     not duplicate / paraphrase · answer key is code · method verified; duplicate_rate 0.0
4. PS2 VERIFICATION → POST /api/v1/verify on fixture demo-02 ("always uses O(1) space")
5. RELIABILITY SCORE → reliability_score + hallucination_probability + verdict "misleading"
6. FLAGGED SPAN → "…always uses O(1)…" → contradicts corpus entry
     "Recursive linked list reversal space cost"; contrast demo-05 → trustworthy, 0 spans
7. PASS / REVIEW / REJECT → POST /api/v1/generate-and-verify count=3
     → PASS (both gates) and REVIEW (unverifiable → human)
8. REGENERATION → regeneration_history: REJECT "0.91 similarity to the seed"
     → reasons fed into the next prompt
9. FINAL ACCEPTED QUESTION → re-validated: PS8 passed, PS2 0.75 → PASS → export CSV
END
```
