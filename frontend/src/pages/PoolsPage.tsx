import { useCallback, useEffect, useState } from 'react';
import { Lock, RotateCcw, ScrollText } from 'lucide-react';
import clsx from 'clsx';
import {
  fetchPool,
  placePoolOrder,
  withdrawFromPool,
  closePool,
  reopenPool,
  fetchPoolEvents,
} from '../api';
import type { PoolDetail, PoolEvent, PoolProduct, PoolStrategy } from '../types';
import { formatPaise } from '../lib/money';
import { useCurrentStore } from '../auth';
import { ThresholdBar } from '../lib/ui/ThresholdBar';
import {
  Badge,
  Button,
  EmptyState,
  Figure,
  Input,
  Notice,
  PageHeader,
  Section,
  Segmented,
  Select,
} from '../lib/ui/controls';

const POOL_CODE = 'koramangala';

const STRATEGIES: { value: PoolStrategy; label: string; blurb: string }[] = [
  {
    value: 'pro_rata',
    label: 'By order size',
    blurb:
      'The saving is shared in proportion to how much each shop ordered. This is what most buying groups do.',
  },
  {
    value: 'shapley',
    label: 'By contribution',
    blurb:
      'The saving is shared by how much each shop actually helped reach the tier. Fairer when one shop’s volume is what unlocks the rate.',
  },
  {
    value: 'unit_price',
    label: 'Same rate for all',
    blurb:
      'Everyone simply pays the group rate. A shop that already qualified alone saves nothing while the others ride on its volume.',
  },
];

const STATUS: Record<string, { tone: 'board' | 'brass' | 'neutral' | 'clay'; label: string }> = {
  open: { tone: 'board', label: 'Open' },
  locked: { tone: 'brass', label: 'Locked' },
  settled: { tone: 'neutral', label: 'Closed' },
  cancelled: { tone: 'clay', label: 'Cancelled' },
  draft: { tone: 'neutral', label: 'Draft' },
};

/** "Butter - Pasteurised" is supplier data, not a label we should echo. */
const clean = (name: string) => name.replace(/\s+-\s+/g, ', ');

function TierLadder({ product }: { product: PoolProduct }) {
  return (
    <ol className="space-y-1">
      {product.tiers.map((tier) => {
        const here = tier.label === product.tier_label;
        return (
          <li
            key={tier.label}
            className={clsx(
              'flex items-center justify-between rounded-[6px] px-3 py-1.5 text-small',
              here ? 'bg-board text-white font-semibold' : 'text-muted',
            )}
          >
            <span>{tier.label} units</span>
            <span className="tnum">{formatPaise(tier.unit_price)} each</span>
          </li>
        );
      })}
    </ol>
  );
}

