/**
 * The verification timeline: the path one candidate actually took, attempt by
 * attempt - GENERATE → PS8 → PS2 → decision, then REGENERATION → … → final decision.
 *
 * Built only from what the backend returned: each rejected attempt's recorded PS8
 * result, PS2 score/verdict and reasons, then the final attempt's live result. The
 * score change shown in the header is computed from those two real scores.
 */
const fmt = (v) => (typeof v === 'number' ? v.toFixed(3) : '—');
const has = (v) => typeof v === 'number';

function Node({ label, detail, tone }) {
  return (
    <li className={`node ${tone || ''}`}>
      <span className="nl">{label}</span>
      {detail && <span className="nd">{detail}</span>}
    </li>
  );
}

function AttemptBlock({ a, first }) {
  // Tone follows the verdict PS2 returned, the same mapping the rest of the UI uses.
  const ps2Tone = !has(a.reliability) ? ''
    : a.verdict === 'trustworthy' ? 'ok'
    : a.verdict === 'misleading' || a.verdict === 'fabricated' ? 'bad' : 'warn';
  return (
    <div className="attempt" data-testid="trace-attempt">
      <div className="attempt-head">
        <span className="lbl">Attempt {a.attempt}{first ? '' : ' · regenerated'}</span>
        <span className={`badge ${a.decision}`}>{a.decision}</span>
      </div>
      <ol className="nodes">
        <Node label={first ? 'Generate' : 'Regenerate'} tone="ai"
          detail={first ? 'candidate produced by the generator' : 'new candidate written from the rejection feedback'} />
        <Node label="PS8 · structural validation"
          detail={a.structuralPassed === undefined ? 'not run'
            : a.structuralPassed ? 'passed all checks' : `failed — ${a.structuralReasons[0] || ''}`}
          tone={a.structuralPassed === undefined ? '' : a.structuralPassed ? 'ok' : 'bad'} />
        <Node label="PS2 · reliability verification"
          detail={has(a.reliability)
            ? `reliability ${fmt(a.reliability)} · ${String(a.verdict).replace(/_/g, ' ')}`
            : 'skipped — PS8 failed first'}
          tone={ps2Tone} />
        <Node label={`Decision · ${a.decision}`} tone={a.decision} />
      </ol>
    </div>
  );
}

export default function StageTrace({ item }) {
  const history = item.regeneration_history || [];
  const sv = item.structural_validation;
  const rv = item.reliability_verification;

  const attempts = history.map((h) => ({
    attempt: h.attempt,
    structuralPassed: h.structural_passed,
    structuralReasons: h.structural_reasons || [],
    reliability: h.reliability_score,
    verdict: h.verdict,
    decision: h.decision,
    reasons: [...(h.structural_reasons || []), ...(h.reliability_reasons || [])],
    spans: h.flagged_spans || [],
  }));
  attempts.push({
    attempt: item.attempts,
    structuralPassed: sv?.passed,
    structuralReasons: sv?.reasons || [],
    reliability: rv?.reliability_score,
    verdict: rv?.verdict,
    decision: item.decision,
    reasons: [],
    spans: [],
    final: true,
  });

  const firstScored = attempts.find((a) => has(a.reliability));
  const last = attempts[attempts.length - 1];
  const showDelta = attempts.length > 1 && firstScored && has(last.reliability) && firstScored !== last;
  const delta = showDelta ? last.reliability - firstScored.reliability : 0;

  return (
    <section className="trace" data-testid="stage-trace" aria-label="Verification timeline">
      <div className="trace-title">
        <h4>Verification timeline</h4>
        {showDelta && (
          <span className="delta" data-testid="reliability-delta"
            aria-label={`PS2 reliability ${fmt(firstScored.reliability)} to ${fmt(last.reliability)}`}>
            <span className="from">{fmt(firstScored.reliability)}</span>
            <span aria-hidden="true">→</span>
            <span className="to">{fmt(last.reliability)}</span>
            <span className={delta >= 0 ? 'up' : 'down'}>({delta >= 0 ? '+' : ''}{delta.toFixed(3)})</span>
          </span>
        )}
      </div>

      <div className="attempts">
        {attempts.map((a, i) => (
          <div key={a.attempt}>
            {i > 0 && (
              <div className="regen-link">
                <span className="arrowdown" aria-hidden="true">↓</span>
                <span className="nl">Regeneration → attempt {a.attempt}</span>
                <span>the rejection reasons above were written into the next prompt</span>
              </div>
            )}
            <AttemptBlock a={a} first={i === 0} />
            {!a.final && a.reasons.length > 0 && (
              <div className="trace-reasons" data-testid="trace-rejection-reason">
                <b>Exact rejection reason</b>
                <ul className="reasons">
                  {a.spans.filter((s) => /contradict/.test(s.reason)).map((s, j) => (
                    <li key={`s${j}`}><span className="quote">"{s.text}"</span> → {s.reason}</li>
                  ))}
                  {a.reasons.map((r, j) => <li key={j}>{r}</li>)}
                </ul>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
