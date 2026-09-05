import { useCallback, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import clsx from 'clsx';
import { Cloud, CloudOff, Loader2 } from 'lucide-react';

import metrics from '../data/metrics.json';
import { SectionHeading } from './ui/GlassCard.jsx';
import DecisionBadge from './DecisionBadge.jsx';
import PacketPreview from './PacketPreview.jsx';
import ProbabilityGauge from './ProbabilityGauge.jsx';
import {
  PRESETS,
  decideOffline,
  renderOfflinePacket,
} from '../lib/presets.js';
import {
  DEFAULT_COST_INR,
  DEFAULT_RISK_MARGIN,
  formatInr,
} from '../lib/economics.js';

/**
 * The three-panel simulator.
 *
 * Live-first, static-capable. When `VITE_API_URL` points at a reachable
 * backend, every decision on this panel is the real `Decision` object returned
 * by `GET /v1/simulate/{preset}` — the same object the evaluation harness
 * scores. When it is not reachable, the page falls back to `lib/presets.js`,
 * which recomputes the gate trace and the EV rule client-side against recorded
 * model outputs.
 *
 * **Which mode is active is always shown.** A demo that silently degrades to
 * canned data while looking live is the single most dishonest thing a
 * submission like this can do, so the mode badge is placed at the top of the
 * panel rather than in a footnote.
 */

const API_BASE = import.meta.env.VITE_API_URL ?? '';
const PROBE_TIMEOUT_MS = 2500;

const COST = metrics?.config?.representment_cost_inr ?? DEFAULT_COST_INR;
const MARGIN = metrics?.config?.risk_margin ?? DEFAULT_RISK_MARGIN;
const MODEL_VERSION = metrics?.config?.model_version ?? null;
const CALIBRATION_MODE = metrics?.calibration_effect?.mode ?? 'identity';

/** Normalise the API's snake_case Decision into the shape the UI renders. */
function adaptApiResponse(payload) {
  const d = payload.decision;
  return {
    decision: {
      disputeId: d.dispute_id,
      action: d.action,
      winProbability: d.win_probability,
      threshold: d.threshold,
      thresholdReachable: payload.threshold_reachable,
      expectedValueInr: d.expected_value_inr,
      decidingReason: d.deciding_reason,
      gates: d.gates_evaluated.map((g) => ({
        name: g.gate_name,
        fired: g.fired,
        forcedAction: g.forced_action,
        rationale: g.rationale,
      })),
      latencyMs: d.latency_ms,
      modelVersion: d.model_version,
    },
    rawScore: payload.raw_score,
    shippedProbability: payload.calibrated_probability,
    isotonicProbability: payload.isotonic_probability,
    calibrationMode: payload.calibration_mode,
    explanation: payload.explanation,
    packet: payload.packet_preview
      ? {
          summary: payload.packet_preview.summary,
          evidenceNarrative: payload.packet_preview.evidence_narrative,
          schemeArgument: payload.packet_preview.scheme_argument,
          citedArtifacts: payload.packet_preview.cited_artifacts,
          source: payload.packet_preview.source,
          fallbackReason: '',
          html: payload.packet_preview.html,
          pdfAvailable: payload.packet_preview.pdf_available,
        }
      : null,
  };
}

/** Build the offline result for a preset under the selected calibration map. */
function buildOfflineResult(preset, useIsotonic) {
  const pWin = useIsotonic
    ? preset.recorded.isotonicProbability
    : preset.recorded.shippedProbability;

  const decision = decideOffline(preset, pWin, COST, MARGIN);

  return {
    decision,
    rawScore: preset.recorded.rawScore,
    shippedProbability: preset.recorded.shippedProbability,
    isotonicProbability: preset.recorded.isotonicProbability,
    calibrationMode: CALIBRATION_MODE,
    explanation: null,
    packet:
      decision.action === 'CONTEST' ? renderOfflinePacket(preset) : null,
  };
}

function ModeBadge({ mode, apiBase }) {
  const config = {
    live: {
      icon: Cloud,
      tone: 'border-emerald/35 bg-emerald-dim text-emerald',
      label: 'Live API',
      detail: apiBase || 'same origin',
    },
    offline: {
      icon: CloudOff,
      tone: 'border-white/15 bg-white/[0.04] text-slateink',
      label: 'Offline',
      detail: 'client-side gates · recorded model output',
    },
    probing: {
      icon: Loader2,
      tone: 'border-white/15 bg-white/[0.04] text-slateink/70',
      label: 'Connecting',
      detail: 'probing /health',
    },
  }[mode];

  const Icon = config.icon;

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-2 rounded-lg border px-2.5 py-1.5',
        config.tone,
      )}
    >
      <Icon size={12} className={mode === 'probing' ? 'animate-spin' : ''} />
      <span className="font-mono text-[10px] uppercase tracking-wider">
        {config.label}
      </span>
      <span className="font-mono text-[10px] text-slateink/50">
        {config.detail}
      </span>
    </span>
  );
}

