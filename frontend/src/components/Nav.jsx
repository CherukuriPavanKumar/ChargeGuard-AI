import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import clsx from 'clsx';
import { Menu, X } from 'lucide-react';

import { scrollToSection, useScrollSpy } from '../hooks/useScrollSpy.js';
import Mark from './ui/Mark.jsx';

/**
 * Fixed navigation with a sliding active indicator.
 *
 * The desktop indicator is a single element moved between items by Framer
 * Motion's shared-layout system (`layoutId`), not one underline per item
 * toggling opacity: the eye tracks one object moving, so the reader gets a
 * spatial sense of where they are in the document. Active section comes from
 * IntersectionObserver via `useScrollSpy`, never from scroll-position math.
 *
 * Below `lg` the links collapse to a slide-in sheet with the same scroll-spy
 * behaviour and 44px tap targets. The breakpoint is `lg`, not `md`: eight items
 * plus the wordmark overflow a 768px viewport by ~98px, which pushed the last
 * link off-screen entirely.
 */

const SECTIONS = [
  { id: 'hero', label: 'Overview' },
  { id: 'problem', label: 'Problem' },
  { id: 'architecture', label: 'Architecture' },
  { id: 'simulator', label: 'Simulator' },
  { id: 'eval', label: 'Evaluation' },
  { id: 'verify', label: 'Verify' },
];

export const SECTION_IDS = SECTIONS.map((s) => s.id);

/** The wordmark: the frontier glyph, then ChargeGuard with .AI dimmed to 60%. */
function Wordmark({ onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="ChargeGuard.AI — back to top"
      className="group flex min-h-[44px] items-center gap-2.5 rounded-lg px-1 py-1 text-left"
    >
      <Mark size={22} className="shrink-0" />
      <span className="font-display text-base font-700 tracking-[0.14em] text-white">
        ChargeGuard<span className="text-white/60">.AI</span>
      </span>
    </button>
  );
}

export default function Nav() {
  const activeId = useScrollSpy(SECTION_IDS);
  const [mobileOpen, setMobileOpen] = useState(false);

  const handleNavigate = (id) => {
    setMobileOpen(false);
    scrollToSection(id);
  };

  // Lock body scroll and close on Escape while the sheet is open.
  useEffect(() => {
    if (!mobileOpen) return undefined;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (e) => {
      if (e.key === 'Escape') setMobileOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener('keydown', onKey);
    };
  }, [mobileOpen]);

  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-white/10 bg-obsidian">
      <nav
        aria-label="Section navigation"
        className="mx-auto flex h-16 max-w-content items-center justify-between px-5 sm:px-8"
      >
        <Wordmark onClick={() => handleNavigate('hero')} />

        {/* Desktop links */}
        <ul className="hidden items-center gap-1 lg:flex">
          {SECTIONS.map((section) => {
            const isActive = activeId === section.id;
            return (
              <li key={section.id} className="relative">
                <button
                  type="button"
                  onClick={() => handleNavigate(section.id)}
                  aria-current={isActive ? 'true' : undefined}
                  className={clsx(
                    'relative rounded-lg px-2.5 py-2 text-sm transition-colors duration-200 lg:px-3',
                    isActive ? 'text-white' : 'text-slateink/70 hover:text-slateink',
                  )}
                >
                  {section.label}
                  {isActive && (
                    <motion.span
                      layoutId="nav-active-underline"
                      className="absolute inset-x-2.5 -bottom-0.5 h-px rounded-full bg-emerald"
                      transition={{ type: 'spring', stiffness: 420, damping: 34 }}
                    />
                  )}
                </button>
              </li>
            );
          })}
        </ul>

        {/* Mobile toggle */}
        <button
          type="button"
          onClick={() => setMobileOpen(true)}
          aria-expanded={mobileOpen}
          aria-label="Open navigation"
          className="flex h-11 w-11 items-center justify-center rounded-lg border border-white/10 text-slateink transition-colors hover:text-white lg:hidden"
        >
          <Menu size={18} />
        </button>
      </nav>

      {/* Mobile sheet: slides in from the right, dims the page behind it. */}
      <AnimatePresence>
        {mobileOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              onClick={() => setMobileOpen(false)}
              className="fixed inset-0 z-40 bg-obsidian/85 lg:hidden"
              aria-hidden="true"
            />
            <motion.div
              role="dialog"
              aria-label="Navigation"
              aria-modal="true"
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', stiffness: 380, damping: 38 }}
              className="fixed right-0 top-0 z-50 flex h-full w-72 max-w-[80vw] flex-col border-l border-white/10 bg-obsidian/98 lg:hidden"
            >
              <div className="flex h-16 items-center justify-between border-b border-white/10 px-5">
                <Wordmark onClick={() => handleNavigate('hero')} />
                <button
                  type="button"
                  onClick={() => setMobileOpen(false)}
                  aria-label="Close navigation"
                  className="flex h-11 w-11 items-center justify-center rounded-lg text-slateink transition-colors hover:text-white"
                >
                  <X size={18} />
                </button>
              </div>
              <ul className="flex flex-col p-3">
                {SECTIONS.map((section) => (
                  <li key={section.id}>
                    <button
                      type="button"
                      onClick={() => handleNavigate(section.id)}
                      aria-current={activeId === section.id ? 'true' : undefined}
                      className={clsx(
                        'flex min-h-[44px] w-full items-center gap-3 rounded-lg px-3 text-left text-[15px] transition-colors',
                        activeId === section.id
                          ? 'bg-emerald-dim text-emerald'
                          : 'text-slateink/80 hover:bg-white/5 hover:text-white',
                      )}
                    >
                      <span
                        className={clsx(
                          'h-1.5 w-1.5 rounded-full',
                          activeId === section.id ? 'bg-emerald' : 'bg-white/15',
                        )}
                      />
                      {section.label}
                    </button>
                  </li>
                ))}
              </ul>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </header>
  );
}
