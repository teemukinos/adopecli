# Portable native replay: current implementation and remaining catalog

The complete seventeen-family Local/Cloud portable-project requirement remains
open. Explicit replay profiles cover Write, Slides, CAD, Sheets, PDF, Material,
Texture, Layout, Interface, Animate, Audio, Photo, Inspect, Video and Motion alongside the existing image/vector ZIP
importer. This does not enable those fifteen families
in a deployed Cloud service or claim Linux qualification.

`bundle.execute(..., replay_families=(...))` is an internal, operator-selected
profile. Its default remains image/vector, matching the currently qualified
hosted boundary. Public job parameters cannot choose additional families or an
executable. `bundle_replay.py` resolves only the fifteen maintained adapters and
their receipt-bound engines. Unknown, duplicate or malformed profile selections
are refused before extraction. Imported engine names and versions must match
that explicit profile.

## What replay proves

The ZIP importer first bounds and verifies the complete declared file inventory,
paths, roles, sizes and hashes. Each native profile then copies those files
into a disposable inspection directory. Each history-based adapter checks the native
project container, exact source pin, immutable original, typed revision chain
and current model, and opens the maintained engine. Write and Slides additionally
observe every intermediate native model, including states later edited away.
CAD and Sheets already replay their native operation histories during inspection.

The returned native inventory must equal the bundle's complete declared native
inventory. Every resulting native file must remain byte-identical. A native
member that disagrees with its portable project is refused even when the outer
ZIP hashes are internally consistent. Inspection cannot silently normalize or
migrate the imported editable project. All original files are rehashed before a
successful result is returned. Output publication remains the supervisor's job.

Prior exports and previews are preserved byte-for-byte. The four history-based
profiles do not regenerate every PDF, HTML, PNG or OBJ delivery. Their results set
`export_semantics_replayed` to false; they do not inherit a caller's visual or
export-validation claims. Existing image/vector import retains its independent
pixel/SVG replay checks.

PDF uses a separate static-document profile. It resolves the maintained PDF
engine from the package receipt, source lock and binary hash, rather than PATH or
an imported recipe. Inspection disables document scripts, admits static PDF
structure, observes all current editable records, and renders every page. A
second native process must reproduce the structure, editable records and pixels.
The imported PDF, object mapping and structural snapshot must remain byte-exact.
The entire PDF export/preview inventory must match the regenerated inventory;
the delivered PDF and inspection report must be byte-equal, and each page preview
must have equal dimensions and decoded pixels. An outer checksum alone cannot
validate a stale report or altered page preview.

The PDF profile reports `export_semantics_replayed: true`. It does not
claim a typed revision history or an independently retained original source:
`native_history_replayed` and `initial_source_preserved` are false. It instead
reports `imported_native_bytes_preserved: true`. All profiles keep
`visual_approval: false`. These comparisons establish the bounded native
contract, not general PDF conformance or owner quality acceptance.

Material and Texture also resolve fixed engines through the packaged receipt,
maintained source lock and binary hash. Their existing inspection routes compare
the complete current native model and embedded resources across cold processes;
the replay layer additionally requires exact native inventories and bytes.
Material checks its retained original and lineage record. Texture separately
admits and cold-opens `native/source.tcraft`, which ordinary inspection merely
preserves. Both deny inherited permission to execute links or recipes. A stored
`accept_generated_uvs` value cannot authorize a new conversion during replay.

Neither surface profile claims typed history replay or regenerated exports.
Material retains its existing `initial_source_preserved` proof; Texture reports
the exact imported native bytes and a separate `retained_source_replay`
observation, without inferring a complete source lineage. Map files, thumbnails,
previews and earlier inspection reports remain preserved artifacts with
`export_semantics_replayed: false`. A later explicit cook, export or render has
its own bounded contract.

Layout, Interface and Animate use the same exact native inventory/byte boundary
with fixed receipt-bound engines. Layout also pins its independent PDF reader;
its page and IDML roundtrips use exact bundled fonts. Interface reopens the full
document and embedded assets, retaining its own text and clipping limitations.
Stored recipes cannot authorize font substitution. Animate reopens both the
current document and retained `native/source.anicraft`, comparing complete native
state and selected static frame previews. It does not claim interactive playback,
audio fidelity or a complete movie replay. These three profiles preserve earlier
exports without claiming their semantic equivalence or typed revision history.

Layout now also requires its mapping to cover every supported native frame.
Checking only the records present allowed a missing frame binding to pass native
inspection. The previous packaged adapter reproduced that omission on a private
copy; the updated adapter refuses both empty and partially missing mappings.
Valid existing aliases remain supported, and positive create/revise bundles
retain their complete editable identities.

