/** The explainability list: what was flagged, and exactly why. */
export default function FlaggedSpans({ spans = [] }) {
  if (!spans.length) {
    return <div style={{ fontSize: 13, color: 'var(--pass)' }}>No claims were flagged.</div>;
  }

  return (
    <div>
      {spans.map((span, i) => (
        <div key={i} className={`flag ${span.severity || 'medium'}`}>
          <div className="sev">
            {span.severity || 'medium'} severity
            {span.claim_type ? ` · ${span.claim_type.replace(/_/g, ' ')}` : ''}
          </div>
          <div className="txt">"{span.text}"</div>
          <div className="why">{span.reason}</div>
          {span.best_evidence && (
            <div className="evidence">
              <span className="src">Closest evidence</span>
              {typeof span.best_similarity === 'number'
                ? ` (similarity ${span.best_similarity.toFixed(2)})`
                : ''}
              : {span.best_evidence}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
