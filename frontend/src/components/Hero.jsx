import { motion } from 'framer-motion';
import { ChevronDown, Github, Terminal } from 'lucide-react';

import { scrollToSection } from '../hooks/useScrollSpy.js';
import { prefersReducedMotion } from '../hooks/usePointer.js';

const TITLE = 'ChargeGuard.AI';

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.045, delayChildren: 0.08 } },
};

const character = {
  hidden: { opacity: 0, y: 22, filter: 'blur(6px)' },
  show: {
    opacity: 1,
    y: 0,
    filter: 'blur(0px)',
    transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] },
  },
};

function SceneCell() {
  return (
    <div className="mx-auto w-full max-w-md rounded-2xl border border-emerald/20 bg-surface p-5 shadow-xl shadow-black/20 sm:p-7">
      <div className="flex items-center justify-between border-b border-white/10 pb-4">
        <div>
          <p className="eyebrow text-emerald/80">Decision engine</p>
          <p className="mt-1 font-display text-lg font-600 text-white">One dispute at a time</p>
        </div>
        <span className="rounded-full bg-emerald-dim px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-emerald">
          Ready
        </span>
      </div>
      <div className="mt-6 space-y-3">
        {[
          ['Evidence quality', 'Strong', 'bg-emerald'],
          ['Win probability', '78.4%', 'bg-indigo'],
          ['Expected recovery', '₹2,486', 'bg-coral'],
        ].map(([label, value, tone]) => (
          <div key={label} className="flex items-center justify-between rounded-lg bg-white/[0.04] px-4 py-3">
            <span className="text-sm text-slateink">{label}</span>
            <span className="flex items-center gap-2 font-mono text-sm text-white">
              <span className={`h-2 w-2 rounded-full ${tone}`} />
              {value}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-6 flex items-center justify-between border-t border-white/10 pt-4">
        <span className="font-mono text-xs text-slateink/60">Policy threshold</span>
        <span className="font-mono text-sm text-emerald">12.6%</span>
      </div>
    </div>
  );
}

export default function Hero() {
  const reduced = prefersReducedMotion();

  return (
    <section
      id="hero"
      className="relative min-h-[92vh] overflow-hidden pt-16"
    >
      <div className="mx-auto grid h-full min-h-[calc(92vh-4rem)] max-w-content grid-cols-1 items-center gap-8 px-5 sm:px-8 lg:grid-cols-2 lg:gap-6">
        {/* ------------------------------------------------------------------ */}
        {/* Canvas — first in DOM on mobile so it sits above the text; second  */}
        {/* visually on lg via order.                                          */}
        {/* ------------------------------------------------------------------ */}
        <div className="order-1 lg:order-2 lg:h-[72vh]">
          <SceneCell />
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Text column                                                        */}
        {/* ------------------------------------------------------------------ */}
        <div className="order-2 max-w-xl lg:order-1">
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className="mb-6 inline-flex items-center gap-2 rounded-full border border-emerald/25 bg-emerald-dim px-3 py-1.5"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-emerald" />
            <span className="font-mono text-2xs uppercase tracking-[0.16em] text-emerald">
              Razorpay AI Buildathon 2026 · Track 02 · AI Risk Manager
            </span>
          </motion.div>

          <motion.h1
            variants={reduced ? undefined : container}
            initial={reduced ? undefined : 'hidden'}
            animate={reduced ? undefined : 'show'}
            className="font-display font-700 leading-[0.95] tracking-tight text-white text-balance"
            style={{ fontSize: 'clamp(3rem, 7vw, 6.5rem)' }}
            aria-label={TITLE}
          >
            <span aria-hidden="true">
              {TITLE.split('').map((char, index) => (
                <motion.span
                  key={`${char}-${index}`}
                  variants={reduced ? undefined : character}
                  className="inline-block"
                >
                  {char}
                </motion.span>
              ))}
            </span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, delay: 0.35, ease: [0.22, 1, 0.36, 1] }}
            className="mt-6 font-display text-xl font-500 leading-snug text-[#CBD5E1] text-balance sm:text-2xl"
          >
            Autonomous Multi-Modal Chargeback Defense &amp; Economic Arbitrage
            Engine
          </motion.p>

          <motion.p
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, delay: 0.46, ease: [0.22, 1, 0.36, 1] }}
            className="mt-5 text-base leading-relaxed text-[#CBD5E1]/85 text-pretty"
            style={{ fontSize: '16px', lineHeight: 1.6 }}
          >
            A dispute is worth contesting only when expected recovery beats the
            cost of fighting. Not sometimes. Not on average across the portfolio.{' '}
            <span className="text-white">Per dispute.</span>
          </motion.p>

          {/* The rule itself, in the hero. */}
          <motion.div
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, delay: 0.58, ease: [0.22, 1, 0.36, 1] }}
            className="mt-8 inline-flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-white/10 bg-surface px-4 py-3"
          >
            <span className="font-mono text-sm text-slateink/60">contest</span>
            <span className="font-mono text-sm text-slateink/40">⟺</span>
            <span className="font-mono text-base text-white tabular">
              p<sub className="text-xs">i</sub>
            </span>
            <span className="font-mono text-sm text-slateink/60">≥</span>
            <span className="font-mono text-base text-emerald tabular">
              λ·c / A<sub className="text-xs">i</sub>
            </span>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, delay: 0.7, ease: [0.22, 1, 0.36, 1] }}
            className="mt-10 flex flex-wrap items-center gap-3"
          >
            <button
              type="button"
              onClick={() => scrollToSection('simulator')}
              className="group inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-emerald px-5 py-3 font-display text-sm font-600 text-obsidian transition-all duration-300 ease-entrance hover:bg-emerald/90"
            >
              <Terminal size={16} />
              Run the simulator
            </button>
            <button
              type="button"
              onClick={() => scrollToSection('eval')}
              className="inline-flex min-h-[44px] items-center gap-2 rounded-xl border border-white/15 bg-white/[0.04] px-5 py-3 font-display text-sm font-600 text-white transition-all duration-300 ease-entrance hover:border-white/30 hover:bg-white/[0.08]"
            >
              See the held-out metrics
            </button>
            <button
              type="button"
              onClick={() => scrollToSection('verify')}
              className="inline-flex min-h-[44px] items-center gap-2 rounded-xl px-4 py-3 font-display text-sm font-500 text-slateink transition-colors hover:text-white"
            >
              <Github size={16} />
              Verify it yourself
            </button>
          </motion.div>
        </div>
      </div>

      {/* Hairline scroll cue. */}
      {!reduced && (
        <motion.button
          type="button"
          onClick={() => scrollToSection('problem')}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1, y: [0, 6, 0] }}
          transition={{
            opacity: { delay: 1.2, duration: 0.6 },
            y: { delay: 1.2, duration: 2.4, repeat: Infinity, ease: 'easeInOut' },
          }}
          aria-label="Scroll to the problem statement"
          className="tap-44 absolute bottom-6 left-1/2 z-20 -translate-x-1/2 p-2 text-slateink/40 transition-colors hover:text-slateink"
        >
          <ChevronDown size={18} strokeWidth={1.5} />
        </motion.button>
      )}
    </section>
  );
}
