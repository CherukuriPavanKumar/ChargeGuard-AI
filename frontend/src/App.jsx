import { Suspense, lazy, useEffect } from 'react';
import Lenis from 'lenis';

import Nav from './components/Nav.jsx';
import HeroSequence from './components/hero/HeroSequence.jsx';
import ProblemSection from './components/ProblemSection.jsx';
import ArchitectureDiagram from './components/ArchitectureDiagram.jsx';
import RevealTransition from './components/hero/RevealTransition.jsx';
import { MarkDivider } from './components/ui/Mark.jsx';

/**
 * Page composition.
 *
 * The section order is an argument, not a layout preference:
 *
 *   1. hero          the rule, stated in one line and plotted live
 *   1.5. spatial     the same case, followed through evidence -> economics ->
 *                     a live decision -- a continuation of the hero's 3D
 *                     language before the page settles into flat sections
 *   2. problem       why the rule inverts standard fraud intuition
 *   3. architecture  who is allowed to apply it
 *   4. math          the rule, made interactive
 *   5. simulator     the rule, applied to three real cases
 *   6. eval          whether it actually worked, on held-out data
 *   7. verify        how to reproduce that yourself
 *   8. repo          how the invariants are enforced
 *
 * Claim, justification, mechanism, evidence, reproduction. A reader who stops at
 * any point has a coherent partial picture rather than half of a pitch.
 *
 * Everything from the arbitrage visualiser down is behind `React.lazy`. Those
 * four sections carry the entire Recharts dependency (~150KB gzipped), and none
 * of them is above the fold — loading them eagerly would mean the headline waits
 * on a charting library it does not use. The split is by *section*, not by
 * chart, so a reader who never scrolls past the architecture diagram never
 * downloads Recharts at all. `SpatialWorkflow` is lazy for the same reason: it
 * is entirely below the fold and carries its own Framer Motion choreography
 * that the hero has no use for until the reader actually scrolls there.
 */

const ArbitrageVisualizer = lazy(() => import('./components/ArbitrageVisualizer.jsx'));
const Simulator = lazy(() => import('./components/Simulator.jsx'));
const EvalDashboard = lazy(() => import('./components/EvalDashboard.jsx'));
const VerifySection = lazy(() => import('./components/VerifySection.jsx'));
const RepoSection = lazy(() => import('./components/RepoSection.jsx'));

/**
 * Placeholder for a lazy section. Reserves realistic height so the page does not
 * jump as each chunk lands — a layout shift while the reader is mid-scroll is
 * worse than a moment of empty space.
 */
function SectionFallback({ id, label }) {
  return (
    <section id={id} className="py-24 sm:py-32">
      <div className="mx-auto max-w-content px-5 sm:px-8">
        <div className="h-6 w-40 animate-pulse rounded bg-white/[0.06]" />
        <div className="mt-4 h-10 w-2/3 max-w-xl animate-pulse rounded bg-white/[0.05]" />
        <div className="mt-10 h-64 animate-pulse rounded-2xl bg-white/[0.03]" />
        <span className="sr-only">Loading {label}…</span>
      </div>
    </section>
  );
}

export default function App() {
  // Lenis smooths the whole page and is the single scroll-smoothing system, as
  // the hero's scroll-linked stages assume one eased scroll position. It uses
  // the real scroll position, so Framer Motion's useScroll stays in step with
  // it; scrollToSection routes through the same instance (see useScrollSpy).
  // Disabled entirely under reduced motion, where scrolling must be instant.
  useEffect(() => {
    const lenis = new Lenis({ lerp: 0.1, wheelMultiplier: 1, smoothWheel: true });
    window.__lenis = lenis;
    let raf = 0;
    const loop = (time) => {
      lenis.raf(time);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      lenis.destroy();
      if (window.__lenis === lenis) window.__lenis = null;
    };
  }, []);

  return (
    <div className="min-h-screen bg-obsidian">
      <Nav />

      <main>
        <HeroSequence />

        <div>
          <ProblemSection />

          {/* The architecture section arrives through a growing card-shaped
              window rather than simply scrolling up. RevealTransition renders
              it exactly once -- the window is a hole in an opaque cover, not a
              second copy -- so the nav's scroll-spy still finds one
              #architecture and the diagram never mounts twice. */}
          <RevealTransition>
            <ArchitectureDiagram />
          </RevealTransition>

          <MarkDivider />

          <Suspense fallback={<SectionFallback id="math" label="the arbitrage visualiser" />}>
            <ArbitrageVisualizer />
          </Suspense>
          <MarkDivider />

          <Suspense fallback={<SectionFallback id="simulator" label="the simulator" />}>
            <Simulator />
          </Suspense>
          <MarkDivider />

          <Suspense fallback={<SectionFallback id="eval" label="the evaluation dashboard" />}>
            <EvalDashboard />
          </Suspense>
          <MarkDivider />

          <Suspense fallback={<SectionFallback id="verify" label="the verification section" />}>
            <VerifySection />
          </Suspense>
          <MarkDivider />

          <Suspense fallback={<SectionFallback id="repo" label="the repository tour" />}>
            <RepoSection />
          </Suspense>
        </div>
      </main>
    </div>
  );
}
