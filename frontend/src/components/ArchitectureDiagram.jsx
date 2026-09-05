import { useState } from 'react';
import { motion } from 'framer-motion';

import { SectionHeading } from './ui/GlassCard.jsx';

/**
 * Hand-authored SVG architecture diagram, colour-coded by trust boundary.
 *
 * Hand-authored rather than generated from a diagramming library because the
 * *encoding* is the content: colour here is not decoration, it states which
 * components are permitted to decide anything. A library would give a prettier
 * auto-layout and no way to make that argument.
 *
 *   slate    I/O boundary        untrusted input, untrusted output
 *   emerald  deterministic       pure functions, auditable by reading them
 *   indigo   probabilistic       returns a number it cannot justify
 *   coral    policy gate         the only thing that decides
 *
 * The argument the diagram makes: every path from an indigo node to an output
 * passes through the coral node. The model and the LLM are both *upstream* of
 * a checkpoint they cannot bypass.
 */

const TIERS = [
  { y: 60, label: 'Ingest' },
  { y: 158, label: 'Extract' },
  { y: 256, label: 'Feature' },
  { y: 354, label: 'Infer' },
  { y: 452, label: 'Decide' },
  { y: 550, label: 'Emit' },
];

const KIND = {
  io: {
    fill: 'rgba(148,163,184,0.10)',
    stroke: 'rgba(148,163,184,0.45)',
    text: '#CBD5E1',
    label: 'I/O boundary',
  },
  deterministic: {
    fill: 'rgba(16,185,129,0.10)',
    stroke: 'rgba(16,185,129,0.55)',
    text: '#6EE7B7',
    label: 'Deterministic',
  },
  probabilistic: {
    fill: 'rgba(99,102,241,0.10)',
    stroke: 'rgba(99,102,241,0.55)',
    text: '#A5B4FC',
    label: 'Probabilistic',
  },
  gate: {
    fill: 'rgba(249,115,98,0.12)',
    stroke: 'rgba(249,115,98,0.65)',
    text: '#FCA5A5',
    label: 'Policy gate',
  },
};

const NODES = [
  {
    id: 'webhook',
    tier: 0,
    x: 60,
    w: 230,
    kind: 'io',
    title: 'Dispute Webhook',
    subtitle: 'acquirer envelope → DisputeEvent',
    module: 'ingest/webhook.py',
    detail:
      'Parses the acquirer envelope. Paise convert to rupees through Decimal, never float — a binary rounding error here would propagate into every expected-value computation for the life of the dispute.',
  },
  {
    id: 'bundle',
    tier: 0,
    x: 330,
    w: 250,
    kind: 'io',
    title: 'Evidence Bundle',
    subtitle: 'order + session + POD image',
    module: 'ingest/evidence_loader.py',
    detail:
      'Composes three independent modalities: the courier slip image, the merchant OMS record, and checkout telemetry. Every field is an observation, not a fact.',
  },
  {
    id: 'ocr',
    tier: 1,
    x: 330,
    w: 250,
    kind: 'deterministic',
    title: 'OCR Extractor',
    subtitle: 'pytesseract → ProofOfDelivery',
    module: 'extraction/ocr.py',
    detail:
      'Never raises. Engine missing, image corrupt, page blank — every path returns a valid parse whose extraction_status states exactly how much it can be trusted. UNVERIFIED and ABSENT are deliberately distinct: one is a document we could not read, the other is no document, and the policy layer treats them very differently.',
  },
  {
    id: 'features',
    tier: 2,
    x: 195,
    w: 250,
    kind: 'deterministic',
    title: 'Feature Builder',
    subtitle: '35 features · pure · v1',
    module: 'features/builder.py',
    detail:
      'INVARIANT 2: no network, no disk, no clock, no randomness. Same input, same output, forever. Enforced by an AST test and by a determinism test. This is what makes train/serve skew structurally impossible rather than merely unlikely.',
  },
  {
    id: 'model',
    tier: 3,
    x: 60,
    w: 230,
    kind: 'probabilistic',
    title: 'Win-Probability Model',
    subtitle: 'LightGBM + isotonic → float',
    module: 'models/win_probability.py',
    detail:
      'Returns a calibrated float and nothing else. Cannot import Decision — enforced by test. Calibration matters here more than usual: the policy engine multiplies this number by rupees, so a miscalibrated score corrupts every threshold comparison while leaving AUC untouched.',
  },
  {
    id: 'llm',
    tier: 3,
    x: 330,
    w: 250,
    kind: 'probabilistic',
    title: 'LLM Synthesiser',
    subtitle: 'Claude → validated prose',
    module: 'llm/synthesiser.py',
    detail:
      'Never receives p_win, the threshold, or the decision — enforced on the function signature, not by convention. Runs downstream of the decision and only on CONTEST. Any citation to an artifact absent from the bundle rejects the whole draft and falls back to deterministic templates.',
  },
  {
    id: 'policy',
    tier: 4,
    x: 155,
    w: 330,
    kind: 'gate',
    title: 'Policy Gate  ·  the decision authority',
    subtitle: '6 ordered gates → EV rule → Decision',
    module: 'policy/engine.py',
    detail:
      'INVARIANT 1: the only module in the codebase permitted to construct a Decision. An AST-walking test fails the build if any other file does. The ML model returns a float; the LLM returns prose; neither decides anything. Every decision carries the complete ordered gate trace, fired or not.',
  },
  {
    id: 'api',
    tier: 5,
    x: 60,
    w: 230,
    kind: 'io',
    title: 'Decision API',
    subtitle: 'POST /v1/disputes/score',
    module: 'api/routes/disputes.py',
    detail:
      'Synchronous, p95 under 200 ms. Pure feature construction, in-process tree traversal, six gate evaluations. No network egress on this path at all.',
  },
  {
    id: 'packet',
    tier: 5,
    x: 330,
    w: 250,
    kind: 'io',
    title: 'Evidence Packet',
    subtitle: 'Jinja → HTML → PDF (async)',
    module: 'packet/renderer.py',
    detail:
      'Background job, deliberately off the latency path: it calls a language model and a native PDF engine, neither of which belongs inside a 200 ms budget. Generated only when the decision was CONTEST.',
  },
];

