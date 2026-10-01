/**
 * Thin API client for the Code Titans backend.
 *
 * Requests go to a relative /api path so Vite's dev proxy handles the origin.
 * Errors are normalised so the UI can always show something meaningful.
 */

const BASE = '/api/v1';

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
  } catch (err) {
    throw new Error(
      `Cannot reach the backend at ${BASE}. Is it running on port 8000? (${err.message})`
    );
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body.detail) {
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      /* response had no JSON body; keep the status line */
    }
    throw new Error(detail);
  }

  return response.json();
}

export const api = {
  health: () => request('/health'),
  domains: () => request('/domains'),
  strategies: () => request('/strategies'),

  generateAndVerify: (payload) =>
    request('/generate-and-verify', { method: 'POST', body: JSON.stringify(payload) }),

  generate: (payload) =>
    request('/generate', { method: 'POST', body: JSON.stringify(payload) }),

  verify: (payload) =>
    request('/verify', { method: 'POST', body: JSON.stringify(payload) }),

  progress: (jobId) => request(`/progress/${encodeURIComponent(jobId)}`),
  taxonomy: () => request('/taxonomy'),
  startJob: (payload) => request('/jobs', { method: 'POST', body: JSON.stringify(payload) }),
  startDemoJob: () => request('/jobs/demo', { method: 'POST' }),
  job: (jobId) => request(`/jobs/${encodeURIComponent(jobId)}`),
  jobs: (limit = 20) => request(`/jobs?limit=${limit}`),
  runDemo: (jobId) => request('/demo/run', { method: 'POST', body: JSON.stringify({ job_id: jobId }) }),

  questions: () => request('/questions?limit=1000'),
  reviewQueue: () => request('/review-queue?limit=1000'),
  approveReview: (id, note) =>
    request(`/review-queue/${encodeURIComponent(id)}/approve`, {
      method: 'POST', body: JSON.stringify({ note: note || null }),
    }),
  rejectReview: (id, note) =>
    request(`/review-queue/${encodeURIComponent(id)}/reject`, {
      method: 'POST', body: JSON.stringify({ note: note || null }),
    }),
  validationReports: () => request('/validation-reports?limit=200'),
  demoFixtures: () => request('/demo/problematic-responses'),

  exportUrl: (fmt) => `${BASE}/export?fmt=${fmt}`,
};
