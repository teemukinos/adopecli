# Efficient agent orchestration

This is a local development implementation over the existing runtime Store and
worker. It does not install a service, configure MCP, or qualify a hosted product.
The five-workflow performance pilot is an acceptance gate, not a support claim.
See [the local qualification boundary](AGENT_QUALIFICATION.md) for the exact tested
package, operation matrix, evidence paths and unmet acceptance criteria.

## Run the isolated package

Build from a retained, compatible local package. The destination must not exist:

```sh
python3 tools/build_agent_package.py --base /path/to/DobeCLI --output /path/to/isolated-package
```

The builder retains engine provenance and copies the current runtime into a
separate package. It does not rebuild engines. A retained video engine without
`graphics.textDiagnostics` is incompatible with the current video validator;
rebuild the existing locked engine offline using `craft/engines/build_engine.py`
and retain its complete engine manifest before packaging it. Do not relax the
validator to make an old binary pass.

The builder verifies the inherited manifest before copying and verifies the
copied bytes again before overlaying the runtime. Unexpected files and changed
native payloads are rejected. It preserves partial output on failure and refuses
to overwrite it. If an old package contains regenerated Python caches, use
`--omit-python-bytecode` only for a new development package. This removes derived
caches only when their corresponding recorded Python sources verify, and records
the original expected/observed entries in `development_derivation`. The original
package remains untouched. This option cannot excuse changed source or engines.

The API credential comes from `OPENAI_API_KEY`, or the existing owner-only file
`~/.config/adopecli-benchmark/openai-api-key`. Credentials are never placed in a
project, job request, engine environment, or attempt receipt. Use your secret
manager to set the environment variable; do not put credentials in a brief.

Use the actual packaged entry point. Start the existing worker in a separate
terminal and use the same absolute state directory for every command:

```sh
/path/to/isolated-package/bin/a-dope-cli --state /absolute/state worker
/path/to/isolated-package/bin/a-dope-cli --state /absolute/state create-project 'My project'
/path/to/isolated-package/bin/a-dope-cli --state /absolute/state agent capabilities --workflow image
/path/to/isolated-package/bin/a-dope-cli --state /absolute/state agent run \
  --project PROJECT_ID --workflow image --brief /absolute/brief.txt \
  --acceptance /absolute/criteria.json --budget-usd 2
/path/to/isolated-package/bin/a-dope-cli --state /absolute/state agent status RUN_ID
/path/to/isolated-package/bin/a-dope-cli --state /absolute/state agent resume RUN_ID
/path/to/isolated-package/bin/a-dope-cli --state /absolute/state agent cancel RUN_ID
/path/to/isolated-package/bin/a-dope-cli --state /absolute/state checkout REVISION_ID /new/delivery
```

`criteria.json` maps criterion IDs to concrete requirements. Optional `--assets`
loads a JSON list describing already imported project asset IDs. The coordinator
never invents assets or imports arbitrary model-supplied paths. Corrections are
bounded by `--max-corrections` (default one), twelve model calls, and the explicit
spending limit. It uses `gpt-6-astra` with high reasoning; changing models is not
part of the experiment.

Queued work waits without model calls. After 120 seconds without a worker, the
client returns with its durable step still waiting. Start the worker and resume
the same run. Do not submit another run as a substitute for resuming it. A
completed run returns its existing result without generating again.

## Durable state and cost accounting

Schema 7 combines the canonical project-erasure schema and the earlier agent-development schema 6. It adds agent budgets, runs, calls and steps in the existing SQLite Store.
It preserves projects and revisions. Upgrade with the local worker stopped;
older writers are fenced by the existing connection-version guards. Coordinator
leases prevent concurrent resumes. A paid decision, job idempotency key, and
resulting revision remain linked. Step completion and current context commit in
one transaction.

New runs record a fingerprint of the selected operation contract and the complete
package manifest. Resume rejects incompatible versions or changed packages before
taking a lease or dispatching a request. Use the originating package for pending
runs; automatic migration of pending creative decisions is not implemented.
Completed historical runs still return their recorded result without replay.
Legacy unfinished runs created before this binding require their originating
development package. Source-mode development has no sealed engine bundle.

## Detail inspection

The model can request original-resolution PNG or JPEG regions with the ordinary
`inspect` decision. Full previews include their original pixel dimensions:

```json
{"action":"inspect","revision":"CURRENT_REVISION","crops":[{"path":"production/exports/photograph.png","box":[240,300,400,240]}],"notes":"Check the label and material texture."}
```

The box is `[left, top, width, height]` in original pixels. At most eight full
images and crops may be selected together. Omit `artifacts` for crops alone, or
list exact published image paths to include full views. `focus` selects component
state; it does not crop a picture. Images above 16,777,216 pixels are outside this
bounded inspection interface.

