import FlaggedSpans from './FlaggedSpans.jsx';
import HighlightedText from './HighlightedText.jsx';
import StageTrace from './StageTrace.jsx';
import Icon from './Icon.jsx';
import ValidationReport, { GateGrid, gateChecks } from './ValidationReport.jsx';
import { areaLabel, useAppData } from '../state/AppData.jsx';

const fmt = (v, d = 3) => (typeof v === 'number' ? v.toFixed(d) : '—');

/** Tone of a PS2 result, read from the verdict the backend returned. */
export function verdictTone(verdict) {
  if (verdict === 'trustworthy') return 'good';
  if (verdict === 'partially_reliable' || verdict === 'unverifiable') return 'mid';
  if (verdict === 'misleading' || verdict === 'fabricated') return 'bad';
  return '';
}

/** Attempt 1 → REJECT → Attempt 2 → PASS, straight from the regeneration history. */
export function AttemptTimeline({ history = [], finalDecision, attempts }) {
  if (!history.length) return null;
  return (
    <div className="timeline" data-testid="attempt-timeline">
      {history.map((h) => (
        <span key={h.attempt} className="flex" style={{ gap: 6 }}>
          <span>Attempt {h.attempt}</span>
          <span className={`badge ${h.decision}`}>{h.decision}</span>
          <span className="arrow" aria-hidden="true">→</span>
        </span>
      ))}
      <span>Attempt {attempts}</span>
      <span className={`badge ${finalDecision}`}>{finalDecision}</span>
    </div>
  );
}

/** Every rejected attempt with its exact reasons, as fed back into the next prompt. */
export function RegenerationDetail({ history = [] }) {
  if (!history.length) return null;
  return (
    <div className="regen">
      <h4>Regeneration — the exact rejection reasons were fed back into the next prompt</h4>
      {history.map((h) => (
        <div key={h.attempt} style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 13, color: 'var(--muted)' }}>
            Attempt {h.attempt} → <b>{h.decision}</b>. Rejected question:
          </div>
          <div className="old">{h.rejected_question}</div>
          <ul className="reasons">
            {[...(h.structural_reasons || []), ...(h.reliability_reasons || [])]
              .map((r, j) => <li key={j}>{r}</li>)}
          </ul>
        </div>
      ))}
    </div>
  );
}