Audio uses a genuine observation route shared with typed production. It opens,
saves and bounces the complete current session in two separate native processes,
compares every session field (with the existing native f32 gain rule), verifies
source bytes and compares all output PCM samples. Replay resolves its fixed
package receipt and binary; an empty PATH does not select another engine. It
requires the complete native and asset inventories and refuses unqualified native
files instead of silently dropping them from a subsequent revision.

Native edits also retain `native/Backups/document backup N.scraft`. Each bounded
backup is admitted and independently opened, saved and bounced on a disposable
copy, with complete model preservation. Its original serialized bytes remain
unchanged in the imported project. These observations do not establish a typed
revision chain or an original-source lineage. Unknown fields discarded by the
native parser are refused in both the current session and any retained backup.
The first private replay attempt omitted these legitimate backup files; the
preserved refusal led to the explicit backup contract, not deletion of evidence.

Audio replays its entire export inventory and requires the delivered WAV to match
the regenerated format, duration, channels and complete PCM. Both Audio and PDF
therefore report `export_semantics_replayed: true`. Audio does not claim listening
approval, general mastering quality or historical export equivalence. Ordinary
create/edit operations retain their two-process qualification; backup replay is
specific to the explicit import profile. Local storage-only import and default
hosted operation admission remain unchanged.

Photo uses a separate observation route that never submits an empty edit. It
admits the complete catalog, mapping, originals and bounded retained history,
then renders every current photo in two cold native processes. The entire
snapshot, including its sequence number and every retained history/version
record, must remain equal. Replay additionally requires exact native file bytes,
complete source/export inventories and the original source bytes. The fixed
engine is resolved through the package receipt and source lock, with no PATH
fallback. Stored recipes cannot authorize external profiles, browsed folders,
unreconciled journals or a source outside the portable project.

Photo compares bounded PNG scanlines at their full 8-bit or 16-bit precision and
also binds all non-IDAT chunk metadata. This catches low-bit changes invisible
in an 8-bit preview and color metadata that could change display interpretation.
Equivalent recompression and IDAT chunk splitting remain accepted. The complete
export inventory is replayed, so Photo joins PDF and Audio in reporting
`export_semantics_replayed: true`. Retained history is observed and preserved,
not claimed as a typed operation chain. General camera RAW fidelity, new subject
synthesis and owner visual approval remain outside this proof.

Inspect requires a separate caller-supplied authorization in addition to the
explicit family selection:

```python
bundle.execute(source, destination, maximum,
               replay_families=('inspect',),
               replay_authorizations={'inspect': {
                   'permission': 'owned-or-authorized',
                   'input_sha256': authorized_input_sha256,
                   'expected_sha256': authorized_native_project_sha256,
               }})
```

Neither the outer archive, retained origin nor last-operation recipe can supply
this authorization. Both hashes must match the actual original input and current
native project before an engine is constructed. The import also requires the
currently qualified macOS ARM64 host and report environment; a simulated Linux
policy refusal is not Linux execution evidence. Default public/hosted admission
and storage-only local import remain unchanged.

The existing fixed, receipt-bound Inspect engine analyzes the authorized input
in two cold native processes, reproduces the complete native report and replays
every analyst annotation. Target code is never executed and external references
are never resolved. Exact native inventory and byte comparisons cover the
original input, report, current notes, intermediate notes and portable project.
The result reports `initial_source_preserved` and `annotation_history_replayed`.
It leaves generic `native_history_replayed` false, avoiding a claim about past
native invocations merely because analyst edits replay correctly.

Current JSON, escaped self-contained HTML and native project deliveries are
regenerated exactly. The inspection-summary envelope must be consistent with
the retained operation and its typed parameters. This recipe is checked as data;
its operation is never executed. An annotation request must equal the last
replayed annotation step. A historical prior-project hash is checked for request
consistency, not reconstructed as proof of the old ZIP's exact serialization.
Consequently `export_semantics_replayed` and
`current_content_deliveries_replayed` are true while
`historical_execution_authenticated` remains false. The checks authenticate
neither prior human permission nor a historical invocation. Fresh caller consent
is still mandatory for every replay.

## Reproducing the bounded acceptance

`craft/runtime/tools/bundle_replay_acceptance.py` takes a read-only package, a
checksum-bound input inventory and a fresh disposable output directory. The input
JSON contains exactly `write`, `slides`, `cad` and `sheets`, each with `path`,
`bytes` and `sha256` for a complete existing project ZIP. Paths are absolute.
Use the package's Python under an OS network-deny policy:

