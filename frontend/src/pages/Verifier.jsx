import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api.js';
import { EvidenceTable, verdictTone } from '../components/CandidateCard.jsx';
import FlaggedSpans from '../components/FlaggedSpans.jsx';
import HighlightedText from '../components/HighlightedText.jsx';
import ScoreBar from '../components/ScoreBar.jsx';
import TaxonomyFilters from '../components/TaxonomyFilters.jsx';
import { areaLabel, areaOf, difficultyOf, matchesFilters, useAppData } from '../state/AppData.jsx';

/**
 * PS2 Verifier - an inspection view of results that were ALREADY verified
 * automatically by the pipeline (active job results + stored validation reports).
 * Nothing here re-runs verification; it shows what PS2 concluded and why.
 * The free-text verifier is kept below for ad-hoc checks.
 */

const fmt = (v, d = 3) => (typeof v === 'number' ? v.toFixed(d) : '—');

function useVerifiedItems(job) {
  const [reports, setReports] = useState([]);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    api.validationReports().then((d) => { setReports(d.reports || []); setError(null); }).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  // Refresh when a job finishes, so its persisted reports appear.
  useEffect(() => { if (job?.status === 'completed') load(); }, [job?.status, load]);

  const items = useMemo(() => {
    const out = [];
    const seen = new Set();
    (job?.results || []).forEach((r, i) => {
      seen.add(r.candidate.id);
      out.push({
        key: `job-${r.candidate.id}`, source: job.demo ? 'DEMO job' : 'current job',
        question: r.candidate.question, answer: r.candidate.answer_key, decision: r.decision,
        subject_area: r.subject_area, domain: r.candidate.domain, difficulty: r.candidate.difficulty,
        strategy: r.candidate.variation_strategy, method: r.candidate.solution_method,
        rv: r.reliability_verification, sv: r.structural_validation, attempts: r.attempts, index: i + 1,
      });
    });
    [...reports].reverse().forEach((r) => {
      if (seen.has(r.candidate_id)) return;
      out.push({
        key: `rep-${r.candidate_id}-${r.created_at}`, source: 'stored report',
        question: r.question, answer: null, decision: r.decision,
        subject_area: r.subject_area, domain: r.domain, difficulty: r.difficulty,
        strategy: r.variation_strategy, method: r.solution_method,
        rv: r.reliability_verification, sv: r.structural_validation, attempts: r.attempts,
        created_at: r.created_at,
      });
    });
    return out;
  }, [job, reports]);
  return { items, error, reload: load };
}