/**
 * Skeleton for the scoring panels.
 *
 * Mirrors the real layout's block sizes so the transition from loading to
 * loaded moves nothing. A spinner in a centred box would be smaller and easier,
 * and would guarantee a layout shift the moment the content arrived.
 */
function ScoringSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-hidden="true">
      <div className="glass p-5">
        <div className="skeleton h-3 w-28" />
        <div className="skeleton mx-auto mt-6 h-[200px] w-[200px] rounded-full" />
        <div className="skeleton mt-6 h-14 w-full" />
      </div>
      <div className="glass p-5">
        <div className="skeleton h-3 w-32" />
        <div className="skeleton mt-3 h-3 w-full" />
        <div className="skeleton mt-2 h-3 w-4/5" />
      </div>
    </div>
  );
}

function EvidenceRow({ label, value, tone = 'default' }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-white/[0.06] py-2 last:border-0">
      <span className="text-xs text-slateink/60">{label}</span>
      <span
        className={clsx(
          'text-right font-mono text-xs tabular',
          tone === 'good' && 'text-emerald',
          tone === 'bad' && 'text-coral',
          tone === 'default' && 'text-white',
        )}
      >
        {value}
      </span>
    </div>
  );
}

export default function Simulator() {
  const [activeKey, setActiveKey] = useState(PRESETS[0].key);
  const [useIsotonic, setUseIsotonic] = useState(false);
  const [mode, setMode] = useState('probing');
  const [liveResults, setLiveResults] = useState({});
  const [loading, setLoading] = useState(false);

  const preset = useMemo(
    () => PRESETS.find((p) => p.key === activeKey) ?? PRESETS[0],
    [activeKey],
  );

  // Skeleton only while a *live* fetch is outstanding and nothing is cached for
  // this preset. Offline mode resolves synchronously, so it never flashes one.
  const showSkeleton = loading && mode === 'live' && !liveResults[activeKey];

  // Probe the API once at mount. AbortController rather than a bare fetch, so
  // a backend that accepts the connection and then hangs does not leave the
  // panel stuck in "connecting" indefinitely.
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);

    fetch(`${API_BASE}/health`, { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : Promise.reject()))
      .then((payload) => {
        if (cancelled) return;
        // A reachable API with no model loaded cannot score anything, so treat
        // that as offline rather than showing a panel that 503s on every click.
        setMode(payload?.capabilities?.model?.available ? 'live' : 'offline');
      })
      .catch(() => {
        if (!cancelled) setMode('offline');
      })
      .finally(() => clearTimeout(timer));

    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, []);

  // Fetch a preset from the live API, caching per key.
  const fetchLive = useCallback(
    async (key) => {
      if (mode !== 'live' || liveResults[key]) return;
      setLoading(true);
      try {
        const response = await fetch(`${API_BASE}/v1/simulate/${key}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        setLiveResults((prev) => ({ ...prev, [key]: adaptApiResponse(payload) }));
      } catch {
        // A failure mid-session degrades the whole panel rather than leaving
        // one preset broken, so the mode badge stays truthful.
        setMode('offline');
      } finally {
        setLoading(false);
      }
    },
    [mode, liveResults],
  );

  useEffect(() => {
    fetchLive(activeKey);
  }, [activeKey, fetchLive]);

  // Live results come from the server, which decides using the map that
  // actually shipped -- that is the production path. Flipping the toggle asks
  // what the isotonic map would have produced instead; that counterfactual is
  // recomputed client-side, so the server never issues a decision from a map
  // it did not ship.
  const result = useMemo(() => {
    const live = liveResults[activeKey];
    if (mode === 'live' && live) {
      if (!useIsotonic) return live;
      const counterfactual = decideOffline(
        preset,
        live.isotonicProbability,
        COST,
        MARGIN,
      );
      return { ...live, decision: counterfactual };
    }
    return buildOfflineResult(preset, useIsotonic);
  }, [mode, liveResults, activeKey, useIsotonic, preset]);

  const e = preset.evidence;

  return (
    <section id="simulator" className="relative border-y border-white/[0.06] bg-black/10 py-20 sm:py-24">
      <div className="mx-auto max-w-content px-5 sm:px-8">
        <div className="flex flex-wrap items-end justify-between gap-5">
          <SectionHeading
            eyebrow="Simulator"
            title="Test the decision engine."
            lead="Select a dispute, inspect the evidence, and follow the path to the final action."
          />
          <div className="flex items-center gap-3 pb-1">
            <ModeBadge mode={mode} apiBase={API_BASE} />
            {loading && <span className="font-mono text-[10px] text-slateink/50">scoring…</span>}
          </div>
        </div>

        {mode === 'offline' && (
          <div className="mt-5 inline-flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 font-mono text-[10px] text-slateink/65">
            <span className="text-white">Offline mode</span>
            <span>· client-side gates</span>
            <span>· recorded {MODEL_VERSION ?? 'model'} output</span>
            <span className="text-emerald">· make serve for live scoring</span>
          </div>
        )}

        <div className="mt-8 grid gap-3 md:grid-cols-3">
          {PRESETS.map((item) => {
            const isActive = item.key === activeKey;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => setActiveKey(item.key)}
                aria-pressed={isActive}
                className={clsx(
                  'relative rounded-xl border p-4 text-left transition-colors',
                  'focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-emerald',
                  isActive
                    ? 'border-emerald/45 bg-emerald-dim'
                    : 'border-white/10 bg-white/[0.025] hover:border-white/20 hover:bg-white/[0.05]',
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <span className={clsx('font-display text-sm font-600', isActive ? 'text-white' : 'text-slateink')}>
                    {item.label}
                  </span>
                  {isActive && <span className="h-2 w-2 rounded-full bg-emerald" />}
                </div>
                <div className="mt-3 flex items-center justify-between gap-2 font-mono text-[10px] text-slateink/55">
                  <span>{item.dispute.reasonCode}</span>
                  <span>{formatInr(item.dispute.amountInr)}</span>
                </div>
              </button>
            );
          })}
        </div>

        <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(210px,0.72fr)_minmax(320px,1fr)_minmax(340px,1.12fr)]">
          <div className="order-3 space-y-5 lg:order-1">
            <div className="glass p-4">
              <div className="eyebrow mb-2.5">Evidence bundle</div>
              <div>
                <EvidenceRow label="Cardholder" value={e.customerName} />
                <EvidenceRow label="Order total" value={formatInr(e.orderTotal)} />
                <EvidenceRow label="3-D Secure" value={e.threeDsStatus} tone={e.threeDsStatus === 'AUTHENTICATED' ? 'good' : 'bad'} />
                <EvidenceRow label="AVS / CVV" value={`${e.avsMatch ? '✓' : '✗'} / ${e.cvvMatch ? '✓' : '✗'}`} tone={e.avsMatch && e.cvvMatch ? 'good' : 'bad'} />
                <EvidenceRow label="Proof of delivery" value={e.podStatus} tone={e.podStatus === 'VERIFIED' ? 'good' : e.podStatus === 'ABSENT' ? 'bad' : 'default'} />
                {e.podStatus !== 'ABSENT' && (
                  <>
                    <EvidenceRow label="Signature" value={e.podSignature ? 'captured' : 'not captured'} tone={e.podSignature ? 'good' : 'bad'} />
                    <EvidenceRow label="OCR confidence" value={`${Math.round(e.podOcrConfidence * 100)}%`} />
                    <EvidenceRow label="Carrier scans" value={String(e.podScanCount)} />
                  </>
                )}
                <EvidenceRow label="Checkout IP" value={e.ipCity} tone={e.ipOffshore ? 'bad' : 'default'} />
                <EvidenceRow label="Account age" value={e.accountAgeDays < 1 ? `${Math.round(e.accountAgeDays * 24)} h` : `${Math.round(e.accountAgeDays)} d`} tone={e.accountAgeDays < 7 ? 'bad' : 'default'} />
                <EvidenceRow label="Prior disputes" value={String(e.priorDisputeCount)} tone={e.priorDisputeCount >= 3 ? 'bad' : 'default'} />
              </div>
            </div>
          </div>

          <div className="order-1 space-y-5 lg:order-2">
            {showSkeleton ? (
              <ScoringSkeleton />
            ) : (
              <>
                <div className="glass p-5">
                  <div className="mb-3 flex items-start justify-between gap-3">
                    <div>
                      <div className="eyebrow mb-1">Win probability</div>
                      <div className="font-display text-sm text-slateink/70">{formatInr(preset.dispute.amountInr)} · {preset.dispute.reasonLabel}</div>
                    </div>
                    <span className="rounded-md bg-white/[0.05] px-2 py-1 font-mono text-[10px] text-slateink/60">{preset.expectedPath}</span>
                  </div>
                  <ProbabilityGauge
                    shippedProbability={result.shippedProbability}
                    isotonicProbability={result.isotonicProbability}
                    calibrationMode={result.calibrationMode ?? CALIBRATION_MODE}
                    threshold={result.decision.threshold}
                    thresholdReachable={result.decision.thresholdReachable}
                    useIsotonic={useIsotonic}
                    onToggleIsotonic={() => setUseIsotonic((on) => !on)}
                    modelVersion={MODEL_VERSION}
                  />
                </div>
                <details className="glass group p-4">
                  <summary className="cursor-pointer list-none text-xs text-slateink/75 marker:hidden">
                    <span className="group-open:text-white">Why this case?</span>
                    <span className="ml-2 text-slateink/40 group-open:hidden">+</span>
                  </summary>
                  <p className="mt-3 text-xs leading-relaxed text-slateink/70 text-pretty">{preset.narrative}</p>
                </details>
              </>
            )}
          </div>

          <div className="order-2 space-y-5 lg:order-3">
            <DecisionBadge decision={result.decision} cost={COST} />
            <PacketPreview
              packet={result.packet}
              decision={result.decision}
              preset={preset}
              apiBase={API_BASE}
              live={mode === 'live'}
            />
          </div>
        </div>
      </div>
    </section>
  );
}
