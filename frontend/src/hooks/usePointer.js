import { useEffect, useRef } from 'react';

/**
 * Track normalised pointer position without triggering React re-renders.
 *
 * Returns a ref, not state, and that is the entire point. The hero scene reads
 * the pointer inside a `useFrame` callback running at 60fps; storing the
 * position in state would re-render the React tree on every mouse move and
 * fight the render loop for the main thread. A ref lets the imperative
 * animation read the latest value while React stays completely idle.
 *
 * Coordinates are normalised to [-1, 1] with the origin at the viewport centre,
 * which is the convention three.js NDC space uses, so the scene can consume
 * them without a conversion step.
 *
 * @returns {{current: {x: number, y: number, active: boolean}}}
 */
export function usePointer() {
  const pointer = useRef({ x: 0, y: 0, active: false });

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;

    const handleMove = (event) => {
      pointer.current.x = (event.clientX / window.innerWidth) * 2 - 1;
      pointer.current.y = -((event.clientY / window.innerHeight) * 2 - 1);
      pointer.current.active = true;
    };

    const handleLeave = () => {
      pointer.current.active = false;
    };

    // Touch is handled too, but a touch is a discrete tap rather than a
    // continuous hover: the displacement effect reads as a ripple instead of a
    // trailing repulsion, which is the right behaviour on a phone.
    const handleTouch = (event) => {
      const touch = event.touches[0];
      if (!touch) return;
      pointer.current.x = (touch.clientX / window.innerWidth) * 2 - 1;
      pointer.current.y = -((touch.clientY / window.innerHeight) * 2 - 1);
      pointer.current.active = true;
    };

    window.addEventListener('pointermove', handleMove, { passive: true });
    window.addEventListener('pointerleave', handleLeave, { passive: true });
    window.addEventListener('touchmove', handleTouch, { passive: true });
    window.addEventListener('touchend', handleLeave, { passive: true });

    return () => {
      window.removeEventListener('pointermove', handleMove);
      window.removeEventListener('pointerleave', handleLeave);
      window.removeEventListener('touchmove', handleTouch);
      window.removeEventListener('touchend', handleLeave);
    };
  }, []);

  return pointer;
}

/**
 * True when the reader has asked for reduced motion.
 *
 * Read synchronously rather than through state because every consumer needs it
 * at mount time to decide whether to start an animation at all, and a value
 * that arrives one render later would mean the animation briefly runs anyway.
 *
 * @returns {boolean}
 */
export function prefersReducedMotion() {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
