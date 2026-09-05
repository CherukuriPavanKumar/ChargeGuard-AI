import { Github, Terminal } from 'lucide-react';

import metrics from '../../data/metrics.json';
import { scrollToSection } from '../../hooks/useScrollSpy.js';
import {
  formatInr,
  formatPercent,
} from '../../lib/economics.js';
import { HERO_CASE, HERO_EV, HERO_THRESHOLD, PLATES } from './plateData.js';

const STATUS_METRIC = `${(metrics.economics.oracle_efficiency * 100).toFixed(1)}%`;

function Signal({ label, value, tone = 'text-emerald' }) {
  return (
    <div className="flex items-center justify-between gap-4 border-t border-white/10 py-3 first:border-0 first:pt-0 last:pb-0">
      <span className="text-sm text-slateink">{label}</span>
      <span className={`text-right font-mono text-sm ${tone}`}>{value}</span>
    </div>
  );
}

function Plate({ plate }) {
  return (
    <article className="rounded-xl border border-white/10 bg-white/[0.025] p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.16em]" style={{ color: plate.accent }}>
            {plate.n} · {plate.title}
          </p>
          <h3 className="mt-2 font-display text-lg font-600 text-white">{plate.big}</h3>
        </div>
        {plate.score && <span className="font-mono text-xl text-indigo">{plate.score}</span>}
        {plate.pill && <span className="rounded-full bg-emerald-dim px-2.5 py-1 font-mono text-xs text-emerald">{plate.pill.value}</span>}
        {plate.evBadge && <span className="font-mono text-sm text-emerald">{plate.evBadge}</span>}
      </div>
      <div className="mt-4">
        {plate.rows.map((row) => (
          <Signal key={row.k} label={row.k} value={row.v} tone={row.k === 'Verdict' ? 'text-emerald' : 'text-slateink/90'} />
        ))}
      </div>
      {plate.badge && <p className="mt-4 font-mono text-[10px] text-slateink/60">{plate.badge}</p>}
      {plate.footnote && <p className="mt-4 text-xs text-slateink/60">{plate.footnote}</p>}
    </article>
  );
}

