import { useCallback, useEffect, useState } from 'react';
import { BellRing, CheckCircle2, ExternalLink, Send, Trash2 } from 'lucide-react';
import {
  fetchAlerts,
  newTelegramLink,
  removeAlertChat,
  sendTestAlert,
  setChatHourly,
} from '../api';
import { useCurrentStore } from '../auth';
import type { AlertKind, AlertsOverview, TelegramLink } from '../types';
import { Badge, Button, EmptyState, Notice, PageHeader, Section } from '../lib/ui/controls';

const REFRESH_MS = 4000;

const KIND: Record<AlertKind, { label: string; tone: 'clay' | 'brass' | 'board' | 'neutral' }> = {
  slow_hour: { label: 'Slow hour', tone: 'clay' },
  busy_hour: { label: 'Busy hour', tone: 'board' },
  behind_pace: { label: 'Behind pace', tone: 'brass' },
  ahead_pace: { label: 'Strong day', tone: 'board' },
  day_summary: { label: "Day's summary", tone: 'neutral' },
  conversion_drop: { label: 'Few buyers', tone: 'clay' },
};

/** "2026-09-30T14:05:09" -> "30 Sep, 14:05". */
function when(iso: string): string {
  const d = new Date(iso);
  const day = d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  return `${day}, ${iso.slice(11, 16)}`;
}

