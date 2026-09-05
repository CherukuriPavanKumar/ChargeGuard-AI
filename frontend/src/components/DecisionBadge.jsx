import { motion } from 'framer-motion';
import clsx from 'clsx';
import { Check, ChevronRight, Minus, ShieldCheck, ShieldX } from 'lucide-react';

import { formatInr, formatPercent, formatThreshold } from '../lib/economics.js';

/**
 * The decision, and the complete trace of how it was reached.
 *
 * Two parts, and the second is the more important one. The badge states the
 * action; the gate trace below it shows every rule that was *considered*,
 * whether it fired, and what it would have forced. That is what makes a
 * decision auditable rather than merely explained — an auditor can see the
 * alternatives that were evaluated and rejected, not just the branch taken.
 *
 * Colour follows the site-wide encoding: emerald CONTEST, coral ACCEPT.
 */

const GATE_LABELS = {
  amount_below_cost: 'Amount at or below filing cost',
  expired_window: 'Representment window expired',
  credit_already_processed: 'Credit already processed',
  no_pod_on_non_receipt: 'No proof of delivery on a non-receipt claim',
  fraud_without_liability_shift: 'Fraud denial without liability shift',
  strong_evidence: 'Compelling evidence present',
};

function GateRow({ gate, isDeciding }) {
  const fired = gate.fired;
  const forced = gate.forcedAction ?? gate.forced_action ?? null;

  return (
    <li
      className={clsx(
        'rounded-lg border px-3 py-2.5 transition-colors',
        isDeciding
          ? forced === 'CONTEST'
            ? 'border-emerald/40 bg-emerald-dim'
            : 'border-coral/40 bg-coral-dim'
          : fired
            ? 'border-white/15 bg-white/[0.04]'
            : 'border-white/[0.07] bg-transparent',
      )}
    >
      <div className="flex items-start gap-2.5">
        <span
          className={clsx(
            'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full',
            fired
              ? forced === 'CONTEST'
                ? 'bg-emerald/25 text-emerald'
                : 'bg-coral/25 text-coral'
              : 'bg-white/[0.06] text-slateink/40',
          )}
        >
          {fired ? <Check size={10} strokeWidth={3} /> : <Minus size={10} />}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <code
              className={clsx(
                'font-mono text-2xs',
                fired ? 'text-white' : 'text-slateink/50',
              )}
            >
              {gate.name ?? gate.gate_name}
            </code>
            {isDeciding && (
              <span
                className={clsx(
                  'rounded px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider',
                  forced === 'CONTEST'
                    ? 'bg-emerald/20 text-emerald'
                    : 'bg-coral/20 text-coral',
                )}
              >
                decided
              </span>
            )}
          </div>
          <div
            className={clsx(
              'mt-0.5 text-xs leading-snug',
              fired ? 'text-slateink/85' : 'text-slateink/45',
            )}
          >
            {GATE_LABELS[gate.name ?? gate.gate_name] ?? gate.rationale}
          </div>
          {fired && gate.rationale && (
            <div className="mt-1.5 text-[11px] leading-relaxed text-slateink/60 text-pretty">
              {gate.rationale}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

export default function DecisionBadge({ decision, cost }) {
  if (!decision) return null;

  const isContest = decision.action === 'CONTEST';
  const decidedByGate = decision.decidingReason !== 'EV_RULE';
  const ev = decision.expectedValueInr;

  return (
    <div className="flex flex-col gap-4">
      {/* Badge */}
      <motion.div
        key={`${decision.disputeId}-${decision.action}`}
        initial={{ opacity: 0, scale: 0.97 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
        className={clsx(
          'rounded-2xl border p-5',
          isContest
            ? 'border-emerald/35 bg-emerald-dim'
            : 'border-coral/35 bg-coral-dim',
        )}
      >
        <div className="flex items-start gap-3.5">
          <div
            className={clsx(
              'rounded-xl p-2.5',
              isContest ? 'bg-emerald/15' : 'bg-coral/15',
            )}
          >
            {isContest ? (
              <ShieldCheck size={22} className="text-emerald" />
            ) : (
              <ShieldX size={22} className="text-coral" />
            )}
          </div>

          <div className="min-w-0 flex-1">
            <div
              className={clsx(
                'font-display text-2xl font-700 tracking-tight',
                isContest ? 'text-emerald' : 'text-coral',
              )}
            >
              {decision.action}
            </div>

            <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-slateink/70">
              <span>decided by</span>
              <code className="font-mono text-white">
                {decidedByGate ? decision.decidingReason : 'EV rule'}
              </code>
              {!decidedByGate && (
                <>
                  <ChevronRight size={11} className="text-slateink/40" />
                  <span className="font-mono text-white tabular">
                    {formatPercent(decision.winProbability)}
                  </span>
                  <span>{isContest ? '≥' : '<'}</span>
                  <span className="font-mono text-white tabular">
                    {formatThreshold(decision.threshold)}
                  </span>
                </>
              )}
            </div>
          </div>
        </div>

        {/* Economics of this decision. */}
        <dl className="mt-5 grid grid-cols-3 gap-3 border-t border-white/10 pt-4">
          <div>
            <dt className="eyebrow mb-1">Expected value</dt>
            <dd
              className={clsx(
                'font-mono text-sm tabular',
                ev >= 0 ? 'text-emerald' : 'text-coral',
              )}
            >
              {ev >= 0 ? '+' : ''}
              {formatInr(ev, true)}
            </dd>
          </div>
          <div>
            <dt className="eyebrow mb-1">Threshold</dt>
            <dd className="font-mono text-sm text-white tabular">
              {formatThreshold(decision.threshold)}
            </dd>
          </div>
          <div>
            <dt className="eyebrow mb-1">Filing cost</dt>
            <dd className="font-mono text-sm text-slateink tabular">
              {formatInr(cost)}
            </dd>
          </div>
        </dl>

        {/* The uncomfortable case, surfaced rather than hidden: a gate can
            force ACCEPT on a dispute whose raw expected value is positive. */}
        {!isContest && ev > 0 && (
          <p className="mt-4 rounded-lg border border-white/10 bg-black/20 p-3 text-xs leading-relaxed text-slateink/70 text-pretty">
            <span className="text-white">Note the tension.</span> Expected value
            here is <span className="font-mono text-emerald">
              +{formatInr(ev, true)}
            </span>
            , yet the policy concedes. A hard gate has overridden the
            arithmetic because the dispute is unwinnable on scheme rules — the
            residual win rate in this segment is issuer noise, not something a
            model can select on. The cost of that choice is published in section
            5 of the evaluation report rather than argued away.
          </p>
        )}
      </motion.div>

      {/* Gate trace */}
      <div className="glass p-4">
        <div className="mb-3 flex items-baseline justify-between gap-2">
          <div className="eyebrow">Gate trace · evaluation order</div>
          <span className="font-mono text-2xs text-slateink/45">
            first to fire wins
          </span>
        </div>

        <ol className="space-y-1.5">
          {decision.gates.map((gate) => (
            <GateRow
              key={gate.name ?? gate.gate_name}
              gate={gate}
              isDeciding={
                (gate.name ?? gate.gate_name) === decision.decidingReason
              }
            />
          ))}

          {/* The EV rule sits at the end of the same ordered list, because that
              is exactly where it sits in the engine: it decides only when every
              gate has declined to. */}
          <li
            className={clsx(
              'rounded-lg border px-3 py-2.5',
              !decidedByGate
                ? isContest
                  ? 'border-emerald/40 bg-emerald-dim'
                  : 'border-coral/40 bg-coral-dim'
                : 'border-white/[0.07]',
            )}
          >
            <div className="flex items-start gap-2.5">
              <span
                className={clsx(
                  'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full',
                  !decidedByGate
                    ? isContest
                      ? 'bg-emerald/25 text-emerald'
                      : 'bg-coral/25 text-coral'
                    : 'bg-white/[0.06] text-slateink/40',
                )}
              >
                {!decidedByGate ? (
                  <Check size={10} strokeWidth={3} />
                ) : (
                  <Minus size={10} />
                )}
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <code
                    className={clsx(
                      'font-mono text-2xs',
                      !decidedByGate ? 'text-white' : 'text-slateink/50',
                    )}
                  >
                    EV_RULE
                  </code>
                  {!decidedByGate && (
                    <span
                      className={clsx(
                        'rounded px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider',
                        isContest
                          ? 'bg-emerald/20 text-emerald'
                          : 'bg-coral/20 text-coral',
                      )}
                    >
                      decided
                    </span>
                  )}
                </div>
                <div
                  className={clsx(
                    'mt-0.5 text-xs leading-snug',
                    !decidedByGate ? 'text-slateink/85' : 'text-slateink/45',
                  )}
                >
                  {decidedByGate
                    ? 'Not reached — a gate decided first.'
                    : decision.thresholdReachable
                      ? `p = ${formatPercent(decision.winProbability)} ${isContest ? '≥' : '<'} p* = ${formatThreshold(decision.threshold)}`
                      : 'Threshold exceeds certainty. ACCEPT forced by arithmetic.'}
                </div>
              </div>
            </div>
          </li>
        </ol>
      </div>
    </div>
  );
}
