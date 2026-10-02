import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App.jsx';
import { api } from '../api.js';
import { bankRows, candidate, demoJob, health, job, report, taxonomy } from './fixtures.js';

vi.mock('../api.js', () => ({
  api: {
    health: vi.fn(), taxonomy: vi.fn(), domains: vi.fn(), startJob: vi.fn(), startDemoJob: vi.fn(),
    job: vi.fn(), jobs: vi.fn(), cancelJob: vi.fn(), questions: vi.fn(), reviewQueue: vi.fn(),
    validationReports: vi.fn(), reportStats: vi.fn(), demoFixtures: vi.fn(), verify: vi.fn(),
    approveReview: vi.fn(), rejectReview: vi.fn(), exportUrl: (fmt) => `/api/v1/export?fmt=${fmt}`,
  },
}));

const stats = (pass, review, reject, extra = {}) => {
  const total = pass + review + reject;
  const pc = (n) => (total ? Math.round((1000 * n) / total) / 10 : 0);
  return {
    total, regenerated: 0, regeneration_rate: 0, runs: [], reports_without_run: 0,
    decisions: { PASS: { count: pass, percent: pc(pass) }, REVIEW: { count: review, percent: pc(review) }, REJECT: { count: reject, percent: pc(reject) } },
    ...extra,
  };
};

beforeEach(() => {
  vi.clearAllMocks();
  api.health.mockResolvedValue(health);
  api.taxonomy.mockResolvedValue(taxonomy);
  api.domains.mockResolvedValue([]);
  api.questions.mockResolvedValue({ count: bankRows.length, questions: bankRows });
  api.reviewQueue.mockResolvedValue({ count: 0, items: [] });
  api.validationReports.mockResolvedValue({ count: 0, reports: [] });
  api.reportStats.mockResolvedValue(stats(0, 0, 0));
  api.demoFixtures.mockResolvedValue({ cases: [] });
  api.jobs.mockResolvedValue({ count: 0, jobs: [] });
});

const nav = (name) => screen.getByRole('button', { name: new RegExp(`^${name}`) });
const ready = () => waitFor(() => expect(screen.getByTestId('generate-btn')).toBeEnabled());
const optionLabels = (select) => within(select).getAllByRole('option').map((o) => o.textContent);

/** A backend job that keeps running - one candidate short of done - until the test
 *  lets it finish. How fast the test navigates therefore cannot decide whether the
 *  job is still running when a page is reached. */
function progressingJob(total = 3) {
  let polls = 0;
  let finish = false;
  api.startJob.mockResolvedValue(job({ status: 'queued', current_stage: 'queued' }));
  api.job.mockImplementation(async () => {
    polls += 1;
    const done = finish ? total : Math.min(total - 1, Math.floor(polls / 4));
    const results = Array.from({ length: done }, (_, i) => candidate(i + 1, i === 1 ? 'REVIEW' : 'PASS'));
    return done >= total
      ? job({ results, status: 'completed', current_stage: 'complete', completed_at: new Date().toISOString() })
      : job({ results });
  });
  const count = () => polls;
  count.finish = () => { finish = true; };
  return count;
}

