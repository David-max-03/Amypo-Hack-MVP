/** Shows what is actually running, so a demo never silently degrades. */
export default function HealthBar({ health, error }) {
  if (error) {
    return (
      <div className="health">
        <span className="pill"><i className="dot bad" />backend unreachable</span>
      </div>
    );
  }
  if (!health) {
    return (
      <div className="health">
        <span className="pill"><i className="dot warn" />checking…</span>
      </div>
    );
  }

  const ollamaOk = health.ollama?.reachable && health.ollama?.model_available;
  const embOk = health.embeddings?.is_minilm;

  return (
    <div className="health">
      <span className="pill">
        <i className={`dot ${health.status === 'ok' ? 'ok' : 'warn'}`} />
        {health.status}
      </span>
      <span className="pill" title={health.ollama?.detail}>
        <i className={`dot ${ollamaOk ? 'ok' : 'bad'}`} />
        Ollama · {health.ollama?.model}
      </span>
      <span className="pill" title={health.embeddings?.load_error || health.embeddings?.backend}>
        <i className={`dot ${embOk ? 'ok' : 'warn'}`} />
        {embOk ? 'MiniLM' : 'fallback vectoriser'}
      </span>
      <span className="pill">
        <i className="dot ok" />
        corpus · {health.corpus?.entry_count} entries
      </span>
      <span className="pill">
        <i className="dot ok" />
        bank · {health.storage?.accepted_questions}
      </span>
    </div>
  );
}
