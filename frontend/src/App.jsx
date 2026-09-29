import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import CandidateCard from './components/CandidateCard.jsx';
import FlaggedSpans from './components/FlaggedSpans.jsx';
import HealthBar from './components/HealthBar.jsx';
import PipelineProgress from './components/PipelineProgress.jsx';
import ScoreBar from './components/ScoreBar.jsx';

const TABS = [
  ['pipeline', 'Generate & Verify'],
  ['verify', 'PS2 Verifier'],
  ['bank', 'Question Bank'],
  ['review', 'Review Queue'],
];

export default function App() {
  const [tab, setTab] = useState('pipeline');
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);

  const refreshHealth = useCallback(() => {
    api.health().then(setHealth).catch((e) => setHealthError(e.message));
  }, []);

  useEffect(() => {
    refreshHealth();
    const t = setInterval(refreshHealth, 15000);
    return () => clearInterval(t);
  }, [refreshHealth]);

  return (
    <div className="app">
      <div className="header">
        <div>
          <h1>Code Titans — Question Trust Pipeline</h1>
          <div className="sub">PS8 Question Variation Generation × PS2 Hallucination Detection</div>
          <div className="team">HackWithAMYPO 2026 · Stage 2 MVP · Ashadavid S J &amp; Dinesh A</div>
        </div>
        <HealthBar health={health} error={healthError} />
      </div>

      <div className="tagline">
        <b>PS8 makes the questions diverse. PS2 makes them trustworthy.</b>{' '}
        A candidate is only accepted when it clears both gates. Everything runs locally —
        Qwen2.5-Coder 7B via Ollama for generation, MiniLM for verification. No paid APIs.
      </div>

      <div className="tabs">
        {TABS.map(([id, label]) => (
          <button key={id} className={`tab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'pipeline' && <PipelineTab health={health} onDone={refreshHealth} />}
      {tab === 'verify' && <VerifyTab />}
      {tab === 'bank' && <BankTab />}
      {tab === 'review' && <ReviewTab />}
    </div>
  );
}

/* ==================================================================== */
/* Tab 1 — the integrated pipeline                                       */
/* ==================================================================== */
function PipelineTab({ health, onDone }) {
  const [seed, setSeed] = useState('Write a function to reverse a singly linked list.');
  const [domain, setDomain] = useState('programming');
  const [count, setCount] = useState(3);
  const [domains, setDomains] = useState([]);
  const [regen, setRegen] = useState(true);

  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    api.domains().then(setDomains).catch(() => {});
  }, []);

  useEffect(() => () => clearInterval(timer.current), []);

  async function run() {
    setRunning(true);
    setError(null);
    setResult(null);
    setElapsed(0);
    timer.current = setInterval(() => setElapsed((e) => e + 1), 1000);

    try {
      const data = await api.generateAndVerify({
        seed_question: seed,
        domain,
        count: Number(count),
        enable_regeneration: regen,
        persist: true,
      });
      setResult(data);
      onDone?.();
    } catch (e) {
      setError(e.message);
    } finally {
      clearInterval(timer.current);
      setRunning(false);
    }
  }

  const ollamaReady = health?.ollama?.reachable && health?.ollama?.model_available;

  return (
    <>
      <div className="panel">
        <h2>1 · Enter a seed question</h2>
        <label htmlFor="seed">Seed question</label>
        <textarea id="seed" value={seed} onChange={(e) => setSeed(e.target.value)} />

        <div className="row" style={{ marginTop: 14 }}>
          <div>
            <label htmlFor="domain">Domain</label>
            <select id="domain" value={domain} onChange={(e) => setDomain(e.target.value)}>
              {domains.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="count">Variations</label>
            <input
              id="count" type="number" min="1" max="15"
              value={count} onChange={(e) => setCount(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="regen">Regeneration</label>
            <select id="regen" value={regen ? 'on' : 'off'} onChange={(e) => setRegen(e.target.value === 'on')}>
              <option value="on">On (retry rejects)</option>
              <option value="off">Off</option>
            </select>
          </div>
          <button className="primary" onClick={run} disabled={running || seed.trim().length < 5}>
            {running ? <><span className="spinner" /> Running…</> : 'Generate & Verify'}
          </button>
        </div>

        {domains.length > 0 && (
          <div className="examples">
            <span>Try:</span>
            {domains.slice(0, 5).map((d) => (
              <button
                key={d.id} className="chip"
                onClick={() => { setSeed(d.example_seed); setDomain(d.id); }}
              >
                {d.label}
              </button>
            ))}
          </div>
        )}

        {!ollamaReady && health && (
          <div className="notice" style={{ marginTop: 14 }}>
            Ollama is not ready ({health.ollama?.detail}). Generation needs it. Start it with{' '}
            <code>ollama serve</code> and pull the model with{' '}
            <code>ollama pull {health.ollama?.model}</code>. The PS2 Verifier tab works regardless.
          </div>
        )}

        <PipelineProgress active={running} elapsed={elapsed} />
      </div>

      {error && <div className="error">{error}</div>}

      {result?.warnings?.length > 0 && (
        <div className="notice">
          {result.warnings.map((w, i) => <div key={i}>{w}</div>)}
        </div>
      )}

      {result && (
        <>
          <div className="panel">
            <h2>2 · Pipeline result</h2>
            <div className="tiles">
              <div className="tile"><div className="k">Generated</div><div className="v">{result.summary.generated}</div></div>
              <div className="tile pass"><div className="k">Passed</div><div className="v">{result.summary.passed}</div></div>
              <div className="tile review"><div className="k">Review</div><div className="v">{result.summary.review}</div></div>
              <div className="tile reject"><div className="k">Rejected</div><div className="v">{result.summary.rejected}</div></div>
              <div className="tile"><div className="k">Duplicate rate</div><div className="v">{(result.summary.duplicate_rate * 100).toFixed(0)}%</div></div>
              <div className="tile"><div className="k">Mean reliability</div><div className="v">{result.summary.mean_reliability_score.toFixed(2)}</div></div>
              <div className="tile"><div className="k">Regenerations</div><div className="v">{result.summary.regeneration_attempts}</div></div>
              <div className="tile"><div className="k">Flagged spans</div><div className="v">{result.summary.flagged_span_count}</div></div>
            </div>

            {result.seed_metadata && (
              <details style={{ marginTop: 14 }}>
                <summary>Seed analysis — what PS8 extracted</summary>
                <div className="table-wrap">
                  <table>
                    <tbody>
                      <tr><th>Domain</th><td>{result.seed_metadata.domain}</td></tr>
                      <tr><th>Topic</th><td>{result.seed_metadata.topic}</td></tr>
                      <tr><th>Core concept</th><td>{result.seed_metadata.core_concept}</td></tr>
                      <tr><th>Question type</th><td>{result.seed_metadata.question_type}</td></tr>
                      <tr><th>Difficulty</th><td>{result.seed_metadata.difficulty} ({result.seed_metadata.difficulty_score})</td></tr>
                      <tr><th>Learning objective</th><td>{result.seed_metadata.learning_objective}</td></tr>
                    </tbody>
                  </table>
                </div>
              </details>
            )}

            <details style={{ marginTop: 10 }}>
              <summary>Measured stage timings</summary>
              <div className="table-wrap">
                <table>
                  <tbody>
                    {Object.entries(result.timings_ms).map(([k, v]) => (
                      <tr key={k}><th>{k}</th><td className="mono">{Math.round(v)} ms</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </div>

          <h2 style={{ fontSize: 17, margin: '22px 0 12px' }}>
            3 · Candidates — each judged by both gates
          </h2>
          {result.results.map((item, i) => (
            <CandidateCard key={item.candidate.id} item={item} index={i} />
          ))}
        </>
      )}
    </>
  );
}

/* ==================================================================== */
/* Tab 2 — standalone PS2 verifier                                       */
/* ==================================================================== */
function VerifyTab() {
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
                <span className="num" style={{ fontSize: 11 }}>
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

/* ==================================================================== */
/* Tab 3 — accepted question bank                                        */
/* ==================================================================== */
function BankTab() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api.questions().then(setData).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  return (
    <div className="panel">
      <div className="flex" style={{ justifyContent: 'space-between', marginBottom: 14 }}>
        <h2 style={{ margin: 0 }}>Accepted question bank ({data?.count ?? 0})</h2>
        <div className="flex">
          <button className="ghost" onClick={load}>Refresh</button>
          <a href={api.exportUrl('json')} target="_blank" rel="noreferrer">
            <button className="ghost">Export JSON</button>
          </a>
          <a href={api.exportUrl('csv')}>
            <button className="ghost">Export CSV</button>
          </a>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {!data?.questions?.length ? (
        <div className="empty">
          No accepted questions yet. Run the pipeline on the first tab — questions that
          clear both gates land here.
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Question</th><th>Strategy</th><th>Difficulty</th>
                <th>Reliability</th><th>Verdict</th>
              </tr>
            </thead>
            <tbody>
              {[...data.questions].reverse().map((q) => (
                <tr key={q.id}>
                  <td>{q.question}</td>
                  <td>{q.variation_strategy}</td>
                  <td>{q.difficulty}</td>
                  <td className="mono">{q.reliability_score?.toFixed(3) ?? '—'}</td>
                  <td>
                    {q.verdict
                      ? <span className={`verdict ${q.verdict}`}>{q.verdict.replace(/_/g, ' ')}</span>
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ==================================================================== */
/* Tab 4 — human review queue                                            */
/* ==================================================================== */
function ReviewTab() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api.reviewQueue().then(setData).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  return (
    <div className="panel">
      <div className="flex" style={{ justifyContent: 'space-between', marginBottom: 14 }}>
        <h2 style={{ margin: 0 }}>Review queue ({data?.count ?? 0})</h2>
        <button className="ghost" onClick={load}>Refresh</button>
      </div>

      <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 0 }}>
        Candidates the system could not confirm either way — an incomplete corpus is not
        proof a claim is wrong, so these are routed to a human instead of being discarded.
      </p>

      {error && <div className="error">{error}</div>}

      {!data?.items?.length ? (
        <div className="empty">Review queue is empty.</div>
      ) : (
        [...data.items].reverse().map((item) => (
          <div className="card REVIEW" key={item.id}>
            <div className="card-head">
              <div className="idx">{item.variation_strategy} · {item.difficulty}</div>
              <span className="badge REVIEW">REVIEW</span>
            </div>
            <div className="question">{item.question}</div>
            <div className="answer">
              <div className="lbl">Answer key</div>
              {item.answer_key || <em>missing</em>}
            </div>
            {item.review_reasons?.length > 0 && (
              <ul className="reasons">
                {item.review_reasons.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            )}
            {item.flagged_spans?.length > 0 && <FlaggedSpans spans={item.flagged_spans} />}
          </div>
        ))
      )}
    </div>
  );
}
