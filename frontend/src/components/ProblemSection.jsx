import { motion } from 'framer-motion';
import { AlertTriangle, Scale, TrendingDown } from 'lucide-react';

import metrics from '../data/metrics.json';
import { GlassCardReveal, SectionHeading, Stat } from './ui/GlassCard.jsx';
import { formatInr, formatPercent } from '../lib/economics.js';

/**
 * The problem statement, and the inversion the rest of the site depends on.
 *
 * Every figure here is read from `metrics.json`. Nothing is transcribed: if the
 * harness has not run, this section renders the same zeros the dashboard does
 * rather than a plausible-looking story that happens to be fiction.
 */

const hasMetrics = (metrics?.test_set_size ?? 0) > 0;
const asym = metrics?.asymmetry ?? {};
const econ = metrics?.economics ?? {};
const cfg = metrics?.config ?? {};

const cost = cfg.representment_cost_inr ?? 350;

export default function ProblemSection() {
  return (
    <section id="problem" className="relative py-24 sm:py-32">
      <div className="mx-auto max-w-content px-5 sm:px-8">
        <SectionHeading
          eyebrow="The loss vector"
          title="Friendly fraud is not a detection problem. It is an allocation problem."
          lead="A merchant receiving a chargeback already knows something went wrong. What they do not know is which of the disputes in front of them are worth the cost of fighting — and getting that wrong in the cheap direction costs one to two orders of magnitude more than getting it wrong in the expensive one."
        />

        {/* The inversion, stated plainly and then quantified. */}
        <div className="mt-14 grid gap-5 lg:grid-cols-3">
          <GlassCardReveal className="p-6 lg:col-span-2" accent="coral">
            <div className="flex items-start gap-4">
              <div className="rounded-xl bg-coral-dim p-2.5">
                <Scale size={20} className="text-coral" />
              </div>
              <div>
                <h3 className="font-display text-lg font-600 text-white">
                  The two ways to be wrong do not cost the same
                </h3>
                <p className="mt-3 text-sm leading-relaxed text-slateink text-pretty">
                  In transaction fraud you tune for precision, because a false
                  positive blocks a paying customer. Here the arithmetic runs the
                  other way. Contest and lose, and you are out the filing cost —{' '}
                  <span className="font-mono text-white">
                    {formatInr(cost)}
                  </span>
                  , flat, whether the dispute was for {formatInr(900)} or{' '}
                  {formatInr(80000)}. Accept a dispute you would have won, and you
                  forfeit the entire recovery.
                </p>

                <div className="mt-6 grid gap-4 sm:grid-cols-2">
                  <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
                    <div className="eyebrow mb-2 text-slateink/60">
                      False positive — contested and lost
                    </div>
                    <div className="font-mono text-xl text-white tabular">
                      FP = c
                    </div>
                    <div className="mt-1.5 text-xs text-slateink/60">
                      Flat in the amount. A horizontal line.
                    </div>
                  </div>
                  <div className="rounded-xl border border-coral/25 bg-coral-dim p-4">
                    <div className="eyebrow mb-2 text-coral/80">
                      False negative — accepted but winnable
                    </div>
                    <div className="font-mono text-xl text-coral tabular">
                      FN = A<sub className="text-xs">i</sub> − c
                    </div>
                    <div className="mt-1.5 text-xs text-slateink/60">
                      Linear in the amount. A ray from the origin.
                    </div>
                  </div>
                </div>

                <p className="mt-5 text-sm leading-relaxed text-slateink text-pretty">
                  So a missed win costs more than a lost fight whenever{' '}
                  <span className="font-mono text-white">A ≥ 2c</span>. On the
                  held-out corpus that is{' '}
                  <span className="font-mono text-coral">
                    {hasMetrics
                      ? formatPercent(asym.share_above_2c ?? 0, 1)
                      : '—'}
                  </span>{' '}
                  of disputes.
                </p>
              </div>
            </div>
          </GlassCardReveal>

          <GlassCardReveal className="p-6" accent="none" delay={0.08}>
            <div className="flex items-start gap-3">
              <div className="rounded-xl bg-slateink-dim p-2.5">
                <TrendingDown size={20} className="text-slateink" />
              </div>
              <h3 className="font-display text-lg font-600 text-white">
                Measured on the corpus
              </h3>
            </div>

            <div className="mt-6 space-y-6">
              <Stat
                label="Median FN / FP ratio"
                value={
                  hasMetrics
                    ? `${(asym.median_fn_fp_ratio ?? 0).toFixed(1)}×`
                    : '—'
                }
                sublabel="A missed win at the median dispute"
                accent="coral"
              />
              <Stat
                label="Maximum FN / FP ratio"
                value={
                  hasMetrics
                    ? `${(asym.max_fn_fp_ratio ?? 0).toFixed(0)}×`
                    : '—'
                }
                sublabel="At the top of the amount distribution"
                accent="coral"
              />
              <Stat
                label="Recovery left on the table"
                value={hasMetrics ? formatInr(econ.fn_cost_inr ?? 0) : '—'}
                sublabel="False-negative cost of ChargeGuard's own decisions"
                accent="slate"
              />
            </div>

            {!hasMetrics && (
              <p className="mt-6 rounded-lg border border-white/10 bg-white/[0.03] p-3 font-mono text-xs text-slateink/60">
                Run <span className="text-emerald">make all</span> to populate.
              </p>
            )}
          </GlassCardReveal>
        </div>

        {/* What this means for how the system is built. */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
          className="mt-5 grid gap-5 md:grid-cols-3"
        >
          {[
            {
              title: 'Aggressive recall, bounded by arithmetic',
              body: 'Because a false negative is the expensive error, the correct posture is to contest widely and let the per-dispute threshold — not a confidence cutoff — decide where to stop.',
            },
            {
              title: 'Only rule-based hard overrides',
              body: 'Six gates force a decision, and every one encodes a card-scheme rule or an arithmetic impossibility. None of them is a confidence cutoff, because a confidence cutoff would reintroduce the precision bias.',
            },
            {
              title: 'Scored in rupees, not F1',
              body: 'The evaluation reports net yield against a perfect-foresight oracle. F1 weights the numerous disputes; only a money-denominated metric weights the expensive ones.',
            },
          ].map((item) => (
            <div
              key={item.title}
              className="rounded-2xl border border-white/10 bg-white/[0.02] p-5"
            >
              <h4 className="font-display text-sm font-600 text-white">
                {item.title}
              </h4>
              <p className="mt-2.5 text-sm leading-relaxed text-slateink/75 text-pretty">
                {item.body}
              </p>
            </div>
          ))}
        </motion.div>

        {/* The honest caveat, placed in the problem section rather than hidden
            in a footnote at the bottom of the evaluation. */}
        <GlassCardReveal className="mt-5 p-5" delay={0.12}>
          <div className="flex items-start gap-3">
            <AlertTriangle
              size={16}
              className="mt-0.5 shrink-0 text-slateink/50"
            />
            <p className="text-sm leading-relaxed text-slateink/70 text-pretty">
              <span className="text-white">A note on what is measured.</span>{' '}
              Everything on this page is computed on synthetic data generated by
              a documented latent process, and the generator is in the repository
              for inspection. Two of the drivers of the outcome are deliberately
              withheld from every feature, which bounds achievable AUC well below
              1. That is the point: the interesting question is not whether a
              model can separate the classes, but whether the policy layer
              extracts most of the money that a genuinely uncertain probability
              makes available.
            </p>
          </div>
        </GlassCardReveal>
      </div>
    </section>
  );
}
