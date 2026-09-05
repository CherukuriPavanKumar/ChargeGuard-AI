import { forwardRef } from 'react';

/**
 * One plate of the exploded 3D stack, in brushed-titanium and smoked glass.
 *
 * SCOPE OF THIS FILE. Purely presentational -- the styling and typography
 * layer only. Stage.jsx remains the sole author of each plate's `transform`,
 * `opacity` and `filter`, written imperatively every frame; the scroll
 * mechanics, spring physics and ring coordinates are untouched by this
 * component. That separation is deliberate: a CSS transition on `transform`
 * here would fight the loop for the same property on every frame.
 *
 * (This replaces the earlier `Plate.jsx`. Same contract, same props, same
 * ref forwarding -- only the material and the per-plate content changed.)
 *
 * THE MATERIAL, and why each piece is load-bearing:
 *
 *   - A near-opaque brushed gradient, not translucent glass. Lighter fills let
 *     the text of the plate behind bleed through and garble the text in front.
 *     If that symptom ever reappears it is translucency, not a duplicate node.
 *   - `backface-visibility: hidden` (in hero.css). Once a plate rotates past
 *     90deg it would otherwise show its own back face -- the front seen from
 *     behind -- and every label renders mirrored. Hiding the back face fixes
 *     that without clamping rotation, which would stop the ring ever closing.
 *   - A 1px top highlight over a 12%-white body border, reading as a milled
 *     metal rim catching the light from above.
 *
 * Every accent -- rule, header, meter fill, focus glow, scan line -- reads
 * from the single `--ac` custom property, so a plate cannot disagree with
 * itself about its own colour.
 */

/** A engraved-looking header badge: `LAYER 01 // IDENTITY SHELL`. */
function LayerBadge({ plate }) {
  return (
    <div className="lbadge">
      <span className="lbadge__n">LAYER {plate.n}</span>
      <span className="lbadge__sep">//</span>
      <span className="lbadge__t">{plate.title}</span>
    </div>
  );
}

/** 01 -- device fingerprint confidence, as a milled meter. */
function ConfidenceMeter({ meter }) {
  const pct = Math.round(meter.value * 100);
  return (
    <div className="lmeter">
      <div className="lmeter__head">
        <span>{meter.label}</span>
        <b className="tabular-nums">{pct}%</b>
      </div>
      <div className="lmeter__track">
        <div className="lmeter__fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/** 02 -- biometric match pill plus the courier telemetry badge. */
function ForensicPills({ plate }) {
  return (
    <div className="lpills">
      <span className="lpill lpill--solid">
        <span className="tabular-nums">{plate.pill.value}</span> {plate.pill.state}
      </span>
      <span className="lpill lpill--ghost tabular-nums">{plate.badge}</span>
    </div>
  );
}

/**
 * 03 -- the calibrated win-probability wave.
 *
 * The gradient and the soft outer glow are what make this read as an
 * instrument trace rather than a stroked path; the score sits on the same
 * baseline so the eye takes the number and the curve as one readout.
 */
function ProbabilityWave({ plate }) {
  return (
    <div className="lwave">
      <svg viewBox="0 0 380 44" className="lwave__svg" aria-hidden="true" preserveAspectRatio="none">
        <defs>
          <linearGradient id="waveGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#818CF8" stopOpacity="0.15" />
            <stop offset="45%" stopColor="#818CF8" stopOpacity="1" />
            <stop offset="100%" stopColor="#06B6D4" stopOpacity="0.9" />
          </linearGradient>
          <filter id="waveGlow" x="-20%" y="-80%" width="140%" height="260%">
            <feGaussianBlur stdDeviation="2.4" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <path
          d="M0 30 Q26 30 40 24 T80 20 T120 26 T160 14 T200 18 T240 9 T280 14 T320 7 T380 5"
          fill="none"
          stroke="url(#waveGrad)"
          strokeWidth="1.8"
          strokeLinecap="round"
          filter="url(#waveGlow)"
        />
      </svg>
      <div className="lwave__score tabular-nums">{plate.score}</div>
    </div>
  );
}

/** 04 -- the rule, set as a formula block, with the net EV badge beneath. */
function GovernorFormula({ plate }) {
  return (
    <div className="lformula">
      <div className="lformula__eq tabular-nums">
        p* = (λ · c) / A<sub>i</sub>
      </div>
      <div className="lformula__badge tabular-nums">{plate.evBadge}</div>
    </div>
  );
}

const ExplodedPlate = forwardRef(function ExplodedPlate({ plate, index }, ref) {
  return (
    <div ref={ref} className="layer" data-index={index} style={{ '--ac': plate.accent }}>
      {/* Milled top rim -- a 1px gradient hairline, brightest at the centre. */}
      <div className="layer__rim" aria-hidden="true" />
      {/* Only visible on the plate currently being inspected. */}
      <div className="scan" />

      <div>
        <LayerBadge plate={plate} />
        <div className="lbig">{plate.big}</div>
      </div>

      {plate.kind === 'identity' && <ConfidenceMeter meter={plate.meter} />}
      {plate.kind === 'forensic' && <ForensicPills plate={plate} />}
      {plate.kind === 'lattice' && <ProbabilityWave plate={plate} />}
      {plate.kind === 'governor' && <GovernorFormula plate={plate} />}

      <div>
        {plate.rows.map((row) => (
          <div className="lrow" key={row.k}>
            <span>{row.k}</span>
            <b className="tabular-nums">{row.v}</b>
          </div>
        ))}
        {plate.footnote && <div className="lfoot">{plate.footnote}</div>}
      </div>
    </div>
  );
});

export default ExplodedPlate;
