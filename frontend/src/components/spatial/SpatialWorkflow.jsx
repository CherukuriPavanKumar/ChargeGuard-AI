import { useState } from 'react';

import { PRESETS, getPreset } from '../../lib/presets.js';
import NeuralLattice from './NeuralLattice.jsx';
import EconomicSandtable from './EconomicSandtable.jsx';
import DossierAssembly from './DossierAssembly.jsx';
import AttackSimulator from './AttackSimulator.jsx';
import './spatial.css';

/**
 * The continuous 3D spatial workflow that picks up where the hero leaves off:
 * one case, three still-real-data 3D panels (lattice, sandtable, dossier),
 * then a sandbox that runs the actual offline decision path against it.
 *
 * ONE CASE SELECTOR, SHARED. The lattice, dossier and simulator all read the
 * same `activePreset` from `lib/presets.js` -- the same three real cases the
 * (separate, further down the page) Simulator section uses -- so switching
 * "which dispute" here is one decision, not three unsynchronised ones. The
 * sandtable is the one panel that ignores it: it plots the EV surface in the
 * abstract (p, A, c, lambda), not one case's numbers.
 *
 * Each panel is its own component with its own tilt rig and its own
 * IntersectionObserver-gated animation (see `useSpatialTilt`), so nothing
 * here needs a shared rAF loop the way the hero's Stage.jsx does -- these
 * sections don't share geometry with each other, they just share a palette,
 * a glass treatment (`spatial.css`), and this one case selector.
 */
export default function SpatialWorkflow() {
  const [presetKey, setPresetKey] = useState(PRESETS[0].key);
  const preset = getPreset(presetKey);

  return (
    <div className="relative py-24 sm:py-32">
      <div className="mx-auto max-w-content px-5 sm:px-8">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-6">
          <div>
            <div className="eyebrow">Continuous spatial workflow</div>
            <h2 className="mt-2 font-display text-2xl font-700 text-white sm:text-3xl">
              One case, followed through the whole system.
            </h2>
          </div>
          <div className="flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <button
                key={p.key}
                type="button"
                onClick={() => setPresetKey(p.key)}
                className="rounded-lg border px-3 py-2 font-mono text-[11px] font-500 transition-colors"
                style={{
                  borderColor: p.key === presetKey ? 'rgba(16,185,129,0.5)' : 'rgba(255,255,255,0.12)',
                  background: p.key === presetKey ? 'rgba(16,185,129,0.12)' : 'transparent',
                  color: p.key === presetKey ? '#62C6D7' : '#AEBFC7',
                }}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-20 space-y-28 sm:mt-28 sm:space-y-36">
        <NeuralLattice preset={preset} />
        <EconomicSandtable />
        <DossierAssembly preset={preset} />
        <AttackSimulator preset={preset} />
      </div>
    </div>
  );
}
