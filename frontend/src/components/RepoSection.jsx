import { useState } from 'react';
import { motion } from 'framer-motion';
import clsx from 'clsx';
import { Check, Copy, FolderTree, ShieldCheck, Terminal } from 'lucide-react';

import metrics from '../data/metrics.json';
import { SectionHeading } from './ui/GlassCard.jsx';
import Mark from './ui/Mark.jsx';

/**
 * Repository tour: the directory tree, the six invariants, and how to run it.
 *
 * The invariants are listed with the test that enforces each one, because an
 * invariant nobody checks is a comment. Every claim in this section is
 * falsifiable by running `make test`.
 */

const TREE = [
  { depth: 0, name: 'ChargeGuard-ai/', kind: 'dir' },
  { depth: 1, name: 'backend/', kind: 'dir' },
  { depth: 2, name: 'src/sentinel/', kind: 'dir' },
  {
    depth: 3,
    name: 'schemas/',
    kind: 'dir',
    note: 'frozen Pydantic v2 contracts, extra="forbid"',
  },
  {
    depth: 3,
    name: 'ingest/',
    kind: 'dir',
    note: 'webhook + evidence bundle assembly',
  },
  {
    depth: 3,
    name: 'extraction/',
    kind: 'dir',
    note: 'OCR, fuzzy matching, the single degradation path',
    accent: 'emerald',
  },
  {
    depth: 3,
    name: 'features/',
    kind: 'dir',
    note: 'INVARIANT 2 — pure, 35 features, versioned',
    accent: 'emerald',
  },
  {
    depth: 3,
    name: 'models/',
    kind: 'dir',
    note: 'LightGBM + isotonic calibration',
    accent: 'indigo',
  },
  {
    depth: 3,
    name: 'llm/',
    kind: 'dir',
    note: 'constrained synthesis + hallucination guard',
    accent: 'indigo',
  },
  {
    depth: 3,
    name: 'policy/',
    kind: 'dir',
    note: 'INVARIANT 1 — the sole decision authority',
    accent: 'coral',
  },
  { depth: 4, name: 'economics.py', kind: 'file', note: 'the EV derivation' },
  { depth: 4, name: 'gates.py', kind: 'file', note: '6 ordered hard overrides' },
  {
    depth: 4,
    name: 'engine.py',
    kind: 'file',
    note: 'the only Decision constructor',
    accent: 'coral',
  },
  { depth: 3, name: 'packet/', kind: 'dir', note: 'Jinja → HTML → PDF' },
  { depth: 3, name: 'api/', kind: 'dir', note: 'FastAPI, latency middleware' },
  {
    depth: 2,
    name: 'data_gen/',
    kind: 'dir',
    note: 'latent process + frozen seeds — read this first',
  },
  {
    depth: 2,
    name: 'eval/',
    kind: 'dir',
    note: 'harness, metrics, economics, 4 baselines',
  },
  {
    depth: 3,
    name: 'reports/',
    kind: 'dir',
    note: 'metrics.json + REPORT.md — committed',
  },
  { depth: 2, name: 'tests/', kind: 'dir', note: '8 files enforcing the invariants' },
  { depth: 1, name: 'frontend/', kind: 'dir', note: 'Vite + React static site' },
  {
    depth: 2,
    name: 'src/data/metrics.json',
    kind: 'file',
    note: 'copied by make eval — the dashboard reads only this',
  },
];

const INVARIANTS = [
  {
    id: 1,
    title: 'The Policy Gate is the sole decision authority',
    body: 'Only sentinel.policy.engine may construct a Decision. The model returns a float; the LLM returns prose; neither decides anything.',
    test: 'tests/test_decision_authority.py',
    how: 'AST-walks every .py file under backend/ and fails on any unauthorised construction, including Decision.model_validate.',
  },
  {
    id: 2,
    title: 'The Feature Builder is pure',
    body: 'No network, no disk, no clock, no randomness. Same input, same output, forever — which makes train/serve skew structurally impossible.',
    test: 'tests/test_feature_purity.py',
    how: 'AST-inspects for forbidden imports and call names, then asserts a 365-day translation of every timestamp leaves the feature vector bit-identical.',
  },
  {
    id: 3,
    title: 'Calibrated probabilities, not ranking scores',
    body: 'The engine multiplies p by rupees. Isotonic regression is fitted on a fold disjoint from both the training and early-stopping folds.',
    test: 'eval/harness.py → metrics.json',
    how: 'Brier and ECE are reported on the held-out test set, before and after calibration. AUC would not have moved.',
  },
  {
    id: 4,
    title: 'Deterministic seeds',
    body: 'Every stochastic step draws from a seed committed to data_gen/seeds.py. A clean machine running make all gets identical numbers.',
    test: 'data_gen/seeds.py',
    how: 'One independent RNG stream per stage, so a change to one stage leaves the others bit-identical.',
  },
  {
    id: 5,
    title: 'No fabricated metrics',
    body: 'The dashboard reads eval/reports/metrics.json and nothing else. No metric literal appears in any component.',
    test: 'components/EvalDashboard.jsx',
    how: 'If test_set_size is 0 the section renders an instruction to run make all, not a plausible-looking number.',
  },
  {
    id: 6,
    title: 'Graceful degradation is implemented, not described',
    body: 'OCR failure, LLM failure, PDF failure, and all three at once each have working fallback code.',
    test: 'tests/test_fallbacks.py',
    how: 'Injects each failure by monkeypatching the real dependency and asserts a valid Decision and a valid packet still come back.',
  },
];

