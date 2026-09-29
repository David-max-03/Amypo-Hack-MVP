# Model / Technique Card — Code Titans PS8 + PS2 Pipeline

HackWithAMYPO 2026 · Stage 2 · Team Code Titans

## 1. Approach

The system is a two-gate pipeline. Nothing is trained or fine-tuned: the behaviour comes from
two off-the-shelf local models, controlled prompting, and transparent, rule-based validation.
Every rule and threshold is inspectable in `backend/app/config.py`.

| Stage | Technique |
|---|---|
| Seed parsing | Heuristic extraction (domain keywords, difficulty cues), optionally refined per field by the LLM |
| Variation planning | Round-robin over 5 framing strategies × 4 solution methods (coding). Coprime cycles, so all 20 pairs appear before any pair repeats |
| Generation | Qwen2.5-Coder 7B via Ollama, JSON mode, temperature 0.85. Parallel waves, each told what earlier waves produced |
| Structural validation (PS8) | Concept (keyword overlap OR MiniLM similarity, plus a data-structure anchor), difficulty (±0.20), duplicates (Jaccard + MiniLM vs seed, run and bank), paraphrase ceiling (0.80, or 0.86 for a verified method change), answer key (must be code for coding questions), method (verified in the answer-key code) |
| Reliability verification (PS2) | Claim segmentation and typing; grounding by MiniLM similarity **and** keyword overlap against a local corpus; contradiction rules (Big-O, antonyms, prefix negation, numbers, polarity); fabrication markers (invented citations, over-precise statistics, absolutes); weighted reliability score → 5 verdicts + flagged spans |
| Decision | PASS only if both gates pass. Unverifiable → REVIEW. Failures are regenerated with their exact reasons, ≤ 2 retries |

## 2. Models

| Model | Role | Details |
|---|---|---|
| **Qwen2.5-Coder 7B Instruct** (`qwen2.5-coder:7b`) | Question + answer-key generation; optional seed-field refinement | Via Ollama; Q4_K_M quantisation, 4.7 GB, 7.6 B parameters, 4096-token context. Open weights; no paid API |
| **all-MiniLM-L6-v2** (sentence-transformers) | Embeddings for similarity, duplicate detection and PS2 grounding | 22 M parameters, 384-dim vectors, CPU. Weights cached locally (baked into the Docker image) |

A deterministic lexical vectoriser is the fallback if MiniLM cannot load, and
`/api/v1/health` reports which backend is actually active.

## 3. Configuration data (no training data)

- **Prompts:** `backend/app/ps8/prompt_builder.py`. These are the system prompt, the
  per-strategy and per-method instructions, and a regeneration prompt that quotes the exact
  rejection reasons.
- **Strategies and methods:** `ps8/strategies.py`, `ps8/methods.py`. Each method has
  code-evidence checks, for example "recursive" requires a function that calls itself within
  its own body, with test code excluded.
- **Domains:** 7 (programming, mathematics, science, business, language, health, general
  knowledge), defined in `ps8/domains.py`.
- **Reference corpus:** `data/reference_corpus.json`, **36 hand-written entries** (15
  programming, 6 mathematics, 5 science, 3 health, 3 business, 2 language, 2 general
  knowledge). This is our own corpus, **not** the organiser-provided verified datasets, which
  have not been integrated yet.
- **Thresholds:** `backend/app/config.py`. They were tuned against real Qwen outputs from the
  runs below, and each has a comment explaining its value.

## 4. Evaluation — what has actually been measured

Hardware: Apple M5, 16 GB unified memory, on AC power, macOS Low Power Mode off, Ollama 0.34.4
with `OLLAMA_NUM_PARALLEL=4`. Seed: *"Write a function to reverse a singly linked list."*

| Measurement | Result |
|---|---|
| `/generate` count=15 | **14 / 15 accepted**, duplicate rate 0.0, **370 s**. First-attempt generation 168 s (~11 s/variation), retries 195 s (11 retries, 5 recovered) |
| `/generate` count=60 | <!-- 60RUN --> |
| Methods in accepted set (count=15) | iterative 4, recursive 3, auxiliary stack 4, non-destructive rebuild 3. Each is verified in the answer-key code |
| Throughput, single request | 11.7 tok/s in Low Power Mode; ~2× faster on AC power |
| Throughput, 4 parallel slots | 20.3 tok/s total, versus 11.7 tok/s for a single request (both in Low Power Mode) |
| `/verify` latency | 6–214 ms with a warm model (PS2 limit: < 10 s) |
| `/verify` on a hallucinated linked-list response | 6 flagged spans, verdict `misleading` |
| Unit and integration tests | 173 passing |

**Not yet measured:** PS2 precision, recall and false-positive rate on a labelled benchmark;
answer-key correctness through execution; the organiser evaluation harness, which has not been
received. No accuracy figure is claimed for these.

## 5. Known limitations

- **Generation speed** is bounded by a 7B model on a laptop. 60 variations in under 5 minutes
  (the PS8 Stage 3 target) is not met on this hardware.
- **Answer keys are checked for form, not executed.** They must be real code and must use the
  planned method, but they are not run against their test cases. A syntactically plausible
  but wrong solution can pass.
- **Solution-method variation exists for coding questions only.**
- **The corpus is thin outside programming**, so correct claims in other domains often come back
  `unverifiable` and go to REVIEW (by design: a gap in the corpus is not evidence that a claim
  is false).
- **Hallucination detection is heuristic** and can be fooled by fluent fabrications that avoid
  the rule patterns.
- **Difficulty** comes from text cues rather than human-calibrated ratings. In practice, nearly
  all variations of one seed score the same value.
- **The 7B model is weak at some instructions.** Before the prompt showed the exact
  construction pattern, it wrote in-place code for every "non-destructive rebuild" request.
  The method validator catches such failures, and the variation is then regenerated.

## 6. Resource footprint

| Resource | Usage |
|---|---|
| Disk | Qwen 7B Q4_K_M 4.7 GB · MiniLM ~90 MB · Python env (CPU PyTorch) ~1–2 GB |
| Memory | Qwen weights 4.7 GB plus the KV cache for 4 slots (Ollama process ≈ 29% of 16 GB observed) · backend with MiniLM loaded, a few hundred MB |
| Compute | Apple GPU via Metal for Qwen; CPU for MiniLM. No discrete GPU required |
| Network | None at runtime once the models are pulled |
| Cost | Zero. No paid API calls anywhere |
