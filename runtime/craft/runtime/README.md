# A dope CLI durable runtime

This runtime adds persistent projects, jobs and immutable native revisions above the Craft engine layer. The source-run entry point requires Python 3.10 or later and the pinned engines needed by the selected operations. The early Image/Vector examples below use VectorCraft 0.24.1 and PhotoCraft 0.23.1 on PATH; image validation requires Pillow or FFmpeg. This source setup is not the supported end-user installation route. The offline macOS package is assembled by ../local/build.py (`craft/local/build.py`).

## Current scope — 19 November 2026

The [source inventory](../CAPABILITIES.md) records seventeen native application families with 85 native operation names. Eleven additional local construction, photographic-production and optional synthesis operations bring local registration to 96. Hosted source registration covers the 85 native operations plus portable import, for 86; it excludes those eleven additional local operations. Registration does not mean every input, platform or model is qualified. Discover installed engine availability independently from the registered names.

The private macOS ARM64 `0.1.0-plan-client-private.1` image, built from `e58a351`, contains all seventeen native engine families and exposes eighteen local MCP tools. Its installed Cloud plan client has separate local PostgreSQL/loopback qualification with synthetic identity, prices and native receipts. Fixture correction `e351267` preserves the public CLI alias without changing the image's production code. Earlier all-family and campaign execution retains its own exact-artifact boundary; it is not automatically requalified by a later package build.

These are private development results. Full Linux engine execution, deployed Cloud service, actual provider charges, publisher signing/notarization, stock-host installation, complete notices and release acceptance remain open. The early Linux ARM64 Vector evidence below is not complete Linux support. See [qualification](../QUALIFICATION.md), local distribution (`craft/local/README.md`) and hosted plans (`craft/hosted/USAGE_PLANS.md`) for the supported boundaries.

Named `dev.*` packages and dated evidence below are historical checkpoints, preserved with their original counts and limits. They do not describe the current package inventory. API examples retain their existing command and identifier spelling.

## Run locally

In an open-source checkout, run `scripts/setup` once and then use `bin/dope` from the repository root. It sets the paths, state folder and network-deny sandbox described below.

Source usage accounting now includes [workflow cost receipts and native OCR checks](USAGE.md).
The source server adds six `*_usage_*` tools and optional job workflow bindings.
The private package inventories above remain historical; installed packages are
not upgraded by changing this checkout.

From the repository root:

```sh
export PYTHONPATH="$PWD/craft/runtime"
python3 -m studio_runtime --state /path/to/private-state worker
```

Run the worker as a separate supervised process. Submission clients and MCP connections may exit while it works. Use a dedicated private state directory; it contains SQLite metadata, immutable blobs and attempt logs. Do not share this directory with untrusted users or engines.

Connect an MCP client to this command, with the same `PYTHONPATH` and state directory:

```sh
python3 -m studio_runtime --state /path/to/private-state mcp
```

It exposes eighteen tools: the thirteen lifecycle tools for capabilities, project creation/listing, archival/restoration, artifact deletion, durable submission/status/cancellation/retry, revision metadata, project export, asset import and project import; three typed planning tools for construction, photographic production and synthesis; and two tools for listing and explicitly reconciling held attempts. `studio_export_project` writes a fresh directory containing native sources, exports and a versioned `project.json` manifest. It refuses an existing destination. Engine availability is reported separately from supported operation names.

The CLI exposes the same lifecycle:

```sh
python3 -m studio_runtime create-project "Example"
python3 -m studio_runtime submit PROJECT_ID vector.create --parameters composition.json --key first
python3 -m studio_runtime job JOB_ID
python3 -m studio_runtime submit PROJECT_ID vector.revise_text --parameters revision.json --key change-caption --source REVISION_ID
python3 -m studio_runtime checkout REVISION_ID /path/to/new-export-directory
```

When using a non-default state directory, pass the same `--state` value before every subcommand. The default is `~/.studio/runtime` or `STUDIO_STATE_DIR`.

`composition.json`:

```json
{
  "width": 320,
  "height": 200,
  "objects": [
    {"name": "background", "type": "rectangle", "x": 0, "y": 0, "width": 320, "height": 200, "color": "#18202a"},
    {"name": "caption", "type": "text", "x": 20, "y": 90, "text": "Original caption", "size": 20, "font": "Source Sans 3", "color": "#ffffff"}
  ]
}
```

`revision.json`:

```json
{"text": {"caption": "Revised caption"}}
```

Use an installed font family. Font substitution and text overflow reported by the engine fail the job. Vector operations support compositions of rectangles, ellipses, polygons and text, named text revisions and targeted geometry revisions. They are not arbitrary engine commands or complete VectorCraft support.

Shapes are filled with `color` and have no outline. An ellipse takes its bounding box: `x` and `y` are the top-left corner, plus `width` and `height`. A polygon takes the same box plus `sides`, an integer from 3 to 64. It is regular, has one corner straight up, and is drawn as large as the box allows, centred in it:

```json
{"name": "badge", "type": "polygon", "x": 200, "y": 40, "width": 80, "height": 80, "sides": 6, "color": "#f5c542"}
```

`vector.revise_geometry` takes a source revision and absolute bounds in points:

```json
{"objects": {"background": {"x": 35, "y": 20, "width": 120, "height": 70}}}
```

Positions use the top-left of the object's bounds, including for text (not its
baseline). Omitted coordinates and dimensions stay unchanged. Rectangles and
ellipses support position and size; text supports position only. For a polygon,
the bounds are its bounding box: the polygon is fitted into the new box again. Positions must be between -8192
and 8192 points and dimensions between 1 and 8192 points. The adapter checks the
actual native bounds and unchanged properties of other named objects before
publication. Unknown names and unsupported geometry fail without changing the
project head. This operation is local-only until its Cloud contract is qualified.

## Persistence and recovery

- SQLite WAL with full synchronization records submissions before they are acknowledged. Idempotency keys are scoped to projects; reuse with different parameters is rejected.
- A kernel lock prevents duplicate local supervisors for one state directory. Workers claim jobs transactionally, renew expiring leases and carry fencing tokens. A stale worker cannot publish a revision.
- Each attempt runs in its own process group with an allowlisted environment. Cancellation and deadlines stop that group before recording the terminal outcome. An attempt watches its parent and stops itself if its supervisor disappears.
- Expired active leases become `interrupted`. They are never automatically replayed. This preserves uncertainty rather than risking duplicate external effects. Explicit retry is available only for the four isolated local operations, with an idempotency key and a three-attempt limit. Provider operations require separate reconciliation.
- Native files and exports are copied to content-addressed storage. A revision becomes visible only when its manifest, project head and successful job state commit together. Unreferenced staged blobs may remain after failure; explicit retention cleanup can remove old unused files after the worker stops.
- Publication requires the exact source revision to remain the project head. Competing edits cannot silently overwrite each other.
- A checkout verifies hashes and copies files. Engine edits cannot mutate the stored revision through hard links.

The vector adapter saves a native `.vectorcraft` document, exports SVG/PNG, terminates the engine, reopens that native source in a fresh engine and checks that the SVG export is byte-identical. Text revisions use stable engine object IDs saved alongside the native document. This is structural/export evidence, not a claim that every creative brief is visually correct.

## Recorded local evidence

On 14 November 2026, local Linux arm64 execution using VectorCraft 0.24.1 with no network, 2 CPUs and 4 GB RAM completed creation and text revision in two separate supervisor processes. Both revisions passed native cold reopen; the original export and object map were preserved. Evidence is retained locally in `.verify/durable-native-evidence/`.

Local execution limits are configurable through `limits`; limits are recorded with each attempt. CPU and file limits are inherited by engine children; the supervisor monitors memory, process count, working files and elapsed time. These are local execution budgets, not hosted tenant isolation.

The local journal checks cover persistence, idempotency, concurrent claims, workspace-scoped lookups, cancellation, deadlines, lease fencing, stale revision rejection, event history and corrupt artifacts. Protocol checks verify durable submission across three independent MCP processes. These checks do not establish hosted tenant isolation.

A separate real-engine crash check killed the supervisor after its attempt started. The orphan attempt stopped, the persisted lease expired, and a fresh store reconciled the job to `interrupted` without publishing or replaying it. A running-job cancellation check ended as `cancelled` with no project revision. Evidence is under `crash-state/` and `cancel-state/` in the local evidence directory.

The journal's 11 local checks and the existing transfer/request checks (18) passed. The repository command `CI=true scripts/verify.sh --skip 18` passed 26/26, including the existing 43 unit tests. The maintainer-setup, real-application and private-source checks were skipped as documented in the repository. No remote tests or deployment occurred.

## Remaining work toward the full goal

