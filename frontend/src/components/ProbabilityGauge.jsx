import { motion } from 'framer-motion';
import { useId } from 'react';

import { formatPercent, formatThreshold } from '../lib/economics.js';

/**
 * Arc gauge showing p_win against the per-dispute threshold.
 *
 * The threshold is drawn on the *same arc*, not in a separate readout, because
 * the comparison is the decision. Seeing 0.34 next to 0.93 in two boxes is a
 * pair of numbers; seeing the needle sitting well short of a marked line is the
 * argument.
 *
 * The calibration toggle compares the map that **shipped** against the isotonic
 * map that was fitted and then rejected. Not raw-versus-calibrated: on this
 * model the held-out selection chose the identity, so that framing would be a
 * switch that does nothing. Flipping this one shows the counterfactual, and on a
 * dispute near its threshold that movement is the difference between contesting
 * and conceding — which is the clearest way to show why calibration is
 * load-bearing here and merely cosmetic in a system that only ranks.
 */

const SIZE = 260;
const CENTER = SIZE / 2;
const RADIUS = 96;
const STROKE = 14;

// A 240-degree sweep, opening downward. A full circle leaves no natural place
// for the readout; a 180-degree half circle wastes the lower third of the box.
const START_ANGLE = 150;
const SWEEP = 240;

function polar(angleDeg, radius = RADIUS) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return {
    x: CENTER + radius * Math.cos(rad),
    y: CENTER + radius * Math.sin(rad),
  };
}

function arcPath(fromValue, toValue, radius = RADIUS) {
  const a0 = START_ANGLE + SWEEP * Math.max(0, Math.min(1, fromValue));
  const a1 = START_ANGLE + SWEEP * Math.max(0, Math.min(1, toValue));
  const start = polar(a0, radius);
  const end = polar(a1, radius);
  const largeArc = Math.abs(a1 - a0) > 180 ? 1 : 0;
  return `M ${start.x} ${start.y} A ${radius} ${radius} 0 ${largeArc} 1 ${end.x} ${end.y}`;
}

