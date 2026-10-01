import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import { AttemptTimeline } from '../components/CandidateCard.jsx';
import TaxonomyFilters from '../components/TaxonomyFilters.jsx';
import ValidationReport from '../components/ValidationReport.jsx';
import { areaLabel, areaOf, matchesFilters, useAppData } from '../state/AppData.jsx';

export default function ReportsPage() {
  const { taxonomy } = useAppData();
  const [tf, setTf] = useState({ area: '', difficulty: '' });
  const [decision, setDecision] = useState('');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    setError(null);
    api.validationReports().then(setData).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const allReports = [...(data?.reports || [])].reverse();
  const reports = allReports.filter((r) => matchesFilters(r, tf) && (!decision || r.decision === decision));
  const tally = reports.reduce((acc, r) => ({ ...acc, [r.decision]: (acc[r.decision] || 0) + 1 }), {});

  return (
    <div className="panel" data-testid="reports">
      <div className="toolbar">
        <h2>Validation reports <span className="status-pill">{data?.count ?? 0}</span></h2>
        <div className="actions"><button className="ghost" onClick={load}>Refresh</button></div>
      </div>
      <p className="lede">
        Every decision the pipeline made, newest first — the six PS8 structural checks, the six PS2
        reliability signals and the resulting PASS / REVIEW / REJECT.
      </p>
      <div className="filters filters-3">
        <TaxonomyFilters idPrefix="rep" value={tf} onChange={setTf} />
        <div>
          <label htmlFor="rep-decision">Decision</label>
          <select id="rep-decision" value={decision} onChange={(e) => setDecision(e.target.value)}>
            <option value="">All decisions</option><option>PASS</option><option>REVIEW</option><option>REJECT</option>
          </select>
        </div>
      </div>
      <p className="lede" style={{ marginTop: 0 }}>
        Showing {reports.length} of {allReports.length}. Reports recorded before domains and difficulty
        were stored only appear under "All domains" / "All difficulties".
      </p>
      {reports.length > 0 && (
        <div className="summary-row" aria-label="Decisions in these reports">
          {['PASS', 'REVIEW', 'REJECT'].map((d) => (
            <span key={d} className={`badge ${d}`}>{d} · {tally[d] || 0}</span>
          ))}
        </div>
      )}
      {error && <div className="error">{error}</div>}
      {!reports.length ? (
        <div className="empty">No reports yet — every candidate the pipeline decides gets one.</div>
      ) : reports.map((r) => (
        <div className={`card ${r.decision}`} key={`${r.candidate_id}-${r.created_at}`}>
          <div className="card-head">
            <div>
              <div className="idx">{r.candidate_id} · {r.created_at?.replace('T', ' ').slice(0, 19)} · attempts {r.attempts}</div>
              <div className="meta" style={{ marginTop: 6 }}>
                {areaOf(r) && <span className="tag">{areaLabel(taxonomy, areaOf(r))}</span>}
                {r.difficulty && <span className="tag">{r.difficulty}</span>}
                {r.variation_strategy && <span className="tag ps8">{r.variation_strategy}</span>}
                {r.solution_method && <span className="tag ps8">method: {r.solution_method}</span>}
              </div>
            </div>
            <span className={`badge ${r.decision}`}>{r.decision}</span>
          </div>
          <div className="question">{r.question}</div>
          <AttemptTimeline history={r.regeneration_history} finalDecision={r.decision} attempts={r.attempts} />
          <ValidationReport sv={r.structural_validation} rv={r.reliability_verification}
            decision={r.decision} decisionReasons={r.decision_reasons || []} />
        </div>
      ))}
    </div>
  );
}
