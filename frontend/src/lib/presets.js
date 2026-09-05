/**
 * Simulator presets and the offline decision path.
 *
 * MIRROR: `backend/src/sentinel/api/routes/simulate.py` builds the same three
 * cases server-side. Keys match (`electronics-fraud`, `low-value-subscription`,
 * `fraud-ring`) so the simulator can call the live API when one is reachable
 * and fall back to this file when the site is deployed statically.
 *
 * Each preset exercises a *different decision path*, which is the point:
 *
 *   electronics-fraud       CONTEST via the strong_evidence gate
 *   low-value-subscription  ACCEPT  via the EV rule alone
 *   fraud-ring              ACCEPT  via the no_pod_on_non_receipt gate
 *
 * A demo where every case resolves the same way proves nothing about the policy
 * layer.
 *
 * ---------------------------------------------------------------------------
 * What is computed here and what is recorded
 * ---------------------------------------------------------------------------
 *
 * The **gate trace is computed**, live, in this file. Gates are deterministic
 * functions of the evidence, so reimplementing them client-side is honest and
 * verifiable against `policy/gates.py`.
 *
 * The **model probability is recorded**, not computed. A gradient-boosted
 * booster cannot run in the browser, and inventing a plausible number would be
 * fabrication. Each preset therefore carries `recorded`, holding the exact raw
 * and calibrated outputs the real model produced for that exact input, together
 * with the model version that produced them. When the simulator is running
 * offline it says so on screen and names the version -- it never presents a
 * recorded value as a live one.
 */

import {
  applyEvRule,
  DEFAULT_COST_INR,
  DEFAULT_RISK_MARGIN,
} from './economics.js';

/* -------------------------------------------------------------------------- */
/* Preset definitions                                                         */
/* -------------------------------------------------------------------------- */

/**
 * The three cases, in display order.
 *
 * `evidence` mirrors the `EvidenceBundle` the backend assembles, reduced to the
 * fields the gates and the UI actually read.
 */
