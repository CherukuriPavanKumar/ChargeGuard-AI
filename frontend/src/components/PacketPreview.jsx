import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
  AlertCircle,
  Check,
  Download,
  FileText,
  Loader2,
  Lock,
  Sparkles,
} from 'lucide-react';

import { formatInr } from '../lib/economics.js';

/**
 * The representment document, previewed.
 *
 * Rendered only when the decision was CONTEST — building a filing for a dispute
 * the policy conceded would burn an LLM call on a document nobody submits, and
 * would blur the one-way boundary between deciding and documenting.
 *
 * The `source` badge is load-bearing rather than decorative. A merchant
 * reviewing a filing is entitled to know whether the prose was written by a
 * language model or assembled from deterministic templates, and if the model
 * was skipped, why. Both paths produce a valid filing; only one of them is
 * fluent.
 */

const ARTIFACT_DESCRIPTIONS = {
  ORDER_RECORD: 'Merchant order record: line items, totals, addresses.',
  AUTHORISATION_AVS_RESULT: 'Address Verification Service result.',
  AUTHORISATION_CVV_RESULT: 'CVV2/CVC2 verification result.',
  AUTHORISATION_3DS_RESULT: '3-D Secure outcome and liability position.',
  SESSION_LOG: 'Checkout telemetry: IP, device, timestamps.',
  POD_SLIP: 'Carrier proof-of-delivery slip as parsed.',
  POD_DELIVERY_SIGNATURE: 'Signature captured at handover.',
  POD_DELIVERY_TIMESTAMP: 'Delivery timestamp on the carrier slip.',
  CARRIER_SCAN_TRAIL: 'Carrier network scan events.',
  MERCHANT_CUSTOMER_COMMS_LOG: 'Logged merchant-to-cardholder contacts.',
  REFUND_LEDGER_ENTRY: 'Refund ledger entry against this transaction.',
  CARDHOLDER_DISPUTE_HISTORY: 'Prior disputes by this cardholder.',
};

function describeArtifact(identifier) {
  const match = Object.keys(ARTIFACT_DESCRIPTIONS).find((prefix) =>
    identifier.startsWith(prefix),
  );
  return match
    ? ARTIFACT_DESCRIPTIONS[match]
    : 'Supporting record held by the merchant.';
}

/**
 * Offer the rendered HTML as a download.
 *
 * Built as a Blob URL at click time rather than held as a data URI, so a large
 * document does not sit in memory for the life of the page.
 */
