import { motion } from 'framer-motion';

import { FLOATING_TAGS } from './plateData.js';

/**
 * The three premium tags that orbit the resting card.
 *
 * THE ENTRANCE IS THE POINT. Each tag starts at `scale(0)`, fully transparent,
 * at the card's centre, and travels outward to its resting offset — so it reads
 * as *emerging from the card*, not fading in from thin air at its own location.
 * The travel is a spring rather than an ease-out, which gives a slight organic
 * overshoot as it settles.
 *
 * TWO NESTED ELEMENTS, TWO TRANSFORMS. The outer `motion.div` owns the
 * entrance (x/y/scale). The inner `.tag-float` owns the idle drift, as a CSS
 * keyframe. They must not be the same element: two sources writing one
 * `transform` fight every frame and the animation freezes unpredictably.
 *
 * Each tag drifts on its own period (4.2s / 5.1s / 4.7s) so the three never
 * move in visible sync with each other or with the card.
 *
 * Values are this dispute's own — never a portfolio-level statistic.
 *
 * Sized ~25% larger than the first pass, and re-materialised as brushed
 * titanium (`.satellite`) rather than a flat translucent block, so they read
 * as instrumentation mounted beside the card instead of floating labels.
 */
export default function FloatingTags({ startDelay = 1.3, reduced = false, count = 3 }) {
  // Below 1024px only the headline value survives; three tags around a smaller
  // card reads as clutter rather than instrumentation.
  const tags = FLOATING_TAGS.slice(0, count);

  return (
    <div className="pointer-events-none absolute inset-0 z-[8]">
      {tags.map((tag, i) => (
        <motion.div
          key={tag.key}
          className="absolute left-1/2 top-1/2"
          initial={{ x: 0, y: 0, scale: 0, opacity: 0 }}
          animate={{ x: tag.dx, y: tag.dy, scale: 1, opacity: 1 }}
          transition={
            reduced
              ? { duration: 0 }
              : {
                  type: 'spring',
                  damping: 16,
                  stiffness: 90,
                  delay: startDelay + i * 0.12,
                  opacity: { duration: 0.35, delay: startDelay + i * 0.12 },
                }
          }
          style={{ marginLeft: -88, marginTop: -28 }}
        >
          <div className="tag-float" style={{ animationDuration: `${tag.floatPeriod}s` }}>
            {/* `.satellite` carries the brushed-titanium material: smoked
                obsidian body, gradient border via the padding-box/border-box
                trick, and an inset specular rim. See hero.css. */}
            <div className="satellite" style={{ '--sat': tag.accent }}>
              <div className="satellite__label">{tag.label}</div>
              <div className="satellite__value">{tag.value}</div>
            </div>
          </div>
        </motion.div>
      ))}
    </div>
  );
}