describe('generation is application-level', () => {
  it('keeps running, and keeps being polled, while the user visits other pages', async () => {
    const user = userEvent.setup();
    const polls = progressingJob();
    render(<App pollMs={15} />);
    await ready();

    await user.click(screen.getByTestId('generate-btn'));
    expect(api.startJob).toHaveBeenCalledWith(expect.objectContaining({
      subject_area: 'data_structures', count: 10, enable_regeneration: true, persist: true,
    }));
    await screen.findByTestId('job-indicator');

    await user.click(nav('Question Bank'));
    expect(await screen.findByTestId('bank')).toBeInTheDocument();
    expect(screen.queryByTestId('generate-btn')).not.toBeInTheDocument();   // Generate page is unmounted
    const onBank = polls();
    await waitFor(() => expect(polls()).toBeGreaterThan(onBank + 1));         // ...and the job is still polled
    expect(screen.getByTestId('job-indicator')).toHaveTextContent(/Generation running · \d\/3/);

    await user.click(nav('Reports'));
    expect(await screen.findByTestId('reports')).toBeInTheDocument();
    const onReports = polls();
    await waitFor(() => expect(polls()).toBeGreaterThan(onReports + 1));

    // The header indicator leads back to the same job, with its live results.
    await user.click(screen.getByTestId('job-indicator'));
    expect(await screen.findByTestId('generate-btn')).toBeInTheDocument();
    polls.finish();
    await waitFor(() => expect(screen.getAllByTestId('candidate-card')).toHaveLength(3));
    expect(screen.getByTestId('run-summary')).toHaveTextContent('completed');
    expect(await screen.findByText(/Generation finished — 2 PASS · 1 REVIEW · 0 REJECT/)).toBeInTheDocument();
    expect(api.startJob).toHaveBeenCalledTimes(1);                            // never restarted
  });

  it('resumes the stored job after a reload', async () => {
    window.localStorage.setItem('amypo.activeJobId', 'job_test');
    api.job.mockResolvedValue(job({ results: [candidate(1)] }));
    render(<App pollMs={15} />);
    expect(await screen.findByTestId('job-indicator')).toHaveTextContent('Generation running · 1/3');
    expect(api.job).toHaveBeenCalledWith('job_test');
    expect(await screen.findByTestId('candidate-card')).toBeInTheDocument();
    expect(screen.getAllByTestId('candidate-skeleton').length).toBeGreaterThan(0);  // still-pending candidates
  });

  it('forgets a job the backend no longer knows', async () => {
    window.localStorage.setItem('amypo.activeJobId', 'job_gone');
    api.job.mockRejectedValue(new Error("No job 'job_gone' (jobs live until the backend restarts)"));
    render(<App pollMs={15} />);
    await waitFor(() => expect(window.localStorage.getItem('amypo.activeJobId')).toBeNull());
    expect(screen.queryByTestId('job-indicator')).not.toBeInTheDocument();
  });

  it('cancels the running job through the backend', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem('amypo.activeJobId', 'job_test');
    api.job.mockResolvedValue(job({ results: [candidate(1)] }));
    api.cancelJob.mockResolvedValue(job({ cancel_requested: true, current_stage: 'cancelling', results: undefined }));
    render(<App pollMs={15} />);
    await user.click(await screen.findByTestId('cancel-btn'));
    expect(api.cancelJob).toHaveBeenCalledWith('job_test');
  });

  it('shows the backend error when a job cannot start', async () => {
    const user = userEvent.setup();
    api.startJob.mockRejectedValue(new Error('Cannot reach the backend'));
    render(<App pollMs={15} />);
    await ready();
    await user.click(screen.getByTestId('generate-btn'));
    expect((await screen.findAllByText(/Cannot reach the backend/)).length).toBeGreaterThan(0);
    expect(screen.getByRole('alert')).toHaveTextContent('Cannot reach the backend');
    expect(screen.getByTestId('generate-btn')).toBeEnabled();                 // the form is usable again
  });
});

describe('PS2 runs automatically', () => {
  it('shows the PS8 and PS2 results the backend returned for every candidate, with no manual step', async () => {
    window.localStorage.setItem('amypo.activeJobId', 'job_test');
    api.job.mockResolvedValue(job({
      status: 'completed', current_stage: 'complete', completed_at: new Date().toISOString(),
      results: [candidate(1, 'PASS'), candidate(2, 'REVIEW')],
    }));
    render(<App pollMs={15} />);
    const cards = await screen.findAllByTestId('candidate-card');
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByTestId('metric-reliability')).toHaveTextContent('0.92');
    expect(within(cards[0]).getByTestId('gate-ps8')).toHaveTextContent(/5\/5 passed/);
    expect(within(cards[0]).getByTestId('gate-ps2')).toHaveTextContent(/6\/6 passed/);
    expect(within(cards[1]).getByTestId('metric-reliability')).toHaveTextContent('0.61');
    expect(within(cards[1]).getByTestId('gate-ps2')).toHaveTextContent(/5\/6 passed/);
    expect(within(cards[1]).getByTestId('decision-reason')).toHaveTextContent('PS2 could not ground the scenario details');
    expect(api.verify).not.toHaveBeenCalled();                                // nothing was pasted into the verifier
  });

  it('lists verified candidates on the PS2 Verifier page with their job and candidate id', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem('amypo.activeJobId', 'job_test');
    api.job.mockResolvedValue(job({ results: [candidate(1, 'PASS')] }));
    render(<App pollMs={15} />);
    await screen.findByTestId('job-indicator');
    await user.click(nav('PS2 Verifier'));
    expect(await screen.findByTestId('ps2-live')).toHaveTextContent(/Verifying now.*job_test/);
    const detail = await screen.findByTestId('ps2-detail');
    expect(detail).toHaveTextContent('#q_1');
    expect(detail).toHaveTextContent('job_test');
    expect(detail).toHaveTextContent('0.920');
  });
});

