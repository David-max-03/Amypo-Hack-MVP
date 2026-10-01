import { useState } from 'react';
import HealthBar from './components/HealthBar.jsx';
import BankPage from './pages/Bank.jsx';
import DashboardPage from './pages/Dashboard.jsx';
import GeneratePage from './pages/Generate.jsx';
import ReportsPage from './pages/Reports.jsx';
import ReviewPage from './pages/Review.jsx';
import VerifierPage from './pages/Verifier.jsx';
import { AppDataProvider, useAppData } from './state/AppData.jsx';

const NAV = [
  ['dashboard', 'Dashboard'],
  ['generate', 'Generate & Verify'],
  ['verify', 'PS2 Verifier'],
  ['bank', 'Question Bank'],
  ['review', 'Review Queue'],
  ['reports', 'Reports'],
];

function Shell() {
  const { health, healthError, job, jobRunning, taxonomyError } = useAppData();
  const [page, setPage] = useState('dashboard');
  const title = NAV.find(([id]) => id === page)?.[1];

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">CT</div>
          <div>
            <div className="brand-name">Question Trust</div>
            <div className="brand-sub">PS8 × PS2 pipeline</div>
          </div>
        </div>
        <nav aria-label="Sections">
          <ul className="nav">
            {NAV.map(([id, label]) => {
              const count = id === 'bank' ? health?.storage?.accepted_questions
                : id === 'review' ? health?.storage?.review_queue : undefined;
              return (
                <li key={id}>
                  <button className={`nav-item ${page === id ? 'active' : ''}`}
                    aria-current={page === id ? 'page' : undefined} onClick={() => setPage(id)}>
                    <span>{label}</span>
                    {id === 'generate' && jobRunning && <span className="live" aria-label="job running" />}
                    {typeof count === 'number' && (
                      <span className={`count ${id === 'review' && count > 0 ? 'attn' : ''}`}>{count}</span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
        {jobRunning && (
          <button className="job-chip" onClick={() => setPage('generate')}>
            <span className="ai-dot" aria-hidden="true" />
            <span>{job.demo ? 'DEMO job' : 'Job'} running · {job.generated_count}/{job.requested_count}</span>
          </button>
        )}
        <div className="sidebar-foot">HackWithAMYPO 2026 · Code Titans<br />Ashadavid S J &amp; Dinesh A</div>
      </aside>

      <main className="main">
        <header className="topbar">
          <h1>{title}</h1>
          <HealthBar health={health} error={healthError} />
        </header>
        {taxonomyError && <div className="error">Could not load the domain / difficulty configuration: {taxonomyError}</div>}
        {page === 'dashboard' && <DashboardPage go={setPage} />}
        {page === 'generate' && <GeneratePage onOpenBank={() => setPage('bank')} />}
        {page === 'verify' && <VerifierPage />}
        {page === 'bank' && <BankPage />}
        {page === 'review' && <ReviewPage />}
        {page === 'reports' && <ReportsPage />}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AppDataProvider>
      <Shell />
    </AppDataProvider>
  );
}
