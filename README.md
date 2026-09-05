# ChargeGuard.AI

ChargeGuard.AI is a chargeback-defense application for merchants. It helps decide
whether a dispute is worth contesting and prepares evidence for disputes that
should be challenged.

The project contains:

- A FastAPI backend for scoring disputes and generating representment packets.
- A React/Vite frontend with an interactive simulator and evaluation dashboard.
- A synthetic data pipeline for training and evaluating the decision model.
- Tests for the policy rules, schemas, feature builder, fallbacks, and economics.

## How It Works

ChargeGuard.AI is designed as a decision pipeline, not as a chatbot that writes
a persuasive answer and then decides whether to submit it. Each part has one
responsibility, and the deterministic policy engine is the only component that
can make the final `CONTEST` or `ACCEPT` decision.

### 1. Receive and normalize a dispute

The API accepts an acquirer dispute webhook or a bare dispute object together
with the merchant's order record and checkout session. The webhook adapter
normalizes different input shapes into the same typed `DisputeEvent` schema.
Amounts are represented with decimal-safe values so currency calculations do
not depend on binary floating-point rounding.

The request can also include:

- A structured proof-of-delivery record.
- A path to a proof-of-delivery image for OCR.
- Prior disputes for the cardholder.
- Refund information.
- Merchant-to-customer communication count.

Invalid or unexpected fields are rejected by the Pydantic schemas instead of
being silently ignored.

### 2. Assemble the evidence bundle

The evidence loader combines the dispute with the merchant's supporting
records. The bundle can include order details, customer and address data,
checkout telemetry, authorization results, proof-of-delivery information,
carrier scans, delivery signatures, and merchant communications.

Proof of delivery has three meaningful states:

| State | Meaning |
| --- | --- |
| `VERIFIED` | A delivery record was found and its contents could be checked. |
| `UNVERIFIED` | A document exists, but OCR or parsing could not establish its contents. |
| `ABSENT` | No proof-of-delivery document was supplied. |

`UNVERIFIED` is deliberately different from `ABSENT`. A damaged document is
still evidence that exists, while no document may trigger a hard policy gate.
OCR failures, unreadable images, and missing optional dependencies degrade the
bundle into an explicit state instead of crashing the scoring request.

### 3. Build the feature vector

The feature builder converts the dispute and evidence bundle into the versioned
35-feature `FeatureVector` used by both training and serving. Features include
signals such as:

- Name and address similarity.
- Proof-of-delivery presence, verification, signature, scan count, and OCR quality.
- 3-D Secure, AVS, and CVV results.
- Account age, login-to-order timing, and dispute-window timing.
- Checkout IP location and offshore distance.
- Prior dispute count and merchant communication count.
- Reason-code and liability-shift interactions.

The builder is pure: it performs no network access, disk access, clock reads,
random sampling, or model inference. The same inputs must always produce the
same vector. This prevents training/serving skew and makes an archived decision
reproducible.

### 4. Estimate the probability of winning

The LightGBM model receives the feature vector and returns a probability between
0 and 1: the estimated chance that the merchant will win if it submits a
representment. The model is loaded once when the API starts, not once per
request.

The training and evaluation pipeline also tests an isotonic calibration map.
The map is fitted on out-of-fold predictions and compared with the raw booster
on a separate selection fold. Whichever option performs better is recorded in
the model artifacts. This matters because the value is used as a probability
inside a currency calculation, not merely as a ranking score.

The model does not decide the action. It only supplies `p_win` and its model
version to the policy engine.

### 5. Evaluate policy gates

Before applying the economic rule, the policy engine evaluates all six ordered
gates and stores the complete trace in the returned `Decision`. The first gate
that fires supplies the deciding reason and forced action:

1. **Amount below cost**: filing cannot recover its own cost.
2. **Expired window**: the representment deadline has passed.
3. **Credit already processed**: the merchant has already issued the relevant refund or credit.
4. **No proof of delivery on a non-receipt claim**: the required evidence is unavailable.
5. **Fraud claim without liability shift**: the available authorization position does not support the representment.
6. **Strong evidence**: the evidence bundle contains a compelling basis for contesting.

