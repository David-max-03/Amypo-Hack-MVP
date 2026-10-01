/**
 * The readable validation report: every PS8 check, every PS2 signal, the decision.
 * Used on candidate cards and on the Validation Reports tab.
 */
const n = (v, d = 2) => (typeof v === 'number' ? v.toFixed(d) : '—');

function Row({ ok, label, detail }) {
  const mark = ok === null || ok === undefined ? '–' : ok ? '✓' : '✗';
  const cls = ok === null || ok === undefined ? 'na' : ok ? 'yes' : 'no';
  return (
    <div className="rep-row">
      <span className={`rep-mark ${cls}`}>{mark}</span>
      <span className="rep-label">{label}</span>
      <span className="rep-detail">{detail}</span>
    </div>
  );
}

export default function ValidationReport({ sv, rv, decision, decisionReasons = [] }) {
  const ck = sv?.checks || {};
  const method = ck.method || {};
  const answer = ck.answer_key || {};
  const dup = ck.duplicate || {};
  const diff = ck.difficulty || {};
  const concept = ck.concept || {};

  const evidence = rv?.evidence || [];
  const supported = evidence.filter((e) => e.supported).length;
  const claimTypes = (rv?.claims || []).reduce((acc, c) => {
    acc[c.claim_type] = (acc[c.claim_type] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="report" data-testid="validation-report">
      <div className="rep-section ps8">
        <h4>PS8 · Structural validation</h4>
        {sv ? (
          <>
            <Row ok={sv.concept_preserved} label="Concept"
              detail={`keyword overlap ${n(sv.concept_overlap)} · objective similarity ${n(concept.semantic_similarity_to_objective)}`} />
            <Row ok={sv.difficulty_match} label="Difficulty"
              detail={`${diff.candidate ?? '?'} vs seed ${diff.target ?? '?'} · Δ ${n(sv.difficulty_delta)}`} />
            <Row ok={!sv.is_duplicate} label="Duplicate"
              detail={`max similarity ${n(dup.max_semantic_similarity)} (lexical ${n(dup.max_lexical_similarity)})` +
                (dup.nearest_source ? ` · nearest: ${dup.nearest_source}` : '')} />
            <Row ok={sv.meaningful_variation} label="Meaningful variation"
              detail={`similarity to seed ${n(sv.semantic_similarity)} · lexical ${n(sv.lexical_similarity)}`} />
            <Row ok={answer.substantive ?? sv.checks?.answer_key_present} label="Answer key"
              detail={answer.has_code === true ? 'real code' : answer.has_code === false ? 'no code found' : 'present'} />
            <Row ok={method.planned ? !!(method.used_in_answer && method.required_by_question) : null}
              label="Solution method"
              detail={method.planned
                ? `${method.planned} · in answer ${method.used_in_answer ? 'yes' : 'no'} · asked in question ${method.required_by_question ? 'yes' : 'no'}`
                : 'no method axis for this question type'} />
            {sv.reasons?.length > 0 && (
              <ul className="reasons">{sv.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
            )}
          </>
        ) : <div className="rep-empty">not run</div>}
      </div>

      <div className="rep-section ps2">
        <h4>PS2 · Reliability verification</h4>
        {rv ? (
          <>
            <Row ok={(rv.claims?.length ?? 0) > 0} label="Claims"
              detail={`${rv.claims?.length ?? 0} extracted · ` +
                Object.entries(claimTypes).map(([k, v]) => `${v} ${k}`).join(', ')} />
            <Row ok={typeof rv.signals?.source_grounding === 'number' ? rv.signals.source_grounding >= 0.5 : null}
              label="Source grounding"
              detail={`${supported} of ${evidence.length} checked claims grounded · score ${n(rv.signals?.source_grounding)}`} />
            <Row ok={!(rv.contradictions?.length)} label="Contradictions"
              detail={`${rv.contradictions?.length ?? 0} found`} />
            <Row ok={rv.hallucination_probability < 0.5} label="Hallucination signals"
              detail={`probability ${n(rv.hallucination_probability, 3)} · unsupported ${n(rv.signals?.unsupported)} · fabrication markers ${n(rv.signals?.fabrication_markers)}`} />
            <Row ok={rv.reliability_score >= 0.7} label="Reliability score"
              detail={<>{n(rv.reliability_score, 3)} · verdict <span className={`verdict ${rv.verdict}`}>{rv.verdict.replace(/_/g, ' ')}</span></>} />
            <Row ok={!(rv.flagged_spans?.length)} label="Flagged spans"
              detail={`${rv.flagged_spans?.length ?? 0} flagged`} />
          </>
        ) : <div className="rep-empty">not run — PS8 structural validation failed first</div>}
      </div>

      <div className={`rep-section decision ${decision}`}>
        <h4>Decision</h4>
        <span className={`badge ${decision}`}>{decision}</span>
        {decisionReasons.length > 0 && (
          <ul className="reasons">{decisionReasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
        )}
      </div>
    </div>
  );
}
