import { HERO_CASE } from './plateData.js';
import { formatInr } from '../../lib/economics.js';

/**
 * The resting card — a sealed decision device, not a payment card.
 *
 * Ported from `stage1_ascension_final.html`. It is a real slab: the face sits
 * at `translateZ(9px)` and four thin rotated rectangles form its 18px sides, so
 * when the rig tilts under the cursor the card has visible thickness instead of
 * reading as a decal.
 *
 * Deliberately absent: card number, expiry, cardholder name, network branding.
 * The only figures shown are this dispute's own — id, amount, reason code and
 * the decision — all read from preset case data.
 *
 * Stage.jsx fades this out as the four layers separate; the card does not
 * animate itself beyond the specular sweep and the chip.
 */
export default function Card({ innerRef }) {
  return (
    <div ref={innerRef} className="card-face">
      {/* Slab sides. */}
      <div className="edge edge--right" />
      <div className="edge edge--left" />
      <div className="edge edge--top" />
      <div className="edge edge--bottom" />

      {/* Circuit etching across the whole face. */}
      <svg className="circuits" viewBox="0 0 440 277" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <g stroke="#62C6D7" strokeWidth="0.6" fill="none" opacity="0.4">
          <path d="M0 90 L120 90 L140 110 L260 110 L280 90 L440 90" />
          <path d="M0 200 L90 200 L110 180 L230 180 L250 200 L440 200" />
          <path d="M330 0 L330 60 L360 90 L360 190 L390 220 L390 277" />
          <path d="M60 0 L60 40 L80 60 L80 130" />
          <circle cx="140" cy="110" r="2.2" fill="#62C6D7" opacity="0.7" />
          <circle cx="280" cy="90" r="2.2" fill="#62C6D7" opacity="0.7" />
          <circle cx="230" cy="180" r="2.2" fill="#62C6D7" opacity="0.7" />
          <circle cx="360" cy="90" r="2.2" fill="#62C6D7" opacity="0.7" />
        </g>
      </svg>

      <div className="sweep" />

      {/* Top row: the dispute reference and the mark. */}
      <div className="absolute left-7 right-7 top-[26px] z-[5] flex items-start justify-between">
        <div>
          <div className="font-mono text-[9.5px] tracking-[0.14em]" style={{ color: '#5A6577' }}>
            DISPUTE
          </div>
          <div
            className="mt-1 font-mono text-[13px] tracking-[0.04em]"
            style={{ color: '#8FE3C0', textShadow: '0 0 12px rgba(16,185,129,0.4)' }}
          >
            #{HERO_CASE.id}
          </div>
        </div>
        <svg
          className="h-[30px] w-[30px] opacity-90"
          viewBox="0 0 40 40"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          style={{ filter: 'drop-shadow(0 0 6px rgba(16,185,129,0.4))' }}
          aria-hidden="true"
        >
          <path d="M20 3 L34 9 L34 20 Q34 30 20 37 Q6 30 6 20 L6 9 Z" stroke="#62C6D7" strokeWidth="1.4" />
          <path d="M20 10 Q27 26 20 26" stroke="#62C6D7" strokeWidth="1.1" opacity="0.85" />
          <circle cx="20" cy="26" r="1.3" fill="#62C6D7" />
        </svg>
      </div>

      {/* The chip. Its waves cross the whole face, so nothing above clips them. */}
      <div className="absolute left-7 top-[78px] z-[6]">
        <div className="chip">
          <div className="contact" style={{ top: 11 }} />
          <div className="contact" style={{ top: 19 }} />
          <div className="contact" style={{ top: 27 }} />
          <div className="contact" style={{ top: 35 }} />
          <div className="vline" style={{ left: 19 }} />
          <div className="vline" style={{ left: 37 }} />
          <div className="wave" />
          <div className="wave wave--2" />
          <div className="wave wave--3" />
        </div>
      </div>

      {/* Engraved wordmark. Sits at 96px rather than the reference's 64px: at
          64px it collides with the reason-code line of the bottom row, which
          starts ~64px up once the amount below it is accounted for. */}
      <div
        className="absolute bottom-[96px] left-7 z-[5] font-mono text-[10px] tracking-[0.22em]"
        style={{ color: '#3A4250' }}
      >
        <b style={{ color: '#5A6577', letterSpacing: '0.28em' }}>ChargeGuard</b> SENTINEL
      </div>

      {/* Bottom row: reason code, amount, decision. */}
      <div className="absolute bottom-[26px] left-7 right-7 z-[5] flex items-end justify-between">
        <div>
          <div className="font-mono text-[9.5px] tracking-[0.04em]" style={{ color: '#5A6577' }}>
            {HERO_CASE.reasonCode} · {HERO_CASE.reasonLabel}
          </div>
          <div className="mt-[3px] font-mono text-[20px] font-600" style={{ color: '#E8EBF0' }}>
            {formatInr(HERO_CASE.amountInr)}
          </div>
        </div>
        <div
          className="rounded-[7px] px-3 py-1.5 font-mono text-[9.5px] tracking-[0.1em]"
          style={{
            color: '#62C6D7',
            background: 'rgba(16,185,129,0.08)',
            border: '1px solid rgba(16,185,129,0.3)',
            boxShadow: '0 0 16px -4px rgba(16,185,129,0.5)',
          }}
        >
          {HERO_CASE.decision}
        </div>
      </div>
    </div>
  );
}