All gates are evaluated even when an earlier gate decides the action. That gives
auditors the full ordered trace rather than only the branch that happened to
fire. The language model is not involved in this step.

### 6. Apply the per-dispute economic rule

If no hard gate fires, ChargeGuard.AI compares the calibrated win probability
with the break-even threshold:

```text
threshold = risk_margin * representment_cost / dispute_amount

CONTEST when win_probability >= threshold
ACCEPT  when win_probability <  threshold
```

The equivalent expected-value calculation is:

```text
expected_value = win_probability * dispute_amount - representment_cost
```

The default configuration uses a representment cost of INR 350 and a risk
margin of 1.2. The threshold is calculated separately for every dispute. A
large dispute can be worth contesting at a lower probability, while a small
dispute may require near certainty.

If the threshold is greater than 1, it is unreachable. The engine returns
`ACCEPT` for that arithmetic reason rather than pretending the model simply had
a low score. Every decision records the threshold, expected value, probability,
model version, deciding reason, gate trace, and latency.

### 7. Generate a packet only after `CONTEST`

Packet generation is downstream of the decision. It never participates in the
decision and never receives the probability, threshold, or action as an input.
This keeps fluent language-model output from influencing whether money is spent
on a filing.

For a `CONTEST` decision, the packet builder creates a structured representment
packet containing:

- A case summary.
- A narrative built from the available evidence.
- A card-scheme argument tied to the dispute reason code.
- Citations to the exact supporting artifacts.
- HTML output and an optional PDF rendering.

If an Anthropic API key is unavailable, the system uses deterministic templates.
If an LLM response is invalid or cites an artifact that does not exist, the
whole draft is rejected and the template path is used. If the native PDF stack
is unavailable, a valid HTML packet is still returned and the PDF field remains
explicitly unavailable.

### Synchronous scoring and asynchronous packets

The two expensive operations are intentionally separate:

```text
POST /v1/disputes/score
  ingest -> evidence -> features -> model -> gates -> economic rule -> Decision

POST /v1/disputes/{id}/packet
  queue job -> synthesize narrative -> render HTML/PDF -> poll job status
```

Scoring stays synchronous and fast because it does not call an LLM, run OCR on
demand, or render a document. Packet generation runs as a background job because
it may call external services and a native PDF engine.

### Frontend behavior

The simulator can operate in two honest modes:

- **Live mode**: with `VITE_API_URL` configured and a healthy trained backend,
  it requests the real API decision and packet preview.
- **Offline mode**: without a reachable backend, it uses the shipped preset
  inputs and recorded model probabilities, then recomputes the gate trace and
  economic rule in the browser using `frontend/src/lib/economics.js`.

The frontend labels the active mode. It never presents recorded offline values as
fresh model inference. The evaluation dashboard reads the generated metrics
artifact rather than duplicating metric values inside individual components.

### Graceful degradation

The system is designed to report capability loss without hiding it:

- Missing model artifacts keep the API alive, but scoring returns a clear error
  until `make data && make train` has been run.
- Missing Tesseract produces `UNVERIFIED` proof-of-delivery evidence.
- Missing Anthropic credentials uses deterministic packet templates.
- LLM failures or invalid citations fall back to templates.
- Missing WeasyPrint produces HTML instead of a fake PDF.

The `/health` endpoint reports the current state of the model, OCR, LLM, and PDF
capabilities.

## Requirements

For a local setup:

- Python 3.11 or newer
- Node.js and npm
- GNU Make

Docker can be used instead of installing Python and Node locally.

## Quick Start

From the repository root:

```bash
make install
make all
```

`make all` generates the synthetic data, trains the model, evaluates it, and
runs the test suite.

Start the backend and frontend in separate terminals:

```bash
make serve
```

