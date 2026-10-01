import { useEffect, useState } from 'react';
import { api } from '../api.js';
import CandidateCard from '../components/CandidateCard.jsx';
import PipelineProgress from '../components/PipelineProgress.jsx';
import { AreaSelect, DifficultySelect } from '../components/TaxonomyFilters.jsx';
import { areaLabel, useAppData } from '../state/AppData.jsx';

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

function RunSummary({ job, taxonomy }) {
  const results = job.results || [];
  const scores = results.map((r) => r.reliability_verification?.reliability_score).filter((v) => typeof v === 'number');
  const avg = job.summary ? job.summary.mean_reliability_score : (scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null);
  const done = job.status === 'completed';
  return (
    <div className="panel" data-testid="dashboard">
      <h2>
        Run summary {job.demo && <span className="demo-tag">DEMO</span>}
        <span className={`status-pill ${done ? 'ok' : ''}`}>{job.status}</span>
      </h2>
      {job.demo && <div className="demo-banner"><b>{job.demo_label}</b></div>}
      <div className="seed-line">
        <span className="k">Seed</span>{job.seed_metadata?.raw_seed || job.seed || 'Write a function to reverse a singly linked list.'}
        <span className="k"> · {areaLabel(taxonomy, job.subject_area || job.domain)}</span>
      </div>
      <div className="tiles">
        <div className="tile"><div className="k">Generated</div><div className="v">{job.generated_count}<span style={{ fontSize: 14, color: 'var(--dim)' }}> / {job.requested_count}</span></div></div>
        <div className="tile pass"><div className="k">Accepted</div><div className="v">{job.accepted_count}</div></div>
        <div className="tile review"><div className="k">Review</div><div className="v">{job.review_count}</div></div>
        <div className="tile reject"><div className="k">Rejected</div><div className="v">{job.rejected_count}</div></div>
        <div className="tile"><div className="k">Duplicate rate</div><div className="v">{job.summary ? `${(job.summary.duplicate_rate * 100).toFixed(0)}%` : '—'}</div></div>
        <div className="tile"><div className="k">Avg reliability</div><div className="v">{avg === null ? '—' : avg.toFixed(2)}</div></div>
        <div className="tile ai"><div className="k">Regenerations</div><div className="v">{job.regeneration_attempts}</div></div>
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--muted)', marginTop: 10 }}>
        {job.summary ? `${job.summary.flagged_span_count} flagged span(s) across all candidates` : 'Numbers update live as each candidate is decided.'}
        {job.demo ? ' · DEMO run — not saved to the question bank' : ''}
      </div>

      {job.seed_metadata && (
        <details>
          <summary>Seed analysis — what PS8 extracted</summary>
          <div className="table-wrap"><table><tbody>
            <tr><th>Pipeline domain</th><td>{job.seed_metadata.domain}</td></tr>
            <tr><th>Topic</th><td>{job.seed_metadata.topic}</td></tr>
            <tr><th>Core concept</th><td>{job.seed_metadata.core_concept}</td></tr>
            <tr><th>Question type</th><td>{job.seed_metadata.question_type}</td></tr>
            <tr><th>Difficulty</th><td>{job.seed_metadata.difficulty} ({job.seed_metadata.difficulty_score})</td></tr>
            <tr><th>Learning objective</th><td>{job.seed_metadata.learning_objective}</td></tr>
          </tbody></table></div>
        </details>
      )}
      {Object.keys(job.timings_ms || {}).length > 0 && (
        <details>
          <summary>Measured stage timings</summary>
          <div className="table-wrap"><table><tbody>
            {Object.entries(job.timings_ms).map(([k, v]) => (
              <tr key={k}><th>{k}</th><td className="mono">{Math.round(v)} ms</td></tr>
            ))}
          </tbody></table></div>
        </details>
      )}
    </div>
  );
}

