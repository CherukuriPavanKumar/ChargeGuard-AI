import { AnimatePresence, motion } from 'framer-motion';
import { useMemo } from 'react';

import { artifactIndex } from '../../lib/presets.js';
import { evidenceSignals } from './attribution.js';

/**
 * 03 -- the dossier assembles: real artifact identifiers for the active case,
 * arriving one at a time, alongside a feature-attribution readout.
 *
 * `artifactIndex()` is imported straight from lib/presets.js -- the same
 * function the (existing) Simulator section uses to list what evidence a
 * representment packet actually cites. Nothing here invents an artifact.
 *
 * The bars below are the same `evidenceSignals()` heuristic the neural
 * lattice uses, re-sorted by magnitude and re-labelled once more as what it
 * is: an illustrative client-side weighting, not the shipped LightGBM
 * model's SHAP output. Repeating the caveat here rather than assuming a
 * reader who scrolled past the lattice already has it in mind.
 */
const EASE = [0.22, 1, 0.36, 1];

export default function DossierAssembly({ preset }) {
  const artifacts = useMemo(() => artifactIndex(preset), [preset]);
  const signals = useMemo(
    () => [...evidenceSignals(preset)].sort((a, b) => Math.abs(b.signal) - Math.abs(a.signal)),
    [preset],
  );

  return (
    <div className="mx-auto max-w-content px-5 sm:px-8">
      <div className="grid gap-10 lg:grid-cols-2 lg:items-start">
        <div>
          <div className="eyebrow">Spatial workflow · 03</div>
          <h3 className="mt-3 font-display text-3xl font-700 leading-tight text-white sm:text-4xl">
            The dossier
            <br />
            assembles itself.
          </h3>
          <p className="mt-4 max-w-md text-base leading-relaxed" style={{ color: '#94A3B8' }}>
            Every artifact cited below is real: the same identifiers{' '}
            <code className="font-mono text-xs" style={{ color: '#8FE3C0' }}>
              artifactIndex()
            </code>{' '}
            hands the representment packet in the Simulator section, for the
            case currently selected.
          </p>

          <div className="spatial-glass mt-6 overflow-hidden rounded-2xl p-5">
            <div className="font-mono text-[10px] tracking-[0.14em]" style={{ color: '#5A6577' }}>
              CASE {preset.dispute.disputeId.replace('dp_', '').toUpperCase()} · ARTIFACT INDEX
            </div>
            <AnimatePresence mode="popLayout">
              <motion.ul key={preset.key} className="mt-3 space-y-2">
                {artifacts.map((a, i) => (
                  <motion.li
                    key={a}
                    initial={{ opacity: 0, x: -14 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.35, delay: i * 0.08, ease: EASE }}
                    className="flex items-center gap-2 font-mono text-[11px]"
                    style={{ color: '#CBD5E1' }}
                  >
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: '#62C6D7' }} />
                    {a}
                  </motion.li>
                ))}
              </motion.ul>
            </AnimatePresence>
          </div>
        </div>

        <div>
          <div className="spatial-glass rounded-2xl p-5">
            <div className="flex items-baseline justify-between">
              <span className="font-mono text-[10px] tracking-[0.14em]" style={{ color: '#5A6577' }}>
                FEATURE ATTRIBUTION
              </span>
              <span className="font-mono text-[9px]" style={{ color: '#4A5464' }}>
                illustrative -- not SHAP
              </span>
            </div>
            <div className="mt-4 space-y-3">
              {signals.map((s) => (
                <div key={s.key}>
                  <div className="flex items-center justify-between text-[11px]">
                    <span style={{ color: '#94A3B8' }}>{s.label}</span>
                    <span className="font-mono font-tnum" style={{ color: '#CBD5E1' }}>
                      {s.value}
                    </span>
                  </div>
                  <div className="relative mt-1 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${Math.abs(s.signal) * 100}%` }}
                      transition={{ duration: 0.5, ease: EASE }}
                      className="absolute h-full rounded-full"
                      style={{
                        left: s.signal < 0 ? 'auto' : '50%',
                        right: s.signal < 0 ? '50%' : 'auto',
                        background: s.signal >= 0 ? '#62C6D7' : '#E58B84',
                      }}
                    />
                    <div className="absolute inset-y-0 left-1/2 w-px bg-white/25" />
                  </div>
                </div>
              ))}
            </div>
            <p className="mt-4 text-[10.5px] leading-relaxed" style={{ color: '#5A6577' }}>
              A deterministic heuristic over this case's evidence bundle, for
              this visualisation only. The shipped model's real attribution
              (SHAP over the LightGBM booster) cannot run in the browser and
              is not committed anywhere in this repository.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
