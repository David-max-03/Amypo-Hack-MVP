import { useEffect, useState } from 'react';
import { api } from '../api.js';
import PipelineProgress from '../components/PipelineProgress.jsx';
import { areaLabel, areaOf, useAppData } from '../state/AppData.jsx';
import { progressView, useJobElapsed } from './Generate.jsx';

const FLOW = [
  ['gen', 'Generate', 'Qwen2.5-Coder 7B writes a variation'],
  ['ps8', 'PS8', 'structural checks: concept, difficulty, duplicate, answer, method'],
  ['ps2', 'PS2', 'reliability: claims, grounding, contradictions'],
  ['dec', 'Decision', 'PASS · REVIEW · REJECT'],
  ['regen', 'Regenerate', 'REJECT → new attempt from the exact reasons'],
  ['ps8', 'Revalidate', 'the new attempt goes through PS8 and PS2 again'],
  ['pass', 'PASS', 'accepted into the question bank'],
];

export default function DashboardPage({ go }) {
  const { health, job, jobRunning, taxonomy } = useAppData();
  const [reports, setReports] = useState(null);
  const [recentJobs, setRecentJobs] = useState([]);
  const elapsed = useJobElapsed(job, jobRunning);

  useEffect(() => {
    api.validationReports().then((d) => setReports(d.reports || [])).catch(() => setReports([]));
    api.jobs(5).then((d) => setRecentJobs(d.jobs || [])).catch(() => {});
  }, [job?.status]);

  const tally = (reports || []).reduce((a, r) => ({ ...a, [r.decision]: (a[r.decision] || 0) + 1 }), {});
  const recent = [...(reports || [])].reverse().slice(0, 6);

  return (
    <>
      <section className="panel" aria-label="How the pipeline works">
        <h2>The pipeline</h2>
        <ol className="flow7">
          {FLOW.map(([tone, t, d], i) => (
            <li key={i} className={`flow7-step ${tone}`}>
              <span className="n">{String(i + 1).padStart(2, '0')}</span>
              <span className="t">{t}</span>
              <span className="d">{d}</span>
            </li>
          ))}
        </ol>
      </section>

      <div className="dash-grid">
        <section className="panel" aria-label="Active job">
          <h2>Generation job</h2>
          {!job ? (
            <div className="empty">
              No job yet.
              <div style={{ marginTop: 12 }}><button className="primary" onClick={() => go('generate')}>Start a generation job</button></div>
            </div>
          ) : (
            <>
              <div className="seed-line">
                <span className="k">{job.demo ? 'DEMO' : 'Seed'}</span>{job.seed || 'Write a function to reverse a singly linked list.'}
              </div>
              <div className="flex" style={{ marginBottom: 10 }}>
                <span className={`status-pill ${job.status === 'completed' ? 'ok' : ''}`}>{job.status}</span>
                <span className="status-pill">{areaLabel(taxonomy, job.subject_area || job.domain)}</span>
                <span className="status-pill">{job.generated_count} / {job.requested_count} decided</span>
              </div>
              <div className="tiles">
                <div className="tile pass"><div className="k">Accepted</div><div className="v">{job.accepted_count}</div></div>
                <div className="tile review"><div className="k">Review</div><div className="v">{job.review_count}</div></div>
                <div className="tile reject"><div className="k">Rejected</div><div className="v">{job.rejected_count}</div></div>
                <div className="tile ai"><div className="k">Regenerations</div><div className="v">{job.regeneration_attempts}</div></div>
              </div>
              {jobRunning && <PipelineProgress active elapsed={elapsed} job={progressView(job)} />}
              <button className="ghost" style={{ marginTop: 14 }} onClick={() => go('generate')}>Open in Generate &amp; Verify →</button>
            </>
          )}
        </section>

        <section className="panel" aria-label="System status">
          <h2>System</h2>
          <div className="stat-list">
            <div><span>Backend</span><b className={health?.status === 'ok' ? 'good' : 'mid'}>{health?.status ?? '…'}</b></div>
            <div><span>Generation model</span><b>{health?.ollama?.model ?? '…'}</b></div>
            <div><span>Ollama</span><b className={health?.ollama?.reachable && health?.ollama?.model_available ? 'good' : 'bad'}>{health ? (health.ollama?.reachable ? 'reachable' : 'unreachable') : '…'}</b></div>
            <div><span>Embeddings</span><b className={health?.embeddings?.is_minilm ? 'good' : 'mid'}>{health ? (health.embeddings?.is_minilm ? 'MiniLM' : 'fallback') : '…'}</b></div>
            <div><span>Reference corpus</span><b>{health?.corpus?.entry_count ?? '…'} entries</b></div>
            <div><span>Question bank</span><b>{health?.storage?.accepted_questions ?? '…'}</b></div>
            <div><span>Review queue</span><b className={health?.storage?.review_queue ? 'mid' : ''}>{health?.storage?.review_queue ?? '…'}</b></div>
          </div>
        </section>
      </div>

      <div className="dash-grid">
        <section className="panel" aria-label="Decisions">
          <h2>Decisions on record</h2>
          <div className="summary-row">
            {['PASS', 'REVIEW', 'REJECT'].map((d) => <span key={d} className={`badge lg ${d}`}>{d} · {tally[d] || 0}</span>)}
          </div>
          {!recent.length ? <div className="empty">No decisions recorded yet.</div> : (
            <ul className="recent">
              {recent.map((r) => (
                <li key={`${r.candidate_id}-${r.created_at}`}>
                  <span className={`badge ${r.decision}`}>{r.decision}</span>
                  <span className="recent-q">{r.question}</span>
                  <span className="recent-m">{areaOf(r) ? areaLabel(taxonomy, areaOf(r)) : '—'} · PS2 {typeof r.reliability_verification?.reliability_score === 'number' ? r.reliability_verification.reliability_score.toFixed(2) : '—'}</span>
                </li>
              ))}
            </ul>
          )}
          <button className="ghost" style={{ marginTop: 12 }} onClick={() => go('reports')}>All reports →</button>
        </section>

        <section className="panel" aria-label="Recent jobs">
          <h2>Recent jobs</h2>
          {!recentJobs.length ? <div className="empty">No jobs since the backend started.</div> : (
            <ul className="recent">
              {recentJobs.map((j) => (
                <li key={j.job_id}>
                  <span className={`status-pill ${j.status === 'completed' ? 'ok' : ''}`}>{j.status}</span>
                  <span className="recent-q">{j.demo ? 'DEMO scenario' : j.seed}</span>
                  <span className="recent-m">{j.accepted_count} pass · {j.review_count} review · {j.rejected_count} reject · {Math.round(j.elapsed_s)}s</span>
                </li>
              ))}
            </ul>
          )}
          <div className="flex" style={{ marginTop: 12 }}>
            <button className="ghost" onClick={() => go('generate')}>New job</button>
            <button className="ghost" onClick={() => go('review')}>Review queue</button>
          </div>
        </section>
      </div>
    </>
  );
}