```sh
/absolute/package/lib/dobe/python/bin/python3 -I -B \
  craft/runtime/tools/bundle_replay_acceptance.py \
  --package /absolute/package \
  --inputs /absolute/inputs.json \
  --output /absolute/new-disposable-output
```

The harness explicitly loads the two changed replay source modules while using
unchanged packaged adapters and receipt-bound native engines. It does not modify
the package or claim a sealed release contains those source changes. Acceptance
covers four complete native bundles, twelve admission/inconsistency refusals and
one deliberately altered export whose bytes are preserved without a semantic
validation claim. The five successful replay cases run real native engines;
refusals are not substituted native mocks. Inputs remain unchanged.

The local application already offers whole-project byte-preserving import and
explicitly reports `native_cold_reopen: false` for that storage-only operation.
This source-level qualification does not change that API into an implicit engine
execution route. Subsequent typed application operations retain their own native
admission and durable publication checks.

`craft/runtime/tools/pdf_bundle_replay_acceptance.py` uses the same invocation
flags and network-deny requirement. Its input keys are `original`,
`replacement-restyled` and `portable-restored`, with the same checksum fields.
It explicitly loads source `pdf.py`, `bundle.py` and `bundle_replay.py` into the
package namespace. Three real native replays cover created, incrementally edited
and previously restored PDFs. Nine refusals cover the three default hosted
boundaries, inconsistent structural metadata, an additional native member,
altered PDF/report deliveries, a missing page and a one-pixel preview change.
All altered bundles have internally consistent outer hashes. The package and
original fixtures remain unchanged; this is source qualification, not a newly
sealed package or a Linux execution result.

`craft/runtime/tools/surface_bundle_replay_acceptance.py` uses the same flags and
requires `material-revised`, `material-restored`, `texture-linked` and
`texture-restored` input records. It loads the two source adapters, their fixed
binding and the two replay modules into the package namespace. Six actual native
replays cover the four bundles and two deliberately altered exports whose
semantics remain explicitly unverified. Ten refusals cover default hosted
admission, inconsistent native mappings, additional native members, a corrupt
retained Texture source and a stored recipe attempting to grant UV conversion.
The native runs succeed with an empty engine search path. Executable hashes and
all original input files are checked again at completion.

`craft/runtime/tools/publication_bundle_replay_acceptance.py` takes the same flags
and six inputs: `layout-original`, `layout-revised`, `interface-original`,
`interface-revised`, `animate-revised` and `animate-restored`. It loads the changed
transports/adapters, fixed binding and replay modules into the unchanged package
namespace. Nine actual native replay cases and fourteen refusals cover complete
bundles, default hosted boundaries, missing/extra native metadata, a partial
Layout mapping and an invalid retained Animate source. Three successful cases
deliberately preserve altered exports without asserting semantic replay. An empty
engine search path verifies fixed executable resolution. Source qualification
does not update an installed package or establish Linux execution.

`craft/runtime/tools/audio_bundle_replay_acceptance.py` uses the same arguments
with `original`, `revised` and `restored` checksum-bound input ZIPs. Three complete
Audio replays include every retained native backup. Fourteen refusals cover the
default hosted boundary, missing mappings, discarded current/backup fields,
extra native files, stale dependencies, missing exports, altered/nonfinite PCM,
extra previews, unreferenced media and external sources. Three additional real
native create/edit/restore operations exercise the refactored production route,
including exact unrelated model preservation and restored PCM. The inputs were
created by three durable jobs through the unchanged sealed public CLI, including
a fresh-state portable restoration. These native operations and replay cases are
not additional durable jobs.

`craft/runtime/tools/photo_bundle_replay_acceptance.py` takes the same arguments
with seven inputs: `original`, `editorial`, `monochrome`, `portable-restored`,
`formats`, `raw-revised` and `eight-bit`. The four retained photographic delivery
archives have only their outer directory prefix removed in separately preserved
ZIPs; every member byte and manifest hash remains equal. The existing complete
Photo acceptance creates three fresh numeric libraries covering PNG, TIFF,
oriented JPEG and synthetic sensor DNG, including native revisions and both
output depths. Those fixtures do not establish general camera RAW fidelity.

Eight Photo replay cases include equivalent PNG recompression. Seventeen
refusals cover default hosted admission, missing mappings, stale dependencies,
unreconciled journals, extra native/source/preview members, external sources,
unsupported retained history, altered 16-bit values and changed PNG metadata.
The altered low-bit fixture has identical 8-bit decoded RGB, so a reduced-depth
comparison would miss it. Three additional native create/edit/restore operations
exercise the modified transport and preserve prior history and original source
bytes. Their final pixels equal the original native rendering. These direct
native operations and replay cases are distinct from the existing durable-job
acceptance that supplied the numeric libraries.

