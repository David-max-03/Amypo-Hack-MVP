import { useEffect, useState } from 'react';
import HealthBar from './components/HealthBar.jsx';
import Icon from './components/Icon.jsx';
import { ToastProvider } from './components/Toast.jsx';
import BankPage from './pages/Bank.jsx';
import GeneratePage from './pages/Generate.jsx';
import ReportsPage from './pages/Reports.jsx';
import ReviewPage from './pages/Review.jsx';
import VerifierPage from './pages/Verifier.jsx';
import { AppDataProvider, useAppData } from './state/AppData.jsx';

// The three sections of the design, then the two working tools that support them.
const PRIMARY = [
  ['generate', 'Generate', 'generate'],
  ['bank', 'Question Bank', 'bank'],
  ['reports', 'Reports', 'reports'],
];
const SECONDARY = [
  ['verify', 'PS2 Verifier', 'verify'],
  ['review', 'Review Queue', 'review'],
];

function Logo() {
  return (
    <span className="logo">
      <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
        <rect width="28" height="28" rx="7" fill="#090D0B" />
        <path d="M14 6l7 16h-3.4l-1.3-3.2h-4.6L10.4 22H7l7-16z" fill="#fff" />
        <path d="M14 12.2l1.5 3.9h-3L14 12.2z" fill="#16A34A" />
      </svg>
      <span className="logo-name">Amypo</span>
    </span>
  );
}

function Shell() {
  const { health, healthError, job, jobRunning, taxonomyError } = useAppData();
  const [page, setPage] = useState('generate');
  const [open, setOpen] = useState(false);   // pinned open (desktop) / drawer open (mobile)

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const go = (id) => { setPage(id); setOpen(false); };

  const item = ([id, label, icon]) => {
    const count = id === 'bank' ? health?.storage?.accepted_questions
      : id === 'review' ? health?.storage?.review_queue : undefined;
    return (
      <li key={id} className={page === id ? 'on' : undefined}>
        <button className={`rail-item ${page === id ? 'active' : ''}`} aria-current={page === id ? 'page' : undefined}
          onClick={() => go(id)} title={label}>
          <span className="rail-icon">
            <Icon name={icon} size={20} />
            {id === 'generate' && jobRunning && <span className="live-dot" aria-hidden="true" />}
          </span>
          <span className="rail-label">{label}</span>
          {typeof count === 'number' && (
            <span className={`rail-count ${id === 'review' && count > 0 ? 'attn' : ''}`} aria-label={`${count} items`}>{count}</span>
          )}
        </button>
      </li>
    );
  };

  return (
    <div className={`shell ${open ? 'nav-open' : ''}`}>
      <header className="appbar">
        <button className="icon-btn" onClick={() => setOpen((v) => !v)} aria-label={open ? 'Collapse navigation' : 'Expand navigation'}
          aria-expanded={open} aria-controls="app-nav">
          <Icon name={open ? 'close' : 'menu'} size={20} />
        </button>
        <Logo />
        <div className="appbar-right">
          {jobRunning && (
            <button className="job-indicator" onClick={() => go('generate')} data-testid="job-indicator"
              title="Go to the running generation job">
              <span className="pulse" aria-hidden="true" />
              <span><span className="ji-long">{job.demo ? 'Demo' : 'Generation'} running · </span>{job.generated_count}/{job.requested_count}</span>
            </button>
          )}
          <HealthBar health={health} error={healthError} />
        </div>
      </header>

      <nav id="app-nav" className="rail" aria-label="Sections">
        <ul>{PRIMARY.map(item)}</ul>
        <div className="rail-sep" role="presentation" />
        <ul>{SECONDARY.map(item)}</ul>
        <div className="rail-foot"><Icon name="bolt" size={18} /><span className="rail-label">PS8 × PS2 · Code Titans</span></div>
      </nav>
      <div className="scrim" onClick={() => setOpen(false)} aria-hidden="true" />

      <main className="content" id="main">
        {taxonomyError && <div className="error">Could not load the domain / difficulty configuration: {taxonomyError}</div>}
        {page === 'generate' && <GeneratePage onOpenBank={() => go('bank')} onOpenReview={() => go('review')} />}
        {page === 'bank' && <BankPage onGenerate={() => go('generate')} />}
        {page === 'reports' && <ReportsPage onGenerate={() => go('generate')} />}
        {page === 'verify' && <VerifierPage />}
        {page === 'review' && <ReviewPage />}
      </main>
    </div>
  );
}

export default function App({ pollMs }) {
  return (
    <ToastProvider>
      <AppDataProvider pollMs={pollMs}>
        <Shell />
      </AppDataProvider>
    </ToastProvider>
  );
}
