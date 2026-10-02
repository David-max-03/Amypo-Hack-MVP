import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { DecisionBadge } from '../components/CandidateCard.jsx';
import Icon from '../components/Icon.jsx';
import PageHeader, { Skeleton, StateBlock } from '../components/PageHeader.jsx';
import TaxonomyFilters from '../components/TaxonomyFilters.jsx';
import { areaLabel, areaOf, matchesFilters, useAppData } from '../state/AppData.jsx';

const PAGE_SIZE = 10;
const uniq = (xs) => [...new Set(xs.filter(Boolean))].sort();
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : '—');
const words = (s) => (s ? s.replace(/_/g, ' ') : '—');

function ExportMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (e.key === 'Escape' || (e.type === 'mousedown' && !ref.current?.contains(e.target))) setOpen(false); };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', close);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', close); };
  }, [open]);
  return (
    <div className="menu" ref={ref}>
      <button className="btn primary" aria-haspopup="true" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <Icon name="download" />Export<Icon name="chevron-down" size={16} />
      </button>
      {open && (
        <div className="menu-list">
          <a href={api.exportUrl('json')} target="_blank" rel="noreferrer" onClick={() => setOpen(false)}>JSON — full records</a>
          <a href={api.exportUrl('csv')} onClick={() => setOpen(false)}>CSV — spreadsheet</a>
        </div>
      )}
    </div>
  );
}

