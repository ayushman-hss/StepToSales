import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../auth';

/**
 * Gate for every page that shows a shop's numbers. Remembers where the user
 * was heading, so logging in lands them there rather than on a default page.
 */
export function RequireAuth() {
  const status = useAuth((s) => s.status);
  const me = useAuth((s) => s.me);
  const location = useLocation();

  if (status === 'checking') {
    return <p className="text-small text-muted">Checking your login&hellip;</p>;
  }
  if (status !== 'in' || !me) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname + location.search }}
      />
    );
  }
  // Keyed by shop so no page keeps local state from a previous login.
  return <Outlet key={me.store_code} />;
}
