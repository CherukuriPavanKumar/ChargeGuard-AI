import { useEffect, useMemo, useRef, useState } from 'react';

import { prefersReducedMotion } from '../../hooks/usePointer.js';

/**
 * RevealTransition — a card-shaped window that grows until it fills the
 * viewport, revealing the section it wraps.
 *
 * Wrap the section to reveal:
 *
 *   <RevealTransition><ArchitectureDiagram /></RevealTransition>
 *
 * ---------------------------------------------------------------------------
 * NO DUPLICATE RENDER — the window is a HOLE, not a picture
 * ---------------------------------------------------------------------------
 * The obvious implementation of this effect puts a copy of the target section
 * inside a positively-masked layer, and the real section after the track. That
 * renders the section twice: duplicate DOM, duplicate `id="architecture"`
 * (which silently breaks the nav's scroll-spy, since `getElementById` returns
 * whichever copy comes first), and duplicate charts/observers.
 *
 * This inverts it. `children` is rendered exactly ONCE. During the reveal its
 * wrapper is `position: fixed` — pinned to the viewport, clipped to one screen
 * — and an opaque cover sits on top with a rounded-rect hole punched through
 * it. What you see through the hole is therefore the real section, not a
 * likeness of it, so "pixel-identical at handoff" is true by construction
 * rather than by careful matching.
 *
 * The hole is cut with `clip-path: path(evenodd, ...)` — the viewport rect
 * followed by the card rect, with the even-odd fill rule leaving the card
 * as a gap. This is used in preference to two mask layers composited with
 * `mask-composite: exclude`, whose `-webkit-` form takes different keywords
 * and is the more fragile of the two across engines. The growth maths is
 * unchanged, and `--maskW` is still written each frame for inspectability.
 *
 * ---------------------------------------------------------------------------
 * WHY THE HANDOFF SWAPS AT p = 1, NOT p = 0.97
 * ---------------------------------------------------------------------------
 * The two requirements "unpin at p >= 0.97" and "no visible seam at the
 * handoff" cannot both hold literally. When the wrapper stops being fixed it
 * lands where normal flow puts it, and flow alignment is only exact once the
 * full reveal distance has been scrolled. Swapping at 0.97 leaves ~3% of the
 * track — several vh — between the pinned position and the flow position, and
 * the section visibly jumps by exactly that much.
 *
 * So the *visual* reveal completes by 0.97 (the hole is larger than the
 * viewport well before then, so the last 3% shows a fully-open, unobstructed
 * section), and the *positional* swap happens at p = 1, where flow alignment
 * is exact and the swap is invisible. The seam requirement wins because it is
 * the one a viewer can actually see.
 *
 * ---------------------------------------------------------------------------
 * Notes
 * ---------------------------------------------------------------------------
 * - No GSAP. Progress comes from the same `getBoundingClientRect` read the
 *   hero's ring stage already uses, on one rAF loop that stops for good once
 *   the reveal has released.
 * - `clip-path` and the custom property are paint-only; neither forces layout.
 * - The track keeps its height after release, so releasing never changes
 *   document height and never jolts the scroll position.
 */

/** Card proportions, shared with the hero: 22px radius at a 440px width. */
const CARD_ASPECT = 1.586;
const CARD_RADIUS_RATIO = 22 / 440;

/**
 * Measure the H's crossbar by rasterising the glyph and reading its pixels.
 *
 * The aperture has to match the bar exactly — its width is the gap between the
 * stems, its height the bar's stroke thickness — and neither is derivable from
 * font metrics: `measureText` reports advances and bounding boxes, never the
 * position of a stroke inside the outline. So the glyph is drawn once per font
 * size and scanned:
 *
 *   1. Probe a row above the bar. It crosses both stems and nothing else, so
 *      its two filled runs give the stems' inner edges — the counter.
 *   2. Probe the column midway between those edges. There the only ink is the
 *      bar itself, so its filled run gives the bar's top and bottom.
 *
 * Results are cached per font size; the scan is a few thousand byte reads and
 * only reruns when the size actually changes.
 */
const glyphCache = new Map();

/** Aperture width as a fraction of the true counter, so it sits neatly inside
 *  the stems instead of touching both. */
