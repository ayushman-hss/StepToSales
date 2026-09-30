import { create } from 'zustand';
import type { DashboardData } from './types';

/**
 * Named ranges a shopkeeper actually thinks in. "Last 7 days" and "last 4
 * weeks" end YESTERDAY, so they only ever contain complete days -- a
 * half-finished today would make the latest week look worse than it was.
 */
export type RangePreset = 'today' | 'yesterday' | '7d' | '28d' | 'all' | 'custom';

function iso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return iso(d);
}

export function rangeFor(preset: RangePreset): { startDate: string; endDate: string } {
  switch (preset) {
    case 'today':
      return { startDate: daysAgo(0), endDate: daysAgo(0) };
    case 'yesterday':
      return { startDate: daysAgo(1), endDate: daysAgo(1) };
    case '7d':
      return { startDate: daysAgo(7), endDate: daysAgo(1) };
    case '28d':
      return { startDate: daysAgo(28), endDate: daysAgo(1) };
    case 'all':
    case 'custom':
      return { startDate: '', endDate: '' };
  }
}

/**
 * The shop is not part of this state: it is fixed by who is logged in (see
 * auth.ts), and the server scopes every request to it.
 */
interface State {
  data: DashboardData | null;
  loading: boolean;
  error: string | null;
  preset: RangePreset;
  startDate: string;
  endDate: string;
  setData: (d: DashboardData | null) => void;
  setLoading: (b: boolean) => void;
  setError: (e: string | null) => void;
  setPreset: (p: RangePreset) => void;
  setFilters: (f: { startDate?: string; endDate?: string }) => void;
  /** Back to "today" with nothing loaded -- used when the login changes. */
  reset: () => void;
}

function initialState() {
  return {
    data: null,
    loading: false,
    error: null,
    preset: 'today' as RangePreset,
    ...rangeFor('today'),
  };
}

export const useDashboard = create<State>((set) => ({
  ...initialState(),
  setData: (data) => set({ data }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
  setPreset: (preset) =>
    set((s) =>
      preset === 'custom'
        ? { preset, startDate: s.startDate || daysAgo(7), endDate: s.endDate || daysAgo(1) }
        : { preset, ...rangeFor(preset) },
    ),
  setFilters: (f) =>
    set((s) => ({
      startDate: f.startDate ?? s.startDate,
      endDate: f.endDate ?? s.endDate,
      // Typing a date is choosing a custom range.
      preset: f.startDate !== undefined || f.endDate !== undefined ? 'custom' : s.preset,
    })),
  reset: () => set(initialState()),
}));
