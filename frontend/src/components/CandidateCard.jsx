import FlaggedSpans from './FlaggedSpans.jsx';
import HighlightedText from './HighlightedText.jsx';
import ScoreBar from './ScoreBar.jsx';

/**
 * One candidate, showing both gates side by side.
 *
 * The left column is PS8 (is this a good *variation*?), the right is PS2
 * (is it *trustworthy*?). Putting them next to each other is the whole point of
 * the integration: a judge can see at a glance that PASS requires both.
 */
export default function CandidateCard({ item, index }) {
  const c = item.candidate;
  const sv = item.structural_validation;
  const rv = item.reliability_verification;
  const decision = item.decision;

  // PS2 verifies question + answer key together, so offsets index that combined text.
  const combined = `${c.question}\n\n${c.answer_key}`;

  return (
    <div className={`card ${decision}`}>
      <div className="card-head">
        <div>
          <div className="idx">
            VARIATION #{index + 1}
            {item.attempts > 1 ? ` · ${item.attempts} attempts` : ''}
          </div>
          <div className="meta" style={{ marginTop: 6 }}>
            <span className="tag ps8">{c.strategy_label || c.variation_strategy}</span>
            <span className="tag">{c.difficulty}</span>
            <span className="tag">{c.question_type}</span>
            <span className="tag">{c.domain}</span>
            {c.subtopic && <span className="tag">{c.subtopic}</span>}
            <span className="tag">status: {item.status}</span>
          </div>
        </div>
        <span className={`badge ${decision}`}>{decision}</span>
      </div>

      <div className="question">
        {rv?.flagged_spans?.length ? (
          <HighlightedText text={combined.slice(0, c.question.length)} spans={rv.flagged_spans} />
        ) : (
          c.question
        )}
      </div>

      <div className="answer">
        <div className="lbl">Answer key</div>
        {c.answer_key || <em style={{ color: 'var(--reject)' }}>missing</em>}
      </div>

      {c.test_cases?.length > 0 && (
        <details>
          <summary>{c.test_cases.length} test case(s)</summary>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Input</th><th>Expected output</th></tr>
              </thead>
              <tbody>
                {c.test_cases.map((tc, i) => (
                  <tr key={i}>
                    <td className="mono">{tc.input}</td>
                    <td className="mono">{tc.expected_output}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}

      <div className="gates">
        {/* ---------------- PS8 gate ---------------- */}
        <div className="gate ps8">
          <h4>PS8 · Structural validation</h4>
          {sv ? (
            <>
              <div className="check">
                <span className="name">Concept preserved</span>
                <span className={sv.concept_preserved ? 'yes' : 'no'}>
                  {sv.concept_preserved ? 'PASS' : 'FAIL'}
                </span>
              </div>
              <div className="check">
                <span className="name">Difficulty match</span>
                <span className={sv.difficulty_match ? 'yes' : 'no'}>
                  {sv.difficulty_match ? 'PASS' : 'FAIL'}
                </span>
              </div>
              <div className="check">
                <span className="name">Not a duplicate</span>
                <span className={!sv.is_duplicate ? 'yes' : 'no'}>
                  {!sv.is_duplicate ? 'PASS' : 'FAIL'}
                </span>
              </div>
              <div className="check">
                <span className="name">Meaningful variation</span>
                <span className={sv.meaningful_variation ? 'yes' : 'no'}>
                  {sv.meaningful_variation ? 'PASS' : 'FAIL'}
                </span>
              </div>
              <div className="check" style={{ marginTop: 8 }}>
                <span className="name">Similarity to seed</span>
                <span className="num">{sv.semantic_similarity?.toFixed(3)}</span>
              </div>
              <div className="check">
                <span className="name">Lexical overlap</span>
                <span className="num">{sv.lexical_similarity?.toFixed(3)}</span>
              </div>
              {sv.reasons?.length > 0 && (
                <ul className="reasons">
                  {sv.reasons.map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              )}
            </>
          ) : (
            <div style={{ color: 'var(--dim)', fontSize: 13 }}>not run</div>
          )}
        </div>

        {/* ---------------- PS2 gate ---------------- */}
        <div className="gate ps2">
          <h4>PS2 · Reliability verification</h4>
          {rv ? (
            <>
              <ScoreBar label="Reliability score" value={rv.reliability_score} />
              <ScoreBar label="Confidence" value={rv.confidence_score} />
              <ScoreBar label="Hallucination probability" value={rv.hallucination_probability} invert />

              <div className="verdict-line">
                Verdict: <span className={`verdict ${rv.verdict}`}>{rv.verdict.replace(/_/g, ' ')}</span>
              </div>

              <div className="check" style={{ marginTop: 8 }}>
                <span className="name">Claims checked</span>
                <span className="num">{rv.claims?.length ?? 0}</span>
              </div>
              <div className="check">
                <span className="name">Grounded in corpus</span>
                <span className="num">{rv.evidence?.filter((e) => e.supported).length ?? 0}</span>
              </div>
              <div className="check">
                <span className="name">Contradictions</span>
                <span className={rv.contradictions?.length ? 'no' : 'yes'}>
                  {rv.contradictions?.length ?? 0}
                </span>
              </div>
              <div className="check">
                <span className="name">Analysis time</span>
                <span className="num">{Math.round(rv.timings_ms?.total_ms ?? 0)} ms</span>
              </div>
            </>
          ) : (
            <div style={{ color: 'var(--dim)', fontSize: 13 }}>
              not run — PS8 structural validation failed first
            </div>
          )}
        </div>
      </div>

      {rv?.flagged_spans?.length > 0 && (
        <details open={decision !== 'PASS'}>
          <summary>{rv.flagged_spans.length} flagged claim(s) — why PS2 raised them</summary>
          <FlaggedSpans spans={rv.flagged_spans} />
        </details>
      )}

      {rv?.evidence?.length > 0 && (
        <details>
          <summary>Evidence trail ({rv.evidence.length} claim checks)</summary>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Claim</th><th>Status</th><th>Sim.</th><th>Source</th></tr>
              </thead>
              <tbody>
                {rv.evidence.map((e, i) => (
                  <tr key={i}>
                    <td>{e.claim}</td>
                    <td className={e.supported ? 'yes' : ''} style={{ whiteSpace: 'nowrap' }}>
                      {e.status.replace(/_/g, ' ')}
                    </td>
                    <td className="mono">{e.similarity?.toFixed(2)}</td>
                    <td>{e.source_title || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}

      {item.regeneration_history?.length > 0 && (
        <div className="regen">
          <h4>Regeneration — {item.regeneration_history.length} attempt(s) fed back into the prompt</h4>
          {item.regeneration_history.map((h, i) => (
            <div key={i} style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 12, color: 'var(--muted)' }}>Attempt {h.attempt} was rejected:</div>
              <div className="old">{h.rejected_question}</div>
              <ul className="reasons">
                {[...(h.structural_reasons || []), ...(h.reliability_reasons || [])]
                  .slice(0, 4)
                  .map((r, j) => <li key={j}>{r}</li>)}
              </ul>
            </div>
          ))}
        </div>
      )}

      {item.decision_reasons?.length > 0 && (
        <details>
          <summary>Decision rationale</summary>
          <ul className="reasons">
            {item.decision_reasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </details>
      )}

      {c.parse_warnings?.length > 0 && (
        <details>
          <summary>{c.parse_warnings.length} parser warning(s)</summary>
          <ul className="reasons">
            {c.parse_warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}
