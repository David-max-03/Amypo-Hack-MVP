# Model benchmark — Qwen2.5-Coder 7B vs Mistral 7B

Raw data: [`benchmark_20260930T102440Z.json`](benchmark_20260930T102440Z.json)
Script: [`scripts/benchmark_models.py`](../../scripts/benchmark_models.py)

```bash
.venv/bin/python scripts/benchmark_models.py \
    --models qwen2.5-coder:7b mistral:7b --count 5 --runs 1 --concurrency 2
```

## Conditions

Both models ran the identical integrated pipeline. Only the Ollama model name changed.

| Setting | Value |
|---|---|
| Seed question | "Write a function to reverse a singly linked list." |
| Domain / subject area | programming / Data Structures |
| Candidates per run | 5 |
| Generation / regeneration temperature | 0.85 / 0.6 |
| top_p, max tokens | 0.95, 600 |
| Sampler seed | 42 (set by the benchmark only; production does not set one) |
| Max regeneration attempts | 2 |
| PS8 rules, PS2 engine, MiniLM, corpus (36 entries) | unchanged, same for both |
| Seed parsing | heuristic parser (no model call), so it does not differ by model |
| Persistence | off: nothing was written to the bank, review queue or reports |
| Hardware | Apple M5, 16 GB, on battery with Low Power Mode on |
| Ollama | 0.34.4, `OLLAMA_NUM_PARALLEL=4` |
| Date | 2026-09-30, 10:00–10:24 UTC |

Each model was loaded with one warm-up call before timing started.

## Sequential run (one pipeline, 5 candidates)

| Metric | Qwen2.5-Coder 7B | Mistral 7B |
|---|---|---|
| Total time | 245.1 s | 286.2 s |
| Average per decided candidate | 49.0 s | 57.2 s |
| Candidates per minute | 1.22 | 1.05 |
| Mean generation call | 26.9 s | 40.3 s |
| Mean regeneration call | 27.5 s | 42.1 s |
| Model calls | 9 | 7 |
| Valid output rate (decided / requested) | 5 / 5 | 5 / 5 |
| Malformed output rate | 0 / 9 | 0 / 7 |
| PS8 pass rate (final attempt) | 5 / 5 | 4 / 5 |
| Regeneration rate (candidates regenerated) | 3 / 5 | 1 / 5 |
| Decisions | 1 PASS, 4 REVIEW | 2 PASS, 3 REVIEW |
| PS2 verdicts | 1 trustworthy, 4 unverifiable | 2 trustworthy, 1 partially reliable, 2 unverifiable |
| PS2 reliability, mean (min–max) | 0.645 (0.442–0.911) | 0.773 (0.661–0.961) |

Where the time went (sum over the run):

| Stage | Qwen2.5-Coder 7B | Mistral 7B |
|---|---|---|
| LLM generation | 134.7 s | 201.6 s |
| Regeneration | 110.0 s | 84.2 s |
| PS8 structural validation | 0.18 s | 0.22 s |
| PS2 verification | 0.14 s | 0.16 s |
| Seed parsing | under 1 ms | under 1 ms |

## Concurrent run (two identical pipelines in parallel, 10 candidates)

| Metric | Qwen2.5-Coder 7B | Mistral 7B |
|---|---|---|
| Wall time | 411.9 s | 480.4 s |
| Candidates per minute | 1.46 | 1.25 |
| Model calls, mean call time | 19, 40.9 s | 18, 53.1 s |
| Decisions | 3 PASS, 7 REVIEW | 0 PASS, 10 REVIEW |
| PS2 verdicts | 4 trustworthy, 6 unverifiable | 4 partially reliable, 6 unverifiable |
| PS8 passed (final attempt) | 9 / 10 | 6 / 10 |

## What the numbers support

- **The model call is the whole cost.** PS8 and PS2 together took under half a second
  per run for either model, against 245–286 s total. Switching model, or reducing
  regenerations, is the only thing that changes speed. Optimising PS8 or PS2 would not.
- **Qwen was faster per call** in both runs: about 27 s against 40 s sequentially.
  Qwen's total lead was smaller (14%) because it regenerated more candidates (3 of 5
  against 1 of 5).
- **Running two pipelines at once raised throughput only slightly** (Qwen 1.22 → 1.46
  per minute, Mistral 1.05 → 1.25). Each call got slower under load.
- **Quality is mixed and the sample is too small to rank the models.** Mistral scored
  higher on PS2 in the sequential run (mean 0.773 against 0.645, 2 PASS against 1). In
  the concurrent run the result reversed: Qwen had 3 PASS and Mistral none, and Mistral
  failed PS8 on 4 of 10 against Qwen's 1 of 10.
- **Neither model produced malformed output** in the 16 sequential calls. The 37
  concurrent calls were not checked one by one, but all 20 concurrent candidates were
  decided.

## Recommendation

Keep Qwen2.5-Coder 7B as the default. It was faster in both runs and failed PS8 less
often, and nothing here shows Mistral to be reliably better on PS2.

This is not a strong result. It rests on one seed question, one domain, and 15
candidates per model, measured on battery in Low Power Mode. The two runs disagree on
quality, so the PS2 differences are within run-to-run variation. A decision to switch
would need several seeds across domains and at least a few dozen candidates per model.
The script's `--runs`, `--count` and `--seed` options cover that.

## Not measured

- Other seeds, domains or difficulty targets.
- Mains power or Low Power Mode off; absolute times will differ.
- Human judgement of question quality. PS2 reliability is the pipeline's own score.
- The LLM seed parser, which was switched off so both models got the same parsed seed.
