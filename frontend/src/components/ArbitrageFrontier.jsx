/**
 * The hero visual: the product thesis rendered as a live, controllable plot.
 *
 * This is not a stock WebGL background. It is the decision rule `p* = λc / A`
 * drawn as a glowing frontier over a field of disputes, and it only exists
 * because the economics exist. Move the pointer and you move `λ`: the frontier
 * rises or falls and every dispute whose classification changes flips colour.
 * In about two seconds of mouse movement the mechanism becomes legible.
 *
 * Coordinate space
 *   X — dispute amount, logarithmic, ₹100 → ₹100,000
 *   Y — calibrated win probability, 0 → 1
 * The whole plot is tilted ~12° on X and ~4° on Y to read as dimensional
 * without distorting the curve.
 *
 * Every threshold comes from `lib/economics.js` — the same `decisionThreshold`
 * the simulator and the arbitrage visualiser call. A discrepancy would be a bug.
 *
 * Performance
 *   - 450 disputes in a single InstancedMesh, one draw call.
 *   - The render loop is throttled to ~45fps with a delta accumulator.
 *   - The frontier is recomputed on the CPU only when λ changes, never per frame.
 *   - The loop pauses entirely when the hero scrolls out of view.
 *   - Lazy-mounted by the Hero behind Suspense; the fallback is the static SVG,
 *     so there is never an empty box.
 */

import { Line } from '@react-three/drei';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';

import {
  AMOUNT_MAX,
  AMOUNT_MIN,
  DEFAULT_COST_INR,
  MARGIN_MAX,
  MARGIN_MIN,
  decisionThreshold,
  formatInr,
} from '../lib/economics.js';
import { prefersReducedMotion, usePointer } from '../hooks/usePointer.js';
import ArbitrageFrontierStatic from './ArbitrageFrontierStatic.jsx';

/* -------------------------------------------------------------------------- */
/* Constants                                                                  */
/* -------------------------------------------------------------------------- */

const COUNT = 450;
const PLOT_W = 9.2;
const PLOT_H = 6.4;
const FPS_STEP = 1 / 45;
const COST = DEFAULT_COST_INR;

const LOG_MIN = Math.log(AMOUNT_MIN);
const LOG_MAX = Math.log(AMOUNT_MAX);

const EMERALD = new THREE.Color('#62C6D7');
const CORAL = new THREE.Color('#E58B84');
const OBSIDIAN = new THREE.Color('#0A0D14');

/** Amount → world X. */
function worldX(amount) {
  const t = (Math.log(amount) - LOG_MIN) / (LOG_MAX - LOG_MIN);
  return (t - 0.5) * PLOT_W;
}
/** Probability → world Y. */
function worldY(p) {
  return (p - 0.5) * PLOT_H;
}

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Deterministic lognormal amount + centred probability. */
function drawDispute(rng) {
  const u1 = Math.max(1e-9, rng());
  const u2 = rng();
  const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  const amount = Math.min(AMOUNT_MAX, Math.max(AMOUNT_MIN, 2400 * Math.exp(0.95 * z)));
  const p = (rng() + rng() + rng()) / 3;
  return { amount, p };
}

const easeOutCubic = (t) => 1 - (1 - t) ** 3;

/* -------------------------------------------------------------------------- */
/* The frontier curve                                                         */
/* -------------------------------------------------------------------------- */

function frontierPoints(lambda) {
  const pts = [];
  const N = 120;
  for (let i = 0; i <= N; i += 1) {
    const t = i / N;
    const amount = Math.exp(LOG_MIN + t * (LOG_MAX - LOG_MIN));
    const threshold = Math.min(1, decisionThreshold(amount, COST, lambda));
    pts.push(new THREE.Vector3(worldX(amount), worldY(threshold), 0.02));
  }
  return pts;
}

/* -------------------------------------------------------------------------- */
/* The dispute field                                                          */
/* -------------------------------------------------------------------------- */

