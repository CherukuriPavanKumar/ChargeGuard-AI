import { AnimatePresence, motion } from 'framer-motion';
import { useState } from 'react';

import { artifactIndex, decideOffline, renderOfflinePacket } from '../../lib/presets.js';
import { formatInr, formatPercent } from '../../lib/economics.js';

const EASE = [0.22, 1, 0.36, 1];

/**
 * 04 -- the attack simulator: a sandbox for the dispute lifecycle, ending in a
 * one-click "Auto-Contest" run against the real offline decision path.
 *
 * The webhook events below name real Razorpay dispute-webhook event types
 * (payment.dispute.created / .under_review / .won / .lost / .closed), but
 * nothing here calls Razorpay -- there is no live connection, and the panel
 * says so. Selecting one only appends a local timeline entry; it is a
 * rehearsal of the lifecycle shape, not a webhook receiver.
 *
 * "Auto-Contest Dispute" is the one action that is NOT decorative: it calls
 * `decideOffline()` and `renderOfflinePacket()` from lib/presets.js -- the
 * same offline decision path and template renderer the Simulator section
 * uses when no backend is reachable -- against the selected case's actual
 * recorded model probability. The generation animation is a fixed sequence
 * over the case's real `artifactIndex()`, then the real decision lands.
 */

const WEBHOOK_EVENTS = [
  { key: 'created', label: 'payment.dispute.created', tone: '#94A3B8' },
  { key: 'under_review', label: 'payment.dispute.under_review', tone: '#F0B66E' },
  { key: 'won', label: 'payment.dispute.won', tone: '#62C6D7' },
  { key: 'lost', label: 'payment.dispute.lost', tone: '#E58B84' },
  { key: 'closed', label: 'payment.dispute.closed', tone: '#5A6577' },
];

function timestamp() {
  return new Date().toLocaleTimeString('en-IN', { hour12: false });
}

