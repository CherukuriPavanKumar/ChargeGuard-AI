/**
 * A small, honest heuristic over one preset's evidence bundle.
 *
 * IMPORTANT: this is NOT the shipped model's SHAP output. The LightGBM
 * booster (`backend/src/sentinel/...`) cannot run in the browser, and no
 * per-feature attribution is committed to the repo the way `metrics.json`
 * commits aggregate calibration numbers. Inventing plausible-looking SHAP
 * values would be fabrication, so the neural-lattice and dossier sections
 * instead compute a transparent, deterministic "evidence signal" per field:
 * how strongly that one field points toward CONTEST (positive) or ACCEPT
 * (negative), on a fixed, documented scale. It is illustrative wiring for
 * the visualisation, labelled as such everywhere it appears on screen.
 *
 * Every input comes from `lib/presets.js` -- the same three real cases the
 * Simulator section uses -- so at least the underlying evidence is genuine,
 * even though the attribution weighting is a UI heuristic.
 */

/**
 * @param {object} preset one of PRESETS from lib/presets.js
 * @returns {{key: string, label: string, value: string, signal: number}[]}
 *   `signal` in [-1, 1]: positive favours CONTEST, negative favours ACCEPT.
 */
export function evidenceSignals(preset) {
  const e = preset.evidence;
  const d = preset.dispute;

  const signals = [
    {
      key: 'pod',
      label: 'Proof of delivery',
      value: e.podStatus,
      signal: e.podStatus === 'VERIFIED' ? 0.9 : e.podStatus === 'UNVERIFIED' ? 0.1 : -0.9,
    },
    {
      key: 'signature',
      label: 'Delivery signature',
      value: e.podSignature ? 'CAPTURED' : 'ABSENT',
      signal: e.podSignature ? 0.6 : -0.3,
    },
    {
      key: 'nameMatch',
      label: 'Recipient name match',
      value: `${Math.round(e.recipientNameMatch * 100)}%`,
      signal: e.recipientNameMatch * 1.6 - 0.6,
    },
    {
      key: '3ds',
      label: '3-D Secure',
      value: e.threeDsStatus,
      signal: e.threeDsStatus === 'AUTHENTICATED' ? 0.8 : e.threeDsStatus === 'ATTEMPTED' ? -0.1 : -0.5,
    },
    {
      key: 'avscvv',
      label: 'AVS / CVV',
      value: `${e.avsMatch ? 'MATCH' : 'NO MATCH'} / ${e.cvvMatch ? 'MATCH' : 'NO MATCH'}`,
      signal: (e.avsMatch ? 0.25 : -0.25) + (e.cvvMatch ? 0.25 : -0.25),
    },
    {
      key: 'ip',
      label: 'IP telemetry',
      value: e.ipCity,
      signal: e.ipOffshore ? -0.7 : 0.3,
    },
    {
      key: 'accountAge',
      label: 'Account age',
      value: `${Math.round(e.accountAgeDays)} days`,
      signal: Math.max(-0.8, Math.min(0.6, (e.accountAgeDays - 30) / 300)),
    },
    {
      key: 'priorDisputes',
      label: 'Prior disputes',
      value: String(e.priorDisputeCount),
      signal: -0.25 * e.priorDisputeCount,
    },
    {
      key: 'reasonCode',
      label: 'Reason code',
      value: d.reasonCode,
      signal: 0,
    },
  ];

  return signals.map((s) => ({ ...s, signal: Math.max(-1, Math.min(1, s.signal)) }));
}