function DisputeField({ lambdaRef, statsRef, visibleRef }) {
  const meshRef = useRef(null);
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const scratch = useMemo(() => new THREE.Color(), []);
  const acc = useRef(0);

  // Per-instance state, allocated once.
  const disputes = useMemo(() => {
    const rng = mulberry32(0x51ed270b);
    const arr = [];
    for (let i = 0; i < COUNT; i += 1) {
      const { amount, p } = drawDispute(rng);
      arr.push({
        amount,
        p,
        // stagger initial spawn so the field assembles rather than popping in
        age: -(i / COUNT) * 2.2,
        life: 6 + rng() * 6,
        settleT: 0,
        pulse: 0,
        contest: true,
        color: new THREE.Color(),
        target: new THREE.Color(),
        seededColor: false,
      });
    }
    return arr;
  }, []);

  const respawn = (d, rng) => {
    const next = drawDispute(rng);
    d.amount = next.amount;
    d.p = next.p;
    d.age = 0;
    d.life = 6 + rng() * 6;
    d.settleT = 0;
    d.pulse = 0;
    d.seededColor = false;
  };

  const rng = useMemo(() => mulberry32(0xa1b2c3d4), []);

  useFrame((_, delta) => {
    const mesh = meshRef.current;
    if (!mesh || !visibleRef.current) return;

    acc.current += Math.min(delta, 0.1);
    if (acc.current < FPS_STEP) return;
    const dt = acc.current;
    acc.current = 0;

    const lambda = lambdaRef.current;
    let contestCount = 0;

    for (let i = 0; i < COUNT; i += 1) {
      const d = disputes[i];
      d.age += dt;

      // Recycle expired points so density stays constant.
      if (d.age > d.life) respawn(d, rng);

      // --- position: ease in from the left edge over ~0.9s ---
      const spawnX = -PLOT_W / 2 - 1.4;
      const targetX = worldX(d.amount);
      const targetY = worldY(d.p);
      let x;
      let y;
      let z;
      if (d.age < 0) {
        // pre-spawn stagger: hold off-screen
        x = spawnX;
        y = targetY + 0.6;
        z = 0.5;
      } else if (d.age < 0.9) {
        const e = easeOutCubic(d.age / 0.9);
        x = spawnX + (targetX - spawnX) * e;
        y = targetY + 0.6 * (1 - e);
        z = 0.5 * (1 - e);
        d.settleT = 0;
      } else {
        x = targetX;
        y = targetY;
        z = 0.02;
        if (d.settleT === 0) {
          d.settleT = d.age; // moment of arrival → trigger resolve + pulse
          d.pulse = 1;
        }
      }

      // --- classification against the live frontier ---
      const threshold = Math.min(1, decisionThreshold(d.amount, COST, lambda));
      const contest = d.p >= threshold;
      d.contest = contest;
      if (contest) contestCount += 1;
      const near = Math.abs(d.p - threshold) < 0.04;

      // target colour for this class; crossfade current → target (~180ms)
      d.target.copy(contest ? EMERALD : CORAL);
      if (!d.seededColor) {
        d.color.copy(d.target);
        d.seededColor = true;
      } else {
        d.color.lerp(d.target, Math.min(1, dt / 0.18));
      }

      // --- opacity / brightness ---
      // settled points fade to 35%; near-frontier points stay bright; the
      // arrival pulse briefly brightens. Opacity is expressed as brightness
      // against the obsidian background (per-instance alpha is not available on
      // an instanced basic material).
      let brightness;
      if (d.age < 0.9) {
        brightness = 0.15 + 0.85 * (d.age < 0 ? 0 : d.age / 0.9);
      } else {
        brightness = near ? 1 : 0.35;
      }
      if (d.pulse > 0) {
        brightness = Math.min(1.3, brightness + d.pulse * 0.6);
        d.pulse = Math.max(0, d.pulse - dt / 0.2);
      }

      scratch.copy(d.color).lerp(OBSIDIAN, 1 - Math.min(1, brightness));

      // --- radius ---
      const base = near ? 0.06 : 0.045;
      const pulseScale = 1 + d.pulse * 0.4;
      dummy.position.set(x, y, z);
      dummy.scale.setScalar(base * pulseScale);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
      mesh.setColorAt(i, scratch);
    }

    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;

    statsRef.current.contest = contestCount;
    statsRef.current.accept = COUNT - contestCount;
    statsRef.current.lambda = lambda;
  });

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, COUNT]} frustumCulled={false}>
      <sphereGeometry args={[1, 10, 10]} />
      <meshBasicMaterial toneMapped={false} transparent opacity={0.95} />
    </instancedMesh>
  );
}

