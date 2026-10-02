import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import { AttemptTimeline, DecisionBadge, EvidenceTable, RegenerationDetail } from '../components/CandidateCard.jsx';
import Icon from '../components/Icon.jsx';
import PageHeader, { Skeleton, StateBlock } from '../components/PageHeader.jsx';
import TaxonomyFilters from '../components/TaxonomyFilters.jsx';
import ValidationReport, { GateGrid, gateChecks, tally } from '../components/ValidationReport.jsx';
import { areaLabel, areaOf, matchesFilters, useAppData } from '../state/AppData.jsx';

const TIMES = [['', 'All time'], ['1', 'Last hour'], ['24', 'Last 24 hours'], ['168', 'Last 7 days']];
const STAT = {
  PASS: { icon: 'check-circle', note: 'Passed both gates' },
  REVIEW: { icon: 'alert', note: 'Needs human inspection' },
  REJECT: { icon: 'x-circle', note: 'Discarded after retries' },
};

export function timeAgo(iso, now = Date.now()) {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m} minute${m === 1 ? '' : 's'} ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? '' : 's'} ago`;
  const d = Math.round(h / 24);
  return `${d} day${d === 1 ? '' : 's'} ago`;
}

const short = (s, n = 48) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s);

function gateSummary(r, ps8, ps2) {
  const a = tally(ps8); const b = tally(ps2);
  if (!r.structural_validation) return ['na', 'Checks not recorded'];
  if (a.passed < a.total) return ['REJECT', r.attempts > 1 ? 'PS8 failed · retried' : 'PS8 failed'];
  if (b.total && b.passed < b.total) return [r.decision === 'PASS' ? 'PASS' : 'REVIEW', r.decision === 'PASS' ? 'Passed with minor PS2 flags' : 'PS2 review flagged'];
  return ['PASS', 'All gates satisfied'];
}

function ReportCard({ r, taxonomy }) {
  const { ps8, ps2 } = gateChecks(r.structural_validation, r.reliability_verification);
  const [tone, label] = gateSummary(r, ps8, ps2);
  // The backend prefixes its reasons with the decision; the box already says which it is.
  const reasons = (r.decision_reasons || []).map((x) => x.replace(/^(REVIEW|REJECT|PASS):\s*/, ''));
  const history = r.regeneration_history || [];
  return (
    <article className={`report-card ${r.decision}`} data-testid="report-card">
      <header className="report-head">
        <div className="report-id">
          <DecisionBadge decision={r.decision} />
          <span className="mono qid">#{r.candidate_id}</span>
          <span className="when"><Icon name="clock" size={14} /><time dateTime={r.created_at} title={r.created_at ? new Date(r.created_at).toLocaleString() : ''}>{timeAgo(r.created_at)}</time></span>
        </div>
        <span className="seed-chip mono" title={r.seed_question || 'seed not recorded for this report'}>
          Seed: {r.seed_question ? short(r.seed_question) : 'not recorded'}
        </span>
      </header>
      <div className="report-body">
        <p className="report-q">{r.question}</p>
        <div className="cand-chips">
          {areaOf(r) && <span className="chip-static">{areaLabel(taxonomy, areaOf(r))}</span>}
          {r.difficulty && <span className={`difficulty ${r.difficulty}`}>{r.difficulty}</span>}
          {r.variation_strategy && <span className="chip-static">{r.variation_strategy}</span>}
          {r.solution_method && <span className="chip-static">method: {r.solution_method}</span>}
          {r.job_id && <span className="chip-static mono" title="generation run">{r.job_id}</span>}
        </div>

        {r.decision !== 'PASS' && reasons.length > 0 && (
          <div className={`reason-box ${r.decision}`}>
            <Icon name={r.decision === 'REJECT' ? 'x-circle' : 'alert'} />
            <div>
              <b>{r.decision === 'REJECT' ? 'Failure reason' : 'Review reason'}: {reasons[0]}</b>
              {reasons.slice(1, 3).map((x, i) => <p key={i}>{x}</p>)}
            </div>
          </div>
        )}

        <div className="gate-box">
          <div className="gate-box-head">
            <span><Icon name="reports" size={16} />PS8 &amp; PS2 gate validation</span>
            <span className={`gate-summary ${tone}`}>{label}</span>
          </div>
          <div className="gate-pair flat">
            <GateGrid engine="ps8" title="Structural checks" checks={ps8} />
            <GateGrid engine="ps2" title="Grounding checks" checks={ps2} />
          </div>
        </div>

        <details className="fold">
          <summary><Icon name="chevron-right" size={16} className="caret" />
            {history.length ? 'View evidence & regeneration history' : 'View evidence & verification checks'}
            <span className={`fold-meta ${history.length && r.decision === 'PASS' ? 'ok' : ''}`}>
              {history.length && r.decision === 'PASS' ? `Recovered in attempt ${r.attempts}` : `Attempt ${r.attempts ?? 1}${history.length ? ` (${history.length} rejected)` : ''}`}
            </span>
          </summary>
          <div className="fold-body">
            <AttemptTimeline history={history} finalDecision={r.decision} attempts={r.attempts} />
            <ValidationReport sv={r.structural_validation} rv={r.reliability_verification}
              decision={r.decision} decisionReasons={reasons} />
            {r.reliability_verification?.evidence?.length > 0 && <EvidenceTable evidence={r.reliability_verification.evidence} />}
            <RegenerationDetail history={history} />
          </div>
        </details>
      </div>
    </article>
  );
}

export default function ReportsPage({ onGenerate }) {
  const { taxonomy, job } = useAppData();
  const [tf, setTf] = useState({ area: '', difficulty: '' });
  const [decision, setDecision] = useState('');
  const [run, setRun] = useState('');
  const [since, setSince] = useState('');
  const [q, setQ] = useState('');
  const [data, setData] = useState(null);
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    const filters = { job_id: run, since_hours: since };
    setError(null);
    setLoading(true);
    Promise.all([api.validationReports(filters), api.reportStats(filters)])
      .then(([reports, s]) => { setData(reports); setStats(s); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [run, since]);
  useEffect(load, [load]);
  // A job that just finished has new reports: refresh the numbers.
  useEffect(() => { if (job && job.status !== 'running' && job.status !== 'queued') load(); }, [job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const needle = q.trim().toLowerCase();
  const scoped = [...(data?.reports || [])].reverse().filter((r) =>
    matchesFilters(r, tf) &&
    (!needle || `${r.candidate_id} ${r.question} ${r.seed_question || ''} ${r.job_id || ''}`.toLowerCase().includes(needle)));
  const reports = scoped.filter((r) => !decision || r.decision === decision);
  const narrowed = needle || tf.area || tf.difficulty;
  // Tab counts: the backend's numbers, unless a client-side search/domain filter narrows the list.
  const tabCount = (d) => (narrowed ? scoped.filter((r) => !d || r.decision === d).length
    : d ? stats?.decisions?.[d]?.count ?? 0 : stats?.total ?? 0);

  return (
    <div data-testid="reports">
      <PageHeader title="Reports" description="Recent validation decisions across generation runs.">
        <button className="btn ghost" onClick={load} disabled={loading}><Icon name="refresh" size={16} />Refresh</button>
      </PageHeader>

      <section className="stat-cards" aria-label="Decision statistics" aria-busy={loading && !stats}>
        {['PASS', 'REVIEW', 'REJECT'].map((d) => (
          <div className={`stat-card ${d}`} key={d} data-testid={`stat-${d}`}>
            <div>
              <div className="stat-card-label"><Icon name={STAT[d].icon} size={16} />{d}</div>
              {stats ? (
                <div className="stat-card-value"><b>{stats.decisions[d].count}</b><span className="mono">{stats.decisions[d].percent.toFixed(1)}%</span></div>
              ) : <Skeleton lines={1} />}
              <div className="stat-card-note">{stats ? `of ${stats.total} stored report${stats.total === 1 ? '' : 's'} • ${STAT[d].note}` : 'Loading…'}</div>
            </div>
            <span className="stat-card-icon" aria-hidden="true"><Icon name={STAT[d].icon} size={22} /></span>
          </div>
        ))}
      </section>

      <section className="panel filter-bar reports-filters" aria-label="Filters">
        <div className="segmented tabs" role="group" aria-label="Decision">
          {[['', 'All'], ['PASS', 'Pass'], ['REVIEW', 'Review'], ['REJECT', 'Reject']].map(([d, label]) => (
            <button key={label} className={decision === d ? 'active' : ''} aria-pressed={decision === d} onClick={() => setDecision(d)}>
              {label} ({tabCount(d)})
            </button>
          ))}
        </div>
        <div className="with-icon">
          <Icon name="layers" size={16} />
          <label htmlFor="rep-run" className="sr-only">Run</label>
          <select id="rep-run" value={run} onChange={(e) => setRun(e.target.value)}>
            <option value="">Run: All runs</option>
            {(stats?.runs || []).map((r) => (
              <option key={r.job_id} value={r.job_id}>{short(r.seed_question || r.job_id, 36)} · {r.reports} · {timeAgo(r.last_at)}</option>
            ))}
          </select>
        </div>
        <div className="with-icon">
          <Icon name="clock" size={16} />
          <label htmlFor="rep-time" className="sr-only">Time range</label>
          <select id="rep-time" value={since} onChange={(e) => setSince(e.target.value)}>
            {TIMES.map(([v, label]) => <option key={label} value={v}>Time: {label}</option>)}
          </select>
        </div>
        <TaxonomyFilters idPrefix="rep" value={tf} onChange={setTf} hideLabel />
        <div className="search">
          <Icon name="search" />
          <label htmlFor="rep-search" className="sr-only">Search reports</label>
          <input id="rep-search" type="search" placeholder="Filter by ID, topic, or seed…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </section>
      {stats?.reports_without_run > 0 && !run && (
        <p className="hint below">{stats.reports_without_run} older report{stats.reports_without_run === 1 ? ' was' : 's were'} stored before runs and seeds were recorded; {stats.reports_without_run === 1 ? 'it appears' : 'they appear'} only under "All runs".</p>
      )}

      {error ? (
        <StateBlock tone="error" title="Could not load reports" action={<button className="btn ghost" onClick={load}>Try again</button>}>{error}</StateBlock>
      ) : loading && !data ? (
        <div data-testid="reports-loading" aria-busy="true" className="report-list">
          {Array.from({ length: 3 }, (_, i) => <div className="report-card skeleton-card" key={i}><Skeleton lines={4} /></div>)}
        </div>
      ) : !reports.length ? (
        <StateBlock title={stats?.total || data?.count ? 'No reports match these filters' : 'No reports yet'}
          action={!data?.count && !run && !since && onGenerate ? <button className="btn primary" onClick={onGenerate}><Icon name="generate" />Go to Generate</button> : undefined}>
          {data?.count ? 'Change the decision, run, time or search filters.' : 'Every candidate the pipeline decides gets a report here.'}
        </StateBlock>
      ) : (
        <div className="report-list">
          {reports.map((r) => <ReportCard key={`${r.candidate_id}-${r.created_at}`} r={r} taxonomy={taxonomy} />)}
        </div>
      )}
    </div>
  );
}