export default function GeneratePage({ onOpenBank }) {
  const { health, taxonomy, job, jobRunning, jobError, startJob, startDemoJob } = useAppData();
  const [seed, setSeed] = useState('Write a function to reverse a singly linked list.');
  const [area, setArea] = useState('programming');
  const [target, setTarget] = useState('');
  const [count, setCount] = useState(10);
  const [regen, setRegen] = useState(true);
  const [mode, setMode] = useState(job?.demo ? 'demo' : 'normal');
  const [examples, setExamples] = useState([]);
  const [error, setError] = useState(null);
  const elapsed = useJobElapsed(job, jobRunning);

  useEffect(() => { api.domains().then(setExamples).catch(() => {}); }, []);

  async function run() {
    setError(null);
    try {
      if (mode === 'demo') await startDemoJob();
      else await startJob({
        seed_question: seed, subject_area: area, count: Number(count),
        difficulty_shift: target || null, enable_regeneration: regen, persist: true,
      });
    } catch (e) {
      setError(e.message);
    }
  }

  const ollamaReady = health?.ollama?.reachable && health?.ollama?.model_available;
  const showJob = job && (mode === 'demo' ? job.demo : !job.demo);

  return (
    <>
      <div className="panel">
        <div className="mode-switch" role="tablist" aria-label="Run mode">
          <button className={mode === 'normal' ? 'active' : ''} disabled={jobRunning} onClick={() => setMode('normal')}>Normal</button>
          <button className={`demo ${mode === 'demo' ? 'active' : ''}`} disabled={jobRunning} onClick={() => setMode('demo')}>DEMO scenario</button>
        </div>

        {mode === 'demo' ? (
          <>
            <h2>DEMO scenario <span className="demo-tag">DEMO</span></h2>
            <div className="demo-banner" data-testid="demo-banner">
              <b>DEMO — scripted candidates, real validation.</b> Only the model call is replaced by
              two scripted candidate outputs; the first contains a deliberate factual error. Parsing,
              PS8 structural validation, PS2 verification, the decision and regeneration are the real
              pipeline, and every score shown is computed live. Demo runs are never saved and are not
              a measured benchmark result.
            </div>
            <div className="seed-line"><span className="k">Seed</span>Write a function to reverse a singly linked list. <span className="k">· Programming (general) · 1 variation</span></div>
            <button className="primary" onClick={run} disabled={jobRunning}>
              {jobRunning ? <><span className="spinner" /> Running…</> : 'Run DEMO scenario'}
            </button>
          </>
        ) : (
          <>
            <h2>New generation job</h2>
            <label htmlFor="seed">Seed question</label>
            <textarea id="seed" value={seed} onChange={(e) => setSeed(e.target.value)} />
            <div className="gen-grid">
              <AreaSelect id="gen-area" value={area} onChange={setArea} allowAll={false} />
              <DifficultySelect id="gen-target" value={target} onChange={setTarget}
                label="Target difficulty" allLabel="Match the seed (default)" />
              <div>
                <label htmlFor="count">Variations</label>
                <input id="count" type="number" min="1" max="15" value={count} onChange={(e) => setCount(e.target.value)} />
              </div>
              <div>
                <label htmlFor="regen">Regeneration</label>
                <select id="regen" value={regen ? 'on' : 'off'} onChange={(e) => setRegen(e.target.value === 'on')}>
                  <option value="on">On (retry rejects)</option>
                  <option value="off">Off</option>
                </select>
              </div>
              <button className="primary" onClick={run} disabled={jobRunning || seed.trim().length < 5 || !taxonomy}>
                {jobRunning ? <><span className="spinner" /> Running…</> : 'Generate & Verify'}
              </button>
            </div>
            {examples.length > 0 && (
              <div className="examples">
                <span>Try:</span>
                {examples.slice(0, 5).map((d) => (
                  <button key={d.id} className="chip" onClick={() => { setSeed(d.example_seed); setArea(d.id); }}>{d.label}</button>
                ))}
              </div>
            )}
            {!ollamaReady && health && (
              <div className="notice" style={{ marginTop: 14 }}>
                Ollama is not ready ({health.ollama?.detail}). Generation needs it. Start it with{' '}
                <code>ollama serve</code> and pull the model with <code>ollama pull {health.ollama?.model}</code>.
              </div>
            )}
          </>
        )}

        {jobRunning && (
          <>
            <PipelineProgress active elapsed={elapsed} job={progressView(job)} />
            <div className="job-note">
              This job runs on the server. You can switch to any other page — it keeps going, and its
              progress is shown here and on the Dashboard when you come back.
            </div>
          </>
        )}
      </div>

      {(error || jobError) && <div className="error">{error || jobError}</div>}
      {showJob && job.errors?.length > 0 && <div className="error">{job.errors.map((e, i) => <div key={i}>{e}</div>)}</div>}
      {showJob && job.warnings?.length > 0 && <div className="notice">{job.warnings.map((w, i) => <div key={i}>{w}</div>)}</div>}

      {showJob && (
        <>
          <RunSummary job={job} taxonomy={taxonomy} />
          {job.results?.length > 0 && (
            <h2 className="section-title">
              Candidates <span className="hint">each judged by PS8, then PS2, then decided</span>
            </h2>
          )}
          {(job.results || []).map((item, i) => (
            <CandidateCard key={item.candidate.id} item={item} index={i} onOpenBank={onOpenBank} demo={!!job.demo} />
          ))}
        </>
      )}
    </>
  );
}
