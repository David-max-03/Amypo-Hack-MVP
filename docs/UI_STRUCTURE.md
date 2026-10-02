# Frontend UI Structure

Code Titans — Question Trust Pipeline · React + Vite

This describes `frontend/src` after the design implementation ("Emerald Verification
Precision": Plus Jakarta Sans headings, Inter body, emerald primary). The backend owns
generation jobs, PS2 runs automatically on every candidate, and one shared
domain/difficulty configuration is used everywhere.

---

## 1. File layout

```
frontend/src/
├── main.jsx                     entry point, mounts <App/>
├── App.jsx                      ToastProvider + AppDataProvider + Shell (header, rail, drawer)
├── api.js                       thin fetch client, one function per endpoint
├── styles.css                   design tokens (:root) + all component styles
├── state/
│   └── AppData.jsx              shared app state: taxonomy, health, the active job (polled)
│                                 helpers: areaOf, difficultyOf, matchesFilters, areaLabel
├── pages/
│   ├── Generate.jsx             seed form, Normal / Demo, live progress, run summary, candidate cards
│   ├── Bank.jsx                 Question Bank table: search, 6 filters, expandable rows, paging, export
│   ├── Reports.jsx              backend statistics, run / time / decision / search filters, report cards
│   ├── Verifier.jsx             PS2 inspector over verified results + collapsible custom /verify
│   └── Review.jsx               review queue: approve / reject
├── components/
│   ├── TaxonomyFilters.jsx      AreaSelect, DifficultySelect, TaxonomyFilters (the only filter UI)
│   ├── CandidateCard.jsx        evaluation card (+ DecisionBadge, AttemptTimeline, EvidenceTable, …)
│   ├── ValidationReport.jsx     gateChecks() (the 6 PS8 + 6 PS2 checks), GateGrid, full report
│   ├── PageHeader.jsx           PageHeader, Skeleton, StateBlock (empty / error states)
│   ├── Toast.jsx                ToastProvider, useToast
│   ├── Icon.jsx                 inline SVG icon set
│   ├── HealthBar.jsx            header status pills
│   ├── PipelineProgress.jsx     live stage / progress bar for a job
│   ├── StageTrace.jsx           per-attempt Generate → PS8 → PS2 → decision timeline
│   ├── FlaggedSpans.jsx, HighlightedText.jsx, ScoreBar.jsx
└── test/                        vitest + Testing Library: app.test.jsx, fixtures.js, setup.js
```

There is no router. `Shell` switches pages with `useState`. The job lives in
`AppDataProvider` above every page, so switching pages never unmounts it.

---

## 2. Shell and navigation

- **Header:** menu button, Amypo logo, the job indicator ("Generation running · 5/10",
  shown on every page while a job runs; clicking it opens Generate), and the status
  pills (backend, Ollama + model, MiniLM, corpus count, bank count).
- **Rail:** collapsed to icons by default. It expands on hover or keyboard focus, and
  the menu button pins it open. Under 860px it becomes a drawer with a scrim; Escape or
  a click on the scrim closes it.

| Section | Page | Purpose |
|---|---|---|
| Generate | `GeneratePage` | Seed, quick presets, domain, target difficulty, count and regeneration toggle. Starts a Normal job or the Demo job, then shows live progress and candidate cards |
| Question Bank | `BankPage` | Accepted questions: search plus domain, difficulty, strategy, method, validation status and decision filters |
| Reports | `ReportsPage` | PASS / REVIEW / REJECT statistics from the backend, and every stored decision as a report card |
| PS2 Verifier | `VerifierPage` | Inspection of results PS2 already produced: score, verdict, flagged spans, claims, evidence, signals, job id, candidate id, timestamp |
| Review Queue | `ReviewPage` | Human decisions on REVIEW items |

The first three are the screens in the design. PS2 Verifier and Review Queue sit below
a divider in the rail, restyled with the same design system.

---

## Responsive layout

`.shell` is a grid: a rail column (`--rail-w`, 64px, or 0 on phones) and a
`minmax(0, 1fr)` content column. Nothing at application level has a `max-width`; only
running text is capped (about 110 characters) for readability.

| Width | Behaviour |
|---|---|
| 1800px and up | Candidate and report cards flow into 2–3 columns (`auto-fit`, 760px minimum) |
| 1101–1799px | Full desktop layout, one card column, status pills in the header |
| 901–1100px | Header status collapses into one menu; form and summary grids go 2- and 3-up; the bank table drops columns |
| 768–900px | As above, and Question Bank rows become cards |
| under 768px | Rail becomes a drawer; grids stack; 44px touch targets; 16px inputs |
| under 480px | Logo text and the long job label are hidden; filters go single-column |

Tested at 320, 375, 390, 768, 1024, 1280, 1440, 1920 and 2560px wide.

---

## 3. Background jobs

```
GeneratePage ── startJob(payload) ──► POST /api/v1/jobs  (202, returns job_id)
                                     │  backend thread runs run_pipeline(...)
AppDataProvider                      │  PS8 → PS2 → decision → regeneration per candidate
  localStorage amypo.activeJobId     ▼
  poll every 1.5 s ─────────────► GET /api/v1/jobs/{job_id}
  until status ∈ {completed, failed,   status, current_stage, counts, results[], errors,
               cancelled}             timings, metrics
```

- A page change, or a full reload, does not stop or lose the job. On load the provider
  reads the stored job id and resumes polling. A 404 (for example after a backend
  restart) clears the stored id.
- `results[]` grows as each candidate is decided, so cards appear live.
- A job can be cancelled. It stops before its next candidate; candidates already
  decided are kept.
- When a job ends, a toast announces the result on whichever page is open.
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
| Generate | `GET /domains` (quick presets) | `POST /jobs`, `POST /jobs/demo` (the demo is never persisted), `POST /jobs/{id}/cancel` |
| PS2 Verifier | active job results, `GET /validation-reports`, `GET /demo/problematic-responses` | `POST /verify` (custom text only) |
| Question Bank | `GET /questions` | `GET /export?fmt=json\|csv` |
| Review Queue | `GET /review-queue` | `POST /review-queue/{id}/approve\|reject` |
| Reports | `GET /validation-reports/stats` and `GET /validation-reports`, both with `job_id` / `since_hours` | — |

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
| PS8 / PS2 accents | `--ps8` / `--ps2` | structural checks / trust checks |

A badge always carries a text label, never colour alone. The design tokens live once in
`:root` in `styles.css`.
