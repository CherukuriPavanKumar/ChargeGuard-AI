import { useState } from 'react';
import { motion } from 'framer-motion';
import { Check, Copy, Fingerprint, Terminal } from 'lucide-react';

import metrics from '../data/metrics.json';
import { SectionHeading } from './ui/GlassCard.jsx';

/**
 * The verification section.
 *
 * This exists because a technical reviewer's first instinct on seeing
 * impressive metrics is to doubt them — correctly. Rather than arguing, this
 * section gives them the shortest path to checking: three commands, a
 * provenance stamp they can compare against, and a plain statement of what the
 * numbers are and are not.
 *
 * Every value in the stamp is read from `metrics.json`, written by
 * `eval/harness.py`. Nothing here is hardcoded — if the harness has not run,
 * the stamp says so rather than displaying a plausible-looking hash.
 */

const COMMANDS = [
  {
    cmd: 'make install',
    note: 'Backend venv + pip, frontend npm.',
    runtime: '~3–5 min',
  },
  {
    cmd: 'make all',
    note: 'Generate 20,000 disputes → train → evaluate → test.',
    runtime: '~3–4 min',
  },
  {
    cmd: 'make verify',
    note: 'Re-run the harness and diff it against the committed metrics.json.',
    runtime: '~40 s',
  },
];

function CommandRow({ cmd, note, runtime }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(cmd);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard is unavailable in some embedded contexts. The command is
      // selectable text regardless, so failing quietly is correct.
      setCopied(false);
    }
  };

  return (
    <li className="flex flex-col gap-2 border-b border-white/[0.06] py-3 last:border-0 sm:flex-row sm:items-center sm:gap-4">
      <div className="flex min-w-0 flex-1 items-center gap-2.5 rounded-lg border border-white/10 bg-black/35 px-3 py-2.5">
        <Terminal size={14} className="shrink-0 text-emerald" />
        <code className="min-w-0 flex-1 truncate font-mono text-sm text-emerald">
          {cmd}
        </code>
        <button
          type="button"
          onClick={copy}
          aria-label={`Copy "${cmd}" to clipboard`}
          className="tap-44 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-white/10 text-slateink transition-colors hover:border-white/25 hover:text-white"
        >
          {copied ? (
            <Check size={13} className="text-emerald" />
          ) : (
            <Copy size={13} />
          )}
        </button>
      </div>
      <div className="sm:w-64 sm:shrink-0">
        <div className="text-xs leading-snug text-slateink/70">{note}</div>
        <div className="mt-0.5 font-mono text-[10px] text-slateink/45">
          {runtime}
        </div>
      </div>
    </li>
  );
}

function StampRow({ label, value, mono = true, truncate = false }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-white/[0.06] py-2.5 last:border-0">
      <dt className="shrink-0 text-xs text-slateink/60">{label}</dt>
      <dd
        className={`min-w-0 text-right text-xs text-white ${
          mono ? 'font-mono tabular' : ''
        } ${truncate ? 'truncate' : 'break-all'}`}
        title={String(value)}
      >
        {value}
      </dd>
    </div>
  );
}

