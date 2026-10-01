import { useAppData } from '../state/AppData.jsx';

/**
 * The domain + difficulty selectors, built only from the shared taxonomy.
 * Used by every page that filters - there is no other definition of these options.
 */
export function AreaSelect({ id, value, onChange, allowAll = true, label = 'Domain' }) {
  const { taxonomy } = useAppData();
  const groups = taxonomy?.groups ?? [];
  return (
    <div>
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={!taxonomy}>
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

export function DifficultySelect({ id, value, onChange, allLabel = 'All difficulties', label = 'Difficulty' }) {
  const { taxonomy } = useAppData();
  return (
    <div>
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={!taxonomy}>
        <option value="">{allLabel}</option>
        {(taxonomy?.difficulties ?? []).map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
      </select>
    </div>
  );
}

/** Both selectors side by side, for list pages. `value` = { area, difficulty }. */
export default function TaxonomyFilters({ idPrefix, value, onChange }) {
  return (
    <>
      <AreaSelect id={`${idPrefix}-area`} value={value.area}
        onChange={(area) => onChange({ ...value, area })} />
      <DifficultySelect id={`${idPrefix}-difficulty`} value={value.difficulty}
        onChange={(difficulty) => onChange({ ...value, difficulty })} />
    </>
  );
}