export default function HeroSequence() {
  return (
    <section id="hero" className="relative px-5 pb-20 pt-28 sm:px-8 sm:pt-36">
      <div className="mx-auto max-w-content">
        <div className="grid items-start gap-12 lg:grid-cols-5 lg:gap-20">
          <div className="max-w-2xl lg:col-span-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-emerald/25 bg-emerald-dim px-3 py-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald" />
              <span className="font-mono text-2xs uppercase tracking-[0.16em] text-emerald">
                Autonomous dispute defense engine
              </span>
            </div>

            <h1
              className="mt-7 max-w-xl font-display font-700 tracking-tight text-white"
              style={{ fontSize: 'clamp(3.25rem, 6vw, 5.75rem)', lineHeight: 0.98 }}
            >
              Every dispute,
              <span className="block text-emerald">priced to defend.</span>
            </h1>

            <p className="mt-7 max-w-xl text-lg leading-relaxed text-slateink sm:text-xl">
              Real-time LightGBM inference scores every chargeback, then a per-dispute
              economic threshold decides which cases are worth contesting. Not a
              blanket policy. One verdict, priced per dispute.
            </p>

            <div className="mt-7 inline-flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-white/10 bg-surface px-4 py-3 font-mono text-sm">
              <span className="text-slateink/70">contest when</span>
              <span className="text-white">p* = λ·c / A</span>
              <span className="text-slateink/70">and expected recovery beats cost</span>
            </div>

            <div className="mt-8 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => scrollToSection('simulator')}
                className="inline-flex min-h-[44px] items-center gap-2 rounded-lg bg-emerald px-5 py-3 font-display text-sm font-600 text-obsidian transition-colors hover:bg-emerald/90"
              >
                <Terminal size={16} />
                Run the simulator
              </button>
              <button
                type="button"
                onClick={() => scrollToSection('verify')}
                className="inline-flex min-h-[44px] items-center gap-2 rounded-lg border border-white/15 px-5 py-3 font-display text-sm font-600 text-white transition-colors hover:border-emerald/40 hover:text-emerald"
              >
                <Github size={16} />
                Verify it yourself
              </button>
            </div>

            <div className="mt-10 flex flex-wrap gap-x-8 gap-y-4 border-t border-white/10 pt-5">
              <div>
                <p className="font-mono text-2xl text-emerald">{STATUS_METRIC}</p>
                <p className="mt-1 text-xs text-slateink/65">of oracle-optimal recovery captured</p>
              </div>
              <div>
                <p className="font-mono text-2xl text-white">{metrics.test_set_size.toLocaleString('en-IN')}</p>
                <p className="mt-1 text-xs text-slateink/65">held-out disputes</p>
              </div>
              <div>
                <p className="font-mono text-2xl text-white">{metrics.classifier.ece.toFixed(3)}</p>
                <p className="mt-1 text-xs text-slateink/65">expected calibration error</p>
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-emerald/20 bg-surface p-5 shadow-xl shadow-black/20 sm:p-7 lg:col-span-2">
            <div className="flex items-start justify-between gap-4 border-b border-white/10 pb-5">
              <div>
                <p className="eyebrow text-emerald/80">Live case</p>
                <h2 className="mt-1 font-display text-xl font-600 text-white">#{HERO_CASE.id}</h2>
                <p className="mt-1 font-mono text-xs text-slateink/65">
                  {HERO_CASE.reasonCode} · {HERO_CASE.reasonLabel}
                </p>
              </div>
              <span className="rounded-full bg-emerald-dim px-3 py-1.5 font-mono text-xs tracking-wider text-emerald">
                {HERO_CASE.decision}
              </span>
            </div>

            <div className="mt-6 grid grid-cols-2 gap-3">
              <div className="rounded-lg bg-white/[0.04] p-4">
                <p className="eyebrow text-slateink/60">Dispute amount</p>
                <p className="mt-2 font-mono text-xl text-white">{formatInr(HERO_CASE.amountInr)}</p>
              </div>
              <div className="rounded-lg bg-white/[0.04] p-4">
                <p className="eyebrow text-slateink/60">Win probability</p>
                <p className="mt-2 font-mono text-xl text-indigo">{formatPercent(HERO_CASE.pWin, 1)}</p>
              </div>
            </div>

            <div className="mt-6">
              <Signal label="Expected value" value={`+${formatInr(HERO_EV)}`} />
              <Signal label="Policy threshold" value={formatPercent(HERO_THRESHOLD, 1)} />
              <Signal label="Evidence match" value={formatPercent(HERO_CASE.nameMatch, 1)} />
              <Signal label="OCR confidence" value={HERO_CASE.ocrConfidence.toFixed(2)} />
              <Signal label="Delivery reference" value={HERO_CASE.awb} />
            </div>

            <p className="mt-5 border-t border-white/10 pt-4 font-mono text-[10px] text-slateink/55">
              Held-out model · {metrics.config.model_version}
            </p>
          </div>
        </div>

        <div className="mt-20 border-t border-white/10 pt-10">
          <div className="max-w-2xl">
            <p className="eyebrow text-emerald/80">Evidence stack</p>
            <h2 className="mt-3 font-display text-3xl font-700 text-white sm:text-4xl">
              Everything the engine considers before it decides.
            </h2>
            <p className="mt-4 text-base leading-relaxed text-slateink">
              The same dispute moves through identity, evidence, intelligence, and
              economics before the policy engine returns a verdict.
            </p>
          </div>

          <div className="mt-8 grid gap-4 md:grid-cols-2">
            {PLATES.map((plate) => <Plate key={plate.n} plate={plate} />)}
          </div>
        </div>
      </div>
    </section>
  );
}