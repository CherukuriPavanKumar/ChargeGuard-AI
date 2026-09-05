import {
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts';

import { formatPercent } from '../lib/economics.js';

/**
 * Reliability diagram: predicted confidence against observed frequency.
 *
 * Read it against the diagonal. A point above the line means the model was
 * under-confident in that bin — it said 30% and won 40% of the time. Below
 * means over-confident. For a system that multiplies this number by rupees,
 * distance from the diagonal is distance from correct expected values.
 *
 * Points are sized by bin population, which matters: a bin holding eleven
 * disputes sitting far off the diagonal is noise, and drawing it the same size
 * as a bin holding nine hundred would invite the reader to over-read it.
 *
 * Every value is read from `metrics.json`. If the harness has not run, the
 * chart renders an empty state rather than a plausible-looking curve.
 */

const AXIS = {
  stroke: 'rgba(148,163,184,0.28)',
  tick: {
    fill: 'rgba(148,163,184,0.65)',
    fontSize: 10,
    fontFamily: 'JetBrains Mono',
  },
};

const TOOLTIP_STYLE = {
  background: 'rgba(17,23,37,0.96)',
  border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: '10px',
  fontSize: '11px',
  fontFamily: 'JetBrains Mono',
  padding: '8px 10px',
};

/** Highlight whichever column the held-out selection actually shipped. */
function rawTone(effect, column) {
  const selected = effect?.mode === column;
  return `py-1.5 text-right font-mono tabular ${
    selected ? 'text-emerald' : 'text-slateink/60'
  }`;
}

export default function CalibrationCurve({ points, brier, ece, effect }) {
  const hasData = Array.isArray(points) && points.length > 0;

  if (!hasData) {
    return (
      <div className="glass flex h-full min-h-[320px] flex-col items-center justify-center p-6 text-center">
        <div className="eyebrow mb-2">Reliability diagram</div>
        <p className="max-w-xs text-sm text-slateink/55">
          No calibration data. Run{' '}
          <code className="font-mono text-emerald">make all</code> to generate
          the held-out evaluation.
        </p>
      </div>
    );
  }

  const maxCount = Math.max(...points.map((p) => p.count));

  return (
    <div className="glass p-5">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-display text-base font-600 text-white">
          Is a 30% prediction actually a 30% win rate?
        </h3>
        <span className="font-mono text-2xs text-slateink/50">
          10 bins · held-out
        </span>
      </div>
      <p className="mb-4 text-xs leading-relaxed text-slateink/60">
        Points on the diagonal are perfectly calibrated. Size is bin population.
      </p>

      <div className="h-[220px] w-full sm:h-[260px]">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 14, bottom: 4, left: -10 }}>
            <CartesianGrid
              strokeDasharray="2 4"
              stroke="rgba(148,163,184,0.10)"
            />
            <XAxis
              type="number"
              dataKey="predicted"
              name="predicted"
              domain={[0, 1]}
              ticks={[0, 0.25, 0.5, 0.75, 1]}
              tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
              stroke={AXIS.stroke}
              tick={AXIS.tick}
              label={{
                value: 'predicted',
                position: 'insideBottom',
                offset: -2,
                fill: 'rgba(148,163,184,0.5)',
                fontSize: 9,
                fontFamily: 'JetBrains Mono',
              }}
            />
            <YAxis
              type="number"
              dataKey="observed"
              name="observed"
              domain={[0, 1]}
              ticks={[0, 0.25, 0.5, 0.75, 1]}
              tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
              stroke={AXIS.stroke}
              tick={AXIS.tick}
            />
            <ZAxis
              type="number"
              dataKey="count"
              range={[40, 340]}
              domain={[0, maxCount]}
            />

            {/* Perfect-calibration reference. Drawn as two reference lines
                rather than a Line series so it never appears in the tooltip. */}
            <ReferenceLine
              segment={[
                { x: 0, y: 0 },
                { x: 1, y: 1 },
              ]}
              stroke="rgba(255,255,255,0.28)"
              strokeDasharray="4 4"
            />

            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              cursor={{ strokeDasharray: '3 3', stroke: 'rgba(255,255,255,0.2)' }}
              formatter={(value, name) =>
                name === 'count'
                  ? [value.toLocaleString('en-IN'), 'disputes in bin']
                  : [formatPercent(value), name]
              }
            />
            <Scatter
              data={points}
              fill="rgba(16,185,129,0.55)"
              stroke="#62C6D7"
              strokeWidth={1.5}
              isAnimationActive={false}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      {/* The selection, shown as a comparison rather than as a claimed gain.
          Both candidates are scored on the test set, so the choice made on the
          held-out fold can be checked rather than taken on trust. */}
      <div className="mt-4 border-t border-white/10 pt-4">
        <div className="mb-2.5 flex items-baseline justify-between gap-2">
          <span className="eyebrow">Calibrator selection</span>
          <span className="rounded bg-emerald-dim px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider text-emerald">
            shipped: {effect?.mode ?? '—'}
          </span>
        </div>

        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-white/10">
              <th className="pb-1.5 text-left font-mono text-[9px] font-400 uppercase tracking-wider text-slateink/50" />
              <th className="pb-1.5 text-right font-mono text-[9px] font-400 uppercase tracking-wider text-slateink/50">
                raw booster
              </th>
              <th className="pb-1.5 text-right font-mono text-[9px] font-400 uppercase tracking-wider text-slateink/50">
                isotonic
              </th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-white/[0.05]">
              <td className="py-1.5 text-slateink/60">Brier</td>
              <td className={rawTone(effect, 'identity')}>
                {effect?.brier_raw?.toFixed(4) ?? '—'}
              </td>
              <td className={rawTone(effect, 'isotonic')}>
                {effect?.brier_isotonic?.toFixed(4) ?? '—'}
              </td>
            </tr>
            <tr>
              <td className="py-1.5 text-slateink/60">ECE</td>
              <td className={rawTone(effect, 'identity')}>
                {effect?.ece_raw?.toFixed(4) ?? '—'}
              </td>
              <td className={rawTone(effect, 'isotonic')}>
                {effect?.ece_isotonic?.toFixed(4) ?? '—'}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p className="mt-3.5 text-[11px] leading-relaxed text-slateink/55 text-pretty">
        <span className="text-white">Calibration is selected, not assumed.</span>{' '}
        Isotonic is fitted on{' '}
        {(effect?.selection?.n_calibration_rows ?? 0).toLocaleString('en-IN')}{' '}
        out-of-fold predictions, then measured against the raw booster on a fold
        neither had seen. LightGBM minimising logloss optimises a strictly proper
        scoring rule, so it is often already calibrated and the correction can
        only add variance — which is what happened here. ROC-AUC is identical
        under both options and would have hidden the difference entirely.
      </p>
    </div>
  );
}
