import { Link } from 'react-router-dom';
import { BarChart3, Package, Tag, Users } from 'lucide-react';
import { ThresholdBar } from '../lib/ui/ThresholdBar';
import { Button } from '../lib/ui/controls';
import { useAuth } from '../auth';

/**
 * The old landing showed two of the four features and used gradient-washed
 * icon tiles. Four now, no gradients, and the hero is the threshold bar --
 * the same component that carries every page, introduced here as the idea
 * the whole product runs on.
 */
const SECTIONS = [
  {
    to: '/dashboard',
    icon: BarChart3,
    title: 'Sales vs footfall',
    line: 'See the hours people walk in but do not buy.',
  },
  {
    to: '/products',
    icon: Package,
    title: 'Products',
    line: 'Set your cost and selling price once, so every suggestion protects your margin.',
  },
  {
    to: '/bundles',
    icon: Tag,
    title: 'Bundles',
    line: 'Pair the things customers already buy together, priced above your floor.',
  },
  {
    to: '/pools',
    icon: Users,
    title: 'Group buying',
    line: 'Combine orders with nearby shops to reach the wholesale rate.',
  },
];

export function LandingPage() {
  const me = useAuth((s) => s.me);

  return (
    <div className="py-4 md:py-8">
      <section className="max-w-xl">
        <h1 className="text-3xl font-bold tracking-tight text-ink md:text-4xl">
          Every number here is a line you can cross.
        </h1>
        <p className="mt-3 text-body text-muted">
          More of your visitors buying. A bundle that clears your margin floor. Enough
          volume for the next wholesale rate. StepToSales shows you where the line is and
          how far you have to go.
        </p>

        <div className="mt-7">
          <ThresholdBar
            value={72}
            max={100}
            threshold={60}
            thresholdLabel="the line"
            caption="You are over it, or you are not. That is the whole idea."
          />
        </div>

        <div className="mt-8">
          {me ? (
            <Button to="/dashboard">Open {me.store_code}&rsquo;s numbers</Button>
          ) : (
            <Button to="/login">Log in to your shop</Button>
          )}
        </div>
      </section>

      <nav className="mt-12" aria-label="Sections">
        <ul className="divide-y divide-rule border-y border-rule">
          {SECTIONS.map(({ to, icon: Icon, title, line }) => (
            <li key={to}>
              <Link
                to={to}
                className="group flex items-start gap-4 py-5 transition-colors hover:bg-white focus-visible:bg-white md:px-2"
              >
                <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-item bg-board-tint text-board transition-colors group-hover:bg-board group-hover:text-white">
                  <Icon size={18} aria-hidden />
                </span>
                <span>
                  <span className="block text-heading text-ink">{title}</span>
                  <span className="mt-0.5 block text-small text-muted">{line}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
