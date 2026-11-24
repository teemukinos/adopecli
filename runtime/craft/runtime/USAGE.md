# Workflow usage and cost receipts

A dope CLI now exposes a local usage ledger through the source CLI and MCP. It
combines durable agent calls, every native job attempt, native OCR checks and
incremental usage imported from external coding assistants or media providers.
Production and development workflows have separate scope labels and totals.

This is source functionality. It does not update an installed package, restart
an MCP server, deploy hosted billing or collect usage from another assistant's
account. No provider call is made by a usage command. Existing local billing and
agent budget enforcement remain authoritative; this ledger is a reporting layer.

## Run from this checkout

From `runtime/`, use Python with Pillow installed:

```sh
export PYTHONPATH="$PWD/craft/runtime"
python3 -m studio_runtime --state /path/to/private-state usage --help
```

All examples below use `python3 -m studio_runtime`. An explicitly rebuilt local
package exposes the same arguments after `dobe`. Always pass the same `--state`
before the subcommand. A worker must still run separately for native jobs.

## Start and connect a workflow

```sh
python3 -m studio_runtime --state /path/to/private-state usage start \
  --project PROJECT_ID --workflow poster-with-checks --scope production \
  --workload poster-brief-v1 --quality-contract poster-acceptance-v1

python3 -m studio_runtime --state /path/to/private-state submit PROJECT_ID image.create \
  --parameters composition.json --key first-render --usage-workflow poster-with-checks
```

The workflow ID is an idempotency key. Reusing it with different metadata fails.
The job binding is committed with job admission and remains attached across
retries. Reusing a job key with a different workflow fails. Existing jobs remain
visible in the project receipt; they are not assigned to a new workflow by guess.

For creative agent runs:

```sh
python3 -m studio_runtime --state /path/to/private-state agent run \
  --project PROJECT_ID --workflow image --brief brief.txt --budget-usd 2 \
  --usage-workflow poster-with-checks --inspection-policy native-ocr-low
```

If `--usage-workflow` is omitted, `agent run` creates one and returns its receipt.
Its workload and acceptance identifiers are derived from the specification.
`--usage-scope development` changes the scope of this automatically created
workflow; the default is production. An explicitly supplied workflow keeps its
original scope. Agent status, resume and cancel responses include the receipt.

Image, video, animation, document and other native jobs use the same accounting
path. This does not turn sampled video previews into temporal quality checks.

## Native OCR and deterministic checks

```sh
python3 -m studio_runtime --state /path/to/private-state usage inspect \
  --project PROJECT_ID --workflow poster-with-checks \
  --revision REVISION_ID --path exports/preview.png \
  --expected-text 'STUDIO' --expected-dimensions 1080 1350
```

The artifact must belong to the project. Its immutable blob hash is verified
before processing. The command reports the image hash, dimensions, optional
dimension equality, recognized text with confidence and bounding boxes, and
optional exact-line text matches. Text matching collapses whitespace but preserves
case and punctuation. A phrase split across lines does not match an exact line.
Pass the actual required lines and account for permitted punctuation explicitly.
An absent match can be an OCR error, not a defect in the image.

Apple Vision runs locally on macOS. First use compiles the packaged Swift helper
with an existing `swiftc`; no toolchain or model is downloaded. Other platforms
report `unsupported`; a missing compiler reports `unavailable`. Helper failures
are recorded explicitly. Inputs are bounded to PNG/JPEG, 16 MiB and 16,777,216
pixels. Recognition uses accurate English text recognition without spelling
correction. Other languages are not qualified.

Observations are cached within the project by image bytes, helper source,
platform and configuration. Each inspection retains its own elapsed time and
cache-hit status. Changed bytes or helper identity invalidate the cache. Full
observations remain in the local project journal. Project erasure removes them.
The executable cache contains only compiled helper code, not artifact text.
Image bytes reach the helper through stdin, not a temporary image file. Inspection
holds the existing artifact-access lock so erasure cannot race active processing.
A durable start record precedes helper execution. If the client terminates before
completion is journaled, the receipt retains an unsettled OCR entry and blocks
comparison; it does not infer zero cost or automatically replay the inspection.
There is no automatic reconciliation of those interrupted inspections in this
initial implementation.

Agent policies:

- `high` is the unchanged default: high-detail image review without OCR.
- `native-ocr-high` adds OCR evidence and retains high-detail image review.
- `native-ocr-low` uses low-detail previews only when OCR returns nonempty,
  untruncated observations with every line at confidence 0.8 or above. Explicit
  image selections and crops remain high detail. Missing, failed or uncertain
  OCR keeps high detail. Confidence is a routing heuristic, not a quality score.

Recognized text is labeled as untrusted artifact data. The assistant still reviews
visual quality and must request more evidence for uncertainty. OCR never approves
quality, changes image bytes, edits prompts or regenerates outputs. OCR identity
is pinned in new agent runs and checked on resume. Existing runs retain their
original policy. Coordinator heartbeats continue during helper compilation.

## Import external usage

Create an entry such as `assistant-call.json`:

