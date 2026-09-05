/**
 * The ChargeGuard.AI brand mark: the decision frontier, reduced to a glyph.
 *
 * This is not a decorative logo. It is the literal shape of the arbitrage rule
 * `p* = λc / A` — a hyperbola — clipped to a square, with a short baseline and a
 * single dot sitting *above* the curve. The dot is a dispute in the CONTEST
 * region: the whole product, in one mark.
 *
 * Drawn as one emerald hairline path. Stroke width scales inversely with size so
 * the line stays a true hairline whether the mark is rendered at 20px in the nav
 * or 512px in the OG image — a fixed stroke would look spidery when large and
 * bloated when small.
 *
 * The hyperbola is sampled once at module scope, not per render: the curve never
 * changes, so recomputing it on every mount would be waste.
 */

const VIEW = 100;

// Sample y = k/x over the box. k and the clip window are chosen so the curve
// enters near the top-left, sweeps through the middle, and exits near the
// bottom-right, filling the square rather than hugging one corner.
const K = 1400;
const X_MIN = 18;
const X_MAX = 88;
const Y_FLOOR = 14; // keep the curve off the very bottom so the baseline reads
const SAMPLES = 40;

const FRONTIER_PATH = (() => {
  const pts = [];
  for (let i = 0; i <= SAMPLES; i += 1) {
    const x = X_MIN + ((X_MAX - X_MIN) * i) / SAMPLES;
    const y = Math.max(Y_FLOOR, VIEW - K / x); // invert: SVG y grows downward
    pts.push([x, y]);
  }
  return pts
    .map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`)
    .join(' ');
})();

// The dot: a dispute sitting in the CONTEST territory, comfortably above the
// curve at a mid-range amount.
const DOT = { x: 62, y: 30, r: 6.5 };

export default function Mark({ size = 24, className = '', title = 'ChargeGuard.AI' }) {
  // Hairline: ~1.6px at 24px, thinning proportionally as the mark grows.
  const stroke = (1.6 / 24) * size;

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${VIEW} ${VIEW}`}
      className={className}
      role="img"
      aria-label={title}
      fill="none"
    >
      {title ? <title>{title}</title> : null}

      {/* Baseline — a short axis tick so the curve reads as a plotted frontier
          rather than a stray stroke. */}
      <line
        x1={X_MIN - 4}
        y1={VIEW - Y_FLOOR + 2}
        x2={X_MAX * 0.62}
        y2={VIEW - Y_FLOOR + 2}
        stroke="currentColor"
        strokeOpacity="0.35"
        strokeWidth={stroke * 0.8}
        strokeLinecap="round"
      />

      {/* The frontier itself — the brightest element, the curve p* = λc / A. */}
      <path
        d={FRONTIER_PATH}
        stroke="#62C6D7"
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* The dispute above the frontier: a filled emerald dot in CONTEST space. */}
      <circle cx={DOT.x} cy={DOT.y} r={DOT.r} fill="#62C6D7" />
    </svg>
  );
}

/**
 * The mark used as a between-section divider: the glyph centred on a hairline
 * rule that fades out to either side. Same geometry, horizontal context.
 */
export function MarkDivider({ className = '' }) {
  return (
    <div
      className={`flex items-center justify-center gap-4 py-2 ${className}`}
      aria-hidden="true"
    >
      <span className="h-px w-16 bg-gradient-to-r from-transparent to-white/12" />
      <Mark size={18} title="" className="opacity-80" />
      <span className="h-px w-16 bg-gradient-to-l from-transparent to-white/12" />
    </div>
  );
}
