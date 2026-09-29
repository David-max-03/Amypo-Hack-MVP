/**
 * Renders text with PS2's flagged spans highlighted in place.
 *
 * Spans arrive with character offsets into the combined question+answer text.
 * Overlapping spans are merged so a region is never wrapped twice, which would
 * corrupt the offsets of everything after it.
 */
export default function HighlightedText({ text, spans = [] }) {
  const located = spans
    .filter((s) => Number.isInteger(s.start) && Number.isInteger(s.end) && s.end > s.start)
    .sort((a, b) => a.start - b.start);

  if (!located.length) return <span>{text}</span>;

  const merged = [];
  for (const span of located) {
    const last = merged[merged.length - 1];
    if (last && span.start < last.end) {
      last.end = Math.max(last.end, span.end);
      last.reason = `${last.reason} | ${span.reason}`;
    } else {
      merged.push({ ...span });
    }
  }

  const parts = [];
  let cursor = 0;
  merged.forEach((span, i) => {
    if (span.start > cursor) parts.push(<span key={`t${i}`}>{text.slice(cursor, span.start)}</span>);
    parts.push(
      <mark key={`m${i}`} title={span.reason}>
        {text.slice(span.start, span.end)}
      </mark>
    );
    cursor = span.end;
  });
  if (cursor < text.length) parts.push(<span key="tail">{text.slice(cursor)}</span>);

  return <>{parts}</>;
}