- Broaden image layer/mask qualification and qualify media workflows.
- Add resource policies and complete dependency packaging, including font files and license records.
- Finish the local application release gates (`craft/local/README.md`), including signing, clean-machine qualification, reboot/login behavior and interruption recovery.
- Finish production qualification of hosted tenancy (`craft/hosted/README.md`), including client authorization, deployment and operational recovery. Its local Postgres/Storage integration is implemented; SQLite workspace predicates are not customer authorization or a sandbox.

## Image revisions, imports and explicit retries

Import an image using `import-asset PROJECT_ID INPUT_FILE`. Submit `image.adjust` with parameters such as `{"asset":"ASSET_ID","brightness":25,"width":160}`. Subsequent `image.revise` jobs take the previous source revision and adjustment parameters without an asset ID. The qualified subset accepts 8-bit images up to 8192 pixels per dimension. It retains the original asset, saves a native `.pcraft`, checks layer/mask identity, and compares decoded pixels from the saved composite with a fresh-process native export.

### Editable image compositions

`image.create` starts an 8-bit RGB composition with named solid-fill, embedded-asset and text layers. Layers are ordered from bottom to top above the reserved `background` layer. Import each PNG, JPEG or self-contained SVG into the project before submitting its asset ID. SVG artwork must use outlines, without scripts, external resources, embedded media or text dependencies. Source bytes are retained as project assets; placement uses embedded smart objects in the native document.

```json
{
  "width": 256,
  "height": 160,
  "background": "#182133",
  "layers": [
    {"type":"solid","name":"panel","color":"#334466","opacity":0.5,"mask":{"rect":[8,8,80,80]}},
    {"type":"asset","name":"logo","asset":"IMPORTED_ASSET_ID","center":[48,48],"scale":100,"mask":{"rect":[24,24,24,48]}},
    {"type":"text","name":"caption","x":12,"y":120,"text":"Studio Åäö Ω Ж","font":"Inter","size":16,"color":"#ffffff"}
  ]
}
```

Text positions are baseline coordinates in pixels; sizes are points at 72 ppi. Asset `center` is in canvas pixels and `scale` is a percentage. Masks use canvas rectangles `[x,y,width,height]`, with optional density from 0 to 100 and feather from 0 to 1000 pixels. Background accepts `transparent` or a six-digit hex color. Names are unique identifiers, and the request supports up to 64 layers and 128 KiB of JSON.

`image.edit` takes the current source revision and an `edits` list. Each entry names an existing native layer. Text, font, size and color changes apply to text layers; opacity, visibility and masks apply to supported layers. Supplying a mask rectangle replaces its geometry; density or feather alone preserves its pixels; `null` removes it.

```json
{"edits":[{"name":"caption","text":"Revised Åäö Ω Ж"},{"name":"logo","mask":{"density":50}}]}
```

Revisions preserve native layer IDs, layer order, unrelated layer properties, embedded source blobs and retained source assets. Each save cold-reopens in a fresh engine process and compares PNG pixels with the native full composite. A portable bundle can be imported and edited again by native layer name; the adapter does not trust sidecar IDs. Whole-canvas resize remains available through `image.revise`. Its brightness and vibrance commands require an active pixel layer and are not global adjustments for a layered composition.

Inter and JetBrains Mono are the currently admitted engine-bundled font families. The font manifest records available faces and missing-family checks. PhotoCraft's current inspection interface does not establish glyph coverage for arbitrary Unicode text; `glyph_coverage_verified` remains false. This is not a claim of complete typography qualification. External fonts, nested layer groups and wider editor operations still need development.

`import-project BUNDLE_DIRECTORY NAME` verifies the manifest, relative paths, hashes and file sizes before creating a new project. It rejects symlinks and nonregular files. Import proves bundle integrity only; the imported validation record explicitly says that native cold reopen is pending. A subsequent typed revision reopens and validates that native file. Vector inspection rejects missing/substituted fonts, missing glyphs and warnings, and records resolved font dependencies.

`retry JOB_ID --key RETRY_KEY` explicitly requeues a failed, cancelled or interrupted local job. It retains attempt history, gives the new attempt a fresh fence, and refuses a changed project head. Reusing the retry key never starts another attempt. External provider operations are excluded.

Additional evidence on 14 November 2026: ten local import/retry checks passed; ten MCP tools were exercised through the protocol listing. PhotoCraft 0.23.1 creation, revision, export/import into a separate state root and revision after import passed offline. VectorCraft 0.24.1 passed the same portable revision cycle with exact font resolution. Evidence: `.verify/durable-native-evidence/photo-v2/` and `vector-v2/`. The earlier `photo/` run used a faulty version parser; its date-like version field is superseded by `photo-v2`, not valid engine-version evidence. The previously crashed vector job succeeded on explicit attempt 2 with exactly one published revision; `crash-state/retry-evidence.json` follows the retained original interruption record.

## Retention cleanup

`cleanup` previews unreferenced blobs, abandoned staging files and terminal attempt directories older than 24 hours. `cleanup --apply` removes that preview's eligible classes after recomputing references under an exclusive artifact lock. The local worker must be stopped before applying cleanup. `--older-than-hours` accepts a retention age of at least one hour.

Every imported asset and published revision of a project that has not been explicitly deleted remains referenced and is retained. Interrupted attempts, unknown directories, job metadata and event history are also retained. Cleanup never removes a project or a revision. Artifact writes hold the same lock from blob creation through metadata commit, so cleanup cannot delete an import that has not yet committed. Symlinked storage directories and unsafe candidates are refused. This is an explicit retention policy; it does not impose a hard total-storage quota or automatically discard historical revisions.

## Project archival and artifact deletion

Schema 3 adds project states and a separate project event history. Existing schema 1/2 projects migrate to `active` without rewriting their revisions. Migration requires the worker to be stopped. Older packages reject schema 3; the installer refuses a rollback to an incompatible reader. A newer settings application refuses to migrate a workspace still assigned to an older installed package; install the update first.

Use `projects` to list up to 100 projects, including archived/deleted entries. Pass `--after` with `next_project` to continue. `project-state PROJECT_ID archived` blocks new submissions, retries and asset imports while retaining export access. `project-state PROJECT_ID active` restores an archived project. Current queued/running/validating/interrupted jobs must first settle.

`delete-project-artifacts PROJECT_ID` previews the specific retained blobs and known attempt folders that can be removed. `--apply` requires the worker to be stopped and commits irreversible deletion intent before touching files. A project becomes unavailable for export as soon as deletion starts. A failed or interrupted deletion is resumed by repeating the same command. It recomputes shared references under the artifact lock, so a newly imported reference cannot be removed by an old plan.

Blobs shared with any other retained project, including another internal workspace, survive. The last project referencing a blob may remove it. Project/revision/job metadata, manifests, source parameters and event records remain; this is artifact deletion, not personal-data erasure. External source files, exports outside the runtime, and unidentified orphan/staging files are not targeted. General age-based cleanup remains available for eligible unreferenced processing files. A project with any unresolved historical attempt is refused even after a later attempt succeeds; those records are never silently treated as confirmed termination.

The MCP tools are `studio_list_projects`, `studio_set_project_state` and `studio_delete_project_artifacts`; deletion defaults to preview and requires a boolean `apply`. Exports, imports, publication and deletion coordinate through the same artifact lock. Archival preserves every revision until a separate explicit deletion request. Neither archival nor deletion imposes a hard total-storage quota.

Local checks cover concurrent schema upgrades, a running-worker migration refusal, cross-workspace shared blobs, import/deletion races, interrupted unlink recovery, immutable history, uncertain-attempt refusal, symlinks and MCP argument validation. Packaged native image/vector revisions passed after migration and archive/restore. Evidence remains under `.verify/local-project-retention/`.

Schema 4 additionally fences database writes through a connection-local runtime guard. Older live clients must restart after the upgrade; an existing connection cannot continue writing into a workspace that has moved. The local manager can provision bounded workspace storage (`craft/local/README.md`) on macOS. Its kernel-enforced capacity is separate from retention policy and sampled attempt budgets. Capacity checks preserve cleanup and failure settlement while refusing new work when recovery headroom is unavailable. Plain directory workspaces remain supported without an aggregate capacity limit.

### Explicit local project erasure

`erase-project PROJECT_ID` previews the separate removal of local records and
unshared managed files. `--apply` requires a stopped worker and proof that all
selected work is settled. MCP exposes `studio_erase_project` (or
`dope_erase_project` under the Dobe protocol identity). Shared blobs, original
imports, external exports, hosted records, assistant transcripts and backups
remain separate. Database cleanup can stay pending while readers hold old pages
or space is insufficient; repeat the same erasure after resolving the reported
condition. Ordinary writes remain fenced until cleanup completes. This is not
guaranteed physical erasure from storage media. See [the erasure contract](LOCAL_ERASURE.md)
for schema 6, authority boundaries and qualification limits.


