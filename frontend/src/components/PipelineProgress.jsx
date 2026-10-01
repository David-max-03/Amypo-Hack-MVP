/**
 * Live progress of a generate-and-verify run.
 *
 * Driven by GET /api/v1/progress/{job_id}, which the backend updates at every real
 * step it reports: seed parsed, variation generating / regenerating / decided.
 * Nothing here is simulated - PS8 and PS2 run inside the "decided" step, so the
 * live view does not claim a separate "validating now" state it cannot observe.
 */
export default function PipelineProgress({ active, elapsed, job }) {
  if (!active) return null;

  const total = job?.total ?? null;
  const done = job?.done ?? 0;
  const pct = total ? Math.round((done / total) * 100) : 0;

  let line = 'Starting the pipeline…';
  let reason = null;
  if (job?.stage === 'parsing_seed') {
    line = 'Analysing the seed question';
  } else if (job?.stage === 'generating') {
    line = `Generating variation ${job.variation} of ${total}` +
      (job.strategy ? ` · ${job.strategy}` : '') + (job.method ? ` · ${job.method}` : '');
  } else if (job?.stage === 'regenerating') {
    line = `Regenerating variation ${job.variation} · attempt ${job.attempt}`;
    reason = job.reason ? `Previous attempt rejected: ${job.reason}` : null;
  } else if (job?.stage === 'decided') {
    line = `Variation ${job.variation} decided — validating & verifying the next`;
  } else if (job?.stage === 'complete') {
    line = 'Finishing up';
  }

  return (
    <div className="progress-card" data-testid="progress" role="status" aria-live="polite" aria-busy="true">
      <div className="progress-head">
        <span className="progress-now"><span className="ai-dot" aria-hidden="true" />{line}</span>
        <span className="progress-count">{total ? `${done} / ${total} decided · ` : ''}{elapsed}s</span>
      </div>
      {reason && <div className="progress-reason">{reason}</div>}
      <div className="bar" style={{ marginTop: 10 }} aria-hidden="true">
        <i className="ai" style={{ width: `${Math.max(pct, total ? 2 : 0)}%` }} />
      </div>
      {job?.decisions?.length > 0 && (
        <div className="progress-decisions">
          {job.decisions.map((d) => (
            <span key={d.variation} className={`badge ${d.decision}`}>
              #{d.variation} {d.decision}{d.attempts > 1 ? ` · ${d.attempts} attempts` : ''}
            </span>
          ))}
        </div>
      )}
      <div className="progress-foot">
        A local 7B model takes roughly 20–40 s per variation on a laptop; regeneration adds more.
      </div>
    </div>
  );
}
