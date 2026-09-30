import type { DashboardData } from './types';
import type { Product, BundleSuggestion } from './types';
import type { PoolDetail, PoolStrategy, PoolEvent as PoolEventRow } from './types';
import type { LiveSpeed, LiveStatus, RecentBill } from './types';
import { useAuth, type Me } from './auth';

// ---- auth ---------------------------------------------------------------

const EXPIRED = 'Your session has ended. Log in again.';

/**
 * fetch() with the login attached. Every call after login goes through here,
 * so a 401 anywhere -- an expired or revoked session -- signs the browser out
 * in one place and the router sends it to the login page.
 */
async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const { token, signedOut } = useAuth.getState();
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401) {
    signedOut(token ? EXPIRED : null);
  }
  return res;
}

async function errorDetail(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => ({}));
  return typeof body.detail === 'string' ? body.detail : fallback;
}

export async function login(username: string, password: string): Promise<void> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    throw new Error(
      res.status === 401
        ? 'That username and password do not match.'
        : await errorDetail(res, 'Could not log in. Is the server running?'),
    );
  }
  const { token, store_code, store_name } = await res.json();
  useAuth.getState().signedIn(token, { store_code, store_name });
}

export async function logout(): Promise<void> {
  const { token, signedOut } = useAuth.getState();
  // Forget locally first: logging out must work even if the server is down.
  signedOut();
  if (token) {
    await fetch('/api/auth/logout', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    }).catch(() => undefined);
  }
}

/** Confirm a token saved from an earlier visit is still good. */
export async function restoreSession(): Promise<void> {
  const { token, confirmed, unreachable } = useAuth.getState();
  if (!token) return;
  try {
    const res = await apiFetch('/api/auth/me');
    if (res.ok) confirmed((await res.json()) as Me);
    else if (res.status !== 401) unreachable();
  } catch {
    unreachable();
  }
}

// ---- sales vs footfall --------------------------------------------------

export interface HoursUploadResult {
  upload_id: number;
  rows: number;
  stores: string[];
  date_range: [string, string];
  /** Rows for other shops in a combined file; the server does not load them. */
  skipped_rows: number;
}

export async function uploadExcel(file: File): Promise<HoursUploadResult> {
  const form = new FormData();
  form.append('file', file);
  const res = await apiFetch('/api/upload', { method: 'POST', body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? 'Upload failed');
  }
  return res.json();
}

/** No shop here: the server always answers for the logged-in one. */
export interface DashboardParams {
  start_date?: string;
  end_date?: string;
}

export async function fetchDashboard(params: DashboardParams = {}): Promise<DashboardData> {
  const qs = new URLSearchParams();
  if (params.start_date) qs.set('start_date', params.start_date);
  if (params.end_date) qs.set('end_date', params.end_date);

  const res = await apiFetch(`/api/dashboard?${qs.toString()}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? 'Fetch failed');
  }
  return res.json();
}

export async function uploadProductCatalog(storeId: string, file: File) {
  const form = new FormData();
  form.append('file', file);
  const res = await apiFetch(`/api/products/upload?store_id=${storeId}`, {
    method: 'POST', body: form,
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? 'Upload failed');
  return res.json();
}

export async function fetchProducts(storeId: string): Promise<Product[]> {
  const res = await apiFetch(`/api/products?store_id=${storeId}`);
  if (!res.ok) throw new Error('Failed to load products');
  return res.json();
}

export async function uploadSalesLines(
  storeId: string,
  file: File,
  mode: 'replace' | 'append' = 'replace',
) {
  const form = new FormData();
  form.append('file', file);
  const res = await apiFetch(
    `/api/bundles/upload-lines?store_id=${storeId}&mode=${mode}`,
    { method: 'POST', body: form },
  );
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? 'Upload failed');
  return res.json();
}

export interface GenerateResult {
  suggestions: number;
  decisions_kept: number;
  baskets: number;
  min_support_tx: number;
  min_lift: number;
  unmatched_sku_count: number;
  unmatched_skus: string[];
  candidate_pairs?: number;
  dropped_missing_product?: number;
  dropped_no_discount?: number;
}

export async function generateBundles(
  storeId: string,
  marginFloorPct: number,
): Promise<GenerateResult> {
  const res = await apiFetch(
    `/api/bundles/generate?store_id=${storeId}&margin_floor_pct=${marginFloorPct}`,
    { method: 'POST' },
  );
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? 'Generate failed');
  return res.json();
}

export async function fetchBundles(storeId: string, status: string): Promise<BundleSuggestion[]> {
  const res = await apiFetch(`/api/bundles?store_id=${storeId}&status=${status}`);
  if (!res.ok) throw new Error('Failed to load bundles');
  return res.json();
}

export async function approveBundle(id: number, price?: number) {
  const res = await apiFetch(`/api/bundles/${id}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ price }),
  });
  if (!res.ok) throw new Error('Approve failed');
  return res.json();
}