function Detail({ item, taxonomy }) {
  const rv = item.rv;
  if (!rv) {
    return <div className="empty">No PS2 result is stored for this candidate (recorded before PS2 ran on every candidate).</div>;
  }
  const combined = item.answer ? `${item.question}\n\n${item.answer}` : item.question;
  const claimTypes = (rv.claims || []).reduce((a, c) => ({ ...a, [c.claim_type]: (a[c.claim_type] || 0) + 1 }), {});
  return (
    <div className="inspect-detail" data-testid="ps2-detail">
      <div className="card-head">
        <div className="meta">
          <span className="tag">{item.source}</span>
          <span className="tag">{areaLabel(taxonomy, areaOf(item))}</span>
          {item.difficulty && <span className="tag">{item.difficulty}</span>}
          {item.strategy && <span className="tag ps8">{item.strategy}</span>}
          {item.method && <span className="tag ps8">method: {item.method}</span>}
        </div>
        <span className={`badge lg ${item.decision}`}>{item.decision}</span>
      </div>
      <div className="question">
        <HighlightedText text={combined.slice(0, item.question.length)} spans={rv.flagged_spans || []} />
      </div>
      <div className="metrics">
        <div className={`metric hero ${verdictTone(rv.verdict)}`}>
          <div className="k">PS2 reliability</div><div className="v">{fmt(rv.reliability_score)}</div>
          <div className="s"><span className={`verdict ${rv.verdict}`}>{rv.verdict.replace(/_/g, ' ')}</span></div>
        </div>
        <div className="metric"><div className="k">Hallucination prob.</div><div className="v">{fmt(rv.hallucination_probability)}</div><div className="s">lower is better</div></div>
        <div className="metric"><div className="k">Confidence</div><div className="v">{fmt(rv.confidence_score)}</div><div className="s">evidence breadth</div></div>
        <div className="metric"><div className="k">PS8</div><div className="v">{item.sv ? (item.sv.passed ? 'passed' : 'failed') : '—'}</div><div className="s">structural gate</div></div>
      </div>
      <section className={`spans-panel ${rv.flagged_spans?.length ? '' : 'clean'}`}>
        {rv.flagged_spans?.length
          ? <><h4>{rv.flagged_spans.length} flagged span(s) — why PS2 raised them</h4><FlaggedSpans spans={rv.flagged_spans} /></>
          : <h4>No claims were flagged by PS2</h4>}
      </section>
      <h3 style={{ marginTop: 18 }}>Claims ({rv.claims?.length ?? 0}) · {Object.entries(claimTypes).map(([k, v]) => `${v} ${k}`).join(', ')}</h3>
      <div className="table-wrap"><table>
        <thead><tr><th>Claim</th><th>Type</th></tr></thead>
        <tbody>{(rv.claims || []).map((c, i) => <tr key={i}><td>{c.text}</td><td>{c.claim_type}</td></tr>)}</tbody>
      </table></div>
      {rv.evidence?.length > 0 && (<><h3 style={{ marginTop: 18 }}>Evidence</h3><EvidenceTable evidence={rv.evidence} /></>)}
      {rv.contradictions?.length > 0 && (
        <><h3 style={{ marginTop: 18 }}>Contradictions</h3>
          {rv.contradictions.map((c, i) => (
            <div className="flag" key={i}><div className="sev">{c.type}</div><div className="txt">"{c.claim_a}"</div><div className="txt">vs "{c.claim_b}"</div><div className="why">{c.reason}</div></div>
          ))}</>
      )}
      {rv.reasons?.length > 0 && (<><h3 style={{ marginTop: 18 }}>Why</h3><ul className="reasons">{rv.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul></>)}
      <details>
        <summary>Signals</summary>
        {Object.entries(rv.signals || {}).map(([k, v]) => (
          <div className="check" key={k}><span className="name">{k.replace(/_/g, ' ')}</span><span className="num">{typeof v === 'number' ? v.toFixed(3) : String(v)}</span></div>
        ))}
      </details>
    </div>
  );
}

function Inspector() {
  const { job, taxonomy } = useAppData();
  const { items, error, reload } = useVerifiedItems(job);
  const [filters, setFilters] = useState({ area: '', difficulty: '' });
  const [decision, setDecision] = useState('');
  const [verdict, setVerdict] = useState('');
  const [selected, setSelected] = useState(null);

  const rows = items.filter((it) => matchesFilters(it, filters)
    && (!decision || it.decision === decision)
    && (!verdict || it.rv?.verdict === verdict));
  const current = rows.find((r) => r.key === selected) || rows[0] || null;

  return (
    <div className="panel" data-testid="ps2-inspector">
      <div className="toolbar">
        <h2>PS2 Verifier <span className="status-pill">{rows.length} of {items.length} verified</span></h2>
        <div className="actions"><button className="ghost" onClick={reload}>Refresh</button></div>
      </div>
      <p className="lede">
        Every generated candidate is verified by PS2 automatically. Pick one to inspect exactly what PS2
        concluded — reliability, verdict, each claim, its evidence and the flagged spans.
      </p>
      <div className="filters">
        <TaxonomyFilters idPrefix="insp" value={filters} onChange={setFilters} />
        <div>
          <label htmlFor="insp-decision">Decision</label>
          <select id="insp-decision" value={decision} onChange={(e) => setDecision(e.target.value)}>
            <option value="">All decisions</option><option>PASS</option><option>REVIEW</option><option>REJECT</option>
          </select>
        </div>
        <div>
          <label htmlFor="insp-verdict">PS2 verdict</label>
          <select id="insp-verdict" value={verdict} onChange={(e) => setVerdict(e.target.value)}>
            <option value="">All verdicts</option>
            {['trustworthy', 'partially_reliable', 'unverifiable', 'misleading', 'fabricated'].map((v) => <option key={v} value={v}>{v.replace(/_/g, ' ')}</option>)}
          </select>
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {!rows.length ? (
        <div className="empty">No verified candidates match. Run a job on Generate &amp; Verify — every candidate lands here automatically.</div>
      ) : (
        <div className="inspect">
          <ul className="inspect-list" aria-label="Verified candidates">
            {rows.map((it) => (
              <li key={it.key}>
                <button className={`inspect-row ${current?.key === it.key ? 'active' : ''}`} onClick={() => setSelected(it.key)}>
                  <span className={`badge ${it.decision}`}>{it.decision}</span>
                  <span className="inspect-q">{it.question}</span>
                  <span className="inspect-meta">
                    {areaLabel(taxonomy, areaOf(it))} · {difficultyOf(it) || '—'} · PS2 {fmt(it.rv?.reliability_score, 2)}
                    {it.rv?.verdict ? ` ${it.rv.verdict.replace(/_/g, ' ')}` : ''}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {current && <Detail item={current} taxonomy={taxonomy} />}
        </div>
      )}
    </div>
  );
}

function CustomVerify() {
  const [text, setText] = useState(
    'Reversing a singly linked list iteratively runs in O(log n) time. According to ' +
      'the 2019 Stanford Algorithms Report, it is 47.3% faster than recursion. ' +
      'Recursive reversal always uses O(1) space.'
  );
  const [context, setContext] = useState('');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [fixtures, setFixtures] = useState([]);

  useEffect(() => {
    api.demoFixtures().then((d) => setFixtures(d.cases || [])).catch(() => {});
  }, []);

  async function run() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await api.verify({
          response_text: text,
          source_context: context.trim() ? context.split('\n').filter(Boolean) : [],
        })
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="panel">
        <h2>PS2 · Verify any AI response</h2>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 0 }}>
          This is the standalone <code>POST /api/v1/verify</code> contract. It needs no
          model server — only the local MiniLM embeddings and the reference corpus.
        </p>

        <label htmlFor="rt">Response text</label>
        <textarea id="rt" value={text} onChange={(e) => setText(e.target.value)} style={{ minHeight: 110 }} />

        <label htmlFor="ctx" style={{ marginTop: 12 }}>
          Optional source context (one trusted statement per line)
        </label>
        <textarea id="ctx" value={context} onChange={(e) => setContext(e.target.value)} />

        <div className="flex" style={{ marginTop: 14 }}>
          <button className="primary" onClick={run} disabled={busy || !text.trim()}>
            {busy ? <><span className="spinner" /> Analysing…</> : 'Verify'}
          </button>
          {fixtures.length > 0 && (
            <>
              <span style={{ fontSize: 12, color: 'var(--dim)' }}>Demo cases:</span>
              {fixtures.map((f) => (
                <button key={f.id} className="chip" title={f.expect}
                  onClick={() => { setText(f.response_text); setResult(null); }}>
                  {f.label}
                </button>
              ))}
            </>
          )}
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {result && (
        <div className="panel">
          <h2>
            Verdict: <span className={`verdict ${result.verdict}`}>{result.verdict.replace(/_/g, ' ')}</span>
          </h2>

          <div className="gates">
            <div className="gate ps2">
              <h4>Scores</h4>
              <ScoreBar label="Reliability score" value={result.reliability_score} />
              <ScoreBar label="Confidence" value={result.confidence_score} />
              <ScoreBar label="Hallucination probability" value={result.hallucination_probability} invert />
              <div className="check" style={{ marginTop: 10 }}>
                <span className="name">Analysis time</span>
                <span className="num">{Math.round(result.analysis_time_ms)} ms</span>
              </div>
              <div className="check">
                <span className="name">Within 10s budget</span>
                <span className={result.within_latency_budget ? 'yes' : 'no'}>
                  {result.within_latency_budget ? 'YES' : 'NO'}
                </span>
              </div>
              <div className="check">
                <span className="name">Embedding backend</span>
                <span className="num" style={{ fontSize: 12 }}>
                  {result.embedding_backend?.includes('MiniLM') || result.embedding_backend?.includes('MiniLM'.toLowerCase())
                    ? 'MiniLM' : result.embedding_backend}
                </span>
              </div>
            </div>

            <div className="gate ps2">
              <h4>Signals</h4>
              {Object.entries(result.signals || {}).map(([k, v]) => (
                <div className="check" key={k}>
                  <span className="name">{k.replace(/_/g, ' ')}</span>
                  <span className="num">{typeof v === 'number' ? v.toFixed(3) : String(v)}</span>
                </div>
              ))}
            </div>
          </div>

          <h3 style={{ marginTop: 18 }}>Flagged spans</h3>
          <FlaggedSpans spans={result.flagged_spans} />

          {result.contradictions?.length > 0 && (
            <>
              <h3 style={{ marginTop: 18 }}>Contradictions</h3>
              {result.contradictions.map((c, i) => (
                <div className="flag" key={i}>
                  <div className="sev">{c.type}</div>
                  <div className="txt">"{c.claim_a}"</div>
                  <div className="txt">vs "{c.claim_b}"</div>
                  <div className="why">{c.reason}</div>
                </div>
              ))}
            </>
          )}

          {result.reasons?.length > 0 && (
            <>
              <h3 style={{ marginTop: 18 }}>Why</h3>
              <ul className="reasons">{result.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
            </>
          )}

          {result.recommendations?.length > 0 && (
            <>
              <h3 style={{ marginTop: 18 }}>Recommendations</h3>
              <ul className="reasons">{result.recommendations.map((r, i) => <li key={i}>{r}</li>)}</ul>
            </>
          )}

          <details style={{ marginTop: 14 }}>
            <summary>Evidence trail ({result.evidence?.length ?? 0} claim checks)</summary>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Claim</th><th>Status</th><th>Sim.</th><th>Keyword</th><th>Source</th></tr></thead>
                <tbody>
                  {(result.evidence || []).map((e, i) => (
                    <tr key={i}>
                      <td>{e.claim}</td>
                      <td>{e.status.replace(/_/g, ' ')}</td>
                      <td className="mono">{e.similarity?.toFixed(2)}</td>
                      <td className="mono">{e.keyword_grounding?.toFixed(2)}</td>
                      <td>{e.source_title || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </div>
      )}
    </>
  );
}

export default function VerifierPage() {
  return (
    <>
      <Inspector />
      <details className="panel custom-verify">
        <summary>Verify custom text — run PS2 on any response you paste (ad-hoc check)</summary>
        <CustomVerify />
      </details>
    </>
  );
}
