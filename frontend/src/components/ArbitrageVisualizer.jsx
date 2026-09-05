import { useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { SectionHeading } from './ui/GlassCard.jsx';
import {
  AMOUNT_MAX,
  AMOUNT_MIN,
  COST_MAX,
  COST_MIN,
  DEFAULT_COST_INR,
  DEFAULT_RISK_MARGIN,
  MARGIN_MAX,
  MARGIN_MIN,
  asymmetryCrossover,
  asymmetryCurve,
  breakevenAmount,
  costAsymmetryRatio,
  decisionThreshold,
  formatInr,
  formatInrCompact,
  isThresholdReachable,
  thresholdCurve,
} from '../lib/economics.js';

/**
 * The interactive statement of the core idea.
 *
 * Three sliders, two charts. The first chart shows p* decaying hyperbolically
 * as the stake rises — that curve *is* the thesis, and it is why a global
 * confidence cutoff is economically illiterate. The second shows why the
 * asymmetry runs the direction it does: one flat line, one ray, and a labelled
 * crossover at A = 2c.
 *
 * All maths comes from `lib/economics.js`, which mirrors
 * `backend/src/sentinel/policy/economics.py`. Nothing is computed inline here.
 *
 * The amount slider is logarithmic. On a linear scale from ₹100 to ₹100,000 the
 * entire interesting region — everything under ₹5,000, which is most of a real
 * portfolio — occupies the first 5% of travel and is unusable.
 */

const AMOUNT_LOG_MIN = Math.log(AMOUNT_MIN);
const AMOUNT_LOG_MAX = Math.log(AMOUNT_MAX);

function sliderToAmount(position) {
  return Math.exp(AMOUNT_LOG_MIN + position * (AMOUNT_LOG_MAX - AMOUNT_LOG_MIN));
}

function amountToSlider(amount) {
  return (Math.log(amount) - AMOUNT_LOG_MIN) / (AMOUNT_LOG_MAX - AMOUNT_LOG_MIN);
}

const AXIS = {
  stroke: 'rgba(148,163,184,0.28)',
  tick: { fill: 'rgba(148,163,184,0.65)', fontSize: 10, fontFamily: 'JetBrains Mono' },
};

const TOOLTIP_STYLE = {
  background: 'rgba(17,23,37,0.96)',
  border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: '10px',
  fontSize: '11px',
  fontFamily: 'JetBrains Mono',
  padding: '8px 10px',
};

function Slider({ label, value, display, min, max, step, onChange, hint }) {
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <label className="eyebrow" htmlFor={`slider-${label}`}>
          {label}
        </label>
        <span className="font-mono text-sm text-white tabular">{display}</span>
      </div>
      <input
        id={`slider-${label}`}
        type="range"
        className="slider"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      {hint && <p className="mt-1.5 text-2xs text-slateink/50">{hint}</p>}
    </div>
  );
}

