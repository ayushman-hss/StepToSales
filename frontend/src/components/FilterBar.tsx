import { useDashboard, type RangePreset } from '../store';
import { useCurrentStore } from '../auth';
import { Input, Segmented } from '../lib/ui/controls';

const PERIODS: { value: RangePreset; label: string }[] = [
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: '7d', label: 'Last 7 days' },
  { value: '28d', label: 'Last 4 weeks' },
  { value: 'all', label: 'All' },
  { value: 'custom', label: 'Pick dates' },
];

export function FilterBar() {
  const { preset, startDate, endDate, setFilters, setPreset } = useDashboard();
  const me = useCurrentStore();

  return (
    <div className="space-y-4 rounded-section border border-rule bg-white p-4 md:p-5">
      <div className="flex flex-wrap items-end gap-4">
        {/* Not a picker any more: a login sees exactly one shop. Still shown,
            so it is never ambiguous whose numbers these are. */}
        <div className="flex flex-col gap-1.5">
          <span className="text-small font-medium text-muted">Shop</span>
          <span className="inline-flex min-h-11 items-center gap-2 rounded-control border border-rule bg-chalk px-3.5 text-body md:min-h-10">
            <span className="font-semibold text-ink">{me.store_code}</span>
            {me.store_name !== me.store_code && (
              <span className="text-muted">{me.store_name}</span>
            )}
          </span>
        </div>

        <Segmented
          label="Period"
          value={preset}
          onChange={setPreset}
          options={PERIODS}
          size="sm"
        />
      </div>

      {/* Raw date boxes only when asked for: most days the question is
          "how is today going", which should be one tap, not two pickers. */}
      {preset === 'custom' && (
        <div className="grid grid-cols-2 gap-3 sm:max-w-sm">
          <Input
            label="From"
            type="date"
            value={startDate}
            max={endDate || undefined}
            onChange={(e) => setFilters({ startDate: e.target.value })}
          />
          <Input
            label="To"
            type="date"
            value={endDate}
            min={startDate || undefined}
            onChange={(e) => setFilters({ endDate: e.target.value })}
          />
        </div>
      )}
    </div>
  );
}
