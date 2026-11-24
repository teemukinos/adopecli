# Sheets live-child recovery on the private receipt-client image

The staged `craft/runtime/tools/sheets_recovery_acceptance.py` fixture closes the
previously unqualified Sheets-specific supervisor-crash and running-cancellation
cases within this exact private macOS artifact boundary. It records **90 checks,
three durable jobs and four actual native attempts**: two successes, one crashed
attempt explicitly reconciled as stopped, and one cancellation. The check count
includes public command, artifact receipt and package identity assertions.

## Native workload and observed interruption

The fixture creates a synthetic workbook with 7,680 occupied cells across 512
rows. It contains 1,024 formulas and substantial text content within the declared
Sheets admission profile. All formula results equal the independently calculated
integer sum 131,328. No external workbook, macro, paid model or service is used.

During `sheets.calculate`, the fixture observes an actual receipt-bound
`dobe-sheets recalc` child in the recorded attempt process group. It then kills
only its own public worker supervisor. The native group becomes absent, no
revision is published, and the original project head remains unchanged.

After natural lease expiry, public recovery marks the attempt interrupted. An
idle worker does not replay it. Public reconciliation independently establishes
that the registered group is absent, records the evidence and publishes nothing.
No database lease, clock, execution record or production binary is modified by
the fixture.

An explicit retry uses the original job and an idempotency key. Repeating the key
does not create another attempt. Attempt two succeeds and publishes exactly one
new revision. The complete native `original.json` and `document.json` bytes match
the baseline, including every original cell and calculated value. Both exported
project manifests verify; the original checkout remains unchanged.

## Running cancellation

A persistent public MCP client initializes before a separate calculation starts.
After another real native `recalc` child is observed, the client requests
`dobe_cancel_job`. The worker records cancellation, the native process group
becomes absent, and the cancelled job publishes no result or additional revision.
The successfully recovered project head remains intact. The MCP session closes
normally.

Final checks confirm exactly three jobs and four attempts, absence of all four
registered native groups, database integrity and foreign keys, both complete
checkout receipts, and unchanged package verification. SQLite inspection is
query-only; all application mutations use the public CLI or MCP service.

## Execution and resumption

Run the stages in order: `baseline`, `interrupt`, `retry`, `cancel`, `verify`.
Pass the sealed package, a new disposable output directory and the exact expected
guard-verification JSON. Later stages require `--resume`. Completed stages report
their recorded result; a previously started incomplete stage refuses automatic
restart. Inspect its actual durable job and live process handles before recovery.
An observation timeout is not permission to submit or run the work again.

The first external driver wrapped the package in an additional OS sandbox.
macOS refused the nested sandbox before local state or job creation with
`sandbox-exec: sandbox_apply: Operation not permitted`. That refusal is retained.
The corrected local-only driver invokes the unchanged package guard directly;
the guard continues to enforce its native runtime network policy. No production
policy, package content or test condition was relaxed.

## Exact artifact and remaining limits

This run uses private `0.1.0-receipt-client-private.1`, built from `0ca48a3`:

- Image SHA-256: `81c2923e58a2dd3eed8ad38a358c3de2bfb5caf601f1f4c2974914d0258550c3`.
- Guard SHA-256: `568051d5ab916d5e8e3036c86b66684d7688ad0d47a6483ba5493714f313b388`.
- Seal SHA-256: `ea6fb59b8906ccfb0da8ba52fd6a1347df12e9bd33ef02ad702963cad504611d`.
- The guard verifies 7,063 sealed entries. No runtime module or native engine is
  changed for this fixture, and no replacement package is built.

This is a bounded native calculation/recovery result. General XLSX support,
rendered HTML, owner quality acceptance, other Sheets operations under every
failure mode, power-loss recovery, stock-host security, publisher identity,
Linux/Cloud and the complete Local/Cloud release remain separate requirements.
Earlier Sheets minimum, generic supervisor and campaign evidence retain their
original source and artifact boundaries.
