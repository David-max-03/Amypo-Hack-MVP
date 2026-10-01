# One-Page Summary — Code Titans

**HackWithAMYPO 2026 · Integrated track: PS8 (Question Variation Generation) + PS2 (Hallucination
Detection & Reliability Scoring) · Ashadavid S J & Dinesh A, VSB College of Engineering Technical Campus**

## Problem
Instructors need many genuinely different versions of an assessment question, so answers cannot
simply be copied between cohorts. Generating those versions with an LLM creates a second
problem: paraphrased duplicates, drifted difficulty, wrong answer keys and fabricated facts that
reach students before anyone notices.

## Solution
A local, two-gate pipeline. **PS8 generates, PS2 verifies**, and a variation is released only
if both gates pass.

1. **Plan before generating.** A seed question is parsed into its domain, concept, difficulty
   and learning objective. Each requested variation is then assigned one of 5 framing
   strategies (scenario, parameter, constraint, structure, representation) and, for coding
   questions, one of 4 solution methods (iterative, recursive, auxiliary stack,
   non-destructive rebuild). Variations therefore differ in how they are *solved*, not only
   in how they read.
2. **Generate locally.** Qwen2.5-Coder 7B runs via Ollama in JSON mode, with requests sent in
   parallel waves. No paid API is used anywhere.
3. **PS8 structural gate.** The variation must keep the seed's concept and data structure,
   match its difficulty, and be neither a duplicate nor a paraphrase. Its answer key must be
   real code, and it must *verifiably* use its planned method: a "recursive" answer has to
   call itself.
4. **PS2 trust gate.** The response is split into claims. Factual claims are grounded against a
   local corpus using MiniLM similarity and keyword overlap, and checked for contradictions
   and fabrication markers. The result is a reliability score, one of 5 verdicts, and
   flagged spans that explain *why* each was flagged.
5. **Feedback, not blind retries.** A rejected variation is regenerated with its exact rejection
   reasons in the prompt, up to twice. An unverifiable claim goes to human review, never to
   automatic rejection.

## What makes it different
- **Every label is checked.** Methods are confirmed in code, answer keys must be code, and a
  concept cannot drift to a different data structure. Several of these checks were added
  after real model outputs got past earlier versions of the validator.
- **Explainable end to end.** Every rejection and every flagged span carries a human-readable
  reason, and every threshold lives in one config file.
- **Honest about uncertainty.** A thin corpus leads to REVIEW, not a false REJECT, and no
  accuracy figure is claimed until it has been measured.

## Measured results (Apple M5 laptop, local 7B model)
- **14 of 15** variations accepted from one seed, 0% duplicates, all 4 solution methods present,
  in 370 s.
- **46 of 60** accepted in one 60-variation run (0% duplicates, all 4 methods), in 30 minutes. Most
  rejections were near-duplicates of other variations, as a single seed runs out of fresh angles.
- PS2 `/verify`: 6–214 ms per response (limit < 10 s). A hallucinated response received 6
  flagged spans and the verdict `misleading`.
- 183 automated tests, several built from real model failures.

## Limitations and next steps
- 60 variations in under 5 minutes is not reached on laptop hardware. Next: a smaller or faster
  model, or GPU hardware.
- PS2 precision and recall are not yet measured. Next: run the organiser benchmark and
  evaluation harness.
- The reference corpus has 36 entries. Next: integrate the organiser's verified datasets.
- Answer keys are checked for form, not executed. Next: sandboxed execution against the
  generated test cases.
