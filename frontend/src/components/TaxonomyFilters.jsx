import { useAppData } from '../state/AppData.jsx';

/**
 * The domain + difficulty selectors, built only from the shared taxonomy.
 * Used by every page that filters - there is no other definition of these options.
 */
export function AreaSelect({ id, value, onChange, allowAll = true, label = 'Domain', disabled = false, hideLabel = false }) {
  const { taxonomy } = useAppData();
  const groups = taxonomy?.groups ?? [];
  return (
    <div>
      <label htmlFor={id} className={hideLabel ? 'sr-only' : undefined}>{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={!taxonomy || disabled}>
        {allowAll && <option value="">All domains</option>}
        {groups.map((g) => (
          <optgroup key={g} label={g}>
            {taxonomy.subject_areas.filter((a) => a.group === g).map((a) => (
              <option key={a.id} value={a.id}>{a.label}</option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}

export function DifficultySelect({ id, value, onChange, allLabel = 'All difficulties', label = 'Difficulty', disabled = false, hideLabel = false }) {
  const { taxonomy } = useAppData();
  return (
    <div>
      <label htmlFor={id} className={hideLabel ? 'sr-only' : undefined}>{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={!taxonomy || disabled}>
        <option value="">{allLabel}</option>
        {(taxonomy?.difficulties ?? []).map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
      </select>
    </div>
  );
}

/** Both selectors side by side, for list pages. `value` = { area, difficulty }. */
export default function TaxonomyFilters({ idPrefix, value, onChange, hideLabel = false }) {
  return (
    <>
      <AreaSelect id={`${idPrefix}-area`} value={value.area} hideLabel={hideLabel}
        onChange={(area) => onChange({ ...value, area })} />
      <DifficultySelect id={`${idPrefix}-difficulty`} value={value.difficulty} hideLabel={hideLabel}
        onChange={(difficulty) => onChange({ ...value, difficulty })} />
    </>
  );
}
