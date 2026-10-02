# Semantic drift — before and after the Seed Contract

Script: [`scripts/drift_eval.py`](../../scripts/drift_eval.py). Raw data, one file per run:
`baseline_*.json` (code before the change), `contract_*.json` (contract + validator),
`contract2_*.json` (same, plus the "do not copy the seed's sentence" prompt rule — the
code as it stands).

```bash
.venv/bin/python scripts/drift_eval.py --label <name> --count 5
```

## Conditions

Every run used the real pipeline with the real model: Qwen2.5-Coder 7B through Ollama,
the LLM seed parser on, PS8 and PS2 on, regeneration on (up to 2 retries), nothing
persisted. Ten seeds, one per domain, five variations each (one per strategy), so 50
candidates per run. Apple M5, 16 GB, on battery, runs back to back on 2026-10-01.

| Domain | Seed |
|---|---|
| Programming | Write a function to check whether a number is prime. |
| Algorithms | Implement binary search on a sorted array of integers. |
| Data Structures | Implement a stack that supports push, pop and retrieving the minimum element. |
| Database | Write a SQL query to find duplicate email addresses in a users table. |
| Operating Systems | Explain how round-robin CPU scheduling decides which process runs next. |
| Computer Networks | Explain how TCP congestion control uses slow start and congestion avoidance. |
| AI / ML | Explain how the k-nearest neighbours algorithm classifies a new data point. |
| Web Development | Write an HTML form that collects a user's name and email address. |
| Software Engineering | Explain the difference between unit testing and integration testing. |
| Mathematics | Find the derivative of f(x) = 3x^2 + 5x - 7. |

## Results

| Measure | Baseline | Contract | Contract + prompt rule (current) |
|---|---|---|---|
| Final questions on a different task (read by hand) | 8 of 50 | 0 of 50 | 0 of 50 |
| Final candidates passing PS8 | 33 | 32 | 38 |
| Accepted on the first attempt | 24 | 23 | 26 |
| Regeneration attempts | 46 | 49 | 41 |
| Decisions | 1 PASS, 49 REVIEW | 3 PASS, 47 REVIEW | 3 PASS, 47 REVIEW |
| Total wall time | 2,797 s | 2,182 s | 1,864 s |

Why attempts were rejected (count of rejected attempts showing each reason):

| Reason | Baseline | Contract | Current |
|---|---|---|---|
| Solution method not used / not asked for | 24 | 0 | 0 |
| Answer key is not a real answer | 11 | 0 | 0 |
| Concept not preserved / learning objective changed | 4 | 0 | 0 |
| Strategy not followed | — | 0 | 2 |
| Not a meaningful variation (paraphrase of the seed) | 20 | 49 | 39 |
| Too similar to the seed or an earlier variation | 17 | 35 | 30 |
| PS2 only | 4 | 0 | 2 |

### What the baseline got wrong

The eight final questions that were about something else, all from the baseline run:

- Database (SQL duplicates): two became "write a **Python function** to find duplicate
  elements in a list of integers".
- Web Development (HTML form): "a **recursive HTML form generator**", "a **Python
  function** that generates an HTML form", and a form question with "a function that
  uses an array" bolted on.
- Software Engineering: "regression testing and refactoring testing" instead of unit
  and integration testing.
- Mathematics: a "derivative" scenario that only asked for f(3).
- Algorithms: a search question that never required binary search.

The old PS8 recorded a concept failure on only 2 of its 50 finals. Most of these were produced
*because* the old pipeline demanded a linked-list-style solution method ("auxiliary
stack", "non-destructive rebuild", "recursive") of seeds it does not apply to, and then
rejected the answer for not using it (24 rejected attempts).

### What the new checks flagged in the current run

Three flags on final candidates. Two are right (a scenario variation that added four
words of setting to the seed's sentence). One is a false alarm: "write a SQL query to
find email addresses that **appear more than once**" was flagged because it never says
"duplicate". It went to REVIEW, not PASS and not discarded.

## Cost

| Step | Measured |
|---|---|
| Seed analysis by the model (existed before; one call per job) | 2.8–11.5 s |
| Building the Seed Contract (new, local) | 0.2–50 ms per seed; 0.1 s in total over 10 seeds |
| New concept + strategy checks (new, local) | about 12 ms per candidate |
| PS8 structural validation, all checks, 50 candidates + retries | 3.6 s before, 2.7 s after |

The contract adds no model call. Total time fell from 2,797 s to 1,864 s. Part of that
is fewer regenerations (46 → 41) and no method-driven retries; part is that a model call
took about 26 s in the baseline run and about 19 s in the last one, which this
comparison does not control for. Treat the time difference as indicative, not as a
measured speed-up of the code.

## Near-copies: the follow-up fix

Half of the rejected first attempts opened with the seed's own words and appended the
change. The prompt now tells the model how each strategy's question must open (the
setting, the concrete data, the situation behind the constraint, the material given, or
the new format), forbids the seed's opening words by quoting them, and asks for
specifics of its own and at least two sentences. The same instruction is repeated on
regeneration. No PS8 threshold was changed.

Measured on first attempts only (`--no-regen`, 50 generations, file
`opening_first_*.json`), against the first attempts of the previous run:

| First attempts | Before the fix | After |
|---|---|---|
| Fail on similarity | 22 of 50 | 11 of 50 |
| Pass PS8 | about 26 of 50 | 37 of 50 |
| By strategy: scenario / constraint / parameter / structure / representation | 2 / 6 / 5 / 4 / 5 | 2 / 2 / 4 / 2 / 1 |

The "before" pass figure is the number of candidates accepted without a retry in the
previous full run.

Full run with regeneration on the same prompt (`opening_full_*.json`, 2026-10-02):

| Full run, 50 candidates | Baseline | Before the fix | After |
|---|---|---|---|
| Final candidates passing PS8 | 33 | 38 | 44 |
| Finals failing on similarity | 10 | 10 | 6 |
| Accepted on the first attempt | 24 | 26 | 37 |
| Regeneration attempts | 46 | 41 | 21 |
| Attempts rejected as near-copy or too similar | 37 | 69 | 24 |
| Final questions on a different task | 8 | 0 | 0 |
| Decisions | 1 PASS, 49 REVIEW | 3 PASS, 47 REVIEW | 1 PASS, 49 REVIEW |
| Wall time | 2,797 s | 1,864 s | 1,442 s |

This run was on mains power and the earlier ones on battery, so the wall times are not
comparable; the regeneration count (21 against 41) is the like-for-like figure.

## What is still wrong

- **Six of 50 finals still fail on similarity.** They are no longer copies of the seed:
  each opens with its own data or situation, but scores 0.81-0.93 against the seed on
  the embedding model, above the 0.80 / 0.86 limits. They cluster on the TCP, k-nearest
  neighbours and database seeds. The PS8 similarity thresholds were not changed.
- **Almost everything still ends in REVIEW** (49 of 50 in the last run). That is PS2: the 36-entry
  reference corpus cannot ground most claims outside linked lists. PS2 was not changed.
- **A concept described but never named is sent back** (one false alarm in 50, above).
- **One run per configuration.** Sampling is not seeded in production, so counts will
  move by a few between runs.