const EDGES = [
  ['webhook', 'features'],
  ['bundle', 'ocr'],
  ['ocr', 'features'],
  ['features', 'model'],
  ['features', 'llm'],
  ['model', 'policy'],
  ['policy', 'api'],
  ['policy', 'packet'],
];

const NODE_H = 62;

function nodeById(id) {
  return NODES.find((n) => n.id === id);
}

function nodeCenter(node) {
  return { x: node.x + node.w / 2, y: TIERS[node.tier].y + NODE_H / 2 };
}

/**
 * Edge path. Vertical runs get an S-curve so lines crossing tiers read as flow
 * rather than as a wiring harness.
 */
function edgePath(from, to) {
  const a = nodeCenter(from);
  const b = nodeCenter(to);
  const ay = TIERS[from.tier].y + NODE_H;
  const by = TIERS[to.tier].y;
  const mid = (ay + by) / 2;
  return `M ${a.x} ${ay} C ${a.x} ${mid}, ${b.x} ${mid}, ${b.x} ${by}`;
}

/**
 * Single-column variant for narrow viewports.
 *
 * Below `md` the six-tier layout does not fit, and the alternative -- a
 * horizontally scrolling SVG -- is a bad reading experience: the reader has to
 * pan back and forth to follow an edge, which defeats the point of a diagram
 * whose whole argument is *where the edges go*. This renders the same nodes,
 * same colour encoding, stacked, with the flow running straight down.
 *
 * The node list and the colour map are shared with the wide version, so the two
 * cannot drift apart.
 */
const V_NODE_H = 66;
const V_GAP = 26;
const V_W = 320;

