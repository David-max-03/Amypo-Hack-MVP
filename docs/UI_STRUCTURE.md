# Frontend UI Structure

Code Titans — Question Trust Pipeline · React + Vite

This describes `frontend/src` after the UI/UX + pipeline improvement phase. The main
changes from before: the backend now owns generation jobs, there is a sidebar with six
sections, the PS2 Verifier inspects results that were already verified, and one shared
domain/difficulty configuration is used everywhere.

---

## 1. File layout

```
frontend/src/
├── main.jsx                     entry point, mounts <App/>
├── App.jsx                      AppDataProvider + Shell (sidebar nav, topbar, page switch)
├── api.js                       thin fetch client, one function per endpoint
├── styles.css                   design tokens + all component styles
├── state/
│   └── AppData.jsx              shared app state: taxonomy, health, the active job (polled)
│                                 helpers: areaOf, difficultyOf, matchesFilters, areaLabel
├── pages/
│   ├── Dashboard.jsx            7-step pipeline, active job, system stats, decision tally, recent jobs
│   ├── Generate.jsx             Normal / Demo job form, live progress, run summary, candidate cards
│   ├── Verifier.jsx             PS2 inspector over verified results + collapsible custom /verify
│   ├── Bank.jsx                 accepted questions, shared filters + strategy/method/search, export
│   ├── Review.jsx               review queue, shared filters, approve / reject
│   └── Reports.jsx              every stored decision, shared filters + decision filter
└── components/
    ├── TaxonomyFilters.jsx      AreaSelect, DifficultySelect, TaxonomyFilters (the only filter UI)
    ├── HealthBar.jsx            topbar status pills
    ├── PipelineProgress.jsx     live stage / progress bar for a job
    ├── CandidateCard.jsx        one variation's full report (+ AttemptTimeline, EvidenceTable, …)
    ├── StageTrace.jsx           per-attempt Generate → PS8 → PS2 → decision timeline
    ├── ValidationReport.jsx     PS8 + PS2 check grids + decision
    ├── FlaggedSpans.jsx         PS2 flagged spans with reasons
    ├── HighlightedText.jsx      question text with flagged spans marked in place
    └── ScoreBar.jsx             labelled 0–1 bar
```

There is still no router. `Shell` switches pages with `useState`. Unlike the old tabs,
the job lives in `AppDataProvider` above every page, so switching pages never unmounts it.

---

## 2. Navigation

| Section | Page | Purpose |
|---|---|---|
| Dashboard | `DashboardPage` | Shows the pipeline (GENERATE → PS8 → PS2 → DECISION → REGENERATE → REVALIDATE → PASS), the running or last job, storage counts, a decision tally and recent jobs |
| Generate & Verify | `GeneratePage` | Starts a Normal job (area, target difficulty, count, regeneration) or the Demo job, then shows live progress and candidate cards |
| PS2 Verifier | `VerifierPage` | Lets you inspect the PS2 result of every candidate already verified: score, verdict, flagged spans, claims, evidence and contradictions. Checking arbitrary text sits in a collapsible panel |
| Question Bank | `BankPage` | Accepted questions |
| Review Queue | `ReviewPage` | Human decisions on REVIEW items |
| Reports | `ReportsPage` | Every PASS/REVIEW/REJECT with its full report |

The sidebar shows live counts for the Bank and Review sections, a pulsing dot on
"Generate & Verify" while a job runs, and a job chip ("Job running · 2/5") that returns
you to the Generate page.

---

## 3. Background jobs

```
GeneratePage ── startJob(payload) ──► POST /api/v1/jobs  (202, returns job_id)
                                     │  backend thread runs run_pipeline(...)
AppDataProvider                      │  PS8 → PS2 → decision → regeneration per candidate
  localStorage amypo.activeJobId     ▼
  poll every 1.5 s ─────────────► GET /api/v1/jobs/{job_id}
  until status ∈ {completed, failed}   status, current_stage, counts, results[], errors, timings
```

- A page change, or a full reload, does not stop or lose the job. On load the provider
  reads the stored job id and resumes polling. A 404 (for example after a backend
  restart) clears the stored id.
- `results[]` grows as each candidate is decided, so cards appear live.
- Jobs are held in memory (the last 50). Candidates are still persisted to the
  bank/review/report files as before, so a backend restart loses only the job record.

---

## 4. Shared domain & difficulty configuration

There is one source: `backend/app/taxonomy.py`, served at `GET /api/v1/taxonomy`.

- **14 CS subject areas:** Algorithms, Data Structures, Web Development, Database,
  Operating Systems, Computer Networks, Computer Architecture, OOP, Software Engineering,
  AI / Machine Learning, Cloud Computing, Cybersecurity, Programming Languages and
  System Design. There is also "Programming (general)" and a group of other domains.
- **Difficulties:** Easy, Medium, Hard and Expert.
- Every CS area maps to the pipeline domain `programming`, so PS8/PS2 behave exactly as
  before. The chosen area is stored on each record as `subject_area`.
- The frontend fetches it once, in `AppDataProvider`. `TaxonomyFilters` is the only
  filter component, and Generate, the Verifier, Bank, Review and Reports all use it
  together with `matchesFilters`.
- Records created before this phase have no `subject_area`. They match only when the
  filter is set to "All".

---

## 5. Data flow — page → endpoint

| Page | Reads | Writes |
|---|---|---|
| (shell) | `GET /health` every 15 s, `GET /taxonomy`, `GET /jobs/{id}` every 1.5 s while running | — |
| Dashboard | `GET /validation-reports`, `GET /jobs` | — |
| Generate & Verify | `GET /domains` (example seeds) | `POST /jobs`, `POST /jobs/demo` (the demo is never persisted) |
| PS2 Verifier | active job results, `GET /validation-reports`, `GET /demo/problematic-responses` | `POST /verify` (custom text only) |
| Question Bank | `GET /questions` | `GET /export?fmt=json\|csv` |
| Review Queue | `GET /review-queue` | `POST /review-queue/{id}/approve\|reject` |
| Reports | `GET /validation-reports` | — |

The old synchronous endpoints, `POST /generate-and-verify`, `POST /demo/run` and
`GET /progress/{job_id}`, are unchanged and still covered by the tests. The UI no longer
calls them.

---

## 6. Status language

| State | Token | Meaning |
|---|---|---|
| `PASS` ✓ | `--pass` | passed both gates |
| `REVIEW` ! | `--review` | unresolved, routed to a human |
| `REJECT` ✕ | `--reject` | failed a gate |
| AI processing | `--ai` | generation or regeneration in progress |
| PS8 / PS2 accents | `--ps8` / `--ps2` | structural checks / trust checks |

A badge always carries a text label, never colour alone. The design tokens live once in
`:root` in `styles.css`.