function downloadHtml(html, disputeId) {
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `representment_${disputeId}.html`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

/**
 * Drive the asynchronous PDF job: queue it, then poll until it settles.
 *
 * The packet shown inline is a *preview* rendered in memory by the simulate
 * endpoint. This runs the genuine background job the production route uses —
 * language model, template fallback, and the native PDF attempt — which is why
 * it needs a progress state at all. Polling stops on `done`, on `failed`, and on
 * a deadline, so a wedged job cannot leave the panel spinning forever.
 */
function usePacketJob(apiBase, presetKey, enabled) {
  const [state, setState] = useState({ phase: 'idle' });
  const timer = useRef(null);

  // Any change of preset invalidates an in-flight job for the previous one.
  useEffect(() => {
    setState({ phase: 'idle' });
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [presetKey]);

  const start = async () => {
    if (!enabled) return;
    setState({ phase: 'queued' });

    try {
      const res = await fetch(`${apiBase}/v1/simulate/${presetKey}/packet`, {
        method: 'POST',
      });
      if (res.status === 409) {
        setState({
          phase: 'error',
          message: 'The policy conceded this dispute; no packet is generated.',
        });
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const { job_id: jobId } = await res.json();
      const deadline = Date.now() + 30000;

      const poll = async () => {
        if (Date.now() > deadline) {
          setState({ phase: 'error', message: 'Timed out after 30s.' });
          return;
        }
        try {
          const jr = await fetch(`${apiBase}/v1/disputes/jobs/${jobId}`);
          if (!jr.ok) throw new Error(`HTTP ${jr.status}`);
          const job = await jr.json();

          if (job.status === 'done') {
            setState({ phase: 'done', job });
            return;
          }
          if (job.status === 'failed') {
            setState({ phase: 'error', message: job.error ?? 'Job failed.' });
            return;
          }
          setState({ phase: job.status });
          timer.current = setTimeout(poll, 500);
        } catch (err) {
          setState({ phase: 'error', message: String(err.message ?? err) });
        }
      };

      timer.current = setTimeout(poll, 350);
    } catch (err) {
      setState({ phase: 'error', message: String(err.message ?? err) });
    }
  };

  return { ...state, start };
}

export default function PacketPreview({
  packet,
  decision,
  preset,
  apiBase = '',
  live = false,
}) {
  const [expanded, setExpanded] = useState(false);
  const job = usePacketJob(apiBase, preset?.key, live);

  // The one case where a preview is deliberately absent.
  if (!packet) {
    return (
      <div className="glass p-5">
        <div className="mb-3 flex items-center gap-2.5">
          <Lock size={15} className="text-slateink/50" />
          <h3 className="font-display text-sm font-600 text-white">
            No representment packet
          </h3>
        </div>
        <p className="text-xs leading-relaxed text-slateink/65 text-pretty">
          The decision was <span className="text-coral">ACCEPT</span>, so no
          filing is assembled. Packet generation runs downstream of the decision
          and only on CONTEST — the synthesiser is never handed the win
          probability, the threshold, or the action, and its function signature
          has no parameter that could carry them.
        </p>
      </div>
    );
  }

  const isLlm = packet.source === 'LLM';

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
      className="glass overflow-hidden"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-5 py-3.5">
        <div className="flex items-center gap-2.5">
          <FileText size={15} className="text-emerald" />
          <h3 className="font-display text-sm font-600 text-white">
            Representment packet
          </h3>
        </div>

        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 font-mono text-[9px] uppercase tracking-wider ${
              isLlm
                ? 'bg-indigo/20 text-indigo'
                : 'bg-slateink-dim text-slateink'
            }`}
          >
            {isLlm && <Sparkles size={9} />}
            {isLlm ? 'LLM narrative' : 'Template narrative'}
          </span>

          <button
            type="button"
            onClick={() => downloadHtml(packet.html, decision.disputeId)}
            className="tap-44 inline-flex items-center gap-1.5 rounded-md border border-white/15 px-2.5 py-1 font-mono text-[10px] text-slateink transition-colors hover:border-white/30 hover:text-white"
          >
            <Download size={10} />
            HTML
          </button>
        </div>
      </div>

      {/* Asynchronous PDF job. Queued, polled, and reported honestly --
          including that the PDF engine may be unavailable, in which case the
          job still succeeds and produces HTML. */}
      <div className="border-b border-white/10 px-5 py-3">
        {job.phase === 'idle' && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-[11px] text-slateink/60">
              {live
                ? 'Render the full packet through the background job.'
                : 'Background rendering needs the live API.'}
            </span>
            <button
              type="button"
              onClick={job.start}
              disabled={!live}
              className="tap-44 inline-flex min-h-[32px] items-center gap-1.5 rounded-md border border-white/15 px-2.5 py-1 font-mono text-[10px] text-slateink transition-colors hover:border-white/30 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              Generate PDF
            </button>
          </div>
        )}

        {(job.phase === 'queued' || job.phase === 'running') && (
          <div className="flex items-center gap-2.5">
            <Loader2 size={13} className="animate-spin text-indigo" />
            <span className="font-mono text-[10px] uppercase tracking-wider text-indigo">
              {job.phase}
            </span>
            <span className="text-[11px] text-slateink/55">
              {job.phase === 'queued'
                ? 'Job accepted, waiting for a worker.'
                : 'Synthesising the narrative and rendering the document.'}
            </span>
          </div>
        )}

        {job.phase === 'done' && (
          <div className="flex flex-wrap items-center gap-2.5">
            <Check size={13} className="text-emerald" />
            <span className="font-mono text-[10px] uppercase tracking-wider text-emerald">
              rendered
            </span>
            <span className="text-[11px] text-slateink/60">
              {job.job?.packet?.pdf_path
                ? 'PDF written on the server.'
                : 'HTML only — the PDF engine is unavailable in this environment, which the schema admits rather than faking.'}
            </span>
          </div>
        )}

        {job.phase === 'error' && (
          <div className="flex items-start gap-2.5">
            <AlertCircle size={13} className="mt-0.5 shrink-0 text-slateink/50" />
            <span className="text-[11px] leading-relaxed text-slateink/60">
              {job.message}
            </span>
          </div>
        )}
      </div>

      {/* Document body */}
      <div className="space-y-4 px-5 py-4">
        <section>
          <div className="eyebrow mb-1.5">1 · Case summary</div>
          <p className="text-xs leading-relaxed text-slateink/85 text-pretty">
            {packet.summary}
          </p>
        </section>

        <section className="rounded-lg border-l-2 border-emerald/50 bg-emerald-dim px-3.5 py-3">
          <div className="eyebrow mb-1.5 text-emerald/80">
            2 · Compelling evidence
          </div>
          <p
            className={`text-xs leading-relaxed text-slateink/85 text-pretty ${
              expanded ? '' : 'line-clamp-4'
            }`}
          >
            {packet.evidenceNarrative}
          </p>
        </section>

        <section>
          <div className="eyebrow mb-1.5">
            3 · Scheme argument · {preset?.dispute?.reasonCode ?? ''}
          </div>
          <p
            className={`text-xs leading-relaxed text-slateink/85 text-pretty ${
              expanded ? '' : 'line-clamp-3'
            }`}
          >
            {packet.schemeArgument}
          </p>
        </section>

        <button
          type="button"
          onClick={() => setExpanded((open) => !open)}
          className="tap-44 inline-flex items-center font-mono text-[10px] uppercase tracking-wider text-emerald transition-colors hover:text-emerald/80"
        >
          {expanded ? '− collapse' : '+ read in full'}
        </button>

        {/* Artifact index. Every cited identifier was checked against the
            bundle before this rendered; anything unrecognised rejects the whole
            draft and falls back to templates. */}
        <section className="border-t border-white/10 pt-4">
          <div className="eyebrow mb-2.5">
            4 · Artifact index · {packet.citedArtifacts.length} cited
          </div>
          <ul className="space-y-1.5">
            {packet.citedArtifacts.map((identifier) => (
              <li key={identifier} className="flex items-start gap-2.5">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-emerald" />
                <div className="min-w-0">
                  <code className="font-mono text-[10px] text-white">
                    {identifier}
                  </code>
                  <div className="text-[11px] leading-snug text-slateink/55">
                    {describeArtifact(identifier)}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {/* Footer: the hallucination guard, stated where it belongs. */}
      <div className="border-t border-white/10 bg-black/20 px-5 py-3">
        <p className="text-[11px] leading-relaxed text-slateink/60 text-pretty">
          Every artifact identifier above was verified against the evidence
          bundle before rendering. A citation to a document the merchant does not
          hold is a false statement to a financial institution, so a draft
          containing one is discarded in full — partial acceptance is not
          offered, because a model that invented one citation cannot be trusted
          to have grounded the surrounding prose.
          {!isLlm && packet.fallbackReason && (
            <>
              {' '}
              <span className="text-slateink/80">
                This narrative came from the deterministic templates
                {packet.fallbackReason ? `: ${packet.fallbackReason}` : ''}.
              </span>
            </>
          )}
          {packet.pdfAvailable === false && (
            <>
              {' '}
              PDF rendering is unavailable in this environment, so the packet is
              HTML only — the schema admits that case rather than claiming a PDF
              that does not exist.
            </>
          )}
        </p>
      </div>
    </motion.div>
  );
}
