import { useEffect, useMemo, useState } from 'react';
import { api } from '../api.js';
import CandidateCard from '../components/CandidateCard.jsx';
import Icon from '../components/Icon.jsx';
import PageHeader, { Skeleton, StateBlock } from '../components/PageHeader.jsx';
import PipelineProgress from '../components/PipelineProgress.jsx';
import { AreaSelect, DifficultySelect } from '../components/TaxonomyFilters.jsx';
import { useToast } from '../components/Toast.jsx';
import { areaLabel, useAppData } from '../state/AppData.jsx';

const MAX_COUNT = 15;

/** Seconds since the job started, measured client-side between backend updates. */
export function useJobElapsed(job, running) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!running) return undefined;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [running]);
  if (!job?.started_at) return 0;
  const start = Date.parse(job.started_at);
  const end = job.completed_at ? Date.parse(job.completed_at) : now;
  return Math.max(0, Math.round((end - start) / 1000));
}

/** Map backend job state onto what PipelineProgress displays. */
export function progressView(job) {
  if (!job) return null;
  return {
    stage: job.current_stage,
    total: job.requested_count,
    done: job.generated_count,
    ...job.current,
    decisions: (job.results || []).map((r, i) => ({ variation: i + 1, decision: r.decision, attempts: r.attempts })),
  };
}