describe('one shared domain and difficulty configuration', () => {
  it('builds every selector from the backend taxonomy', async () => {
    const user = userEvent.setup();
    render(<App pollMs={15} />);
    await ready();
    const areas = taxonomy.subject_areas.map((a) => a.label);
    const levels = taxonomy.difficulties.map((d) => d.label);
    expect(optionLabels(screen.getByLabelText('Domain classification'))).toEqual(areas);
    expect(optionLabels(screen.getByLabelText('Target difficulty')).slice(1)).toEqual(levels);

    for (const page of ['Question Bank', 'Reports', 'PS2 Verifier', 'Review Queue']) {
      await user.click(nav(page));
      await waitFor(() => expect(optionLabels(screen.getByLabelText('Domain'))).toEqual(['All domains', ...areas]));
      expect(optionLabels(screen.getByLabelText('Difficulty'))).toEqual(['All difficulties', ...levels]);
    }
    expect(api.taxonomy).toHaveBeenCalledTimes(1);                            // fetched once, shared by all pages
  });

  it('reports a taxonomy failure instead of falling back to a hard-coded list', async () => {
    api.taxonomy.mockRejectedValue(new Error('HTTP 500'));
    render(<App pollMs={15} />);
    expect(await screen.findByText(/Could not load the domain \/ difficulty configuration: HTTP 500/)).toBeInTheDocument();
    expect(screen.getByTestId('generate-btn')).toBeDisabled();
  });
});