/* -------------------------------------------------------------------------- */
/* The frontier line + territory washes                                       */
/* -------------------------------------------------------------------------- */

function Frontier({ lambdaRef }) {
  const [pts, setPts] = useState(() => frontierPoints(lambdaRef.current));
  const lastLambda = useRef(lambdaRef.current);

  // Recompute ONLY when λ changes meaningfully, never per frame.
  useFrame(() => {
    const lambda = lambdaRef.current;
    if (Math.abs(lambda - lastLambda.current) > 0.004) {
      lastLambda.current = lambda;
      setPts(frontierPoints(lambda));
    }
  });

  return (
    <group>
      {/* bloom pass — wide, dim, additive */}
      <Line
        points={pts}
        color="#62C6D7"
        lineWidth={7}
        transparent
        opacity={0.18}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
      {/* crisp frontier — the brightest element on the page */}
      <Line
        points={pts}
        color="#34D399"
        lineWidth={2.4}
        transparent
        opacity={0.95}
        depthWrite={false}
      />
    </group>
  );
}

/** Faint two-tone territory wash, so the plane reads as CONTEST vs ACCEPT. */
function Territories() {
  // Deliberately larger than the plot. A plane sized to PLOT_W x PLOT_H draws a
  // crisp rectangular edge across the hero, which reads as a stray UI box rather
  // than as two territories. Overrunning the frustum removes the edge entirely
  // and leaves only the tone difference above and below the frontier.
  const w = PLOT_W * 2.4;
  const h = PLOT_H * 2.2;
  return (
    <group position={[0, 0, -0.05]}>
      <mesh position={[0, h / 4, 0]}>
        <planeGeometry args={[w, h / 2]} />
        <meshBasicMaterial color="#62C6D7" transparent opacity={0.028} depthWrite={false} />
      </mesh>
      <mesh position={[0, -h / 4, 0]}>
        <planeGeometry args={[w, h / 2]} />
        <meshBasicMaterial color="#E58B84" transparent opacity={0.028} depthWrite={false} />
      </mesh>
    </group>
  );
}

/** Sparse axis hairlines with no full grid — a plot, not a chart. */
function Axes() {
  const geom = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const verts = new Float32Array([
      -PLOT_W / 2, -PLOT_H / 2, 0, -PLOT_W / 2, PLOT_H / 2, 0,
      -PLOT_W / 2, -PLOT_H / 2, 0, PLOT_W / 2, -PLOT_H / 2, 0,
    ]);
    g.setAttribute('position', new THREE.BufferAttribute(verts, 3));
    return g;
  }, []);
  return (
    <lineSegments geometry={geom}>
      <lineBasicMaterial color="#AEBFC7" transparent opacity={0.08} />
    </lineSegments>
  );
}

/* -------------------------------------------------------------------------- */
/* Scene driver: λ from pointer, idle oscillation                              */
/* -------------------------------------------------------------------------- */

function SceneDriver({ pointer, lambdaRef, visibleRef }) {
  const lastMove = useRef(0);
  const lastX = useRef(0);
  const { clock } = useThree();

  useFrame(() => {
    if (!visibleRef.current) return;
    const now = clock.elapsedTime;

    // Detect pointer movement.
    if (pointer.current.active && Math.abs(pointer.current.x - lastX.current) > 0.002) {
      lastMove.current = now;
      lastX.current = pointer.current.x;
    }

    const idleFor = now - lastMove.current;
    let target;
    if (pointer.current.active && idleFor < 3) {
      // pointer.x in [-1,1] → λ in [MARGIN_MIN, MARGIN_MAX]
      const t = (pointer.current.x + 1) / 2;
      target = MARGIN_MIN + t * (MARGIN_MAX - MARGIN_MIN);
    } else {
      // idle: gently oscillate between 1.15 and 1.35
      target = 1.25 + 0.1 * Math.sin(now * 0.5);
    }
    // smooth toward target so the frontier glides rather than snaps
    lambdaRef.current += (target - lambdaRef.current) * 0.08;
  });

  return null;
}

