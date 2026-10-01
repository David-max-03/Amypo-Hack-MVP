import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import { AttemptTimeline, EvidenceTable, RegenerationDetail } from '../components/CandidateCard.jsx';
import FlaggedSpans from '../components/FlaggedSpans.jsx';
import ScoreBar from '../components/ScoreBar.jsx';
import TaxonomyFilters from '../components/TaxonomyFilters.jsx';
import { areaLabel, areaOf, matchesFilters, useAppData } from '../state/AppData.jsx';

export default function ReviewPage() {
  const { taxonomy, refreshHealth } = useAppData();
  const [tf, setTf] = useState({ area: '', difficulty: '' });
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [notes, setNotes] = useState({});
  const [busy, setBusy] = useState(null);
  const [message, setMessage] = useState(null);

  const load = useCallback(() => {
    setError(null);
    api.reviewQueue().then(setData).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  async function act(item, action) {
    setBusy(item.id);
    setMessage(null);
    try {
      await (action === 'approve' ? api.approveReview : api.rejectReview)(item.id, notes[item.id]);
      setMessage(action === 'approve'
        ? `Approved — "${item.question.slice(0, 70)}…" moved to the Question Bank.`
        : `Rejected — "${item.question.slice(0, 70)}…" removed from the queue.`);
      load();
      refreshHealth();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="panel" data-testid="review">
      <div className="toolbar">
        <h2>Review queue <span className="status-pill">{data?.count ?? 0} waiting</span></h2>
        <div className="actions"><button className="ghost" onClick={load}>Refresh</button></div>
      </div>

      <p className="lede">
        Candidates the system could not confirm either way — an incomplete corpus is not proof a
        claim is wrong, so these are routed to a human instead of being discarded. Approve moves a
        question into the bank; reject records the decision.
      </p>

      <div className="filters filters-2">
        <TaxonomyFilters idPrefix="rev" value={tf} onChange={setTf} />
      </div>

      {message && <div className="notice ok" role="status">{message}</div>}
      {error && <div className="error">{error}</div>}

      {!data?.items?.length ? (
        <div className="empty">Review queue is empty.</div>
      ) : (
        [...data.items].reverse().filter((it) => matchesFilters(it, tf)).map((item) => (
          <div className="card REVIEW" key={item.id} data-testid="review-item">
            <div className="card-head">
              <div>
                <div className="idx">{item.id} · {(item.attempts ?? 1) > 1 ? `${item.attempts} attempts` : 'first attempt'}</div>
                <div className="meta" style={{ marginTop: 6 }}>
                  <span className="tag ps8">{item.strategy_label || item.variation_strategy}</span>
                  {item.solution_method && <span className="tag ps8">method: {item.solution_method}</span>}
                  <span className="tag">{item.difficulty}</span>
                  <span className="tag">{areaLabel(taxonomy, areaOf(item))}</span>
                </div>
              </div>
              <span className="badge lg REVIEW">REVIEW</span>
            </div>

            <AttemptTimeline history={item.regeneration_history} finalDecision="REVIEW" attempts={item.attempts ?? 1} />
            <div className="question">{item.question}</div>
            <details>
              <summary>Answer key</summary>
              <pre className="answer mono" style={{ whiteSpace: 'pre-wrap' }}>{item.answer_key || 'missing'}</pre>
            </details>

            <div className="reject-box REVIEW">
              <b>Reason for review</b>
              <ul className="reasons">
                {[...(item.review_reasons || []), ...(item.structural_reasons || [])].map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </div>

            {typeof item.reliability_score === 'number' ? (
              <div className="gates" style={{ marginTop: 12 }}>
                <div className="gate ps2">
                  <ScoreBar label="PS2 reliability score" value={item.reliability_score} />
                  <ScoreBar label="Hallucination probability" value={item.hallucination_probability} invert />
                  <div className="verdict-line">PS2 verdict: <span className={`verdict ${item.verdict}`}>{item.verdict?.replace(/_/g, ' ')}</span></div>
                </div>
              </div>
            ) : (
              <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 12 }}>
                No PS2 score — PS8 structural validation failed on the final attempt.
              </div>
            )}

            {item.flagged_spans?.length > 0 && (
              <section className="spans-panel" aria-label="Flagged spans">
                <h4>{item.flagged_spans.length} flagged span(s) — why PS2 raised them</h4>
                <FlaggedSpans spans={item.flagged_spans} />
              </section>
            )}
            {item.evidence?.length > 0 && (
              <details><summary>Evidence ({item.evidence.length} claim checks)</summary><EvidenceTable evidence={item.evidence} /></details>
            )}
            {item.regeneration_history?.length > 0 && (
              <details>
                <summary>Rejected attempts in full ({item.regeneration_history.length})</summary>
                <RegenerationDetail history={item.regeneration_history} />
              </details>
            )}

            <div className="review-actions">
              <input placeholder="Reviewer note (optional)" aria-label="Reviewer note" value={notes[item.id] || ''}
                onChange={(e) => setNotes({ ...notes, [item.id]: e.target.value })} />
              <button className="approve" disabled={busy === item.id} onClick={() => act(item, 'approve')}>Approve → bank</button>
              <button className="reject" disabled={busy === item.id} onClick={() => act(item, 'reject')}>Reject</button>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
