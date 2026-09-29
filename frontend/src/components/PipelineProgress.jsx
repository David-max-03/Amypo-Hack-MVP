const STEPS = [
  'Parse seed',
  'Plan variations',
  'Generate (Qwen2.5-Coder)',
  'PS8 structural validation',
  'PS2 reliability verification',
  'Decision',
];

/**
 * Stage indicator shown while a run is in flight.
 *
 * The backend returns one response at the end rather than streaming, so this
 * advances on a timer calibrated to the observed stage order. It is presentational
 * only - it never claims a stage succeeded, and the real per-stage timings are
 * reported from the server once the run completes.
 */
export default function PipelineProgress({ active, elapsed }) {
  if (!active) return null;

  // Generation dominates the wall clock on a local 7B model.
  const step = elapsed < 2 ? 0 : elapsed < 4 ? 1 : elapsed < 9 ? 2 : elapsed < 11 ? 3 : elapsed < 13 ? 4 : 5;

  return (
    <div>
      <div className="progress">
        {STEPS.map((label, i) => (
          <span key={label} className={`step ${i === step ? 'active' : i < step ? 'done' : ''}`}>
            {i < step ? '✓ ' : ''}{label}
          </span>
        ))}
      </div>
      <div style={{ marginTop: 10, fontSize: 13, color: 'var(--muted)' }}>
        <span className="spinner" /> Running the pipeline locally — {elapsed}s elapsed.
        A local 7B model takes roughly 5–20s per variation.
      </div>
    </div>
  );
}