The coordinator validates revision, published paths, source hashes and bounds
before persisting the selection. It derives lossless PNG regions without resizing,
enhancement, a render job or an API request. Source pixels and native artifacts
remain unchanged. Durable selections bind the source hashes; resume reconstructs
the same pixels. Each review request retains the crop bytes and provenance,
including source revision, hash, original dimensions and box. A new revision
clears old selections. The API baseline uses this same inspection interface.
This provides evidence for review; it does not declare material quality accepted.

The source follow-up also retains revision-bound inspection assessments. An
`inspect` decision's notes describe the previews just reviewed, rather than the
newly requested selection. The next compact request includes the last four
assessments and their full-view/crop selections, with at most 2,000 characters of
notes each. Truncation and omitted assessment counts are explicit; complete
decisions remain in the attempt journal. These are prior model observations,
not technical proof or permission to relax the acceptance criteria. A new native
revision clears the assessments. Resume preserves them without an API request.
This addresses repeated full-view/crop inspection caused by losing the previous
findings. The frozen v13 package does not contain this later source fix; its
performance must not be credited with the repair.

Project erasure refuses active coordinators and unresolved provider charges. It removes project prompts, decisions, receipts and run records. Shared budgets retain only aggregate spent micro-USD, so erasure cannot restore an already spent allowance. Erasure authority remains restricted to the selected project.

Every generation request is reserved durably before dispatch. The reservation
uses counted input tokens plus a margin, the highest supported cache-write
price, and the maximum output tokens, including reasoning. Reservations across
runs sharing a benchmark budget are admitted atomically. A timeout leaves the
charge unknown and retains the reservation. There are no hidden API retries.
HTTP errors retain available provider request IDs. Token-count preflights have
separate evidence and are not described as generation attempts.

