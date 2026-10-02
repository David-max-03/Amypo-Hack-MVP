# Why everything ended in REVIEW, and what changed

Raw data in this folder: `opening_full_*.json` and `heldout_before_*.json` (before),
`ps2fix_main_*.json` and `ps2fix_heldout_*.json` (after). Script:
[`scripts/drift_eval.py`](../../scripts/drift_eval.py) (`--set main` / `--set heldout`).

## The cause

PS2 treated nearly every sentence of a generated question as a factual claim and
required the reference corpus to ground it. In 50 candidates it extracted 174
"factual claims"; almost none were facts:

| What PS2 called a factual claim | What it is |
|---|---|
| "Check if the number 37 is prime." | an instruction |
| "Each member has an email address." | a premise the problem sets up |
| "is_prime(2) should return True" | a specification |
| "This query groups the members by email." | a description of the candidate's own solution |
| "Finally, P3 runs from time 6 to time 10." | working on the problem's own values |

Each was marked "could not be grounded", which forces the verdict `unverifiable` and
the decision REVIEW. The few genuine facts also failed, because the 36-entry corpus was
almost entirely about linked lists.

## What changed

1. **Claim classification for generated candidates** (`ps2/response_analyzer.py`).
   Sentences of the question are classified as instruction, premise/example, or general
   statement; only general statements (a complexity, a definition, a law) are checked
   as facts. In the answer key, descriptions of the candidate's own solution and
   working on the problem's own values are set aside; everything else is still checked.
   HTML and SQL in an answer are recognised as code. Free text sent to `/verify` is
   classified exactly as before.
2. **Corpus** (`data/reference_corpus.json`): 36 → 150 entries, covering the
   fundamentals of each supported CS area and basic mathematics.
3. **Support by entailment** (`core/entailment.py`, `ps2/source_verification.py`).
   With a larger corpus the old support test (topical similarity + shared words) marked
   wrong statements as supported. A local entailment model
   (`cross-encoder/nli-MiniLM2-L6-H768`, CPU, baked into the image) now decides whether
   a corpus sentence about the same subject entails the claim or contradicts it.
4. **Contradiction rules**: instructions and premises assert nothing, so only the
   complexity rule applies to them; word-level negation/antonym conflicts must be
   confirmed by the entailment model; average-case and worst-case complexities are no
   longer treated as conflicting.
5. **Two checks added after reading the first PASS list**: PS8 rejects an answer key that
   is the prompt's placeholder text; PS2 rejects an answer that calls a result wrong and
   then gives the same result as the correction.

## Results on real generations

Qwen2.5-Coder 7B, 10 seeds × 5 variations, regeneration on, nothing persisted.

| | Main seeds, before | Main seeds, after | Held-out seeds, before | Held-out seeds, after |
|---|---|---|---|---|
| PASS | 1 | 22 | 5 | 19 |
| REVIEW | 49 | 28 | 45 | 31 |
| Final candidates passing PS8 | 44 | 47 | 42 | 40 |
| Regeneration attempts | 21 | 18 | 30 | 30 |

The main-seed "after" run finished before change 5. Re-checked with the final code, 3
of its 22 PASSes are withdrawn (two placeholder answers, one self-contradicting
answer), leaving 19. The held-out "after" run used the final code.

PASS by seed (out of 5):

| Kind of seed | Main | Held-out |
|---|---|---|
| Code: function / algorithm | prime 4, binary search 4 | factorial 4, merge sort 5 |
| Code: data structure | min stack 2 | queue from two stacks 2 |
| SQL | 3 | 1 |
| HTML / CSS | 3 | 3 |
| Mathematics | 3 | 4 |
| Operating systems (explain) | 0 | 0 |
| Networks (explain) | 0 | 0 |
| AI / ML (explain) | 1 | 0 |
| Software engineering (explain) | 2 (both withdrawn by change 5) | 0 |

**Explanation-type questions still end in REVIEW.** Their answer keys are paragraphs of
factual prose; a paragraph passes only if every checkable sentence in it is entailed by
a corpus sentence, and real answers are wordier than the corpus. That is REVIEW for the
right reason: nothing confirmed them.

## Does PS2 still catch wrong content?

A labelled set of 22 correct statements and the same 22 made wrong, on topics the
corpus covers (`backend/tests/test_ps2_entailment.py`):

| Corpus and support rule | Wrong statements passed | Right statements passed | Right statements wrongly rejected |
|---|---|---|---|
| 36 entries, similarity + keywords (before) | 0 of 22 (all sent to review) | 0 of 22 (all sent to review) | 0 |
| 150 entries, similarity + keywords | 9 of 22 | 18 of 22 | 3 |
| 150 entries, entailment (shipped) | 1 of 22 | 18 of 22 | 1 |

With the shipped rule 17 wrong statements are rejected, 4 go to review and 1 passes
("Classification predicts a continuous value and regression predicts a discrete class
label": the small model does not see attributes swapped between two concepts).

On the 100 real candidates of the "before" runs the first version of the entailment rule
raised 7 contradictions, and all 7 were false alarms (a correct statement about unit
testing "contradicted" by the neighbouring sentence about integration testing). The
rule was tightened; the final version raised none on those candidates, and in the two
"after" runs PS2 alone rejected 2 attempts out of about 150.

## Cost

| | Before | After |
|---|---|---|
| PS2 time per candidate (mean, measured under load) | about 290 ms | about 440 ms |
| PS2 time over a 50-candidate run with retries | 2.1–4.0 s | 9.6–16.6 s |
| Backend image | 2.07 GB (as documented earlier) | 2.72 GB |

Generation still dominates: a 50-candidate run takes 25–35 minutes.

## What PASS means now, and what it does not

PASS = PS8 passed, and PS2 found no contradiction, no fabrication marker, and no
general factual statement that the corpus failed to confirm.

- **It is not a check that the answer is correct.** Code is not executed and arithmetic
  is not recomputed. Among the 19 held-out PASSes, one question is a different task
  that reuses the seed's words ("merge two sorted arrays" for a merge-sort seed) and one
  answer's code looks wrong (a recursive `enqueue` with no terminating case).
- **A question with no general factual statement passes PS2 with nothing verified.** The
  result says so ("no independently checkable factual claims were found").
- **The corpus was written alongside both seed sets.** The held-out seeds test the
  classification change cleanly, but not the corpus: its entries cover the fundamentals
  those seeds are about. A topic the corpus does not cover still goes to REVIEW.
- **The entailment model is small.** It misses attribute swaps between sibling concepts
  and can contradict a correct statement from a nearby sentence; the rule requires the
  closest sentence, high confidence and shared vocabulary before calling anything wrong.
