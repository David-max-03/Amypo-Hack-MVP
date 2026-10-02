/** The header card at the top of every page: optional eyebrow, title, description, actions. */
export default function PageHeader({ eyebrow, title, description, children }) {
  return (
    <header className="page-head">
      <div>
        {eyebrow && <span className="eyebrow-chip">{eyebrow}</span>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {children && <div className="page-actions">{children}</div>}
    </header>
  );
}

/** Placeholder block shown while data loads. */
export function Skeleton({ lines = 3, className = '' }) {
  return (
    <div className={`skeleton ${className}`} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => <span key={i} style={{ width: `${92 - i * 14}%` }} />)}
    </div>
  );
}

/** Empty / error state with an optional action. */
export function StateBlock({ tone = 'empty', title, children, action }) {
  return (
    <div className={`state ${tone}`} role={tone === 'error' ? 'alert' : undefined}>
      <b>{title}</b>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}
