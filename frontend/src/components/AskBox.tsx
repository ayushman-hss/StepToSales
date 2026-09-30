import { useState } from 'react';
import { SendHorizontal } from 'lucide-react';
import { askShop } from '../api';
import { Button, Section } from '../lib/ui/controls';

const EXAMPLES = [
  'How much did I sell today?',
  'What sold most this week?',
  'How is today going?',
  'Busiest hour?',
  'Compare today with yesterday',
  'How can I improve sales?',
];

interface Turn {
  question: string;
  answer: string | null;
}

/**
 * The same assistant the Telegram bot answers with, on the page: plain
 * questions, answers from the shop's own numbers. Nothing leaves the server.
 */
export function AskBox() {
  const [text, setText] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setText('');
    setTurns((t) => [...t.slice(-4), { question: q, answer: null }]);
    let reply: string;
    try {
      reply = await askShop(q);
    } catch (e) {
      reply = e instanceof Error ? e.message : 'Could not get an answer. Try again.';
    }
    setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, answer: reply } : turn)));
    setBusy(false);
  };

  return (
    <Section title="Ask about your shop">
      <p className="text-small text-muted">
        Type a question in your own words, here or to the bot on Telegram. Answers come from
        your own numbers, worked out on this server.
      </p>

      {turns.length > 0 && (
        <ul className="mt-4 space-y-3">
          {turns.map((t, i) => (
            <li key={i} className="space-y-2">
              <p className="ml-auto w-fit max-w-[85%] rounded-item bg-board px-3 py-2 text-body text-white">
                {t.question}
              </p>
              <p className="w-fit max-w-[92%] whitespace-pre-line rounded-item border border-rule bg-chalk px-3 py-2 text-body text-ink">
                {t.answer ?? 'Working it out…'}
              </p>
            </li>
          ))}
        </ul>
      )}

      <form
        className="mt-4 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          ask(text);
        }}
      >
        <input
          aria-label="Your question"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. how many people came in yesterday evening?"
          maxLength={300}
          className="min-h-12 min-w-0 flex-1 rounded-control border border-rule bg-white px-3 text-body text-ink placeholder:text-muted focus:border-board focus:outline-none md:min-h-10"
        />
        <Button type="submit" disabled={busy || !text.trim()} aria-label="Ask">
          <SendHorizontal size={16} aria-hidden />
          <span className="hidden sm:inline">Ask</span>
        </Button>
      </form>

      <div className="mt-3 flex flex-wrap gap-2">
        {EXAMPLES.map((e) => (
          <button
            key={e}
            type="button"
            onClick={() => ask(e)}
            disabled={busy}
            className="min-h-9 rounded-full border border-rule bg-white px-3 text-small text-muted transition-colors hover:border-board hover:text-board disabled:opacity-50"
          >
            {e}
          </button>
        ))}
      </div>
    </Section>
  );
}
