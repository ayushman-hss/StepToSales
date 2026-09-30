import { useCallback, useEffect, useRef, useState } from 'react';
import { useDashboard } from '../store';
import { fetchDashboard, uploadExcel } from '../api';
import { KpiCards } from '../components/KpiCards';
import { InsightCards } from '../components/InsightCards';
import { WhatsAppPreview } from '../components/WhatsAppPreview';
import { FilterBar } from '../components/FilterBar';
import { FootfallSalesChart } from '../components/FootfallSales';
import { ConversionChart } from '../components/ConversionChart';
import { Heatmap } from '../components/Heatmap';
import { FeatureSwitcher } from '../components/FeatureSwitcher';
import { LivePanel } from '../components/LivePanel';
import { LiveStrip } from '../components/LiveStrip';
import {
  EmptyState,
  Notice,
  PageHeader,
  Section,
  UploadButton,
} from '../lib/ui/controls';

/** "2026-09-21T20" -> "today, 20:00" / "yesterday, 21:00" / "Fri 18 Sep". */
function freshness(through: string | null): string | null {
  if (!through) return null;
  const [day, hour] = through.split('T');
  const now = new Date();
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (day === iso(now)) return `today, up to the ${Number(hour)}:00 hour`;
  if (day === iso(yesterday)) return 'yesterday';
  const d = new Date(`${day}T00:00:00`);
  return d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });
}

const NO_DATA = 'No data for the given filters';
/** Often enough that at 300x the live chart gets a fresh point every 10 shop
 *  minutes; the chart glides between points, so it never looks stepped. */
const LIVE_REFRESH_MS = 2000;

/** Hourly charts show an average day once the range is longer than one. */
const avgDay = (days: number) => (days > 1 ? ', on an average day' : '');

export function DashboardPage() {
  const {
    data, loading, error, startDate, endDate, preset,
    setData, setLoading, setError, setPreset,
  } = useDashboard();
  const [note, setNote] = useState<string | null>(null);

  // Only the newest request may write to the page. Tapping "Last 4 weeks"
  // while today's numbers are still loading must not let the slower,
  // older reply land last and show today under the wrong period.
  const latest = useRef(0);

  // No shop in the request: the server answers for the logged-in one.
  // quiet: a background refresh. No spinner, and a failed refresh keeps the
  // numbers on screen instead of blanking them.
  const isToday = preset === 'today';
  const load = useCallback(async (quiet = false) => {
    const id = ++latest.current;
    try {
      if (!quiet) setLoading(true);
      setError(null);
      // Today is the shop's day, which the server knows: the browser's date
      // is wrong outside IST, and goes stale if the page stays open past
      // midnight.
      const d = await fetchDashboard(
        isToday
          ? { today: true }
          : { start_date: startDate || undefined, end_date: endDate || undefined },
      );
      if (id === latest.current) setData(d);
    } catch (e) {
      if (id !== latest.current || quiet) return;
      const msg = e instanceof Error ? e.message : 'Unknown error';
      // An empty period is not an error -- nothing has been sold yet.
      setError(msg === NO_DATA ? null : msg);
      setData(null);
    } finally {
      if (id === latest.current) setLoading(false);
    }
  }, [isToday, startDate, endDate, setData, setLoading, setError]);

  useEffect(() => { load(); }, [load]);

  // Live: while looking at today, refresh every few seconds. Other periods
  // are finished history and never change underneath you.
  useEffect(() => {
    if (!isToday) return;
    const id = window.setInterval(() => load(true), LIVE_REFRESH_MS);
    return () => window.clearInterval(id);
  }, [isToday, load]);

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setLoading(true);
      setError(null);
      setNote(null);
      const result = await uploadExcel(file);
      if (result.skipped_rows) {
        setNote(
          `Loaded ${result.rows} hours for your shop. ${result.skipped_rows} rows ` +
            'in the file were for other shops and were left out.',
        );
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setLoading(false);
      e.target.value = '';
    }
  };

  return (
    <div>
      <PageHeader
        title="Sales vs footfall"
        lead="How many of the people who walk in actually buy, hour by hour."
        action={<UploadButton onChange={onUpload}>Upload your hours file</UploadButton>}
      />

      <div className="space-y-8">
        <FilterBar />

        {isToday && <LiveStrip />}

        {loading && !data && <p className="text-small text-muted">Loading&hellip;</p>}
        {error && <Notice>{error}</Notice>}
        {note && <Notice tone="brass">{note}</Notice>}

        {!data && !loading && !error && (
          <EmptyState
            title={
              preset === 'today'
                ? 'No bills recorded yet today'
                : 'Nothing recorded for this period'
            }
          >
            {preset === 'today' ? (
              <p>
                The shop may not have opened yet.{' '}
                <button
                  onClick={() => setPreset('yesterday')}
                  className="font-medium text-board underline underline-offset-2"
                >
                  See yesterday
                </button>
              </p>
            ) : (
              <p>Choose another period, or upload a file with your hourly visitors and sales.</p>
            )}
          </EmptyState>
        )}

        {data && (
          <>
            {freshness(data.data_through) && (
              <p className="text-small text-muted">
                Latest bills: {freshness(data.data_through)}
              </p>
            )}

            {data.live && <LivePanel live={data.live} />}

            <KpiCards
              kpis={data.kpis}
              hourly={data.hourly}
              period={data.period}
              compare={data.compare}
            />

            <Section title={`Visitors and sales, hour by hour${avgDay(data.period.days)}`}>
              <FootfallSalesChart data={data.hourly} />
            </Section>

            <Section title={`Share who bought, hour by hour${avgDay(data.period.days)}`}>
              <ConversionChart data={data.hourly} />
            </Section>

            {data.period.days >= 7 && (
              <Section title="Busiest times of the week, on an average week">
                <Heatmap data={data.heatmap} />
              </Section>
            )}

            <InsightCards insights={data.insights} />

            <WhatsAppPreview text={data.whatsapp} />
          </>
        )}
      </div>

      <FeatureSwitcher
        to="/bundles"
        label="Bundles"
        description="Find the products your customers already buy together."
      />
    </div>
  );
}
