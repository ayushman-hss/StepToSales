import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom';
import { BarChart3, Package, Tag, Users, Home, LogOut } from 'lucide-react';
import clsx from 'clsx';
import { logout } from '../api';
import { useAuth } from '../auth';
import { Wordmark } from '../lib/ui/Wordmark';

/** Short labels are for the bottom bar, where five tabs have to fit a phone. */
const NAV = [
  { to: '/', short: 'Home', long: 'Home', icon: Home, exact: true },
  { to: '/dashboard', short: 'Footfall', long: 'Sales vs footfall', icon: BarChart3 },
  { to: '/products', short: 'Products', long: 'Products', icon: Package },
  { to: '/bundles', short: 'Bundles', long: 'Bundles', icon: Tag },
  { to: '/pools', short: 'Group', long: 'Group buying', icon: Users },
];

function isActive(pathname: string, to: string, exact?: boolean) {
  return exact ? pathname === to : pathname.startsWith(to);
}

/** Which shop this is, and the way out. Sits at the right of the header. */
function Account() {
  const me = useAuth((s) => s.me);
  const status = useAuth((s) => s.status);
  const navigate = useNavigate();

  if (status === 'checking') return null;

  if (!me) {
    return (
      <Link
        to="/login"
        className="inline-flex min-h-11 items-center rounded-control px-3 text-small font-semibold text-board hover:bg-board-tint md:min-h-9"
      >
        Log in
      </Link>
    );
  }

  const named = me.store_name && me.store_name !== me.store_code;
  return (
    <div className="flex min-w-0 items-center gap-1">
      <span className="min-w-0 truncate text-small text-muted" title={me.store_name}>
        <span className="font-semibold text-ink">{me.store_code}</span>
        {/* The name only where the section links are not competing for room. */}
        {named && <span className="hidden sm:inline md:hidden"> &middot; {me.store_name}</span>}
      </span>
      <button
        type="button"
        onClick={async () => {
          await logout();
          navigate('/login', { replace: true });
        }}
        className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-control px-2 text-small font-medium text-muted transition-colors hover:bg-board-tint hover:text-board md:min-h-9 md:min-w-0 md:px-3"
      >
        <LogOut size={15} aria-hidden />
        <span className="sr-only md:not-sr-only">Log out</span>
      </button>
    </div>
  );
}

export function Layout() {
  const { pathname } = useLocation();

  return (
    <div className="min-h-screen bg-chalk">
      {/* Desktop chrome. On a phone the wordmark stays but the links move to
          the bottom bar, where a thumb can actually reach them. */}
      <header className="sticky top-0 z-20 border-b border-rule bg-chalk/95 backdrop-blur">
        <div className="mx-auto flex max-w-[960px] items-center gap-8 px-5 py-3 md:px-8">
          <Link to="/" className="shrink-0" aria-label="StepToSales home">
            <Wordmark size={20} />
          </Link>

          <nav className="hidden gap-1 md:flex" aria-label="Sections">
            {NAV.slice(1).map(({ to, long, icon: Icon, exact }) => {
              const active = isActive(pathname, to, exact);
              return (
                <Link
                  key={to}
                  to={to}
                  aria-current={active ? 'page' : undefined}
                  className={clsx(
                    'inline-flex items-center gap-2 rounded-control px-3 py-2 text-small font-medium transition-colors',
                    active
                      ? 'bg-board text-white'
                      : 'text-muted hover:bg-board-tint hover:text-board',
                  )}
                >
                  <Icon size={15} aria-hidden />
                  {long}
                </Link>
              );
            })}
          </nav>

          <div className="ml-auto min-w-0">
            <Account />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[960px] px-5 pt-6 pb-nav md:px-8 md:pt-10">
        <Outlet />
      </main>

      {/* Bottom tabs: 56px, thumb-reachable, one-handed in a shop. */}
      <nav
        aria-label="Sections"
        className="fixed inset-x-0 bottom-0 z-20 border-t border-rule bg-white md:hidden"
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
      >
        <div className="flex">
          {NAV.map(({ to, short, icon: Icon, exact }) => {
            const active = isActive(pathname, to, exact);
            return (
              <Link
                key={to}
                to={to}
                aria-current={active ? 'page' : undefined}
                className={clsx(
                  'flex flex-1 flex-col items-center gap-1 py-2.5 text-fine font-medium transition-colors',
                  active ? 'text-board' : 'text-muted',
                )}
              >
                <span
                  className={clsx(
                    'flex h-7 w-12 items-center justify-center rounded-full transition-colors',
                    active && 'bg-board-tint',
                  )}
                >
                  <Icon size={18} aria-hidden />
                </span>
                {short}
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