export async function rejectBundle(id: number) {
  const res = await apiFetch(`/api/bundles/${id}/reject`, { method: 'POST' });
  if (!res.ok) throw new Error('Reject failed');
  return res.json();
}
// ---- group-buying pools -------------------------------------------------

async function poolJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    throw new Error((await res.json().catch(() => ({}))).detail ?? 'Request failed');
  }
  return res.json();
}

export async function fetchPool(
  code: string,
  strategy: PoolStrategy,
): Promise<PoolDetail> {
  return poolJson(await apiFetch(`/api/pools/${code}?strategy=${strategy}`));
}

export async function placePoolOrder(
  code: string,
  strategy: PoolStrategy,
  body: { store_id: string; sku: string; qty: number },
): Promise<PoolDetail> {
  return poolJson(
    await apiFetch(`/api/pools/${code}/orders?strategy=${strategy}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  );
}

export async function withdrawFromPool(
  code: string,
  strategy: PoolStrategy,
  body: { store_id: string; sku?: string },
): Promise<PoolDetail> {
  return poolJson(
    await apiFetch(`/api/pools/${code}/withdraw?strategy=${strategy}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  );
}

export async function closePool(
  code: string,
  strategy: PoolStrategy,
): Promise<PoolDetail> {
  return poolJson(
    await apiFetch(`/api/pools/${code}/close?strategy=${strategy}`, { method: 'POST' }),
  );
}

export async function reopenPool(
  code: string,
  strategy: PoolStrategy,
): Promise<PoolDetail> {
  return poolJson(
    await apiFetch(`/api/pools/${code}/reopen?strategy=${strategy}`, { method: 'POST' }),
  );
}

export async function fetchPoolEvents(code: string): Promise<PoolEventRow[]> {
  return poolJson(await apiFetch(`/api/pools/${code}/events`));
}

// ---- live mode ------------------------------------------------------------

export async function fetchLiveStatus(): Promise<LiveStatus> {
  return poolJson(await apiFetch('/api/live/status'));
}

export async function setLiveSpeed(speed: LiveSpeed): Promise<LiveStatus> {
  return poolJson(
    await apiFetch('/api/live/speed', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speed }),
    }),
  );
}

/** One id per bill, made on the phone, so a retried tap is counted once. */
export function newEventId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export interface TillReceipt {
  recorded: boolean;
  amount_paise: number;
  at: string;
}

export async function ringBill(
  eventId: string,
  lines: { sku: string; qty: number }[],
): Promise<TillReceipt> {
  return poolJson(
    await apiFetch('/api/live/bill', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_id: eventId, lines }),
    }),
  );
}

export async function countVisitor(eventId: string): Promise<TillReceipt> {
  return poolJson(
    await apiFetch('/api/live/visit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_id: eventId }),
    }),
  );
}

export async function fetchRecentBills(limit = 8): Promise<RecentBill[]> {
  return poolJson(await apiFetch(`/api/live/bills?limit=${limit}`));
}
