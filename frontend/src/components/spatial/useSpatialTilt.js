import { useEffect, useRef } from 'react';

import { prefersReducedMotion } from '../../hooks/usePointer.js';

/**
 * A small, self-contained 3D tilt rig for the post-hero spatial sections.
 *
 * Deliberately NOT Stage.jsx's loop: these panels are independent, scroll into
 * view one at a time, and don't need to share a single frame budget with the
 * hero. Each gets its own tiny rAF, gated by IntersectionObserver so an
 * off-screen panel costs nothing, and the ambient pointer tilt is clamped to
 * the same luxury bounds as the hero rig -- rotateX +/-18deg, rotateY
 * +/-10deg -- so the whole page reads as one calibrated system rather than
 * each section improvising its own feel. A continuous `spin` (deg/s) is
 * layered on top of, not inside, that clamp: it is meant to complete full
 * rotations, the way the hero's formed ring does, so it is never restricted
 * to the ambient tilt's small range.
 *
 * @param {{ spin?: number }} [opts] `spin`: continuous auto-rotation in
 *   degrees per second; 0 (default) means the rig only responds to the cursor.
 * @returns {React.RefObject<HTMLElement>} attach to the element that should
 *   receive pointer tracking; the returned rig element (`.spin-rig` child, or
 *   the element itself if it declares `data-spatial-rig`) gets the transform.
 */
export function useSpatialTilt({ spin = 0 } = {}) {
  const containerRef = useRef(null);
  const rigRef = useRef(null);
  const state = useRef({ tx: 0, ty: 0, cx: 0, cy: 0, spinDeg: 0, last: 0 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el || prefersReducedMotion()) return undefined;

    const onMove = (e) => {
      const r = el.getBoundingClientRect();
      state.current.tx = ((e.clientX - r.left) / r.width - 0.5) * 20;
      state.current.ty = ((e.clientY - r.top) / r.height - 0.5) * -28;
    };
    const onLeave = () => {
      state.current.tx = 0;
      state.current.ty = 0;
    };
    el.addEventListener('mousemove', onMove);
    el.addEventListener('mouseleave', onLeave);

    let raf = 0;
    let running = true;
    const io = new IntersectionObserver(
      ([entry]) => {
        running = entry.isIntersecting;
        if (running) {
          state.current.last = 0;
          raf = requestAnimationFrame(frame);
        }
      },
      { threshold: 0.05 },
    );
    io.observe(el);

    function frame(t) {
      if (!running) return;
      const s = state.current;
      const dt = s.last ? Math.min((t - s.last) / 1000, 0.05) : 0;
      s.last = t;
      s.cx += (s.tx - s.cx) * 0.07;
      s.cy += (s.ty - s.cy) * 0.07;
      s.spinDeg = (s.spinDeg + spin * dt) % 360;

      const rotX = Math.max(-18, Math.min(18, s.cy));
      const rotY = s.spinDeg + Math.max(-10, Math.min(10, s.cx));

      if (rigRef.current) {
        rigRef.current.style.transform = `rotateX(${rotX}deg) rotateY(${rotY}deg)`;
      }
      raf = requestAnimationFrame(frame);
    }

    return () => {
      cancelAnimationFrame(raf);
      io.disconnect();
      el.removeEventListener('mousemove', onMove);
      el.removeEventListener('mouseleave', onLeave);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spin]);

  return { containerRef, rigRef };
}
