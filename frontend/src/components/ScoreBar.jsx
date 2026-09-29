/** A labelled 0..1 score with a colour-coded bar. */
export default function ScoreBar({ label, value, invert = false }) {
  const pct = Math.round((value ?? 0) * 100);
  // For hallucination probability, low is good - so the colour scale inverts.
  const effective = invert ? 1 - (value ?? 0) : value ?? 0;
  const tone = effective >= 0.7 ? 'good' : effective >= 0.45 ? 'mid' : 'bad';

  return (
    <div className="score">
      <div className="score-top">
        <span className="lbl">{label}</span>
        <span className="val">{(value ?? 0).toFixed(3)}</span>
      </div>
      <div className="bar">
        <i className={tone} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
