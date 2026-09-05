import { useEffect, useRef, useState } from 'react';

import { prefersReducedMotion } from '../hooks/usePointer.js';

/**
 * ParticleIntroLoader -- a 3-phase cinematic micro-particle preloader on a
 * single 2D `<canvas>`.
 *
 * WHY CANVAS 2D, NOT WEBGL. ~4,000 micro-particles is comfortably inside a
 * single 2D context's budget once the two classic traps are avoided:
 * per-particle `arc()` + `shadowBlur` (re-rasterises a blur every draw call)
 * and per-frame allocation (GC stalls read as dropped frames). Every particle
 * here is a `drawImage` of one of four pre-rendered glow sprites, and all
 * particle state lives in flat `Float32Array`s. No shader compilation, no
 * context-loss surface, nothing that can render solid black.
 *
 * MICRO-PARTICLES, NOT BLOBS. Core radius is 0.8-1.6px. The sprite gradient is
 * deliberately front-loaded -- a near-white core inside the first 18% of the
 * radius, then a fast fall-off -- so each particle reads as a hard sparkle
 * with a faint halo rather than a soft bubble. Drawing a *small* sprite box is
 * what keeps it crisp: a large box with a soft gradient is exactly the "chunky
 * bubble" look this replaces.
 *
 * CURL NOISE, GENUINELY. Phase 1 advects particles along the curl of a scalar
 * potential field: v = (dPsi/dy, -dPsi/dx). Taking the curl makes the field
 * divergence-free, which is the property that matters -- an incompressible
 * field has no sources or sinks, so particles never pile into a point or drain
 * out of a region; they orbit and shear past each other, which is what reads
 * as turbulent suspense. The potential itself is cheap value-noise (hashed
 * lattice + smoothstep interpolation, animated on a third axis) rather than
 * true simplex: at these advection speeds the two are visually
 * indistinguishable, and this needs no dependency.
 *
 * THE THREE PHASES, run as one continuous simulation with ~260ms smoothstep
 * crossfades at each boundary, never a hard switch:
 *
 *   1. VORTEX    0.0s-2.2s   curl-noise advection, loosely tethered so the
 *                            swarm stays on screen.
 *   2. ASSEMBLE  2.2s-3.4s   critically-damped spring onto letterform targets
 *                            sampled from a rasterised "ChargeGuard.AI".
 *   3. HOLD      3.4s-4.8s   spring holds; Brownian micro-jitter and a slow
 *                            light-sweep keep the word alive, then
 *      IMPLODE    4.8s-5.4s  the spring retargets to one point near the hero
 *                            card's chip and particles fade as they arrive.
 *
 * THE CONVERGENCE POINT IS APPROXIMATE. This loader finishes before the hero
 * card exists in the DOM -- that is what a preloader is -- so it has no
 * element to measure. The defaults approximate the chip on a centred 440px
 * card; pass real fractions if the caller knows better.
 *
 * @param {object} props
 * @param {() => void} props.onComplete Fired once, when the implosion ends or
 *   the reader skips. The caller unmounts this component; it does not unmount
 *   itself.
 * @param {number} [props.convergeXFrac=0.42] Implosion target x, viewport fraction.
 * @param {number} [props.convergeYFrac=0.52] Implosion target y, viewport fraction.
 * @param {boolean} [props.showSkip=true] Render the skip affordance.
 */
