# Campaign interruption and explicit recovery

`craft/runtime/tools/campaign_recovery_acceptance.py` exercises the retained
full twelve-second announcement through an independently authenticated sealed
public CLI package. All runtime mutations use that public CLI. The observation
connection enforces SQLite `query_only`; SQLite may maintain its normal WAL
index. The fixture never changes the lease, wall clock, store rows or engine.

Run the stages in order: `interrupt`, `retry`, `compare`, `cancel`, and
`dependencies`. Each later stage uses `--resume` and the same output directory.
The fixture requires the package directory, an unused output directory, the
complete original campaign checkout, and `--expect-verification` containing
independently authenticated guard output. A completed stage is not rerun.
An existing active or failed native attempt is never silently restarted. Only
an authoritative queued job with attempt zero can continue after a pre-start
observation failure.

The interruption stage observes at least three actual rendered PNG frames and
the registered live Blender child, then kills only its owned supervisor. The
attempt watchdog stops its native group. The fixture waits for kernel evidence
of group absence and natural lease expiry, observes the interrupted state and
proves that an idle worker cannot automatically retry it. Public reconciliation
preserves the old attempt without publishing or deleting artifacts.

The explicit retry uses the same durable job, with an idempotent retry key.
Repeated submission and retry requests must not create another attempt or
revision. The full recovered movie remains 1920 × 1080, 24 fps and twelve
seconds. Independent pinned FFmpeg decoding compares every RGB pixel in all
288 frames through decoded-frame hashes. The complete construction document,
all native object records and exact linked asset/font bytes remain unchanged.

A separate actual partial render exercises public cancellation, group teardown,
no publication and unchanged project head. Copied bundles with a missing logo
or unreadable font must be rejected before creating a project, job or revision.
Those dependency cases qualify ingestion, not render-time fallback behavior.
Original inputs remain unchanged. Every failed or interrupted attempt is kept.

This is same-host process interruption and explicit full rerender, not a
checkpoint continuation from the last frame, power-loss/reboot proof, a clean
machine, Linux/Cloud proof or billed-cost evidence. It does not establish
provider cancellation, a monetary quote or human creative approval. No remote
action, service change, VM restart or publication is part of this fixture.