`craft/runtime/tools/inspect_bundle_replay_acceptance.py` takes the same package,
input and output arguments. Its input inventory has eighteen owned retained
fixtures, each with a separate explicit `authorization` object in addition to
`path`, `bytes` and `sha256`. Actual native replays cover all six Inspect
operations, annotation additions/changes/removals, JSON/HTML/native exports,
JavaScript including parser fallback, WebAssembly including an invalid-input
report, ELF, Mach-O and PE. Fifty-three refusals cover missing/stale/wrong consent,
default hosted admission, unqualified host/report environments, forged native
findings, broken annotation history, extra/mismatched members and altered
summaries/deliveries. A constructor observer delegates to the real engine and
proves that consent/admission refusals do not start it. The Linux-host policy
branch uses a local stub and claims no Linux native execution.

## Video and Motion

Both profiles observe existing editable projects, without manufacturing no-op
edits. Receipt-bound native binaries render on disposable copies. Video opens
and saves the complete model with the same document filename, comparing every
serialized field. Motion retains its full model comparison with only its two
session-view fields excluded; all imported native bytes still remain exact.
Complete native inventories, editable mappings, linked media inventories and
source hashes are required. Missing bindings, discarded native fields and unused
assets cannot become accepted by a directory scan.

An independent, exactly pinned FFmpeg/FFprobe pair decodes every delivered and
regenerated H.264 frame. The profile compares all original YUV420 sample bytes,
every presentation timestamp, complete stream/color metadata and all stereo
48 kHz decoded PCM. It preserves subframe timing using the demuxer time base.
Decoding forces the MOV/MP4 demuxer, disables external data references and limits
protocols, output bytes and runtime. The three separately rendered PNG previews
also match, but those samples do not stand in for complete movie verification.
Equivalent container remuxes may pass when full decoded contents/timing match.

Retained probe JSON must describe the original delivered movie. Motion render
receipts bind their composition and bounded shape; historical elapsed time and
machine-specific output paths are preserved as unauthenticated provenance.
They are never followed or executed. Results explicitly report
`historical_render_execution_authenticated: false`. Native revision history and
original-source lineage remain unclaimed; current imported native state and all
movie contents are checked. Visual approval remains false.

The maintained `movie_bundle_replay_acceptance.py` fixture uses six checksum-bound
retained branded-film projects. It covers four native Motion compositions, the
15-second original film and its 17-second revision, plus an equivalent remux.
Negative cases include an actual valid movie with only unsampled frame 1 changed,
and altered audio with every picture frame unchanged. Separate direct production
create/edit/restore calls exercise both existing public adapter entry points.
Read the evidence from a completed run before claiming these checks pass.

The decoder support route currently requires the qualified macOS host. Linux
native receipt declarations do not establish Linux decoder qualification or
supporting-library distribution rights. These remain explicit hosted/release work.

## Remaining full-product work

All seventeen families now have source replay routes, but source coverage does
not establish sealed-package or cross-platform qualification. Inspect remains
admitted only on macOS ARM64: Linux needs explicit report migration retaining
original findings and annotation evidence. Video and Motion require qualified
Linux supporting decoders. A recipe embedded in an untrusted bundle is never
new consent. No family is complete merely because its identity appears in a catalog.

Integrate selected profiles with the full hosted SQL/admission transition and
qualify actual Linux x86-64 workers, private publication, durable cancellation/
recovery, resource limits and cross-platform migration. Keep the local
storage-only import boundary honest. The full product also retains package,
rights, signing, clean-host, billing/provider and owner quality gates. No remote
action, VM restart, deployment or release is authorized by these local checks.

## Hosted request integration

The hosted `native-v2` worker contract declares its supported import families.
Explicit authenticated requests select one family; legacy requests without a
family continue to accept only image/vector projects and require an image that
supports both. Selection is checked in queue claiming, before container creation
and at boot. The archive cannot choose a different engine. Publication binds the
result to the exact import parameters and selected family's validation evidence.
Inspect additionally requires fresh authorization and both hashes in the request.

`hosted_portable_acceptance.py` exercises the shared hosted boot entry point with
real packaged macOS engines and explicit source overlays. This route does not
prove PostgreSQL predicates, container isolation, Linux decoder/native parity,
Inspect cross-platform migration or a sealed package containing the overlays.
Migration 022 fences older writers at version 16; no automatic migration occurs.
