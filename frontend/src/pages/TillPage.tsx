import { useEffect, useMemo, useState } from 'react';
import { Minus, Plus, UserPlus } from 'lucide-react';
import {
  countVisitor,
  fetchProducts,
  fetchRecentBills,
  newEventId,
  ringBill,
} from '../api';
import { useCurrentStore } from '../auth';
import type { Product, RecentBill } from '../types';
import { formatPaise } from '../lib/money';
import {
  Badge,
  Button,
  EmptyState,
  Input,
  Notice,
  PageHeader,
  Section,
} from '../lib/ui/controls';

const paise = (rupees: number) => Math.round(rupees * 100);
/** "Butter - Pasteurised" is supplier data, not a label to echo. */
const clean = (name: string) =>
  name.split(/\s-\s/).map((part) => part.trim()).join(', ');

/**
 * A phone till for the logged-in shop. Every bill lands on the live
 * dashboard within seconds, priced from the shop's own price list on the
 * server -- the phone only says what and how many.
 */
export function TillPage() {
  const me = useCurrentStore();
  const [products, setProducts] = useState<Product[]>([]);
  const [query, setQuery] = useState('');
  const [cart, setCart] = useState<Record<string, number>>({});
  // One id per bill, kept until it is recorded: a retry after a dropped
  // connection resends the same id, so the bill still counts once.
  const [billId, setBillId] = useState(newEventId);
  const [recent, setRecent] = useState<RecentBill[]>([]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [visitors, setVisitors] = useState(0);

  useEffect(() => {
    fetchProducts(me.store_code)
      .then(setProducts)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load products'));
  }, [me.store_code]);

  useEffect(() => {
    let alive = true;
    const tick = () =>
      fetchRecentBills(8)
        .then((b) => alive && setRecent(b))
        .catch(() => undefined);
    void tick();
    const id = window.setInterval(tick, 4000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const bySku = useMemo(() => new Map(products.map((p) => [p.sku, p])), [products]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return products
      .filter((p) => !q || p.name.toLowerCase().includes(q) || p.sku.toLowerCase().includes(q))
      .slice(0, 24);
  }, [products, query]);

  const lines = Object.entries(cart).filter(([, qty]) => qty > 0);
  const total = lines.reduce(
    (sum, [sku, qty]) => sum + qty * paise(bySku.get(sku)?.sell_price ?? 0),
    0,
  );

  const add = (sku: string, delta: number) =>
    setCart((c) => ({ ...c, [sku]: Math.max(0, Math.min(99, (c[sku] ?? 0) + delta)) }));

  const onRing = async () => {
    setBusy(true);
    setError(null);
    try {
      const receipt = await ringBill(
        billId,
        lines.map(([sku, qty]) => ({ sku, qty })),
      );
      setDone(`Rung up ${formatPaise(receipt.amount_paise)} at ${receipt.at.slice(11, 16)}.`);
      setCart({});
      setBillId(newEventId());
      setRecent(await fetchRecentBills(8));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not ring that up. Try again.');
    } finally {
      setBusy(false);
    }
  };

  const onVisitor = async () => {
    try {
      await countVisitor(newEventId());
      setVisitors((v) => v + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not count that visitor');
    }
  };

  return (
    <div>
      <PageHeader
        title="Till"
        lead={`Ring up a sale for ${me.store_code} and it shows on the live dashboard within seconds. Every bill also counts one visitor.`}
      />

      <div className="space-y-6">
        {error && <Notice>{error}</Notice>}
        {done && !error && <Notice tone="board">{done}</Notice>}

        <Section title="This bill">
          {lines.length === 0 ? (
            <p className="text-small text-muted">Tap products below to add them.</p>
          ) : (
            <ul className="divide-y divide-rule">
              {lines.map(([sku, qty]) => {
                const p = bySku.get(sku);
                return (
                  <li key={sku} className="flex items-center gap-3 py-2">
                    <span className="min-w-0 flex-1 truncate text-body">
                      {p ? clean(p.name) : sku}
                    </span>
                    <span className="flex items-center gap-1">
                      <button
                        type="button"
                        aria-label={`One less ${p?.name ?? sku}`}
                        onClick={() => add(sku, -1)}
                        className="flex h-11 w-11 items-center justify-center rounded-control border border-rule md:h-9 md:w-9"
                      >
                        <Minus size={15} aria-hidden />
                      </button>
                      <span className="tnum w-7 text-center font-semibold">{qty}</span>
                      <button
                        type="button"
                        aria-label={`One more ${p?.name ?? sku}`}
                        onClick={() => add(sku, 1)}
                        className="flex h-11 w-11 items-center justify-center rounded-control border border-rule md:h-9 md:w-9"
                      >
                        <Plus size={15} aria-hidden />
                      </button>
                    </span>
                    <span className="tnum w-20 text-right text-body">
                      {formatPaise(qty * paise(p?.sell_price ?? 0))}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}

          <Button block className="mt-4" disabled={!lines.length || busy} onClick={onRing}>
            {busy
              ? 'Ringing up…'
              : lines.length
                ? `Ring up ${formatPaise(total)}`
                : 'Ring up'}
          </Button>
          <Button variant="secondary" block className="mt-2" onClick={onVisitor}>
            <UserPlus size={15} aria-hidden />
            Someone walked in and did not buy
            {visitors > 0 && <span className="tnum text-muted">({visitors})</span>}
          </Button>
        </Section>

        <Section title="Products">
          <Input
            label="Find a product"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            wrapClassName="mb-4"
            className="w-full"
          />
          {products.length === 0 ? (
            <EmptyState title="No products in your price list">
              Upload one on the Products page first.
            </EmptyState>
          ) : (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {shown.map((p) => (
                <button
                  key={p.sku}
                  type="button"
                  onClick={() => add(p.sku, 1)}
                  className="min-h-16 rounded-item border border-rule bg-white px-3 py-2 text-left transition-colors hover:border-board active:bg-board-tint"
                >
                  <span className="line-clamp-2 text-small font-medium text-ink">
                    {clean(p.name)}
                  </span>
                  <span className="tnum mt-0.5 block text-small text-muted">
                    {formatPaise(paise(p.sell_price))}
                    {cart[p.sku] ? (
                      <span className="ml-2 font-semibold text-board">×{cart[p.sku]}</span>
                    ) : null}
                  </span>
                </button>
              ))}
            </div>
          )}
        </Section>

        {/* On a phone the bill scrolls away while you tap products, so the
            ring-up button follows you, just above the tab bar. */}
        {lines.length > 0 && (
          <div
            className="fixed inset-x-0 z-10 px-5 md:hidden"
            style={{ bottom: 'calc(4.75rem + env(safe-area-inset-bottom))' }}
          >
            <Button block disabled={busy} onClick={onRing} className="shadow-lg">
              {busy ? 'Ringing up\u2026' : `Ring up ${formatPaise(total)}`}
            </Button>
          </div>
        )}

        <Section title="Latest bills">
          {recent.length === 0 ? (
            <p className="text-small text-muted">No live bills yet today.</p>
          ) : (
            <ul className="divide-y divide-rule">
              {recent.map((b, i) => (
                <li key={`${b.at}-${i}`} className="flex items-center gap-3 py-2 text-small">
                  <span className="tnum w-12 text-muted">{b.at.slice(11, 16)}</span>
                  <span className="min-w-0 flex-1 truncate text-ink">
                    {b.lines.map((l) => `${l.qty}× ${clean(l.name)}`).join(', ')}
                  </span>
                  <Badge tone={b.source === 'pos' ? 'board' : 'neutral'}>
                    {b.source === 'pos' ? 'till' : 'simulated'}
                  </Badge>
                  <span className="tnum w-20 text-right font-medium">
                    {formatPaise(b.amount_paise)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
    </div>
  );
}
