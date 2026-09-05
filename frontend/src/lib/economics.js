/**
 * The arbitrage arithmetic, client side.
 *
 * MIRROR: `backend/src/sentinel/policy/economics.py` is the authority. This file
 * reimplements the same formulas so the arbitrage visualiser can respond to a
 * slider at 60fps without a round trip, and so the simulator still works when
 * deployed statically with no API reachable.
 *
 * Any change to the Python must be made here, and vice versa. The two are
 * checked against each other by the simulator itself: when the API is
 * reachable it renders the server's decision, and the same inputs run through
 * these functions must agree.
 *
 * ---------------------------------------------------------------------------
 * The rule
 * ---------------------------------------------------------------------------
 *
 *   EV_i    = p_i * A_i - c
 *   contest <=> p_i >= lambda * c / A_i  =:  p*_i
 *
 * The threshold is per dispute, not global. That is the whole idea.
 *
 * ---------------------------------------------------------------------------
 * The asymmetry
 * ---------------------------------------------------------------------------
 *
 *   FP (contested and lost)    = c          -- flat in the amount
 *   FN (accepted but winnable) = A_i - c    -- linear in the amount
 *
 * So FN > FP whenever A_i > 2c, which on the evaluation corpus is 87% of
 * disputes. A false negative is not a slightly worse false positive; at the
 * top of the amount distribution it is two orders of magnitude worse.
 */

/** Default representment cost `c`, in INR. Mirrors `Settings.representment_cost_inr`. */
export const DEFAULT_COST_INR = 350;

/** Default risk margin `lambda`. Mirrors `Settings.risk_margin`. */
export const DEFAULT_RISK_MARGIN = 1.2;

/** Slider bounds for the arbitrage visualiser. */
export const AMOUNT_MIN = 100;
export const AMOUNT_MAX = 100000;
export const COST_MIN = 100;
export const COST_MAX = 2000;
export const MARGIN_MIN = 1.0;
export const MARGIN_MAX = 2.0;

/**
 * Per-dispute break-even win probability, `p* = lambda * c / A`.
 *
 * Deliberately **not clamped to 1**. A value above 1 means the threshold is
 * unreachable -- no probability, not even certainty, repays the filing cost --
 * and that is a materially different statement from "requires certainty".
 * Clamping would erase the distinction the UI needs to show.
 *
 * @param {number} amountInr Disputed amount `A_i`, must be positive.
 * @param {number} costInr Representment cost `c`, must be positive.
 * @param {number} riskMargin Risk margin `lambda`, at least 1.
 * @returns {number} The threshold. May exceed 1.
 */
export function decisionThreshold(amountInr, costInr, riskMargin) {
  if (!(amountInr > 0)) throw new Error(`amountInr must be positive, got ${amountInr}`);
  if (!(costInr > 0)) throw new Error(`costInr must be positive, got ${costInr}`);
  if (!(riskMargin >= 1)) throw new Error(`riskMargin must be >= 1, got ${riskMargin}`);
  return (riskMargin * costInr) / amountInr;
}

/**
 * True when some probability in [0, 1] could clear the threshold.
 * @param {number} threshold
 * @returns {boolean}
 */
export function isThresholdReachable(threshold) {
  return threshold <= 1;
}

/**
 * Expected value of contesting, `EV = p * A - c`, in INR.
 *
 * This is the difference between contesting and accepting. Accepting has zero
 * incremental cash flow -- the amount is already debited -- so the two
 * coincide.
 *
 * @param {number} pWin Calibrated win probability in [0, 1].
 * @param {number} amountInr
 * @param {number} costInr
 * @returns {number} Expected value in INR; negative quantifies loss avoided.
 */
export function expectedValue(pWin, amountInr, costInr) {
  if (!(pWin >= 0 && pWin <= 1)) throw new Error(`pWin must be in [0,1], got ${pWin}`);
  return pWin * amountInr - costInr;
}

/**
 * Cost of contesting a dispute we go on to lose. Flat in the amount.
 * @param {number} costInr
 * @returns {number}
 */
export function falsePositiveCost(costInr) {
  return costInr;
}

/**
 * Opportunity cost of accepting a dispute we would have won. Linear in the amount.
 *
 * Floors at zero rather than going negative: below the filing cost there was no
 * profitable recovery to forgo, so nothing was lost.
 *
 * @param {number} amountInr
 * @param {number} costInr
 * @returns {number}
 */
export function falseNegativeCost(amountInr, costInr) {
  return Math.max(0, amountInr - costInr);
}

/**
 * `FN / FP` -- how many times worse a missed win is than a lost fight.
 * Returns 0 when the false-negative cost is zero, where the ratio is undefined.
 * @param {number} amountInr
 * @param {number} costInr
 * @returns {number}
 */
export function costAsymmetryRatio(amountInr, costInr) {
  const fn = falseNegativeCost(amountInr, costInr);
  if (fn === 0) return 0;
  return fn / falsePositiveCost(costInr);
}

/**
 * Smallest amount for which the threshold is reachable at all, `A_min = lambda * c`.
 * @param {number} costInr
 * @param {number} riskMargin
 * @returns {number}
 */