export const PRESETS = [
  {
    key: 'electronics-fraud',
    label: '₹32,000 Electronics Fraud',
    blurb: 'High value, airtight delivery proof, 3-D Secure authenticated.',
    narrative:
      'The compelling-evidence gate contests this regardless of model score. On a ₹32,000 dispute with a verified, signed, name-matched proof of delivery, deferring to a probabilistic score would be the expensive mistake.',
    expectedPath: 'CONTEST via strong_evidence gate',
    dispute: {
      disputeId: 'dp_preset_electronics',
      transactionId: 'pay_preset_electronics',
      merchantId: 'acc_0031',
      amountInr: 32000,
      reasonCode: 'VISA_10.4',
      reasonLabel: 'Other Fraud — Card Absent Environment',
      network: 'VISA',
      hoursRemaining: 264,
    },
    evidence: {
      customerName: 'Ananya Iyer',
      items: ['4K Action Camera', 'Noise Cancelling Headphones'],
      orderTotal: 32000,
      billingAddress:
        'Flat 902, Orchid Towers, Residency Road, Bengaluru, Karnataka 560025',
      shippingAddress:
        'Flat 902, Orchid Towers, Residency Road, Bengaluru, Karnataka 560025',
      avsMatch: true,
      cvvMatch: true,
      threeDsStatus: 'AUTHENTICATED',
      podStatus: 'VERIFIED',
      podCarrier: 'BLUEDART',
      podAwb: 'BLU4471902238',
      podRecipient: 'Ananya Iyer',
      podSignature: true,
      podScanCount: 9,
      podOcrConfidence: 0.94,
      podDelivered: true,
      recipientNameMatch: 1.0,
      ipCity: 'Bengaluru (49.207.184.22)',
      ipOffshore: false,
      deviceFingerprint: 'dev_a91f4c73b8e25d10',
      accountAgeDays: 612,
      priorDisputeCount: 0,
      refundRequested: false,
      merchantCommsCount: 3,
    },
    // Recorded outputs of the real booster for this exact input. See the module
    // docstring: not computed in the browser, and never shown as if it were.
    // `shippedProbability` is what the policy engine consumed;
    // `isotonicProbability` is the counterfactual the toggle reveals.
    recorded: {
      rawScore: 0.619378,
      shippedProbability: 0.619378,
      isotonicProbability: 0.645312,
    },
  },
  {
    key: 'low-value-subscription',
    label: '₹450 Low-Value Subscription',
    blurb: 'Above the filing cost, so no gate fires. The threshold decides.',
    narrative:
      'At c = ₹350 and λ = 1.2 the break-even probability is 1.2 × 350 / 450 = 93.3%. This dispute must be all but certain to be worth contesting, and no realistic evidence position clears that bar. The arithmetic concedes it — this is the case that shows the per-dispute threshold operating on its own.',
    expectedPath: 'ACCEPT via EV rule',
    dispute: {
      disputeId: 'dp_preset_subscription',
      transactionId: 'pay_preset_subscription',
      merchantId: 'acc_0008',
      amountInr: 450,
      reasonCode: 'VISA_13.6',
      reasonLabel: 'Credit Not Processed',
      network: 'VISA',
      hoursRemaining: 192,
    },
    evidence: {
      customerName: 'Rahul Mehta',
      items: ['Monthly Subscription Renewal'],
      orderTotal: 450,
      billingAddress: 'Flat 214, Green Meadows, SV Road, Mumbai, Maharashtra 400058',
      shippingAddress: 'Flat 214, Green Meadows, SV Road, Mumbai, Maharashtra 400058',
      avsMatch: true,
      cvvMatch: true,
      threeDsStatus: 'NOT_ENROLLED',
      podStatus: 'ABSENT',
      podCarrier: 'UNKNOWN',
      podAwb: '',
      podRecipient: '',
      podSignature: false,
      podScanCount: 0,
      podOcrConfidence: 0,
      podDelivered: false,
      recipientNameMatch: 0,
      ipCity: 'Mumbai (103.21.58.194)',
      ipOffshore: false,
      deviceFingerprint: 'dev_5c2e08a7d41b9f36',
      accountAgeDays: 418,
      priorDisputeCount: 1,
      refundRequested: false,
      merchantCommsCount: 1,
    },
    recorded: {
      rawScore: 0.29454,
      shippedProbability: 0.29454,
      isotonicProbability: 0.302326,
    },
  },
  {
    key: 'fraud-ring',
    label: 'Fraud Ring Syndicate',
    blurb: 'Every behavioural signal screams abuse. None of them are admissible.',
    narrative:
      'A device fingerprint shared across a ring, an account minted five hours before the order, an offshore checkout IP, four prior disputes — and no proof of delivery. Under Visa 13.1 proof of delivery is the evidence the scheme requires, so the system concedes a dispute it is confident is fraudulent. Being right is not the same as being able to prove it under the rulebook.',
    expectedPath: 'ACCEPT via no_pod_on_non_receipt gate',
    dispute: {
      disputeId: 'dp_preset_fraudring',
      transactionId: 'pay_preset_fraudring',
      merchantId: 'acc_0017',
      amountInr: 8900,
      reasonCode: 'VISA_13.1',
      reasonLabel: 'Merchandise / Services Not Received',
      network: 'VISA',
      hoursRemaining: 312,
    },
    evidence: {
      customerName: 'Imran Khan',
      items: ['Mechanical Keyboard', 'Gaming Mouse', 'Bluetooth Speaker'],
      orderTotal: 8900,
      billingAddress: 'Flat 118, Crystal Court, Ring Road, Delhi, Delhi 110024',
      shippingAddress: 'Flat 704, Palm Grove, Station Road, Jaipur, Rajasthan 302017',
      avsMatch: false,
      cvvMatch: true,
      threeDsStatus: 'ATTEMPTED',
      podStatus: 'ABSENT',
      podCarrier: 'UNKNOWN',
      podAwb: '',
      podRecipient: '',
      podSignature: false,
      podScanCount: 0,
      podOcrConfidence: 0,
      podDelivered: false,
      recipientNameMatch: 0,
      ipCity: 'Dubai (185.220.101.47)',
      ipOffshore: true,
      deviceFingerprint: 'dev_ring_07_3f9a1c4e88b2',
      accountAgeDays: 0.21,
      priorDisputeCount: 4,
      refundRequested: false,
      merchantCommsCount: 0,
    },
    recorded: {
      rawScore: 0.163233,
      shippedProbability: 0.163233,
      isotonicProbability: 0.124528,
    },
  },
];

/** Look up a preset by key. */
export function getPreset(key) {
  return PRESETS.find((p) => p.key === key) ?? PRESETS[0];
}

/* -------------------------------------------------------------------------- */
/* Client-side gate evaluation                                                */
/* -------------------------------------------------------------------------- */

