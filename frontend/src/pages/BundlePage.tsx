import { useEffect, useState } from 'react';
import {
  uploadSalesLines,
  generateBundles,
  fetchBundles,
  approveBundle,
  rejectBundle,
} from '../api';
import type { GenerateResult } from '../api';
import { useCurrentStore } from '../auth';
import type { BundleSuggestion } from '../types';
import { BundleCard } from '../components/BundleCard';
import { FeatureSwitcher } from '../components/FeatureSwitcher';
import {
  Button,
  EmptyState,
  Input,
  Notice,
  PageHeader,
  Segmented,
  UploadButton,
} from '../lib/ui/controls';

type StatusFilter = 'pending' | 'approved' | 'rejected' | 'all';

export function BundlesPage() {
  const storeId = useCurrentStore().store_code;
  // S2's catalogue tops out near 13.8% product margin, so a 15% floor makes
  // every bundle there impossible. 10% leaves both shops room to discount.
  const [marginFloor, setMarginFloor] = useState(0.1);
  const [bundles, setBundles] = useState<BundleSuggestion[]>([]);
  const [status, setStatus] = useState<StatusFilter>('pending');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [diag, setDiag] = useState<GenerateResult | null>(null);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      setBundles(await fetchBundles(storeId, status));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [storeId, status]);

  const onUploadLines = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setLoading(true);
      setError(null);
      await uploadSalesLines(storeId, file);
      setDiag(await generateBundles(storeId, marginFloor));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setLoading(false);
      e.target.value = '';
    }
  };

  const onRegenerate = async () => {
    try {
      setLoading(true);
      setError(null);
      setDiag(await generateBundles(storeId, marginFloor));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not work them out');
    } finally {
      setLoading(false);
    }
  };

  const onApprove = async (id: number, price?: number) => {
    await approveBundle(id, price);
    await load();
  };

  const onReject = async (id: number) => {
    await rejectBundle(id);
    await load();
  };

  return (
    <div>
      <PageHeader
        title="Bundles"
        lead="Pairs your customers already buy together, priced so you still clear your margin floor."
        action={<UploadButton onChange={onUploadLines}>Upload your bills file</UploadButton>}
      />

      <div className="space-y-6">
        <div className="flex flex-wrap items-end gap-4 rounded-section border border-rule bg-white p-4 md:p-5">
          <Input
            label="Keep at least"
            type="number"
            min={0}
            max={95}
            step={1}
            value={Math.round(marginFloor * 100)}
            onChange={(e) => setMarginFloor(Number(e.target.value) / 100)}
            className="w-24"
            hint="percent of each bundle"
          />
          <Segmented
            label="Show"
            value={status}
            onChange={(v) => setStatus(v as StatusFilter)}
            options={[
              { value: 'pending', label: 'To decide' },
              { value: 'approved', label: 'Approved' },
              { value: 'rejected', label: 'Rejected' },
              { value: 'all', label: 'All' },
            ]}
            size="sm"
          />
          <Button variant="secondary" onClick={onRegenerate} disabled={loading}>
            Work them out again
          </Button>
        </div>

        {error && <Notice>{error}</Notice>}

        {diag && diag.unmatched_sku_count > 0 && (
          <Notice tone="brass">
            {diag.unmatched_sku_count} product
            {diag.unmatched_sku_count === 1 ? '' : 's'} sold in this shop
            {diag.unmatched_sku_count === 1 ? ' is' : ' are'} missing from your price
            list, so they can never be bundled: {diag.unmatched_skus.join(', ')}.
          </Notice>
        )}

        {loading && !bundles.length && (
          <p className="text-small text-muted">Loading&hellip;</p>
        )}

        {!loading && !bundles.length && !error && (
          <EmptyState title="Nothing to decide here">
            {diag && diag.candidate_pairs ? (
              <div className="space-y-1">
                <p>
                  Found <strong>{diag.candidate_pairs}</strong> pair
                  {diag.candidate_pairs === 1 ? '' : 's'} bought together across{' '}
                  {diag.baskets} bills, but none became a bundle.
                </p>
                {!!diag.dropped_no_discount && (
                  <p>
                    <strong>{diag.dropped_no_discount}</strong> could not be discounted
                    without dropping below {Math.round(marginFloor * 100)}%. Lower that
                    and work them out again.
                  </p>
                )}
                {!!diag.dropped_missing_product && (
                  <p>
                    <strong>{diag.dropped_missing_product}</strong> involve products
                    missing from your price list.
                  </p>
                )}
              </div>
            ) : (
              <p>Upload a file of your bills so we can see what sells together.</p>
            )}
          </EmptyState>
        )}

        <div className="grid gap-4 lg:grid-cols-2">
          {bundles.map((b) => (
            <BundleCard
              key={b.id}
              bundle={b}
              onApprove={onApprove}
              onReject={onReject}
            />
          ))}
        </div>
      </div>

      <FeatureSwitcher
        to="/pools"
        label="Group buying"
        description="Buy with the shops around you and reach the wholesale rate."
      />
    </div>
  );
}
