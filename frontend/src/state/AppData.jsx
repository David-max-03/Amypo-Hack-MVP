import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api } from '../api.js';

/**
 * App-level state that must outlive any single page:
 *  - the shared taxonomy (the ONE domain / difficulty configuration, from the backend)
 *  - backend health
 *  - the active generation job
 *
 * The job itself runs on the backend (POST /jobs). This provider only remembers its id
 * and polls GET /jobs/{id}; it sits above every page, so navigating between pages never
 * stops polling, and the id is remembered across a page reload.
 */
const AppDataContext = createContext(null);
const JOB_KEY = 'amypo.activeJobId';
const TERMINAL = new Set(['completed', 'failed']);

function readStoredJobId() {
  try { return window.localStorage.getItem(JOB_KEY); } catch { return null; }
}
function storeJobId(id) {
  try {
    if (id) window.localStorage.setItem(JOB_KEY, id);
    else window.localStorage.removeItem(JOB_KEY);
  } catch { /* storage unavailable (private mode): the job still runs, only reload-resume is lost */ }
}

export function AppDataProvider({ children }) {
  const [taxonomy, setTaxonomy] = useState(null);
  const [taxonomyError, setTaxonomyError] = useState(null);
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);
  const [jobId, setJobId] = useState(readStoredJobId);
  const [job, setJob] = useState(null);
  const [jobError, setJobError] = useState(null);
  const pollRef = useRef(null);

  const refreshHealth = useCallback(() => {
    api.health().then((h) => { setHealth(h); setHealthError(null); }).catch((e) => setHealthError(e.message));
  }, []);

  useEffect(() => {
    api.taxonomy().then(setTaxonomy).catch((e) => setTaxonomyError(e.message));
    refreshHealth();
    const t = setInterval(refreshHealth, 15000);
    return () => clearInterval(t);
  }, [refreshHealth]);

  // Poll the active job until it reaches a terminal state - independent of the page shown.
  useEffect(() => {
    clearInterval(pollRef.current);
    if (!jobId) { setJob(null); return undefined; }
    let cancelled = false;
    const tick = () => {
      api.job(jobId)
        .then((j) => {
          if (cancelled) return;
          setJob(j);
          setJobError(null);
          if (TERMINAL.has(j.status)) {
            clearInterval(pollRef.current);
            refreshHealth();
          }
        })
        .catch((e) => {
          if (cancelled) return;
          // 404: the backend restarted and forgot the job - stop tracking it.
          if (/No job/.test(e.message)) { setJobId(null); storeJobId(null); }
          setJobError(e.message);
        });
    };
    tick();
    pollRef.current = setInterval(tick, 1500);
    return () => { cancelled = true; clearInterval(pollRef.current); };
  }, [jobId, refreshHealth]);

  const track = useCallback((started) => {
    setJob(started);
    setJobId(started.job_id);
    storeJobId(started.job_id);
    return started;
  }, []);

  const startJob = useCallback((payload) => api.startJob(payload).then(track), [track]);
  const startDemoJob = useCallback(() => api.startDemoJob().then(track), [track]);
  const clearJob = useCallback(() => { setJobId(null); storeJobId(null); setJob(null); }, []);

  const value = {
    taxonomy, taxonomyError, health, healthError, refreshHealth,
    job, jobError, jobRunning: !!job && !TERMINAL.has(job.status),
    startJob, startDemoJob, clearJob,
  };
  return <AppDataContext.Provider value={value}>{children}</AppDataContext.Provider>;
}

export function useAppData() {
  const ctx = useContext(AppDataContext);
  if (!ctx) throw new Error('useAppData must be used inside <AppDataProvider>');
  return ctx;
}

/* ---- shared taxonomy helpers: every page matches records the same way ---- */

/** The subject area a stored record / job result belongs to. Records made before
 *  subject areas existed fall back to their pipeline domain ("programming" etc.). */
export function areaOf(record) {
  if (!record) return null;
  if (record.subject_area) return record.subject_area;
  const domain = record.domain ?? record.candidate?.domain;
  return domain || null;
}

export function difficultyOf(record) {
  return record?.difficulty_label ?? record?.difficulty ?? record?.candidate?.difficulty ?? null;
}

export function matchesFilters(record, { area, difficulty }) {
  if (area && areaOf(record) !== area) return false;
  if (difficulty && difficultyOf(record) !== difficulty) return false;
  return true;
}

export function areaLabel(taxonomy, id) {
  return taxonomy?.subject_areas?.find((a) => a.id === id)?.label ?? id ?? '—';
}