const FRAUD_CODES = new Set(['VISA_10.4', 'MC_4837']);
const NON_RECEIPT_CODES = new Set(['VISA_13.1', 'MC_4853']);

/** Recipient-name similarity floor for the strong-evidence gate. */
const STRONG_NAME_MATCH_FLOOR = 0.9;

/**
 * Evaluate all six gates in order, mirroring `policy/gates.GATE_ORDER`.
 *
 * Evaluation does **not** short-circuit: every gate's result is returned so the
 * UI can render the complete trace, including the gates that were considered
 * and rejected. First-fire-wins precedence is applied by the caller, exactly as
 * `policy.engine.decide` does.
 *
 * @param {object} preset
 * @param {number} costInr
 * @returns {{name: string, fired: boolean, forcedAction: string|null, rationale: string}[]}
 */
export function evaluateGates(preset, costInr) {
  const { dispute: d, evidence: e } = preset;
  const isFraud = FRAUD_CODES.has(d.reasonCode);
  const isNonReceipt = NON_RECEIPT_CODES.has(d.reasonCode);
  const liabilityShifted = e.threeDsStatus === 'AUTHENTICATED';

  return [
    {
      name: 'amount_below_cost',
      fired: d.amountInr <= costInr,
      forcedAction: d.amountInr <= costInr ? 'ACCEPT' : null,
      rationale:
        d.amountInr <= costInr
          ? `Disputed amount ₹${d.amountInr.toLocaleString('en-IN')} does not exceed the ₹${costInr.toLocaleString('en-IN')} representment cost. Even a certain win loses money.`
          : `Amount ₹${d.amountInr.toLocaleString('en-IN')} exceeds cost ₹${costInr.toLocaleString('en-IN')}; a profitable recovery exists.`,
    },
    {
      name: 'expired_window',
      fired: d.hoursRemaining <= 0,
      forcedAction: d.hoursRemaining <= 0 ? 'ACCEPT' : null,
      rationale:
        d.hoursRemaining <= 0
          ? 'The representment window has closed. The scheme will reject any filing.'
          : `${d.hoursRemaining.toLocaleString('en-IN')} hours remain before the representment deadline.`,
    },
    {
      name: 'credit_already_processed',
      fired: d.reasonCode === 'VISA_13.6' && e.refundRequested,
      forcedAction: d.reasonCode === 'VISA_13.6' && e.refundRequested ? 'ACCEPT' : null,
      rationale:
        d.reasonCode === 'VISA_13.6' && e.refundRequested
          ? 'Credit-not-processed dispute with a refund recorded against this order. The cardholder is right.'
          : 'Not a credit-not-processed dispute with a matching refund on record.',
    },
    {
      name: 'no_pod_on_non_receipt',
      fired: isNonReceipt && e.podStatus === 'ABSENT',
      forcedAction: isNonReceipt && e.podStatus === 'ABSENT' ? 'ACCEPT' : null,
      rationale:
        isNonReceipt && e.podStatus === 'ABSENT'
          ? `Reason code ${d.reasonCode} alleges non-receipt and no proof-of-delivery document exists. Scheme rules admit no substitute artifact; there is nothing to represent.`
          : 'Either not a non-receipt dispute, or a proof-of-delivery document exists.',
    },
    {
      name: 'fraud_without_liability_shift',
      fired: isFraud && !liabilityShifted,
      forcedAction: isFraud && !liabilityShifted ? 'ACCEPT' : null,
      rationale:
        isFraud && !liabilityShifted
          ? `Fraud denial with 3-D Secure status ${e.threeDsStatus}, not AUTHENTICATED. Fraud liability remains with the merchant.`
          : 'Either not a fraud reason code, or 3-D Secure shifted liability to the issuer.',
    },
    {
      name: 'strong_evidence',
      fired:
        e.podStatus === 'VERIFIED' &&
        e.podSignature &&
        e.recipientNameMatch > STRONG_NAME_MATCH_FLOOR,
      forcedAction:
        e.podStatus === 'VERIFIED' &&
        e.podSignature &&
        e.recipientNameMatch > STRONG_NAME_MATCH_FLOOR
          ? 'CONTEST'
          : null,
      rationale:
        e.podStatus === 'VERIFIED' &&
        e.podSignature &&
        e.recipientNameMatch > STRONG_NAME_MATCH_FLOOR
          ? `Compelling evidence present: proof of delivery VERIFIED at ${Math.round(e.podOcrConfidence * 100)}% OCR confidence, signature captured, recipient name matches at ${Math.round(e.recipientNameMatch * 100)}%. Contesting regardless of model score.`
          : `Compelling-evidence bar not met (status=${e.podStatus}, signature=${e.podSignature}, name match=${e.recipientNameMatch.toFixed(2)}).`,
    },
  ];
}