function VerticalDiagram({ hovered, setHovered }) {
  const order = [
    'webhook', 'bundle', 'ocr', 'features', 'model', 'llm', 'policy', 'api', 'packet',
  ];
  const height = order.length * (V_NODE_H + V_GAP);

  return (
    <svg
      viewBox={`0 0 ${V_W} ${height}`}
      className="h-auto w-full"
      role="img"
      aria-label="ChargeGuard.AI architecture, vertical: dispute ingest through the policy gate to the decision API and evidence packet."
    >
      {/* Its own marker: a marker defined in another <svg> root does not
          resolve, and the wide diagram is display:none at this breakpoint. */}
      <defs>
        <marker
          id="arrow-v"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="5"
          markerHeight="5"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="rgba(148,163,184,0.45)" />
        </marker>
      </defs>

      {order.map((id, i) => {
        const node = nodeById(id);
        const kind = KIND[node.kind];
        const y = i * (V_NODE_H + V_GAP);
        const isHovered = hovered === id;
        const isLast = i === order.length - 1;

        return (
          <g key={id}>
            {!isLast && (
              <line
                x1={V_W / 2}
                y1={y + V_NODE_H}
                x2={V_W / 2}
                y2={y + V_NODE_H + V_GAP}
                stroke="rgba(148,163,184,0.28)"
                strokeWidth="1.2"
                markerEnd="url(#arrow-v)"
              />
            )}
            <g
              onMouseEnter={() => setHovered(id)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(id)}
              onBlur={() => setHovered(null)}
              tabIndex={0}
              role="button"
              aria-label={`${node.title}: ${node.subtitle}`}
              style={{ cursor: 'pointer', outline: 'none' }}
            >
              <rect
                x={8}
                y={y}
                width={V_W - 16}
                height={V_NODE_H}
                rx="10"
                fill={kind.fill}
                stroke={kind.stroke}
                strokeWidth={isHovered ? 1.8 : 1.1}
                style={{ transition: 'stroke-width 0.25s' }}
              />
              <text
                x={22}
                y={y + 26}
                fontSize="12.5"
                fill={kind.text}
                fontWeight="600"
                className="font-display"
              >
                {node.title}
              </text>
              <text
                x={22}
                y={y + 44}
                fontSize="9.5"
                fill="rgba(148,163,184,0.75)"
                className="font-mono"
              >
                {node.subtitle}
              </text>
            </g>
          </g>
        );
      })}
    </svg>
  );
}

