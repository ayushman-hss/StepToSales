import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import type { LiveBlock } from '../types';
import { CHART, baseOption, categoryAxis, valueAxis } from '../lib/charts/theme';
import { Figure, Notice, Section } from '../lib/ui/controls';

const rupees = (n: number) =>
  `₹${Math.round(n).toLocaleString('en-IN')}`;

/** "+18%" / "-7%" with a word, never a bare sign. */
function paceSentence(live: LiveBlock): string | null {
  if (live.pace == null || live.pace_through_hour == null) return null;
  const pct = Math.round(Math.abs(live.pace) * 100);
  const by = `by ${live.pace_through_hour + 1}:00`;
  if (pct < 5) return `Right on your usual pace ${by}.`;
  return live.pace > 0
    ? `${pct}% ahead of a usual ${live.weekday.slice(0, -1)} ${by}.`
    : `${pct}% behind a usual ${live.weekday.slice(0, -1)} ${by}.`;
}

/** Cumulative sales today, inside the corridor past weeks ran through. */
function BandChart({ live }: { live: LiveBlock }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chartRef.current = chart;
    const onResize = () => chart.resize();
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      chart.dispose();
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    // Only the hours the shop is ever open: a band of zeros at 3am is noise.
    const open = live.band.filter((b) => b.p90 > 0 || (b.actual ?? 0) > 0);
    const first = open.length ? open[0].hour : 0;
    const last = open.length ? open[open.length - 1].hour : 23;
    const rows = live.band.filter((b) => b.hour >= Math.max(0, first - 1) && b.hour <= last);
    const label = (h: number) => `${h + 1}:00`;

    chart.setOption(
      {
        ...baseOption({ left: 56, right: 18 }),
        tooltip: {
          ...baseOption().tooltip,
          formatter: (params: unknown) => {
            const i = (params as { dataIndex: number }[])[0].dataIndex;
            const r = rows[i];
            const today = r.actual == null ? '' : `<br/>Today ${rupees(r.actual)}`;
            return `<b>By ${label(r.hour)}</b>${today}<br/>Usual ${rupees(r.p50)}<br/>Range ${rupees(r.p10)} to ${rupees(r.p90)}`;
          },
        },
        xAxis: { ...categoryAxis(rows.map((r) => label(r.hour))), boundaryGap: false },
        yAxis: valueAxis({
          axisLabel: {
            color: CHART.muted,
            fontSize: 11.5,
            fontFamily: CHART.font,
            formatter: (v: number) => (v >= 1000 ? `₹${(v / 1000).toFixed(v % 1000 ? 1 : 0)}k` : `₹${v}`),
          },
        }),
        series: [
          // The band is drawn as a stacked pair: an invisible floor at p10,
          // then the p10-to-p90 thickness on top of it.
          {
            name: 'floor',
            type: 'line',
            stack: 'band',
            data: rows.map((r) => r.p10),
            lineStyle: { opacity: 0 },
            symbol: 'none',
            silent: true,
          },
          {
            name: 'usual range',
            type: 'line',
            stack: 'band',
            data: rows.map((r) => r.p90 - r.p10),
            lineStyle: { opacity: 0 },
            areaStyle: { color: CHART.boardTint, opacity: 1 },
            symbol: 'none',
            silent: true,
          },
          {
            name: 'usual',
            type: 'line',
            data: rows.map((r) => r.p50),
            lineStyle: { color: CHART.boardSoft, width: 1.5, type: 'dashed' },
            symbol: 'none',
            silent: true,
          },
          {
            name: 'today',
            type: 'line',
            data: rows.map((r) => r.actual),
            lineStyle: { color: CHART.board, width: 3 },
            itemStyle: { color: CHART.board },
            symbol: 'circle',
            symbolSize: (_: unknown, p: { dataIndex: number }) =>
              rows[p.dataIndex + 1]?.actual == null ? 9 : 0,
            connectNulls: false,
          },
        ],
      },
      true,
    );
  }, [live]);

  return (
    <div>
      <div ref={ref} className="h-64 w-full md:h-72" />
      <p className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-small text-muted">
        <span className="inline-flex items-center gap-2">
          <span className="h-0.5 w-4 rounded-full bg-board" aria-hidden />
          today
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="h-2.5 w-4 rounded-[2px] bg-board-tint" aria-hidden />
          usual range on {live.weekday}
        </span>
      </p>
    </div>
  );
}

/** Pace, the hour in progress, and the corridor: how today is going. */
export function LivePanel({ live }: { live: LiveBlock }) {
  const pace = paceSentence(live);
  const now = live.now;

  return (
    <div className="space-y-6">
      {live.alert && <Notice>{live.alert}</Notice>}

      <Section title="How today is going">
        {pace && <p className="text-heading text-ink">{pace}</p>}
        <p className="mt-1 text-small text-muted">
          Compared with the last {live.days_compared} {live.weekday}. The hour in
          progress is left out until it ends.
        </p>

        <div className="mt-5 flex flex-wrap gap-x-12 gap-y-5">
          {live.projected_sales != null && (
            <Figure
              value={rupees(live.projected_sales)}
              label="likely by closing"
              tone="board"
            />
          )}
          <Figure value={rupees(live.typical_sales)} label={`a usual ${live.weekday.slice(0, -1)}`} />
          {now && (
            <div>
              <div className="tnum text-2xl font-bold tracking-tight text-ink">
                {now.footfall} in, {now.transactions} bought
              </div>
              <div className="mt-0.5 text-small text-muted">
                {now.hour}:00 so far &middot; about {Math.round(now.usual_footfall)} and{' '}
                {Math.round(now.usual_transactions)} in a usual full hour
              </div>
            </div>
          )}
        </div>

        <div className="mt-6">
          <BandChart live={live} />
        </div>
      </Section>
    </div>
  );
}