```json
{
  "id": "provider-request-123",
  "source": "external:codex",
  "domain": "assistant",
  "model": "model-from-the-provider-receipt",
  "tokens": {
    "input_tokens": 12000,
    "output_tokens": 800,
    "cached_input_tokens": 9000,
    "reasoning_tokens": 300
  },
  "cost_microusd": 24000,
  "cost_basis": "usage_priced",
  "seconds": 18.2,
  "evidence": "local:provider-receipt-123"
}
```

These are example values, not a price quote or a measured saving.

```sh
python3 -m studio_runtime --state /path/to/private-state usage record \
  --project PROJECT_ID --workflow poster-with-checks --file assistant-call.json
```

Use one incremental entry per call or charge. Source and ID together are unique
within the project; exact replay is harmless and changed replay fails. Do not
import parent cumulative usage alongside child calls. Do not reimport calls
already recorded by the built-in agent. The ledger cannot infer duplicate billing
from unrelated external IDs or verify an uploaded invoice.

Supported domains are `assistant`, `generation` and `compute`. Image/video provider
fees belong to `generation`; they need not have token counts. Human review and
other uninstrumented work can be represented separately only where the supplied
record has an appropriate measured basis. `tokens: null` means unreported, not zero.
Cached input and reasoning are subsets of input and output; they are not added
again to total tokens. Built-in calls also retain their original provider usage.

Amounts are integer micro-USD: 1,000,000 means USD 1. Cost basis is `billed`,
`usage_priced`, `estimated`, `quoted` or `unknown`. Imported billed amounts are
operator-reported. Unknown amounts require `cost_microusd: null`. Quotes appear
separately and do not count as spending. Reserved agent budget is never reported
as a charge. Uncertain calls remain visible and prevent a completed comparison.

An optional `--compute-microusd-per-hour` on `usage start` applies an explicit
estimate to measured native attempt and OCR time. It is not an invoice or an
automatic estimate of power, hardware depreciation, monthly subscriptions or
cloud CPU prices. Avoid separately importing the same compute cost. Missing
attempt measurements still produce unknown costs even when a rate is supplied.

## Read receipts and compare observed workflows

```sh
python3 -m studio_runtime --state /path/to/private-state usage receipt \
  --project PROJECT_ID --workflow poster-with-checks

python3 -m studio_runtime --state /path/to/private-state usage receipt \
  --project PROJECT_ID --details
```

Receipts show assistant tokens, tokens by domain, cost by evidence basis, known
cost subtotal, unknown entries, native/OCR measurements, cache hits, pending work
and separate production/development/unassigned totals. Native retries and failed
attempts remain included. Sum of measured work is explicitly not end-to-end
latency: tasks can overlap and external activity can be missing. OCR timing
includes a first-use compile when required; OCR peak memory excludes the compiler
and parent process. A cache hit does not claim the original helper's peak memory
as new memory consumption. Input-count preflights are listed separately from
generated tokens.

Total cost remains null until every domain has declared coverage, all work is
settled and no cost is missing or merely quoted. The project-wide view does not
silently assert complete coverage. Native or external preparation, hosted work,
browser inspection and UI review are not comprehensively instrumented by this
first local implementation; leave coverage unknown until any missing work has
been independently accounted for.

Create a separate baseline workflow with the same scope, workload identifier and
quality contract. Use equivalent outputs and settings. Do not rerun a paid
baseline for every production job; retain suitable measured comparisons instead.
After reviewing each outcome, record an assessment JSON:

```json
{
  "quality": "pass",
  "evidence": "local:blind-review-and-usage-audit-123",
  "coverage": {
    "assistant": "complete",
    "generation": "not_used",
    "compute": "complete"
  }
}
```

`pass` is an operator attestation, not an OCR result. `not_used` is refused when
usage in that domain is already observed. Use `unknown` wherever coverage is
incomplete. The assessment is bound to the current receipt fingerprint; new
calls, imports, inspections or changed run outcomes invalidate it.

```sh
python3 -m studio_runtime --state /path/to/private-state usage assess \
  --project PROJECT_ID --workflow poster-with-checks --file assessment.json

python3 -m studio_runtime --state /path/to/private-state usage compare \
  --project PROJECT_ID --baseline poster-baseline --candidate poster-with-checks
```

Both workflows require current passing assessments and matching metadata.
Assistant token savings and total cost savings have separate coverage gates.
Negative savings remain negative. Zero baseline produces a null percentage.
Unmeasured comparisons return null with reasons, not an estimated win. A passing
pair does not establish universal quality equivalence or savings for other media.

## MCP and persistence

The source server adds `studio_usage_start`, `studio_usage_record`,
`studio_usage_receipt`, `studio_usage_assess`, `studio_usage_compare` and
`studio_usage_inspect`. Product identity `dobe` exposes the `dope_usage_*` names.
`studio_submit_job` / `dope_submit_job` accept `usage_workflow`.

Workflow metadata, imported entries, assessments and OCR observations use the
existing project event journal. Existing agent calls and job attempts are read
directly and are never copied into a second billing ledger. Schema version stays
7. Public ledger APIs append records; this is not a tamper-proof financial store.
Project ownership, archival restrictions and full project erasure still apply.

Run local checks without provider access:

```sh
PYTHONPATH=craft/runtime python3 -m unittest discover -s craft/runtime/tools -p 'test_usage.py' -v
PYTHONPATH=craft/runtime python3 -m unittest discover -s craft/runtime/tools -p 'test_agent*.py' -q
```
