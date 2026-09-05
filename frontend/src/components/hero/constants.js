/**
 * Shared tokens, timings and the small amount of maths the hero sequence needs.
 *
 * The scroll breakpoints are consumed by both the shared animation loop (which
 * computes plate transforms) and the chapter copy (which swaps at stage
 * boundaries). They live here so the two can never drift apart and announce a
 * stage the plates have not yet entered.
 */

/* -------------------------------------------------------------------------- */
/* Palette. Mirrors tailwind.config.js, plus the gold used by the Economic     */
/* Governor, which is specific to this sequence.                              */
/* -------------------------------------------------------------------------- */

export const COLOR = {
  bg: '#0B1720',
  slate: '#AEBFC7',
  // Plate accents, one per layer. Each is the single source for that plate's
  // rule, header, focus glow and scan line -- passed down as the `--ac` custom
  // property so a plate can never disagree with itself about its own colour.
  emerald: '#62C6D7',      // 01 Identity Shell
  cyan: '#8BD5DE',         // 02 Forensic Evidence
  indigo: '#F0B66E',       // 03 Intelligence Lattice
  amber: '#E5A56D',        // 04 Economic Governor
  neonEmerald: '#A7E8EC',  // preloader sparkle only
  ink: '#EDF5F7',
  muted: '#718893',
};

/* -------------------------------------------------------------------------- */
/* Scroll stage boundaries, in normalised hero-scroll progress [0, 1].        */
/* -------------------------------------------------------------------------- */

export const STAGE = {
  restEnd: 0.08,   // card + tags at rest; tags clear by here
  splitStart: 0.1,
  splitEnd: 0.38,
  ringStart: 0.38,
  ringEnd: 0.62,
  exitStart: 0.9,  // plate i begins exiting at exitStart + i * EXIT_STAGGER
};

/** Per-plate stagger on the ascension exit, in scroll progress. */
export const EXIT_STAGGER = 0.018;

/** Ring formation is "complete" past this, which is when auto-rotation begins. */
export const RING_FORMED_AT = 0.985;

/* -------------------------------------------------------------------------- */
/* Geometry.                                                                  */
/* -------------------------------------------------------------------------- */

export const PLATE_COUNT = 4;

/** Angular position of each plate on the ring. */
export const THETA = [0, 90, 180, 270];

/** Stack separation while split. Both axes are required — see Stage.jsx. */
export const SPLIT_Y = 195;
export const SPLIT_Z = 85;

/** Ring radius by breakpoint. Below 768px there is no ring at all. */
// Tablet was 200 -- combined with CARD_WIDTH.tablet driving a uniform
// scale(cardWidth/440) over the whole rig (see Stage.jsx), plate text that
// reads fine at 440px was shrinking to ~75%, past comfortable legibility.
export const RING_RADIUS = { desktop: 300, tablet: 235 };

/** Continuous ring spin, degrees per second, once formed. */
export const RING_SPEED_DEG_S = 22;

/** Pulse heads travel faster than the ring, so they read as flow, not carriage. */
export const PULSE_SPEED_DEG_S = 70;
export const PULSE_HEADS = 3;
export const PULSE_TAIL = 3;       // echo dots per head
export const PULSE_TAIL_GAP_DEG = 5;

/** Cursor may nudge the ring by this much, either way. */
// Was 70 (a full-width sweep swung the ring +/-35deg). At that sensitivity a
// few pixels of real cursor movement was enough to swing a different plate to
// the front, which combined with focus hysteresis fighting the swing read as
// "twitchy" rather than "responsive". 30 still comfortably covers browsing
// between 4 plates 90deg apart, at a pace a reader can actually track.
export const MANUAL_OFFSET_DEG = 30;

/** Heartbeat period, seconds. Sonar rings are offset by half of it. */
export const HEARTBEAT_PERIOD_S = 2.1;

/** Focus response. */
export const FOCUS_SCALE = 1.14;
export const FOCUS_Z = 90;
export const UNFOCUSED_OPACITY = 0.22;
export const UNFOCUSED_BLUR = 5;

/** Ascension exit. */
export const EXIT_Y = -680;
export const EXIT_SCALE = 0.72;
export const EXIT_BLUR = 10;

/** Card width by breakpoint. 440px is the reference's value. */
export const CARD_WIDTH = { desktop: 440, tablet: 380 };

/** How many resting tags each breakpoint shows. Below 1024px, just one. */
export const TAG_COUNT = { desktop: 3, tablet: 1 };

/* -------------------------------------------------------------------------- */
/* Maths helpers.                                                             */
/* -------------------------------------------------------------------------- */

export const clamp = (v, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));

export const lerp = (a, b, t) => a + (b - a) * t;

export function mapRange(v, inMin, inMax, outMin, outMax) {
  if (inMax === inMin) return outMin;
  return lerp(outMin, outMax, clamp((v - inMin) / (inMax - inMin)));
}

export const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

export const easeInOutCubic = (t) =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

/**
 * The reference file's `eIO`. Quadratic, not cubic — every split/ring/exit
 * timing in `stage1_ascension_final.html` was tuned against this exact curve,
 * so substituting a cubic would subtly change motion that is already correct.
 */
export const easeInOutQuad = (t) =>
  t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;

/** Progress of v through [start,end] as an eased 0..1, clamped outside. */
export function segment(v, start, end, ease = (t) => t) {
  return ease(clamp((v - start) / (end - start)));
}
