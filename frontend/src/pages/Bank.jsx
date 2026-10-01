import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import ScoreBar from '../components/ScoreBar.jsx';
import TaxonomyFilters from '../components/TaxonomyFilters.jsx';
import { areaLabel, areaOf, matchesFilters, useAppData } from '../state/AppData.jsx';

const uniq = (xs) => [...new Set(xs.filter(Boolean))].sort();

export default function BankPage() {
  const { taxonomy } = useAppData();
  const [tf, setTf] = useState({ area: '', difficulty: '' });
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [q, setQ] = useState('');
  const [f, setF] = useState({ strategy: '', method: '' });

  const load = useCallback(() => {
    setError(null);
    api.questions().then(setData).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const all = data?.questions || [];
  const opts = {
    strategy: uniq(all.map((x) => x.variation_strategy)),
    method: uniq(all.map((x) => x.solution_method)),
  };
  const needle = q.trim().toLowerCase();
  const rows = [...all].reverse().filter((x) =>
    (!needle || `${x.question} ${x.answer_key} ${x.topic}`.toLowerCase().includes(needle)) &&
    matchesFilters(x, tf) &&
    (!f.strategy || x.variation_strategy === f.strategy) &&
    (!f.method || x.solution_method === f.method));

  const select = (key, label) => (
    <div>
      <label htmlFor={`f-${key}`}>{label}</label>
      <select id={`f-${key}`} value={f[key]} onChange={(e) => setF({ ...f, [key]: e.target.value })}>
        <option value="">All</option>
        {opts[key].map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  );

  return (
    <div className="panel" data-testid="bank">
      <div className="toolbar">
        <h2>Question bank <span className="status-pill">{rows.length} of {all.length}</span></h2>
        <div className="actions">
          <button className="ghost" onClick={load}>Refresh</button>
          <a href={api.exportUrl('json')} target="_blank" rel="noreferrer"><button className="ghost">Export JSON</button></a>
          <a href={api.exportUrl('csv')}><button className="ghost">Export CSV</button></a>
        </div>
      </div>

      <p className="lede">
        Questions that cleared both gates, plus any a reviewer approved. Filter, then export the
        whole bank as JSON or CSV.
      </p>

      <div className="filters">
        <div>
          <label htmlFor="f-search">Search</label>
          <input id="f-search" placeholder="question, answer or topic…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <TaxonomyFilters idPrefix="bank" value={tf} onChange={setTf} />
        {select('strategy', 'Strategy')}
        {select('method', 'Solution method')}
      </div>

      {error && <div className="error">{error}</div>}

      {!all.length ? (
        <div className="empty">
          No accepted questions yet. Run the pipeline on the first tab — questions that clear both
          gates (or that a reviewer approves) land here.
        </div>
      ) : !rows.length ? (
        <div className="empty">No questions match these filters.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Question</th><th>Domain</th><th>Difficulty</th><th>Strategy</th><th>Method</th>
                <th>Reliability</th><th>Verdict</th><th>Validation status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((x) => (
                <tr key={x.id} data-testid="bank-row">
                  <td>
                    {x.question}
                    <details><summary style={{ fontSize: 12 }}>answer key</summary>
                      <pre className="mono" style={{ whiteSpace: 'pre-wrap', fontSize: 12 }}>{x.answer_key}</pre>
                    </details>
                  </td>
                  <td>{areaLabel(taxonomy, areaOf(x))}</td>
                  <td>{x.difficulty}{typeof x.difficulty_score === 'number' ? ` (${x.difficulty_score.toFixed(2)})` : ''}</td>
                  <td>{x.variation_strategy}</td>
                  <td>{x.solution_method || '—'}</td>
                  <td style={{ minWidth: 120 }}>
                    {typeof x.reliability_score === 'number' ? <ScoreBar label="" value={x.reliability_score} /> : '—'}
                  </td>
                  <td>{x.verdict ? <span className={`verdict ${x.verdict}`}>{x.verdict.replace(/_/g, ' ')}</span> : '—'}</td>
                  <td>
                    <span className={`status-pill ${/human/.test(x.validation_status || '') ? 'human' : 'ok'}`}>
                      {x.validation_status || (x.decision === 'PASS' ? 'passed both gates' : x.decision)}
                    </span>
                    {x.attempts > 1 && <div style={{ fontSize: 12, color: 'var(--dim)', marginTop: 4 }}>{x.attempts} attempts</div>}
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