export default function BankPage({ onGenerate }) {
  const { taxonomy } = useAppData();
  const [tf, setTf] = useState({ area: '', difficulty: '' });
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [f, setF] = useState({ strategy: '', method: '', status: '', decision: '' });
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState(null);

  const load = useCallback(() => {
    setError(null);
    setLoading(true);
    api.questions().then(setData).catch((e) => setError(e.message)).finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);
  useEffect(() => { setPage(1); }, [q, f, tf]);

  const all = data?.questions || [];
  const opts = {
    strategy: uniq(all.map((x) => x.variation_strategy)),
    method: uniq(all.map((x) => x.solution_method)),
    status: uniq(all.map((x) => x.validation_status)),
    decision: uniq(all.map((x) => x.decision)),
  };
  const needle = q.trim().toLowerCase();
  const rows = [...all].reverse().filter((x) =>
    (!needle || `${x.question} ${x.answer_key} ${x.topic} ${x.id} ${x.solution_method} ${x.variation_strategy}`.toLowerCase().includes(needle)) &&
    matchesFilters(x, tf) &&
    (!f.strategy || x.variation_strategy === f.strategy) &&
    (!f.method || x.solution_method === f.method) &&
    (!f.status || x.validation_status === f.status) &&
    (!f.decision || x.decision === f.decision));
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const current = Math.min(page, pages);
  const shown = rows.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);
  const filtered = needle || tf.area || tf.difficulty || Object.values(f).some(Boolean);
  const clear = () => { setQ(''); setTf({ area: '', difficulty: '' }); setF({ strategy: '', method: '', status: '', decision: '' }); };

  const select = (key, label, all_) => (
    <div>
      <label htmlFor={`f-${key}`} className="sr-only">{label}</label>
      <select id={`f-${key}`} value={f[key]} onChange={(e) => setF({ ...f, [key]: e.target.value })}>
        <option value="">{all_}</option>
        {opts[key].map((o) => <option key={o} value={o}>{cap(words(o))}</option>)}
      </select>
    </div>
  );

  return (
    <div data-testid="bank">
      <PageHeader title="Question Bank" description="Curated collection of questions validated by the trust pipeline.">
        <button className="btn ghost" onClick={load} disabled={loading}><Icon name="refresh" size={16} />Refresh</button>
        <ExportMenu />
      </PageHeader>

      <section className="panel filter-bar" aria-label="Filters">
        <div className="search">
          <Icon name="search" />
          <label htmlFor="f-search" className="sr-only">Search questions</label>
          <input id="f-search" type="search" placeholder="Search questions, tags, methods…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <TaxonomyFilters idPrefix="bank" value={tf} onChange={setTf} hideLabel />
        {select('strategy', 'Strategy', 'All strategies')}
        {select('method', 'Method', 'All methods')}
        {select('status', 'Validation status', 'All validation statuses')}
        {select('decision', 'Decision', 'All decisions')}
      </section>

      {error ? (
        <StateBlock tone="error" title="Could not load the question bank"
          action={<button className="btn ghost" onClick={load}>Try again</button>}>{error}</StateBlock>
      ) : loading && !data ? (
        <section className="panel table-card" data-testid="bank-loading" aria-busy="true">
          {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} lines={2} className="row" />)}
        </section>
      ) : !all.length ? (
        <StateBlock title="No accepted questions yet"
          action={onGenerate && <button className="btn primary" onClick={onGenerate}><Icon name="generate" />Go to Generate</button>}>
          Questions that pass both gates, or that a reviewer approves, are saved here automatically.
        </StateBlock>
      ) : !rows.length ? (
        <StateBlock title="No questions match these filters"
          action={<button className="btn ghost" onClick={clear}>Clear filters</button>} />
      ) : (
        <section className="panel table-card">
          <div className="table-wrap">
            <table className="bank-table">
              <thead>
                <tr>
                  <th scope="col" className="col-num">#</th><th scope="col">Question definition &amp; metadata</th><th scope="col">Domain</th>
                  <th scope="col">Difficulty</th><th scope="col" className="col-strategy">Strategy &amp; method</th><th scope="col">Reliability</th>
                  <th scope="col">Decision</th><th scope="col" className="col-status">Validation status</th><th scope="col">Details</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((x, i) => {
                  const n = (current - 1) * PAGE_SIZE + i + 1;
                  const isOpen = expanded === x.id;
                  const human = /human|approved/i.test(x.validation_status || '');
                  return (
                    <Fragment key={x.id}>
                      <tr data-testid="bank-row" className={isOpen ? 'open' : ''}>
                        <td className="num mono col-num">{String(n).padStart(2, '0')}</td>
                        <td className="qcell">
                          <div className="qtitle">{x.question}</div>
                          <div className="qmeta">
                            <span className="qid mono">{x.id}</span>
                            {x.created_at && <span>{new Date(x.created_at).toLocaleDateString()}</span>}
                            <span>{x.attempts > 1 ? `${x.attempts} attempts` : 'first attempt'}</span>
                          </div>
                        </td>
                        <td data-label="Domain">{areaLabel(taxonomy, areaOf(x))}</td>
                        <td data-label="Difficulty"><span className={`difficulty ${x.difficulty}`}>{cap(x.difficulty)}</span></td>
                        <td className="col-strategy" data-label="Strategy & method"><div><div className="strat">{cap(words(x.variation_strategy))}</div><div className="sub">{cap(words(x.solution_method))}</div></div></td>
                        <td className="rel" data-label="Reliability">
                          {typeof x.reliability_score === 'number' ? (
                            <>
                              <div><b>{x.reliability_score.toFixed(2)}</b> <span className="sub">{words(x.verdict)}</span></div>
                              <div className="bar" aria-hidden="true"><i className={x.reliability_score >= 0.7 ? 'good' : x.reliability_score >= 0.55 ? 'mid' : 'bad'} style={{ width: `${Math.round(x.reliability_score * 100)}%` }} /></div>
                            </>
                          ) : '—'}
                        </td>
                        <td data-label="Decision"><DecisionBadge decision={x.decision} /></td>
                        <td className="col-status" data-label="Validation status"><span className={`status-pill ${human ? 'human' : 'ok'}`}><i className="dot ok" />{human ? 'Approved by reviewer' : 'Verified'}</span></td>
                        <td data-label="Details">
                          <button className="icon-btn bordered" aria-expanded={isOpen} aria-controls={`bank-d-${x.id}`}
                            aria-label={`${isOpen ? 'Hide' : 'Show'} details for question ${n}`} onClick={() => setExpanded(isOpen ? null : x.id)}>
                            <Icon name="chevron-down" size={16} className={isOpen ? 'flip' : ''} />
                          </button>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="detail-row" id={`bank-d-${x.id}`}>
                          <td colSpan={9}>
                            <div className="detail-grid">
                              <div>
                                <span className="eyebrow">Question</span>
                                <p>{x.question}</p>
                                {x.seed_question && (<><span className="eyebrow">Seed</span><p className="sub">{x.seed_question}</p></>)}
                                <span className="eyebrow">Validation</span>
                                <p className="sub">{x.validation_status || '—'} · topic {x.topic || '—'} · {x.question_type || '—'}{x.job_id ? ` · ${x.job_id}` : ''}</p>
                              </div>
                              <div>
                                <span className="eyebrow">Answer key</span>
                                <pre className="answer mono">{x.answer_key || 'missing'}</pre>
                                {x.test_cases?.length > 0 && <p className="sub">{x.test_cases.length} test case(s) stored — included in the export.</p>}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <footer className="table-foot">
            <span>Showing <b>{(current - 1) * PAGE_SIZE + 1}–{(current - 1) * PAGE_SIZE + shown.length}</b> of <b>{rows.length}</b> question{rows.length === 1 ? '' : 's'}{filtered ? ` (filtered from ${all.length})` : ''}</span>
            <nav className="pager" aria-label="Pages">
              <button className="icon-btn" disabled={current === 1} onClick={() => setPage(current - 1)} aria-label="Previous page"><Icon name="chevron-left" size={16} /></button>
              {Array.from({ length: pages }, (_, i) => (
                <button key={i} className={`page-btn ${current === i + 1 ? 'active' : ''}`} aria-current={current === i + 1 ? 'page' : undefined} onClick={() => setPage(i + 1)}>{i + 1}</button>
              ))}
              <button className="icon-btn" disabled={current === pages} onClick={() => setPage(current + 1)} aria-label="Next page"><Icon name="chevron-right" size={16} /></button>
            </nav>
          </footer>
        </section>
      )}
    </div>
  );
}
