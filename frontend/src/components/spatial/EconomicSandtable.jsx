import { useMemo, useState } from 'react';

import { useSpatialTilt } from './useSpatialTilt.js';
import {
  AMOUNT_MIN,
  AMOUNT_MAX,
  COST_MIN,
  COST_MAX,
  MARGIN_MIN,
  MARGIN_MAX,
  DEFAULT_COST_INR,
  DEFAULT_RISK_MARGIN,
  decisionThreshold,
  expectedValue,
  applyEvRule,
  formatInr,
  formatInrCompact,
  formatPercent,
  formatThreshold,
} from '../../lib/economics.js';

/**
 * 02 -- the economic governor sandtable: a live 3D EV surface, sliced by the
 * threshold curve, driven by the exact functions the rest of the site uses.
 *
 * A NOTE ON THE FORMULA. This build was specified against
 * p* = c / (lambda * A + c). That is not the rule this repository ships:
 * lib/economics.js (mirroring backend/.../policy/economics.py, and used by
 * both ArbitrageVisualizer and Simulator elsewhere on this page) is
 * p* = lambda * c / A. Building a second, quietly different "truth" into one
 * more component would let this page disagree with itself about its own
 * central claim, so this sandtable calls the same decisionThreshold /
 * expectedValue / applyEvRule everything else does. Flagged here and in the
 * accompanying summary rather than silently substituted.
 *
 * THE SURFACE. EV = p*A - c does not depend on lambda (see economics.js's own
 * docstring), so the grid plots EV over a (probability x amount) mesh at the
 * slider's cost, and the threshold curve is overlaid as a ridge of lit cells
 * -- the actual boundary the policy engine draws through that same surface.
 * Amount is log-spaced, matching every other amount axis on this page,
 * because a linear axis buries the interesting range in a few pixels.
 */

const P_STEPS = 7;
const A_STEPS = 9;
const SPACING_X = 34;
const SPACING_Z = 30;
const AMOUNT_LOG_MIN = Math.log(AMOUNT_MIN);
const AMOUNT_LOG_MAX = Math.log(AMOUNT_MAX);

function sliderToAmount(position) {
  return Math.exp(AMOUNT_LOG_MIN + position * (AMOUNT_LOG_MAX - AMOUNT_LOG_MIN));
}
function amountToSlider(amount) {
  return (Math.log(amount) - AMOUNT_LOG_MIN) / (AMOUNT_LOG_MAX - AMOUNT_LOG_MIN);
}

function Slider({ label, value, display, onChange, min, max, step }) {
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="eyebrow">{label}</span>
        <span className="font-mono font-tnum text-sm text-white">{display}</span>
      </div>
      <input
        type="range"
        className="slider mt-1.5"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}

