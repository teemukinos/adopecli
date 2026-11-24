# Studio runtime development

The existing Craft integration is the engine layer for further development. Preserve the five pinned engines, MCP adapters and skill recipes. Keep hosted deployment configuration and private customer material outside this public repository.

## First increment: file transfer and request correctness

Implemented locally:

- Uploads use descriptor-relative directory traversal without following symlinks, exclusive random temporary files, and atomic publication. Interrupted uploads retain the previous destination.
- Downloads validate every manifest path and size before writing, reject directory symlinks, stream content, and publish atomically. The default no-overwrite policy holds even when another writer creates the destination during transfer.
- JSON MCP responses wait for the matching result rather than returning a progress notification.
- Disconnected requests remain in-flight until an engine response or exit. Session eviction cannot mistake a disconnected render for idle work. Duplicate in-flight request IDs are refused.
- Failed secret, environment and version probes cannot report success solely from empty stdout.

These changes do not provide a hostile-process sandbox, tenant isolation, a persistent queue, or an engine execution deadline. A process with the same filesystem privileges still requires a separate isolation boundary. Concurrent uploads to one path have last-writer-wins semantics; project revisions must eventually provide immutable artifact ownership.

Validation uses local temporary fixtures and a loopback HTTP server. It covers the previously reproduced defects, directory and destination symlinks, empty and interrupted uploads, concurrent publication, malformed manifests, download size mismatch, progress routing and probe failures. It does not claim that the changed image has been deployed or that the engines have been requalified. Local regression scripts and evidence stay in the ignored `.verify/` directory; no remote test workflows are added.

Validation recorded on 13 November 2026:

- `python3 .verify/check-runtime-safety.py`: 18 local checks passed, including JSON and SSE responses, duplicate requests and concurrent no-overwrite publication. Evidence: `.verify/runtime-safety-check.log`.
- `CI=true scripts/verify.sh --skip 18`: 26/26 release checks passed, including 43 existing unit tests, package installation and a fresh-copy contributor run. Evidence: `.verify/release-check.log` and `.verify/logs/`.
- Check 18 (maintainer setup) was explicitly skipped. Checks 21 (real applications) and 22 (private source synchronization) were skipped by the existing CI-mode behavior. No remote engine checks were run.

## In progress: durable local image/vector workflow

Build a supervisor above the existing engine bridge, with one public Studio MCP connection. Start with PhotoCraft and VectorCraft.

The first implementation now lives in `runtime/`. It includes a SQLite job journal, a separate supervisor, ten local MCP tools, typed vector creation/text revisions and image adjustments and immutable native/export snapshots. A real VectorCraft 0.24.1 creation and revision passed cold reopen in separate worker processes. See [runtime/README.md](runtime/README.md) for exact evidence and open gates. PhotoCraft 0.23.1 adjustments and revisions, asset import, portable re-import and explicit safe retries now have local evidence. Packaging, media qualification and hosted tenancy remain in scope; this is not the completed goal.

1. Define a versioned project manifest with asset hashes, engine versions, native files, export intent and an explicit source revision.
2. Persist submissions in a local SQLite journal before acknowledging them. Scope idempotency keys to a project and reject reuse with different parameters.
3. Run queued operations through typed engine adapters. Persist attempts, progress, outputs and terminal errors separately from HTTP sessions.
4. Publish immutable revisions only after successful output validation. Retain original native files and exports.
5. Recover interrupted work conservatively: mark uncertain attempts explicitly; never silently repeat a possibly paid or externally visible operation.
6. Expose cancellation with confirmed versus pending states, execution deadlines and resource policies.

Acceptance: submit a real image/vector job, restart the supervisor, reconcile the job, terminate all relevant engine processes, reopen the saved native project, revise one element, and export a new revision. The original revision and unchanged assets remain intact. Engine output properties and source editability must both be checked.

## Later increments

- Extend the same contract to FilmCraft and EffectCraft, with exact media timing, audio and caption validation.
- Package a local installer, runtime supervision, offline policy, credentials, status, updates and rollback. Local operations must not require a Studio cloud account.
- Add workspace identity, scoped storage access, isolated hosted workers, durable scheduling, quotas and usage accounting. A shared bearer token is not customer authorization.
- Introduce generation adapters with budget reservation, provider request reconciliation and measured usage. Live paid validation requires an explicit budget.
- Maintain qualification entries for all seventeen applications. The current five binary integrations do not establish complete application support, maintained source forks or renamed release artifacts.

Remote publishing, deployments, paid generation and additional remote validation are separate actions requiring explicit owner instructions.

## Local application development