## Interrupted execution reconciliation and schema 5

Schema 5 records the machine, boot and process group for new local attempts. The worker commits the process group before admitting the engine through a private pipe. If the worker dies before admission, the child exits without running the engine. If an engine leader exits while its group remains present, the attempt becomes `interrupted`; no result is published or declared safely failed. Cancelling or expiring a queued retry leaves the previous attempt's uncertainty intact.

Stop the worker before previewing or applying reconciliation:

```sh
python3 -m studio_runtime --state /private/studio-state attempt-holds
python3 -m studio_runtime --state /private/studio-state reconcile-attempt JOB_ID --attempt 1
python3 -m studio_runtime --state /private/studio-state reconcile-attempt JOB_ID --attempt 1 --apply
```

`attempt-holds` lists up to 100 unresolved attempts, including historical attempts of jobs that later succeeded. Pass its `next_cursor` as `--after` to continue. MCP exposes the same contract through `studio_list_attempt_holds` and `studio_reconcile_attempt`; the local stdio server now exposes fifteen tools. Clients address attempts by job ID and attempt number, never their internal fencing token.

Reconciliation requires positive evidence: the engine was never admitted, its recorded group is absent on the same machine and boot, or the same machine has booted again since registration. Process inspection sends signal zero only. A present or reused group, permission error, different machine or unsupported operation remains held. The reconciler never kills a remembered PID, retries a job, publishes uncertain output or deletes artifacts.

After an execution leader exits, the supervisor allows up to two seconds for the
kernel to remove its remaining native children. This also covers transient macOS
permission errors during process teardown. It still requires an observed absent
group: persistent presence or inspection denial records an interrupted attempt
for reconciliation, without terminating the supervisor or publishing a result.
The wait sends no termination signals to a remembered process group.

Applying an eligible preview records an immutable receipt with the previous state, error, finish time and termination evidence. The attempt becomes `failed`; its active job lease is fenced. Settling a historical attempt preserves later queued retries, completed jobs and published revisions. Repeating reconciliation returns the same receipt. Cleanup, project artifact deletion and capacity changes can proceed once their other conditions are satisfied. If a bounded volume is full, reconciliation releases its recovery reservation only after every unresolved local execution is proved stopped or never admitted. Repair replenishes that reservation after space is available.

At severe capacity pressure, SQLite opens in exclusive locking mode so inspection can use an in-memory WAL index without allocating a new shared-memory file. Committed WAL data remains visible; the database is not opened as an immutable snapshot. Existing database readers must close before exclusive access can proceed. This follows SQLite's documented [WAL operation without shared memory](https://www.sqlite.org/wal.html#use_of_wal_without_shared_memory).

Attempts created before schema 5 have no launch registration. An owner who knows that an attempt ran on this machine can explicitly record that fact with `--apply --confirm-local-origin`. This records an audit baseline only; the attempt remains held until a later boot of this same machine. Agents must not invent that attestation. A copied workspace or unknown origin remains held. Actual reboot qualification remains a release gate; a simulated boot identity change is not reboot evidence.

The schema upgrade requires a stopped worker, preserves existing projects and history, and rejects older readers and already-open older writers. Install the matching package before using its management commands. These guarantees cover the supported local adapters and their process groups, not hostile programs that deliberately escape process groups or a cloned machine identity.

Local evidence under `.verify/local-reconciliation/` covers admission-boundary SIGKILLs, a surviving descendant, atomic receipt recovery before and after commit, migration from a real schema-4 package, and kernel ENOSPC with both absent and uncheckpointed WAL files. Packaged image/vector revisions and a real native-engine supervisor crash passed; explicit reconciliation followed by retry published one revision and permitted a later capacity change. Legacy reboot logic uses a simulated identity change and does not qualify an actual reboot. Earlier fixture failures and the initial full-volume inspection failure are retained alongside the corrected runs.

## Native video timelines

The local source runtime now supports typed native timeline creation and named text, trim and gain edits. See [VIDEO.md](VIDEO.md) for parameters, preserved editable files, measured 15-to-17-second revision evidence and remaining qualification. Video is included in the current private macOS package and registered in hosted source admission. Actual Linux worker and deployed-service qualification remain open; source registration is not a deployed availability claim.

## Native audio production

`audio.create` imports WAV assets, places editable named clips on named tracks,
trims their source windows, applies clip/track gain and fades, and renders a
stereo float32 WAV. `audio.edit` revises named clip timing/gain/fades or track
gain without rebuilding unrelated native content. All positions and lengths
are integer samples at the session rate; imported sources are resampled by the
native engine. The current source contract requires SoundCraft 0.20.1 (or its
maintained `dobe-audio` build) and remains local-only. Installed Audio packaging
and Linux/Cloud qualification are separate gates.

Example create parameters, after importing the two assets into this project:

```json
{
  "sample_rate": 48000,
  "frames": 144000,
  "tracks": [
    {"name": "voice", "clips": [
      {"name": "opening", "asset": "IMPORTED_ASSET_ID", "start": 0,
       "source_in": 12000, "frames": 60000, "gain_db": -3,
       "fade_in": 4800, "fade_out": 4800, "fade_shape": "linear"}
    ]},
    {"name": "music", "gain_db": -6, "clips": [
      {"name": "bed", "asset": "SECOND_ASSET_ID", "start": 48000,
       "frames": 96000, "fade_in": 4800, "fade_shape": "equal_power"}
    ]}
  ]
}
```

Example edit parameters, submitted with the current source revision:

```json
{"edits": [
  {"type": "clip", "name": "opening", "source_in": 24000, "frames": 48000, "gain_db": -6},
  {"type": "track", "name": "music", "gain_db": -9}
]}
```

The supported contract has these bounds:

- 44.1, 48 or 96 kHz sessions, up to 600 seconds, 16 tracks and 64 clips.
- Mono/stereo RIFF WAV input: 8/16/24/32-bit integer PCM or finite float32.
  Source files are at most 512 MiB and 600 seconds. Decoded imports, counting
  each placed source and resampling, total at most 64 million channel samples.
- Clips on each track are ordered without overlap and use matching channel
  counts. Tracks may overlap freely for mixing. Names are unique identifiers.
- Clip and track gain range from -60 to +12 dB. Linear, equal-power and S-curve
  fades fit inside their clips. Every edit validates the resulting whole session.
- Native `.scraft` format 1, packaged `Audio Files/` sources, stable IDs and an
  object map remain editable. Imported originals are retained separately.
  External references, hosted plugins, instruments, MIDI/video, automation,
  frozen tracks and unsupported routing are refused before opening a session.
- A separate native process reopens and renders the saved session. Publication
  requires matching PCM, source hashes and the complete native session, including
  metadata outside its tracks. Native f32 gain precision is preserved when
  comparing the saved document; fields silently discarded by the native reader
  fail publication. See the [Audio acceptance record](../qualification/AUDIO_MINIMUM.md)
  for the sealed local cue, format checks and portable revisions.
- The exported float32 WAV is not normalized or integer-clipped. Validation
  reports its measured peak; values above 1 retain headroom for later mixing.

These are production-tool operations, not model inference. No additional paid
image, video or audio generation service is used by this contract.

### Native photo libraries

`photo.create` imports 1–32 distinct originals into an editable native photo
library. Each entry in `photos` has a unique `name`, an imported `asset`, and
`format` (`png`, `jpeg`, `tiff` or `dng`). Optional `adjustments` map native control
names to numbers: `light.exposure` (−5…5 EV), `wb.temp` (2000…50000 K), `wb.tint`
(−150…150), and `light.contrast`, `light.highlights`, `light.shadows`,
`light.whites`, `light.blacks`, `color.vibrance`, `color.saturation`,
`effects.texture`, `effects.clarity`, `effects.dehaze` (−100…100). Optional `crop`
is a normalized `[x0, y0, x1, y1]` rectangle. White balance on rendered sources
is the engine's relative adjustment; Kelvin camera interpretation applies to
RAW sources with color matrices.

`photo.edit` requires a source revision and named entries in `photos` containing
new `adjustments` and/or `crop`. Changes preserve every untargeted native photo,
existing history/version entries and original bytes. A native automatic version
may be appended when leaving an edited photo. Both operations accept `bit_depth`
(8 or 16); creation defaults to 16, edits retain the existing depth. Changing
bit depth re-exports the whole series. Every photo receives an sRGB PNG export.
No file paths or arbitrary native commands are accepted by these operations.

