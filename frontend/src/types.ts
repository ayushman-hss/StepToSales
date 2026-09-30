export interface Kpis {
  total_footfall: number;
  total_sales: number;
  total_transactions: number;
  conversion_rate: number;
  avg_basket: number;
  sales_per_visitor: number;
}

/** An hour of the AVERAGE day when the range is longer than one day. */
export interface HourlyPoint {
  hour: number;
  footfall: number;
  sales: number;
  transactions: number;
  conversion: number;
}

export interface DailyPoint {
  date: string;
  footfall: number;
  sales: number;
  transactions: number;
  conversion: number;
}

export interface Insight {
  kind: 'warning' | 'opportunity' | 'observation' | 'win';
  text: string;
}

export interface Period {
  start: string;
  end: string;
  days: number;
  /** The range ends on a day still in progress (today). */
  partial: boolean;
  label: string;
}

/** The same weekday a week earlier, cut at the same hour. */
export interface Comparison {
  date: string;
  label: string;
  through_hour: number;
  footfall: number;
  transactions: number;
  sales: number;
}

export interface DashboardData {
  kpis: Kpis;
  hourly: HourlyPoint[];
  daily: DailyPoint[];
  insights: Insight[];
  whatsapp: string;
  heatmap: HeatmapPoint[];
  period: Period;
  /** Latest date and hour held for this shop, e.g. "2026-09-21T20". */
  data_through: string | null;
  compare: Comparison | null;
  /** Pace, band and the hour in progress; only when the range is today. */
  live: LiveBlock | null;
}

export interface Store {
  code: string;
  name: string;
}

export interface HeatmapPoint {
  dow: number;
  hour: number;
  footfall: number;
}

export interface Product {
  id: number;
  sku: string;
  name: string;
  cost_price: number;
  sell_price: number;
  margin_pct: number;
}

export interface BundleSuggestion {
  id: number;
  sku_a: string;
  sku_b: string;
  name_a: string;
  name_b: string;
  transactions_with_both: number;
  total_transactions: number;
  confidence: number;
  lift: number;
  separate_price: number;
  separate_margin_pct: number;
  suggested_price: number;
  suggested_margin_pct: number;
  margin_floor_pct: number;
  status: 'pending' | 'approved' | 'rejected';
  approved_price: number | null;
}
// ---- group-buying pools -------------------------------------------------
// Every monetary field below is an integer number of PAISE, never rupees.
// Format with formatPaise(); never do arithmetic on the rupee string.

export type PoolStrategy = 'unit_price' | 'pro_rata' | 'shapley';
export type PoolStatus = 'draft' | 'open' | 'locked' | 'settled' | 'cancelled';

export interface PoolTier {
  min_qty: number;
  max_qty: number | null;
  unit_price: number;
  label: string;
}

export interface PoolStoreLine {
  store: string;
  qty: number;
  cost_alone: number;
  payable: number;
  savings: number;
}

export interface PoolProduct {
  sku: string;
  name: string;
  supplier_id: string;
  price_list_version: string;
  total_qty: number;
  pooled_unit_price: number;
  tier_label: string;
  units_to_next_tier: number | null;
  next_tier_unit_price: number | null;
  invoice_total: number;
  total_savings: number;
  tiers: PoolTier[];
  lines: PoolStoreLine[];
}

export interface PoolStore {
  store: string;
  cost_alone: number;
  payable: number;
  savings: number;
  savings_pct: number;
}

export interface PoolDetail {
  code: string;
  name: string;
  status: PoolStatus;
  strategy: PoolStrategy;
  rotation: number;
  closes_at: string | null;
  invoice_total: number;
  total_savings: number;
  products: PoolProduct[];
  stores: PoolStore[];
}

export interface PoolEvent {
  actor: string;
  kind: string;
  detail: string;
  created_at: string;
}

// ---- live mode ----------------------------------------------------------

/** Cumulative sales by the end of an hour: the usual corridor, and today. */
export interface LiveBandPoint {
  hour: number;
  p10: number;
  p50: number;
  p90: number;
  /** Today; null for hours that have not happened yet. */
  actual: number | null;
}

export interface LiveHourNow {
  hour: number;
  footfall: number;
  transactions: number;
  sales: number;
  usual_footfall: number;
  usual_transactions: number;
  usual_sales: number;
}

/** Today against the same weekday in past weeks. Only present for today. */
export interface LiveBlock {
  weekday: string;
  days_compared: number;
  band: LiveBandPoint[];
  now: LiveHourNow | null;
  /** 0.18 = 18% ahead of the usual sales by the last finished hour. */
  pace: number | null;
  pace_through_hour: number | null;
  projected_sales: number | null;
  typical_sales: number;
  alert: string | null;
  /** The shop clock as hours since midnight (14.5 = 14:30); the line ends here. */
  clock_hour: number | null;
  /** Today's sales up to the shop clock, the hour in progress included. */
  sales_so_far: number;
}

export type LiveSpeed = 0 | 1 | 10 | 60 | 300;

export interface LiveStatus {
  running: boolean;
  speed: LiveSpeed;
  shop_time: string;
  real_time: string;
  minutes_ahead: number;
  last_event_at: string | null;
  last_bill_at: string | null;
  bills_today: number;
  visitors_today: number;
}

export interface RecentBill {
  at: string;
  source: 'sim' | 'pos';
  amount_paise: number;
  items: number;
  lines: { sku: string; name: string; qty: number; unit_price_paise: number }[];
}

// ---- phone alerts ----------------------------------------------------------

export type AlertKind = 'conversion_drop' | 'behind_pace' | 'day_summary';

export interface AlertChat {
  id: number;
  title: string;
  linked_at: string;
}

export interface ShopAlert {
  id: number;
  kind: AlertKind;
  text: string;
  /** Shop clock (IST) when it was raised. */
  shop_time: string;
  /** How many Telegram chats got it; 0 when Telegram is not set up. */
  delivered: number;
}

export interface AlertsOverview {
  telegram: { configured: boolean; bot_username: string | null; error: string | null };
  chats: AlertChat[];
  recent: ShopAlert[];
}

export interface TelegramLink {
  code: string;
  url: string | null;
  bot_username: string | null;
  expires_at: string;
}