const BAR_INSET = 0.86;

function measureCrossbar(fontSizePx) {
  const key = Math.round(fontSizePx);
  if (glyphCache.has(key)) return glyphCache.get(key);
  if (typeof document === 'undefined' || key < 8) return null;

  const size = key;
  const c = document.createElement('canvas');
  c.width = Math.ceil(size * 1.6);
  c.height = Math.ceil(size * 2);
  const g = c.getContext('2d', { willReadFrequently: true });
  const baseline = Math.round(size * 1.4);
  g.font = `800 ${size}px "Plus Jakarta Sans", system-ui, sans-serif`;
  g.textBaseline = 'alphabetic';
  g.fillStyle = '#fff';
  g.fillText('H', Math.round(size * 0.2), baseline);

  const { data } = g.getImageData(0, 0, c.width, c.height);
  const on = (x, y) => data[(y * c.width + x) * 4 + 3] > 128;

  // Ink bounding box.
  let minX = c.width;
  let maxX = -1;
  let minY = c.height;
  let maxY = -1;
  for (let y = 0; y < c.height; y += 1) {
    for (let x = 0; x < c.width; x += 1) {
      if (on(x, y)) {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }
  }
  if (maxX < 0) return null;

  // A row well above the bar: crosses the two stems only.
  const probeY = Math.round(minY + (maxY - minY) * 0.16);
  const runs = [];
  let run = null;
  for (let x = minX; x <= maxX; x += 1) {
    if (on(x, probeY)) {
      if (!run) run = { a: x, b: x };
      else run.b = x;
    } else if (run) {
      runs.push(run);
      run = null;
    }
  }
  if (run) runs.push(run);
  if (runs.length < 2) return null;

  const counterLeft = runs[0].b + 1;
  const counterRight = runs[runs.length - 1].a - 1;
  const counterW = counterRight - counterLeft;
  if (counterW <= 1) return null;

  // A column between the stems: the only ink there is the bar.
  const probeX = Math.round((counterLeft + counterRight) / 2);
  let barTop = -1;
  let barBottom = -1;
  for (let y = minY; y <= maxY; y += 1) {
    if (on(probeX, y)) {
      if (barTop < 0) barTop = y;
      barBottom = y;
    }
  }
  if (barTop < 0) return null;

  // Font metrics for the same face and size. An inline span's box is the
  // content area — ascent + descent — NOT the font size, and its bottom edge
  // is the descender, NOT the baseline. Both facts are needed to place the bar
  // correctly inside the rendered span.
  const tm = g.measureText('H');
  const ascent = tm.fontBoundingBoxAscent;
  const descent = tm.fontBoundingBoxDescent;

  const result = {
    // All in px at this font size.
    barW: counterW,
    barH: barBottom - barTop + 1,
    barCentreFromBaseline: baseline - (barTop + barBottom) / 2,
    ascent,
    descent,
  };
  glyphCache.set(key, result);
  return result;
}

/**
 * Aperture width at progress 0 — a micro-card nested inside the H's counter.
 *
 * Derived from the measured glyph rather than a fixed number, then clamped to
 * the per-breakpoint range so it can never grow past the stems on an unusual
 * font fallback. `hSpanWidth` includes the trailing letter-spacing, and the
 * counter of a weight-800 H is a little under half the remaining advance.
 */
function startSizeFor(vw, hSpanWidth) {
  const range = vw < 640 ? [36, 42] : vw < 1024 ? [52, 60] : [70, 80];
  const fromGlyph = hSpanWidth ? hSpanWidth * 0.43 : range[1];
  return Math.max(range[0], Math.min(range[1], fromGlyph));
}

/** Track height in vh. Shorter on phones so the reveal doesn't outstay it. */
function trackVhFor(vw) {
  return vw < 768 ? 180 : 260;
}

/**
 * A rounded rectangle as an SVG path, generated rather than hand-authored —
 * four arcs and four lines, which is small enough to be obviously correct and
 * removes the risk of a malformed literal path string.
 */
function roundedRectPath(cx, cy, w, h, r) {
  const x = cx - w / 2;
  const y = cy - h / 2;
  const rr = Math.max(0, Math.min(r, w / 2, h / 2));
  return (
    `M${x + rr},${y}` +
    `H${x + w - rr}` +
    `A${rr},${rr} 0 0 1 ${x + w},${y + rr}` +
    `V${y + h - rr}` +
    `A${rr},${rr} 0 0 1 ${x + w - rr},${y + h}` +
    `H${x + rr}` +
    `A${rr},${rr} 0 0 1 ${x},${y + h - rr}` +
    `V${y + rr}` +
    `A${rr},${rr} 0 0 1 ${x + rr},${y}` +
    'Z'
  );
}

/** How many depth slices build the watermark's extruded side wall. */
const WATERMARK_DEPTH = 18;

/**
 * The watermark, as an actual solid.
 *
 * Each slice is a real element pushed a further pixel back in Z inside a
 * `preserve-3d` rig, so the side wall is geometry rather than a stack of
 * painted offsets — turn the rig and the wall turns with it, which a
 * text-shadow extrusion cannot do. Slices darken with depth so the wall falls
 * away from the lit face instead of reading as a flat slab.
 */
const WORD = 'ChargeGuard';
/** Index of the centre glyph the aperture docks into. */
const DOCK_INDEX = 3; // the H in P R A H A R I

function Watermark({ dockRef }) {
  const slices = useMemo(
    () =>
      Array.from({ length: WATERMARK_DEPTH }, (_, i) => {
        const t = i / (WATERMARK_DEPTH - 1);
        return {
          z: -(i + 1) * 1.6,
          // Fades toward the back so the extrusion has falloff, not a hard end.
          color: `rgba(${Math.round(18 - 12 * t)}, ${Math.round(48 - 34 * t)}, ${Math.round(40 - 28 * t)}, 1)`,
        };
      }),
    [],
  );

  return (
    <div className="reveal-watermark" aria-hidden="true">
      <div className="reveal-watermark__rig">
        {slices.map((s) => (
          <span
            key={s.z}
            className="reveal-watermark__layer reveal-watermark__depth"
            style={{ transform: `translateZ(${s.z}px)`, color: s.color }}
          >
            {WORD}
          </span>
        ))}
        {/* The face is split per letter so the dock glyph can be measured.
            Assuming the centre letter sits at 50% is wrong: ChargeGuard's left
            group (P R A) is much wider than its right (A R I) -- measured at
            1440px, H's centre lands 60px right of the viewport centre -- so a
            50%-positioned aperture would dock over the A, not inside the H. */}
        <span className="reveal-watermark__layer reveal-watermark__face">
          {WORD.split('').map((ch, i) => (
            // Plain inline spans, NOT inline-block: inline-block changes how
            // letter-spacing and kerning resolve, which made the face word
            // measurably wider than the plain-text depth slices behind it and
            // showed up as ghosted, doubled letters. Inline spans leave text
            // layout untouched and still report a correct bounding box.
            <span key={`${ch}-${i}`} ref={i === DOCK_INDEX ? dockRef : undefined}>
              {ch}
            </span>
          ))}
        </span>
      </div>
    </div>
  );
}

/**
 * Neon dust motes filling the air around the aperture.
 *
 * Positions and timings are drawn once at mount and kept — regenerating them
 * on re-render would make the field visibly reshuffle. Rendered inside the
 * cover so the aperture's clip-path erases them within the window: the dust is
 * in the room, never over the revealed section.
 */
function DustField({ count = 54 }) {
  const motes = useMemo(
    () =>
      Array.from({ length: count }, (_, i) => {
        // Deterministic scatter, so the field is stable across renders.
        const r = (n) => {
          const x = Math.sin((i + 1) * n) * 43758.5453;
          return x - Math.floor(x);
        };
        const size = 1 + r(12.9898) * 2.2;
        const angle = r(4.1414) * Math.PI * 2;
        const travel = 40 + r(93.989) * 130;
        return {
          id: i,
          left: `${r(78.233) * 100}%`,
          top: `${r(11.7) * 100}%`,
          size,
          dx: `${Math.cos(angle) * travel}px`,
          dy: `${Math.sin(angle) * travel - 30}px`,
          dur: 9 + r(27.61) * 14,
          delay: -r(53.17) * 20,
          // Smaller motes sit further back, so they glow less.
          op: 0.25 + (size / 3.2) * 0.5,
        };
      }),
    [count],
  );

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      {motes.map((m) => (
        <span
          key={m.id}
          className="reveal-dust"
          style={{
            left: m.left,
            top: m.top,
            width: `${m.size}px`,
            height: `${m.size}px`,
            boxShadow: `0 0 ${m.size * 4}px ${m.size * 0.9}px rgba(16,185,129,0.75)`,
            animationDuration: `${m.dur}s`,
            animationDelay: `${m.delay}s`,
            '--dx': m.dx,
            '--dy': m.dy,
            '--dust-op': m.op,
          }}
        />
      ))}
    </div>
  );
}

