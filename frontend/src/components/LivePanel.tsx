import { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts';
import type { LiveBandPoint, LiveBlock } from '../types';
import { CHART, baseOption, valueAxis } from '../lib/charts/theme';
import { Figure, Notice, Section } from '../lib/ui/controls';

const rupees = (n: number) =>
  `₹${Math.round(n).toLocaleString('en-IN')}`;

/** 14.5 -> "14:30". */
function hhmm(hours: number): string {
  const m = Math.round(hours * 60);
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}`;
}

const reducedMotion = () =>
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

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

// ---------------------------------------------------------------------------
// The live line
//
// Points sit on a time axis: one at the end of every finished hour, and a
// last one at the shop clock carrying everything sold so far. Between two
// refreshes the end of the line glides from where it was to where it is now,
// along the real hour marks it passes, so at 10x or 300x the curve bends
// continuously instead of jumping an hour at a time.
// ---------------------------------------------------------------------------

type Pt = [number, number];

/** How much the curves round off between points. Low: the data stays honest. */
const SMOOTH = 0.0;

/** Redraw at most this often while gliding; plenty for a line, easy on laptops. */
const FRAME_MS = 30;
const GLIDE = false;

/** Only the hours the shop is ever open: a band of zeros at 3am is noise. */
function openRows(band: LiveBandPoint[]): LiveBandPoint[] {
  const open = band.filter((b) => b.p90 > 0 || (b.actual ?? 0) > 0);
  const first = open.length ? open[0].hour : 0;
  const last = open.length ? open[open.length - 1].hour : 23;
  return band.filter((b) => b.hour >= Math.max(0, first - 1) && b.hour <= last);
}

/** Finished hours, and the moving end of the line. */
function todayPoints(live: LiveBlock, rows: LiveBandPoint[], x0: number, x1: number) {
  const marks: Pt[] = rows
    .filter((r) => r.actual != null)
    .map((r) => [r.hour + 1, r.actual as number]);
  if (live.clock_hour == null) {
    return { done: marks, tip: marks.length ? marks[marks.length - 1] : null };
  }
  const x = Math.min(Math.max(live.clock_hour, x0), x1);
  // An hour's mark is only real once the hour is over; the one in progress
  // is represented by the tip instead.
  return { done: marks.filter(([mx]) => mx <= x), tip: [x, live.sales_so_far] as Pt };
}

/** Where the line's end is, a fraction f of the way from `from` to `to`. */
function glide(path: Pt[], f: number): Pt {
  const from = path[0];
  const to = path[path.length - 1];
  const x = from[0] + (to[0] - from[0]) * f;
  if (to[0] - from[0] < 1e-6) return [x, from[1] + (to[1] - from[1]) * f];
  for (let i = 1; i < path.length; i++) {
    const [ax, ay] = path[i - 1];
    const [bx, by] = path[i];
    if (x <= bx) {
      const t = bx > ax ? (x - ax) / (bx - ax) : 1;
      return [x, ay + (by - ay) * t];
    }
  }
  return to;
}

/** A y-axis top and step that read well: steps of 1, 2, 2.5 or 5 x 10^k. */
function niceScale(max: number, ticks = 4) {
  const raw = Math.max(max, 1) / ticks;
  const e = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * e).find((s) => s >= raw) ?? raw;
  return { step, top: Math.ceil(max / step) * step };
}

const shortRupees = (v: number) =>
  v >= 1000 ? `₹${+(v / 1000).toFixed(2)}k` : `₹${v}`;

/** Cumulative sales today, inside the corridor past weeks ran through. */
function BandChart({ live }: { live: LiveBlock }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  /** The end of the line as it is drawn right now. */
  const shown = useRef<Pt | null>(null);
  const rowsRef = useRef<LiveBandPoint[]>([]);
  const scale = useRef<{ key: string; top: number; step: number } | null>(null);
  const lastUpdate = useRef(0);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chartRef.current = chart;
    const onResize = () => chart.resize();
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      chart.dispose();
      chartRef.current = null;
      scale.current = null;
      shown.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const rows = openRows(live.band);
    if (!rows.length) return;
    rowsRef.current = rows;
    const x0 = rows[0].hour + 1;
    const x1 = rows[rows.length - 1].hour + 1;
    const { done, tip } = todayPoints(live, rows, x0, x1);

    // The y-axis only ever grows during a day, so the curve never jumps
    // because the scale under it moved. A new day or a reset starts over.
    const need =
      Math.max(...rows.map((r) => r.p90), tip?.[1] ?? 0, ...done.map((p) => p[1])) * 1.04;
    const key = `${live.weekday}|${x0}|${x1}`;
    let s = scale.current;
    const rebuild = !s || s.key !== key || need > s.top || need < s.top * 0.5;
    if (rebuild) {
      s = { key, ...niceScale(need) };
      scale.current = s;
      chart.setOption(fullOption(rows, x0, x1, s, rowsRef, shown), true);
    } else {
      chart.setOption({
        series: [
          { id: 'floor', data: rows.map((r) => [r.hour + 1, r.p10]) },
          { id: 'range', data: rows.map((r) => [r.hour + 1, r.p90 - r.p10]) },
          { id: 'usual', data: rows.map((r) => [r.hour + 1, r.p50]) },
        ],
      });
    }

    const draw = (end: Pt | null) => {
      shown.current = end;
      chart.setOption(
        {
          series: [
            { id: 'today', data: end ? [...done.filter((p) => p[0] < end[0]), end] : done },
            { id: 'tip', data: end ? [end] : [] },
          ],
        },
        { lazyUpdate: true },
      );
    };

    const now = performance.now();
    const gap = lastUpdate.current ? now - lastUpdate.current : 0;
    lastUpdate.current = now;

    const from = shown.current;
    const jump =
      !tip ||
      !from ||
      rebuild ||
      !GLIDE ||
      tip[0] < from[0] - 1e-9 || // clock went back: a reset, a new day
      tip[1] < from[1] - 0.5;
    if (jump) {
      draw(tip);
      return;
    }

    // Glide over about as long as the next refresh takes, so the end of the
    // line keeps moving instead of rushing ahead and then waiting.
    const duration = Math.min(Math.max(gap || 2000, 400), 6000) * 0.95;
    const path: Pt[] = [from, ...done.filter((p) => p[0] > from[0] && p[0] < tip[0]), tip];
    const start = performance.now();
    let last = 0;
    let raf = 0;
    const step = (t: number) => {
      const f = Math.min(1, (t - start) / duration);
      if (f < 1 && t - last < FRAME_MS) {
        raf = requestAnimationFrame(step);
        return;
      }
      last = t;
      draw(f >= 1 ? tip : glide(path, f));
      if (f < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [live]);

  return (
    <div>
      <div ref={ref} className="h-64 w-full md:h-72" />
      <p className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-small text-muted">
        <span className="inline-flex items-center gap-2">
          <span className="h-0.5 w-4 rounded-full bg-board" aria-hidden />
          today, up to the shop clock
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="h-2.5 w-4 rounded-[2px] bg-board-tint" aria-hidden />
          usual range on {live.weekday}
        </span>
      </p>
    </div>
  );
}

function fullOption(
  rows: LiveBandPoint[],
  x0: number,
  x1: number,
  s: { top: number; step: number },
  rowsRef: React.RefObject<LiveBandPoint[]>,
  shown: React.RefObject<Pt | null>,
) {
  const axisText = { color: CHART.muted, fontSize: 11.5, fontFamily: CHART.font };
  return {
    ...baseOption({ left: 56, right: 24 }),
    // Motion is driven by hand (see BandChart); ECharts' own tweening would
    // restart on every frame and stutter.
    animation: false,
    tooltip: {
      ...baseOption().tooltip,
      formatter: (params: unknown) => {
        const list = params as { seriesId: string; value: Pt }[];
        const usual = list.find((p) => p.seriesId === 'usual');
        const r = usual && rowsRef.current?.find((row) => row.hour + 1 === usual.value[0]);
        if (!r) return '';
        const end = shown.current;
        const x = r.hour + 1;
        let today = '';
        if (end && x <= end[0] && r.actual != null) today = `<br/>Today ${rupees(r.actual)}`;
        else if (end && x - 1 < end[0] && end[0] < x)
          today = `<br/>So far ${rupees(end[1])} at ${hhmm(end[0])}`;
        return `<b>By ${x}:00</b>${today}<br/>Usual ${rupees(r.p50)}<br/>Range ${rupees(r.p10)} to ${rupees(r.p90)}`;
      },
    },
    xAxis: {
      type: 'value' as const,
      min: x0,
      max: x1,
      interval: 1,
      axisLine: { lineStyle: { color: CHART.rule } },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { ...axisText, formatter: (v: number) => `${v}:00`, hideOverlap: true },
    },
    yAxis: valueAxis({
      min: 0,
      max: s.top,
      interval: s.step,
      axisLabel: { ...axisText, formatter: shortRupees },
    }),
    series: [
      // The band is a stacked pair: an invisible floor at p10, then the
      // p10-to-p90 thickness on top of it.
      {
        id: 'floor',
        type: 'line',
        stack: 'band',
        data: rows.map((r) => [r.hour + 1, r.p10]),
        lineStyle: { opacity: 0 },
        symbol: 'none',
        smooth: SMOOTH,
        silent: true,
      },
      {
        id: 'range',
        type: 'line',
        stack: 'band',
        data: rows.map((r) => [r.hour + 1, r.p90 - r.p10]),
        lineStyle: { opacity: 0 },
        areaStyle: { color: CHART.boardTint, opacity: 1 },
        symbol: 'none',
        smooth: SMOOTH,
        silent: true,
      },
      {
        id: 'usual',
        type: 'line',
        data: rows.map((r) => [r.hour + 1, r.p50]),
        lineStyle: { color: CHART.boardSoft, width: 1.5, type: 'dashed' as const },
        symbol: 'none',
        smooth: SMOOTH,
        silent: true,
      },
      {
        id: 'today',
        type: 'line',
        data: [] as Pt[],
        lineStyle: { color: CHART.board, width: 3, cap: 'round' as const },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(11, 92, 78, 0.16)' },
            { offset: 1, color: 'rgba(11, 92, 78, 0)' },
          ]),
        },
        symbol: 'none',
        smooth: SMOOTH,
        smoothMonotone: 'x' as const,
        z: 3,
      },
      {
        // The end of the line: the shop clock, with a slow ripple so it
        // reads as live even when paused between bills.
        id: 'tip',
        type: 'effectScatter',
        data: [] as Pt[],
        symbolSize: 10,
        itemStyle: { color: CHART.board, borderColor: CHART.white, borderWidth: 2 },
        rippleEffect: { brushType: 'fill' as const, scale: 2.6, period: 2.4, color: 'rgba(11, 92, 78, 0.25)' },
        label: {
          show: true,
          position: 'top' as const,
          distance: 9,
          formatter: (p: { value: Pt }) => hhmm(p.value[0]),
          ...axisText,
          fontWeight: 600,
          color: CHART.board,
        },
        tooltip: { show: false },
        z: 4,
      },
    ],
  };
}

/** A rupee figure that counts to its new value instead of snapping. */
function RollingRupees({ value }: { value: number }) {
  const [shownValue, setShownValue] = useState(value);
  const current = useRef(value);

  useEffect(() => {
    const from = current.current;
    if (from === value) return;
    if (reducedMotion()) {
      current.current = value;
      const raf = requestAnimationFrame(() => setShownValue(value));
      return () => cancelAnimationFrame(raf);
    }
    const start = performance.now();
    let raf = 0;
    const step = (t: number) => {
      const f = Math.min(1, (t - start) / 1400);
      const eased = 1 - (1 - f) ** 3;
      current.current = from + (value - from) * eased;
      setShownValue(current.current);
      if (f < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);

  return <>{rupees(shownValue)}</>;
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
          progress is left out of the pace until it ends.
        </p>

        <div className="mt-5 flex flex-wrap gap-x-12 gap-y-5">
          <Figure value={<RollingRupees value={live.sales_so_far} />} label="sold so far today" />
          {live.projected_sales != null && (
            <Figure
              value={<RollingRupees value={live.projected_sales} />}
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