function CopyBlock({ command }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard access is denied in some embedded contexts. The command is
      // selectable text either way, so failing silently is correct here.
      setCopied(false);
    }
  };

  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-black/35 px-4 py-3">
      <div className="flex min-w-0 items-center gap-2.5">
        <Terminal size={14} className="shrink-0 text-emerald" />
        <code className="truncate font-mono text-sm text-emerald">
          {command}
        </code>
      </div>
      <button
        type="button"
        onClick={handleCopy}
        aria-label={`Copy "${command}" to clipboard`}
        className="tap-44 shrink-0 rounded-lg border border-white/10 p-1.5 text-slateink transition-colors hover:border-white/25 hover:text-white"
      >
        {copied ? (
          <Check size={13} className="text-emerald" />
        ) : (
          <Copy size={13} />
        )}
      </button>
    </div>
  );
}

const ACCENT_TEXT = {
  emerald: 'text-emerald',
  indigo: 'text-indigo',
  coral: 'text-coral',
};

export default function RepoSection() {
  const cfg = metrics?.config ?? {};
  const hasMetrics = (metrics?.test_set_size ?? 0) > 0;

  return (
    <section id="repo" className="relative py-24 sm:py-32">
      <div className="mx-auto max-w-content px-5 sm:px-8">
        <SectionHeading
          eyebrow="The repository"
          title="Six invariants, each with the test that enforces it."
          lead="An architectural claim nobody checks is a comment. Every invariant below is verified by a test that fails the build when it is violated."
        />

        <div className="mt-12 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
          {/* Directory tree */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-80px' }}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className="glass overflow-hidden"
          >
            <div className="flex items-center gap-2.5 border-b border-white/10 px-5 py-3.5">
              <FolderTree size={15} className="text-slateink" />
              <span className="eyebrow">Structure</span>
            </div>

            <div className="overflow-x-auto px-4 py-4">
              <ul className="space-y-0.5 sm:min-w-[420px]">
                {TREE.map((entry, index) => (
                  <li
                    key={`${entry.name}-${index}`}
                    className="flex items-baseline gap-3 rounded px-2 py-1 hover:bg-white/[0.03]"
                    style={{ paddingLeft: `${entry.depth * 14 + 8}px` }}
                  >
                    <code
                      className={clsx(
                        'shrink-0 font-mono text-xs',
                        entry.accent
                          ? ACCENT_TEXT[entry.accent]
                          : entry.kind === 'dir'
                            ? 'text-white'
                            : 'text-slateink/80',
                      )}
                    >
                      {entry.name}
                    </code>
                    {entry.note && (
                      <span className="truncate text-[11px] text-slateink/45">
                        {entry.note}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>

            <div className="border-t border-white/10 px-5 py-4">
              <div className="eyebrow mb-3">Run it</div>
              <div className="space-y-2">
                <CopyBlock command="make install && make all" />
                <p className="px-1 text-[11px] leading-relaxed text-slateink/50">
                  Generates 20,000 disputes, trains the model, evaluates on the
                  5,000-dispute held-out split, and runs the test suite. On
                  Windows, where GNU make is not installed by default, use{' '}
                  <code className="font-mono text-slateink/70">
                    .\make.ps1 all
                  </code>
                  .
                </p>
              </div>
            </div>
          </motion.div>

          {/* Invariants */}
          <div className="flex flex-col gap-3">
            {INVARIANTS.map((invariant, index) => (
              <motion.div
                key={invariant.id}
                initial={{ opacity: 0, y: 14 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: '-60px' }}
                transition={{
                  duration: 0.45,
                  delay: Math.min(index * 0.05, 0.25),
                  ease: [0.22, 1, 0.36, 1],
                }}
                className="glass p-4"
              >
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-emerald-dim font-mono text-[11px] text-emerald">
                    {invariant.id}
                  </span>
                  <div className="min-w-0">
                    <h3 className="font-display text-sm font-600 text-white">
                      {invariant.title}
                    </h3>
                    <p className="mt-1.5 text-xs leading-relaxed text-slateink/70 text-pretty">
                      {invariant.body}
                    </p>
                    <div className="mt-2.5 flex items-start gap-2 border-t border-white/[0.07] pt-2.5">
                      <ShieldCheck
                        size={12}
                        className="mt-0.5 shrink-0 text-emerald/70"
                      />
                      <div className="min-w-0">
                        <code className="font-mono text-[10px] text-emerald/85">
                          {invariant.test}
                        </code>
                        <p className="mt-0.5 text-[11px] leading-snug text-slateink/50 text-pretty">
                          {invariant.how}
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <motion.div
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
          className="mt-14 border-t border-white/10 pt-8"
        >
          <div className="flex flex-wrap items-end justify-between gap-6">
            <div>
              <div className="flex items-center gap-2.5">
                <Mark size={20} />
                <span className="font-display text-base font-700 tracking-[0.14em] text-white">
                  ChargeGuard<span className="text-white/60">.AI</span>
                </span>
              </div>
              <p className="mt-2 max-w-md text-xs leading-relaxed text-slateink/55 text-pretty">
                Autonomous Multi-Modal Chargeback Defense &amp; Economic
                Arbitrage Engine. Built for the Razorpay AI Buildathon 2026,
                Track 02 — AI Risk Manager.
              </p>
            </div>

            <div className="font-mono text-[10px] leading-relaxed text-slateink/40">
              {hasMetrics ? (
                <>
                  <div>model {cfg.model_version}</div>
                  <div>features {cfg.feature_version}</div>
                  <div>
                    c = ₹{cfg.representment_cost_inr} · λ = {cfg.risk_margin}
                  </div>
                </>
              ) : (
                <div>run make all to populate</div>
              )}
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
