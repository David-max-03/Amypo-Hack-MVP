import FlaggedSpans from './FlaggedSpans.jsx';
import HighlightedText from './HighlightedText.jsx';
import StageTrace from './StageTrace.jsx';
import ValidationReport from './ValidationReport.jsx';
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

function Metric({ k, v, s, tone = '', hero = false, bar, invert = false, testid }) {
  const width = typeof bar === 'number' ? Math.round(Math.max(0, Math.min(1, bar)) * 100) : null;
  return (
    <div className={`metric ${tone} ${hero ? 'hero' : ''}`} data-testid={testid}>
      <div className="k">{k}</div>
      <div className="v">{v}</div>
      {s && <div className="s">{s}</div>}
      {width !== null && (
        <div className="bar" aria-hidden="true">
          <i className={invert ? (bar <= 0.3 ? 'good' : bar <= 0.55 ? 'mid' : 'bad') : (tone || 'mid')} style={{ width: `${width}%` }} />
        </div>
      )}
    </div>
  );
}

/**
 * One candidate: decision first, then how it got there (timeline), the question,
 * the key numbers, why PS2 flagged anything, and the full report.
 */
export default function CandidateCard({ item, index, onOpenBank, demo = false }) {
  const c = item.candidate;
  const { taxonomy } = useAppData();
  const sv = item.structural_validation;
  const rv = item.reliability_verification;
  const decision = item.decision;
  const dup = sv?.checks?.duplicate || {};
  const history = item.regeneration_history || [];

  // PS2 verifies question + answer key together, so offsets index that combined text.
  const combined = `${c.question}\n\n${c.answer_key}`;
  const rejectReasons = [...(sv?.reasons || []), ...(rv && decision !== 'PASS' ? rv.reasons || [] : [])];
  const spans = rv?.flagged_spans || [];

  return (
    <article className={`card ${decision}`} data-testid="candidate-card" aria-label={`Variation ${index + 1}: ${decision}`}>
      <div className="card-head">
        <div>
          <div className="idx">
            {demo && <span className="demo-tag">DEMO</span>}
            VARIATION #{index + 1}
            {item.attempts > 1 ? ` · ${item.attempts} attempts` : ' · first attempt'}
          </div>
          <div className="meta" style={{ marginTop: 8 }}>
            <span className="tag ps8" title="variation strategy">{c.strategy_label || c.variation_strategy}</span>
            {c.solution_method && <span className="tag ps8" title="solution method">method: {c.solution_method}</span>}
            <span className="tag" title="difficulty">{c.difficulty} ({c.difficulty_score?.toFixed(2)})</span>
            <span className="tag">{c.question_type}</span>
            <span className="tag" title="subject area">{item.subject_area ? areaLabel(taxonomy, item.subject_area) : c.domain}</span>
          </div>
        </div>
        <span className={`badge lg ${decision}`}>{decision}</span>
      </div>

      <AttemptTimeline history={history} finalDecision={decision} attempts={item.attempts} />
      {(demo || history.length > 0) && <StageTrace item={item} />}

      <div className="question">
        {spans.length ? (
          <HighlightedText text={combined.slice(0, c.question.length)} spans={spans} />
        ) : (
          c.question
        )}
      </div>

      <div className="metrics">
        {rv ? (
          <Metric testid="metric-reliability" hero k="PS2 reliability" v={fmt(rv.reliability_score)}
            s={<span className={`verdict ${rv.verdict}`}>{rv.verdict.replace(/_/g, ' ')}</span>}
            tone={verdictTone(rv.verdict)} bar={rv.reliability_score} />
        ) : (
          <Metric testid="metric-reliability" hero k="PS2 reliability" v="—" s="not run — PS8 structural validation failed first" />
        )}
        <Metric k="Hallucination prob." v={rv ? fmt(rv.hallucination_probability) : '—'}
          s={rv ? 'lower is better' : 'not run'} bar={rv ? rv.hallucination_probability : undefined} invert />
        <Metric k="Similarity to seed" v={fmt(sv?.semantic_similarity)}
          s={`nearest duplicate ${fmt(dup.max_semantic_similarity, 2)}${dup.nearest_source ? ` · ${dup.nearest_source}` : ''}`} />
        <Metric k="Attempts" v={item.attempts}
          s={history.length ? `${history.length} regenerated from rejection feedback` : 'accepted as generated'} />
      </div>

      {decision !== 'PASS' && rejectReasons.length > 0 && (
        <div className={`reject-box ${decision}`} data-testid="rejection-reason">
          <b>{decision === 'REJECT' ? 'Rejected because:' : 'Sent to review because:'}</b>
          <ul className="reasons">{rejectReasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </div>
      )}

      {rv && (
        <section className={`spans-panel ${spans.length ? '' : 'clean'}`} aria-label="Flagged spans">
          {spans.length ? (
            decision === 'PASS' ? (
              <details style={{ marginTop: 0 }}>
                <summary>{spans.length} flagged span(s) — minor, PS2 still passed it</summary>
                <FlaggedSpans spans={spans} />
              </details>
            ) : (
              <>
                <h4>{spans.length} flagged span(s) — why PS2 raised them</h4>
                <FlaggedSpans spans={spans} />
              </>
            )
          ) : (
            <h4>No claims were flagged by PS2</h4>
          )}
        </section>
      )}

      <details open>
        <summary>Answer key</summary>
        <pre className="answer mono" style={{ whiteSpace: 'pre-wrap' }}>{c.answer_key || 'missing'}</pre>
      </details>

      {c.test_cases?.length > 0 && (
        <details>
          <summary>{c.test_cases.length} test case(s)</summary>
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

      <ValidationReport sv={sv} rv={rv} decision={decision} decisionReasons={item.decision_reasons} />

      {rv?.evidence?.length > 0 && (
        <details>
          <summary>Evidence trail ({rv.evidence.length} claim checks)</summary>
          <EvidenceTable evidence={rv.evidence} />
        </details>
      )}

      {history.length > 0 && (
        <details>
          <summary>Rejected attempts in full ({history.length})</summary>
          <RegenerationDetail history={history} />
        </details>
      )}

      {decision === 'PASS' && onOpenBank && !demo && (
        <button className="ghost" style={{ marginTop: 14 }} onClick={onOpenBank}>
          ✓ Saved to the Question Bank — open it
        </button>
      )}

      {c.parse_warnings?.length > 0 && (
        <details>
          <summary>{c.parse_warnings.length} parser warning(s)</summary>
          <ul className="reasons">{c.parse_warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </details>
      )}
    </article>
  );
}