export function breakevenAmount(costInr, riskMargin) {
  return riskMargin * costInr;
}

/**
 * The amount at which a missed win and a lost fight cost the same, `A = 2c`.
 * Annotated on the asymmetry chart as the crossover.
 * @param {number} costInr
 * @returns {number}
 */
export function asymmetryCrossover(costInr) {
  return 2 * costInr;
}

/**
 * Sample `(amount, threshold)` pairs on a logarithmic amount axis.
 *
 * Log spacing is what makes the hyperbolic decay legible; on a linear axis the
 * interesting part of the curve is compressed into the first few pixels.
 * Thresholds are clamped to 1 **for plotting only** -- the rule itself is not.
 *
 * @param {number} costInr
 * @param {number} riskMargin
 * @param {number} [points=64]
 * @returns {{amount: number, threshold: number, unreachable: boolean}[]}
 */
export function thresholdCurve(costInr, riskMargin, points = 64) {
  const logMin = Math.log(AMOUNT_MIN);
  const logMax = Math.log(AMOUNT_MAX);
  const step = (logMax - logMin) / (points - 1);

  const out = [];
  for (let i = 0; i < points; i += 1) {
    const amount = Math.exp(logMin + i * step);
    const raw = decisionThreshold(amount, costInr, riskMargin);
    out.push({
      amount,
      threshold: Math.min(raw, 1),
      unreachable: raw > 1,
    });
  }
  return out;
}

/**
 * Sample the two error-cost curves against amount, for the asymmetry chart.
 *
 * The whole point of plotting them together is that one is a horizontal line
 * and the other is a ray from the origin: the visual gap *is* the argument.
 *
 * @param {number} costInr
 * @param {number} [points=64]
 * @returns {{amount: number, fpCost: number, fnCost: number, ratio: number}[]}
 */
export function asymmetryCurve(costInr, points = 64) {
  const logMin = Math.log(AMOUNT_MIN);
  const logMax = Math.log(AMOUNT_MAX);
  const step = (logMax - logMin) / (points - 1);

  const out = [];
  for (let i = 0; i < points; i += 1) {
    const amount = Math.exp(logMin + i * step);
    out.push({
      amount,
      fpCost: falsePositiveCost(costInr),
      fnCost: falseNegativeCost(amount, costInr),
      ratio: costAsymmetryRatio(amount, costInr),
    });
  }
  return out;
}

/**
 * Apply the expected-value rule. Economics only -- gates are not consulted.
 *
 * Mirrors `engine._apply_ev_rule`. The client-side simulator fallback layers
 * the gates on top of this separately, exactly as the engine does, so that the
 * two-stage structure of the real decision stays visible rather than being
 * collapsed into one predicate.
 *
 * @param {number} pWin
 * @param {number} amountInr
 * @param {number} costInr
 * @param {number} riskMargin
 * @returns {{action: 'CONTEST'|'ACCEPT', threshold: number, reachable: boolean,
 *            expectedValue: number, margin: number}}
 */
export function applyEvRule(pWin, amountInr, costInr, riskMargin) {
  const threshold = decisionThreshold(amountInr, costInr, riskMargin);
  const reachable = isThresholdReachable(threshold);
  const ev = expectedValue(pWin, amountInr, costInr);

  return {
    action: reachable && pWin >= threshold ? 'CONTEST' : 'ACCEPT',
    threshold,
    reachable,
    expectedValue: ev,
    margin: pWin - threshold,
  };
}

/* -------------------------------------------------------------------------- */
/* Formatting                                                                 */
/* -------------------------------------------------------------------------- */

const INR = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
});

const INR_PRECISE = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/**
 * Format rupees using the Indian digit grouping (lakh/crore), not thousands.
 * @param {number} value
 * @param {boolean} [precise=false] Include paise.
 * @returns {string}
 */
export function formatInr(value, precise = false) {
  if (!Number.isFinite(value)) return '—';
  return precise ? INR_PRECISE.format(value) : INR.format(value);
}

/**
 * Compact rupee formatting for axis ticks: 1.2L, 45k.
 * @param {number} value
 * @returns {string}
 */
export function formatInrCompact(value) {
  if (!Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 10000000) return `₹${(value / 10000000).toFixed(1)}Cr`;
  if (abs >= 100000) return `₹${(value / 100000).toFixed(1)}L`;
  if (abs >= 1000) return `₹${(value / 1000).toFixed(0)}k`;
  return `₹${Math.round(value)}`;
}

/**
 * Format a probability as a percentage.
 * @param {number} value
 * @param {number} [digits=1]
 * @returns {string}
 */
export function formatPercent(value, digits = 1) {
  if (!Number.isFinite(value)) return '—';
  return `${(value * 100).toFixed(digits)}%`;
}

/**
 * Format a threshold, distinguishing the unreachable case explicitly.
 * @param {number} threshold
 * @returns {string}
 */
export function formatThreshold(threshold) {
  if (!Number.isFinite(threshold)) return '—';
  if (threshold > 1) return '>100% — unreachable';
  return `${(threshold * 100).toFixed(1)}%`;
}
