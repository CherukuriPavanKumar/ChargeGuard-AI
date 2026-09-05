import clsx from 'clsx';
import { motion } from 'framer-motion';

/**
 * The single raised-surface primitive used everywhere in the site.
 *
 * Defined once so every panel reads as the same material. The alternative --
 * each section styling its own container -- produces surfaces that are almost
 * but not quite identical, which the eye reads as sloppiness long before it can
 * name why.
 *
 * `accent` ties the card to the trust-boundary colour encoding used in the
 * architecture diagram: emerald for deterministic compute, indigo for
 * probabilistic, coral for policy gates, slate for I/O and neutral chrome.
 */

const ACCENT_RING = {
  none: '',
  emerald: 'ring-1 ring-emerald/25',
  indigo: 'ring-1 ring-indigo/25',
  coral: 'ring-1 ring-coral/25',
  slate: 'ring-1 ring-white/10',
};

const ACCENT_GLOW = {
  none: '',
  emerald: 'shadow-emerald/10',
  indigo: 'shadow-indigo/10',
  coral: 'shadow-coral/10',
  slate: '',
};

export default function GlassCard({
  children,
  className,
  accent = 'none',
  as: Component = 'div',
  hover = false,
  ...rest
}) {
  return (
    <Component
      className={clsx(
        'glass',
        ACCENT_RING[accent] ?? ACCENT_RING.none,
        ACCENT_GLOW[accent] ?? '',
        hover &&
          'transition-transform duration-300 ease-entrance hover:-translate-y-0.5 hover:border-white/20',
        className,
      )}
      {...rest}
    >
      {children}
    </Component>
  );
}

/**
 * A GlassCard that fades up when scrolled into view.
 *
 * `viewport={{ once: true }}` throughout: a section that re-animates every time
 * it re-enters the viewport turns scrolling back to re-read something into a
 * small penalty, which is hostile.
 */
export function GlassCardReveal({
  children,
  className,
  accent = 'none',
  delay = 0,
  ...rest
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-80px' }}
      transition={{ duration: 0.5, delay, ease: [0.22, 1, 0.36, 1] }}
      className={clsx('glass', ACCENT_RING[accent] ?? '', className)}
      {...rest}
    >
      {children}
    </motion.div>
  );
}

/**
 * Section heading with an eyebrow label and optional lead paragraph.
 *
 * Exists so heading rhythm is defined in one place; every section on the page
 * uses it and therefore shares identical vertical spacing and type scale.
 */
export function SectionHeading({ eyebrow, title, lead, className }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-80px' }}
      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
      className={clsx('max-w-3xl', className)}
    >
      {eyebrow && <div className="eyebrow mb-3">{eyebrow}</div>}
      <h2 className="font-display text-3xl font-600 leading-tight text-white text-balance sm:text-4xl">
        {title}
      </h2>
      {lead && (
        <p className="mt-4 text-base leading-relaxed text-slateink text-pretty">
          {lead}
        </p>
      )}
    </motion.div>
  );
}

/**
 * A labelled numeric readout.
 *
 * Uses the mono face with tabular figures so the value does not change width
 * while animating -- without that, a metric counting up visibly shoves its
 * neighbours around.
 */
export function Stat({ label, value, sublabel, accent = 'slate', className }) {
  const tone = {
    emerald: 'text-emerald',
    indigo: 'text-indigo',
    coral: 'text-coral',
    slate: 'text-white',
  }[accent];

  return (
    <div className={clsx('flex flex-col gap-1', className)}>
      <div className="eyebrow">{label}</div>
      <div className={clsx('font-mono text-2xl font-500 tabular', tone)}>
        {value}
      </div>
      {sublabel && (
        <div className="text-xs leading-snug text-slateink/60">{sublabel}</div>
      )}
    </div>
  );
}