export default function ArchitectureDiagram() {
  const [hovered, setHovered] = useState(null);
  const active = hovered ? nodeById(hovered) : null;

  return (
    <section id="architecture" className="relative py-24 sm:py-32">
      <div className="mx-auto max-w-content px-5 sm:px-8">
        <SectionHeading
          eyebrow="Trust boundaries"
          title="Two components in this system are not trustworthy. Neither of them decides anything."
          lead="The gradient-boosted model returns a float it cannot justify. The language model returns fluent prose that may be confabulated. Colour in this diagram is not decoration — it marks which components are permitted to determine whether the company spends money."
        />

        <div className="mt-12 grid gap-6 lg:grid-cols-[1fr_320px]">
          {/* Diagram */}
          <motion.div
            initial={{ opacity: 0, y: 18 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-80px' }}
            transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            className="glass p-4 sm:p-6"
          >
            {/* Below md: stacked. At md and up: the six-tier layout. Neither
                scrolls horizontally. */}
            <div className="md:hidden">
              <VerticalDiagram hovered={hovered} setHovered={setHovered} />
            </div>

            <svg
              viewBox="0 0 640 640"
              className="hidden h-auto w-full md:block"
              role="img"
              aria-label="ChargeGuard.AI architecture: six tiers from dispute ingest through the policy gate to the decision API and evidence packet."
            >
              <defs>
                <marker
                  id="arrow"
                  viewBox="0 0 10 10"
                  refX="8"
                  refY="5"
                  markerWidth="5"
                  markerHeight="5"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="rgba(148,163,184,0.45)" />
                </marker>
              </defs>

              {/* Tier rails */}
              {TIERS.map((tier) => (
                <g key={tier.label}>
                  <line
                    x1="46"
                    y1={tier.y + NODE_H / 2}
                    x2="596"
                    y2={tier.y + NODE_H / 2}
                    stroke="rgba(148,163,184,0.07)"
                    strokeWidth="1"
                  />
                  <text
                    x="596"
                    y={tier.y + NODE_H / 2 + 3}
                    textAnchor="end"
                    className="font-mono"
                    fontSize="8"
                    fill="rgba(148,163,184,0.35)"
                    letterSpacing="1.4"
                  >
                    {tier.label.toUpperCase()}
                  </text>
                </g>
              ))}

              {/* Edges, drawn under the nodes */}
              {EDGES.map(([fromId, toId]) => {
                const from = nodeById(fromId);
                const to = nodeById(toId);
                const isLit = hovered === fromId || hovered === toId;
                return (
                  <path
                    key={`${fromId}-${toId}`}
                    d={edgePath(from, to)}
                    fill="none"
                    stroke={
                      isLit ? 'rgba(16,185,129,0.6)' : 'rgba(148,163,184,0.22)'
                    }
                    strokeWidth={isLit ? 1.8 : 1.2}
                    markerEnd="url(#arrow)"
                    style={{ transition: 'stroke 0.25s, stroke-width 0.25s' }}
                  />
                );
              })}

              {/* Nodes */}
              {NODES.map((node) => {
                const kind = KIND[node.kind];
                const isHovered = hovered === node.id;
                const y = TIERS[node.tier].y;

                return (
                  <g
                    key={node.id}
                    onMouseEnter={() => setHovered(node.id)}
                    onMouseLeave={() => setHovered(null)}
                    onFocus={() => setHovered(node.id)}
                    onBlur={() => setHovered(null)}
                    tabIndex={0}
                    role="button"
                    aria-label={`${node.title}: ${node.subtitle}`}
                    style={{
                      cursor: 'pointer',
                      transform: isHovered ? 'translateY(-3px)' : 'none',
                      transition: 'transform 0.25s cubic-bezier(0.22,1,0.36,1)',
                      outline: 'none',
                    }}
                  >
                    <rect
                      x={node.x}
                      y={y}
                      width={node.w}
                      height={NODE_H}
                      rx="10"
                      fill={kind.fill}
                      stroke={kind.stroke}
                      strokeWidth={isHovered ? 1.8 : 1.1}
                      style={{ transition: 'stroke-width 0.25s' }}
                    />
                    <text
                      x={node.x + 14}
                      y={y + 25}
                      fontSize="12.5"
                      fill={kind.text}
                      fontWeight="600"
                      className="font-display"
                    >
                      {node.title}
                    </text>
                    <text
                      x={node.x + 14}
                      y={y + 42}
                      fontSize="9.5"
                      fill="rgba(148,163,184,0.75)"
                      className="font-mono"
                    >
                      {node.subtitle}
                    </text>
                  </g>
                );
              })}
            </svg>
          </motion.div>

          {/* Legend and detail panel */}
          <div className="flex flex-col gap-5">
            <div className="glass p-5">
              <div className="eyebrow mb-4">Colour encoding</div>
              <ul className="space-y-3">
                {Object.entries(KIND).map(([key, kind]) => (
                  <li key={key} className="flex items-start gap-3">
                    <span
                      className="mt-1 h-3 w-3 shrink-0 rounded-sm"
                      style={{
                        background: kind.fill,
                        border: `1.5px solid ${kind.stroke}`,
                      }}
                    />
                    <div>
                      <div
                        className="text-sm font-500"
                        style={{ color: kind.text }}
                      >
                        {kind.label}
                      </div>
                      <div className="text-xs leading-snug text-slateink/60">
                        {
                          {
                            io: 'Untrusted input and output.',
                            deterministic:
                              'Pure functions. Auditable by reading them.',
                            probabilistic:
                              'Returns a value it cannot justify.',
                            gate: 'The only component that decides.',
                          }[key]
                        }
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>

            {/* Detail panel. Reserves its own height so hovering nodes does not
                reflow the column and shove the diagram around. */}
            <div className="glass min-h-[230px] p-5">
              {active ? (
                <motion.div
                  key={active.id}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
                >
                  <div
                    className="eyebrow mb-2"
                    style={{ color: KIND[active.kind].text }}
                  >
                    {KIND[active.kind].label}
                  </div>
                  <h4 className="font-display text-base font-600 text-white">
                    {active.title}
                  </h4>
                  <code className="mt-1 block font-mono text-2xs text-slateink/60">
                    {active.module}
                  </code>
                  <p className="mt-3 text-sm leading-relaxed text-slateink/80 text-pretty">
                    {active.detail}
                  </p>
                </motion.div>
              ) : (
                <div className="flex h-full min-h-[190px] flex-col justify-center">
                  <p className="text-sm leading-relaxed text-slateink/50 text-pretty">
                    Hover or focus any node for detail.
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* The argument the diagram exists to make. */}
        <motion.p
          initial={{ opacity: 0, y: 14 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
          className="mx-auto mt-8 max-w-3xl text-center text-sm leading-relaxed text-slateink/70 text-pretty"
        >
          <span className="text-white">Read the edges.</span> Every path from an
          indigo node to an output passes through the coral one. The model and
          the language model are both upstream of a checkpoint they cannot
          bypass, and that checkpoint is ninety lines long — short enough that
          the economic guarantee can be verified by reading a single file.
        </motion.p>
      </div>
    </section>
  );
}