Projects retain relative originals, stable photo identities and native
`lightcraft-catalog` schema 13 settings/history. Cold reopening must reproduce
encoded scanlines at the actual output precision, including 16-bit data. The
validator checks originals, bounded settings/history, a fully saved snapshot,
and absence of external resources or folder views before opening imported
libraries. Image dimensions are at most 8192 per side, with 64 million aggregate
source pixels, 256 MiB per source and the supervisor's additional attempt limits.
DNG directory dimensions are checked before native decoding. Unsupported RAW or
preview-only fallback fails the job; no camera-wide fidelity claim is made.

Photo requires the maintained `dobe-photo` engine. It runs on CPU with isolated
configuration paths and without extra paid generation models. Installed package, Linux and Cloud acceptance require their own evidence.
Hosted capability admission remains separate. Each native process receives a
fresh temporary home and configuration directory, so imported project files
cannot act as desktop preferences or camera-profile settings.

## Interface development operations

The source runtime supports `interface.create`, `interface.import`,
`interface.inspect` and `interface.edit` through the existing CLI/MCP job queue. They require the
maintained `dobe-interface` engine and preserve editable native projects,
component links and embedded artwork through cold reopen. See
[INTERFACE.md](INTERFACE.md) for request fields, artifacts and evidence.
Creation and edits refuse failed text shaping. Plain-text, solid-fill and move
revisions preserve unrequested fields, component overrides and untargeted root
pixels. Inspection reports distinguish preserved native state from visual approval;
clipping is not yet qualified. Unsigned dev.42 packages nine maintained apps.
Installed Interface checks cover native/portable reopening, rollback/reinstall,
cancellation, supervisor-crash reconciliation and resumed revision work.
Styled range edits, clean-machine/reboot, Linux and Cloud execution remain unfinished.

## Animate decoding foundation

`studio_runtime.animate_format` implements the first native admission layer.
It reads bounded regular files without rewriting them, rejects duplicate JSON
keys, invalid Unicode and nonfinite or oversized numbers, and checks nesting and
item budgets before constructing the JSON object tree. Native format 3 requires
the shared path table before the document because the engine reads it in order.
The decoder preserves this distinction instead of accepting any dictionary order.

Native path decoding covers the engine's absolute `M`, `L`, `Q`, `C`, `Z` grammar
and legacy tagged geometry, with exact f32 coordinates and shared references.
Repeated `M` coordinates remain separate moves, matching AniCraft rather than
general SVG semantics. Limits are 64 MiB per file, 64 JSON nesting levels,
400,000 JSON items, 8,192 shared paths, 2 MiB per path string, 50,000 commands per
path and 250,000 stored commands in total. Inline paths consume that same total.
Unused table entries can be refused before native saving silently discards them.

This module does not admit complete documents or register Animate operations.
Timeline and symbol dependencies, expanded rendering costs, embedded media,
text shaping, complete state preservation and durable installed execution still
require implementation and qualification. Local decoder evidence includes real
native round trips for 80 path cases and native rejection of 17 malformed paths.
Those checks establish path compatibility, not animation or publication fidelity.

`studio_runtime.animate_graph` adds structural admission for complete scene
lengths, native identities, keyframe spans, layer parents, library folders and
symbol/image/sound references. It refuses structures the native engine would
silently repair, including overlapping keyframes, broken parent links, misplaced
cameras and a colliding next ID. Element IDs may repeat across keyframes; duplicate
IDs within one keyframe are refused. Every symbol dependency is checked, including
unused library items, with a depth limit of 32 and a conservative limit of 32,768
expanded elements. Shared dependencies retain their multiplicity in that budget.
Hidden content is counted too. This bounds element expansion, not render memory
or generated geometry from effects, morphing and nine-slice scaling.

Scene durations include all native layer spans. The movie length is the sum of
its scene lengths; an empty timeline still contributes one frame. Duration uses
the engine's f32 frame rate. The native information reply's `frames` field refers
to the current timeline, while `movie_frames` covers the entire movie. Local
checks preserve a two-scene, 59-frame native project with nested symbols, library
folders, embedded image/audio references, masks, guides and a camera. Cold native
state and selected pixels at both scene boundaries match. Complete property,
media, shaping and render-budget admission remain unfinished; Animate is still
not a registered or packaged runtime application.

`studio_runtime.animate_properties` now checks static transforms, all four paint
kinds, stroke caps/joins/dashes/width profiles, native color effects, stored text
metadata, easing, shape hints, symbol playback/blend fields, all seven filter
kinds and nine-slice guides. It refuses values the native engine would clamp,
merge, wrap or discard, including uniform width profiles, odd dash patterns and
contradictory inactive color fields. Native f32 thresholds govern width-point
merging, dash periods and bitmap matrix inversion. Intentional hard gradient
stops, negative Advanced color multipliers and bounded easing overshoot remain
valid. The input document is not rewritten.

Local property checks cover a native fixture with 14 paint/color/stroke variants
and all seven filter kinds, complete cold native state, selected matching pixels
and seven actual native repair cases. Stored text metadata is not proof that
the selected font or glyph outlines are correct. These checks also do not bound
composed transforms, generated geometry, filtered surface memory or animated
curves. `shaping_verified` and `render_budget_verified` remain false. Stored
behavior admission is described below. Media decoding and the complete typed
Animate runtime remain release work.

`studio_runtime.animate_animation` checks all 20 motion properties, ordered
property keys, easing, canonical cubic motion paths and interior anchor pins.
Native walk sampling and angle boundaries use f32 arithmetic. Paths that native
loading would convert or discard are refused. Property keys outside their span
are preserved and reported instead of truncated. Aggregate limits include 32,768
property keys and 4,096 motion segments; motion geometry also consumes the shared
document command budget.

Armature admission checks bone identities, targets, invertible rest transforms,
joint limits, native breadth-first bone order and bounded unique pose angles.
Dormant poses on other layer kinds remain stored and are reported separately.
Local native evidence includes a complete 21-frame motion document with a measured
interior pin, plus a two-root armature whose measured joint positions match three
sampled frames. Complete canonical files and pixels survive cold reopening.
Nine actual native repair cases and four native walk-boundary cases support the
admission rules. Composed rendering, media, shaping, typed jobs and
installed Animate qualification remain unfinished.

`studio_runtime.animate_behavior` validates the ten stored action kinds, all five
pointer events, frame-script variants, class linkage and nine publish profiles.
It limits each action list to 256 entries, total actions to 32,768, stored source
scripts to 1 MiB each / 4 MiB total and behavior metadata to 4 MiB. Duplicate event
handlers, malformed targets, invalid class names and settings that native loading
would repair are refused. Source text and plugin references are preserved as data;
inspection does not compile scripts, load plugins or run interactive playback.

Finite property values outside their playback range are retained and reported.
Native loading keeps such values when the list is otherwise valid; playback clamps
them. Target syntax validation does not prove that the referenced instance, scene
or frame label exists during playback. `action_targets_resolved` and
`interactive_playback_verified` therefore remain false.

`animate_unicode` carries the native compiler's Unicode character properties.
Regenerate it with `craft/engines/generate_animate_unicode.py` using the same rustc
as the maintained engine build. Python's character and whitespace predicates use
different Unicode rules and cannot substitute for the native class-name rules.

Publish settings remain inert preferences. Even absolute/traversing output strings
and frame numbers beyond the movie can survive native loading. They are retained
for editable-file fidelity, never used as output authority. A closed runtime export
must independently select its attempt-owned path, formats, frames and allocation
budget. All nine formats being enabled in a stored profile authorizes no export.
`execution_authorized`, `output_templates_trusted` and `export_budget_verified`
remain false. This layer does not register a production Animate operation.

Local evidence covers complete cold-state preservation of actions, events, all
three source languages, an unavailable plugin reference and nine publish profiles.
Five static frames retain the independently measured object center and pixel area.
Eleven actual native repair cases support refusals. Interactive playback and
installed runtime jobs still need qualification; media and scoped native
diagnostics are described below.


`studio_runtime.animate_media` validates canonical embedded base64 and bounds
encoded bytes, decoded pixels and samples across the document. PNG checks include
chunk CRCs, complete contiguous IDAT data, exact bounded scanline inflation
(including Adam7), dimensions and actual single-image decoding. Inflation is
streamed in 64 KiB output chunks. Each bitmap allows at most 32 million pixels;
the document allows 64 million. Media allows 32 MiB per payload / 48 MiB total.