Known receipts account for uncached input, cached input, 30-minute cache writes,
12-hour cache writes, and output. Reasoning is already included in output tokens;
it is reported separately without charging it twice. Prices are a dated snapshot
of [OpenAI standard API pricing](https://developers.openai.com/api/docs/pricing):
GPT-6 Astra input $10, cached input $1, output $50, and cache writes $12.50/$25 per
million tokens, checked on 19 November 2026. Update and verify pricing before
using this snapshot at a later date. Unknown billing categories are held for
reconciliation, never treated as free.

A stored complete response whose usage format becomes supported can be
reconciled locally with `Journal.reconcile_received_usage(run)`. This preserves
the previous error and a reconciliation record. It does not send another request.
A missing provider response cannot be resolved by this method.

Status distinguishes completed, failed, cancelled, budget_exhausted, uncertain,
and quality_unmet. It returns compact receipts, revision references and findings,
not full prompts or encoded previews. Full request/response evidence remains in
the private Store. A completed model review is not independent creative approval.

## Contracts, edits and qualification boundaries

Operation descriptions are versioned in `agent_contracts.json`, selected by
`agent_catalog.py`, and paired with fingerprints of handwritten validators.
Validators remain authoritative; fingerprints alone are not semantic compatibility
proof. Local contract tests and real engine probes supply that evidence.
Registration, machine availability and orchestration qualification are separate.
The registry does not claim every registered engine is qualified.

`agent capabilities --workflow ...` derives versioned operation descriptors,
function definitions and documentation through `agent_operations.py`. Function
schemas describe bounded top-level parameters; the authored profile contract and
native validators govern nested documents. They do not pretend to infer a full
schema from handwritten validators. The coordinator's compact JSON decisions
submit the same operations without placing the discovery inventory in every
model request. Extensions can provide parameter schemas in their descriptors.

The coordinator removes cryptographic inventory and editor selection/history
defaults from decision context after validating them locally. Image review keeps
native layer identities, text, bounds, visibility, masks, warnings and validation.
The current brief and every acceptance criterion remain in every request. Image,
video and document reviews receive their explicit edit contracts; scene and
interaction reviews retain complete parameter limits. Full published evidence
remains in the Store. This projection does not reduce preview resolution or omit
creative review. Behavioral previews can be selected by their published
`inspection/...` paths, with revision and asset-hash checks.

Byte-identical previews are sent once with aliases identifying every sampled
frame or state. Pixels and resolution remain unchanged. Distinct states take
priority when duplicate frames would crowd out a keyframe. Native 3D revision
proofs provide exact changed values and identity/render invariants without
repeating unchanged before/after snapshots; the full proof remains available.

- **Image:** `image.create`, `image.edit`; native layered document and PNG.
  Edits cover existing supported text/style/layer properties. Structural and
  position edits are not exposed by this bounded contract.
- **Video:** `video.create`, `video.edit`; native timeline, titles, audio and MP4.
  Edits cover title text, trims and gains. The locked title-diagnostics engine is
  required. Bounded output receives complete owned decoding plus representative frames at cuts. Sampled visual review does not prove every temporal behavior.
- **Animation:** `construct.create/edit/render/inspect/verify`, restricted to the
  existing Rive profile. Native IDs, RML, compiled Rive, reduced-motion output and
  a local player are retained. Headless browser inspection exercises configured states, intermediate transitions and immediate reduced-motion settling. Inspection failures prevent creative acceptance.
- **Bounded 3D:** `production.create/edit/render/verify/inspect`. Material and light edits
  extend to camera settings, object location/rotation/material assignment, and
  text content/size/extrusion. Mesh topology, object dimensions and render quality
  cannot be patched. Native object identity is retained; no general modeling is
  claimed. Deterministic inspection renders two additional views at unchanged render settings and verifies the native file remains unchanged.
- **Document:** `write.create/edit/inspect/export/bundle`; editable native text,
  guarded typed edits, portable native archive, and PNG/PDF export. The coordinator
  exports PNG pages deterministically after creation/editing. Arbitrary DOCX import
  and complete source-format fidelity remain outside this qualification.

The engine still executes offline. Only the coordinator launcher has API access.
No queue, worker service or project database is duplicated. A new workflow uses
registration, a descriptor and existing adapter validation; coordinator control
flow does not need an engine-specific branch. Optional generic engine compilers
remain product inputs; previous artistic answers are not reused in the pilot.

## Verification and pilot

Run local unit coverage with Python 3.13 and Pillow available:

```sh
PYTHONPATH=. python3 -m unittest discover -s tools -p 'test_*.py'
python3 -B tools/agent_local_probe.py --package /path/to/isolated-package --output /new/probe
```

Use `-B` whenever an external Python helper imports an isolated package's runtime,
including `agent_resume_probe.py` and benchmark helpers. Without it, Python can
write unrecorded bytecode into the package. The packaged launcher already uses
`-B`. Verify package contents after probes; preserve any mutated artifact as
evidence and build a new destination rather than repairing it in place.

`agent_benchmark.py` records fresh runs against frozen briefs, two alternating
baseline/optimized pairs per workflow, using one shared $25 ledger. Its baseline
retains full authored documents and review conversation; a correction reconstructs
in a fresh project. It adds no artificial read-instructions turn. It is an API-level
pilot, not a measurement of the desktop coding-agent harness. This distinction
must remain visible in every cost report.

The report retains failed runs, all model usage, request IDs, uncertain charges,
job/revision references, and elapsed time. Its local compute basis is a declared
$0.10 per allocated machine-hour assumption, not measured electricity. Count
preflight failures, package preparation, engine rebuilds, implementation and
accounting work separately from recurring generation costs. Failed production
attempts must remain in production totals.

`accounting-audit.json` reconciles every run in the shared budget, lists every
render attempt, preserves failed or unfinished runs, and evaluates numerical
gates separately for each cohort. `model-attempts.csv` lists every provider call,
including cached input, cache writes and reasoning within output tokens. Unknown
charges and missing local measurements cannot pass the cost gate. A complete
cohort requires exactly two pairs per workflow; missing or duplicate entries
cannot pass. All earlier cohorts still count against the same $25 allowance.
These numerical gates do not establish baseline fidelity or creative acceptance.

Use `tools/agent_token_breakdown.py --root /path/to/evidence --cohort COHORT` for
per-call input, output, reasoning and image-count diagnostics without provider
requests. Section character counts are structural diagnostics, not measured token
attribution. Actual provider counters remain authoritative.

Preparation usage can be measured separately from an authorized local Codex log:

```sh
python3 tools/agent_preparation_usage.py --history /path/to/local-history.jsonl \
  --since 2026-11-19T11:05:06Z --output /path/to/evidence/preparation-usage.json
```

This reads cumulative token counters and model metadata. It includes cached input
on every recorded request and counts reasoning once within output. It retains no
prompts or transcript content. The report labels its API-equivalent price scenario
separately from actual Codex billing, the $25 benchmark request allowance and
recurring product costs. Refresh it for later work; other conversations and
unrecorded failed requests remain outside this snapshot.

The dispatcher holds a local exclusive lock to prevent duplicate benchmark
launches. Registry and accounting files publish atomically. Existing output
aliases are refused, and a partial write preserves the previous complete file.

Do not claim the accepted optimization goal is complete until every workflow
passes technical and creative checks, aggregate tokens fall at least 50%, no
workflow mean regresses, modeled mean production cost does not rise, all attempts
are included, and the original experimental controls are satisfied.

## Usage receipts and native OCR

New source CLI runs create a usage workflow automatically or join one supplied
with `--usage-workflow`. Status includes its cost receipt. Optional
`--inspection-policy native-ocr-high` or `native-ocr-low` adds local Apple Vision
observations. The default remains high-detail review without OCR. See
[workflow accounting](USAGE.md) for coverage, comparison gates and platform limits.