/**
 * Pull the camera to whatever distance fits the plot in the current canvas.
 *
 * The hero cell is portrait on desktop (a tall right-hand column) and landscape
 * on mobile (a wide band), so a fixed `z` clips the plot at one of them. This
 * solves for the distance that fits both axes with a margin, and re-solves on
 * resize. Without it the frontier ran off the right edge in the desktop column.
 */
function FitCamera() {
  const { camera, size } = useThree();

  useEffect(() => {
    const aspect = size.width / size.height;
    const vFov = (camera.fov * Math.PI) / 180;
    const margin = 1.12;

    // Distance needed for each axis independently; take the larger.
    const zForHeight = (PLOT_H * margin) / (2 * Math.tan(vFov / 2));
    const zForWidth = (PLOT_W * margin) / (2 * Math.tan(vFov / 2) * aspect);

    camera.position.z = Math.max(zForHeight, zForWidth);
    camera.updateProjectionMatrix();
  }, [camera, size.width, size.height]);

  return null;
}

/** Tilts the whole plot for the isometric read. */
function TiltedScene({ children }) {
  return (
    <group rotation={[(-12 * Math.PI) / 180, (4 * Math.PI) / 180, 0]}>
      {children}
    </group>
  );
}

/* -------------------------------------------------------------------------- */
/* The live readout (DOM overlay, not in the canvas)                           */
/* -------------------------------------------------------------------------- */

