/** Inline stroke icons (24px grid). Decorative by default: pair with a text label. */
const PATHS = {
  menu: 'M4 7h16M4 12h16M4 17h16',
  close: 'M6 6l12 12M18 6L6 18',
  generate: 'M10 3l1.8 4.7L16.5 9.5l-4.7 1.8L10 16l-1.8-4.7L3.5 9.5l4.7-1.8L10 3zM18 14l.9 2.1L21 17l-2.1.9L18 20l-.9-2.1L15 17l2.1-.9L18 14z',
  bank: 'M4 4h16v16H4zM4 10h16M4 15h16M10 4v16',
  reports: 'M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3zM9 12l2 2 4-4',
  verify: 'M11 4a7 7 0 105.3 11.6L20 19.3M8.5 11l1.8 1.8 3.4-3.6',
  review: 'M4 13l2.5-8h11L20 13v6H4v-6zM4 13h5a3 3 0 006 0h5',
  bolt: 'M13 3L5 13h6l-1 8 8-10h-6l1-8z',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  'check-circle': 'M12 21a9 9 0 100-18 9 9 0 000 18zM8.5 12.2l2.4 2.4 4.6-4.9',
  alert: 'M12 4l9 16H3l9-16zM12 10v4M12 17.2v.3',
  'x-circle': 'M12 21a9 9 0 100-18 9 9 0 000 18zM9 9l6 6M15 9l-6 6',
  'chevron-down': 'M6 9l6 6 6-6',
  'chevron-right': 'M9 6l6 6-6 6',
  'chevron-left': 'M15 6l-6 6 6 6',
  download: 'M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19h14',
  clock: 'M12 21a9 9 0 100-18 9 9 0 000 18zM12 7.5V12l3 2',
  layers: 'M12 4l8 4-8 4-8-4 8-4zM4 12l8 4 8-4M4 16l8 4 8-4',
  search: 'M11 18a7 7 0 100-14 7 7 0 000 14zM20 20l-4-4',
  refresh: 'M20 11a8 8 0 10-2.3 5.7M20 5v6h-6',
  stop: 'M7 7h10v10H7z',
  list: 'M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01',
  minus: 'M6 12h12',
  plus: 'M12 6v12M6 12h12',
  history: 'M4 12a8 8 0 108-8 8 8 0 00-6.2 3M4 4v4h4M12 8v4l3 2',
};

export default function Icon({ name, size = 18, className = '', title }) {
  return (
    <svg className={`icon ${className}`} width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden={title ? undefined : 'true'} role={title ? 'img' : undefined} aria-label={title}>
      <path d={PATHS[name] || ''} />
    </svg>
  );
}