export default function ParticleIntroLoader({
  onComplete,
  convergeXFrac = 0.42,
  convergeYFrac = 0.52,
  showSkip = true,
}) {
  const canvasRef = useRef(null);
  const hudRef = useRef(null);
  const skipRequested = useRef(false);
  const doneRef = useRef(false);
  const [fadingOut, setFadingOut] = useState(false);

  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    // Reduced motion: there is nothing here a reader needs to see, only an
    // entrance they may not want to sit through.
    if (prefersReducedMotion()) {
      onCompleteRef.current?.();
      return undefined;
    }

    const ctx = canvas.getContext('2d', { alpha: false });

    /* ------------------------------------------------------------------ */
    /* Timeline (ms)                                                       */
    /* ------------------------------------------------------------------ */
    const T_VORTEX_END = 2200;
    const T_ASSEMBLE_END = 3400;
    const T_HOLD_END = 4800;
    const T_END = 5400;
    const CROSSFADE = 260;

    /* ------------------------------------------------------------------ */
    /* Sizing                                                              */
    /* ------------------------------------------------------------------ */
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let width = window.innerWidth;
    let height = window.innerHeight;

    function sizeCanvas() {
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    sizeCanvas();

    // 4,000 on desktop; fewer on small screens, where the fill rate is lower
    // and the word is physically smaller anyway.
    const N = width < 768 ? 1800 : 4000;

    /* ------------------------------------------------------------------ */
    /* Glow sprites. Built once; the whole render loop is drawImage calls.  */
    /* The stop at 0.18 is what makes a micro-particle instead of a blob.   */
    /* ------------------------------------------------------------------ */
    const PALETTE = [
      '#00FF87', // electric neon emerald
      '#62C6D7', // brand cyan
      '#06B6D4', // icy cyber cyan
      '#FFFFFF', // titanium white sparkle core
    ];
    const SPRITE_PX = 32;

    function makeSprite(hex) {
      const s = document.createElement('canvas');
      s.width = SPRITE_PX;
      s.height = SPRITE_PX;
      const g = s.getContext('2d');
      const r = SPRITE_PX / 2;
      const grad = g.createRadialGradient(r, r, 0, r, r, r);
      grad.addColorStop(0, '#FFFFFFFF');
      grad.addColorStop(0.18, `${hex}FF`);
      grad.addColorStop(0.42, `${hex}66`);
      grad.addColorStop(1, `${hex}00`);
      g.fillStyle = grad;
      g.fillRect(0, 0, SPRITE_PX, SPRITE_PX);
      return s;
    }
    const sprites = PALETTE.map(makeSprite);

    /* ------------------------------------------------------------------ */
    /* Curl noise.                                                         */
    /* ------------------------------------------------------------------ */
    // Deterministic 3D hash -> [0,1). Integer-mixed rather than Math.random
    // so the field is stable in space and only animates on the z axis.
    function hash3(ix, iy, iz) {
      let h = ix * 374761393 + iy * 668265263 + iz * 1442695040;
      h = (h ^ (h >> 13)) * 1274126177;
      return ((h ^ (h >> 16)) >>> 0) / 4294967296;
    }
    const fade = (t) => t * t * (3 - 2 * t);

    /** Value noise in 3D, trilinearly interpolated with a smoothstep fade. */
    function valueNoise(x, y, z) {
      const xi = Math.floor(x);
      const yi = Math.floor(y);
      const zi = Math.floor(z);
      const xf = fade(x - xi);
      const yf = fade(y - yi);
      const zf = fade(z - zi);
      let acc = 0;
      for (let dz = 0; dz <= 1; dz += 1) {
        const wz = dz ? zf : 1 - zf;
        for (let dy = 0; dy <= 1; dy += 1) {
          const wy = dy ? yf : 1 - yf;
          for (let dx = 0; dx <= 1; dx += 1) {
            const wx = dx ? xf : 1 - xf;
            acc += hash3(xi + dx, yi + dy, zi + dz) * wx * wy * wz;
          }
        }
      }
      return acc * 2 - 1;
    }

    // Two octaves is enough to get large sweeping vortices with finer shear
    // riding on top; a third costs 50% more noise calls for very little.
    function potential(x, y, z) {
      return valueNoise(x, y, z) + 0.5 * valueNoise(x * 2.1, y * 2.1, z * 1.3);
    }

    const NOISE_SCALE = 0.0016; // world px -> noise space
    const EPS = 1.0;

    /**
     * Curl of the scalar potential, giving a divergence-free 2D velocity.
     * Divergence-free is the whole point: particles orbit and shear instead of
     * collapsing into sinks, which is what makes it read as turbulence.
     */
    function curl(x, y, z, out) {
      const nx = x * NOISE_SCALE;
      const ny = y * NOISE_SCALE;
      const e = EPS * NOISE_SCALE;
      const dPsiDy = (potential(nx, ny + e, z) - potential(nx, ny - e, z)) / (2 * e);
      const dPsiDx = (potential(nx + e, ny, z) - potential(nx - e, ny, z)) / (2 * e);
      out[0] = dPsiDy;
      out[1] = -dPsiDx;
    }

    /* ------------------------------------------------------------------ */
    /* Letterform targets, sampled from a rasterised wordmark.             */
    /* ------------------------------------------------------------------ */
    const WORD = 'ChargeGuard.AI';
    const targetX = new Float32Array(N);
    const targetY = new Float32Array(N);
    const textBounds = { current: null };

    function sampleWordTargets() {
      const TW = 1800;
      const TH = 400;
      const off = document.createElement('canvas');
      off.width = TW;
      off.height = TH;
      const octx = off.getContext('2d');
      octx.clearRect(0, 0, TW, TH);
      octx.fillStyle = '#fff';
      octx.textAlign = 'center';
      octx.textBaseline = 'middle';
      octx.font = "800 190px 'Plus Jakarta Sans', 'Inter', system-ui, sans-serif";
      octx.fillText(WORD, TW / 2, TH / 2);

      const { data } = octx.getImageData(0, 0, TW, TH);
      const pts = [];
      let minX = TW;
      let maxX = 0;
      let minY = TH;
      let maxY = 0;
      // step 2 gives a dense point pool; with 4,000 particles drawing from it
      // the letterforms stay solid rather than dotted.
      for (let y = 0; y < TH; y += 2) {
        for (let x = 0; x < TW; x += 2) {
          if (data[(y * TW + x) * 4 + 3] > 128) {
            pts.push(x, y);
            if (x < minX) minX = x;
            if (x > maxX) maxX = x;
            if (y < minY) minY = y;
            if (y > maxY) maxY = y;
          }
        }
      }
      if (pts.length < 8) return false;

      const glyphW = maxX - minX || 1;
      const glyphH = maxY - minY || 1;
      const cx = (minX + maxX) / 2;
      const cy = (minY + maxY) / 2;
      const desiredW = Math.min(width * 0.66, 1040);
      const scale = desiredW / glyphW;
      textBounds.current = {
        left: width / 2 - desiredW / 2,
        right: width / 2 + desiredW / 2,
        top: height / 2 - (glyphH * scale) / 2,
        bottom: height / 2 + (glyphH * scale) / 2,
      };

      const pairs = pts.length / 2;
      for (let i = 0; i < N; i += 1) {
        const p = Math.floor(Math.random() * pairs) * 2;
        targetX[i] = width / 2 + (pts[p] - cx) * scale;
        targetY[i] = height / 2 + (pts[p + 1] - cy) * scale;
      }
      return true;
    }

    let haveTargets = sampleWordTargets();
    if (!haveTargets && document.fonts?.ready) {
      document.fonts.ready.then(() => {
        haveTargets = sampleWordTargets();
      });
    }

    /* ------------------------------------------------------------------ */
    /* Particle state -- flat typed arrays, contiguous memory.             */
    /* ------------------------------------------------------------------ */
    const px = new Float32Array(N);
    const py = new Float32Array(N);
    const vx = new Float32Array(N);
    const vy = new Float32Array(N);
    const anchorX = new Float32Array(N);
    const anchorY = new Float32Array(N);
    const seed = new Float32Array(N);
    const radius = new Float32Array(N);
    const spriteIndex = new Uint8Array(N);
    const zOff = new Float32Array(N); // per-particle slice of the noise field's 3rd axis

    for (let i = 0; i < N; i += 1) {
      px[i] = Math.random() * width;
      py[i] = Math.random() * height;
      anchorX[i] = px[i];
      anchorY[i] = py[i];
      seed[i] = Math.random() * Math.PI * 2;
      // Micro-particles: 0.8px to 1.6px core.
      radius[i] = 0.8 + Math.random() * 0.8;
      zOff[i] = Math.random() * 4;
      const r = Math.random();
      spriteIndex[i] = r < 0.34 ? 0 : r < 0.68 ? 1 : r < 0.9 ? 2 : 3;
    }

    const smooth = (t) => {
      const c = t < 0 ? 0 : t > 1 ? 1 : t;
      return c * c * (3 - 2 * c);
    };

    /* ------------------------------------------------------------------ */
    /* Loop                                                                */
    /* ------------------------------------------------------------------ */
    const HUD_PREFIX = 'INITIALIZING SENTINEL PROTOCOL... [';
    const start = performance.now();
    let last = start;
    let raf = 0;
    let skipStart = null;
    const curlOut = [0, 0];

    function finish() {
      if (doneRef.current) return;
      doneRef.current = true;
      onCompleteRef.current?.();
    }

    function frame(now) {
      // A skip fast-forwards the clock into the implosion rather than cutting
      // to onComplete, so the hand-off still reads as "the word flew to the
      // chip" even when a developer is hammering Esc.
      let elapsed = now - start;
      if (skipRequested.current) {
        if (skipStart === null) skipStart = now;
        const k = Math.min(1, (now - skipStart) / 340);
        elapsed = T_HOLD_END + k * (T_END - T_HOLD_END);
        if (k >= 1) elapsed = T_END + 1;
      }

      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;

      if (elapsed >= T_END) {
        raf = 0;
        finish();
        return;
      }

      const wVortex = 1 - smooth((elapsed - (T_VORTEX_END - CROSSFADE)) / CROSSFADE);
      const wAssemble =
        smooth((elapsed - (T_VORTEX_END - CROSSFADE)) / CROSSFADE) *
        (1 - smooth((elapsed - T_HOLD_END) / CROSSFADE));
      const wImplode = smooth((elapsed - T_HOLD_END) / CROSSFADE);
      const holdT = Math.max(0, elapsed - T_ASSEMBLE_END);

      const t = elapsed / 1000;
      const cx = width * convergeXFrac;
      const cy = height * convergeYFrac;
      const globalAlpha = 1 - smooth((elapsed - (T_END - 460)) / 460);

      ctx.fillStyle = '#0B1720';
      ctx.fillRect(0, 0, width, height);
      ctx.globalCompositeOperation = 'lighter';

      for (let i = 0; i < N; i += 1) {
        // -- VORTEX: curl advection + a weak tether so the swarm stays framed.
        let ax = 0;
        let ay = 0;
        if (wVortex > 0.001) {
          curl(px[i], py[i], t * 0.22 + zOff[i], curlOut);
          const tetherX = (anchorX[i] - px[i]) * 0.35;
          const tetherY = (anchorY[i] - py[i]) * 0.35;
          ax += (curlOut[0] * 900 + tetherX) * wVortex;
          ay += (curlOut[1] * 900 + tetherY) * wVortex;
        }

        // -- ASSEMBLE / HOLD: critically-damped spring onto the letterform.
        const K = 52;
        const D = 9.5;
        if (wAssemble > 0.001) {
          const tx = haveTargets ? targetX[i] : px[i];
          const ty = haveTargets ? targetY[i] : py[i];
          ax += ((tx - px[i]) * K - vx[i] * D) * wAssemble;
          ay += ((ty - py[i]) * K - vy[i] * D) * wAssemble;
        }

        // -- IMPLODE: same spring, one shared target near the hero chip.
        if (wImplode > 0.001) {
          ax += ((cx - px[i]) * K * 1.5 - vx[i] * D) * wImplode;
          ay += ((cy - py[i]) * K * 1.5 - vy[i] * D) * wImplode;
        }

        vx[i] += ax * dt;
        vy[i] += ay * dt;
        vx[i] *= 0.968;
        vy[i] *= 0.968;
        px[i] += vx[i] * dt;
        py[i] += vy[i] * dt;

        // -- HOLD jitter, applied to the DRAWN position only so it can never
        // integrate into the physics and drift the formation apart.
        let jx = 0;
        let jy = 0;
        if (wAssemble > 0.85 && wImplode < 0.02) {
          jx = Math.sin(holdT * 0.011 + seed[i] * 7.3) * 0.55;
          jy = Math.cos(holdT * 0.013 + seed[i] * 5.1) * 0.55;
        }

        // Micro-particle draw: box is ~5x the core radius, so a 1.2px core
        // renders as a ~6px sprite that is mostly transparent halo.
        const rad = radius[i] * (wImplode > 0.5 ? 1 - (wImplode - 0.5) * 0.5 : 1);
        const box = rad * 5.2;
        ctx.globalAlpha = globalAlpha * 0.92;
        ctx.drawImage(
          sprites[spriteIndex[i]],
          px[i] + jx - box / 2,
          py[i] + jy - box / 2,
          box,
          box,
        );
      }

      ctx.globalCompositeOperation = 'source-over';
      ctx.globalAlpha = 1;

      // -- Light sweep across the held word.
      if (wAssemble > 0.9 && wImplode < 0.02 && textBounds.current) {
        const b = textBounds.current;
        const sweepT = (holdT % 1500) / 1500;
        const sx = b.left - 140 + sweepT * (b.right - b.left + 280);
        const grad = ctx.createLinearGradient(sx - 100, 0, sx + 100, 0);
        grad.addColorStop(0, 'rgba(255,255,255,0)');
        grad.addColorStop(0.5, 'rgba(190,255,230,0.09)');
        grad.addColorStop(1, 'rgba(255,255,255,0)');
        ctx.globalCompositeOperation = 'lighter';
        ctx.fillStyle = grad;
        ctx.fillRect(0, b.top - 24, width, b.bottom - b.top + 48);
        ctx.globalCompositeOperation = 'source-over';
      }

      // -- HUD, phase 1 only. DOM text written imperatively: a per-frame React
      // state update here would re-render the tree 60 times a second.
      if (hudRef.current) {
        if (elapsed < T_VORTEX_END + 220) {
          const pct = Math.round(24 + 76 * smooth(elapsed / T_VORTEX_END));
          hudRef.current.textContent = `${HUD_PREFIX}${pct}% -> 100%]`;
          hudRef.current.style.opacity = String(1 - smooth((elapsed - T_VORTEX_END) / 220));
        } else {
          hudRef.current.style.opacity = '0';
        }
      }

      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);

    function onResize() {
      sizeCanvas();
      haveTargets = sampleWordTargets();
    }
    window.addEventListener('resize', onResize);

    function requestSkip() {
      if (skipRequested.current) return;
      skipRequested.current = true;
      setFadingOut(true);
    }
    function onKey(e) {
      if (e.key === 'Escape') requestSkip();
    }
    window.addEventListener('keydown', onKey);
    canvas.requestSkip = requestSkip;

    return () => {
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('keydown', onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      role="presentation"
      aria-hidden="true"
      className="fixed inset-0 z-[999]"
      style={{
        background: '#0B1720',
        opacity: fadingOut ? 0.4 : 1,
        transition: 'opacity 0.3s ease',
      }}
    >
      <canvas ref={canvasRef} className="block h-full w-full" />

      <div
        ref={hudRef}
        className="pointer-events-none absolute right-5 top-5 select-none font-mono text-[11px] tabular-nums tracking-[0.08em]"
        style={{
          color: 'rgba(0,255,135,0.85)',
          textShadow: '0 0 12px rgba(0,255,135,0.45)',
          opacity: 0,
        }}
      >
        INITIALIZING SENTINEL PROTOCOL... [24% -&gt; 100%]
      </div>

      {showSkip && (
        <button
          type="button"
          aria-hidden="true"
          tabIndex={-1}
          onClick={() => canvasRef.current?.requestSkip?.()}
          className="tap-44 absolute bottom-5 right-5 rounded-md px-2 py-1 font-mono text-[10px] tracking-[0.08em] transition-colors"
          style={{ color: 'rgba(148,163,184,0.55)' }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = 'rgba(226,232,240,0.9)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = 'rgba(148,163,184,0.55)';
          }}
        >
          SKIP INTRO (ESC)
        </button>
      )}
    </div>
  );
}