describe('Question Bank', () => {
  async function openBank() {
    const user = userEvent.setup();
    render(<App pollMs={15} />);
    await user.click(nav('Question Bank'));
    await waitFor(() => expect(screen.getAllByTestId('bank-row')).toHaveLength(3));
    return user;
  }

  it('filters by domain, difficulty and search, and can clear the filters', async () => {
    const user = await openBank();
    await user.selectOptions(screen.getByLabelText('Domain'), 'algorithms');
    expect(screen.getAllByTestId('bank-row')).toHaveLength(1);
    expect(screen.getByTestId('bank-row')).toHaveTextContent('shortest path');

    await user.selectOptions(screen.getByLabelText('Domain'), '');
    await user.selectOptions(screen.getByLabelText('Difficulty'), 'easy');
    expect(screen.getByTestId('bank-row')).toHaveTextContent('Explain a stack');

    await user.selectOptions(screen.getByLabelText('Difficulty'), '');
    await user.type(screen.getByLabelText('Search questions'), 'linked');
    expect(screen.getByTestId('bank-row')).toHaveTextContent('singly linked list');

    await user.selectOptions(screen.getByLabelText('Difficulty'), 'expert');
    expect(screen.queryByTestId('bank-row')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(screen.getAllByTestId('bank-row')).toHaveLength(3);
  });

  it('filters by strategy, method, validation status and decision', async () => {
    const user = await openBank();
    await user.selectOptions(screen.getByLabelText('Strategy'), 'constraint');
    expect(screen.getByTestId('bank-row')).toHaveTextContent('shortest path');
    await user.selectOptions(screen.getByLabelText('Strategy'), '');
    await user.selectOptions(screen.getByLabelText('Method'), 'iterative');
    expect(screen.getByTestId('bank-row')).toHaveTextContent('singly linked list');
    await user.selectOptions(screen.getByLabelText('Method'), '');
    await user.selectOptions(screen.getByLabelText('Validation status'), 'approved by human reviewer');
    expect(screen.getByTestId('bank-row')).toHaveTextContent('Approved by reviewer');
    await user.selectOptions(screen.getByLabelText('Validation status'), '');
    await user.selectOptions(screen.getByLabelText('Decision'), 'PASS');
    expect(screen.getAllByTestId('bank-row')).toHaveLength(3);
  });

  it('expands a row to show the answer key', async () => {
    const user = await openBank();
    await user.click(screen.getByRole('button', { name: 'Show details for question 1' }));
    expect(screen.getByText('A stack is LIFO.')).toBeInTheDocument();          // newest first
  });

  it('shows a loading skeleton, then an error with a working retry', async () => {
    const user = userEvent.setup();
    let fail;
    api.questions.mockReturnValueOnce(new Promise((_, reject) => { fail = reject; }));
    render(<App pollMs={15} />);
    await user.click(nav('Question Bank'));
    expect(await screen.findByTestId('bank-loading')).toBeInTheDocument();
    fail(new Error('HTTP 503'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the question bank');
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(screen.getAllByTestId('bank-row')).toHaveLength(3));
  });

  it('explains an empty bank', async () => {
    const user = userEvent.setup();
    api.questions.mockResolvedValue({ count: 0, questions: [] });
    render(<App pollMs={15} />);
    await user.click(nav('Question Bank'));
    expect(await screen.findByText('No accepted questions yet')).toBeInTheDocument();
  });
});

describe('Reports', () => {
  it('shows the statistics the backend computed, not a count of the visible cards', async () => {
    const user = userEvent.setup();
    api.reportStats.mockResolvedValue(stats(294, 32, 22));
    api.validationReports.mockResolvedValue({ count: 348, reports: [report(1, 'PASS'), report(2, 'REVIEW')] });
    render(<App pollMs={15} />);
    await user.click(nav('Reports'));
    await waitFor(() => expect(screen.getByTestId('stat-PASS')).toHaveTextContent('294'));
    expect(screen.getByTestId('stat-PASS')).toHaveTextContent('84.5%');
    expect(screen.getByTestId('stat-REVIEW')).toHaveTextContent('32');
    expect(screen.getByTestId('stat-REVIEW')).toHaveTextContent('9.2%');
    expect(screen.getByTestId('stat-REJECT')).toHaveTextContent('22');
    expect(screen.getByTestId('stat-REJECT')).toHaveTextContent('6.3%');
    expect(screen.getAllByTestId('report-card')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'All (348)' })).toBeInTheDocument();
  });

  it('asks the backend again when the run or time filter changes, and filters by decision and search', async () => {
    const user = userEvent.setup();
    api.reportStats.mockResolvedValue(stats(1, 1, 0, { runs: [{ job_id: 'job_test', seed_question: 'Reverse a linked list.', reports: 2, last_at: new Date().toISOString() }] }));
    api.validationReports.mockResolvedValue({ count: 2, reports: [report(1, 'PASS'), report(2, 'REVIEW', { seed_question: 'Sort an array.' })] });
    render(<App pollMs={15} />);
    await user.click(nav('Reports'));
    await waitFor(() => expect(screen.getAllByTestId('report-card')).toHaveLength(2));

    await user.selectOptions(screen.getByLabelText('Run'), 'job_test');
    await waitFor(() => expect(api.reportStats).toHaveBeenLastCalledWith({ job_id: 'job_test', since_hours: '' }));
    await user.selectOptions(screen.getByLabelText('Time range'), '24');
    await waitFor(() => expect(api.validationReports).toHaveBeenLastCalledWith({ job_id: 'job_test', since_hours: '24' }));

    await user.click(screen.getByRole('button', { name: /^Review \(/ }));
    expect(screen.getByTestId('report-card')).toHaveTextContent('Review reason: PS2 could not ground the scenario details');
    await user.click(screen.getByRole('button', { name: /^All \(/ }));
    await user.type(screen.getByLabelText('Search reports'), 'sort an array');
    expect(screen.getAllByTestId('report-card')).toHaveLength(1);
    expect(screen.getByTestId('report-card')).toHaveTextContent('Seed: Sort an array.');
  });

  it('shows loading, error and empty states', async () => {
    const user = userEvent.setup();
    api.validationReports.mockRejectedValueOnce(new Error('HTTP 500'));
    render(<App pollMs={15} />);
    await user.click(nav('Reports'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load reports');
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('No reports yet')).toBeInTheDocument();
  });
});

describe('Demo Mode', () => {
  it('runs the demo job, shows REJECT → regeneration → PASS, and is labelled as not saved', async () => {
    const user = userEvent.setup();
    api.startDemoJob.mockResolvedValue(job({ job_id: 'job_demo', demo: true, kind: 'demo', status: 'queued', requested_count: 1 }));
    api.job.mockResolvedValue(demoJob());
    render(<App pollMs={15} />);
    await ready();
    await user.click(screen.getByRole('button', { name: 'Demo scenario' }));
    expect(screen.getByTestId('demo-banner')).toHaveTextContent('scripted candidates, real validation');
    await user.click(screen.getByRole('button', { name: 'Run demo scenario' }));

    expect(api.startDemoJob).toHaveBeenCalledTimes(1);
    expect(api.startJob).not.toHaveBeenCalled();
    const card = await screen.findByTestId('candidate-card');
    const timeline = within(card).getByTestId('attempt-timeline');
    expect(timeline).toHaveTextContent(/Attempt 1\s*REJECT.*Attempt 2\s*PASS/);
    expect(card).toHaveTextContent('contradicts the reference corpus: O(1) versus O(n)');
    expect(card).toHaveTextContent('not saved');
    expect(within(card).queryByRole('button', { name: /Saved to Bank/ })).not.toBeInTheDocument();
    expect(within(card).getAllByTestId('trace-attempt')).toHaveLength(2);
  });
});