Backend API and Swagger documentation:

<http://localhost:8000/docs>

```bash
make ui
```

Frontend:

<http://localhost:5173>

### Run with Docker

```bash
docker compose run --rm pipeline
docker compose up api ui
```

Then open <http://localhost:5173>.

## Make Commands

| Command | Description |
| --- | --- |
| `make install` | Create the Python virtual environment and install all dependencies |
| `make data` | Generate the synthetic dispute corpus and POD images |
| `make train` | Train the win-probability model |
| `make eval` | Evaluate the model and update the dashboard metrics |
| `make test` | Run the Python test suite |
| `make check` | Run the core policy and invariant tests |
| `make serve` | Start the backend on port 8000 |
| `make ui` | Start the frontend on port 5173 |
| `make all` | Run data generation, training, evaluation, and tests |
| `make clean` | Remove generated data, artifacts, and caches |

## Frontend Only

The frontend can run without the backend. This uses the built-in presets and
client-side economics logic:

```bash
cd frontend
npm install
npm run dev
```

To create a production build:

```bash
npm run build
```

The output is written to `frontend/dist`.

## Full-Stack Frontend Configuration

To make the frontend call the live backend, create `frontend/.env.local`:

```bash
VITE_API_URL=http://localhost:8000
```

Without this variable, the frontend runs in static/demo mode.

Optional backend variables:

| Variable | Default | Description |
| --- | --- | --- |
| `ChargeGuard_ANTHROPIC_API_KEY` | empty | Enables LLM-written narratives; otherwise templates are used |
| `ChargeGuard_REPRESENTMENT_COST_INR` | `350` | Cost of filing a representment |
| `ChargeGuard_RISK_MARGIN` | `1.2` | Risk margin used in the economic rule |
| `ChargeGuard_CORS_ORIGINS` | localhost frontend | JSON list of allowed frontend origins |

Tesseract OCR and WeasyPrint are optional. The application reports unavailable
capabilities at `/health` and falls back to supported degraded behavior.

## API Endpoints

| Endpoint | Method | Description |
| --- | --- | --- |
| `/health` | GET | Report service and optional dependency status |
| `/v1/disputes/score` | POST | Score a dispute and return its decision and gate trace |
| `/v1/disputes/{id}/packet` | POST | Start generating a representment packet |
| `/v1/disputes/jobs/{job_id}` | GET | Get the status of a packet job |
| `/v1/simulate` | GET | List the available demo cases |
| `/v1/simulate/{preset}` | GET | Run a demo case with its decision trace |
| `/v1/metrics` | GET | Return evaluation metrics |
| `/v1/metrics/latency` | GET | Return latency metrics |
| `/v1/metrics/features` | GET | Return the feature registry |
| `/v1/metrics/policy` | GET | Return the active economic policy |

Interactive API documentation is available at <http://localhost:8000/docs>
when the backend is running.

## Project Structure

```text
backend/
  src/sentinel/
    api/          FastAPI application and routes
    extraction/   OCR and evidence extraction
    features/     Feature construction
    llm/          Optional narrative generation and validation
    models/       Win-probability model and artifacts
    packet/       HTML/PDF representment packet rendering
    policy/       Economic rules, gates, and final decisions
    schemas/      Pydantic request and response models
  data_gen/       Synthetic dispute data generation
  eval/           Evaluation harness and reports
  tests/          Backend tests

frontend/
  src/components/ React UI components
  src/lib/        Shared frontend logic and demo presets
  src/data/       Evaluation metrics used by the dashboard

docs/             Documentation assets and screenshots
```

## Important Notes

- The included dataset is synthetic. It is intended for demonstration and testing,
  not for production risk decisions.
- The model must be generated before live scoring works. Run `make all` or at
  least `make data && make train`.
- The system is designed to degrade visibly when OCR, the LLM, PDF rendering, or
  model artifacts are unavailable. Check `/health` for the current state.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).# ChargeGuard-AI
