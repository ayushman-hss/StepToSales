import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { BellRing, ReceiptText } from 'lucide-react';
import clsx from 'clsx';
import { fetchLiveStatus, setLiveSpeed } from '../api';
import type { LiveSpeed, LiveStatus } from '../types';
import { Segmented } from '../lib/ui/controls';

const SPEEDS: { value: string; label: string }[] = [
  { value: '0', label: 'Pause' },
  { value: '1', label: 'Real time' },
  { value: '10', label: '10×' },
  { value: '60', label: '60×' },
  { value: '300', label: '300×' },
];

/** "2026-09-30T14:05:09" -> "14:05". */
const hhmm = (iso: string) => iso.slice(11, 16);

/** Seconds between two shop-clock stamps, as a person would say it. */
function ago(from: string | null, to: string): string | null {
  if (!from) return null;
  const s = Math.max(0, (Date.parse(to) - Date.parse(from)) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `at ${hhmm(from)}`;
}

function aheadLabel(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h}h ${m}m` : `${m} min`;
}

/**
 * The strip that says this page is live: a pulsing dot, how fresh the last
 * bill is, and the demo's speed control. Polls its own small endpoint; the
 * numbers underneath are refreshed by the dashboard.
 */
export function LiveStrip() {
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    const tick = () =>
      fetchLiveStatus()
        .then((s) => alive && setStatus(s))
        .catch(() => alive && setStatus(null));
    tick();
    const id = window.setInterval(tick, 2000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  if (!status) return null;

  const live = status.running && status.speed > 0;
  const lastBill = ago(status.last_bill_at, status.shop_time);

  const onSpeed = async (v: string) => {
    setBusy(true);
    try {
      setStatus(await setLiveSpeed(Number(v) as LiveSpeed));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 rounded-section border border-rule bg-white px-4 py-3 md:px-5">
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
        <span
          className={clsx(
            'inline-flex items-center gap-2 rounded-full px-2.5 py-1 text-fine font-bold tracking-wide',
            live ? 'bg-clay-tint text-clay' : 'bg-chalk text-muted',
          )}
        >
          <span className="relative flex h-2 w-2" aria-hidden>
            {live && (
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-clay opacity-60" />
            )}
            <span
              className={clsx(
                'relative inline-flex h-2 w-2 rounded-full',
                live ? 'bg-clay' : 'bg-muted',
              )}
            />
          </span>
          {live ? 'LIVE' : status.running ? 'PAUSED' : 'OFFLINE'}
        </span>
        <span className="tnum text-small text-muted">
          {status.bills_today} bills, {status.visitors_today} visitors counted live
          {lastBill && <> &middot; last bill {lastBill}</>}
        </span>
        {status.minutes_ahead > 0 && (
          <span className="tnum text-small text-brass-deep">
            Shop clock {hhmm(status.shop_time)}, {aheadLabel(status.minutes_ahead)} ahead
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {status.running && (
          <Segmented
            value={String(status.speed)}
            onChange={(v) => !busy && onSpeed(v)}
            options={SPEEDS}
            size="sm"
          />
        )}
        <Link
          to="/pos"
          className="inline-flex min-h-11 items-center gap-1.5 rounded-control px-2 text-small font-semibold text-board hover:bg-board-tint md:min-h-9"
        >
          <ReceiptText size={15} aria-hidden />
          Open the till
        </Link>
        <Link
          to="/alerts"
          className="inline-flex min-h-11 items-center gap-1.5 rounded-control px-2 text-small font-semibold text-board hover:bg-board-tint md:min-h-9"
        >
          <BellRing size={15} aria-hidden />
          Phone alerts
        </Link>
      </div>
    </div>
  );
}