Sounds are decoded by the maintained native `file.inspect_sound` command before
an imported project is opened. WAV, Ogg Vorbis and MPEG audio must decode completely
without tolerant tail recovery. Stored format, rate, channels and frame count must
match actual decoded bytes. The document allows 67,108,864 samples across channels;
each stored sound's count is also the allocation limit passed into its decoder.
`NativeSoundInspector` owns one short-lived process per sound, fixed commands,
explicit roots, a cleared environment, a 30-second per-process deadline and a
120-second overall deadline. Cancellation kills and reaps the child process group
and removes only its newly created scratch directory. Its executable must come
from the runtime's verified maintained pack. This is not an OS sandbox claim.

Sound placements cover all four sync modes, repeat/loop fields, seven effects and
custom per-channel envelopes. Stored repeat/envelope values that playback clamps,
sorts or truncates remain unchanged and are reported. Placement and envelope
counts are bounded separately. Expanded voice work and general mixing fidelity
remain unverified; a valid stored library does not bound repeated nested playback.

`studio_runtime.animate_document` now composes envelope, graph, static properties,
animation, behavior and complete media admission over one bounded byte snapshot.
The returned internal profile retains those exact bytes and their SHA-256 for an
attempt-owned native handoff. It never reopens the original file after validation.
Its JSON-safe summary preserves media identities, requested fonts, duration,
stored playback adjustments and explicit unverified gates. Native preservation,
shaping, evaluation, rendering and publication are not implied by stored admission.

All stored sound placements, metadata, base64 and aggregate encoded-byte limits
are checked before the first native sound process. Native decoder reports require
the exact maintained schema, integer counts, complete decoding, an unchanged
document, the expected channel policy and finite, consistent peak/RMS values.
The private `animate_process` transport limits stdout and stderr while reading,
rather than collecting unbounded output and checking afterward. It checks timeout
and cancellation even after the leader exits, terminates the owned process group,
closes pipes without waiting for descendants to close them, and reaps the leader.
No additional public tools or production Animate operations are registered yet.

The maintained native `file.inspect_preservation` command compares the complete
serialized document state before and after load sanitization, then through a cold
native save/load cycle. Each compact serialization is limited to 64 MiB while
writing. A repaired name, timeline, ID, publish setting, library folder or other
serialized state causes refusal. The command writes no file and does not change
the session. `read_with_engine` first performs all stored-document admission,
then sends the exact admitted bytes through this probe in its own directory.
Media and state inspection share the same overall deadline.

This comparison begins **after native deserialization**. Native defaults, f32
conversion, custom color/stroke readers and ignored JSON fields precede it. The
report therefore explicitly sets `raw_json_preservation_verified: false`; it
does not replace the Python schema checks or claim original JSON byte preservation.

`read_with_engine` now follows that probe with an owned scratch cold save and
complete semantic reconciliation. `animate_semantics` maps every admitted
document field using the pinned native serialization schema. It fills documented
defaults, compares geometric/visual values at f32 precision and preserves f64
action values and sound-envelope times. IDs remain exact integers. Shared and
inline paths compare by their decoded commands; library placement order follows
the native map. Legacy alpha+tint maps to its native Advanced color effect while
neutral authored Alpha, Tint, Brightness and Advanced styles remain distinct.
Only native self-target omission is normalized; other action text remains verbatim.

The cold save must pass complete admission again. Sound decoding evidence is
reused only for identical bytes from this same admission; changed sound payloads
are refused. All fields, including inactive guides, hidden/unused content,
scripts, plugin references, media and publish preferences, participate in the
comparison. Differences report a semantic field path without exposing contents.
The original file is never rewritten. Scratch serialization, parsing and
comparison share the admission deadline, and their directory is removed on
success, refusal or cancellation. Stored output preferences never supply paths.

The Dobe session constructor preserves empty stored scenes and their next ID.
Opening a headless document must not insert a drawing layer. Creating a layer
remains an explicit, undoable command; desktop AniCraft retains its existing
initial drawing-layer behavior.

`native_semantics` records source, saved-file and semantic hashes plus explicit
byte/generator preservation observations. The generator is envelope provenance,
separate from document meaning. Defaults, f32 decimal spelling, signed numeric
zero and path-table representation may differ without changing stored meaning.
The summary sets `native_preservation_verified` only after native load/save
preservation and semantic reconciliation both pass. This does not authorize
publication or establish shaping, rendered pixels or interactive playback fidelity.

Frame and soundtrack interpretation is now available through the private runtime
adapter. After stored admission and native state checks, `read_with_engine` can
inspect up to 600 distinct zero-based movie frames and one inclusive soundtrack
range at 8,000–192,000 Hz. The adapter generates one fixed read-only command batch
and opens the owned snapshot once. Callers cannot supply native commands or paths.
The batch shares the admission deadline and has a 4 MiB stdout limit.

Reports require exact schemas, integer work counters within maintained native
limits, unchanged-document flags and agreement with the request and admitted
media. Display items, clip/group totals, decoded pixels/samples, expanded voices,
mix work and block counts are checked. Sample boundaries follow native f64
arithmetic over stored f32 frame rates and round halfway values away from zero.
Out-of-movie ranges are refused before the native command can silently clamp them.
Even a short soundtrack range still checks whole-movie sound layout.

Diagnostics retain the source SHA-256 and explicit scope. Static frame evaluation
does not prove rendered pixels, aggregate export work or interactive playback.
Soundtrack reports qualify expansion and mix work, not audible fidelity. These
deterministic counts are not CPU-time measurements or billing prices.
Typed durable operations remain unfinished; no public Animate operation is
registered by this adapter.

Local evidence preserves complete native media bytes through cold reopening,
checks a bitmap against expected pixels and a six-frame repeated mono sound against
every exported stereo sample, and confirms child cancellation/cleanup. Closed
typed Animate operations, composed rendering fidelity and installed lifecycle
remain unfinished.

The maintained native engine now supplies the missing audio expansion check via
`file.inspect_soundtrack`, and enforces it inside Dobe audio export. The check uses
the native layout itself, so nested graphic/movie-clip timing, Start/Stop order,
held frames, layer gains and range selection do not require a second timeline
implementation in Python. Stored-media admission remains necessary before opening
a document. Its `expanded_voice_budget_verified: false` result remains accurate:
stored-media admission alone does not invoke the native layout check. The optional
soundtrack diagnostic above does, after stored admission and native preservation.

Native text qualification now has `text.inspect_layout` and `text.inspect_stored`
as private engine primitives. The first exposes the actual selected bundled face,
shaped UTF-8 clusters, glyph positions and drawing results. The second checks
stored native glyph geometry and box metrics against a fresh layout of the saved
text and style. Family/style substitution, missing glyphs, stale outlines and
clamped style values are separate observations.

The private `read_with_engine(..., inspect_text=True)` path now interprets those
observations for every stored text instance. This includes hidden layers, later
keyframes, additional scenes and unused library symbols. It generates only
`text.inspect_stored` commands against the admitted snapshot, with at most 32
instances and 8,192 source characters per batch, 16 MiB stdout and the shared
admission deadline. One instance cannot exceed 8,192 characters or 32,768 UTF-8
bytes. A failed later batch returns no partial qualified result.

Reports bind to the selected element, layer and keyframe. Face identity is checked
against 20 embedded fonts from the pinned font revision, including file size,
PostScript name, weight, italic flag, face index and glyph count. The reproducible
catalog records each font's SHA-256; it consults no host fonts. UTF-8 paragraph
ranges and cluster boundaries, shaped/drawn glyph identities and advances,
outline totals, missing characters and stored metrics/style flags are checked.
Font substitutions, missing glyphs, drawing failures and stale outlines or box
metrics remain explicit issues. Inspection never repairs the source.

`native_text` carries the source hash, per-instance evidence and scoped coverage/
layout results. Native layout reproduction does not prove full mixed-direction
paragraph itemization or publication fidelity. Those flags remain false. Static
`animate_properties` admission and the overall document summary still report
shaping unverified unless the caller examines the separate native text result.
No public operation or packaged Animate engine is enabled by this integration.

## Animate native import and inspection

The source runtime now registers `animate.create`, `animate.import`, `animate.inspect`,
`animate.edit` and `animate.export`. This
supersedes the earlier foundation-only registration statements above. The
installed dev.42 distribution still contains nine applications; Animate installed
packaging remains release work. Creation, precise revisions and raster exports are described below.

Import requires an asset already imported into the same project:

```json
{"asset":"IMPORTED_ASSET_ID","frames":[0,12],"scale":1,"inspect_text":true}
```

Inspection requires an Animate source revision and accepts the same options
without `asset`. `frames` selects at most 64 distinct zero-based **movie** frames
across all scenes. Omission selects the first frame of every scene; an empty list
requests metadata without previews. `scale` is between 0.001 and 8. Preview
dimensions use the native f32 scale and rounding. Limits are 16,777,216 pixels
per preview, 64,000,000 pixels across previews and 256 MiB of encoded previews.
An optional `soundtrack` object accepts inclusive `from`/`to` movie frames and
`rate` between 8,000 and 192,000 Hz for bounded sound-work inspection. It does
not export audio or establish audible fidelity.

