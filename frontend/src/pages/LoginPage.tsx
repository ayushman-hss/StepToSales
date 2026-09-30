import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { login } from '../api';
import { useAuth } from '../auth';
import { Wordmark } from '../lib/ui/Wordmark';
import { Button, Input, Notice } from '../lib/ui/controls';

/** Only same-app paths, so a crafted link cannot bounce a login elsewhere. */
function safeFrom(state: unknown): string {
  const from = (state as { from?: unknown } | null)?.from;
  return typeof from === 'string' && from.startsWith('/') && !from.startsWith('//')
    ? from
    : '/dashboard';
}

export function LoginPage() {
  const status = useAuth((s) => s.status);
  const notice = useAuth((s) => s.notice);
  const location = useLocation();
  const navigate = useNavigate();
  const from = safeFrom(location.state);

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status === 'in') return <Navigate to={from} replace />;

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError('Enter your username and password.');
      return;
    }
    try {
      setBusy(true);
      setError(null);
      await login(username, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not log in');
      setPassword('');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-chalk">
      <header className="mx-auto w-full max-w-[960px] px-5 py-3 md:px-8">
        <Link to="/" className="inline-block" aria-label="StepToSales home">
          <Wordmark size={20} />
        </Link>
      </header>

      <main className="flex flex-1 items-start justify-center px-5 pt-10 pb-16 md:items-center md:pt-0">
        <div className="w-full max-w-sm">
          <h1 className="text-title text-ink">Log in to your shop</h1>
          <p className="mt-1 text-body text-muted">
            Each login opens one shop&rsquo;s numbers, and no one else&rsquo;s.
          </p>

          <form
            onSubmit={onSubmit}
            noValidate
            className="mt-6 space-y-4 rounded-section border border-rule bg-white p-5 md:p-6"
          >
            {/* One message at a time: a fresh error replaces the redirect reason. */}
            {error ? (
              <Notice>{error}</Notice>
            ) : (
              notice && <Notice tone="brass">{notice}</Notice>
            )}

            <Input
              label="Username"
              name="username"
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full"
            />
            <Input
              label="Password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full"
            />
            <Button type="submit" block disabled={busy}>
              {busy ? 'Logging in…' : 'Log in'}
            </Button>
          </form>

          {import.meta.env.DEV && (
            <p className="mt-4 text-small text-muted">
              Demo shops: <strong className="font-medium text-ink">s1</strong> /{' '}
              <strong className="font-medium text-ink">s1shop</strong>, and the same
              pattern for s2 and s3. Run{' '}
              <code className="rounded bg-board-tint px-1 text-board">scripts/reset_demo.py</code>{' '}
              if they do not work.
            </p>
          )}
        </div>
      </main>
    </div>
  );
}
