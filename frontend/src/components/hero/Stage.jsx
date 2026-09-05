import { useEffect, useRef } from 'react';

import Card from './Card.jsx';
import ExplodedPlate from './ExplodedPlates.jsx';
import HeroSection from './HeroSection.jsx';
import ChromaticNeuralBeam from './ChromaticNeuralBeam.jsx';
import FloatingTags from './FloatingTags.jsx';
import { PLATES } from './plateData.js';
import {
  THETA,
  PLATE_COUNT,
  SPLIT_Y,
  SPLIT_Z,
  RING_SPEED_DEG_S,
  PULSE_SPEED_DEG_S,
  PULSE_HEADS,
  PULSE_TAIL,
  PULSE_TAIL_GAP_DEG,
  MANUAL_OFFSET_DEG,
  FOCUS_SCALE,
  FOCUS_Z,
  UNFOCUSED_OPACITY,
  UNFOCUSED_BLUR,
  EXIT_STAGGER,
  clamp,
  easeInOutQuad,
} from './constants.js';

/**
 * The pinned stage: card at rest, the split into four plates, the ring, hover
 * focus, and the ascension exit — all driven by ONE requestAnimationFrame loop.
 *
 * Ported from `stage1_ascension_final.html`. The transform composition and every
 * timing constant come from that file; they were tuned by hand and are not
 * reinterpreted here.
 *
 * ---------------------------------------------------------------------------
 * Why one loop, and why imperative
 * ---------------------------------------------------------------------------
 * Each plate's transform blends a scroll-driven value (split → ring), a
 * time-driven value (auto-rotation), and a pointer-driven value (manual offset
 * and focus). A scroll-linked Framer value and a rAF value writing the same
 * `transform` would fight for it every frame, so this loop is the sole author
 * of each plate's transform/opacity/filter. Framer Motion is still used where
 * it is genuinely better — the tags' spring entrance — because those elements
 * are not written by this loop.
 *
 * The same loop also drives the pulse trails and the core's fade, so ring,
 * pulses and heartbeat all read the page at one instant rather than three.
 *
 * ---------------------------------------------------------------------------
 * The transform composition — order is load-bearing
 * ---------------------------------------------------------------------------
 *   rotateY(rotY) translateY(curY) translateZ(curZ) scale(s)
 *
 * `rotateY` must be outermost. Rotation about Y does not affect the Y
 * coordinate, so `translateY` keeps the plate at exactly the height it is
 * given regardless of spin, while `translateZ` sweeps around into the visible
 * X/Z circle as `rotY` grows. That is what makes one set of numbers interpolate
 * cleanly from a vertical stack into a ring. Reorder these and the plates move
 * unpredictably.
 *
 * ---------------------------------------------------------------------------
 * The hover bug this deliberately avoids
 * ---------------------------------------------------------------------------
 * Focus is NEVER driven by hovering a plate. A rotating plate slides out from
 * under the cursor and fires `mouseleave` on itself, cancelling its own focus
 * before anything visible happens. Instead the container tracks `mousemove`,
 * maps pointer-x to a manual rotation offset, and the focused plate is simply
 * whichever currently has the highest `facing` value. The cursor is never
 * tested against a moving element's box.
 */