Preparation retains the exact imported bytes as `native/source.anicraft`, an
editable native cold save as `native/document.anicraft`, occurrence selectors in
`native/objects.json`, PNG previews and `exports/inspection.json`. Selectors
include the scene index or symbol ID, layer ID, keyframe start and element ID;
repeated names or element IDs in later keyframes do not collapse into one target.
Hidden content and unused symbols remain in the editable document and mapping.
Subsequent inspections preserve the original imported source artifact.

Every stored field is reconciled with the native save. Selected previews are
decoded and compared byte-for-byte and pixel-for-pixel across a fresh native
process. Saves after rendering also check that rendering did not change stored
meaning. Actual text diagnostics run by default; missing glyphs, substitutions
and stale outlines remain explicit import issues. These checks do not approve
visual design, mixed-direction text layout, interaction or browser/player fidelity.
Stored scripts and publish profiles remain inert.

All outputs are prepared in private scratch space before a complete directory
appears. The existing worker then publishes the immutable revision with its lease
and project-head checks. A failure cannot change the previous revision. Native
children share the registered attempt process group so supervisor cancellation
also stops them if Python dies before cleanup. Standalone probes retain their
own process groups. No additional public MCP tool or generative-model call is
introduced. Cloud, installed-service and clean-machine qualification remain open.

## Animate scene creation

`animate.create` creates a new project revision with native rectangle/ellipse
drawing, native text shaping, multiple scenes and layers, keyed poses, and classic
or shape tween spans. The request contains `stage` and `scenes`, plus the preview
options documented above. For example, this moves an editable rectangle:

```json
{
  "stage": {"width":128,"height":64,"fps":24,"background":"#ffffff"},
  "scenes": [{"name":"Opening","layers":[{"name":"Artwork","keyframes":[
    {"start":0,"duration":12,"tween":"classic","easing":"Linear","objects":[
      {"name":"Mark","type":"rectangle","x":4,"y":20,"width":10,"height":10,"fill":"#ff0000"}
    ]},
    {"start":12,"duration":1,"objects":[
      {"name":"Mark","type":"rectangle","x":100,"y":20,"width":10,"height":10,"fill":"#ff0000"}
    ]}
  ]}]}],
  "frames":[0,6,12]
}
```

Object names use 1–64 ASCII letters, digits, underscores or hyphens, starting
with a letter, and are unique within each keyframe. Reusing a name in later keys of
the same layer preserves native element identity for interpolation. Names in
different layers are independent. Continuity cannot change an object between
text and shape. A tween must end at the following keyframe; `shape` selects
native shape interpolation. Easing accepts the admitted native easing names or
`{"CubicBezier":[x1,y1,x2,y2]}`. Frame labels are optional. Layers may declare
`visible` and `locked`; both are applied after native authoring, including for
empty layers. Layer order follows the native timeline order.

Rectangles and ellipses require `x`, `y`, `width`, `height` and `fill`.
Colors use `#rrggbb`; a null fill requires a stroke. `stroke` and `stroke_width`
are optional, and rectangles accept `radius` up to half the shorter side.
Shape dimensions range from 0.5 to 8,192 pixels; positions range from -8,192 to
8,192. Native f32 geometry, transforms, paint and stroke must match the request.

Text requires `name`, `type:"text"`, `x`, `y`, `text`, `font`, `size` and `color`.
Optional `bold`, `italic`, `align`, `letter_spacing`, `line_spacing` and `width`
control layout; null or omitted width disables wrapping. Use an exact bundled
family name, such as `Inter` or `Liberation Serif`. Font substitution, unavailable
styles, missing glyphs or stale layout fail creation. Text qualification cannot
be disabled for creation. The native engine generates the editable text outlines;
only outline and box metrics are derived fields, and actual native shaping checks
each of them before the requested state can pass.

Creation admits at most 64 scenes, 128 layers, 512 keyframes and 512 object
occurrences in total. Each text object allows 8,192 characters / 32,768 UTF-8
bytes, with 1 MiB of text across the request. Requests remain subject to complete
document geometry and media limits. These are explicit production bounds, not a
claim that every native feature is available through this creation schema.

The revision includes `recipes/create.json` alongside editable native sources,
occurrence selectors, previews and inspection evidence. Inspection and portable
directory import retain that recipe. Stored native values, geometry, identity and
text layout are checked before the existing cold-save/pixel checks and durable
publication. Successful checks do not constitute visual design approval. Additional
revision types, other native authoring features, remaining export routes and
installed Animate qualification remain in the complete software plan.

## Animate precise revisions

`animate.edit` requires a source revision and 1–128 `edits`. Each edit uses an
occurrence selector from `native/objects.json`: either `scene` (zero-based index)
or `symbol` (library ID), plus `layer`, `frame` (the exact keyframe start) and
`element`. Names and IDs reused in later keyframes do not broaden the selection.
Selecting an interior tween frame is refused; the runtime does not auto-key it.

```json
{
  "edits": [
    {"selector":{"scene":0,"layer":1,"frame":0,"element":2},
     "action":"translate","dx":12,"dy":0},
    {"selector":{"scene":0,"layer":1,"frame":0,"element":2},
     "action":"fill","color":"#334488"}
  ],
  "frames":[0,6,12]
}
```

`translate` offsets the selected occurrence's stored transform. If that occurrence
owns a motion tween, its X/Y position keys and motion path are offset too; timing,
easing, pins and other tracks stay unchanged. Other keyframes keep their stored
values. Deltas must be finite and within -8,192 to 8,192; the complete result must
also satisfy native coordinate limits. Armature-layer translation requires a
dedicated pose operation, which remains unfinished, and is explicitly refused.
Editing an ordinary shape inside a rig's library symbol remains supported.

`fill` replaces a shape's fill with a `#rrggbb` solid color or null. Text replacement
uses `action:"replace_text"`, the exact old content in `expected` and nonblank new
content in `text`. It preserves the existing font, style, color, wrapping width and
transform. The native engine generates new outlines and box metrics in an owned
text prototype. Both the prototype and the final revised occurrence must pass
actual glyph/layout inspection. New text is limited to 8,192 characters / 32,768
UTF-8 bytes per edit and 1 MiB across the batch. Text inspection cannot be disabled
for replacement. Sequential edits to the same occurrence use the preceding edit's
state and expected text.

Hidden, locked and unused library content is addressed directly without changing
layer flags. Geometry and fill edits update the documented native fields; text
layout comes from the maintained engine. Shared paths are reindexed without
changing other occurrences. A complete semantic comparison allows only the
requested fields and explicitly derived text layout or motion position changes.
The revised native cold save must match that exact checked state.

Selected previews are compared before and after revision. Scenes with no edited
occurrence or transitive dependency on an edited library symbol must keep their
selected pixels unchanged. Reports list the checked untargeted frames and the
frames whose pixels actually changed; these are static-frame observations, not
interactive playback approval. An edit to hidden or unused content may correctly
change no selected preview.

`recipes/last-edit.json` records the request. The original native source and any
creation recipe survive inspection and portable directory re-editing. If an
imported bundle lacks a source-provenance artifact, its input document is retained
at the first edit. A failed precondition, glyph check, state comparison or preview
check leaves the published project head unchanged. This extends the existing
fifteen public MCP tools; it does not add a native command endpoint or execute
stored scripts/publish templates.

## Animate raster exports

`animate.export` requires a source revision and an `output` request. It produces
PNG sequences, animated GIFs or PNG sprite sheets with a JSON frame map. The
maintained native engine renders every frame; no paid model is called. The
usual preview and inspection options remain available alongside `output`.

```json
{
  "output": {
    "format": "sprite_sheet",
    "from": 0,
    "to": 23,
    "scale": 1,
    "columns": 6,
    "padding": 2,
    "background": true
  },
  "frames": [0, 12, 23]
}
```

The inclusive range uses zero-based movie frames across all scenes. Omitted
endpoints select the whole movie. Requests outside the movie are refused rather
than clamped. Every export allows 1–600 frames, scale 0.001–8, at most 16,777,216
pixels per frame and 552,960,000 pixels across the selected range. Native f32
scale and dimension rounding apply. Encoded raster data is limited to 512 MiB;
the sprite map has a separate 4 MiB limit. Native evaluation, geometry and render
work budgets still apply to the actual export.