const ms = (v) => (typeof v !== 'number' ? '—' : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`);
const pct = (v) => (typeof v === 'number' ? `${Math.round(v * 100)}%` : '—');

function RunSummary({ job, taxonomy }) {
  const results = job.results || [];
  const scores = results.map((r) => r.reliability_verification?.reliability_score).filter((v) => typeof v === 'number');
  const avg = job.summary ? job.summary.mean_reliability_score : (scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null);
  const m = job.metrics;
  return (
    <section className="panel run-summary" data-testid="run-summary">
      <div className="panel-head">
        <h2><Icon name="layers" />Run summary {job.demo && <span className="demo-tag">DEMO</span>}</h2>
        <span className={`status-pill ${job.status}`}>{job.status}</span>
      </div>
      <p className="seed-line">
        <span className="k">Seed</span>{job.seed_metadata?.raw_seed || job.seed || 'Write a function to reverse a singly linked list.'}
        <span className="k sep">{areaLabel(taxonomy, job.subject_area || job.domain)}</span>
        <span className="k mono">{job.job_id}</span>
      </p>
      <div className="stat-row">
        <div className="stat"><span className="k">Generated</span><span className="v">{job.generated_count}<small> / {job.requested_count}</small></span></div>
        <div className="stat PASS"><span className="k">Pass</span><span className="v">{job.accepted_count}</span></div>
        <div className="stat REVIEW"><span className="k">Review</span><span className="v">{job.review_count}</span></div>
        <div className="stat REJECT"><span className="k">Reject</span><span className="v">{job.rejected_count}</span></div>
        <div className="stat"><span className="k">Avg reliability</span><span className="v">{avg === null ? '—' : avg.toFixed(2)}</span></div>
        <div className="stat"><span className="k">Regenerations</span><span className="v">{job.regeneration_attempts}</span></div>
      </div>

      {/* A demo replays scripted model output, so its timings are not a performance measurement. */}
      {m && !job.demo && (
        <details className="fold" data-testid="job-metrics">
          <summary><Icon name="chevron-right" size={16} className="caret" />Measured performance<span className="fold-meta">{ms(m.total_ms)} total · {m.candidates_per_min ?? '—'} candidates/min</span></summary>
          <div className="fold-body">
            <div className="kv-grid">
              <div><span>LLM generation</span><b>{ms(m.llm_generation_ms)}</b></div>
              <div><span>Regeneration</span><b>{ms(m.regeneration_ms)}</b></div>
              <div><span>PS8 validation</span><b>{ms(m.ps8_validation_ms)}</b></div>
              <div><span>PS2 verification</span><b>{ms(m.ps2_verification_ms)}</b></div>
              <div><span>Total job time</span><b>{ms(m.total_ms)}</b></div>
              <div><span>Average per candidate</span><b>{ms(m.avg_candidate_ms)}</b></div>
              <div><span>PS8 pass rate</span><b>{pct(m.ps8_pass_rate)}</b></div>
              <div><span>Pass / review / reject</span><b>{pct(m.pass_rate)} / {pct(m.review_rate)} / {pct(m.reject_rate)}</b></div>
              <div><span>Regeneration rate</span><b>{pct(m.regeneration_rate)}</b></div>
            </div>
            <p className="hint">Wall-clock times recorded by the backend for this job.</p>
          </div>
        </details>
      )}
      {job.seed_metadata && (
        <details className="fold">
          <summary><Icon name="chevron-right" size={16} className="caret" />Seed analysis — what PS8 extracted</summary>
          <div className="fold-body">
            <div className="kv-grid">
              <div><span>Pipeline domain</span><b>{job.seed_metadata.domain}</b></div>
              <div><span>Topic</span><b>{job.seed_metadata.topic}</b></div>
              <div><span>Core concept</span><b>{job.seed_metadata.core_concept}</b></div>
              <div><span>Question type</span><b>{job.seed_metadata.question_type}</b></div>
              <div><span>Difficulty</span><b>{job.seed_metadata.difficulty} ({job.seed_metadata.difficulty_score})</b></div>
              <div className="wide"><span>Learning objective</span><b>{job.seed_metadata.learning_objective}</b></div>
            </div>
          </div>
        </details>
      )}
    </section>
  );
}

const DECISION_RANK = { PASS: 0, REVIEW: 1, REJECT: 2 };

export default function GeneratePage({ onOpenBank, onOpenReview }) {
  const { health, taxonomy, job, jobRunning, jobError, startJob, startDemoJob, cancelJob } = useAppData();
  const toast = useToast();
  // The form reopens on the active job's settings, so coming back to this page
  // shows what is actually running rather than the defaults.
  const mine = job && !job.demo ? job : null;
  const [seed, setSeed] = useState(mine?.seed || 'Write a function to reverse a singly linked list.');
  const [area, setArea] = useState(mine?.subject_area || 'data_structures');
  const [target, setTarget] = useState(mine?.difficulty_shift || '');
  const [count, setCount] = useState(mine?.requested_count || 10);
  const [regen, setRegen] = useState(true);
  const [mode, setMode] = useState(job?.demo ? 'demo' : 'normal');
  const [presets, setPresets] = useState([]);
  const [error, setError] = useState(null);
  const [starting, setStarting] = useState(false);
  const [sort, setSort] = useState('order');
  const elapsed = useJobElapsed(job, jobRunning);

  useEffect(() => { api.domains().then(setPresets).catch(() => {}); }, []);
  // After a reload the job arrives a moment after this page mounts: adopt its settings once.
  const [adopted, setAdopted] = useState(mine?.job_id || null);
  useEffect(() => {
    if (!mine || adopted === mine.job_id) return;
    setAdopted(mine.job_id);
    setSeed(mine.seed || '');
    setArea(mine.subject_area || 'programming');
    setTarget(mine.difficulty_shift || '');
    setCount(mine.requested_count);
  }, [mine, adopted]);

  async function run() {
    setError(null);
    setStarting(true);
    try {
      if (mode === 'demo') await startDemoJob();
      else await startJob({
        seed_question: seed, subject_area: area, count: Number(count),
        difficulty_shift: target || null, enable_regeneration: regen, persist: true,
      });
      toast(mode === 'demo' ? 'Demo scenario started' : `Generation started — ${count} candidate${Number(count) === 1 ? '' : 's'}`, 'info', 3500);
    } catch (e) {
      setError(e.message);
      toast(`Could not start: ${e.message}`, 'error');
    } finally {
      setStarting(false);
    }
  }

  async function cancel() {
    try { await cancelJob(); toast('Cancelling — the job stops before its next candidate', 'warn', 4000); }
    catch (e) { toast(`Could not cancel: ${e.message}`, 'error'); }
  }

  const clamp = (n) => Math.max(1, Math.min(MAX_COUNT, Number.isFinite(n) ? n : 1));
  const ollamaReady = health?.ollama?.reachable && health?.ollama?.model_available;
  const showJob = job && (mode === 'demo' ? job.demo : !job.demo);
  const busy = jobRunning || starting;

  const results = useMemo(() => {
    const list = (showJob ? job.results || [] : []).map((item, i) => ({ item, i }));
    if (sort === 'reliability') {
      list.sort((a, b) => (b.item.reliability_verification?.reliability_score ?? -1) - (a.item.reliability_verification?.reliability_score ?? -1));
    } else if (sort === 'decision') {
      list.sort((a, b) => DECISION_RANK[a.item.decision] - DECISION_RANK[b.item.decision] || a.i - b.i);
    }
    return list;
  }, [showJob, job, sort]);
  const pending = showJob && jobRunning ? Math.max(0, job.requested_count - job.generated_count) : 0;

  return (
    <>
      <PageHeader eyebrow="Synthesis Pipeline" title="Generate" description="Questions are validated automatically after generation.">
        <div className="segmented" role="group" aria-label="Run mode">
          <button className={mode === 'normal' ? 'active' : ''} aria-pressed={mode === 'normal'} disabled={busy} onClick={() => setMode('normal')}>Normal</button>
          <button className={`demo ${mode === 'demo' ? 'active' : ''}`} aria-pressed={mode === 'demo'} disabled={busy} onClick={() => setMode('demo')}>Demo scenario</button>
        </div>
      </PageHeader>

      <section className="panel" aria-labelledby="spec-title">
        <div className="panel-head">
          <h2 id="spec-title"><Icon name="list" />{mode === 'demo' ? 'Demo scenario' : 'Seed Specification & Constraints'}{mode === 'demo' && <span className="demo-tag">DEMO</span>}</h2>
          <span className="hint">{mode === 'demo' ? 'Deterministic: REJECT → regeneration → PASS' : 'Provide root concept, invariants, or edge-case constraints'}</span>
        </div>

        {mode === 'demo' ? (
          <>
            <div className="demo-banner" data-testid="demo-banner">
              <b>DEMO — scripted candidates, real validation.</b> Only the model call is replaced by
              two scripted candidate outputs; the first contains a deliberate factual error. Parsing,
              PS8 structural validation, PS2 verification, the decision and regeneration are the real
              pipeline, and every score shown is computed live. Demo runs are never saved and are not
              a measured benchmark result.
            </div>
            <p className="seed-line"><span className="k">Seed</span>Write a function to reverse a singly linked list. <span className="k sep">Programming (general) · 1 candidate</span></p>
            <div className="form-actions">
              <button className="btn primary" onClick={run} disabled={busy}>
                {busy ? <><span className="spinner" />Running…</> : <><Icon name="bolt" />Run demo scenario</>}
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="field">
              <div className="field-head"><label htmlFor="seed">Seed concept / question</label><span className="hint mono">input prompt</span></div>
              <textarea id="seed" value={seed} onChange={(e) => setSeed(e.target.value)} disabled={busy}
                aria-describedby={seed.trim().length < 5 ? 'seed-help' : undefined} />
              {seed.trim().length < 5 && <p id="seed-help" className="field-error">Enter a seed question of at least 5 characters.</p>}
            </div>

            {presets.length > 0 && (
              <div className="presets">
                <span className="hint">Quick presets:</span>
                {presets.slice(0, 5).map((d) => (
                  <button key={d.id} type="button" className={`chip ${seed === d.example_seed ? 'active' : ''}`} disabled={busy}
                    title={d.example_seed} onClick={() => { setSeed(d.example_seed); setArea(d.id); }}>{d.label}</button>
                ))}
              </div>
            )}

            <div className="spec-grid">
              <AreaSelect id="gen-area" value={area} onChange={setArea} allowAll={false} label="Domain classification" disabled={busy} />
              <DifficultySelect id="gen-target" value={target} onChange={setTarget} label="Target difficulty" allLabel="Match the seed (default)" disabled={busy} />
              <div>
                <label htmlFor="count">Candidate questions (count)</label>
                <div className="stepper">
                  <button type="button" onClick={() => setCount((c) => clamp(Number(c) - 1))} disabled={busy || Number(count) <= 1} aria-label="Fewer candidates"><Icon name="minus" size={16} /></button>
                  <input id="count" type="number" inputMode="numeric" min="1" max={MAX_COUNT} value={count} disabled={busy}
                    onChange={(e) => setCount(e.target.value)} onBlur={() => setCount((c) => clamp(parseInt(c, 10)))} />
                  <button type="button" onClick={() => setCount((c) => clamp(Number(c) + 1))} disabled={busy || Number(count) >= MAX_COUNT} aria-label="More candidates"><Icon name="plus" size={16} /></button>
                </div>
              </div>
              <div>
                <span className="label" id="regen-label">Gate recovery</span>
                <label className="toggle" htmlFor="regen">
                  <span>Regenerate on failed gate</span>
                  <input id="regen" type="checkbox" role="switch" checked={regen} disabled={busy} aria-labelledby="regen-label"
                    onChange={(e) => setRegen(e.target.checked)} />
                  <span className="track" aria-hidden="true" />
                </label>
              </div>
            </div>

            <div className="form-actions">
              <button className="btn primary" onClick={run} data-testid="generate-btn"
                disabled={busy || seed.trim().length < 5 || !taxonomy}>
                {busy ? <><span className="spinner" />Running…</> : <><Icon name="bolt" />Generate &amp; Verify</>}
              </button>
              {!taxonomy && <span className="hint">Loading domains…</span>}
            </div>
            {!ollamaReady && health && (
              <div className="notice">
                Ollama is not ready ({health.ollama?.detail}). Generation needs it. Start it with{' '}
                <code>ollama serve</code> and pull the model with <code>ollama pull {health.ollama?.model}</code>.
              </div>
            )}
          </>
        )}

        {jobRunning && showJob && (
          <>
            <PipelineProgress active elapsed={elapsed} job={progressView(job)} />
            <div className="job-note">
              <span>This job runs on the server. Open any other section — it keeps going, and the header shows its progress.</span>
              {!job.demo && (
                <button className="btn ghost sm" onClick={cancel} disabled={job.cancel_requested} data-testid="cancel-btn">
                  <Icon name="stop" size={14} />{job.cancel_requested ? 'Cancelling…' : 'Cancel job'}
                </button>
              )}
            </div>
          </>
        )}
      </section>

      {(error || jobError) && <div className="error" role="alert">{error || jobError}</div>}
      {showJob && job.errors?.length > 0 && <div className="error" role="alert">{job.errors.map((e, i) => <div key={i}>{e}</div>)}</div>}
      {showJob && job.warnings?.length > 0 && <div className="notice">{job.warnings.map((w, i) => <div key={i}>{w}</div>)}</div>}

      {showJob ? (
        <>
          <RunSummary job={job} taxonomy={taxonomy} />
          <div className="results-head">
            <h2>Candidate Evaluation Results <span className="hint">({job.generated_count} candidate{job.generated_count === 1 ? '' : 's'}{jobRunning ? ` of ${job.requested_count}` : ''})</span></h2>
            <label className="sort">Sort by:
              <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort candidates">
                <option value="order">Generation order</option>
                <option value="reliability">Reliability score</option>
                <option value="decision">Decision</option>
              </select>
            </label>
          </div>
          <div className="cand-list">
            {results.map(({ item, i }) => (
              <CandidateCard key={item.candidate.id} item={item} index={i} demo={!!job.demo}
                onOpenBank={onOpenBank} onOpenReview={onOpenReview} />
            ))}
            {Array.from({ length: Math.min(pending, 2) }, (_, i) => (
              <div className="cand skeleton-card" key={`sk-${i}`} data-testid="candidate-skeleton">
                <Skeleton lines={4} />
              </div>
            ))}
          </div>
          {!jobRunning && results.length === 0 && (
            <StateBlock title="No candidate was decided">
              {job.status === 'cancelled' ? 'The job was cancelled before its first candidate finished.' : 'See the message above for what stopped the run.'}
            </StateBlock>
          )}
        </>
      ) : (
        <StateBlock title="No results yet">
          {mode === 'demo'
            ? 'Run the demo scenario to watch a candidate get rejected, regenerated and pass.'
            : 'Describe a seed question, pick a domain and difficulty, then generate. Each candidate is checked by PS8 and PS2 before it is shown here.'}
        </StateBlock>
      )}
    </>
  );
}
