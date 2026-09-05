/**
 * The arbitrage frontier as a static SVG.
 *
 * One component, three jobs:
 *   1. The Suspense fallback while the WebGL scene lazy-loads, so first paint is
 *      never an empty box.
 *   2. The reduced-motion rendering — same plot, points already resolved, no
 *      animation.
 *   3. The source of `public/og.png`, rendered headless at 1200×630.
 *
 * Every coordinate comes from `lib/economics.js`. The frontier here is the exact
 * curve the live scene animates and the simulator evaluates; if they disagreed,
 * one of them would be lying.
 *
 * Scatter is deterministic — a seeded PRNG — so the fallback, the reduced-motion
 * view, and the OG image are pixel-stable across renders. A hero that reshuffled
 * itself between loads would read as noise rather than as a designed plot.
 */

import {
  AMOUNT_MAX,
  AMOUNT_MIN,
  DEFAULT_COST_INR,
  DEFAULT_RISK_MARGIN,
  decisionThreshold,
  thresholdCurve,
} from '../lib/economics.js';

/* -------------------------------------------------------------------------- */
/* Deterministic sampling                                                     */
/* -------------------------------------------------------------------------- */

/** mulberry32 — a tiny deterministic PRNG so the scatter never reshuffles. */
function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Approximate a lognormal amount draw from two uniforms (Box–Muller). */
function sampleAmount(rng) {
  const u1 = Math.max(1e-9, rng());
  const u2 = rng();
  const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  // median ₹2,400, sigma tuned so the tail reaches ~₹80k
  const amount = 2400 * Math.exp(0.95 * z);
  return Math.min(AMOUNT_MAX, Math.max(AMOUNT_MIN, amount));
}

/** A beta-ish win probability via the mean of two uniforms — centred, bounded. */
function sampleProbability(rng) {
  return (rng() + rng() + rng()) / 3;
}

/**
 * Build a stable set of resolved disputes for the given risk margin.
 * `n` points, classified against the live frontier.
 */
export function buildStaticDisputes(
  n = 130,
  cost = DEFAULT_COST_INR,
  lambda = DEFAULT_RISK_MARGIN,
  seed = 0x9e3779b9,
) {
  const rng = mulberry32(seed);
  const out = [];
  for (let i = 0; i < n; i += 1) {
    const amount = sampleAmount(rng);
    const p = sampleProbability(rng);
    const threshold = decisionThreshold(amount, cost, lambda);
    out.push({
      amount,
      p,
      contest: p >= threshold,
      nearFrontier: Math.abs(p - Math.min(threshold, 1)) < 0.05,
    });
  }
  return out;
}

/* -------------------------------------------------------------------------- */
/* Coordinate mapping                                                         */
/* -------------------------------------------------------------------------- */

const LOG_MIN = Math.log(AMOUNT_MIN);
const LOG_MAX = Math.log(AMOUNT_MAX);

/** Amount → x in [0,1] on a log axis. */
function ax(amount) {
  return (Math.log(amount) - LOG_MIN) / (LOG_MAX - LOG_MIN);
}

const AMOUNT_TICKS = [100, 1000, 10000, 100000];
const P_TICKS = [0, 0.25, 0.5, 0.75, 1];

function fmtAmount(v) {
  if (v >= 100000) return '₹1L';
  if (v >= 1000) return `₹${v / 1000}k`;
  return `₹${v}`;
}

/* -------------------------------------------------------------------------- */
/* Component                                                                  */
/* -------------------------------------------------------------------------- */