export default function ProbabilityGauge({
  shippedProbability,
  isotonicProbability,
  calibrationMode,
  threshold,
  thresholdReachable,
  useIsotonic,
  onToggleIsotonic,
  modelVersion,
}) {
  const gradientId = useId();
  const value = useIsotonic ? isotonicProbability : shippedProbability;
  const clampedThreshold = Math.max(0, Math.min(1, threshold));
  const clears = thresholdReachable && value >= threshold;

  const needleAngle = START_ANGLE + SWEEP * Math.max(0, Math.min(1, value));
  const needleTip = polar(needleAngle, RADIUS - STROKE - 6);
  const thresholdOuter = polar(clampedThreshold * 0 + START_ANGLE + SWEEP * clampedThreshold, RADIUS + STROKE / 2 + 5);
  const thresholdInner = polar(START_ANGLE + SWEEP * clampedThreshold, RADIUS - STROKE / 2 - 5);

  const delta = isotonicProbability - shippedProbability;

  return (
    <div className="flex flex-col items-center">
      <svg
        width={SIZE}
        height={SIZE - 34}
        viewBox={`0 0 ${SIZE} ${SIZE - 34}`}
        role="img"
        aria-label={`Win probability ${formatPercent(value)}, break-even threshold ${formatThreshold(threshold)}.`}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={clears ? '#62C6D7' : '#E58B84'} />
            <stop
              offset="100%"
              stopColor={clears ? '#8BD5DE' : '#F0B66E'}
              stopOpacity="0.75"
            />
          </linearGradient>
        </defs>

        {/* Track */}
        <path
          d={arcPath(0, 1)}
          fill="none"
          stroke="rgba(148,163,184,0.14)"
          strokeWidth={STROKE}
          strokeLinecap="round"
        />

        {/* Value arc. Animated on the path length rather than redrawn, so the
            transition is a smooth sweep instead of a series of jumps. */}
        <motion.path
          d={arcPath(0, 1)}
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth={STROKE}
          strokeLinecap="round"
          initial={false}
          animate={{ pathLength: Math.max(0.001, Math.min(1, value)) }}
          transition={{ duration: 0.65, ease: [0.22, 1, 0.36, 1] }}
        />

        {/* Threshold tick, on the same arc as the value. */}
        {thresholdReachable && (
          <g>
            <line
              x1={thresholdInner.x}
              y1={thresholdInner.y}
              x2={thresholdOuter.x}
              y2={thresholdOuter.y}
              stroke="#FFFFFF"
              strokeWidth="2.5"
              strokeLinecap="round"
              opacity="0.9"
            />
            <circle
              cx={thresholdOuter.x}
              cy={thresholdOuter.y}
              r="2.5"
              fill="#FFFFFF"
              opacity="0.9"
            />
          </g>
        )}

        {/* Needle */}
        <motion.line
          x1={CENTER}
          y1={CENTER}
          initial={false}
          animate={{ x2: needleTip.x, y2: needleTip.y }}
          transition={{ duration: 0.65, ease: [0.22, 1, 0.36, 1] }}
          stroke={clears ? '#62C6D7' : '#E58B84'}
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <circle
          cx={CENTER}
          cy={CENTER}
          r="6"
          fill="#0A0D14"
          stroke={clears ? '#62C6D7' : '#E58B84'}
          strokeWidth="2.5"
        />

        {/* Readout */}
        <text
          x={CENTER}
          y={CENTER + 46}
          textAnchor="middle"
          className="font-mono"
          fontSize="30"
          fontWeight="600"
          fill={clears ? '#62C6D7' : '#E58B84'}
          style={{ fontVariantNumeric: 'tabular-nums' }}
        >
          {formatPercent(value)}
        </text>
        <text
          x={CENTER}
          y={CENTER + 64}
          textAnchor="middle"
          className="font-mono"
          fontSize="9"
          fill="rgba(148,163,184,0.7)"
          letterSpacing="1.2"
        >
          {useIsotonic ? 'ISOTONIC (NOT SHIPPED)' : 'SHIPPED P(WIN)'}
        </text>
      </svg>

      {/* Threshold comparison, stated in words under the geometry. */}
      <div className="mt-1 flex items-center gap-2 text-xs">
        <span className="h-2 w-0.5 rounded-full bg-white/90" />
        <span className="text-slateink/70">
          break-even{' '}
          <span className="font-mono text-white tabular">
            {formatThreshold(threshold)}
          </span>
        </span>
      </div>

      {/* Calibration toggle */}
      <div className="mt-5 w-full">
        <div className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] p-3">
          <div className="min-w-0">
            <div className="text-sm font-500 text-white">
              Apply isotonic map
            </div>
            <div className="font-mono text-2xs text-slateink/60">
              {useIsotonic ? 'ON' : 'OFF'} · Δ{' '}
              {delta >= 0 ? '+' : ''}
              {(delta * 100).toFixed(1)} pts
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={useIsotonic}
            aria-label={
              useIsotonic
                ? 'Showing the isotonic map. Switch back to the shipped probability.'
                : 'Showing the shipped probability. Switch to the isotonic map.'
            }
            onClick={onToggleIsotonic}
            className={`tap-44 relative h-6 w-11 shrink-0 rounded-full transition-colors duration-300 ${
              useIsotonic ? 'bg-indigo' : 'bg-white/15'
            }`}
          >
            <motion.span
              layout
              transition={{ type: 'spring', stiffness: 500, damping: 34 }}
              className={`absolute top-1 h-4 w-4 rounded-full bg-white ${
                useIsotonic ? 'right-1' : 'left-1'
              }`}
            />
          </button>
        </div>

        <p className="mt-3 text-xs leading-relaxed text-slateink/65 text-pretty">
          <span className="text-white">Why this toggle matters.</span> The
          policy engine multiplies this number by rupees and compares it against
          an arithmetic threshold, so a miscalibrated score would corrupt every
          comparison while leaving ROC-AUC completely unchanged — AUC is
          rank-based and blind to monotone distortion.
          {calibrationMode === 'identity' ? (
            <>
              {' '}
              An isotonic map <em>was</em> fitted here, on out-of-fold
              predictions across the whole training split, and then
              <span className="text-white"> lost</span> a held-out comparison
              against the raw booster. LightGBM minimising logloss optimises a
              strictly proper scoring rule, so it is already calibrated and the
              correction only added variance. This toggle shows the
              counterfactual it would have produced.
            </>
          ) : (
            <>
              {' '}
              The isotonic map won its held-out comparison against the raw
              booster, and is what ships.
            </>
          )}
        </p>

        {modelVersion && (
          <p className="mt-2 font-mono text-2xs text-slateink/40">
            {modelVersion}
          </p>
        )}
      </div>
    </div>
  );
}
