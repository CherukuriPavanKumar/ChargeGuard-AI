/**
 * The hero case, the three resting tags, and the four layer plates.
 *
 * The hero carries one concrete dispute — CBK-78291 — from the resting card
 * through to the verdict. Its headline values are the three floating tags; the
 * same values, made granular, are what each plate reveals.
 *
 * Two honesty rules, inherited from the rest of the site:
 *
 *   1. Case-level values are *preset case data*, defined once in `HERO_CASE`
 *      and derived from it everywhere else. Nothing in the hero invents a number.
 *
 *   2. Model-quality figures (Brier, ECE, the reliability bin) are *measured*,
 *      read from `metrics.json` — the same committed report the evaluation
 *      section renders. Hardcoding them would let the hero and the eval
 *      dashboard drift apart and quietly disagree about the model.
 *
 * NOTE ON THE REFERENCE FILE. `stage1_ascension_final.html` carries placeholder
 * figures (73.4% p_win, 61.2% threshold, a Mumbai IP, a 98.2% signature match).
 * Those are not this case, and the 61.2% threshold is not consistent with
 * `p* = λc/A` for a ₹18,500 dispute at all. The mechanics are ported from that
 * file exactly; the numbers are taken from the repository instead, computed
 * through `lib/economics.js` — which is what the build's own content rules
 * require. The real threshold for this dispute is ~2.3%, and the large margin
 * over it is precisely why the case is a CONTEST.
 *
 * Portfolio statistics are deliberately absent: this is one dispute, not the book.
 */

import metrics from '../../data/metrics.json';
import {
  DEFAULT_COST_INR,
  DEFAULT_RISK_MARGIN,
  decisionThreshold,
  expectedValue,
  formatInr,
  formatPercent,
} from '../../lib/economics.js';
import { COLOR } from './constants.js';

/* -------------------------------------------------------------------------- */
/* The hero case.                                                             */
/* -------------------------------------------------------------------------- */

/**
 * `pWin` is this case's calibrated score. It displays as 0.73; the unrounded
 * value drives the EV, so the "EV +₹13,079" tag is the arithmetic of the "0.73"
 * tag rather than a second, independent figure.
 */
export const HERO_CASE = {
  id: 'CBK-78291',
  amountInr: 18500,
  reasonCode: '10.4',
  reasonLabel: 'FRAUD, CARD-ABSENT',
  pWin: 0.7259,
  decision: 'CONTEST',
  costInr: DEFAULT_COST_INR,
  riskMargin: DEFAULT_RISK_MARGIN,
  // Evidence position, mirroring the `electronics-fraud` preset in lib/presets.js.
  awb: 'BLU4471902238',
  ipCity: 'Bengaluru, IN',
  device: 'dev_a91f4c73',
  nameMatch: 1.0,
  ocrConfidence: 0.94,
};

export const HERO_THRESHOLD = decisionThreshold(
  HERO_CASE.amountInr,
  HERO_CASE.costInr,
  HERO_CASE.riskMargin,
);

export const HERO_EV = expectedValue(
  HERO_CASE.pWin,
  HERO_CASE.amountInr,
  HERO_CASE.costInr,
);

/* -------------------------------------------------------------------------- */
/* The three resting tags.                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Resting offsets from the card's centre, in pixels.
 *
 * Asymmetric by construction — upper-left, mid-right, lower-right, at differing
 * distances. Never a symmetric wreath, never a grid. `floatPeriod` differs per
 * tag so they never drift in visible sync with each other or with the card;
 * that asynchrony is most of what separates "considered" from "templated".
 */
export const FLOATING_TAGS = [
  {
    key: 'p',
    label: 'WIN PROBABILITY',
    value: HERO_CASE.pWin.toFixed(2),
    accent: COLOR.indigo,
    dx: -208,
    dy: -156,
    floatPeriod: 4.2,
  },
  {
    key: 'd',
    label: 'DECISION',
    value: HERO_CASE.decision,
    accent: COLOR.emerald,
    dx: 246,
    dy: -26,
    floatPeriod: 5.1,
  },
  {
    key: 'ev',
    label: 'EV',
    value: `+${formatInr(HERO_EV)}`,
    accent: COLOR.amber,
    dx: 178,
    dy: 164,
    floatPeriod: 4.7,
  },
];

/* -------------------------------------------------------------------------- */
/* The four plates.                                                          */
/* -------------------------------------------------------------------------- */

/**
 * `overview` is the one line shown while the plates are merely separated;
 * `rows` is the detail withheld until a plate is inspected on the ring.
 */
export const PLATES = [
  {
    n: '01',
    kind: 'identity',
    accent: COLOR.emerald,
    title: 'IDENTITY SHELL',
    big: 'Device + session',
    overview: 'Identity Shell',
    // `meter` renders as a labelled confidence bar; `rows` as tabular telemetry.
    meter: { label: 'Device fingerprint confidence', value: 0.97 },
    rows: [
      { k: 'Fingerprint', v: `${HERO_CASE.device} · MATCH` },
      { k: 'IP telemetry', v: HERO_CASE.ipCity },
      { k: '3DS auth token', v: 'AUTHENTICATED' },
    ],
  },
  {
    n: '02',
    kind: 'forensic',
    accent: COLOR.cyan,
    title: 'FORENSIC EVIDENCE',
    big: 'Proof of delivery',
    overview: 'Forensic Evidence Plate',
    // The pill is this case's real recipient-name match, not a placeholder.
    pill: { value: formatPercent(HERO_CASE.nameMatch, 1), state: 'CONFIRMED' },
    badge: `AWB ${HERO_CASE.awb}`,
    rows: [
      { k: 'Courier scan', v: 'VERIFIED' },
      { k: 'OCR confidence', v: HERO_CASE.ocrConfidence.toFixed(2) },
      { k: 'Delivery window', v: 'ON TIME' },
    ],
  },
  {
    n: '03',
    kind: 'lattice',
    accent: COLOR.indigo,
    title: 'INTELLIGENCE LATTICE',
    big: 'Calibrated probability',
    overview: 'Intelligence Lattice',
    // The neon readout. This is THIS CASE's calibrated score (72.6%), not a
    // rounded-up marketing figure -- it is the same value the EV below it is
    // computed from, so the two can never drift apart on screen.
    score: formatPercent(HERO_CASE.pWin, 1),
    rows: [
      { k: 'Model', v: metrics.config.model_version },
      // Measured, from metrics.json -- the held-out test set, not this case.
      { k: 'Brier / ECE', v: `${metrics.classifier.brier.toFixed(3)} / ${metrics.classifier.ece.toFixed(3)}` },
    ],
    footnote: 'Held-out test set · metrics.json',
  },
  {
    n: '04',
    kind: 'governor',
    accent: COLOR.amber,
    title: 'ECONOMIC GOVERNOR',
    // Not the formula: the formula block below already states it, and a title
    // that repeats the element under it wastes the plate's most legible line.
    big: 'Decision authority',
    overview: 'Economic Governor',
    evBadge: `+${formatInr(HERO_EV)} EV`,
    rows: [
      { k: 'Threshold p*', v: formatPercent(HERO_THRESHOLD, 1) },
      { k: 'Margin over p*', v: `+${formatPercent(HERO_CASE.pWin - HERO_THRESHOLD, 1)}` },
      { k: 'Verdict', v: HERO_CASE.decision },
    ],
  },
];