export default function ArbitrageFrontierStatic({
  width = 640,
  height = 460,
  lambda = DEFAULT_RISK_MARGIN,
  cost = DEFAULT_COST_INR,
  disputes,
  showChrome = false, // wordmark + formula, for the OG image
  className = '',
}) {
  // Plot inset — leave room for tick labels without a full grid.
  const padL = 44;
  const padR = 22;
  const padT = showChrome ? 96 : 26;
  const padB = 34;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;

  const px = (a) => padL + ax(a) * plotW;
  const py = (p) => padT + (1 - p) * plotH;

  const curve = thresholdCurve(cost, lambda, 96);
  const curvePath = curve
    .map((pt, i) => `${i === 0 ? 'M' : 'L'}${px(pt.amount).toFixed(2)} ${py(pt.threshold).toFixed(2)}`)
    .join(' ');

  // Territory washes: above the curve is CONTEST (emerald), below is ACCEPT
  // (coral). Built by closing the frontier path to the top and bottom edges.
  const abovePath = `${curvePath} L${px(AMOUNT_MAX).toFixed(2)} ${padT} L${px(AMOUNT_MIN).toFixed(2)} ${padT} Z`;
  const belowPath = `${curvePath} L${px(AMOUNT_MAX).toFixed(2)} ${(padT + plotH).toFixed(2)} L${px(AMOUNT_MIN).toFixed(2)} ${(padT + plotH).toFixed(2)} Z`;

  const points = disputes ?? buildStaticDisputes(130, cost, lambda);

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      role="img"
      aria-label="Arbitrage frontier: calibrated win probability against dispute amount, with the contest/accept decision boundary."
      style={{ maxWidth: '100%', height: 'auto' }}
    >
      <defs>
        <linearGradient id="afs-above" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#62C6D7" stopOpacity="0.06" />
          <stop offset="100%" stopColor="#62C6D7" stopOpacity="0.015" />
        </linearGradient>
        <linearGradient id="afs-below" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#E58B84" stopOpacity="0.015" />
          <stop offset="100%" stopColor="#E58B84" stopOpacity="0.06" />
        </linearGradient>
        <linearGradient id="afs-frontier" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#34D399" />
          <stop offset="100%" stopColor="#62C6D7" />
        </linearGradient>
        {showChrome && (
          <linearGradient id="afs-bg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#0A0D14" />
            <stop offset="100%" stopColor="#0d1320" />
          </linearGradient>
        )}
      </defs>

      {showChrome && <rect width={width} height={height} fill="url(#afs-bg)" />}

      {/* Territory washes */}
      <path d={abovePath} fill="url(#afs-above)" />
      <path d={belowPath} fill="url(#afs-below)" />

      {/* Axes — hairlines only, no grid. */}
      <line
        x1={padL}
        y1={padT}
        x2={padL}
        y2={padT + plotH}
        stroke="#AEBFC7"
        strokeOpacity="0.08"
      />
      <line
        x1={padL}
        y1={padT + plotH}
        x2={padL + plotW}
        y2={padT + plotH}
        stroke="#AEBFC7"
        strokeOpacity="0.08"
      />

      {/* Sparse tick labels */}
      {AMOUNT_TICKS.map((t) => (
        <text
          key={`ax-${t}`}
          x={px(t)}
          y={padT + plotH + 18}
          textAnchor="middle"
          fontFamily="'JetBrains Mono', monospace"
          fontSize="10"
          fill="#AEBFC7"
          fillOpacity="0.4"
        >
          {fmtAmount(t)}
        </text>
      ))}
      {P_TICKS.map((t) => (
        <text
          key={`py-${t}`}
          x={padL - 8}
          y={py(t) + 3}
          textAnchor="end"
          fontFamily="'JetBrains Mono', monospace"
          fontSize="10"
          fill="#AEBFC7"
          fillOpacity="0.4"
        >
          {t.toFixed(2)}
        </text>
      ))}

      {/* Resolved disputes */}
      {points.map((d, i) => (
        <circle
          key={i}
          cx={px(d.amount)}
          cy={py(d.p)}
          r={d.nearFrontier ? 3.4 : 2.4}
          fill={d.contest ? '#62C6D7' : '#E58B84'}
          fillOpacity={d.nearFrontier ? 0.9 : 0.42}
        />
      ))}

      {/* Frontier bloom (wide, low opacity) then the crisp line on top */}
      <path
        d={curvePath}
        fill="none"
        stroke="#62C6D7"
        strokeOpacity="0.22"
        strokeWidth="7"
        strokeLinecap="round"
      />
      <path
        d={curvePath}
        fill="none"
        stroke="url(#afs-frontier)"
        strokeWidth="2.25"
        strokeLinecap="round"
      />

      {showChrome && (
        <g>
          <text
            x={padL}
            y={44}
            fontFamily="'Space Grotesk', sans-serif"
            fontSize="34"
            fontWeight="700"
            fill="#FFFFFF"
            letterSpacing="1"
          >
            ChargeGuard
            <tspan fill="#62C6D7" fillOpacity="0.6">
              .AI
            </tspan>
          </text>
          <text
            x={padL}
            y={70}
            fontFamily="'JetBrains Mono', monospace"
            fontSize="15"
            fill="#AEBFC7"
          >
            contest ⟺ p ≥ λc / A
          </text>
          <text
            x={width - padR}
            y={44}
            textAnchor="end"
            fontFamily="'Inter', sans-serif"
            fontSize="13"
            fill="#AEBFC7"
            fillOpacity="0.7"
          >
            Economic Arbitrage Engine
          </text>
        </g>
      )}
    </svg>
  );
}
