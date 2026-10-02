/** Backend-shaped fixtures for the UI tests. The api module is mocked with these. */
export const taxonomy = {
  subject_areas: [
    { id: 'algorithms', label: 'Algorithms', group: 'Computer Science', pipeline_domain: 'programming' },
    { id: 'data_structures', label: 'Data Structures', group: 'Computer Science', pipeline_domain: 'programming' },
    { id: 'database', label: 'Database', group: 'Computer Science', pipeline_domain: 'programming' },
    { id: 'programming', label: 'Programming (general)', group: 'Computer Science', pipeline_domain: 'programming' },
  ],
  difficulties: [
    { id: 'easy', label: 'Easy' }, { id: 'medium', label: 'Medium' },
    { id: 'hard', label: 'Hard' }, { id: 'expert', label: 'Expert' },
  ],
  default_subject_area: 'programming',
  groups: ['Computer Science'],
};

export const health = {
  status: 'ok',
  ollama: { reachable: true, model_available: true, model: 'qwen2.5-coder:7b', detail: 'ok' },
  embeddings: { is_minilm: true },
  corpus: { entry_count: 36 },
  storage: { accepted_questions: 2, review_queue: 1 },
};

const rv = (score, verdict) => ({
  reliability_score: score, verdict, hallucination_probability: 0.12, confidence_score: 0.8,
  claims: [{ text: 'Reversal runs in O(n) time.', claim_type: 'complexity' }],
  evidence: [{ claim: 'Reversal runs in O(n) time.', status: 'supported', supported: true, similarity: 0.91, source_title: 'CLRS' }],
  contradictions: [], flagged_spans: [], reasons: [], signals: { source_grounding: 0.9, unsupported: 0.1, fabrication_markers: 0 },
});
const sv = (passed = true) => ({
  passed, concept_preserved: true, difficulty_match: true, is_duplicate: false, meaningful_variation: passed,
  concept_overlap: 0.6, difficulty_delta: 0, semantic_similarity: 0.7, lexical_similarity: 0.3, reasons: [],
  checks: { answer_key: { substantive: true, has_code: true }, method: {}, duplicate: {}, difficulty: {}, concept: {} },
});

export function candidate(n, decision = 'PASS', extra = {}) {
  return {
    candidate: {
      id: `q_${n}`, question: `Reverse linked list variant ${n}`, answer_key: `def reverse_${n}(head): ...`,
      domain: 'programming', topic: 'Linked Lists', difficulty: 'medium', difficulty_score: 0.55,
      question_type: 'coding', learning_objective: 'Implement reversal.', test_cases: [],
      variation_strategy: 'scenario', strategy_label: 'Scenario Variation', solution_method: 'iterative',
    },
    decision, decision_reasons: decision === 'PASS' ? [] : ['PS2 could not ground the scenario details'],
    structural_validation: sv(), reliability_verification: rv(decision === 'PASS' ? 0.92 : 0.61, decision === 'PASS' ? 'trustworthy' : 'unverifiable'),
    attempts: 1, regeneration_history: [], subject_area: 'data_structures', ...extra,
  };
}

export function job(overrides = {}) {
  const results = overrides.results || [];
  return {
    job_id: 'job_test', kind: 'normal', demo: false, seed: 'Reverse a linked list.', domain: 'programming',
    subject_area: 'data_structures', status: 'running', current_stage: 'generating',
    current: { variation: results.length + 1 }, requested_count: 3, generated_count: results.length,
    accepted_count: results.filter((r) => r.decision === 'PASS').length,
    review_count: results.filter((r) => r.decision === 'REVIEW').length,
    rejected_count: results.filter((r) => r.decision === 'REJECT').length,
    regeneration_attempts: 0, results, summary: null, seed_metadata: null, timings_ms: {}, metrics: null,
    cancel_requested: false, warnings: [], errors: [], started_at: new Date().toISOString(), completed_at: null,
    ...overrides,
  };
}

export const bankRows = [
  { id: 'q_a', question: 'Reverse a singly linked list iteratively.', answer_key: 'def rev(h): ...', domain: 'programming', subject_area: 'data_structures',
    difficulty: 'medium', variation_strategy: 'scenario', solution_method: 'iterative', reliability_score: 0.91, verdict: 'trustworthy',
    decision: 'PASS', validation_status: 'passed both gates', attempts: 1, topic: 'Linked Lists', created_at: '2026-09-30T09:00:00+00:00' },
  { id: 'q_b', question: 'Find the shortest path in a weighted graph.', answer_key: 'def dijkstra(g): ...', domain: 'programming', subject_area: 'algorithms',
    difficulty: 'hard', variation_strategy: 'constraint', solution_method: 'recursive', reliability_score: 0.84, verdict: 'trustworthy',
    decision: 'PASS', validation_status: 'approved by human reviewer', attempts: 2, topic: 'Graphs', created_at: '2026-09-30T09:05:00+00:00' },
  // Stored before subject areas existed: only its pipeline domain is known.
  { id: 'q_c', question: 'Explain a stack with an example.', answer_key: 'A stack is LIFO.', domain: 'programming',
    difficulty: 'easy', variation_strategy: 'parameter', solution_method: null, reliability_score: 0.78, verdict: 'trustworthy',
    decision: 'PASS', validation_status: 'passed both gates', attempts: 1, topic: 'Stacks', created_at: '2026-09-29T09:00:00+00:00' },
];

export function report(n, decision, extra = {}) {
  const c = candidate(n, decision);
  return {
    candidate_id: c.candidate.id, question: c.candidate.question, domain: 'programming', subject_area: 'data_structures',
    seed_question: 'Reverse a linked list.', job_id: 'job_test', difficulty: 'medium', difficulty_score: 0.55,
    variation_strategy: 'scenario', solution_method: 'iterative', decision, decision_reasons: c.decision_reasons,
    attempts: 1, regeneration_history: [], structural_validation: c.structural_validation,
    reliability_verification: c.reliability_verification, created_at: new Date().toISOString(), ...extra,
  };
}

export const demoJob = () => job({
  job_id: 'job_demo', kind: 'demo', demo: true, demo_label: 'DEMO — scripted candidates, real validation',
  status: 'completed', current_stage: 'complete', requested_count: 1, completed_at: new Date().toISOString(),
  results: [candidate(1, 'PASS', {
    attempts: 2,
    regeneration_history: [{
      attempt: 1, decision: 'REJECT', rejected_question: 'Reverse it recursively using O(1) space.',
      structural_reasons: [], reliability_reasons: ['contradicts the reference corpus: O(1) versus O(n)'],
      flagged_spans: [], structural_passed: true, reliability_score: 0.699, verdict: 'misleading',
    }],
  })],
});
