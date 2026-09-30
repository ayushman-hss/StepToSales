import { useEffect, useState } from 'react';
import { uploadProductCatalog, fetchProducts } from '../api';
import { useCurrentStore } from '../auth';
import type { Product } from '../types';
import { ProductTable } from '../components/ProductTable';
import { FeatureSwitcher } from '../components/FeatureSwitcher';
import { ThresholdBar } from '../lib/ui/ThresholdBar';
import {
  EmptyState,
  Notice,
  PageHeader,
  UploadButton,
} from '../lib/ui/controls';

const FLOOR = 10; // the margin floor the bundle pricer defaults to

export function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const storeId = useCurrentStore().store_code;
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      setProducts(await fetchProducts(storeId));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [storeId]);

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setLoading(true);
      setError(null);
      await uploadProductCatalog(storeId, file);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setLoading(false);
      e.target.value = '';
    }
  };

  const margins = products.map((p) => p.margin_pct * 100).sort((a, b) => a - b);
  const median = margins.length ? margins[Math.floor(margins.length / 2)] : 0;
  const thin = margins.filter((m) => m < FLOOR).length;

  return (
    <div>
      <PageHeader
        title="Products"
        lead="Set what you pay and what you charge. Every bundle price is built from these two numbers."
        action={<UploadButton onChange={onUpload}>Upload your price list</UploadButton>}
      />

      <div className="space-y-6">
        {error && <Notice>{error}</Notice>}
        {loading && !products.length && (
          <p className="text-small text-muted">Loading&hellip;</p>
        )}

        {!loading && !products.length && !error && (
          <EmptyState title="No products yet">
            Upload a spreadsheet with a code, name, cost price and selling price for each
            product you stock.
          </EmptyState>
        )}

        {products.length > 0 && (
          <>
            <div className="max-w-xl">
              <p className="text-body text-ink">
                Half your {products.length} products keep{' '}
                <strong className="font-semibold">{median.toFixed(1)}%</strong> or more.
              </p>
              <div className="mt-3">
                <ThresholdBar
                  value={median}
                  max={Math.max(40, median * 1.3)}
                  threshold={FLOOR}
                  thresholdLabel={`floor ${FLOOR}%`}
                  minLabel="0%"
                  maxLabel={`${Math.max(40, Math.round(median * 1.3))}%`}
                  caption={
                    thin
                      ? `${thin} of them sit below the ${FLOOR}% floor, so they cannot be discounted into a bundle.`
                      : `Every product clears the ${FLOOR}% floor, so all of them can go into a bundle.`
                  }
                />
              </div>
            </div>

            <ProductTable products={products} />
          </>
        )}
      </div>

      <FeatureSwitcher
        to="/bundles"
        label="Bundles"
        description="See which of these to pair up, and at what price."
      />
    </div>
  );
}