export default function ArbitrageVisualizer() {
  const [amountPosition, setAmountPosition] = useState(
    amountToSlider(2400),
  );
  const [cost, setCost] = useState(DEFAULT_COST_INR);
  const [margin, setMargin] = useState(DEFAULT_RISK_MARGIN);

  const amount = useMemo(() => sliderToAmount(amountPosition), [amountPosition]);

  const threshold = useMemo(
    () => decisionThreshold(amount, cost, margin),
    [amount, cost, margin],
  );
  const reachable = isThresholdReachable(threshold);

  const curve = useMemo(
    () => thresholdCurve(cost, margin, 72),
    [cost, margin],
  );
  const asymCurve = useMemo(() => asymmetryCurve(cost, 72), [cost]);

  const crossover = asymmetryCrossover(cost);
  const breakeven = breakevenAmount(cost, margin);
  const ratio = costAsymmetryRatio(amount, cost);

  return (
    <section id="math" className="relative py-24 sm:py-32">
      <div className="mx-auto max-w-content px-5 sm:px-8">
        <SectionHeading
          eyebrow="The arbitrage"
          title="The decision threshold is per dispute. Move the sliders and watch it move."
          lead="A ₹450 dispute needs near-certainty to be worth contesting. A ₹40,000 dispute is worth contesting on a long shot. Any system that applies one confidence cutoff across a portfolio is answering a question nobody asked."
        />

        <div className="mt-10 grid gap-5 sm:mt-12 lg:grid-cols-[300px_1fr]">
          {/* Controls and the live formula */}
          <div className="flex flex-col gap-5">
            <div className="glass p-5">
              <div className="space-y-6">
                <Slider
                  label="Aᵢ — disputed amount"
                  value={amountPosition}
                  display={formatInr(amount)}
                  min={0}
                  max={1}
                  step={0.001}
                  onChange={setAmountPosition}
                  hint="Logarithmic. ₹100 → ₹100,000."
                />
                <Slider
                  label="c — representment cost"
                  value={cost}
                  display={formatInr(cost)}
                  min={COST_MIN}
                  max={COST_MAX}
                  step={10}
                  onChange={setCost}
                  hint="Scheme fee + acquirer handling + analyst time."
                />
                <Slider
                  label="λ — risk margin"
                  value={margin}
                  display={margin.toFixed(2)}
                  min={MARGIN_MIN}
                  max={MARGIN_MAX}
                  step={0.05}
                  onChange={setMargin}
                  hint="1.00 is pure break-even. Absorbs calibration error."
                />
              </div>
            </div>

            {/* The formula with the current values substituted. */}
            <div className="glass p-5" aria-live="polite">
              <div className="eyebrow mb-3">Break-even probability</div>
              <div className="font-mono text-sm leading-relaxed text-slateink">
                <div>
                  p* = λ·c / A<sub>i</sub>
                </div>
                <div className="mt-1.5 text-slateink/60">
                  = {margin.toFixed(2)} × {Math.round(cost)} /{' '}
                  {Math.round(amount).toLocaleString('en-IN')}
                </div>
              </div>

              <div className="mt-4 flex items-baseline gap-2">
                <span
                  className={`font-mono text-4xl font-600 tabular ${
                    reachable ? 'text-emerald' : 'text-coral'
                  }`}
                >
                  {reachable ? `${(threshold * 100).toFixed(1)}%` : '>100%'}
                </span>
              </div>

              {reachable ? (
                <p className="mt-3 text-xs leading-relaxed text-slateink/70">
                  The model must be at least{' '}
                  <span className="text-white">
                    {(threshold * 100).toFixed(1)}%
                  </span>{' '}
                  confident before contesting this dispute pays for itself.
                </p>
              ) : (
                <p className="mt-3 text-xs leading-relaxed text-coral/80">
                  Unreachable. Below {formatInr(breakeven)} no probability — not
                  even certainty — repays the filing cost. ACCEPT is forced by
                  arithmetic, not by evidence.
                </p>
              )}
            </div>

            <div className="glass p-5">
              <div className="eyebrow mb-3">At this amount</div>
              <dl className="space-y-2.5 text-sm">
                <div className="flex justify-between gap-3">
                  <dt className="text-slateink/60">Lost fight costs</dt>
                  <dd className="font-mono text-white tabular">
                    {formatInr(cost)}
                  </dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-slateink/60">Missed win costs</dt>
                  <dd className="font-mono text-coral tabular">
                    {formatInr(Math.max(0, amount - cost))}
                  </dd>
                </div>
                <div className="flex justify-between gap-3 border-t border-white/10 pt-2.5">
                  <dt className="text-slateink/60">Ratio</dt>
                  <dd className="font-mono text-white tabular">
                    {ratio > 0 ? `${ratio.toFixed(1)}×` : '—'}
                  </dd>
                </div>
              </dl>
            </div>
          </div>

          {/* Charts */}
          <div className="flex flex-col gap-5">
            {/* Threshold decay */}
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-80px' }}
              transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
              className="glass p-5"
            >
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-display text-base font-600 text-white">
                  Required confidence collapses as the stake rises
                </h3>
                <span className="font-mono text-2xs text-slateink/50">
                  p* vs Aᵢ · log axis
                </span>
              </div>
              <p className="mb-4 text-xs leading-relaxed text-slateink/60">
                Hyperbolic decay. The marker is your current position.
              </p>

              <div className="h-[220px] w-full sm:h-[240px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={curve}
                    margin={{ top: 8, right: 12, bottom: 4, left: -8 }}
                  >
                    <CartesianGrid
                      strokeDasharray="2 4"
                      stroke="rgba(148,163,184,0.10)"
                      vertical={false}
                    />
                    <XAxis
                      dataKey="amount"
                      scale="log"
                      domain={[AMOUNT_MIN, AMOUNT_MAX]}
                      type="number"
                      ticks={[100, 500, 2400, 10000, 40000, 100000]}
                      tickFormatter={formatInrCompact}
                      stroke={AXIS.stroke}
                      tick={AXIS.tick}
                    />
                    <YAxis
                      domain={[0, 1]}
                      ticks={[0, 0.25, 0.5, 0.75, 1]}
                      tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
                      stroke={AXIS.stroke}
                      tick={AXIS.tick}
                    />
                    <Tooltip
                      contentStyle={TOOLTIP_STYLE}
                      labelFormatter={(v) => `Amount ${formatInr(v)}`}
                      formatter={(v) => [
                        `${(v * 100).toFixed(1)}%`,
                        'break-even p*',
                      ]}
                    />
                    <ReferenceLine
                      x={breakeven}
                      stroke="rgba(249,115,98,0.5)"
                      strokeDasharray="3 3"
                      label={{
                        value: 'λc',
                        position: 'top',
                        fill: 'rgba(249,115,98,0.8)',
                        fontSize: 9,
                        fontFamily: 'JetBrains Mono',
                      }}
                    />
                    <Line
                      type="monotone"
                      dataKey="threshold"
                      stroke="#62C6D7"
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                    />
                    <ReferenceDot
                      x={amount}
                      y={Math.min(threshold, 1)}
                      r={5}
                      fill={reachable ? '#62C6D7' : '#E58B84'}
                      stroke="#0A0D14"
                      strokeWidth={2}
                      isFront
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </motion.div>

            {/* Asymmetry */}
            <motion.div
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-80px' }}
              transition={{ duration: 0.5, delay: 0.08, ease: [0.22, 1, 0.36, 1] }}
              className="glass p-5"
            >
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-display text-base font-600 text-white">
                  One error is flat. The other is not.
                </h3>
                <span className="font-mono text-2xs text-slateink/50">
                  cost of being wrong vs Aᵢ
                </span>
              </div>
              <p className="mb-4 text-xs leading-relaxed text-slateink/60">
                The gap between the two lines is the entire argument for
                aggressive recall.
              </p>

              <div className="h-[220px] w-full sm:h-[240px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={asymCurve}
                    margin={{ top: 8, right: 12, bottom: 4, left: 4 }}
                  >
                    <CartesianGrid
                      strokeDasharray="2 4"
                      stroke="rgba(148,163,184,0.10)"
                      vertical={false}
                    />
                    <XAxis
                      dataKey="amount"
                      scale="log"
                      domain={[AMOUNT_MIN, AMOUNT_MAX]}
                      type="number"
                      ticks={[100, 500, 2400, 10000, 40000, 100000]}
                      tickFormatter={formatInrCompact}
                      stroke={AXIS.stroke}
                      tick={AXIS.tick}
                    />
                    <YAxis
                      tickFormatter={formatInrCompact}
                      stroke={AXIS.stroke}
                      tick={AXIS.tick}
                      width={52}
                    />
                    <Tooltip
                      contentStyle={TOOLTIP_STYLE}
                      labelFormatter={(v) => `Amount ${formatInr(v)}`}
                      formatter={(v, name) => [
                        formatInr(v),
                        name === 'fpCost'
                          ? 'FP — contested and lost'
                          : 'FN — accepted but winnable',
                      ]}
                    />
                    <ReferenceLine
                      x={crossover}
                      stroke="rgba(255,255,255,0.28)"
                      strokeDasharray="3 3"
                      label={{
                        value: 'A = 2c',
                        position: 'insideTopLeft',
                        fill: 'rgba(255,255,255,0.6)',
                        fontSize: 9,
                        fontFamily: 'JetBrains Mono',
                      }}
                    />
                    <Line
                      type="monotone"
                      dataKey="fpCost"
                      stroke="#AEBFC7"
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="fnCost"
                      stroke="#E58B84"
                      strokeWidth={2}
                      dot={false}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-white/10 pt-3.5">
                <span className="flex items-center gap-2 text-xs text-slateink/70">
                  <span className="h-0.5 w-4 rounded-full bg-slateink" />
                  False positive — flat at {formatInr(cost)}
                </span>
                <span className="flex items-center gap-2 text-xs text-slateink/70">
                  <span className="h-0.5 w-4 rounded-full bg-coral" />
                  False negative — linear, Aᵢ − c
                </span>
                <span className="ml-auto font-mono text-2xs text-slateink/50">
                  crossover at {formatInr(crossover)}
                </span>
              </div>
            </motion.div>
          </div>
        </div>

        <p className="mx-auto mt-8 max-w-3xl text-center text-sm leading-relaxed text-slateink/60 text-pretty">
          These formulas are implemented twice, deliberately:{' '}
          <code className="font-mono text-2xs text-slateink/80">
            backend/src/sentinel/policy/economics.py
          </code>{' '}
          is the authority and{' '}
          <code className="font-mono text-2xs text-slateink/80">
            frontend/src/lib/economics.js
          </code>{' '}
          mirrors it so this page responds to a slider without a round trip. Each
          file points at the other.
        </p>
      </div>
    </section>
  );
}
