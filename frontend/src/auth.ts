import { create } from 'zustand';
import { useDashboard } from './store';

/** The shop a login belongs to. Every page shows this shop and no other. */
export interface Me {
  store_code: string;
  store_name: string;
}

/**
 * checking: a saved token exists and is being confirmed with the server.
 * in / out: settled either way.
 */
export type AuthStatus = 'checking' | 'in' | 'out';

const TOKEN_KEY = 'steptosales.token';

// Storage can be missing or throw (private mode, blocked site data). Losing it
// only means logging in again, so failures are swallowed.
function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function writeToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

interface AuthState {
  token: string | null;
  me: Me | null;
  status: AuthStatus;
  /** Why the user was sent to the login page, shown once there. */
  notice: string | null;
  signedIn: (token: string, me: Me) => void;
  confirmed: (me: Me) => void;
  signedOut: (notice?: string | null) => void;
  /** The server could not be reached; keep the token and try again later. */
  unreachable: () => void;
}

const saved = readToken();

export const useAuth = create<AuthState>((set) => ({
  token: saved,
  me: null,
  status: saved ? 'checking' : 'out',
  notice: null,
  signedIn: (token, me) => {
    writeToken(token);
    // A different shop must never glimpse the previous one's numbers.
    useDashboard.getState().reset();
    set({ token, me, status: 'in', notice: null });
  },
  confirmed: (me) => set({ me, status: 'in' }),
  signedOut: (notice = null) => {
    writeToken(null);
    useDashboard.getState().reset();
    set({ token: null, me: null, status: 'out', notice });
  },
  unreachable: () =>
    set({
      status: 'out',
      notice: 'Could not reach StepToSales. Check the server is running, then log in.',
    }),
}));

const NO_STORE: Me = { store_code: '', store_name: '' };

/**
 * The logged-in shop. Meant for pages below <RequireAuth>, where it always
 * exists; the empty fallback only covers the render in which a logout is
 * already redirecting away, so that render cannot crash the app.
 */
export function useCurrentStore(): Me {
  return useAuth((s) => s.me) ?? NO_STORE;
}
