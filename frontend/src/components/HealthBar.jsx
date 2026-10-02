/** Shows what is actually running, so a demo never silently degrades.
 *  Wide screens get one pill per component; narrower ones get a single status
 *  button that opens the same pills in a small panel (CSS decides which shows). */
export default function HealthBar({ health, error }) {
  let items;
  if (error) {
    items = [{ tone: 'bad', text: 'backend unreachable' }];
  } else if (!health) {
    items = [{ tone: 'warn', text: 'checking…' }];
  } else {
    const ollamaOk = health.ollama?.reachable && health.ollama?.model_available;
    const embOk = health.embeddings?.is_minilm;
    items = [
      { tone: health.status === 'ok' ? 'ok' : 'warn', text: health.status },
      { tone: ollamaOk ? 'ok' : 'bad', text: `Ollama · ${health.ollama?.model}`, title: health.ollama?.detail },
      { tone: embOk ? 'ok' : 'warn', text: embOk ? 'MiniLM' : 'fallback vectoriser', title: health.embeddings?.load_error || health.embeddings?.backend },
      { tone: 'ok', text: `corpus · ${health.corpus?.entry_count} entries` },
      { tone: 'ok', text: `bank · ${health.storage?.accepted_questions}` },
    ];
  }
  const worst = items.some((i) => i.tone === 'bad') ? 'bad' : items.some((i) => i.tone === 'warn') ? 'warn' : 'ok';
  const issues = items.filter((i) => i.tone !== 'ok').length;
  const summary = error ? 'Offline' : !health ? 'Checking' : issues ? `${issues} issue${issues === 1 ? '' : 's'}` : 'All systems ok';
  const pills = items.map((i) => (
    <span className="pill" key={i.text} title={i.title}><i className={`dot ${i.tone}`} />{i.text}</span>
  ));

  return (
    <div className="health">
      <div className="health health-pills">{pills}</div>
      <details className="health-menu">
        <summary aria-label={`System status: ${summary}. Show details`}>
          <span className="pill"><i className={`dot ${worst}`} /><span className="hm-text">{summary}</span></span>
        </summary>
        <div className="health-panel">{pills}</div>
      </details>
    </div>
  );
}