`png_sequence` accepts the range and scale. `gif` also accepts boolean `loop`
(default true). `sprite_sheet` also accepts `columns` (1 through the selected
frame count), `padding` (0–256) and boolean `background` (default false). The
default column count is the ceiling of the square root of the frame count.
The complete sprite atlas is limited to 16,777,216 pixels. Sprite backgrounds
are transparent unless requested; padding and unused cells remain transparent.

GIF uses a color palette and centisecond timing with a 20 ms minimum per frame.
This can change colors and slow high-frame-rate movies. Sprite-map durations use
the same timing rule; `meta.frameRate` retains the native rate. PNG sequences
retain exact native frame pixels and report the native rate separately.

Every PNG and GIF frame is fully decoded. GIF structure, frame count, loop and
durations are checked. Sprite rectangles, names, dimensions, padding, timing and
metadata must match the exact request. Exports run again after a native cold save;
all output bytes, decoded pixels and timing must agree. Complete native semantic
comparisons before and after both exports protect the editable source.

Files appear under `exports/render/` as `frame_00001.png` (one-based global movie
number), `movie.gif`, or `atlas.png` plus `atlas.json`. `exports/inspection.json`
records the request, dimensions, rate, hashes and format losses.
`recipes/last-export.json` retains the request. Export artifacts belong to that
revision; later edit/inspection jobs do not claim to refresh previous exports.
The original source and earlier immutable revisions remain available. Failures
publish no partial export. Portable directory bundles can be reopened and exported
again through the same fifteen public MCP tools.

MP4 delivery is described below, alongside soundtrack and document exports.
Remaining declared authoring features and installed Animate qualification stay open.
Raster checks do not establish browser/player fidelity or visual design approval.

## Animate soundtrack exports

The same `animate.export` operation accepts native stereo WAV output:

```json
{"output":{"format":"wav","from":0,"to":119,"rate":48000,"bits":24},"frames":[]}
```

`from` and `to` are inclusive zero-based movie frames; omitted endpoints select
the complete movie. `rate` defaults to 44,100 Hz and accepts 8,000–192,000 Hz.
`bits` accepts 16 (default), 24 or 32. The first two select signed integer PCM;
32 selects finite float PCM. Integer encoding rounds and clips samples. Two
channels are always written, including duplicated mono and silence where needed.
There is no raster scale or 600-frame restriction for audio. The output limit is
33,554,432 stereo sample frames, with native soundtrack layout and mix-work
limits checked across the entire source even when exporting a short range.

The maintained engine performs placement, looping, envelopes, resampling and
mixing. Event sounds starting before the selected range are omitted; stream
sounds join mid-way. Sample boundaries use native f64 arithmetic over the stored
f32 movie rate, rounding half samples away from zero. Both range endpoints are
rounded before their difference determines the exact output length.

`exports/render/soundtrack.wav` includes a checked complete RIFF header and exact
PCM byte count, rate, channel count, encoding and sample count. Every float sample
must be finite. The inspection report includes the native layout/work report and
WAV/PCM hashes. A second export from a fresh native process must match all bytes,
sample data and layout. Semantic comparison protects every stored native field.
These checks establish deterministic native output; they do not constitute
listening approval or interactive playback qualification.

The output follows the same durable publication, original-source preservation,
recipe retention and portable re-export contract as raster exports. No additional
MCP tool, external audio service or paid model is involved. Cloud workers and the
remaining full-suite release gates stay open. Installed development qualification
is described with MP4 delivery below.

## Animate SVG, Lottie and HTML exports

`animate.export` also accepts these document requests:

```json
{"output":{"format":"svg","frame":48}}
{"output":{"format":"lottie","from":0,"to":119,"background":false}}
{"output":{"format":"html","title":"Campaign preview","sound":true,"fit":true}}
```

SVG exports one static global movie frame, defaulting to frame zero. The runtime
maps that global frame to the correct native scene and local frame before export.
`exports/render/frame.svg` retains the native vector representation. Complete XML,
stage dimensions and native evaluation/serialization work are checked. Entity
declarations, scripts and external resources are refused. SVG style/filter
attributes use four-decimal formatting; paths retain native f32 coordinates.

Lottie exports an inclusive movie range, defaulting to the complete movie, with
1–600 frames. `background` defaults to false. `exports/render/animation.json`
contains frame-sampled native artwork. Stage dimensions, frame range, rate,
layer count, Bezier structures and held-key timing are checked. The output follows
the native Lottie 5.7.0 representation; serialization does not prove compatibility
or visual fidelity in every Lottie player.

HTML exports the complete movie and used library timelines, with at most 6,000
total baked frames. `title` defaults to "Dobe animation" and accepts 1–256
characters without control characters. `sound` and `fit` default to true.
`exports/render/animation.html` is self-contained: it embeds the maintained
JavaScript player, movie data and source media. The runtime checks the exact
maintained player hash, escaped title, canvas, scene order, timeline lengths,
frame runs and source-image/sound hashes. It never opens the page or executes its
player. Supported stored actions are compiled into movie data for the recipient's
browser; unsupported behavior remains in the editable native source and reported
native feature-loss notes.

Document outputs are limited to 64 MiB. Parsed Lottie/HTML data uses at most one
million JSON items and depth 64. SVG parsing allows at most 400,000 elements and
depth 64. Native construction budgets apply independently. Lottie and HTML
numeric formatting rounds fps to three decimals. Included
stage backgrounds use opaque RGB in those formats.

Each export repeats after a native cold save. Output bytes, metadata, feature-loss
notes and construction counters must agree, and complete native semantics must
remain unchanged. Reports retain known native approximations and omissions.
`feature_loss_notes_exhaustive` and `browser_player_fidelity_verified` remain false:
exhaustive loss accounting and browser/player rendering are still release work.
The editable native source always accompanies the output, preserving features
that a delivery format cannot represent. Durable publication, portable re-export
and the fifteen-tool MCP contract are unchanged.

## Animate MP4 exports

The same durable `animate.export` operation produces H.264/AAC MP4 through the
maintained Dobe Animate and Dobe Video engines:

```json
{"output":{"format":"mp4","from":0,"to":119,"scale":1,"audio":true,"matte":"#000000"},"frames":[]}
```

The range is inclusive and zero-based; omitted endpoints select the complete
movie. Scale defaults to 1 and uses the raster export bounds and native rounding.
`audio` defaults to true and includes a stereo 48 kHz soundtrack, including silence
when the source has no sounds. Set it to false to omit the audio track. `matte`
defaults to black and accepts a six-digit RGB hex color. Unknown fields, output
paths, commands and codec selections are refused. The maintained `dobe-video`
executable is required; an older engine that lacks the owned decoding and precise
sample endpoint support fails rather than bypassing those checks.

One deadline of at most 120 seconds covers qualified PNG/WAV production, two
independent native encodes, complete decoding and delivery inspection. Both
encoded files and their complete inspection reports must agree. The original
Animate document and its owned snapshot must remain byte-identical. Delivery
copies only the checked MP4 and reinspects its complete file hash and container
before the existing durable revision fence can publish it.

The result is `exports/render/movie.mp4`, with the request preserved in
`recipes/last-export.json` and complete timing/decoding evidence in
`exports/inspection.json`. The portable bundle retains the editable Animate
document and original source. Temporary codec projects with scratch paths are
not delivered. H.264 and AAC are lossy; alpha uses the requested matte and odd
dimensions receive right/bottom padding without additional resizing. Partial
soundtrack ranges retain the WAV event/stream behavior described above.

Local qualification covers direct output, disconnected MCP clients, idempotent
submission, immutable source revisions, portable re-export and cancellation while
the native encoder is alive. Failed or cancelled jobs publish no revision and
leave the project head unchanged. There are eight public export formats and the
same fifteen MCP tools. Development package dev.43 includes Animate as the tenth
application and the updated Video engine. Local installed checks cover all eight
formats, creation/revision, portable MP4, rollback/reinstall, cancellation, orphan
cleanup and recovery without publishing interrupted work. These use only bundled
dependencies under network denial. A supervisor-crash probe suspends only the
native encoder; suspending its entire group would also suspend the parent-death
watcher. Process-group absence requires an ESRCH result, never permission denial.
Browser/player fidelity, visual approval, remaining authoring, clean-machine and
reboot qualification, and the full seventeen-application Local/Cloud release
remain unfinished.

### Internal video handoff and verification

`animate_video_handoff.py` assembles already-qualified native PNG and WAV outputs
for the maintained Dobe Video engine. The public MP4 adapter uses this private
component. It verifies the input bytes, decoded pixels, PCM format and samples,
source identity and selected range before generating a fresh native codec project.
The exact rational representation of the stored f32 fps replaces the Video CLI's
default image-sequence rate. No caller project or stored script is executed.