/**
 * Run the full offline decision path for a preset: gates, then the EV rule.
 *
 * Structurally identical to `policy.engine.decide` -- gates first, first-fire
 * wins, economics only when every gate is quiet -- so the offline trace has the
 * same shape as the live one and the UI needs no branching.
 *
 * @param {object} preset
 * @param {number} pWin Calibrated win probability to decide against.
 * @param {number} [costInr]
 * @param {number} [riskMargin]
 * @returns {object} A decision shaped like the API's `Decision`.
 */
export function decideOffline(
  preset,
  pWin,
  costInr = DEFAULT_COST_INR,
  riskMargin = DEFAULT_RISK_MARGIN,
) {
  const amount = preset.dispute.amountInr;
  const gates = evaluateGates(preset, costInr);
  const fired = gates.find((g) => g.fired) ?? null;
  const ev = applyEvRule(pWin, amount, costInr, riskMargin);

  const action = fired ? fired.forcedAction : ev.action;
  const decidingReason = fired ? fired.name : 'EV_RULE';

  return {
    disputeId: preset.dispute.disputeId,
    action,
    winProbability: pWin,
    threshold: ev.threshold,
    thresholdReachable: ev.reachable,
    expectedValueInr: ev.expectedValue,
    gates,
    firedGate: fired,
    decidingReason,
    margin: ev.margin,
  };
}

/* -------------------------------------------------------------------------- */
/* Offline packet rendering                                                   */
/* -------------------------------------------------------------------------- */

/**
 * Scheme rule text per reason code.
 * MIRROR: `backend/src/sentinel/llm/templates.py :: SCHEME_RULE`.
 */
const SCHEME_RULE = {
  'VISA_13.1':
    'Visa Core Rules, dispute condition 13.1 (Merchandise or Services Not Received). The merchant may remedy this dispute by supplying evidence that the goods were delivered to the cardholder or to the address provided at the time of the transaction.',
  'VISA_13.3':
    'Visa Core Rules, dispute condition 13.3 (Not as Described or Defective Merchandise). The merchant may remedy this dispute by evidencing that the goods matched their description at the point of sale and that the disclosed returns policy was made available to the cardholder.',
  'VISA_13.6':
    'Visa Core Rules, dispute condition 13.6 (Credit Not Processed). The merchant may remedy this dispute by evidencing that no credit was owed, or that any credit due has been processed.',
  'VISA_10.4':
    'Visa Core Rules, dispute condition 10.4 (Other Fraud — Card Absent Environment). The merchant may remedy this dispute with compelling evidence under Visa rule 11.4, including evidence of cardholder participation or of a successful 3-D Secure authentication carrying a shift of fraud liability to the issuer.',
  MC_4837:
    'Mastercard Chargeback Guide, reason code 4837 (No Cardholder Authorisation). The merchant may remedy this dispute by evidencing cardholder participation or a successful authentication carrying a liability shift.',
  MC_4853:
    'Mastercard Chargeback Guide, reason code 4853 (Cardholder Dispute). The merchant may remedy this dispute by evidencing delivery of the goods or services as described to the cardholder.',
};

/**
 * Enumerate the artifact identifiers this preset's evidence actually contains.
 * MIRROR: `backend/src/sentinel/llm/validators.py :: artifact_index`.
 */
export function artifactIndex(preset) {
  const e = preset.evidence;
  const ids = [
    `ORDER_RECORD_${preset.dispute.disputeId.replace('dp_', 'ord_')}`,
    'AUTHORISATION_AVS_RESULT',
    'AUTHORISATION_CVV_RESULT',
    'AUTHORISATION_3DS_RESULT',
    `SESSION_LOG_${e.deviceFingerprint.slice(0, 16)}`,
  ];

  if (e.podStatus !== 'ABSENT') {
    ids.push(e.podAwb ? `POD_SLIP_${e.podAwb}` : 'POD_SLIP');
    if (e.podSignature) ids.push('POD_DELIVERY_SIGNATURE');
    if (e.podScanCount > 0) ids.push('CARRIER_SCAN_TRAIL');
    if (e.podDelivered) ids.push('POD_DELIVERY_TIMESTAMP');
  }
  if (e.merchantCommsCount > 0) ids.push('MERCHANT_CUSTOMER_COMMS_LOG');
  if (e.refundRequested) ids.push('REFUND_LEDGER_ENTRY');
  if (e.priorDisputeCount > 0) ids.push('CARDHOLDER_DISPUTE_HISTORY');

  return ids;
}

