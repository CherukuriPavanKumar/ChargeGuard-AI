import { useMemo, useState } from 'react';

import { useSpatialTilt } from './useSpatialTilt.js';
import { evidenceSignals } from './attribution.js';

/**
 * 01 — the neural lattice: the evidence bundle of the active case, drawn as a
 * node graph orbiting a central "risk" node, tilted in 3D under the cursor.
 *
 * Each node is one field from `lib/presets.js`'s real evidence bundle for the
 * selected case; edge colour and thickness encode `evidenceSignals()`'s
 * heuristic signal (see that file's docstring: an illustrative, deterministic
 * UI weighting, explicitly NOT the shipped LightGBM model's SHAP output,
 * which cannot run client-side and is not committed anywhere in the repo).
 * That caveat is also stated on screen, not just in code -- the same honesty
 * discipline `renderOfflinePacket` already applies to the simulator's
 * generated documents.
 *
 * The whole composition sits on one flat plane rotated as a single rigid body
 * (`useSpatialTilt`), with a small per-node Z stagger for a layered-depth cue.
 * This is a deliberate simplification over projecting true 3D node positions
 * through a camera matrix: at this node count, a tilted flat lattice reads as
 * spatial without the complexity (or the WebGL this project's build brief
 * repeatedly warns off) of a real point-cloud renderer.
 */
export default function NeuralLattice({ preset }) {
  const { containerRef, rigRef } = useSpatialTilt({ spin: 3 });
  const [hovered, setHovered] = useState(null);

  const signals = useMemo(() => evidenceSignals(preset), [preset]);
  const RADIUS = 168;

  const nodes = useMemo(
    () =>
      signals.map((s, i) => {
        const angle = (i / signals.length) * Math.PI * 2 - Math.PI / 2;
        return {
          ...s,
          x: Math.cos(angle) * RADIUS,
          y: Math.sin(angle) * RADIUS,
          z: ((i % 3) - 1) * 16,
        };
      }),
    [signals],
  );

  const active = hovered ? nodes.find((n) => n.key === hovered) : null;

  return (
    <div className="mx-auto max-w-content px-5 sm:px-8">
      <div className="grid gap-10 lg:grid-cols-[1fr_1.15fr] lg:items-center">
        <div>
          <div className="eyebrow">Spatial workflow · 01</div>
          <h3 className="mt-3 font-display text-3xl font-700 leading-tight text-white sm:text-4xl">
            The lattice reads<br />the evidence.
          </h3>
          <p className="mt-4 max-w-md text-base leading-relaxed" style={{ color: '#94A3B8' }}>
            Every field in the evidence bundle pulls the case toward CONTEST or
            toward ACCEPT. Move the cursor over the lattice to inspect one
            field at a time.
          </p>
          <p className="mt-4 max-w-md text-xs leading-relaxed" style={{ color: '#5A6577' }}>
            Edge weight is an illustrative heuristic over the evidence bundle —
            not the shipped LightGBM model's SHAP output, which cannot run in
            the browser.
          </p>

          {active && (
            <div className="spatial-glass mt-6 max-w-sm rounded-2xl p-4">
              <div className="font-mono text-[10px] tracking-[0.14em]" style={{ color: '#5A6577' }}>
                {active.label.toUpperCase()}
              </div>
              <div className="mt-1 font-mono font-tnum text-lg" style={{ color: '#E8EBF0' }}>
                {active.value}
              </div>
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.abs(active.signal) * 100}%`,
                    marginLeft: active.signal < 0 ? `${100 - Math.abs(active.signal) * 100}%` : 0,
                    background: active.signal >= 0 ? '#62C6D7' : '#E58B84',
                  }}
                />
              </div>
              <div className="mt-1.5 font-mono font-tnum text-[11px]" style={{ color: '#8A94A6' }}>
                signal {active.signal >= 0 ? '+' : ''}
                {active.signal.toFixed(2)} · favours {active.signal >= 0 ? 'CONTEST' : 'ACCEPT'}
              </div>
            </div>
          )}
        </div>

        <div
          ref={containerRef}
          className="spatial-viewport relative mx-auto flex h-[420px] w-full max-w-[440px] items-center justify-center"
        >
          <div ref={rigRef} className="spatial-rig relative" style={{ width: 1, height: 1 }}>
            {/* Edges, flat on the rig's own plane so they inherit its rotation as one rigid sheet. */}
            <svg
              className="absolute overflow-visible"
              style={{ left: 0, top: 0, width: 1, height: 1 }}
              aria-hidden="true"
            >
              {nodes.map((n) => (
                <line
                  key={n.key}
                  x1={0}
                  y1={0}
                  x2={n.x}
                  y2={n.y}
                  stroke={n.signal >= 0 ? 'rgba(16,185,129,0.55)' : 'rgba(249,115,98,0.5)'}
                  strokeWidth={0.6 + Math.abs(n.signal) * 2.2}
                  opacity={hovered && hovered !== n.key ? 0.25 : 0.9}
                />
              ))}
            </svg>

            {/* Central risk node. */}
            <div
              className="spatial-node absolute flex h-16 w-16 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full"
              style={{
                background: 'radial-gradient(circle, rgba(16,185,129,0.35), rgba(16,185,129,0.05))',
                border: '1px solid rgba(16,185,129,0.5)',
                boxShadow: '0 0 40px -8px rgba(16,185,129,0.6)',
              }}
            >
              <span className="font-mono text-[9px] tracking-[0.1em]" style={{ color: '#8FE3C0' }}>
                RISK
              </span>
            </div>

            {nodes.map((n) => (
              <button
                key={n.key}
                type="button"
                onMouseEnter={() => setHovered(n.key)}
                onMouseLeave={() => setHovered((h) => (h === n.key ? null : h))}
                onFocus={() => setHovered(n.key)}
                onBlur={() => setHovered((h) => (h === n.key ? null : h))}
                className="spatial-node absolute flex h-11 w-11 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full text-center"
                style={{
                  transform: `translate3d(${n.x}px, ${n.y}px, ${n.z}px) translate(-50%, -50%)`,
                  background: 'rgba(13,18,31,0.9)',
                  border: `1px solid ${n.signal >= 0 ? 'rgba(16,185,129,0.55)' : 'rgba(249,115,98,0.5)'}`,
                  boxShadow:
                    hovered === n.key
                      ? `0 0 24px -4px ${n.signal >= 0 ? 'rgba(16,185,129,0.8)' : 'rgba(249,115,98,0.8)'}`
                      : 'none',
                  opacity: hovered && hovered !== n.key ? 0.45 : 1,
                }}
              >
                <span
                  className="px-1 font-mono text-[7.5px] leading-tight tracking-tight"
                  style={{ color: '#CBD5E1' }}
                >
                  {n.label.split(' ')[0]}
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