/** One L-shaped corner mark. */
function CornerBracket({ corner }) {
  const base = 'absolute h-[18px] w-[18px]';
  const edge = 'rgba(16, 185, 129, 0.4)';
  const pos = {
    tl: 'left-6 top-6 border-l border-t',
    tr: 'right-6 top-6 border-r border-t',
    bl: 'bottom-6 left-6 border-b border-l',
    br: 'bottom-6 right-6 border-b border-r',
  }[corner];
  return <div className={`${base} ${pos}`} style={{ borderColor: edge }} aria-hidden="true" />;
}

export default function RevealTransition({ children }) {
  const trackRef = useRef(null);
  const coverRef = useRef(null);
  const stageRef = useRef(null);
  const rimRef = useRef(null);
  const dockRef = useRef(null);
  // Measured H box, refreshed each frame; cheap, and always in step with resize.
  const dockBox = useRef(null);
  const wrapRef = useRef(null);

  // `reduced` is read once: under reduced motion the component renders in its
  // released state from the first paint and no loop ever starts.
  const [reduced] = useState(() => prefersReducedMotion());

  // Three phases, not a boolean.
  //
  //   'before'  the track has not reached the top of the viewport yet. The
  //             section sits below the fold in normal flow and NOTHING is
  //             pinned or covered. This phase existing at all is the fix for
  //             a real bug: with only an active/released boolean, the cover
  //             and the pinned section were mounted from the first paint, so
  //             an opaque overlay sat over the hero and every section above
  //             this one for the whole page.
  //   'during'  the track spans the viewport: section pinned, cover on top.
  //   'after'   released into normal flow.
  const [phase, setPhase] = useState(() => (prefersReducedMotion() ? 'after' : 'before'));
  const [trackVh, setTrackVh] = useState(() =>
    typeof window === 'undefined' ? 260 : trackVhFor(window.innerWidth),
  );

  const phaseRef = useRef(phase);
  phaseRef.current = phase;

  useEffect(() => {
    // `released` is a dependency, not just a guard: when the reader scrolls
    // back up and the re-arm effect below flips it false, this effect must run
    // again to restart the loop. Without it in the deps the loop stays dead
    // after the first release, and a re-entered transition renders a frozen
    // cover stuck at its initial window size.
    if (reduced || phase === 'after') return undefined;

    const onResize = () => setTrackVh(trackVhFor(window.innerWidth));
    window.addEventListener('resize', onResize);

    let raf = 0;
    let stopped = false;

    const frame = () => {
      if (stopped) return;
      const track = trackRef.current;
      if (!track) {
        raf = requestAnimationFrame(frame);
        return;
      }

      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const rect = track.getBoundingClientRect();

      // Reveal distance is the track minus one viewport: the wrapper is pinned
      // for exactly that span, and p = 1 is the moment flow alignment is exact.
      const distance = Math.max(1, track.offsetHeight - vh);
      const p = Math.min(1, Math.max(0, -rect.top / distance));

      // Measure the dock glyph. Cached in a ref and refreshed whenever it moves,
      // so a resize or a late webfont swap re-seats the aperture instead of
      // leaving it docked to where the H used to be.
      const dockEl = dockRef.current;
      if (dockEl) {
        const d = dockEl.getBoundingClientRect();
        if (d.width > 0) {
          const fs = parseFloat(getComputedStyle(dockEl).fontSize) || d.height;
          const bar = measureCrossbar(fs);
          // The span's box is the content area (ascent + descent), projected by
          // the rig's rotation. Dividing by that same em height turns the
          // glyph-space measurements into on-screen pixels, absorbing both the
          // metrics and the projection in one factor.
          const em = bar ? bar.ascent + bar.descent : fs;
          const scale = em > 0 ? d.height / em : 1;
          dockBox.current = bar
            ? {
                cx: d.left + d.width / 2,
                // Measured DOWN from the box top: the baseline sits `ascent`
                // below it, and the bar sits `barCentreFromBaseline` above the
                // baseline. Measuring up from d.bottom instead treats the
                // descender as the baseline and drops the card below the bar.
                cy: d.top + (bar.ascent - bar.barCentreFromBaseline) * scale,
                // Slightly inset from the stems so the bar reads as seated
                // between them rather than butting into both.
                w: bar.barW * scale * BAR_INSET,
                h: bar.barH * scale,
              }
            : {
                cx: d.left + d.width / 2,
                cy: d.top + d.height * 0.42,
                w: d.width * 0.43,
                h: (d.width * 0.43) / CARD_ASPECT,
              };
        }
      }
      const dock = dockBox.current;

      // growthRange is derived from the viewport, never a fixed pixel value —
      // a hardcoded range leaves the hole undersized on very large or very
      // tall screens, where it would stop growing before it covered them.
      //
      // `vh * CARD_ASPECT`, not plain `vh`, is the load-bearing part. The hole
      // is a 1.586-aspect card, so its HEIGHT is only maskW / 1.586 — sizing
      // the range against raw viewport height leaves the card too short to
      // cover a tall screen even at full progress. Measured before this fix:
      // at 390x844 the hole reached 830px tall against an 844px viewport, so a
      // 14px band of cover never opened; 500x1600 and 1280x2000 failed wider
      // still. Scaling the height constraint back into a width requirement
      // fixes every tall viewport without changing wide ones (on 1440x900 and
      // above, width remains the binding constraint and the value is
      // unchanged).
      const growthRange = Math.max(vw, vh * CARD_ASPECT) * 1.3;
      // Exponent 2.6: the aperture holds its nested size for longer before the
      // ramp takes over, so the micro-card reads as seated in the glyph rather
      // than already escaping it on the first few pixels of scroll.
      const startW = dock?.w ?? startSizeFor(vw, null);
      const maskW = startW + Math.pow(p, 2.6) * growthRange;

      // At rest the aperture IS the crossbar, so it takes the bar's own
      // proportions (a bar is far wider than it is thick — nothing like a
      // card). That aspect eases to the card's 1.586 over the first sliver of
      // scroll, so it reads as the bar opening into a card rather than a card
      // that never matched the glyph it came from.
      const startAspect = dock?.h > 0 ? dock.w / dock.h : CARD_ASPECT;
      const shapeT = Math.min(1, p / 0.14);
      const aspect = startAspect + (CARD_ASPECT - startAspect) * shapeT;
      const maskH = maskW / aspect;

      // Origin drifts from inside the H back to the viewport centre. It starts
      // nested in the glyph and finishes centred, which is both what the effect
      // wants and what keeps full-screen coverage honest -- an aperture that
      // stayed off-centre would need to grow further to cover the far edge.
      const dockLerp = Math.min(1, Math.pow(p, 0.85) * 1.25);
      const originX = dock ? dock.cx + (vw / 2 - dock.cx) * dockLerp : vw / 2;
      const originY = dock ? dock.cy + (vh / 2 - dock.cy) * dockLerp : vh / 2;

      const cover = coverRef.current;
      if (cover) {
        cover.style.setProperty('--maskW', `${maskW}px`);
        const outer = `M0,0H${vw}V${vh}H0Z`;
        const hole = roundedRectPath(originX, originY, maskW, maskH, maskW * CARD_RADIUS_RATIO);
        cover.style.clipPath = `path(evenodd, "${outer}${hole}")`;
        cover.style.webkitClipPath = `path(evenodd, "${outer}${hole}")`;
      }

      // The rim tracks the hole exactly — same centre, same size, same corner
      // radius — so the machined edge and the cut edge are always one shape.
      // It fades once the aperture outgrows the viewport, by which point the
      // edge has travelled off-screen and only its bloom would remain.
      const rim = rimRef.current;
      if (rim) {
        rim.style.width = `${maskW}px`;
        rim.style.height = `${maskH}px`;
        rim.style.borderRadius = `${maskW * CARD_RADIUS_RATIO}px`;
        rim.style.left = `${originX}px`;
        rim.style.top = `${originY}px`;
        const over = Math.max(maskW / vw, maskH / vh);
        rim.style.opacity = String(Math.max(0, Math.min(1, 1.55 - over)));
        // Lit-microchip treatment only while it is genuinely nested.
        rim.classList.toggle('reveal-rim--chip', p < 0.05);
      }

      // The instrument chrome belongs to the closed state; it clears as the
      // window opens rather than sitting over the revealed section.
      const stage = stageRef.current;
      if (stage) stage.style.opacity = String(Math.max(0, 1 - p * 1.6));

      if (p >= 1) {
        // Released: swap to normal flow and stop the loop.
        stopped = true;
        setPhase('after');
        return;
      }

      // Pin only once the track has actually reached the top of the viewport.
      // Above that the reader is still on the sections before this one and
      // must see them, not a cover.
      const wantDuring = rect.top <= 0;
      if (wantDuring && phaseRef.current !== 'during') setPhase('during');
      else if (!wantDuring && phaseRef.current !== 'before') setPhase('before');

      raf = requestAnimationFrame(frame);
    };

    raf = requestAnimationFrame(frame);
    return () => {
      stopped = true;
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', onResize);
    };
  }, [reduced, phase]);

  // Re-arm if the reader scrolls back up above the track after release, so the
  // transition is not a one-shot that leaves a dead pinned section behind.
  useEffect(() => {
    if (reduced || phase !== 'after') return undefined;
    const onScroll = () => {
      const track = trackRef.current;
      if (!track) return;
      if (track.getBoundingClientRect().top > 0) setPhase('before');
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, [reduced, phase]);

  const pinned = phase === 'during';

  return (
    <>
      {/* Scroll track. Keeps its height after release so the document never
          changes height underneath the reader. */}
      <div
        ref={trackRef}
        aria-hidden="true"
        style={{ height: reduced ? 0 : `${trackVh}vh` }}
      />

      {/* The revealed section, rendered exactly once. Only this wrapper's
          positioning changes at handoff, so `children` never remounts and
          nothing inside it restarts. */}
      <div
        ref={wrapRef}
        className={pinned ? 'fixed inset-0 z-[40] overflow-hidden' : 'relative'}
        style={pinned || reduced ? undefined : { marginTop: '-100vh' }}
      >
        {children}
      </div>

      {pinned && (
        <>
          {/* The opaque cover with the card-shaped hole. */}
          <div
            ref={coverRef}
            aria-hidden="true"
            className="pointer-events-none fixed inset-0 z-[41]"
            style={{ background: '#0B1720' }}
          >
            <DustField />
            <div className="absolute inset-0 flex select-none items-center justify-center">
              <Watermark dockRef={dockRef} />
            </div>
          </div>

          {/* The lit bevel around the aperture, above the cover so its bloom
              falls on the cover, and below the chrome. Border-and-shadow only:
              the revealed section shows straight through the middle. */}
          <div ref={rimRef} aria-hidden="true" className="reveal-rim z-[42]">
            <span className="reveal-light reveal-light--key" />
            <span className="reveal-light reveal-light--fill" />
          </div>

          {/* Instrument chrome + intro copy, above the cover. */}
          <div
            ref={stageRef}
            aria-hidden="true"
            className="pointer-events-none fixed inset-0 z-[43]"
          >
            <CornerBracket corner="tl" />
            <CornerBracket corner="tr" />
            <CornerBracket corner="bl" />
            <CornerBracket corner="br" />

            <div className="absolute inset-x-0 top-[18%] flex flex-col items-center px-6 text-center">
              <p className="font-display text-2xl font-600 tracking-[-0.02em] text-white sm:text-3xl">
                The case is resolved.
              </p>
              <p className="mt-2 text-sm" style={{ color: '#8A94A6' }}>
                Here&rsquo;s how it got there.
              </p>
            </div>
          </div>
        </>
      )}
    </>
  );
}
