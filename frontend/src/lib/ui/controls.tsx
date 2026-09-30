import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { ChevronDown } from 'lucide-react';

/* --------------------------------------------------------------------------
 * Button
 *
 * Primary is always board green. Ink is text-only and never fills a button,
 * so there is structurally no second candidate for "the confirm colour".
 * 48px minimum height on mobile: these are thumbs in a shop, not cursors.
 * ------------------------------------------------------------------------ */

type Variant = 'primary' | 'secondary' | 'quiet' | 'danger';

const VARIANT: Record<Variant, string> = {
  primary:
    'bg-board text-white hover:bg-board-deep active:bg-board-deep disabled:bg-chalk disabled:text-muted disabled:border disabled:border-rule',
  secondary:
    'bg-white text-ink border border-rule hover:border-board hover:text-board disabled:text-muted disabled:hover:border-rule',
  quiet:
    'bg-transparent text-muted hover:text-ink hover:bg-board-tint disabled:text-rule',
  danger:
    'bg-white text-clay border border-clay/40 hover:bg-clay-tint hover:border-clay',
};

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: 'md' | 'sm';
  to?: string;
  block?: boolean;
}

export function Button({
  variant = 'primary',
  size = 'md',
  to,
  block,
  className,
  children,
  ...rest
}: ButtonProps) {
  const cls = clsx(
    'inline-flex items-center justify-center gap-2 rounded-control font-semibold',
    'transition-colors duration-150 select-none',
    'disabled:cursor-not-allowed',
    size === 'md'
      ? 'min-h-12 px-4 text-body md:min-h-10'
      : 'min-h-11 px-4 text-body md:min-h-9 md:px-3 md:text-small',
    block && 'w-full',
    VARIANT[variant],
    className,
  );
  if (to) {
    return (
      <Link to={to} className={cls}>
        {children}
      </Link>
    );
  }
  return (
    <button className={cls} {...rest}>
      {children}
    </button>
  );
}

/* --------------------------------------------------------------------------
 * Select
 *
 * Kept native and restyled rather than rebuilt as a custom listbox. On a
 * phone the native control opens the OS picker, which is faster and more
 * familiar for a user who is not comfortable with software -- a custom
 * listbox would look tidier and behave worse.
 * ------------------------------------------------------------------------ */

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  hint?: string;
}

export function Select({ label, hint, className, id, ...rest }: SelectProps) {
  const selectId = id ?? `sel-${label?.replace(/\W+/g, '-').toLowerCase()}`;
  return (
    <div className={clsx('flex flex-col gap-1.5', className)}>
      {label && (
        <label htmlFor={selectId} className="text-small font-medium text-muted">
          {label}
        </label>
      )}
      <div className="relative">
        <select
          id={selectId}
          className={clsx(
            'w-full appearance-none rounded-control border border-rule bg-white',
            'min-h-12 md:min-h-10 pl-3 pr-10 text-body text-ink',
            'hover:border-board focus:border-board',
            'disabled:bg-chalk disabled:text-muted disabled:hover:border-rule',
          )}
          {...rest}
        />
        <ChevronDown
          size={16}
          aria-hidden
          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted"
        />
      </div>
      {hint && <p className="text-fine text-muted">{hint}</p>}
    </div>
  );
}

/* --------------------------------------------------------------------------
 * Field wrappers for text/number/date inputs
 * ------------------------------------------------------------------------ */

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
  wrapClassName?: string;
}

export function Input({ label, hint, className, wrapClassName, id, ...rest }: InputProps) {
  const inputId = id ?? `in-${label?.replace(/\W+/g, '-').toLowerCase()}`;
  return (
    <div className={clsx('flex flex-col gap-1.5', wrapClassName)}>
      {label && (
        <label htmlFor={inputId} className="text-small font-medium text-muted">
          {label}
        </label>
      )}
      <input
        id={inputId}
        className={clsx(
          'rounded-control border border-rule bg-white px-3 text-body text-ink',
          'min-h-12 md:min-h-10 hover:border-board focus:border-board',
          'disabled:bg-chalk disabled:text-muted',
          className,
        )}
        {...rest}
      />
      {hint && <p className="text-fine text-muted">{hint}</p>}
    </div>
  );
}

/* --------------------------------------------------------------------------
 * Segmented control
 *
 * For two to four options. Fewer taps than a dropdown and no hidden state,
 * which matters more than compactness for this audience.
 * ------------------------------------------------------------------------ */