export default function AttackSimulator({ preset }) {
  const [timeline, setTimeline] = useState([]);
  const [running, setRunning] = useState(false);
  const [tickedCount, setTickedCount] = useState(0);
  const [result, setResult] = useState(null);

  const fireWebhook = (evt) => {
    setTimeline((t) => [{ id: `${evt.key}-${Date.now()}`, ...evt, time: timestamp() }, ...t].slice(0, 6));
  };

  const runAutoContest = async () => {
    setRunning(true);
    setResult(null);
    setTickedCount(0);
    const artifacts = artifactIndex(preset);

    for (let i = 0; i < artifacts.length; i += 1) {
      // eslint-disable-next-line no-await-in-loop
      await new Promise((r) => setTimeout(r, 260));
      setTickedCount(i + 1);
    }

    const decision = decideOffline(preset, preset.recorded.shippedProbability);
    const packet = renderOfflinePacket(preset);
    setResult({ decision, packet, artifacts });
    setRunning(false);
    fireWebhook(
      decision.action === 'CONTEST'
        ? WEBHOOK_EVENTS.find((e) => e.key === 'under_review')
        : WEBHOOK_EVENTS.find((e) => e.key === 'closed'),
    );
  };

  return (
    <div className="mx-auto max-w-content px-5 sm:px-8">
      <div className="grid gap-10 lg:grid-cols-2 lg:items-start">
        <div>
          <div className="eyebrow">Spatial workflow · 04</div>
          <h3 className="mt-3 font-display text-3xl font-700 leading-tight text-white sm:text-4xl">
            Run the attack
            <br />
            against the case.
          </h3>
          <p className="mt-4 max-w-md text-base leading-relaxed" style={{ color: '#94A3B8' }}>
            Simulated Razorpay-style dispute webhooks, and one real action:
            Auto-Contest calls the same offline decision path the Simulator
            section uses.
          </p>
          <p className="mt-2 text-xs" style={{ color: '#5A6577' }}>
            Simulated -- no live Razorpay connection.
          </p>

          <div className="mt-6 flex flex-wrap gap-2">
            {WEBHOOK_EVENTS.map((evt) => (
              <button
                key={evt.key}
                type="button"
                onClick={() => fireWebhook(evt)}
                className="rounded-lg border px-2.5 py-1.5 font-mono text-[10.5px] transition-colors"
                style={{ borderColor: `${evt.tone}55`, color: evt.tone }}
              >
                {evt.label}
              </button>
            ))}
          </div>

          <div className="spatial-glass mt-5 h-40 overflow-y-auto rounded-2xl p-4">
            {timeline.length === 0 ? (
              <div className="font-mono text-[11px]" style={{ color: '#4A5464' }}>
                No events fired yet.
              </div>
            ) : (
              <ul className="space-y-2">
                <AnimatePresence initial={false}>
                  {timeline.map((t) => (
                    <motion.li
                      key={t.id}
                      initial={{ opacity: 0, y: -6 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      className="flex items-center gap-2 font-mono text-[11px]"
                    >
                      <span className="font-tnum" style={{ color: '#5A6577' }}>
                        {t.time}
                      </span>
                      <span style={{ color: t.tone }}>{t.label}</span>
                    </motion.li>
                  ))}
                </AnimatePresence>
              </ul>
            )}
          </div>

          <button
            type="button"
            onClick={runAutoContest}
            disabled={running}
            className="mt-5 inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-emerald px-5 py-3 font-display text-sm font-600 text-obsidian transition-opacity disabled:opacity-50"
          >
            {running ? 'Generating evidence packet...' : 'Auto-Contest Dispute'}
          </button>
        </div>

        <div className="spatial-glass rounded-2xl p-5">
          <div className="font-mono text-[10px] tracking-[0.14em]" style={{ color: '#5A6577' }}>
            EVIDENCE GENERATION
          </div>

          <div className="mt-3 space-y-1.5">
            {artifactIndex(preset).map((a, i) => {
              const done = running ? i < tickedCount : Boolean(result);
              return (
                <div key={a} className="flex items-center gap-2 font-mono text-[10.5px]">
                  <span
                    className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[9px]"
                    style={{
                      background: done ? 'rgba(16,185,129,0.2)' : 'rgba(255,255,255,0.06)',
                      color: done ? '#62C6D7' : '#718893',
                    }}
                  >
                    {done ? '✓' : '·'}
                  </span>
                  <span style={{ color: done ? '#CBD5E1' : '#5A6577' }}>{a}</span>
                </div>
              );
            })}
          </div>

          <AnimatePresence>
            {result && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, ease: EASE }}
                className="mt-5 border-t border-white/10 pt-4"
              >
                <div className="flex items-center gap-2">
                  <span
                    className="rounded-full px-2.5 py-1 font-mono text-[11px] font-600"
                    style={{
                      background: result.decision.action === 'CONTEST' ? 'rgba(16,185,129,0.16)' : 'rgba(148,163,184,0.14)',
                      color: result.decision.action === 'CONTEST' ? '#62C6D7' : '#AEBFC7',
                    }}
                  >
                    {result.decision.action}
                  </span>
                  <span className="font-mono text-[11px]" style={{ color: '#8A94A6' }}>
                    via {result.decision.decidingReason}
                  </span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-3 font-mono font-tnum text-[11px]">
                  <div>
                    <div style={{ color: '#5A6577' }}>p_win (recorded)</div>
                    <div className="mt-0.5 text-white">{formatPercent(result.decision.winProbability, 1)}</div>
                  </div>
                  <div>
                    <div style={{ color: '#5A6577' }}>expected value</div>
                    <div className="mt-0.5" style={{ color: result.decision.expectedValueInr >= 0 ? '#62C6D7' : '#E58B84' }}>
                      {result.decision.expectedValueInr >= 0 ? '+' : ''}
                      {formatInr(result.decision.expectedValueInr)}
                    </div>
                  </div>
                </div>
                <p className="mt-3 text-[10.5px] leading-relaxed" style={{ color: '#5A6577' }}>
                  {result.packet.summary}
                </p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
