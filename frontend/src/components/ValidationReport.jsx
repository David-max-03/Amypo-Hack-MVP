/**
 * The readable validation report: every PS8 check, every PS2 signal, the decision.
 * `gateChecks` is the single place the 6 + 6 checks are derived from a backend
 * result; candidate cards and the Reports page reuse it for their compact grids.
 */
const n = (v, d = 2) => (typeof v === 'number' ? v.toFixed(d) : '—');

/** { ps8: [{ ok, label, detail }], ps2: [...] } - ok is true / false / null (not applicable). */
export function gateChecks(sv, rv) {
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

  const ps8 = sv ? [
    { ok: sv.concept_preserved, label: 'Concept',
      detail: `keyword overlap ${n(sv.concept_overlap)} · objective similarity ${n(concept.semantic_similarity_to_objective)}` },
    { ok: sv.difficulty_match, label: 'Difficulty',
      detail: `${diff.candidate ?? '?'} vs seed ${diff.target ?? '?'} · Δ ${n(sv.difficulty_delta)}` },
    { ok: !sv.is_duplicate, label: 'Duplicate',
      detail: `max similarity ${n(dup.max_semantic_similarity)} (lexical ${n(dup.max_lexical_similarity)})` +
        (dup.nearest_source ? ` · nearest: ${dup.nearest_source}` : '') },
    { ok: sv.meaningful_variation, label: 'Meaningful variation',
      detail: `similarity to seed ${n(sv.semantic_similarity)} · lexical ${n(sv.lexical_similarity)}` },
    { ok: answer.substantive ?? sv.checks?.answer_key_present, label: 'Answer key',
      detail: answer.has_code === true ? 'real code' : answer.has_code === false ? 'no code found' : 'present' },
    { ok: method.planned ? !!(method.used_in_answer && method.required_by_question) : null, label: 'Solution method',
      detail: method.planned
        ? `${method.planned} · in answer ${method.used_in_answer ? 'yes' : 'no'} · asked in question ${method.required_by_question ? 'yes' : 'no'}`
        : 'no method axis for this question type' },
  ] : [];

  const ps2 = rv ? [
    { ok: (rv.claims?.length ?? 0) > 0, label: 'Claims',
      detail: `${rv.claims?.length ?? 0} extracted · ` + Object.entries(claimTypes).map(([k, v]) => `${v} ${k}`).join(', ') },
    { ok: typeof rv.signals?.source_grounding === 'number' ? rv.signals.source_grounding >= 0.5 : null, label: 'Source grounding',
      detail: `${supported} of ${evidence.length} checked claims grounded · score ${n(rv.signals?.source_grounding)}` },
    { ok: !(rv.contradictions?.length), label: 'Contradictions', detail: `${rv.contradictions?.length ?? 0} found` },
    { ok: rv.hallucination_probability < 0.5, label: 'Hallucination signals',
      detail: `probability ${n(rv.hallucination_probability, 3)} · unsupported ${n(rv.signals?.unsupported)} · fabrication markers ${n(rv.signals?.fabrication_markers)}` },
    { ok: rv.reliability_score >= 0.7, label: 'Reliability score',
      detail: `${n(rv.reliability_score, 3)} · verdict ${rv.verdict.replace(/_/g, ' ')}` },
    { ok: !(rv.flagged_spans?.length), label: 'Flagged spans', detail: `${rv.flagged_spans?.length ?? 0} flagged` },
  ] : [];

  return { ps8, ps2 };
}

/** "5/6" style tally: applicable checks only. */
export function tally(checks) {
  const applicable = checks.filter((c) => c.ok !== null && c.ok !== undefined);
  return { passed: applicable.filter((c) => c.ok).length, total: applicable.length };
}

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
  const { ps8, ps2 } = gateChecks(sv, rv);
  return (
    <div className="report" data-testid="validation-report">
      <div className="rep-section ps8">
        <h4>PS8 · Structural validation</h4>
        {sv ? (
          <>
            {ps8.map((c) => <Row key={c.label} {...c} />)}
            {sv.reasons?.length > 0 && (
              <ul className="reasons">{sv.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
            )}
          </>
        ) : <div className="rep-empty">not run</div>}
      </div>

      <div className="rep-section ps2">
        <h4>PS2 · Reliability verification</h4>
        {rv ? ps2.map((c) => <Row key={c.label} {...c} />)
          : <div className="rep-empty">not recorded for this candidate</div>}
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

/** Compact check grid used on candidate cards and report cards. */
export function GateGrid({ engine, title, checks }) {
  const t = tally(checks);
  const allOk = t.total > 0 && t.passed === t.total;
  return (
    <div className={`gate-grid ${engine}`} data-testid={`gate-${engine}`}>
      <div className="gate-grid-head">
        <span className="gate-grid-title"><span className={`engine ${engine}`}>{engine.toUpperCase()}</span>{title}</span>
        <span className={`gate-tally ${allOk ? 'ok' : t.total ? 'warn' : ''}`}>
          {t.total ? `${t.passed}/${t.total} passed` : 'not recorded'}
        </span>
      </div>
      {checks.length > 0 && (
        <ul className="gate-checks">
          {checks.map((c) => {
            const cls = c.ok === null || c.ok === undefined ? 'na' : c.ok ? 'yes' : 'no';
            return (
              <li key={c.label} className={cls} title={c.detail}>
                <span className="mark" aria-hidden="true">{cls === 'yes' ? '✓' : cls === 'no' ? '!' : '–'}</span>
                <span>{c.label}</span>
                <span className="sr-only">{cls === 'yes' ? ' passed' : cls === 'no' ? ' failed' : ' not applicable'}: {c.detail}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
