import { useEffect, useState } from 'react';

/**
 * Track which section is currently in view.
 *
 * Uses IntersectionObserver rather than reading `scrollY` on every scroll event.
 * The scroll-math approach requires measuring every section's offset, recomputing
 * on resize, and running work on a high-frequency event that blocks the main
 * thread. IntersectionObserver does the same job off the main thread, stays
 * correct when content reflows, and costs nothing while the page is idle.
 *
 * The `rootMargin` biases the detection band toward the upper-middle of the
 * viewport. Without it, a tall section only registers once its top edge is
 * nearly off-screen, and the nav indicator lags noticeably behind what the
 * reader is actually looking at.
 *
 * @param {string[]} sectionIds Ids to observe, in document order.
 * @returns {string} The id of the section considered active.
 */
export function useScrollSpy(sectionIds) {
  const [activeId, setActiveId] = useState(sectionIds[0] ?? '');

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return undefined;

    const visible = new Map();

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            visible.set(entry.target.id, entry.intersectionRatio);
          } else {
            visible.delete(entry.target.id);
          }
        });

        if (visible.size === 0) return;

        // Where several sections straddle the band, prefer the one occupying
        // most of it; ties fall back to document order.
        let best = null;
        let bestRatio = -1;
        sectionIds.forEach((id) => {
          const ratio = visible.get(id);
          if (ratio !== undefined && ratio > bestRatio) {
            best = id;
            bestRatio = ratio;
          }
        });

        if (best) setActiveId(best);
      },
      {
        rootMargin: '-20% 0px -55% 0px',
        threshold: [0, 0.15, 0.4, 0.75, 1],
      },
    );

    const nodes = sectionIds
      .map((id) => document.getElementById(id))
      .filter(Boolean);
    nodes.forEach((node) => observer.observe(node));

    return () => observer.disconnect();
  }, [sectionIds]);

  return activeId;
}

/**
 * Smooth-scroll to a section, honouring the reader's motion preference.
 *
 * `scrollIntoView` with `behavior: 'smooth'` is ignored by browsers when the OS
 * reduce-motion setting is on, but checking explicitly means the jump is
 * instant and predictable rather than depending on engine behaviour.
 *
 * @param {string} id
 */
export function scrollToSection(id) {
  const node = document.getElementById(id);
  if (!node) return;

  const reduced =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // When Lenis is driving the page (set by App), route through it so the
  // programmatic jump is smoothed by the same system as wheel scrolling rather
  // than fighting it. Falls back to native scrolling when Lenis is absent
  // (reduced motion, or before it mounts).
  const lenis = typeof window !== 'undefined' ? window.__lenis : null;
  if (lenis && !reduced) {
    lenis.scrollTo(node, { offset: 0 });
    return;
  }

  node.scrollIntoView({
    behavior: reduced ? 'auto' : 'smooth',
    block: 'start',
  });
}