export default function VerifySection() {
  const prov = metrics?.provenance ?? {};
  const cfg = metrics?.config ?? {};
  const hasMetrics = (metrics?.test_set_size ?? 0) > 0;
  const hasStamp = Boolean(prov.content_sha256);

  return (
    <section id="verify" className="relative py-24 sm:py-32">
      <div className="mx-auto max-w-content px-5 sm:px-8">
        <SectionHeading
          eyebrow="Verification"
          title="Don't take the numbers on trust. Reproduce them."
          lead="Every figure on this page comes from one artifact that one command regenerates. If a regenerated run disagrees with the committed one, that is a bug, and this is how you find out."
        />

        <div className="mt-12 grid gap-5 lg:grid-cols-[1.35fr_1fr]">
          {/* ---------------------------------------------------------------- */}
          {/* Commands                                                         */}
          {/* ---------------------------------------------------------------- */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-80px' }}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className="glass p-5 sm:p-6"
          >
            <h3 className="font-display text-base font-600 text-white">
              Three commands, about eight minutes
            </h3>
            <p className="mt-1.5 text-xs leading-relaxed text-slateink/65">
              From a clean checkout. On Windows, where GNU make is not installed
              by default, substitute{' '}
              <code className="font-mono text-[11px] text-slateink/85">
                .\make.ps1
              </code>{' '}
              — the same targets are implemented in PowerShell.
            </p>

            <ul className="mt-4">
              {COMMANDS.map((c) => (
                <CommandRow key={c.cmd} {...c} />
              ))}
            </ul>

            <div className="mt-5 rounded-lg border border-emerald/20 bg-emerald-dim p-3.5">
              <p className="text-xs leading-relaxed text-slateink/85">
                <span className="font-mono text-emerald">make verify</span>{' '}
                re-runs the full evaluation and compares a SHA-256 digest of
                every reproducible field against the committed artifact. It
                excludes exactly two things —{' '}
                <code className="font-mono text-[11px] text-white">
                  generated_at
                </code>{' '}
                and{' '}
                <code className="font-mono text-[11px] text-white">
                  latency_ms
                </code>{' '}
                — because a wall-clock stamp and a machine-speed measurement are
                legitimately run-dependent. A difference in any other field is a
                genuine reproducibility failure and the check prints which block
                diverged.
              </p>
            </div>
          </motion.div>

          {/* ---------------------------------------------------------------- */}
          {/* Reproducibility stamp                                            */}
          {/* ---------------------------------------------------------------- */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-80px' }}
            transition={{ duration: 0.5, delay: 0.06, ease: [0.22, 1, 0.36, 1] }}
            className="glass p-5 sm:p-6"
          >
            <div className="mb-4 flex items-center gap-2.5">
              <Fingerprint size={15} className="text-emerald" />
              <h3 className="font-display text-base font-600 text-white">
                Reproducibility stamp
              </h3>
            </div>

            {hasStamp ? (
              <>
                <dl>
                  <StampRow label="Git SHA" value={prov.git_sha} />
                  <StampRow label="Master seed" value={prov.master_seed} />
                  <StampRow label="Split seed" value={prov.split_seed} />
                  <StampRow
                    label="Test set"
                    value={`${Number(prov.test_set_size).toLocaleString('en-IN')} disputes`}
                  />
                  <StampRow label="Model" value={prov.model_version} />
                  <StampRow label="Features" value={prov.feature_version} />
                  <StampRow
                    label="Corpus epoch"
                    value={String(prov.corpus_epoch).slice(0, 10)}
                  />
                </dl>

                <div className="mt-4 border-t border-white/10 pt-3.5">
                  <div className="eyebrow mb-1.5">SHA-256 of metrics.json</div>
                  <code className="block break-all font-mono text-[10px] leading-relaxed text-emerald">
                    {prov.content_sha256}
                  </code>
                  <p className="mt-2 text-[11px] leading-relaxed text-slateink/50">
                    {prov.digest_note}
                  </p>
                </div>

                {String(prov.git_sha).startsWith('not-a-git') && (
                  <p className="mt-3 rounded-lg border border-white/10 bg-white/[0.03] p-2.5 text-[11px] leading-relaxed text-slateink/60">
                    This build was produced from a working directory that is not
                    under version control, so there is no commit to cite. Stated
                    rather than filled in with a placeholder — the seeds and the
                    content digest still pin the result exactly.
                  </p>
                )}
              </>
            ) : (
              <p className="text-sm leading-relaxed text-slateink/60">
                No provenance stamp in the artifact. Run{' '}
                <code className="font-mono text-emerald">make all</code> to
                generate one.
              </p>
            )}
          </motion.div>
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* The honesty block                                                  */}
        {/* ------------------------------------------------------------------ */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-80px' }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
          className="glass mt-5 p-5 sm:p-6"
        >
          <h3 className="font-display text-base font-600 text-white">
            What these numbers are, and what they are not
          </h3>

          <div className="mt-4 max-w-3xl space-y-3.5 text-sm leading-relaxed text-slateink/80 text-pretty">
            <p>
              The data is synthetic. There is no real chargeback corpus in this
              repository. The generator is at{' '}
              <code className="font-mono text-xs text-slateink">
                backend/data_gen/generator.py
              </code>{' '}
              and is written to be read — it states its coefficients, its
              unobservable terms, and its noise model in the module docstring.
            </p>
            <p>
              Features are noisy observations of a latent winnability process.
              Two of the drivers of the outcome — an unobservable friendly-fraud
              indicator carrying a coefficient of 1.55, and a Normal(0, 0.85)
              error term — appear in no feature. Achievable AUC is therefore
              bounded by construction. The model never sees the latent.
            </p>
            <p>
              The train/test split seeds are frozen and committed. A regenerated
              run produces byte-identical metrics on any machine, which is what{' '}
              <code className="font-mono text-xs text-slateink">make verify</code>{' '}
              checks.
            </p>
            <p className="text-white">
              These numbers are not a claim about production performance on real
              Razorpay data. They are a measurement of how much of the
              economically available money a policy layer captures, given a
              genuinely uncertain and well-calibrated probability, on a corpus
              whose generating process is fully specified and open to inspection.
            </p>
          </div>

          {hasMetrics && (
            <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-1.5 border-t border-white/10 pt-4 font-mono text-[10px] text-slateink/45">
              <span>c = ₹{cfg.representment_cost_inr}</span>
              <span>λ = {cfg.risk_margin}</span>
              <span>
                generated {String(metrics.generated_at).slice(0, 19)}Z
              </span>
              <a
                href="https://github.com/"
                className="tap-44 inline-flex items-center underline decoration-white/20 underline-offset-2 transition-colors hover:text-slateink"
              >
                MODEL_CARD.md
              </a>
            </div>
          )}
        </motion.div>
      </div>
    </section>
  );
}