Frames retain their dimensions and pixel positions. The handoff composites alpha
over an explicit `#rrggbb` matte in encoded sRGB, then adds only right/bottom
padding to reach even dimensions of at least 2×2. Opaque input pixels remain
unchanged before lossy encoding. Requests retain the existing 600-frame,
16,777,216-pixel-per-frame and 552,960,000-aggregate-pixel budgets after padding;
the native Video limit is 32,768 pixels per side. Prepared PNG bytes and the
completed movie are checked against separate 512 MiB limits.

Audio stays stereo at 48 kHz. The handoff preserves the native WAV's exact sample
count, including the one-sample rounding difference that can occur in a partial
range. It requires the maintained Video build with `audioSampleFrames`; older
builds refuse that setting. Its generated audio clip has the exact sample duration
and its export range retains the exact picture duration. Cold native saves must
preserve the full intermediate, and source artifacts must remain unchanged.

Local qualification covers actual odd/tiny stages, alpha/matte pixels, fractional
fps, partial ranges, exact decoded sample counts and repeatable codec bytes. PCM
oracles check every source sample, including the final sample.

`animate_video_container.py` now inspects the complete owned MP4 before the
handoff returns. It checks progressive, self-contained H.264/AAC tracks, exact
video presentation timestamps, frame count, dimensions, square pixels and
limited-range Rec.709 signaling. Audio must be AAC-LC stereo at 48 kHz with the
expected priming and sample endpoint. Decode/composition runs, edit lists, sync
samples, descriptions and chunk mappings must agree. Every coded byte belongs
to exactly one sample; missing, overlapping and unclaimed media bytes fail.
Each H.264 NAL has checked framing, type and sync metadata. Container inspection
alone does not decode H.264 slices or AAC payloads.

Inspection reads one regular file with no final symlink, hashes every byte and
checks that the file remains unchanged. Limits include 512 MiB per movie,
4 MiB of movie metadata, 4,096 boxes and 40,000 aggregate samples. Cancellation
and deadlines are checked while reading. Both 32-bit and 64-bit chunk offsets,
extended media headers and version-1 duration/edit fields are supported. The
runtime retains the full container report without loading the entire movie into
one Python byte string. Local evidence includes the actual 600-frame limit and
corrupt timing, tables, references, NAL framing and file-boundary refusals.

The handoff then runs the maintained Video engine's private
`inspect-owned-video` command through `animate_video_decode.py`. A bounded sample
manifest selects every coded span. The native pass independently checks span
ownership, counts and timestamps, then decodes raw H.264 and AAC samples using
the software codecs. It does not use playback sources, which normalize frame
rates and can conceal failed audio packets as silence. SPS dimensions are checked
before surface allocation, parameter changes are refused, and the H.264 decoder
uses two workers. Every output picture must have the expected dimensions, color,
timestamp and key flag. Flush errors, missing macroblocks, inferred reference
frames, draft pictures, repeated pictures and incomplete output fail.

Every AAC packet is decoded, including priming and tail padding. Stereo shape,
48 kHz rate, finite samples and exact presentation sample counts are checked.
The report includes diagnostic FNV-1a checksums of visible YUV planes and presented
stereo samples; these are not cryptographic file identities. The runtime reinspects
and SHA-256 hashes the complete MP4 after decoding, requires an unchanged sample
manifest and reconciles all returned counts against its container inspection.
Local qualification compares every decoded YUV byte for integer/fractional rates,
odd/tiny stages and 600-frame output with an independent decoder. Corrupted first,
middle and final AAC packets and damaged first/final pictures fail even when their
container tables remain valid. This evidence does not claim general codec
conformance for arbitrary external media.

Every native Video invocation now enters through an isolated Python exec trampoline
that tightens inherited kernel limits before the engine starts. Regular-file writes
are capped at 512 MiB during encoding, rather than only checked after completion.
The per-process CPU limit is at most the remaining wall deadline, rounded up to
seconds, and never widens an inherited limit. Core dumps are disabled. The parent
process's limits are unchanged; no pre-exec callback runs inside the parent.
Existing worker supervision still enforces aggregate resident memory, process
count, attempt storage and wall time.

The trampoline preserves the native PID and process group across exec. Real native
encoding is locally qualified for kernel file-limit termination and cancellation
while the process is alive. The standalone process group is removed on cancellation.
Within a registered worker group, killing the attempt leader still leaves the
native child in the supervisor's group, so supervisor cleanup removes the orphan.
These are owned-job resource controls, not a hostile-process sandbox.

Returned `container_timing_verified` and `complete_decode_verified` are now true
after both passes. The private report keeps `publication_authorized` false: only
the durable worker may publish the completed artifact through its revision fence.
These checks do not authorize remote publication or establish visual approval.


## Material source-backed projects

The source runtime now supports `material.create`, `material.import`,
`material.inspect`, `material.edit`, `material.cook`, `material.export` and
`material.preview` and `material.bundle` through the same durable CLI and product
MCP. They author structured SBS graphs, import portable SBS/MCraft assets, inspect
complete native state and apply typed scalar or structural revisions while
preserving the initial source bytes. Binary resources use project-scoped asset
IDs and remain owned inside the editable archive. `material.create` also accepts
versioned `ceramic_tiles` and `ribbed_metal` recipes with exposed controls and six
coherent PBR maps. The capability response describes both recipes; their sources
remain editable after creation. See [MATERIAL.md](MATERIAL.md)
for request shapes, source selectors, lineage and qualification evidence.

These operations require the maintained pinned `dobe-material` binary on PATH.
Full-size graph cooking now records finite output diagnostics under shared native
raster budgets and the existing worker limits. Map export uses that same bounded
cook, explicit color/depth/alpha policies and complete output decoding. CPU preview
uses the same qualified cook for selected 2D maps or nine 3D meshes, with explicit
lighting, channel selection, geometry and sample budgets. Version-2 portable bundles preserve exact editable sources and can be imported
back into Material or applied through `texture.material`. Handoff recooks the
source to verify all maps before adding or precisely replacing a linked Texture
fill. Immutable SBS dependencies inside the same archive now work across these
operations. Every package is independently compared before and after a bounded
cook; exact dependency sources stay editable and portable. No external path or
library lookup is enabled. Unsigned dev.45 includes Material and qualifies these
installed operations, Texture handoff and local cancellation/crash recovery.
It contains twelve of seventeen apps; dev.44 remains unchanged. Clean-machine,
reboot and complete release qualification remain open.
Capability output states these limits explicitly.
The complete product goal continues to require all seventeen applications and
the remaining Local/Cloud and release requirements.

## Write integration in progress

The source runtime now exposes `write.create`, `write.import`, `write.inspect`,
`write.edit`, `write.bundle` and `write.export` through the existing durable CLI/product MCP.
These operations preserve exact originals, replay typed revisions and compare
complete native models against the engine bound to the running bundle receipt.
Portable projects remain editable after transfer. Local distribution-layout
checks cover actual native cancellation, supervisor death and explicit retry.
Strict PNG/PDF delivery compares actual fonts and pictures, refuses unapproved
font substitutions and independently decodes every output. A versioned production
brief recipe reuses layout and typography while preserving supplied content and
editable selectors. Unsigned dev.47 qualifies these six operations through the
installed CLI/MCP on the development Mac, including rollback and live native
recovery. Dev.45 and the earlier dev.46 prototype remain preserved. Direct DOCX
conversion, complete fidelity and external release qualification remain open.
The candidate contains thirteen of the required seventeen applications.
See [WRITE.md](WRITE.md) for request shapes, ownership, evidence and remaining work.


## Slides integration in progress

The maintained private Slides worker builds from pinned source. Its source layer
owns exact native ZIP/JSON bytes and independently reconstructs media and chart
payloads, including nested groups and auxiliary masters. Portable projects preserve
exact originals and replay typed text, formatting, geometry and slide revisions.
The receipt-bound private observer compares complete predicted models against native
encoding, independent container reconstruction and cold reopening. Live native
cancellation removes disposable files and reaps the process. The current source registers seven durable Slides operations: create, import,
inspect, edit, bundle, export and migrate, through the same CLI/MCP. Earlier
private checkpoints covered only five operations. Broader
model/resource admission remains pending. A deterministic production-proposal
recipe compiles caller-owned content into editable covers, sections, speaker notes
and paginated delivery specifications. Native placed-text diagnostics expose actual
overflow, automatic shrink, missing glyphs and source-pinned font bytes. Complete
render coverage, model admission and delivery qualification remain required.
See [SLIDES.md](SLIDES.md) for ownership,
repair detection, native MIME dispatch correction and remaining requirements.
The installed dev.47 candidate remains thirteen of seventeen application profiles.