export function PoolsPage() {
  const [strategy, setStrategy] = useState<PoolStrategy>('pro_rata');
  const [pool, setPool] = useState<PoolDetail | null>(null);
  const [events, setEvents] = useState<PoolEvent[]>([]);
  const [showLog, setShowLog] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Orders are always placed as the logged-in shop; the server refuses any other.
  const store = useCurrentStore().store_code;
  const [sku, setSku] = useState('');
  const [qty, setQty] = useState(10);

  const run = useCallback(async (fn: () => Promise<PoolDetail>) => {
    try {
      setBusy(true);
      setError(null);
      setPool(await fn());
      setEvents(await fetchPoolEvents(POOL_CODE));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong');
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    run(() => fetchPool(POOL_CODE, strategy));
  }, [strategy, run]);

  const frozen = pool ? pool.status !== 'open' : false;
  const active = STRATEGIES.find((s) => s.value === strategy)!;
  const badge = pool ? (STATUS[pool.status] ?? STATUS.draft) : STATUS.draft;

  return (
    <div>
      <PageHeader
        title="Group buying"
        lead="Order alongside the shops near you. Your orders are added together to reach the wholesale rate, but each shop still gets only what it ordered."
      />

      {error && <Notice>{error}</Notice>}

      {pool && (
        <div className="space-y-8">
          {/* --- the pool itself ------------------------------------- */}
          <section>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2.5">
                  <h2 className="text-heading">{pool.name}</h2>
                  <Badge tone={badge.tone}>{badge.label}</Badge>
                </div>
                <p className="mt-1 text-small text-muted">
                  {pool.stores.length} shops&nbsp;&nbsp; {pool.products.length} products
                  {pool.rotation > 0 && <>&nbsp;&nbsp; round {pool.rotation + 1}</>}
                </p>
              </div>

              {pool.status === 'open' ? (
                <Button
                  onClick={() => run(() => closePool(POOL_CODE, strategy))}
                  disabled={busy || !pool.products.length}
                >
                  <Lock size={15} aria-hidden />
                  Close this order
                </Button>
              ) : (
                <Button
                  variant="secondary"
                  onClick={() => run(() => reopenPool(POOL_CODE, strategy))}
                  disabled={busy}
                >
                  <RotateCcw size={15} aria-hidden />
                  Start the next round
                </Button>
              )}
            </div>

            <div className="mt-6 flex flex-wrap gap-x-12 gap-y-5">
              <Figure
                size="hero"
                tone="board"
                value={formatPaise(pool.total_savings, { compact: true })}
                label="saved by the group"
              />
              <Figure
                value={formatPaise(pool.invoice_total, { compact: true })}
                label="one bill to the supplier"
              />
            </div>
          </section>

          {/* --- how the saving is shared ----------------------------- */}
          <Section title="How the saving is shared">
            <Segmented
              value={strategy}
              onChange={setStrategy}
              options={STRATEGIES.map((s) => ({ value: s.value, label: s.label }))}
              size="sm"
            />
            <p className="mt-2.5 text-small text-muted">{active.blurb}</p>

            <table className="mt-5 w-full text-body">
              <thead>
                <tr className="border-b border-rule text-left text-small text-muted">
                  <th scope="col" className="pb-2 font-medium">Shop</th>
                  <th scope="col" className="pb-2 text-right font-medium">On its own</th>
                  <th scope="col" className="pb-2 text-right font-medium">Pays now</th>
                  <th scope="col" className="pb-2 text-right font-medium">Saves</th>
                </tr>
              </thead>
              <tbody>
                {pool.stores.map((s) => (
                  <tr key={s.store} className="border-b border-rule last:border-0">
                    <td className="py-2.5 font-medium">
                      {s.store}
                      {s.store === store && (
                        <span className="ml-2 align-middle">
                          <Badge tone="board">You</Badge>
                        </span>
                      )}
                    </td>
                    <td className="py-2.5 text-right text-muted">
                      {formatPaise(s.cost_alone, { compact: true })}
                    </td>
                    <td className="py-2.5 text-right">
                      {formatPaise(s.payable, { compact: true })}
                    </td>
                    <td
                      className={clsx(
                        'py-2.5 text-right font-semibold',
                        s.savings > 0 ? 'text-board' : 'text-muted',
                      )}
                    >
                      {formatPaise(s.savings, { compact: true })}
                      <span className="ml-1.5 font-normal text-muted">
                        {s.savings_pct.toFixed(1)}%
                      </span>
                    </td>
                  </tr>
                ))}
                <tr className="text-small text-muted">
                  <td className="pt-3">Everyone</td>
                  <td />
                  <td className="pt-3 text-right">
                    {formatPaise(pool.invoice_total, { compact: true })}
                  </td>
                  <td className="pt-3 text-right">
                    {formatPaise(pool.total_savings, { compact: true })}
                  </td>
                </tr>
              </tbody>
            </table>
          </Section>

          {/* --- place an order --------------------------------------- */}
          <Section title="Add to this order">
            <p className="mb-3 text-small text-muted">
              Ordering as <strong className="font-semibold text-ink">{store}</strong>.
              Other shops add their own orders when they log in.
            </p>
            <div className="flex flex-wrap items-end gap-3">
              <Select
                label="Product"
                value={sku}
                onChange={(e) => setSku(e.target.value)}
                disabled={frozen}
                className="min-w-56 flex-1"
              >
                <option value="">Choose a product</option>
                {pool.products.map((p) => (
                  <option key={p.sku} value={p.sku}>
                    {clean(p.name)}
                  </option>
                ))}
              </Select>
              <Input
                label="How many"
                type="number"
                inputMode="numeric"
                min={1}
                value={qty}
                onChange={(e) => setQty(Number(e.target.value))}
                disabled={frozen}
                className="w-24"
              />
              <Button
                onClick={() =>
                  run(() =>
                    placePoolOrder(POOL_CODE, strategy, { store_id: store, sku, qty }),
                  )
                }
                disabled={frozen || busy || !sku}
              >
                Add order
              </Button>
              <Button
                variant="quiet"
                onClick={() =>
                  run(() =>
                    withdrawFromPool(POOL_CODE, strategy, {
                      store_id: store,
                      sku: sku || undefined,
                    }),
                  )
                }
                disabled={frozen || busy}
              >
                Take out
              </Button>
            </div>

            {/* A disabled control always says why. */}
            {frozen ? (
              <p className="mt-3 text-small text-muted">
                This order is {badge.label.toLowerCase()}, so nothing can change. Start
                the next round to add more.
              </p>
            ) : (
              !sku && (
                <p className="mt-3 text-small text-muted">Choose a product first.</p>
              )
            )}
          </Section>

          {/* --- per product ------------------------------------------ */}
          <div className="grid gap-4 lg:grid-cols-2">
            {pool.products.map((p) => (
              <article key={p.sku} className="rounded-item border border-rule bg-white p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-heading leading-snug">{clean(p.name)}</h3>
                    <p className="mt-0.5 text-small text-muted">
                      {p.sku} &nbsp; from {p.supplier_id}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="tnum text-heading">{p.total_qty} units</p>
                    <p className="text-small text-muted">
                      {formatPaise(p.pooled_unit_price)} each
                    </p>
                  </div>
                </div>

                <div className="mt-4">
                  <TierLadder product={p} />
                </div>

                <div className="mt-4">
                  {p.units_to_next_tier != null && p.next_tier_unit_price != null ? (
                    <ThresholdBar
                      tone="brass"
                      value={p.total_qty}
                      max={p.total_qty + p.units_to_next_tier}
                      caption={
                        <>
                          <strong className="font-semibold text-ink">
                            {p.units_to_next_tier} more units
                          </strong>{' '}
                          and everyone pays {formatPaise(p.next_tier_unit_price)} each.
                        </>
                      }
                    />
                  ) : (
                    <p className="text-small text-board">
                      Cheapest rate reached. Ordering more will not lower it further.
                    </p>
                  )}
                </div>

                <table className="mt-4 w-full text-small">
                  <thead>
                    <tr className="border-b border-rule text-left text-muted">
                      <th scope="col" className="pb-1.5 font-medium">Shop</th>
                      <th scope="col" className="pb-1.5 text-right font-medium">Units</th>
                      <th scope="col" className="pb-1.5 text-right font-medium">Pays</th>
                      <th scope="col" className="pb-1.5 text-right font-medium">Saves</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.lines.map((l) => (
                      <tr key={l.store} className="border-b border-rule last:border-0">
                        <td className="py-1.5">{l.store}</td>
                        <td className="py-1.5 text-right">{l.qty}</td>
                        <td className="py-1.5 text-right">
                          {formatPaise(l.payable, { compact: true })}
                        </td>
                        <td
                          className={clsx(
                            'py-1.5 text-right font-medium',
                            l.savings > 0 ? 'text-board' : 'text-muted',
                          )}
                        >
                          {formatPaise(l.savings, { compact: true })}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </article>
            ))}
          </div>

          {!pool.products.length && (
            <EmptyState title="No orders in this round yet">
              Add one above to see how close the group is to the next rate.
            </EmptyState>
          )}

          {/* --- audit trail ------------------------------------------ */}
          <Section>
            <button
              onClick={() => setShowLog((v) => !v)}
              aria-expanded={showLog}
              className="inline-flex min-h-11 items-center gap-2 text-body font-medium text-board md:min-h-0"
            >
              <ScrollText size={16} aria-hidden />
              {showLog ? 'Hide' : 'Show'} the record ({events.length})
            </button>
            {showLog && (
              <ul className="mt-4 max-h-64 space-y-1 overflow-auto rounded-item bg-chalk p-4 text-small">
                {events.map((e, i) => (
                  <li key={i} className="flex flex-wrap gap-x-4 text-muted">
                    <span className="tnum">{e.created_at.replace('T', ' ')}</span>
                    <span className="font-medium text-ink">{e.actor}</span>
                    <span>{e.kind}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-small text-muted">
              Every order and every closing is written down and never changed, so if
              anyone disagrees later you can show exactly what happened.
            </p>
          </Section>
        </div>
      )}
    </div>
  );
}