const inr = (value) =>
  `INR ${value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/**
 * Render a deterministic representment draft with no LLM and no API.
 *
 * MIRROR: `backend/src/sentinel/llm/templates.py :: render_template`.
 *
 * This exists so the simulator produces a real document when deployed
 * statically, rather than an empty panel or a placeholder. It is the same
 * fallback the backend uses when the Anthropic API is unreachable — which is
 * the common case, since the key is unset by default — so what the offline page
 * shows is genuinely what the system would file, not a mock-up of it.
 *
 * @param {object} preset
 * @returns {object} A packet shaped like the API's `packet_preview`.
 */
export function renderOfflinePacket(preset) {
  const { dispute: d, evidence: e } = preset;
  const artifacts = artifactIndex(preset);

  const itemText =
    e.items.length > 0 ? e.items.slice(0, 3).join(', ') : 'the ordered goods';

  const summary =
    `This representment concerns dispute ${d.disputeId} against transaction ` +
    `${d.transactionId}, raised under ${d.reasonCode} for ${inr(d.amountInr)}. ` +
    `The order was placed by ${e.customerName} for ${itemText}, with a total ` +
    `order value of ${inr(e.orderTotal)}, and despatched to the address ` +
    `supplied by the cardholder at checkout. The merchant holds ` +
    `contemporaneous records evidencing that the transaction was validly ` +
    `authorised and that the merchant performed its obligations, and ` +
    `respectfully requests that the chargeback be reversed.`;

  let podSentence;
  if (e.podStatus === 'ABSENT') {
    podSentence =
      'No carrier proof-of-delivery document is held against this consignment.';
  } else if (e.podStatus === 'UNVERIFIED') {
    podSentence =
      'A carrier proof-of-delivery document is held against this consignment but could not be machine-verified; the original slip is available on request.';
  } else {
    const parts = [
      `A ${e.podCarrier.charAt(0)}${e.podCarrier.slice(1).toLowerCase()} proof-of-delivery slip`,
    ];
    if (e.podAwb) parts.push(` (waybill ${e.podAwb})`);
    parts.push(' is held against this consignment');
    if (e.podRecipient) parts.push(`, signed for by ${e.podRecipient}`);
    if (e.podScanCount > 0) {
      parts.push(
        `. The carrier network recorded ${e.podScanCount} scan events tracking the parcel to the delivery address`,
      );
    }
    podSentence = `${parts.join('')}.`;
  }

  const authChecks = [
    e.avsMatch ? 'AVS matched' : 'AVS did not match',
    e.cvvMatch ? 'CVV2 matched' : 'CVV2 did not match',
  ].join(' and ');

  const authSentence =
    e.threeDsStatus === 'AUTHENTICATED'
      ? 'The transaction was authenticated via 3-D Secure, shifting fraud liability to the issuer.'
      : e.threeDsStatus === 'ATTEMPTED'
        ? '3-D Secure authentication was attempted but not completed.'
        : e.threeDsStatus === 'FAILED'
          ? '3-D Secure authentication was attempted and failed.'
          : 'The card was not enrolled in 3-D Secure at the time of the transaction.';

  const behaviourParts = [
    `The order was placed from an authenticated session on device ${e.deviceFingerprint}, from ${e.ipCity}`,
    `, against an account ${Math.round(e.accountAgeDays).toLocaleString('en-IN')} days old`,
  ];
  if (e.merchantCommsCount > 0) {
    behaviourParts.push(
      `. The merchant logged ${e.merchantCommsCount} direct communications with the cardholder in relation to this order`,
    );
  }
  if (e.priorDisputeCount > 0) {
    behaviourParts.push(
      `. This cardholder has raised ${e.priorDisputeCount} prior dispute(s) against this merchant`,
    );
  }

  const evidenceNarrative = [
    podSentence,
    `At authorisation, ${authChecks}. ${authSentence}`,
    `${behaviourParts.join('')}.`,
    `The shipping address of record is ${e.shippingAddress}, and the billing address supplied at checkout is ${e.billingAddress}.`,
  ].join(' ');

  const rule =
    SCHEME_RULE[d.reasonCode] ??
    'the applicable card-scheme dispute rules for this reason code';

  let specific;
  if (d.reasonCode === 'VISA_13.1' || d.reasonCode === 'MC_4853') {
    specific =
      'The carrier documentation submitted with this filing evidences delivery to the address the cardholder supplied, which is the remedy the rule contemplates.';
  } else if (d.reasonCode === 'VISA_10.4' || d.reasonCode === 'MC_4837') {
    specific =
      e.threeDsStatus === 'AUTHENTICATED'
        ? 'The transaction carries a successful 3-D Secure authentication. Fraud liability for an authenticated card-absent transaction rests with the issuer, and the dispute is not properly raised against the merchant.'
        : 'The merchant submits the authorisation and session records below as evidence of cardholder participation in the transaction.';
  } else if (d.reasonCode === 'VISA_13.6') {
    specific =
      "The merchant's ledger shows no credit outstanding against this transaction, and no refund was owed under the disclosed terms of sale.";
  } else {
    specific =
      'The merchant submits the order and fulfilment records below as evidence that the goods supplied conformed to their description at the point of sale.';
  }

  const schemeArgument = `${rule} ${specific}`;

  const escape = (text) =>
    String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

  const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Representment ${escape(d.disputeId)}</title>
<style>
body{font-family:Helvetica,Arial,sans-serif;font-size:10pt;line-height:1.5;color:#14181f;max-width:760px;margin:2rem auto;padding:0 1.5rem}
h1{font-size:15pt;text-transform:uppercase;letter-spacing:.4pt;border-bottom:2.5pt solid #0f6b4f;padding-bottom:8pt}
h2{font-size:9pt;text-transform:uppercase;letter-spacing:.7pt;color:#0f6b4f;border-bottom:.6pt solid #d4d9e0;padding-bottom:3pt;margin-top:18pt}
.kv{width:100%;border-collapse:collapse;margin:14pt 0}.kv td{padding:3pt 0;font-size:9.5pt;vertical-align:top}
.kv .k{width:30%;color:#5b6472;text-transform:uppercase;font-size:8pt;letter-spacing:.4pt}
.compelling{background:#f5f7f9;border-left:2.5pt solid #0f6b4f;padding:8pt 10pt}
code{font-family:"Courier New",monospace;font-size:8pt}
.foot{margin-top:18pt;padding-top:8pt;border-top:.6pt solid #d4d9e0;font-size:7.5pt;color:#5b6472}
</style></head><body>
<h1>Merchant Representment</h1>
<table class="kv">
<tr><td class="k">Dispute reference</td><td>${escape(d.disputeId)}</td><td class="k">Reason code</td><td>${escape(d.reasonCode)}</td></tr>
<tr><td class="k">Transaction</td><td>${escape(d.transactionId)}</td><td class="k">Amount disputed</td><td><strong>${escape(inr(d.amountInr))}</strong></td></tr>
</table>
<h2>1 &middot; Case summary</h2><p>${escape(summary)}</p>
<h2>2 &middot; Compelling evidence</h2><div class="compelling"><p>${escape(evidenceNarrative)}</p></div>
<h2>3 &middot; Scheme argument &mdash; ${escape(d.reasonCode)}</h2><p>${escape(schemeArgument)}</p>
<h2>4 &middot; Artifact index</h2><ul>${artifacts.map((a) => `<li><code>${escape(a)}</code></li>`).join('')}</ul>
<h2>5 &middot; Merchant declaration</h2>
<p>The merchant confirms that the records referenced above are contemporaneous business records held in the ordinary course of trade, and that no artifact referenced in this filing has been created for the purpose of this dispute.</p>
<div class="foot">Generated by ChargeGuard.AI from deterministic templates (no language model available in this environment).
Every artifact identifier in section 4 was verified against the evidence bundle before rendering.
This document contains no automated assessment of the dispute's merits; the decision to file was made separately.</div>
</body></html>`;

  return {
    summary,
    evidenceNarrative,
    schemeArgument,
    citedArtifacts: artifacts,
    source: 'TEMPLATE',
    fallbackReason: 'running offline — no API reachable',
    html,
    pdfAvailable: false,
  };
}
