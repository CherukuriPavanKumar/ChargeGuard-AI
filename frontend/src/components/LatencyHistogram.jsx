import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

/**
 * Latency distribution for the synchronous scoring path.
 *
 * Plots the real histogram emitted by the harness, not a shape reconstructed
 * from percentiles — p50, p95 and p99 are consistent with infinitely many
 * distributions, and the part of a latency profile worth looking at is the
 * right tail, which those three numbers describe least well.
 *
 * The SLA line is drawn only when it falls inside the observed range. Forcing
 * the x-axis out to 200ms when every sample sits under 15ms would produce a
 * chart that is 93% empty space and communicates nothing except that the axis
 * was chosen to flatter. The headroom factor is stated numerically instead.
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

function Marker({ label, value, tone }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="eyebrow">{label}</span>
      <span className={`font-mono text-base tabular ${tone}`}>
        {typeof value === 'number' ? `${value.toFixed(2)} ms` : '—'}
      </span>
    </div>
  );
}

export default function LatencyHistogram({ latency, slaMs = 200 }) {
  const histogram = latency?.histogram ?? [];
  const hasData = histogram.length > 0 && (latency?.n ?? 0) > 0;

  if (!hasData) {
    return (
      <div className="glass flex h-full min-h-[320px] flex-col items-center justify-center p-6 text-center">
        <div className="eyebrow mb-2">Scoring latency</div>
        <p className="max-w-xs text-sm text-slateink/55">
          No latency samples. Run{' '}
          <code className="font-mono text-emerald">make all</code> to benchmark
          the scoring path.
        </p>
      </div>
    );
  }

  const p50 = latency.p50;
  const p95 = latency.p95;
  const p99 = latency.p99;
  const maxObserved = latency.max ?? histogram[histogram.length - 1].bin_end;
  const slaInRange = slaMs <= maxObserved * 1.05;
  const headroom = p95 > 0 ? slaMs / p95 : 0;

  return (
    <div className="glass p-5">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-display text-base font-600 text-white">
          Scoring latency distribution
        </h3>
        <span className="font-mono text-2xs text-slateink/50">
          {latency.n.toLocaleString('en-IN')} calls
        </span>
      </div>
      <p className="mb-4 text-xs leading-relaxed text-slateink/60">
        Feature construction, tree traversal, calibration, six gates, Decision
        construction. No network on this path.
      </p>

      <div className="h-[200px] w-full sm:h-[220px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={histogram}
            margin={{ top: 8, right: 12, bottom: 4, left: -14 }}
            barCategoryGap={1}
          >
            <CartesianGrid
              strokeDasharray="2 4"
              stroke="rgba(148,163,184,0.10)"
              vertical={false}
            />
            <XAxis
              dataKey="bin_mid"
              type="number"
              domain={['dataMin', 'dataMax']}
              tickFormatter={(v) => `${v.toFixed(1)}`}
              stroke={AXIS.stroke}
              tick={AXIS.tick}
              label={{
                value: 'milliseconds',
                position: 'insideBottom',
                offset: -2,
                fill: 'rgba(148,163,184,0.5)',
                fontSize: 9,
                fontFamily: 'JetBrains Mono',
              }}
            />
            <YAxis stroke={AXIS.stroke} tick={AXIS.tick} width={44} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              cursor={{ fill: 'rgba(255,255,255,0.04)' }}
              labelFormatter={(v) => `${Number(v).toFixed(2)} ms`}
              formatter={(v) => [v.toLocaleString('en-IN'), 'calls']}
            />

            <ReferenceLine
              x={p50}
              stroke="rgba(148,163,184,0.65)"
              strokeDasharray="3 3"
              label={{
                value: 'p50',
                position: 'top',
                fill: 'rgba(148,163,184,0.8)',
                fontSize: 9,
                fontFamily: 'JetBrains Mono',
              }}
            />
            <ReferenceLine
              x={p95}
              stroke="#62C6D7"
              strokeDasharray="3 3"
              label={{
                value: 'p95',
                position: 'top',
                fill: '#62C6D7',
                fontSize: 9,
                fontFamily: 'JetBrains Mono',
              }}
            />
            <ReferenceLine
              x={p99}
              stroke="#F0B66E"
              strokeDasharray="3 3"
              label={{
                value: 'p99',
                position: 'top',
                fill: '#F0B66E',
                fontSize: 9,
                fontFamily: 'JetBrains Mono',
              }}
            />
            {slaInRange && (
              <ReferenceLine
                x={slaMs}
                stroke="#E58B84"
                strokeWidth={1.5}
                label={{
                  value: `SLA ${slaMs}ms`,
                  position: 'top',
                  fill: '#E58B84',
                  fontSize: 9,
                  fontFamily: 'JetBrains Mono',
                }}
              />
            )}

            <Bar dataKey="count" radius={[2, 2, 0, 0]} isAnimationActive={false}>
              {histogram.map((bin, index) => (
                <Cell
                  key={index}
                  fill={
                    bin.bin_mid > p99
                      ? 'rgba(99,102,241,0.55)'
                      : bin.bin_mid > p95
                        ? 'rgba(16,185,129,0.45)'
                        : 'rgba(16,185,129,0.72)'
                  }
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-4 grid grid-cols-4 gap-3 border-t border-white/10 pt-4">
        <Marker label="p50" value={p50} tone="text-slateink" />
        <Marker label="p95" value={p95} tone="text-emerald" />
        <Marker label="p99" value={p99} tone="text-indigo" />
        <Marker label="SLA" value={slaMs} tone="text-coral" />
      </div>

      <p className="mt-3.5 text-[11px] leading-relaxed text-slateink/55 text-pretty">
        {slaInRange ? (
          <>The 200 ms budget is drawn on the axis above.</>
        ) : (
          <>
            The <span className="text-coral">200 ms</span> SLA line is off this
            chart to the right — every sample sits far below it, and stretching
            the axis to reach it would produce a mostly-empty plot. Headroom at
            p95 is{' '}
            <span className="font-mono text-emerald">
              {headroom >= 1000
                ? `${Math.round(headroom).toLocaleString('en-IN')}×`
                : `${headroom.toFixed(0)}×`}
            </span>
            .
          </>
        )}{' '}
        That headroom is architectural, not the result of micro-optimisation:
        the LLM and the PDF renderer live behind a background job, so nothing on
        this path makes a network call.
      </p>
    </div>
  );
}