function linkedOn(iso: string): string {
  // Stored in UTC without a zone marker.
  return new Date(`${iso}Z`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
}

/**
 * Phone alerts for the logged-in shop: connect Telegram, and see every alert
 * the shop has raised -- sent or not, so the page is useful before Telegram
 * is set up too.
 */
export function AlertsPage() {
  const me = useCurrentStore();
  const [data, setData] = useState<AlertsOverview | null>(null);
  const [link, setLink] = useState<TelegramLink | null>(null);
  const [linkedCount, setLinkedCount] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await fetchAlerts();
      setData(next);
      return next;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load alerts');
      return null;
    }
  }, []);

  useEffect(() => {
    let alive = true;
    const tick = () =>
      fetchAlerts()
        .then((d) => alive && setData(d))
        .catch((e) => alive && setError(e instanceof Error ? e.message : 'Could not load alerts'));
    tick();
    const id = window.setInterval(tick, REFRESH_MS);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  // While a link is out, the new chat shows up in the next refresh: close
  // the link and say who got connected.
  const chats = data?.chats ?? [];
  if (link && linkedCount != null && chats.length > linkedCount) {
    setLink(null);
    setLinkedCount(null);
    setNote(`Connected: ${chats[chats.length - 1].title}. Alerts for ${me.store_code} will arrive there.`);
  }

  const onConnect = async () => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const l = await newTelegramLink();
      setLink(l);
      setLinkedCount(chats.length);
      if (l.url) window.open(l.url, '_blank', 'noopener');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not make a link');
    } finally {
      setBusy(false);
    }
  };

  const onTest = async () => {
    setBusy(true);
    setError(null);
    try {
      const { delivered } = await sendTestAlert();
      setNote(`Test message sent to ${delivered} chat${delivered === 1 ? '' : 's'}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not send a test');
    } finally {
      setBusy(false);
    }
  };

  const onHourly = async (id: number, hourly: boolean) => {
    setError(null);
    // Tick at once; the server catches up a moment later.
    setData((d) => d && { ...d, chats: d.chats.map((c) => (c.id === id ? { ...c, hourly } : c)) });
    try {
      await setChatHourly(id, hourly);
      setNote(hourly ? 'Hourly updates on for that chat.' : 'Hourly updates off for that chat.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change that');
      await refresh();
    }
  };

  const onRemove = async (id: number, title: string) => {
    setError(null);
    try {
      await removeAlertChat(id);
      setNote(`${title} won't get alerts any more.`);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not remove that chat');
    }
  };

  const telegram = data?.telegram;
  const recent = data?.recent ?? [];

  return (
    <div>
      <PageHeader
        title="Phone alerts"
        lead="A Telegram message when an hour is slow or busy, when the day is well behind or ahead of a usual one, and a summary after closing."
      />

      <div className="space-y-6">
        {error && <Notice>{error}</Notice>}
        {note && !error && <Notice tone="board">{note}</Notice>}

        <Section title="Telegram">
          {telegram && !telegram.configured && (
            <div className="space-y-3 text-small text-muted">
              <Notice tone="neutral">
                Telegram isn&apos;t set up on the server yet. Alerts are still worked out and
                listed below; they just aren&apos;t sent anywhere.
              </Notice>
              <ol className="list-decimal space-y-1 pl-5">
                <li>
                  In Telegram, message <span className="font-semibold text-ink">@BotFather</span>,
                  send <code className="rounded bg-chalk px-1">/newbot</code> and follow the steps.
                </li>
                <li>
                  Put the token it gives you in <code className="rounded bg-chalk px-1">backend/.env</code>{' '}
                  as <code className="rounded bg-chalk px-1">TELEGRAM_BOT_TOKEN=...</code>
                </li>
                <li>Restart the backend, then come back here and connect.</li>
              </ol>
            </div>
          )}

          {telegram?.configured && (
            <div className="space-y-4">
              {telegram.error && <Notice tone="brass">{telegram.error}</Notice>}

              {chats.length === 0 ? (
                <p className="text-small text-muted">
                  No phone connected yet. Connect the shop owner&apos;s Telegram, or a group
                  with the staff in it.
                </p>
              ) : (
                <ul className="divide-y divide-rule">
                  {chats.map((c) => (
                    <li key={c.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                      <CheckCircle2 size={16} className="text-board" aria-hidden />
                      <span className="min-w-0 flex-1 truncate text-body text-ink">
                        {c.title}
                        <span className="ml-2 text-small text-muted">since {linkedOn(c.linked_at)}</span>
                      </span>
                      <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 text-small text-ink md:min-h-9">
                        <input
                          type="checkbox"
                          className="h-4 w-4 accent-board"
                          checked={c.hourly}
                          onChange={(e) => onHourly(c.id, e.target.checked)}
                        />
                        Hourly updates
                      </label>
                      <Button
                        variant="quiet"
                        size="sm"
                        aria-label={`Stop alerts to ${c.title}`}
                        onClick={() => onRemove(c.id, c.title)}
                      >
                        <Trash2 size={15} aria-hidden />
                      </Button>
                    </li>
                  ))}
                </ul>
              )}

              {link && (
                <div className="rounded-item border border-board/25 bg-board-tint px-4 py-3 text-small text-ink">
                  {link.url ? (
                    <>
                      <p>
                        Telegram should have opened. Tap <b>Start</b> in the chat with{' '}
                        <b>@{link.bot_username}</b>. This page updates by itself once it&apos;s done.
                      </p>
                      <a
                        href={link.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-2 inline-flex items-center gap-1.5 font-semibold text-board underline-offset-2 hover:underline"
                      >
                        Open Telegram again <ExternalLink size={14} aria-hidden />
                      </a>
                    </>
                  ) : (
                    <p>The bot is still starting up. Try again in a few seconds.</p>
                  )}
                  <p className="mt-2 text-muted">
                    On another phone? Send{' '}
                    <code className="rounded bg-white px-1 text-ink">/start {link.code}</code> to
                    the bot. The link works once, for 15 minutes.
                  </p>
                </div>
              )}

              <div className="flex flex-wrap gap-2">
                <Button onClick={onConnect} disabled={busy}>
                  <BellRing size={15} aria-hidden />
                  {chats.length ? 'Connect another chat' : 'Connect Telegram'}
                </Button>
                {chats.length > 0 && (
                  <Button variant="secondary" onClick={onTest} disabled={busy}>
                    <Send size={15} aria-hidden />
                    Send a test message
                  </Button>
                )}
              </div>
            </div>
          )}
        </Section>

        <Section title="What gets sent">
          <ul className="space-y-1.5 text-body text-ink">
            <li>
              <Badge tone="clay">Slow hour</Badge> fewer people came in than usual, or fewer of
              them bought.
            </li>
            <li>
              <Badge tone="board">Busy hour</Badge> an hour took well over its usual.
            </li>
            <li>
              <Badge tone="brass">Behind pace</Badge> or <Badge tone="board">Strong day</Badge>{' '}
              the day is well behind or ahead of a usual one. Once a day.
            </li>
            <li>
              <Badge tone="neutral">Day&apos;s summary</Badge> after the usual closing time.
            </li>
          </ul>
          <p className="mt-3 text-small text-muted">
            An ordinary day stays quiet on purpose. To see alerts now, go to the dashboard, set{' '}
            <b>Demo day</b> to Slow or Busy and pick 60&times;: the next hour that ends sends one.
            Tick <b>Hourly updates</b> for a short message after every hour as well.
          </p>
        </Section>

        <Section title="Recent alerts">
          {recent.length === 0 ? (
            <EmptyState title="Nothing to report yet">
              Alerts appear here as the day goes. Try 300&times; on the live dashboard to run
              the day forward.
            </EmptyState>
          ) : (
            <ul className="divide-y divide-rule">
              {recent.map((a) => (
                <li key={a.id} className="py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={KIND[a.kind]?.tone ?? 'neutral'}>
                      {KIND[a.kind]?.label ?? a.kind}
                    </Badge>
                    <span className="tnum text-small text-muted">{when(a.shop_time)}</span>
                    <span className="ml-auto text-small text-muted">
                      {a.delivered
                        ? `Sent to ${a.delivered} chat${a.delivered === 1 ? '' : 's'}`
                        : 'Not sent'}
                    </span>
                  </div>
                  <p className="mt-1.5 whitespace-pre-line text-body text-ink">{a.text}</p>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
    </div>
  );
}
