import { motion } from 'framer-motion';

import metrics from '../../data/metrics.json';
import { HERO_CASE } from './plateData.js';

/**
 * The editorial left column of the hero -- the half of the viewport that was
 * previously empty next to the floating card.
 *
 * Presentational and self-contained. Stage.jsx renders it and writes only its
 * container's opacity as the reader scrolls into the layer split, so this
 * component never fights the animation loop for a transform. The card itself
 * sits mid-to-right, positioned by Stage's rig.
 *
 * ---------------------------------------------------------------------------
 * THE STATUS METRIC, AND WHY IT IS NOT 99.4%
 * ---------------------------------------------------------------------------
 * This section was specified with a ticker reading
 * "99.4% Automated Representment Accuracy". No such figure exists anywhere in
 * this repository, and nothing in the committed evaluation supports it: on the
 * held-out set the classifier's precision is 60.7%, recall 78.2%, ROC-AUC
 * 0.832 (`data/metrics.json`, rendered in full by the evaluation section
 * further down this same page).
 *
 * Printing 99.4% in the hero would have the site contradict its own evidence
 * roughly one scroll later -- on a page whose entire argument is that the
 * numbers are reproducible, and which ships a `make verify` target and a model
 * card to prove it. So the ticker shows the strongest figure that is actually
 * true: oracle efficiency, the share of the theoretically-perfect recovery
 * yield the policy actually captures on held-out data. It is read from
 * `metrics.json` at build time rather than typed, so it cannot drift from the
 * evaluation dashboard.
 *
 * If 99.4% refers to something real and measured -- packet acceptance, filing
 * validity, uptime -- add it to the metrics artifact and point `STATUS_METRIC`
 * at it; the layout needs no change.
 */

const EASE = [0.22, 1, 0.36, 1];

const rise = (delay, y = 22, duration = 0.62) => ({
  initial: { opacity: 0, y },
  animate: { opacity: 1, y: 0 },
  transition: { duration, delay, ease: EASE },
});

/** Measured, from the committed held-out evaluation. Never hand-typed. */
const STATUS_METRIC = {
  value: `${(metrics.economics.oracle_efficiency * 100).toFixed(1)}%`,
  label: 'of oracle-optimal recovery captured',
};

export default function HeroSection() {
  return (
    <div className="pointer-events-none absolute inset-y-0 left-0 z-[9] hidden w-[40%] items-center pl-12 pr-6 lg:flex lg:pl-20">
      <div className="max-w-[520px]">
        {/* Category pill with a pulsing radar dot. */}
        <motion.div
          {...rise(0.05, 12, 0.5)}
          className="pointer-events-auto inline-flex items-center gap-2.5 rounded-full px-3.5 py-2"
          style={{
            background: 'rgba(13,18,31,0.88)',
            border: '1px solid rgba(255,255,255,0.1)',
            boxShadow: 'inset 0 1px 1px 0 rgba(255,255,255,0.12)',
          }}
        >
          <span className="relative flex h-1.5 w-1.5">
            <span className="radar-dot absolute inline-flex h-full w-full rounded-full" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full" style={{ background: '#62C6D7' }} />
          </span>
          <span className="font-mono text-[10px] tracking-[0.18em]" style={{ color: '#8FE3C0' }}>
            [ AUTONOMOUS DISPUTE DEFENSE ENGINE ]
          </span>
        </motion.div>

        {/* The headline. Tight tracking and a heavy weight is most of what
            separates "editorial" from "default sans-serif at a big size". */}
        <h1
          className="mt-7 font-display font-700 text-white"
          style={{
            fontSize: 'clamp(2.4rem, 4.4vw, 4rem)',
            lineHeight: 1.02,
            letterSpacing: '-0.03em',
          }}
        >
          <motion.span {...rise(0.14)} className="block">
            Every Dispute.
          </motion.span>
          <motion.span {...rise(0.22)} className="block">
            Intercepted.
          </motion.span>
          <motion.span
            {...rise(0.3)}
            className="block bg-gradient-to-r from-emerald-400 via-teal-300 to-cyan-400 bg-clip-text text-transparent"
          >
            Defended. Won.
          </motion.span>
        </h1>

        <motion.p
          {...rise(0.4, 16, 0.55)}
          className="mt-6 max-w-[30rem] text-[15px] leading-[1.7]"
          style={{ color: '#94A3B8' }}
        >
          Real-time LightGBM inference scores every chargeback the moment it
          lands, then a per-dispute economic threshold{' '}
          <span className="font-mono tabular-nums" style={{ color: '#CBD5E1' }}>
            p* = λ·c / A
          </span>{' '}
          decides which are worth contesting. Not a blanket policy. Not an
          average across the portfolio. One verdict, priced per dispute.
        </motion.p>

        {/* Live status ticker. */}
        <motion.div
          {...rise(0.5, 14, 0.5)}
          className="pointer-events-auto mt-8 inline-flex items-center gap-3 rounded-xl px-4 py-3"
          style={{
            background: 'rgba(13,18,31,0.88)',
            backdropFilter: 'blur(16px)',
            WebkitBackdropFilter: 'blur(16px)',
            border: '1px solid rgba(255,255,255,0.1)',
            boxShadow:
              'inset 0 1px 1px 0 rgba(255,255,255,0.14), 0 20px 40px -24px rgba(0,0,0,0.9)',
          }}
        >
          <span className="relative flex h-2 w-2">
            <span className="radar-dot absolute inline-flex h-full w-full rounded-full" />
            <span className="relative inline-flex h-2 w-2 rounded-full" style={{ background: '#62C6D7' }} />
          </span>
          <span
            className="font-mono text-[15px] font-600 tabular-nums"
            style={{ color: '#00FF87', textShadow: '0 0 14px rgba(0,255,135,0.35)' }}
          >
            {STATUS_METRIC.value}
          </span>
          <span className="text-[12.5px]" style={{ color: '#94A3B8' }}>
            {STATUS_METRIC.label}
          </span>
        </motion.div>

        <motion.p
          {...rise(0.58, 10, 0.5)}
          className="mt-3 font-mono text-[10px] tracking-[0.1em]"
          style={{ color: '#4A5464' }}
        >
          HELD-OUT · n={metrics.test_set_size.toLocaleString('en-IN')} · CASE #{HERO_CASE.id}
        </motion.p>
      </div>
    </div>
  );
}