interface SegmentedProps<T extends string> {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: string }[];
  label?: string;
  /** Names the group for screen readers when there is no visible label. */
  ariaLabel?: string;
  className?: string;
  size?: 'md' | 'sm';
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  ariaLabel,
  className,
  size = 'md',
}: SegmentedProps<T>) {
  return (
    <div className={clsx('flex flex-col gap-1.5', className)}>
      {label && <span className="text-small font-medium text-muted">{label}</span>}
      <div
        role="radiogroup"
        aria-label={label ?? ariaLabel}
        className="inline-flex flex-wrap gap-1 rounded-control border border-rule bg-white p-1"
      >
        {options.map((opt) => {
          const active = opt.value === value;
          return (
            <button
              key={opt.value}
              role="radio"
              aria-checked={active}
              onClick={() => onChange(opt.value)}
              className={clsx(
                'rounded-[6px] font-medium transition-colors duration-150',
                size === 'md'
                  ? 'min-h-11 px-3.5 text-body md:min-h-10'
                  : 'min-h-11 px-3.5 text-body md:min-h-8 md:px-3 md:text-small',
                active
                  ? 'bg-board text-white'
                  : 'text-muted hover:bg-board-tint hover:text-board',
              )}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------------
 * Surfaces and badges
 * ------------------------------------------------------------------------ */

export function Section({
  title,
  action,
  children,
  className,
  flush,
}: {
  title?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  flush?: boolean;
}) {
  return (
    <section
      className={clsx(
        'rounded-section border border-rule bg-white',
        !flush && 'p-5 md:p-6',
        className,
      )}
    >
      {title && (
        <header
          className={clsx(
            'mb-4 flex items-center justify-between gap-3',
            flush && 'border-b border-rule px-5 py-4 md:px-6',
          )}
        >
          <h2 className="text-heading">{title}</h2>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

type Tone = 'board' | 'brass' | 'clay' | 'neutral';

const BADGE: Record<Tone, string> = {
  board: 'bg-board-tint text-board',
  brass: 'bg-brass-tint text-brass-deep',
  clay: 'bg-clay-tint text-clay',
  neutral: 'bg-chalk text-muted',
};

export function Badge({
  tone = 'neutral',
  children,
}: {
  tone?: Tone;
  children: React.ReactNode;
}) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-fine font-medium',
        BADGE[tone],
      )}
    >
      {children}
    </span>
  );
}

/* --------------------------------------------------------------------------
 * Figure -- the replacement for the uppercase-label stat card.
 * No box, no border. Label sits under the number, in sentence case.
 * ------------------------------------------------------------------------ */

export function Figure({
  value,
  label,
  size = 'md',
  tone = 'ink',
}: {
  value: React.ReactNode;
  label: string;
  size?: 'hero' | 'md';
  tone?: 'ink' | 'board';
}) {
  return (
    <div>
      <div
        className={clsx(
          'tnum font-bold tracking-tight',
          size === 'hero' ? 'text-figure' : 'text-2xl',
          tone === 'board' ? 'text-board' : 'text-ink',
        )}
      >
        {value}
      </div>
      <div className="mt-0.5 text-small text-muted">{label}</div>
    </div>
  );
}

/* --------------------------------------------------------------------------
 * Feedback
 * ------------------------------------------------------------------------ */

export function Notice({
  tone = 'clay',
  children,
}: {
  tone?: Tone;
  children: React.ReactNode;
}) {
  const map: Record<Tone, string> = {
    clay: 'border-clay/30 bg-clay-tint text-clay',
    brass: 'border-brass/40 bg-brass-tint text-brass-deep',
    board: 'border-board/25 bg-board-tint text-board',
    neutral: 'border-rule bg-chalk text-muted',
  };
  return (
    <div className={clsx('rounded-item border px-4 py-3 text-small', map[tone])}>
      {children}
    </div>
  );
}

export function EmptyState({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-section border border-dashed border-rule bg-white px-6 py-14 text-center">
      <p className="text-heading text-ink">{title}</p>
      {children && <div className="mt-2 text-small text-muted">{children}</div>}
    </div>
  );
}

/* --------------------------------------------------------------------------
 * Page header -- one shape for all five pages, so the left rail is shared.
 * ------------------------------------------------------------------------ */

export function PageHeader({
  title,
  lead,
  action,
}: {
  title: string;
  lead?: string;
  action?: React.ReactNode;
}) {
  return (
    <header className="mb-7 flex flex-wrap items-start justify-between gap-4">
      <div className="max-w-xl">
        <h1 className="text-title text-ink">{title}</h1>
        {lead && <p className="mt-1 text-body text-muted">{lead}</p>}
      </div>
      {action}
    </header>
  );
}

/** A file picker that looks like a Button without lying about being one. */
export function UploadButton({
  children,
  onChange,
  variant = 'primary',
}: {
  children: React.ReactNode;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  variant?: 'primary' | 'secondary';
}) {
  return (
    <label
      className={clsx(
        'inline-flex min-h-12 cursor-pointer items-center justify-center gap-2 rounded-control px-4',
        'text-body font-semibold transition-colors duration-150 md:min-h-10',
        'focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-board',
        variant === 'primary'
          ? 'bg-board text-white hover:bg-board-deep'
          : 'border border-rule bg-white text-ink hover:border-board hover:text-board',
      )}
    >
      {children}
      <input type="file" accept=".xlsx,.xls" className="sr-only" onChange={onChange} />
    </label>
  );
}