function Readout({ statsRef, visibleRef }) {
  const [state, setState] = useState({ lambda: 1.25, contest: 0, accept: 0 });

  useEffect(() => {
    // Poll the shared stats a few times a second — never per frame.
    const id = setInterval(() => {
      if (!visibleRef.current) return;
      setState({
        lambda: statsRef.current.lambda,
        contest: statsRef.current.contest,
        accept: statsRef.current.accept,
      });
    }, 180);
    return () => clearInterval(id);
  }, [statsRef, visibleRef]);

  return (
    <div className="pointer-events-none absolute bottom-4 right-4 z-20 rounded-xl border border-white/10 bg-obsidian/95 px-3 py-2">
      <div className="flex items-baseline gap-2 font-mono text-[11px]">
        <span className="text-slateink/50">λ</span>
        <span className="tabular text-white">{state.lambda.toFixed(2)}</span>
      </div>
      <div className="mt-1 flex items-center gap-3 font-mono text-[10px]">
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald" />
          <span className="tabular text-emerald">{state.contest}</span>
          <span className="text-slateink/45">contest</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-coral" />
          <span className="tabular text-coral">{state.accept}</span>
          <span className="text-slateink/45">accept</span>
        </span>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Annotation chips (DOM overlay, projected from world space)                  */
/* -------------------------------------------------------------------------- */

const CHIP_POOL = [
  { amount: 32000, p: 0.71 },
  { amount: 480, p: 0.28 },
  { amount: 12500, p: 0.63 },
  { amount: 2400, p: 0.41 },
  { amount: 60000, p: 0.22 },
];

/**
 * Two chips at most, promoted on a timer. Positions are precomputed in plot
 * space and mapped to the tilted canvas via a fixed 2-D approximation of the
 * projection — cheap, stable, and good enough for a label that only needs to
 * sit near its point. Chips are constrained to the right half so they never
 * cross the headline column.
 */
function Chips({ lambdaRef, visibleRef, bounds }) {
  const [active, setActive] = useState([]);

  useEffect(() => {
    let idx = 0;
    const promote = () => {
      if (!visibleRef.current) return;
      const a = CHIP_POOL[idx % CHIP_POOL.length];
      const b = CHIP_POOL[(idx + 2) % CHIP_POOL.length];
      idx += 1;
      setActive([
        { ...a, id: `${idx}-a` },
        { ...b, id: `${idx}-b` },
      ]);
    };
    promote();
    const id = setInterval(promote, 3200);
    return () => clearInterval(id);
  }, [visibleRef]);

  // Map plot coords → percentage within the canvas box. The tilt is shallow, so
  // a linear map with a small vertical skew reads correctly without projecting
  // through the actual camera.
  const place = (amount, p) => {
    const tx = (Math.log(amount) - LOG_MIN) / (LOG_MAX - LOG_MIN); // 0..1
    const ty = 1 - p; // 0 top .. 1 bottom
    // Squeeze into the right-hand band and apply a slight skew from the tilt.
    const left = Math.min(88, 34 + tx * 54);
    const top = Math.min(84, Math.max(8, 14 + ty * 66 - tx * 4));

    // Near the right edge, anchor the chip's right side instead of its centre.
    // A centred chip at left:88% still hangs ~9px past a 375px viewport, which
    // clips the CONTEST/ACCEPT verdict -- the one word the chip exists to show.
    const anchorRight = left > 62;
    return {
      style: {
        left: `${left}%`,
        top: `${top}%`,
        transform: anchorRight
          ? 'translate(-100%, -140%)'
          : 'translate(-50%, -140%)',
      },
      anchorRight,
    };
  };

  return (
    <div className="pointer-events-none absolute inset-0 z-20 overflow-hidden">
      {active.map((c) => {
        const lambda = lambdaRef.current;
        const threshold = Math.min(1, decisionThreshold(c.amount, COST, lambda));
        const contest = c.p >= threshold;
        const pos = place(c.amount, c.p);
        return (
          <div
            key={c.id}
            className="absolute max-w-[92%] animate-fade-up"
            style={pos.style}
          >
            <div className="flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-white/12 bg-obsidian/95 px-2 py-1 font-mono text-[10px]">
              <span className="text-white">{formatInr(c.amount)}</span>
              <span className="text-slateink/40">·</span>
              <span className="text-slateink/70">p {c.p.toFixed(2)}</span>
              <span className="text-slateink/40">·</span>
              <span className={contest ? 'text-emerald' : 'text-coral'}>
                {contest ? 'CONTEST' : 'ACCEPT'}
              </span>
            </div>
            {/* hairline leader down to the dot */}
            <span
              className="absolute top-full h-4 w-px bg-white/20"
              style={{
                left: pos.anchorRight ? 'calc(100% - 12px)' : '50%',
                transform: 'translateX(-50%)',
              }}
            />
          </div>
        );
      })}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Public component                                                            */
/* -------------------------------------------------------------------------- */

export default function ArbitrageFrontier() {
  const pointer = usePointer();
  const reduced = prefersReducedMotion();

  const lambdaRef = useRef(1.25);
  const statsRef = useRef({ lambda: 1.25, contest: 0, accept: 0 });
  const visibleRef = useRef(true);
  const containerRef = useRef(null);

  // Pause the render loop when the hero leaves the viewport.
  useEffect(() => {
    const node = containerRef.current;
    if (!node || typeof IntersectionObserver === 'undefined') return undefined;
    const obs = new IntersectionObserver(
      ([entry]) => {
        visibleRef.current = entry.isIntersecting;
      },
      { threshold: 0.05 },
    );
    obs.observe(node);
    return () => obs.disconnect();
  }, []);

  if (reduced) {
    return (
      <div ref={containerRef} className="h-full w-full">
        <ArbitrageFrontierStatic className="h-full w-full" />
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative h-full w-full">
      <Canvas
        dpr={[1, 1.75]}
        frameloop="always"
        camera={{ position: [0, 0, 12.5], fov: 42 }}
        gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
        style={{ pointerEvents: 'none' }}
      >
        <FitCamera />
        <SceneDriver pointer={pointer} lambdaRef={lambdaRef} visibleRef={visibleRef} />
        <TiltedScene>
          <Territories />
          <Axes />
          <DisputeField lambdaRef={lambdaRef} statsRef={statsRef} visibleRef={visibleRef} />
          <Frontier lambdaRef={lambdaRef} />
        </TiltedScene>
      </Canvas>

      <Chips lambdaRef={lambdaRef} visibleRef={visibleRef} />
      <Readout statsRef={statsRef} visibleRef={visibleRef} />

      {/* Hint that the scene is interactive. */}
      <div className="pointer-events-none absolute left-4 top-4 z-20 font-mono text-[10px] uppercase tracking-[0.16em] text-slateink/45">
        move to set λ
      </div>
    </div>
  );
}