export function EvidenceTable({ evidence = [] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Claim</th><th>Status</th><th>Sim.</th><th>Source</th></tr></thead>
        <tbody>
          {evidence.map((e, i) => (
            <tr key={i}>
              <td>{e.claim}</td>
              <td style={{ whiteSpace: 'nowrap', color: e.supported ? 'var(--pass-text)' : 'var(--muted)' }}>
                {e.status.replace(/_/g, ' ')}
              </td>
              <td className="mono">{e.similarity?.toFixed(2)}</td>
              <td>{e.source_title || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const DECISION_ICON = { PASS: 'check-circle', REVIEW: 'alert', REJECT: 'x-circle' };

/** PASS / REVIEW / REJECT pill: icon + word, never colour alone. */
export function DecisionBadge({ decision, size = '' }) {
  return (
    <span className={`decision ${decision} ${size}`}>
      <Icon name={DECISION_ICON[decision] || 'alert'} size={size === 'lg' ? 16 : 14} />
      {decision}
    </span>
  );
}

const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

/**
 * One candidate, laid out as the design's evaluation card: identity + decision +
 * reliability up top, the problem statement, why it was decided that way, the
 * answer, the two gate grids (PS8 and PS2 both ran automatically), then evidence
 * and regeneration history behind expandable sections. Every value is the
 * backend's; nothing here is computed beyond formatting.
 */
export default function CandidateCard({ item, index, onOpenBank, onOpenReview, demo = false }) {
  const c = item.candidate;
  const { taxonomy } = useAppData();
  const sv = item.structural_validation;
  const rv = item.reliability_verification;
  const decision = item.decision;
  const history = item.regeneration_history || [];
  const { ps8, ps2 } = gateChecks(sv, rv);

  // PS2 verifies question + answer key together, so offsets index that combined text.
  const combined = `${c.question}\n\n${c.answer_key}`;
  const spans = rv?.flagged_spans || [];
  const reasons = [...new Set([
    ...(item.decision_reasons || []),
    ...(decision !== 'PASS' ? sv?.reasons || [] : []),
    ...(rv && decision !== 'PASS' ? rv.reasons || [] : []),
  ])].map((x) => x.replace(/^(REVIEW|REJECT|PASS):\s*/, ''));
  const area = item.subject_area ? areaLabel(taxonomy, item.subject_area) : areaLabel(taxonomy, c.domain);
  const strategy = c.strategy_label || c.variation_strategy;

  return (
    <article className={`cand ${decision}`} data-testid="candidate-card" aria-label={`Candidate ${index + 1}: ${decision}`}>
      <header className="cand-head">
        <div className="cand-id">
          <div className="cand-chips">
            <span className="qid mono">#{c.id}</span>
            <DecisionBadge decision={decision} />
            {demo && <span className="demo-tag">DEMO</span>}
            {item.attempts > 1 && (
              <span className="chip-static repaired" title="Regenerated from the rejection reasons">
                {decision === 'PASS' ? 'Auto-repaired' : 'Regenerated'} (attempt {item.attempts})
              </span>
            )}
            <span className="chip-static">{area}</span>
            <span className={`difficulty ${c.difficulty}`}>{cap(c.difficulty)}</span>
          </div>
          <h3 className="cand-title">
            Variation {index + 1} · {strategy}{c.solution_method ? ` · ${c.solution_method} method` : ''}
          </h3>
        </div>
        <div className="cand-side">
          <div className="reliability" data-testid="metric-reliability">
            <span className="k">Reliability</span>
            <span className={`v ${verdictTone(rv?.verdict)}`}>{rv ? fmt(rv.reliability_score, 2) : '—'}<small> / 1.0</small></span>
          </div>
          {decision === 'PASS' && !demo && onOpenBank && (
            <button className="btn primary sm" onClick={onOpenBank}><Icon name="check" size={15} />Saved to Bank</button>
          )}
          {decision === 'REVIEW' && !demo && onOpenReview && (
            <button className="btn review sm" onClick={onOpenReview}><Icon name="alert" size={15} />Requires Review</button>
          )}
          {demo && <span className="chip-static">not saved</span>}
        </div>
      </header>

      {history.length > 0 && <AttemptTimeline history={history} finalDecision={decision} attempts={item.attempts} />}

      <section className="statement">
        <div className="statement-head">
          <span className="eyebrow">Primary problem statement</span>
          <span className="target mono">Target: {c.difficulty}{typeof c.difficulty_score === 'number' ? ` (${c.difficulty_score.toFixed(2)})` : ''} · {c.question_type}</span>
        </div>
        <p className="statement-body">
          {spans.length ? <HighlightedText text={combined.slice(0, c.question.length)} spans={spans} /> : c.question}
        </p>
      </section>

      <details className={`fold reason ${decision}`} open={decision !== 'PASS'} data-testid="decision-reason">
        <summary><Icon name={DECISION_ICON[decision]} size={16} />Decision reason<Icon name="chevron-down" size={16} className="caret" /></summary>
        <div className="fold-body">
          {rv && (
            <p className="reason-line">
              PS2 verdict <span className={`verdict ${rv.verdict}`}>{rv.verdict.replace(/_/g, ' ')}</span> ·
              reliability {fmt(rv.reliability_score)} · hallucination probability {fmt(rv.hallucination_probability)} ·
              {' '}{spans.length} flagged span{spans.length === 1 ? '' : 's'}
            </p>
          )}
          {reasons.length > 0
            ? <ul className="reasons">{reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
            : <p className="reason-line">Passed PS8 structural validation and PS2 reliability verification.</p>}
        </div>
      </details>

      <section className="variation">
        <div className="eyebrow-row">
          <span className="eyebrow"><Icon name="list" size={14} />Generated variation</span>
          <span className="hint">Answer collapsed by default</span>
        </div>
        <div className="variation-box">
          <span className="tagline-chip">{strategy}{c.solution_method ? ` · ${c.solution_method}` : ''}</span>
          {c.learning_objective && <p className="objective">{c.learning_objective}</p>}
          <details className="inline-fold">
            <summary><Icon name="chevron-down" size={15} className="caret" />Show answer</summary>
            <pre className="answer mono">{c.answer_key || 'missing'}</pre>
          </details>
          {c.test_cases?.length > 0 && (
            <details className="inline-fold">
              <summary><Icon name="chevron-down" size={15} className="caret" />{c.test_cases.length} test case{c.test_cases.length === 1 ? '' : 's'}</summary>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Input</th><th>Expected output</th></tr></thead>
                  <tbody>
                    {c.test_cases.map((tc, i) => (
                      <tr key={i}><td className="mono">{tc.input}</td><td className="mono">{tc.expected_output}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </div>
      </section>

      <div className="gate-pair">
        <GateGrid engine="ps8" title="Structural checks" checks={ps8} />
        <GateGrid engine="ps2" title="Grounding checks" checks={ps2} />
      </div>

      <details className="fold">
        <summary><Icon name="chevron-right" size={16} className="caret" />View evidence, flagged spans &amp; full validation report<span className="fold-meta">{rv?.evidence?.length ?? 0} claim checks · {spans.length} flagged</span></summary>
        <div className="fold-body">
          {rv && (
            <section className={`spans-panel ${spans.length ? '' : 'clean'}`} aria-label="Flagged spans">
              {spans.length ? (<><h4>{spans.length} flagged span(s) — why PS2 raised them</h4><FlaggedSpans spans={spans} /></>)
                : <h4>No claims were flagged by PS2</h4>}
            </section>
          )}
          {rv?.evidence?.length > 0 && <EvidenceTable evidence={rv.evidence} />}
          <ValidationReport sv={sv} rv={rv} decision={decision} decisionReasons={item.decision_reasons} />
          {c.parse_warnings?.length > 0 && (
            <ul className="reasons">{c.parse_warnings.map((w, i) => <li key={i}>Parser: {w}</li>)}</ul>
          )}
        </div>
      </details>

      {(history.length > 0 || demo) && (
        <details className="fold" open={demo}>
          <summary><Icon name="chevron-right" size={16} className="caret" />View regeneration history<span className="fold-meta">{history.length ? `${history.length} rejected attempt${history.length === 1 ? '' : 's'} · final attempt ${item.attempts}` : 'accepted on the first attempt'}</span></summary>
          <div className="fold-body">
            <StageTrace item={item} />
            <RegenerationDetail history={history} />
          </div>
        </details>
      )}
    </article>
  );
}
