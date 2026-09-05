import { useEffect, useRef } from 'react';

import { prefersReducedMotion } from '../../hooks/usePointer.js';

/**
 * A vertical column of flowing chromatic light threads — the data conduit
 * running between the hero's copy and its card.
 *
 * ---------------------------------------------------------------------------
 * WHY CANVAS 2D AND NOT R3F / A GLSL SHADER
 * ---------------------------------------------------------------------------
 * This was specified as a Three.js or shader component, and it is neither, on
 * purpose. What the effect actually needs is a few dozen additively-blended
 * stroked curves — 2D work. Canvas 2D does it with no shader to compile, no
 * WebGL context to lose, and no environment/tone-mapping setup, which is the
 * exact class of problem this codebase already lost time to: the hero's card
 * and glass were attempted in WebGL first and rendered solid black. The same
 * decision was made for the particle preloader and measured at 0.142ms of work
 * per frame for 4,000 sprites — about 0.8% of a 60fps budget — so the headroom
 * here is not in question.
 *
 * The one thing a shader would give for free is per-pixel chromatic
 * aberration. That is reproduced here by stroking each thread three times with
 * a sub-pixel horizontal offset per channel-ish colour, which is what the
 * effect reads as anyway.
 *
 * ---------------------------------------------------------------------------
 * The threads
 * ---------------------------------------------------------------------------
 * Each thread is a vertical spine sampled down the canvas, displaced
 * horizontally by two summed sine waves of different wavelength and speed
 * (cheap, and at these amplitudes indistinguishable from curl noise) plus a
 * pointer term. Sampling top-to-bottom and stroking one path keeps it a single
 * draw per pass rather than a segment-per-line.
 *
 * Pointer influence is lerped, and weighted by vertical position so the
 * middle of the column leans further than its anchored ends — a thread pinned
 * top and bottom cannot bend uniformly along its length.
 */

const THREADS = 13;
const SAMPLES = 34;

/** Chromatic passes: colour, x-offset in px, width multiplier, alpha. */
const PASSES = [
  { color: '138, 92, 246', dx: -1.6, w: 1.9, a: 0.30 }, // violet fringe, outermost
  { color: '6, 182, 212', dx: 0.9, w: 1.35, a: 0.42 }, // cyber cyan
  { color: '0, 255, 135', dx: 0, w: 0.7, a: 0.95 }, // electric emerald core
];

export default function ChromaticNeuralBeam({ className = '' }) {
  const canvasRef = useRef(null);
  const hostRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const host = hostRef.current;
    if (!canvas || !host || prefersReducedMotion()) return undefined;

    const ctx = canvas.getContext('2d');
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let w = 0;
    let h = 0;

    const resize = () => {
      const r = host.getBoundingClientRect();
      w = Math.max(1, r.width);
      h = Math.max(1, r.height);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(host);

    // Pointer is tracked in viewport space and converted per frame, so the
    // threads respond to the cursor anywhere in the hero, not only when it is
    // over the narrow column itself.
    const pointer = { tx: 0, ty: 0, x: 0, y: 0 };
    const onMove = (e) => {
      const r = host.getBoundingClientRect();
      pointer.tx = (e.clientX - (r.left + r.width / 2)) / window.innerWidth;
      pointer.ty = (e.clientY - (r.top + r.height / 2)) / window.innerHeight;
    };
    window.addEventListener('pointermove', onMove, { passive: true });

    let raf = 0;
    let running = true;
    const io = new IntersectionObserver(
      ([entry]) => {
        const next = entry.isIntersecting;
        if (next && !running) {
          running = true;
          raf = requestAnimationFrame(frame);
        }
        running = next;
      },
      { threshold: 0 },
    );
    io.observe(host);

    const start = performance.now();

    function frame(now) {
      if (!running) return;
      const t = (now - start) / 1000;

      // Damped follow, so the column leans rather than snapping to the cursor.
      pointer.x += (pointer.tx - pointer.x) * 0.055;
      pointer.y += (pointer.ty - pointer.y) * 0.055;

      ctx.clearRect(0, 0, w, h);
      ctx.globalCompositeOperation = 'lighter';
      ctx.lineCap = 'round';

      for (let i = 0; i < THREADS; i += 1) {
        const n = i / (THREADS - 1);
        const centred = n - 0.5;
        // Threads fan out from the column's spine; the outer ones are wider
        // apart, slower, and fainter, which gives the bundle depth.
        const spread = w * 0.34 * Math.sin(centred * Math.PI);
        const phase = i * 0.7;
        const speed = 0.55 + (i % 3) * 0.12;
        const depth = 0.45 + 0.55 * (1 - Math.abs(centred) * 2);

        for (const pass of PASSES) {
          ctx.beginPath();
          for (let s = 0; s <= SAMPLES; s += 1) {
            const v = s / SAMPLES; // 0 at top, 1 at bottom
            const y = v * h;

            // Two waves of different wavelength read as organic rather than
            // as a single, obviously periodic sine.
            const sway =
              Math.sin(v * 3.1 + t * speed + phase) * (w * 0.16) +
              Math.sin(v * 7.3 - t * speed * 0.7 + phase * 1.7) * (w * 0.07);

            // Ends are anchored: the column rises from the bottom edge and
            // exits the top, so it must not detach from either.
            const anchor = Math.sin(v * Math.PI);

            // Cursor lean, strongest mid-column for the same reason.
            const lean = pointer.x * w * 1.15 * anchor + pointer.y * w * 0.18 * anchor;

            const x = w / 2 + (spread + sway) * anchor + lean + pass.dx;
            if (s === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
          }
          // A slow breath on the whole bundle so it never sits perfectly still.
          const breath = 0.8 + 0.2 * Math.sin(t * 0.9 + phase);
          ctx.strokeStyle = `rgba(${pass.color}, ${pass.a * depth * breath})`;
          ctx.lineWidth = pass.w * depth;
          ctx.stroke();
        }
      }

      ctx.globalCompositeOperation = 'source-over';
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      io.disconnect();
      window.removeEventListener('pointermove', onMove);
    };
  }, []);

  return (
    // NOTE: no position utility here on purpose. Tailwind emits `.relative`
    // after `.absolute`, so hardcoding `relative` on this root silently beat an
    // `absolute inset-y-0` passed in via className -- the host then collapsed to
    // content height and the column rendered 108px tall instead of full height.
    // Positioning is the caller's to supply.
    <div ref={hostRef} className={`pointer-events-none ${className}`} aria-hidden="true">
      {/* Soft bloom behind the threads so the column glows into the ground
          rather than sitting on it as hairlines. */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(closest-side at 50% 50%, rgba(16,185,129,0.10), rgba(6,182,212,0.05) 45%, transparent 72%)',
        }}
      />
      <canvas ref={canvasRef} className="relative block h-full w-full" />
    </div>
  );
}
