import { useEffect, useState } from 'react';
import { Terminal, Github } from 'lucide-react';

import { scrollToSection } from '../../hooks/useScrollSpy.js';
import Card from './Card.jsx';
import { PLATES, FLOATING_TAGS, HERO_CASE } from './plateData.js';

/**
 * The no-motion path, serving two audiences with the same layout because both
 * need the same thing: the whole argument, readable, with no pointer and no
 * animation.
 *
 *  - `prefers-reduced-motion: reduce` — the card is shown assembled and the four
 *    layers are a plain vertical list with their detail already open. Nothing
 *    is revealed by motion, so nothing is lost by removing it.
 *  - under 768px — there is no ring and no cursor to steer it, so the plates
 *    become a list the reader simply scrolls through. Detail is shown outright
 *    rather than behind a hover a touch device cannot perform.
 */
export default function StaticFallback() {
  // The card is drawn at its design size and scaled to fit, never re-laid out.
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const fit = () => {
      const avail = Math.min(440, window.innerWidth * 0.88);
      setScale(avail > 0 ? avail / 440 : 1);
    };
    fit();
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, []);

  return (
    <section id="hero" className="relative px-5 pb-16 pt-24 sm:px-8">
      <div className="mx-auto max-w-content">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-emerald/25 bg-emerald-dim px-3 py-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald" />
          <span className="font-mono text-2xs uppercase tracking-[0.16em] text-emerald">
            Dispute Defense Engine
          </span>
        </div>

        <h1
          className="font-display font-700 leading-[1.05] tracking-tight text-white"
          style={{ fontSize: 'clamp(2.25rem, 7vw, 3.5rem)' }}
        >
          One card.
          <br />
          Four <span style={{ color: '#62C6D7' }}>judgments</span>.
        </h1>
        <p className="mt-4 max-w-xl text-base leading-relaxed" style={{ color: '#CBD5E1' }}>
          A dispute is worth contesting only when expected recovery beats the cost
          of fighting. Not on average. Per dispute.
        </p>

        {/* The card, assembled and still.

            Scaled rather than resized, for the same reason as the interactive
            stage: the card's internal offsets are fixed pixels tuned against a
            440px card, so narrowing the box makes the chip collide with the
            engraved wordmark. The rendered box reserves the scaled height so
            the layout below it does not overlap. */}
        <div className="mt-10 flex justify-center">
          <div style={{ width: 440 * scale, height: (440 / 1.586) * scale }}>
            <div
              className="relative"
              style={{
                width: 440,
                aspectRatio: '1.586',
                transformStyle: 'preserve-3d',
                transform: `scale(${scale})`,
                transformOrigin: 'top left',
              }}
            >
              <Card />
            </div>
          </div>
        </div>

        {/* This dispute's three values. */}
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          {FLOATING_TAGS.map((tag) => (
            <div key={tag.key} className="satellite" style={{ '--sat': tag.accent }}>
              <div className="satellite__label">{tag.label}</div>
              <div className="satellite__value">{tag.value}</div>
            </div>
          ))}
        </div>

        <div className="mt-8 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => scrollToSection('simulator')}
            className="inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-emerald px-5 py-3 font-display text-sm font-600 text-obsidian"
          >
            <Terminal size={16} />
            Run the simulator
          </button>
          <button
            type="button"
            onClick={() => scrollToSection('verify')}
            className="inline-flex min-h-[44px] items-center gap-2 rounded-xl border border-white/15 px-5 py-3 font-display text-sm font-600 text-white"
          >
            <Github size={16} />
            Verify
          </button>
        </div>

        {/* The four layers, already open. */}
        <div className="mt-14">
          <h2 className="font-display text-2xl font-700 text-white">
            Everything the engine considers, before it decides anything.
          </h2>
          <p className="mt-2 text-sm" style={{ color: '#8A94A6' }}>
            Dispute #{HERO_CASE.id} · {HERO_CASE.reasonCode} · {HERO_CASE.reasonLabel}
          </p>

          <div className="mt-6 grid gap-4">
            {PLATES.map((plate) => (
              <div
                key={plate.n}
                className="rounded-2xl p-6"
                style={{
                  background: 'rgba(13, 18, 31, 0.94)',
                  border: '1px solid rgba(255,255,255,0.12)',
                  borderLeft: `3px solid ${plate.accent}`,
                }}
              >
                <div className="font-mono text-[10px] tracking-[0.12em]" style={{ color: plate.accent }}>
                  {plate.n} · {plate.title}
                </div>
                <div className="mt-1.5 font-mono text-[15px]" style={{ color: '#E8EBF0' }}>
                  {plate.kind === 'governor' ? (
                    <>p* = λc / A<sub>i</sub></>
                  ) : (
                    plate.big
                  )}
                </div>
                <div className="mt-3">
                  {plate.rows.map((row) => (
                    <div
                      key={row.k}
                      className="flex items-center justify-between gap-3 border-t py-1.5 font-mono text-[10.5px]"
                      style={{ borderColor: 'rgba(255,255,255,0.06)', color: '#8A94A6' }}
                    >
                      <span>{row.k}</span>
                      <b className="text-right font-500" style={{ color: '#D7DCE5' }}>{row.v}</b>
                    </div>
                  ))}
                  {plate.footnote && (
                    <div className="pt-2 font-mono text-[9px]" style={{ color: '#4A5464' }}>
                      {plate.footnote}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