export default function EconomicSandtable() {
  const { containerRef, rigRef } = useSpatialTilt({ spin: 0 });

  const [pWin, setPWin] = useState(0.73);
  const [amountPos, setAmountPos] = useState(amountToSlider(18500));
  const [costInr, setCostInr] = useState(DEFAULT_COST_INR);
  const [riskMargin, setRiskMargin] = useState(DEFAULT_RISK_MARGIN);

  const amountInr = useMemo(() => sliderToAmount(amountPos), [amountPos]);
  const ev = applyEvRule(pWin, amountInr, costInr, riskMargin);

  const grid = useMemo(() => {
    const cells = [];
    for (let a = 0; a < A_STEPS; a += 1) {
      const amt = sliderToAmount(a / (A_STEPS - 1));
      const threshold = decisionThreshold(amt, costInr, riskMargin);
      for (let j = 0; j < P_STEPS; j += 1) {
        const p = j / (P_STEPS - 1);
        const cellEv = expectedValue(p, amt, costInr);
        const onRidge = Math.abs(p - threshold) < 1 / (P_STEPS - 1) / 1.4;
        cells.push({
          key: `${a}-${j}`,
          x: (a - (A_STEPS - 1) / 2) * SPACING_X,
          z: (j - (P_STEPS - 1) / 2) * SPACING_Z,
          height: Math.max(4, Math.min(70, 12 + Math.abs(cellEv) / 900)),
          positive: cellEv >= 0,
          onRidge,
        });
      }
    }
    return cells;
  }, [costInr, riskMargin]);

  const selCol = {
    x: (amountPos * (A_STEPS - 1) - (A_STEPS - 1) / 2) * SPACING_X,
    z: (pWin * (P_STEPS - 1) - (P_STEPS - 1) / 2) * SPACING_Z,
  };

  const ridgeColor = (positive) => (positive ? 'rgba(16,185,129,0.9)' : 'rgba(249,115,98,0.9)');
  const cellColor = (positive) => (positive ? 'rgba(16,185,129,0.55)' : 'rgba(249,115,98,0.5)');

  return (
    <div className="mx-auto max-w-content px-5 sm:px-8">
      <div className="grid gap-10 lg:grid-cols-[1fr_1.2fr] lg:items-center">
        <div>
          <div className="eyebrow">Spatial workflow · 02</div>
          <h3 className="mt-3 font-display text-3xl font-700 leading-tight text-white sm:text-4xl">
            The governor sees
            <br />
            the whole surface.
          </h3>
          <p className="mt-4 max-w-md text-base leading-relaxed" style={{ color: '#94A3B8' }}>
            Expected value does not depend on the risk margin -- only the
            threshold does. Move the sliders and watch the lit ridge, not the
            surface underneath it, redraw.
          </p>

          <div className="mt-6 space-y-5">
            <Slider
              label="p -- win probability"
              value={pWin}
              display={formatPercent(pWin, 1)}
              onChange={setPWin}
              min={0}
              max={1}
              step={0.01}
            />
            <Slider
              label="A -- disputed amount"
              value={amountPos}
              display={formatInrCompact(amountInr)}
              onChange={setAmountPos}
              min={0}
              max={1}
              step={0.001}
            />
            <Slider
              label="c -- representment cost"
              value={costInr}
              display={formatInr(costInr)}
              onChange={setCostInr}
              min={COST_MIN}
              max={COST_MAX}
              step={10}
            />
            <Slider
              label="lambda -- risk margin"
              value={riskMargin}
              display={riskMargin.toFixed(2)}
              onChange={setRiskMargin}
              min={MARGIN_MIN}
              max={MARGIN_MAX}
              step={0.01}
            />
          </div>

          <div className="spatial-glass mt-6 grid grid-cols-2 gap-4 rounded-2xl p-4 font-mono font-tnum text-sm">
            <div>
              <div className="text-[10px] tracking-[0.1em]" style={{ color: '#5A6577' }}>
                THRESHOLD p*
              </div>
              <div className="mt-1 text-white">{formatThreshold(ev.threshold)}</div>
            </div>
            <div>
              <div className="text-[10px] tracking-[0.1em]" style={{ color: '#5A6577' }}>
                EXPECTED VALUE
              </div>
              <div className="mt-1" style={{ color: ev.expectedValue >= 0 ? '#62C6D7' : '#E58B84' }}>
                {ev.expectedValue >= 0 ? '+' : ''}
                {formatInr(ev.expectedValue)}
              </div>
            </div>
            <div className="col-span-2 flex items-center gap-2">
              <span
                className="rounded-full px-2.5 py-1 text-[11px] font-600"
                style={{
                  background: ev.action === 'CONTEST' ? 'rgba(16,185,129,0.16)' : 'rgba(148,163,184,0.14)',
                  color: ev.action === 'CONTEST' ? '#62C6D7' : '#AEBFC7',
                }}
              >
                {ev.action}
              </span>
              <span className="text-[11px]" style={{ color: '#8A94A6' }}>
                margin {ev.margin >= 0 ? '+' : ''}
                {(ev.margin * 100).toFixed(1)}pp
              </span>
            </div>
          </div>
        </div>

        <div
          ref={containerRef}
          className="spatial-viewport relative mx-auto flex h-[420px] w-full max-w-[460px] items-center justify-center"
        >
          <div ref={rigRef} className="spatial-rig relative" style={{ width: 1, height: 1 }}>
            {grid.map((c) => (
              <div
                key={c.key}
                className="spatial-node absolute rounded-[2px]"
                style={{
                  width: 14,
                  height: c.height,
                  transform: `translate3d(${c.x}px, ${-c.height / 2}px, ${c.z}px)`,
                  background: cellColor(c.positive),
                  boxShadow: c.onRidge ? `0 0 14px 2px ${ridgeColor(c.positive)}` : 'none',
                  outline: c.onRidge ? '1px solid rgba(255,255,255,0.6)' : 'none',
                  opacity: c.onRidge ? 1 : 0.55,
                }}
              />
            ))}

            {/* The reader's own (p, A) as a bright marker column. */}
            <div
              className="spatial-node absolute rounded-full"
              style={{
                width: 10,
                height: 10,
                transform: `translate3d(${selCol.x}px, -96px, ${selCol.z}px) translate(-50%, -50%)`,
                background: '#F5F7FA',
                boxShadow: '0 0 20px 6px rgba(255,255,255,0.75)',
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