`local/` now builds a macOS Apple Silicon application containing the runtime, pinned image/vector engines, Python and Pillow. It includes an offline launcher, status/settings application, per-user launchd supervision, versioned installation, checksum verification, schema-aware rollback and retained-data uninstall. See local/README.md (`craft/local/README.md`) for commands, exact behavior and release gates. These components do not establish signed distribution, a clean-machine install, all-engine support or hosted tenancy.

Runtime imports are isolated from project contents. Local attempts now record and enforce resource budgets; memory and working-file limits use supervisor sampling, while CPU/file limits use inherited OS limits. The source-run implementation remains available on Linux. Hosted workers still require a separate filesystem/network boundary and hard resource quotas.

The current local acceptance also demonstrates a packaged MCP submission surviving client exit, launchd restarting a killed supervisor, conservative interruption without replay, resource exhaustion followed by explicit retry, tamper rejection, schema-compatible rollback and uninstall retaining revisions. The test service was removed after qualification. Source and evidence distinguish the unsigned development application from a finished signed release. The complete four-part goal remains active, with hosted tenancy and the documented packaging/media gates still unfinished.

Installation now has a durable recovery journal and explicit repair, including safe handling of a database schema newer than the previous package. Same-version installation is idempotent. Retention cleanup preserves all projects/revisions/assets and uncertain attempts, excludes a running worker when applying changes, and coordinates with artifact commits. The status application provides workspace selection, cleanup preview/confirmation and repair controls. The builder checks Mach-O minimum OS versions and explicitly targets macOS 12.0 instead of accidentally inheriting the build machine's OS version. Signing, clean-machine and complete OS/lifecycle qualification remain open. Hosted tenancy remains the next major implementation stage.

## Hosted control plane implementation

The first hosted implementation now lives in hosted/ (`craft/hosted/README.md`). It verifies asymmetric user JWTs, checks live workspace memberships, uses forced PostgreSQL RLS with separate API/coordinator roles, and persists jobs, leases, reservations, retries and append-only usage. Publication checks the project head and commits metadata together with settlement. Expired workers retain their reservation and concurrency slot until their termination is reconciled.

The initial control-plane increment did not include hosted execution. Its transaction fixtures use synthetic manifests and are not represented as native-engine evidence. The subsequent integration below adds private storage and real disposable workers; production remote-MCP authentication/deployment remains open. No remote service was changed.

The hosted path now uses private Supabase Storage and disposable, credential-free Linux engine containers. The coordinator records start intent and observed termination before accounting, retains uncertain reservations, and independently enforces cancellation while a container watchdog covers coordinator death. A baked worker image completed native image/vector creation and revision against real local Postgres and Storage services. Hosted image export also reopened and revised in the offline Mac package. These are Linux ARM64/local-integration results, not an authorized production deployment; x86-64 and deployment/authentication qualification remain open. The following increment qualifies hosted bundle import and file retention locally.

Hosted import now queues an uploaded project ZIP as a durable, isolated job. Qualified image/vector sources cold-reopen, reproduce their exports and retain their original hashes before publication. Local Mac to hosted Linux to local Mac cycles each completed another native revision. Import rejects malformed archives and incorrect vector object mappings.

Owner-only hosted archival, upload abandonment, project-file deletion and bounded cleanup preserve historical metadata and accounting. One durable outbound-write intent per object prevents retries from recreating a deleted object. Uncertain writes stay charged until exact stored bytes establish publication; deletion then requires observed canonical absence. Delayed-upload and lost-deletion-response fixtures passed against real local Storage. Settled attempts also recover interrupted scratch cleanup while preserving receipts. Local evidence is in `.verify/hosted-portable/`; no remote write occurred. Operator reconciliation for unresolved write intents, production auth/transport and rollout qualification, local signing/lifecycle gates and broader native workflows remain unfinished.

## Local project retention

The local journal now migrates to schema 3 with explicit active, archived, deleting and deleted project states. CLI, MCP and status-window controls support archival/restoration and previewed artifact deletion. Deletion excludes the worker, preserves immutable metadata and cross-project blob references, commits intent before filesystem removal and resumes after interruption. Uncertain historical attempts remain protected.

Local qualification includes native image/vector revisions after schema migration, real launchd installation upgrade and incompatible rollback refusal, shared-blob preservation, import/deletion races and process-interruption recovery. The updated settings application cannot migrate a workspace still assigned to an older installed reader. Evidence is under `.verify/local-project-retention/`. Hard total-storage quotas, release identity, complete GUI/lifecycle qualification, production hosted authorization/operations and the broader native suite remain unfinished.