export default function Stage({ trackRef, radius, cardWidth, reduced, tagCount }) {
  const stageRef = useRef(null);
  const rigRef = useRef(null);
  const cardRef = useRef(null);
  const coreRef = useRef(null);
  const plateRefs = useRef([]);
  const labelRefs = useRef([]);
  const chapterRef = useRef(null);
  const chapterTitleRef = useRef(null);
  const chapterBodyRef = useRef(null);
  const tagsRef = useRef(null);
  const editorialRef = useRef(null);
  const scalerRef = useRef(null);
  const pulseRefs = useRef([]); // [{head, echoes:[]}]

  // Mutable animation state. Refs, not state: this all changes every frame and
  // must never trigger a React render.
  const m = useRef({
    tx: 0, ty: 0, cx: 0, cy: 0,
    isoCur: 0,
    autoRotationDeg: 0,
    pulseRotationDeg: 0,
    manualTarget: 0, manualCur: 0,
    hovering: false,
    lastFocusI: -1,
    t2: 0,
    lastTime: 0,
    chapter: -1,
  });

  /* ---- pointer: container-level only ------------------------------------- */
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage || reduced) return undefined;

    const onMove = (e) => {
      const r = stage.getBoundingClientRect();
      const nx = (e.clientX - r.left) / r.width - 0.5;
      const ny = (e.clientY - r.top) / r.height - 0.5;
      m.current.tx = nx * 14;
      m.current.ty = ny * -10;
      // Only once the ring has formed does the cursor steer it.
      if (m.current.t2 > 0.98) {
        m.current.manualTarget = nx * MANUAL_OFFSET_DEG;
        // Arm focus here as well as on `mouseenter`. A reader who scrolls the
        // ring into existence with the cursor already over the stage entered it
        // long before the ring formed, so `mouseenter` fired while t2 was still
        // 0 and was rejected by the guard below — leaving focus permanently
        // dead until they moved the cursor out of the hero and back in. A
        // `mousemove` is proof the pointer is inside, so this is the reliable
        // signal; `mouseleave` remains the only way out.
        m.current.hovering = true;
      }
    };
    const onEnter = () => {
      if (m.current.t2 > 0.98) m.current.hovering = true;
    };
    const onLeave = () => {
      m.current.hovering = false;
      m.current.manualTarget = 0;
      m.current.lastFocusI = -1;
    };

    stage.addEventListener('mousemove', onMove);
    stage.addEventListener('mouseenter', onEnter);
    stage.addEventListener('mouseleave', onLeave);
    return () => {
      stage.removeEventListener('mousemove', onMove);
      stage.removeEventListener('mouseenter', onEnter);
      stage.removeEventListener('mouseleave', onLeave);
    };
  }, [reduced]);

  /* ---- the single animation loop ----------------------------------------- */
  useEffect(() => {
    if (reduced) return undefined;

    let raf = 0;
    let running = true;

    // Stop all work while the hero is off-screen.
    const io = new IntersectionObserver(
      ([entry]) => {
        const next = entry.isIntersecting;
        if (next && !running) {
          running = true;
          m.current.lastTime = 0;
          raf = requestAnimationFrame(frame);
        }
        running = next;
      },
      { threshold: 0 },
    );
    if (stageRef.current) io.observe(stageRef.current);

    // The editorial column only renders at lg and up (see HeroSection); below
    // that there is no room for a genuine split and it would sit on the card.
    const editorialVisible = window.innerWidth >= 1024;

    const CHAPTERS = [
      ['One card.<br>Four judgments.', 'Everything the engine considers, before it decides anything.'],
      ['Four stages,<br>one <em>loop</em>.', 'Every dispute runs the same circuit, every time.'],
      ['Hover to <em>inspect</em><br>any stage.', 'The ring keeps running. Looking closer never stops it for long.'],
      ['Judgment<br><em>rendered</em>.', ''],
    ];

    function frame(t) {
      if (!running) return;
      const s = m.current;
      const dt = s.lastTime ? Math.min((t - s.lastTime) / 1000, 0.05) : 0;
      s.lastTime = t;

      /* -- scroll progress, straight from the track's live rect ------------ */
      const track = trackRef.current;
      let sT = 0;
      if (track) {
        const r = track.getBoundingClientRect();
        const H = track.offsetHeight - window.innerHeight;
        sT = H > 0 ? clamp(-r.top, 0, H) / H : 0;
      }

      const open = easeInOutQuad(clamp((sT - 0.05) / 0.28));
      const t2 = easeInOutQuad(clamp((sT - 0.36) / 0.24));
      s.t2 = t2;
      const exitAll = easeInOutQuad(clamp((sT - 0.9) / 0.1));

      /* -- rig: cursor parallax + isometric tilt as the stack opens --------
         Clamped strictly within rotateX(+/-18deg) rotateY(+/-10deg)
         rotateZ(+/-2deg): the luxury tilt should read as a gentle turn toward
         the light, never as a Rolodex flip. Combined with `backface-visibility:
         hidden` on `.layer`, this clamp is what keeps every plate's text facing
         a plausible camera angle rather than the ring's own full rotation (a
         separate, unclamped value -- see the per-plate composition below)
         somersaulting the whole rig. */
      s.cx += (s.tx - s.cx) * 0.06;
      s.cy += (s.ty - s.cy) * 0.06;
      const isoTarget = -16 * open + 8 * t2;
      s.isoCur += (isoTarget - s.isoCur) * 0.08;
      const rigRotY = clamp(s.cx, -10, 10);
      const rigRotX = clamp(s.cy + s.isoCur, -18, 18);
      const rigRotZ = clamp(s.cx * 0.15, -2, 2);
      if (rigRef.current) {
        rigRef.current.style.transform = `rotateX(${rigRotX}deg) rotateY(${rigRotY}deg) rotateZ(${rigRotZ}deg)`;
      }

      /* -- rotation ------------------------------------------------------- */
      s.manualCur += (s.manualTarget - s.manualCur) * 0.07;
      if (t2 > 0.985 && !s.hovering) s.autoRotationDeg += dt * RING_SPEED_DEG_S;

      /* -- the card fades out as the plates separate ----------------------- */
      if (cardRef.current) {
        cardRef.current.style.opacity = 1 - clamp(open * 1.6);
      }

      /* -- the resting tags and the editorial column both belong to the
         landing state, and clear as soon as the stack starts opening. The
         chapter copy (rendered underneath) takes the left column from here. */
      const restingFade = 1 - clamp(open * 2.4);

      /* -- the card sits mid-to-right while the editorial column holds the
         left half, then glides back to centre as the plates open, because the
         ring must be centred in the viewport to read as a ring. Only on wide
         screens: below lg the editorial column is hidden and the card owns the
         whole stage, so there is nothing to make room for. */
      // Left column occupies 40%, the beam the middle ~20%, so the card is
      // centred in the right 40% -- around 76% of the viewport, i.e. +26vw from
      // centre. Kept just under the geometric 80% so the satellite badges on
      // its right still have room before the viewport edge.
      const restShift = editorialVisible ? window.innerWidth * 0.26 : 0;
      const shiftX = restShift * (1 - clamp(open * 1.6));
      if (scalerRef.current) {
        scalerRef.current.style.transform = `translateX(${shiftX}px) scale(${cardWidth / 440})`;
      }
      if (tagsRef.current) {
        tagsRef.current.style.opacity = restingFade;
        // The satellites are anchored to the stage centre but describe the
        // CARD, so they must ride the same horizontal shift -- otherwise they
        // detach and drift over the editorial column as the card moves right.
        tagsRef.current.style.transform = `translateX(${shiftX}px) scale(${cardWidth / 440})`;
      }
      if (editorialRef.current) {
        editorialRef.current.style.opacity = restingFade;
        // Once faded it must not eat pointer events from the chapter text or
        // the plates behind it.
        editorialRef.current.style.visibility = restingFade < 0.02 ? 'hidden' : 'visible';
      }

      /* -- core heartbeat: in as the ring forms, out on the ascension ------ */
      if (coreRef.current) {
        coreRef.current.style.opacity = clamp((t2 - 0.15) / 0.35) * (1 - exitAll);
      }

      /* -- pulse trails ---------------------------------------------------- */
      // Deliberately NOT gated on `hovering`. The ring pauses when inspected,
      // but the pulses keep moving: the loop keeps running underneath even
      // while you look closer, which is what the product actually does.
      if (t2 > 0.985) s.pulseRotationDeg += dt * PULSE_SPEED_DEG_S;
      const pulseFade = clamp((t2 - 0.9) / 0.1) * (1 - exitAll);
      pulseRefs.current.forEach((grp, i) => {
        if (!grp) return;
        const base = i * (360 / PULSE_HEADS) + s.pulseRotationDeg;
        placeDot(grp.head, base, pulseFade, 1, radius);
        grp.echoes.forEach((echo, e) => {
          // Trailing behind the direction of travel, fading with distance.
          placeDot(echo, base - (e + 1) * PULSE_TAIL_GAP_DEG, pulseFade, 1 - (e + 1) / (PULSE_TAIL + 1), radius);
        });
      });

      /* -- pass 1: geometry, and which plate faces the camera most --------- */
      // A HYSTERESIS BIAS toward whichever plate is already focused. Without
      // it, two plates can sit within a fraction of a degree of tied facing
      // (the ring's rotation phase when hovering starts is effectively random,
      // since it comes from continuous auto-rotation), and the reader's plate
      // loses focus to its neighbour on the very next frame -- with no input
      // from the reader at all. The bias means a rival plate must clearly beat
      // the incumbent, not merely edge it out, before focus moves.
      const FOCUS_HYSTERESIS = 0.12;
      let bestI = 0;
      let bestFacing = -Infinity;
      const geom = [];
      for (let i = 0; i < PLATE_COUNT; i += 1) {
        const yOffStack = (i - (PLATE_COUNT - 1) / 2) * SPLIT_Y * open;
        const zOffStack = i * SPLIT_Z * open;
        const rotY = t2 * (THETA[i] + s.autoRotationDeg + s.manualCur);
        const curY = yOffStack * (1 - t2);
        const curZ = zOffStack * (1 - t2) + radius * t2;
        const facing = Math.cos((rotY * Math.PI) / 180);
        const biasedFacing = i === s.lastFocusI ? facing + FOCUS_HYSTERESIS : facing;
        if (biasedFacing > bestFacing) {
          bestFacing = biasedFacing;
          bestI = i;
        }
        geom.push({ rotY, curY, curZ, facing });
      }
      if (s.hovering && t2 > 0.98) s.lastFocusI = bestI;

      /* -- pass 2: write each plate ---------------------------------------- */
      for (let i = 0; i < PLATE_COUNT; i += 1) {
        const el = plateRefs.current[i];
        if (!el) continue;
        const g = geom[i];
        const isFocused = s.hovering && t2 > 0.98 && i === bestI;

        let curZ = g.curZ;
        if (isFocused) curZ += FOCUS_Z;
        let scaleF = isFocused ? FOCUS_SCALE : 1;

        let opacity;
        let blur;
        if (t2 <= 0.2) {
          // Still separating: plates reveal in sequence as the stack opens.
          opacity = clamp(open * 2.6 - i * 0.32);
          blur = 0;
        } else if (s.hovering && t2 > 0.98) {
          opacity = isFocused ? 1 : UNFOCUSED_OPACITY;
          blur = isFocused ? 0 : UNFOCUSED_BLUR;
        } else {
          // Depth read from facing angle.
          opacity = clamp(0.32 + 0.68 * Math.max(0, g.facing));
          blur = g.facing < 0.15 ? (0.15 - g.facing) * 8 : 0;
        }

        // Ascension: each plate departs slightly after the one before it, so
        // the four read as one graceful final beat rather than a simultaneous
        // disappearance.
        const exitP = easeInOutQuad(clamp((sT - (0.9 + i * EXIT_STAGGER)) / 0.09));
        const exitY = g.curY - exitP * 680;
        scaleF *= 1 - exitP * 0.28;
        opacity *= 1 - exitP;
        blur += exitP * 10;

        el.style.transform = `rotateY(${g.rotY}deg) translateY(${exitY}px) translateZ(${curZ}px) scale(${scaleF})`;
        el.style.opacity = opacity;
        el.style.filter = blur > 0 ? `blur(${blur}px)` : 'none';
        el.classList.toggle('is-focused', isFocused);
      }

      /* -- leader labels, only while the stack is open and not yet a ring --- */
      const labelsOn = open > 0.55 && t2 < 0.3;
      labelRefs.current.forEach((lb) => {
        if (lb) lb.style.opacity = labelsOn ? 1 : 0;
      });

      /* -- chapter copy ---------------------------------------------------- */
      if (chapterRef.current) {
        chapterRef.current.style.opacity =
          clamp((sT - 0.08) / 0.06) * (sT > 0.95 ? clamp((1 - sT) / 0.03) : 1);
      }
      const ci = sT < 0.34 ? 0 : sT < 0.6 ? 1 : sT < 0.9 ? 2 : 3;
      if (ci !== s.chapter) {
        s.chapter = ci;
        if (chapterTitleRef.current) chapterTitleRef.current.innerHTML = CHAPTERS[ci][0];
        if (chapterBodyRef.current) chapterBodyRef.current.textContent = CHAPTERS[ci][1];
      }

      raf = requestAnimationFrame(frame);
    }

    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      io.disconnect();
    };
  }, [radius, reduced, trackRef]);

  return (
    <div
      ref={stageRef}
      className="relative flex h-screen w-full items-center justify-center overflow-hidden"
      style={{ perspective: '1600px' }}
    >
      {/* The editorial left column -- the landing state's headline, subtitle
          and status ticker. Faded by the loop above; it owns no transform, so
          it never contends with the rig. */}
      <div ref={editorialRef} className="absolute inset-0 z-[9]">
        {/* Colossal grounding wordmark, sunk into the lower third so the bottom
            of the frame is never empty. Behind everything else in this layer. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 bottom-0 z-0 flex h-[46%] select-none items-center justify-center overflow-hidden"
        >
          <span
            className="font-display font-800 uppercase leading-none tracking-[-0.05em] text-white"
            style={{ fontSize: 'clamp(6rem, 21vw, 20rem)', opacity: 0.04 }}
          >
            ChargeGuard
          </span>
        </div>

        {/* The conduit, rising the full height of the stage in the gap between
            the copy and the card. */}
        <ChromaticNeuralBeam className="absolute inset-y-0 left-[44%] z-[1] hidden w-[15%] lg:block" />

        <HeroSection />
      </div>

      {/* Chapter copy, left column. */}
      <div
        ref={chapterRef}
        className="pointer-events-none absolute left-[6vw] top-1/2 z-[9] max-w-[340px] -translate-y-1/2"
        style={{ opacity: 0, transition: 'opacity 0.5s ease' }}
      >
        <h2
          ref={chapterTitleRef}
          className="mb-2.5 font-display font-600 leading-[1.15] tracking-[-0.02em] text-white"
          style={{ fontSize: 'clamp(1.4rem, 2.4vw, 1.9rem)' }}
        >
          One card.<br />Four judgments.
        </h2>
        <p ref={chapterBodyRef} className="text-[13px] leading-relaxed" style={{ color: '#8A94A6' }}>
          Everything the engine considers, before it decides anything.
        </p>
      </div>

      {/* Uniform scaler.

          The card's internal metrics (chip at top:78, engrave at bottom:96,
          9.5px labels) are fixed pixels tuned against a 440px card. Rendering
          the rig at a smaller width instead of scaling it makes those offsets
          collide — at 330px the chip lands on top of the engraved wordmark.
          So the rig is ALWAYS 440px and this wrapper scales the whole scene,
          which keeps every proportion and the ring geometry intact at any
          breakpoint. It carries preserve-3d so the 3D chain is not flattened. */}
      <div
        ref={scalerRef}
        style={{
          transform: `scale(${cardWidth / 440})`,
          transformStyle: 'preserve-3d',
        }}
      >
        {/* The rig. Explicit size — a transformed element is the containing
            block for its absolutely-positioned children, and a zero-sized rig
            would collapse every inset:0 plate inside it. */}
        <div
          ref={rigRef}
          className="relative"
          style={{ width: 440, aspectRatio: '1.586', transformStyle: 'preserve-3d' }}
        >
        <div className="float-wrap">
          {PLATES.map((plate, i) => (
            <ExplodedPlate
              key={plate.n}
              ref={(el) => {
                plateRefs.current[i] = el;
              }}
              plate={plate}
              index={i}
            />
          ))}

          <Card innerRef={cardRef} />

          {/* Core heartbeat with its two sonar rings. */}
          <div ref={coreRef} className="core-wrap">
            <div className="sonar" />
            <div className="sonar sonar--2" />
            <div className="core-light" />
          </div>

          {/* Comet-tail pulse groups: one head plus three fading echoes each. */}
          <div>
            {Array.from({ length: PULSE_HEADS }).map((_, i) => (
              <div key={i}>
                <div
                  className="pulse-dot pulse-head"
                  ref={(el) => {
                    if (!pulseRefs.current[i]) pulseRefs.current[i] = { head: null, echoes: [] };
                    pulseRefs.current[i].head = el;
                  }}
                />
                {Array.from({ length: PULSE_TAIL }).map((__, e) => (
                  <div
                    key={e}
                    className="pulse-dot pulse-echo"
                    ref={(el) => {
                      if (!pulseRefs.current[i]) pulseRefs.current[i] = { head: null, echoes: [] };
                      pulseRefs.current[i].echoes[e] = el;
                    }}
                  />
                ))}
              </div>
            ))}
          </div>
          </div>
        </div>
      </div>

      {/* The resting tags.

          Deliberately OUTSIDE the rig. Inside it they share the rig's
          `preserve-3d` context, where the card face sits at translateZ(9px) and
          therefore occludes anything at z=0 — the tags were being clipped by
          the card rather than floating around it. Out here they are an ordinary
          2D layer painted above, and normal z-index applies. They are centred on
          the stage, which is where the card is, so their offsets are unchanged. */}
      {tagCount > 0 && (
        <div ref={tagsRef} className="pointer-events-none absolute inset-0 z-[8]">
          <FloatingTags reduced={reduced} count={tagCount} />
        </div>
      )}

      {/* Leader labels for the separated plates. */}
      {PLATES.map((plate, i) => (
        <div
          key={plate.n}
          ref={(el) => {
            labelRefs.current[i] = el;
          }}
          className="pointer-events-none absolute right-[6vw] z-[9] whitespace-nowrap font-mono"
          style={{ opacity: 0, transition: 'opacity 0.35s ease', top: `${26 + i * 13}%` }}
        >
          <span className="block text-[9px] tracking-[0.14em]" style={{ color: '#5A6577' }}>
            LAYER {plate.n}
          </span>
          <span className="text-[12px]" style={{ color: '#D7DCE5' }}>
            {plate.overview}
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * Place one pulse dot on the ring.
 *
 * Same `rotateY … translateZ` construction as the plates, so the dots ride the
 * exact circle the plates sit on. Dots on the far side dim rather than
 * disappearing, which keeps the ring reading as a solid loop.
 */
function placeDot(el, angleDeg, groupFade, echoFade, radius) {
  if (!el) return;
  el.style.transform = `rotateY(${angleDeg}deg) translateZ(${radius}px)`;
  const facing = Math.cos((angleDeg * Math.PI) / 180);
  el.style.opacity = groupFade * echoFade * clamp(0.2 + 0.8 * Math.max(0, facing));
}
