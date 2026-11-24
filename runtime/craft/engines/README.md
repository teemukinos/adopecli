# Maintained native engine builds

The offline Linux catalog build route (`craft/engines/LINUX_BUILD.md`) prepares portable pinned
inputs for all seventeen families and connects the native builder to the worker
assembler. Its exact input checks and remaining Linux execution gates are
separate from the historical engine evidence below.

The application `.lock.json` files, including `write.lock.json` and `slides.lock.json`, pin each engine source commit, font source commit, Rust version,
Cargo dependency lock and Dobe patch checksum. The corresponding `.patch` file is the maintained
source delta; it is applied to a clean archive of the pinned commit. The build
does not use uncommitted checkout files and does not rename a downloaded binary.

Build on macOS ARM64 or a Linux x86-64 host with Python 3.12+, Git, the locked Rust
toolchain, the platform linker and an existing Cargo dependency cache:

```sh
python3 craft/engines/build_engine.py --engine image \
  --source /path/to/photocraft-checkout \
  --fonts /path/to/craft-fonts-checkout \
  --rust-bin /path/to/rust-toolchain/bin \
  --output /path/to/new-build-directory
```

The output contains archived source, fonts, a build log and `dobe-image/` with
the native executable, notices and `engine.json`. The manifest records exact
source/patch/compiler inputs, enabled features and every distributed file hash.
`cargo-messages.jsonl` retains Cargo compiler artifacts separately from the
human-readable diagnostics in `build.log`. These private build records include
local paths and are not part of the distributed engine pack.

On macOS ARM64, `--link-map` additionally invokes `cargo rustc` for the selected
final binary and captures Apple ld's `link.map` plus a private `link-map.json`
beside the build log. Extra linker flags apply only to that target, not to every
build-script link. The default build command is unchanged. Other hosts and output
paths containing commas or line breaks are refused for this optional capture.

The report binds the linker's output bytes to Cargo's freshly linked executable,
matches archive paths to compiler package IDs and hashes retained archive
containers. It separates live and dead symbol records, toolchain archives,
unattributed objects and SDK stubs. Apple ld's literal symbol labels can contain
non-UTF-8 bytes; only their structural prefix is parsed. Capture refuses malformed
sections, ambiguous artifact ownership, stale/failed compiler evidence, escaping
paths and changed binary/archive bytes. Maps and compiler records are bounded to
256 MiB each, with a 2 MiB line limit.

These files contain local paths and stay outside the distributed engine pack.
This is partial provenance, not complete static linkage: archive member bytes,
LTO, temporary objects, toolchain sources, dynamically loaded libraries and
assets need separate evidence. Unmapped packages are not proven absent. Symbol
counts are records, not nonoverlapping binary-byte coverage. Neither dependency
notice requirements nor the release refusal change; `binary_linkage_determined`
and `redistribution_approved` remain false.

Run the local parser and binding boundary checks with Python 3.12 or later:

```sh
python3 -B craft/tests/link_map_check.py
```

`notices/dependencies/inventory.json` records the actual compiled packages,
including build scripts and proc macros, their declared licenses and copied
notice hashes. `dependency_notices.py` verifies registry archives against the
pinned Cargo.lock, reads their original notice bytes, and resolves workspace
license inheritance from the archived sources. Git dependencies must match one
exact Cargo.lock revision. The collector checks every tracked checkout file
against the stored Git tree, including executable modes and bounded internal
links, then copies notices from the verified Git objects. Workspace inheritance
and notice links remain tied to that same revision. Raw Git reads disable
transport, hooks, replacement refs and lazy fetching. Local source collection
excludes Cargo `target` directories and `.git` metadata. It never downloads missing
notices or substitutes license templates. Missing archives, declarations,
notices or unsupported sources remain explicit issues. A source or archive
identity mismatch fails collection. Git records include the source tree, tracked
file/byte counts and notice blob identities; the preview gate verifies those
identities against the shipped notice bytes. Untracked build inputs remain
unqualified. Repository notice directories may include notices for components
not linked by the selected package, so their presence is not linkage evidence.

Some archives retain their original notice only inside a source file. The
collector supports explicitly inspected excerpts pinned to the package name,
version, archive checksum, full source-file hash/size and exact byte range/hash.
It currently preserves the original qrcodegen 1.8.0 header this way, without
normalizing its bytes. An unrecognized package/version is not inferred from an
MIT declaration or source-text search. Missing or changed pinned source fails
collection. The inventory records the source provenance, and the preview gate
checks its exact pins and copied bytes even if an inventory has been rehashed.
This does not approve terms, establish linkage or update older engine packs.

Run the local boundary checks with Python 3.12 or later:

```sh
python3 -B craft/tests/dependency_notice_excerpt_check.py
```

Future public preview assembly requires complete collected notices in every
engine pack. Previously prepared packs must be rebuilt with this capture step;
their frozen evidence is not modified. Complete collection does not determine
binary linkage or approve redistribution. Native dependencies, assets/fonts,
license obligations and the other release requirements remain separate gates.

Image and Vector are CPU-only. Video and Motion retain native optional hardware support; the durable
runtime explicitly requests CPU rendering for its qualified exports. `--profile dev` selects a development build; the default
is release optimization. `--jobs 1` reduces concurrent compiler memory use; the
default is four jobs and the selected count is recorded in the engine manifest.
`--fetch` permits Cargo dependency downloads; without
it Cargo is offline. Nothing is installed, published or deployed.

For a public preview package, add `--public-paths`. This mode normalizes Rust and
native compiler source paths, strips debug symbols and refuses an executable
that still contains the builder's home or output-parent path. Its manifest
records the normalization mode. Use sibling output directories with a shared
`--target-cache` to reuse dependencies with the same compiler flags. The preview
assembler requires this mode; old development binaries must be rebuilt from
their pinned source, not relabeled or patched as binary files.

This is a reproducible source recipe, not a claim of bit-for-bit reproducible
compiler output. Host SDK/linker qualification, signing, Linux runtime dependency
packaging and complete Dobe identity coverage remain release requirements.
Internal crate/native-format names and required upstream notices are retained.
The product's supported MCP connection is supplied by the durable Dobe runtime.

The patch adds `type.info`'s optional `fontDiagnostics` field: actual font hashes,
collection indices, variation coordinates, synthesis flags, glyph IDs, source
UTF-8 byte ranges and fingerprints of built-in fonts. It refuses incomplete or
inconsistent reports. These are shaped-glyph diagnostics, not a promise that
every source character paints a glyph or that a native project embeds fonts.
The runtime must validate the actual faces against its admitted font policy.

The patch also updates three iteration patterns for Rust 1.100's strict Clippy
checks. The existing channel-count assertion is retained. Invalid sparse row
ranges return `None` rather than indexing outside the column array.

## Video source package

Use the same command with `--engine video`, the pinned FilmCraft checkout as
`--source`, and a new output directory. The result is `dobe-video/`. The patch
adds a separately named executable and a feature-gated native MCP identity;
the default upstream build remains available. Dobe help describes headless use,
and the executable refuses editor bridge connections. Native file formats,
command IDs, crate names and legal notices retain their upstream identities.
The durable runtime remains the supported customer MCP endpoint.

`build_image.py` remains a compatibility entry point with Image as its default.
Both entry points require Python 3.12 or newer. Build manifests bind the actual
lock snapshot read at startup, so a concurrent edit cannot relabel an older
build with a newer source lock. Installer assembly checks both the lock digest
and its embedded contents before accepting an engine pack.

## Motion source package

Use `--engine motion` with the pinned EffectCraft checkout and a new output
folder. The `dobe-motion/` pack contains the headless executable, source/font
notices and exact build provenance. Its feature changes executable help, errors,
version and native MCP identity/resources. It refuses editor bridge arguments
before connecting and excludes the upstream trademark image from the binary.
The upstream default build remains available, with unchanged native formats and
command IDs. No model weights or paid generation service are required.

The source recipe does not establish complete upstream qualification or product
readiness. Native fidelity, actual shaped-glyph diagnostics, Linux x86-64 and
Cloud acceptance remain separate release gates. The customer MCP endpoint stays
`dobe mcp`; the embedded native server is an implementation detail.

## Vector source package

Use `--engine vector` with the pinned VectorCraft checkout. The `dobe-vector/`
pack uses the same archived-source, exact-patch and manifest checks as the other
engines. Its feature changes CLI and native MCP identity, including fixed
resources and object/command/effect/swatch templates. It always runs in safe
mode and refuses editor connections; default MCP startup cannot attach to a
running editor. The upstream default build remains unchanged.

The local runtime prefers `dobe-vector` and retains the upstream binary as an
explicit packaging fallback. Native project extensions, document metadata and
engine identities in portable revisions remain compatible with earlier versions.
Maintained source provenance does not establish complete vector fidelity,
shaped-glyph verification, or Linux/Cloud qualification.

## Complete catalog source inputs

`catalog.sources.json` records all seventeen application mappings and immutable
source commits. These are source inputs, not a capability or release manifest.
An entry without `maintained_lock` still needs its source patch/build contract,
licenses, typed native operations and local/Cloud qualification. Runtime
capability discovery must report only operations actually implemented and engines
actually present. Do not present source discovery as a completed application.

## Audio source package

Use `--engine audio` with the pinned SoundCraft checkout. The `dobe-audio/`
pack records the same exact source, patch, compiler and file checksums. Audio
does not use a GPU. Its opt-in feature provides Dobe CLI and MCP identities,
headless instructions and resource URIs. Editor connections are refused before
opening a socket; desktop-only tools are absent from discovery. Native command
IDs and `.scraft` files remain compatible with the upstream engine.

The local builder accepts `--audio-engine /path/to/dobe-audio`. The supported
product interface remains `dobe mcp`, with bounded durable Audio operations
documented in the runtime README. Packaging does not qualify plugins, arbitrary
native sessions, the full upstream workspace, Linux or Cloud. Those require
their own evidence. No paid generation model is required for native audio work.

## Photo source package

Use `--engine photo` with the pinned LightCraft checkout. The `dobe-photo/`
pack contains a maintained native photo developer and catalog engine, distinct
from the layer-based Image engine. The Dobe feature provides CLI/MCP identity
and resource URIs. The build excludes the UI snapshot dependency and optional
model inference runtime. Editor connections, snapshots and network denoise
serving are refused. Native catalog formats and upstream legal notices remain.

Dobe sessions do not automatically load the desktop user's downloaded lens,
face, segmentation or denoise models. CPU execution is selected explicitly with
`LIGHTCRAFT_GPU=0` and `LIGHTCRAFT_GPU_BACKEND=off`; the engine itself retains
optional native GPU code. The product runtime must isolate configuration paths,
bound all imported media, validate native projects before opening them, and
admit only typed operations. The native command catalog is not the customer
runtime's authorization boundary.

Local native probes cover non-destructive exposure/contrast, normalized crop,
PNG export, stable photo identities, retained edit history, portable relative
sources, and cold reopening with the original directory denied. An owned
uncompressed RGGB DNG proves sensor decoding without an embedded JPEG preview.
This does not establish general camera RAW fidelity or support for every RAW
variant. The durable Photo adapter refuses preview-only fallback. The local
builder accepts `--photo-engine /path/to/dobe-photo`; `photo.create` and
`photo.edit` are documented in the runtime README. Installed lifecycle,
Linux/Cloud qualification and full upstream workspace checks require their own
evidence; the source recipe alone does not establish them.

## PDF source package

Use `--engine pdf` with the pinned PdfCraft checkout. The `dobe-pdf/` pack
contains the headless PDF engine, with feature-gated CLI/MCP identity and
`dobe-pdf://` resource addresses. The editor control module is excluded from
the Dobe binary, and `ui` is explicitly refused. The upstream build remains
available without the feature. Native PDF objects, existing document content
and upstream legal notices are preserved. The source recipe requires the pinned
font input and records all source, patch, compiler and output hashes.

The Dobe PDF build excludes OCR model discovery in the original source checkout.
Explicitly configured and executable-relative model paths remain available in
the native engine, without embedding the builder's home directory. This does
not add OCR to the durable runtime's supported operations.

The durable PDF adapter admits bounded create, import, inspect, merge, extract
and edit operations. The local distribution builder accepts `--pdf-engine`.
The adapter disables document JavaScript before opening documents, isolates
configuration, and uses the maintained structural inspector to refuse active,
encrypted and over-budget inputs. Scripts, Office conversion, OCR and signing
are outside that typed contract. Merely passing `--root` does not establish it.
Use `PDFCRAFT_SYSTEM_FONTS=0` for repeatable exports and qualification; see
[the PDF runtime contract](../runtime/PDF.md) for admission and revision guarantees.

PDF itself is the editable native deliverable. Incremental saves preserve the
original bytes when requested, and cold reopen must retain page content,
annotations and placed text. General rendering fidelity, glyph coverage,
standards compliance, the full upstream workspace and Linux/Cloud execution
remain separate qualification requirements. A successful source build alone
does not establish those properties.

## Layout source package

Use `--engine layout` with the pinned DesignCraft checkout and a new output
folder. The `dobe-layout/` pack contains a CPU page-layout engine with opt-in
Dobe CLI and MCP identity. Editor connections are refused before reading a
script or resolving an address. Native `.designcraft` documents, command IDs,
PDF/IDML interchange and upstream legal notices retain compatibility.

The Dobe feature disables host font catalog scans and system fallback. Bundled
fonts remain available; explicitly supplied document fonts still pass through
the engine's confined read roots. This prevents an unrelated machine font from
silently changing a portable job. It does not establish exact shaping fidelity
or permit silently substituting a missing requested font.

The [bounded Layout runtime contract](../runtime/LAYOUT.md) supplies creation,
native/IDML import, inspection and precise text/position/typography revisions.
Development package `0.1.0-dev.41` includes the maintained engine and independent
PDF validation. Installed lifecycle and portable native reopening are checked
locally. The maintained source passes 48 targeted tests and strict Clippy;
full native workspace CI, broader revisions, Linux/Cloud and external release
qualification remain open. The native command catalog includes printing and
other operations that are not exposed as arbitrary commands by the product
runtime. The supported customer connection remains `dobe mcp`.

## Interface source package

Use `--engine interface` with the pinned FigCraft checkout and a new output
folder. The source recipe produces `dobe-interface/`, with an opt-in Dobe
CLI/MCP identity and `dobe-interface://` resources. The build uses bundled fonts
and disables host font discovery. Ambient optional font-selection variables are
cleared so the pinned source and font inputs determine the embedded catalog.
Interface uses the font revision pinned by its upstream release workflow,
including the Latin presentation catalog. Its Dobe build refuses missing Inter
Regular/SemiBold or Georgian faces instead of silently relying on host fonts.
The pinned font files and license notices are checked locally against all 64
manifest hashes; the native build selects 55 faces under its existing asset
policy. Other engines retain their own font locks.
Editor attachment and CLI publication routes are refused. The headless backend
does not install a network collaboration transport. Upstream defaults, native
`.figcraft` documents and required legal notices remain intact.

Local native probes pass for Dobe identity and file-root refusal with network
and host font folders denied. Real native documents preserve auto layout,
component links, instance text overrides and embedded raster bytes through main
component edits and cold reopening with the original directory denied. Untouched
frames retain their structure and pixels; SVG output retains editable text.
The font build-input checks pass eight cases. The preceding source snapshot also
passes 92 targeted MCP, CLI and font tests plus strict Clippy. These are targeted
source checks, not full native workspace CI. A newer source snapshot adds a
Dobe-only read-only text diagnostic command; its evidence is tracked separately
from the preceding checks. See `craft/runtime/INTERFACE.md` for its limits.

Interface is included in unsigned dev.42 as the ninth maintained application.
Its four typed runtime operations have installed development-Mac evidence for
component revisions, complete native preservation, portable reopening,
rollback/reinstall, cancellation and supervisor-crash reconciliation. The builder
checks the maintained source lock and every pack file before assembly. Text
shaping and bounded raster exports have explicit checks; clipping and visual
approval remain separate, open qualifications. The full native workspace,
clean-machine/reboot, Linux and Cloud also need qualification. A source pin or a
successful native build does not establish those properties. The customer
connection remains `dobe mcp`.

## Maintained Animate source

`build_engine.py --engine animate` builds the private `dobe-animate` entry from
AniCraft v0.2.1 with `animate.lock.json` and its maintained patch. The CPU build
preserves native `.anicraft` format 3: versioned JSON with scenes, timelines,
keyframes, editable elements and a shared path table. It does not open an editor.

The opt-in Dobe feature requires explicit read and write roots. Native disk reads,
writes, streamed exports, renames and removals pass through the shared VFS checks.
File command paths resolve before overwrite confirmation, including separate input
and output roots. Positional CLI inputs retain their canonical source path, so
publication cannot reinterpret that path under another output root. Traversal
and symbolic links are refused. This constrains access
inside owned attempt directories; it is not an operating-system sandbox against
another process racing filesystem changes.

The build embeds twenty pinned faces from Inter, Source Sans 3, Source Serif 4,
Liberation Mono and Liberation Serif. Production font discovery ignores host fonts
and the runtime `CRAFT_FONTS_DIR`. Plugins, editor screenshot delegation and
external executable-based video export are refused. Native PNG frames, GIF,
SVG and sprite sheets use the engine directly. Folder XFL import requires a
separate confinement contract; self-contained archives remain native inputs.
Both stdio transports bound requests to 4 MiB. Native command schemas remain an
internal interface; this does not add arbitrary command execution to product MCP.

Local native probes cover 24 selected frames from a 47-frame native document,
with a classic tween, measured object positions,
editable text revision, complete cold native/pixel reopening, unchanged animated
artwork, decoded GIF timing and sprite tiles. The revision changes only the target
text, its intrinsic width and stored glyph outline in the complete saved document.
SVG parsing and dimensions are checked separately from unclaimed SVG render fidelity.
These probes deny network and host-font reads. Text shaping, imported native
admission, full workspace checks, durable typed runtime operations and installed
Animate lifecycle still require qualification. Dev.42 remains nine applications;
this source increment is not a tenth packaged app or a complete Local/Cloud release.


The Dobe-only `file.inspect_sound` command qualifies complete WAV, Ogg Vorbis and
MPEG audio files without changing the open document. The same native decoders
produce exact sample counts, rates, channels, peak and RMS. Input is limited to
32 MiB; an explicit sample limit (at most 67,108,864 across channels) is enforced.
WAV qualification checks complete chunks/frames and finite floating samples.
Ogg qualification checks every page CRC, sequence, continuation and physical EOS;
chained streams and decoder errors are refused. MPEG qualification uses the pinned
native frame iterator and low-level decoder, checks contiguous complete frames and
constant format, and validates gapless metadata against the decoded frame count.
Tags and valid encoder delay/padding remain supported. Native first-two-channel
selection remains explicit. The ordinary importer keeps its tolerant behavior.

This diagnostic is private to the runtime's admission pipeline. It does not add a
user-facing arbitrary command route or establish perceptual audio fidelity. Local
qualification includes exact valid samples, malformed tails/nonfinite refusals,
requested sample limits, filesystem confinement and unchanged document state.

`file.inspect_soundtrack` computes the native audio layout without writing a file.
Dobe `file.export_audio` uses the same checked layout before publication. Default
upstream playback keeps its tolerant behavior. The checked route refuses native
stretch/depth truncation, bounds stored graph indexing, counts expanded timeline,
layer, keyframe, element and instance-continuity work, and limits expanded sound
placements to 8,192 and copied custom envelope points to 262,144. Start/Stop
matching permits at most 2,000,000 voice comparisons. Used sources decode once per
sound ID under aggregate sample/byte limits, with exact metadata comparison.

Mix limits apply after the requested range selects voices, following native event
and stream semantics. Each export permits 33,554,432 output frames and 268,435,456
weighted sample operations. Equal-rate stereo mixing counts two operations per
frame; resampling counts eight source taps; an envelope adds two gain operations.
These are deterministic work units, not CPU timings or billing estimates. Silent
voices still participate in native Start/Stop resolution. No audio device opens.
The command remains private to the maintained engine; runtime registration and
installed qualification remain separate release work.

`text.inspect_layout` traces the same harfrust shaping and skrifa outline pass used
by native text creation and revision. It reports the selected embedded font file
(by matching the actual bytes), collection index, PostScript name, weight and
slant; requested family/style matches; missing characters and `.notdef` glyphs;
source UTF-8 clusters, advances and offsets; drawn positions, ink bounds and line
metrics. `text.inspect_stored` selects a text block by scene or symbol, layer,
covering keyframe and element ID, then compares the regenerated native path and
box metrics with the stored values without repairing them.

Dobe text authoring permits 8,192 characters, 32,768 shaped glyphs and 250,000
outline commands per block. The outline pen stops collecting when its budget is
exceeded. Default upstream limits remain unchanged. Native imported documents
retain their cached outlines; these diagnostics make stale geometry and font
substitution observable before a revision. The three Inter/Source families in
the pinned bundle lack a bold-italic face: requesting that combination reports a
style mismatch. Liberation Serif and Liberation Mono include all four styles.

The native layout shapes one run per paragraph and wraps at spaces. It does not
perform full bidirectional itemization. A matching glyph trace or stored outline
does not establish correct mixed-direction typography, clipping or publication
approval. Runtime admission must interpret these reports before authoring or
revising text; the diagnostic commands alone do not register an Animate operation.

The maintained Animate geometry layer includes opt-in, shared work accounting for
path scans and generated geometry. One scope permits 2,000,000 path commands,
2,000,000 flattened points, 20,000,000 weighted morph steps, 2,000,000 nine-slice
commands and 10,000,000 path-walking steps. Repeated operations consume the same
counters. Nested scopes cannot reset them; explicitly entered worker scopes share
atomic counters and the first failure. Scope restoration also handles unwinding.
These are work limits, not measured CPU costs or a complete peak-memory bound.

Checks run before path scans, growth, curve samples, morph subdivision/alignment,
hint matching and nine-slice pieces. Actual transformed control points must be
finite and within ±1,000,000,000. Native flattening caps, morph caps, approximate
nine-slice fallback and truncated curve walks become errors in a checked scope.
The native geometry algorithms remain authoritative. Morph area sorting caches
the same areas to avoid repeatedly allocating polygon points in comparisons.

The private `file.inspect_frame` command now enters checked native evaluation and
the shared geometry scope. A caller must consume only a successful result and
publish afterward; intermediate
empty paths or native fallback values after failure are invalid output. Rayon
workers explicitly enter the captured shared scope. The checked CPU renderer
described below now bounds stroke growth, filter surfaces and raster work per frame.
The existing runtime `render_budget_verified=false` remains accurate.

Checked evaluation uses the same native timeline, camera, tween, motion, armature,
mask, group and nine-slice algorithms. One frame permits 65,536 expanded timelines,
1,000,000 layer scans, element scans, instance-continuity steps and recursive bounds
visits each, 20,000,000 helper work units, 32,768 display items and 32,768 clips/groups.
Copies reserve up to 64 MiB of metadata cumulatively; this conservative reservation
does not measure peak memory. Native recursion truncation becomes an error. Actual
composed transforms, colors, output paths and recursive bounds use the geometry
scope's finite-coordinate checks. Stored graph and metadata preflight bounds the
inputs before expanded traversal; it does not replace runtime semantic admission.

Used bitmaps decode afresh once per ID per evaluation, so stale legacy caches cannot
hide changed bytes or dimensions. Header dimensions are checked before allocating
the output buffer: 32,000,000 pixels per image and 64,000,000 per frame, with 32 MiB
per encoded image and 48 MiB per frame. The native PNG decoder bounds auxiliary
allocations and skips unused text/ICC metadata. Complete file-integrity admission
remains separate. Reports explicitly set `evaluation_budget_verified=true`,
`render_budget_verified=false` and `media_integrity_verified=false`. The command
accepts only an optional zero-based movie frame, returns counters and writes no
files. It does not register or package Animate in the product runtime.

`checked_render` now evaluates and rasterizes through the native CPU algorithms
under one shared rendering scope. Dobe PNG creation (including each frame of PNG
sequences) and the private MCP picture tool use this route before encoding or
returning an image. Default upstream rendering remains unchanged. A failed frame
returns an error before that PNG is written or its picture is returned.

Each checked frame permits 512 MiB of cumulative buffer reservations, 4,000,000
stroke work units, 1,000,000,000 raster work units and 20,000,000 helper work units.
Group and clip chains permit 64 levels. The native surface limit remains
16,777,216 pixels. Stroke resampling, dash-to-solid fallback and capped arc sampling
become errors instead of silently degrading geometry. Actual pixel-space controls
and generated stroke vertices use the shared finite-coordinate checks. Filters
reserve temporary coverage/effect planes before work and refuse native extent
truncation. Raster edges, hairlines, coverage, masks and group compositing charge
the same frame budget across worker threads and recursively filtered groups.

Dispatchers capture both scopes explicitly. A captured task replaces and restores
any unrelated scope on a work-stealing thread, including when the dispatched task
is intentionally unscoped. Ordinary nested computations cannot reset their budget.
The frame entry establishes its own context before evaluation, so an outer batch
task stolen during another frame's wait cannot inherit that frame's counters.
Checked renders release prepared geometry synchronously after workers join.

These counters are conservative deterministic work reservations, not timings,
billing amounts or a complete process-memory bound. Document/bitmap admission and
PNG encoding have separate bounds. Successful rasterization does not establish
complete semantic or media-integrity admission. Video and vector export paths
still need checked integration. The PNG sequence route below adds
shared operation limits; multi-file publication still needs runtime qualification. The full runtime therefore still
reports render admission unverified. Animate is not yet registered or packaged.


Dobe PNG sequences now compute all frames before changing the destination. They
retain at most 512 MiB of encoded PNG bytes and render one frame at a time (the
frame itself still uses Rayon). The request is limited to 600 frames and
552,960,000 total pixels, with the existing 16,777,216-pixel per-frame limit.
Each frame keeps its original geometry/render limits and additionally charges
shared export counters before work. Export limits are 8 GiB cumulative rendering
reservations, 32 million stroke units, 8 billion raster units and 160 million
helper units. Shared geometry limits are 32 million path commands, 32 million
flatten points, 160 million morph steps, 32 million sliced commands and 80 million
walk steps. Evaluation still has its existing per-frame limits; the 600-frame
request cap bounds the number of those evaluations.

PNG encoding refuses an output write before extending the retained byte buffer
past its remaining allowance. A late frame, encoding, cancellation or path
preflight failure leaves all destination files unchanged. Successful computation
preflights every output path, then writes on the command thread. This is not an
atomic filesystem transaction: an I/O failure during those final writes can leave
partial publication. The durable runtime must keep the entire operation inside
its owned attempt and publish only after validating the complete artifact set.
Default upstream sequence export retains its original behavior.


Dobe GIF and sprite-sheet exports now use the same checked sequence renderer and
aggregate limits. GIF keeps the native color quantizer, frame delays and loop
semantics, but encodes one frame at a time into a bounded 512 MiB byte writer.
The trailer must finish successfully before publication. Quantization and RGBA
conversion input are bounded by the sequence's aggregate pixel limit.

Sprite sheets keep one RGBA8 atlas and one current frame, rather than retaining
all floating-point frames and a second floating-point atlas. The atlas, including
padding and empty cells, is limited to 16,777,216 pixels (64 MiB RGBA8). Checked
arithmetic rejects invalid dimensions before allocation. Transparent backgrounds,
frame ranges, scale, padding, layout and timing retain their native behavior.
The bounded JSON map uses Dobe Animate as its producer name. A `.png` destination
is required so image and `.json` map cannot name the same file. Both paths are
preflighted before either write. Atlas metadata is limited to 4 MiB.

Geometry, rendering, encoding and path-preflight failures preserve existing
outputs. Final GIF/PNG/JSON filesystem writes still require runtime staging for
atomic publication and I/O recovery. These routes do not qualify SVG, Lottie or
HTML serialization, complete media admission, or installed Animate lifecycle.


Dobe SVG export now enters checked native evaluation and shared geometry/render
work scopes before running the native SVG formatter. Text buffers are capped at
64 MiB and reserve cumulative bytes before appending. Mask scans, group chains,
variable-stroke copies/outlines, transformed path formatting, gradient sorting,
filter ramp sampling and embedded PNG/base64 construction consume bounded work.
Composed bitmap matrices and formatted numbers must remain finite and within the
geometry range; failed bitmap encoding or truncated filter extents cannot silently
omit content in a successful checked export. Default upstream SVG output keeps
its native formatting and behavior outside a checked scope.

The export returns known format-difference notes for omitted shadow/glow modes,
unsupported blend modes, layer isolation, Gaussian filter approximations and
non-repeating bitmap fills exported as SVG patterns. Counts refer to evaluated
items/groups; this is not an exhaustive fidelity certificate. The result explicitly
sets `svg_serialization_budget_verified=true` and `raster_fidelity_verified=false`.
Successful serialization does not establish browser/CPU pixel equivalence, complete
media integrity or atomic filesystem publication. Lottie and HTML still need their
own checked evaluation/serialization paths, followed by complete runtime integration.

Checked SVG text and encoded-output buffers grow capacity geometrically within
their byte cap. Small formatting fragments reuse capacity instead of forcing a
reallocation and copy on every append. Output byte limits remain unchanged.


Dobe Lottie export uses checked native evaluation and variable-stroke outlining
before building the native frame tracks and hold keyframes. Every frame retains
its evaluation and geometry limits. The export accepts 1–600 movie frames, reserves
at most 512 MiB of cumulative buffer work, and limits helper work to 20 million
units. The reservation includes evaluated display copies, bezier conversion, mask
copies, track keys, names, draw-order edges and JSON materialization before their
allocation. JSON reservations deliberately overcount unchanged frames; these are
work limits, not measurements of peak memory. Serialized output is limited to
64 MiB using a fallible bounded writer. Transformed vertices, tangents, gradient
coordinates and stroke widths cannot silently become zero or disappear when they
exceed finite coordinate bounds.

The native animation structure and known feature-loss report are retained. Output
metadata identifies Dobe Animate. The command reports
`lottie_serialization_budget_verified=true` and `player_fidelity_verified=false`.
Successful serialization does not establish Lottie-player pixel equivalence or
exhaustive feature-loss reporting. All frames finish before any destination write;
final filesystem I/O still requires runtime staging for atomic publication.
HTML serialization, complete stored-document admission and runtime integration
remain open. Animate is not yet registered or packaged in the product runtime.


Dobe HTML export now runs the native scene/symbol baker inside an isolated checked
evaluation operation. This scopes the actual guided-layer, motion-guide, camera,
armature and variable-stroke paths; it does not substitute flattened movie frames
for interactive timelines. Up to 6,000 frames across reachable timelines may be
baked. Stored metadata, action lists, source scripts, intern tables, paths, paint,
frame content and JSON copies reserve work before allocation. Retained buffer
work is limited to 512 MiB and helper work to 256 million units. These counters
are conservative reservations, not measurements of peak memory or CPU time.
JSON and HTML text each have a 64 MiB cap; JSON less-than escaping happens while
writing into that cap. Small text fragments reuse capacity.

Source scripts compile from a private copy with refreshed caches, so an earlier
cached compilation cannot override edited source text. Embedded PNGs check their
headers and decode in the current operation; embedded WAV/Ogg/MP3 sounds use the
complete native decoder and must match stored format/rate/channel/frame metadata.
The checked operation cannot inherit another document's bitmap cache. Sounds
omitted by the sound=false option are not decoded. These checks do not establish
complete stored-document admission or complete PNG integrity.

The native player, interactive timeline structure and known feature-loss notes
remain intact. Generator metadata identifies Dobe Animate. The response sets
`html_serialization_budget_verified=true` and `browser_fidelity_verified=false`.
Browser canvas pixels, runtime interactions beyond the tested player fixtures,
exhaustive feature-loss reporting and dynamic instance expansion remain separate
qualification requirements. Construction failures preserve destinations; final
filesystem I/O still needs runtime staging for atomic publication. Typed runtime
integration, portable projects and installed Animate remain unfinished.

## Texture source recipe (qualification pending)

`texture.lock.json` and `texture.patch` prepare the separately named
`dobe-texture` executable from TextureCraft v0.6.1. Use `--engine texture` with
its pinned source checkout and a new output folder. The opt-in feature supplies
Dobe CLI help, version and private MCP identity. It refuses editor bridges and
TCP serving before parsing connections. The feature disables automatic GPU
baking and requires explicit CPU path tracing for previews. Linked-material
cooking and opening a material editor are refused inside the engine: a later
managed cross-application job must own those operations and subprocesses.
Upstream default builds, native `.tcraft` files and required notices remain.

The maintained recipe patches eleven source files. Its Dobe-only session retains
imported thumbnail bytes across save/reopen and edits, and clears them for a new
project. A retained thumbnail is source provenance, not a fresh render after an
edit. The runtime must label or explicitly regenerate it. A focused native Rust
test and thirteen real-engine compound-preservation checks cover this behavior;
the rebuilt binary also passes the existing 23 native smoke checks below. Unknown
archive members are refused by the separate compound preflight, not by a claimed
change to the private native reader.

This is a source recipe, not an installed application. A macOS ARM64 release
build and 23 native smoke checks have local evidence: layered creation, analytic
sRGB compositing and packed scalar-map pixels, targeted roughness revisions,
cold reopen, a CPU preview, private MCP identity and workspace-path refusal.
The decoder used for independent pixel verification is not a runtime dependency.
Complete native CI, imported-document admission, the typed durable runtime,
editable portable project packaging, installation and Linux/Cloud behavior remain
unqualified. No Texture runtime capability or installer package has been enabled.
Do not infer complete application availability from its catalog source lock.

The private native CLI retains upstream trusted-local commands. Customer access
must use bounded runtime operations with isolated filesystem roots, native
archive admission, decoded-image budgets, deterministic font policy, warning
checks and publication fencing. These requirements remain implementation work.


## Material source recipe (installed qualification pending)

`material.lock.json` and `material.patch` build the private `dobe-material`
executable from MaterialCraft v0.4.1 using `--engine material`. The opt-in Dobe
feature retains CPU graph cooking, editable SBS/MCraft documents, map and portable
material export, and CPU previews. It refuses standalone MCP, editor connections
and network serving before token lookup. The existing product MCP will own typed,
durable customer operations.

The pinned upstream documents explicitly leave redistribution rights for the
converted `assets/sbs/functions.sbs` bodies unverified. The Dobe feature excludes
that asset at compile time and disables ambient library discovery, including the
environment-variable override. Native primitive/function/pattern operations
remain. The actual `nodes` command enumerates 29 entries, despite the older
upstream documentation's count of 30. Original ceramic-tile and ribbed-metal recipes now build editable graphs from
these primitives. Managed library dependencies remain required work.

Automatic external package and resource loading is disabled. Imported resources
must be embedded; recovered/unsupported imports with warnings and unresolved
package references are refused. Shared-home-folder publication into Texture is
also disabled until a managed cross-application operation owns it. Private `info`
returns the complete serialized native package for preservation checks. These
changes do not establish arbitrary XML/archive admission or bounded graph work.

The macOS ARM64 release build has 46 local native checks across 40 real process
calls: editable creation, analytic six-channel PBR pixels, exact targeted color
revision with five other map files preserved, complete native cold reopening,
CPU preview repeatability, function/pattern sample maps, portable material source
retention, and dependency/library/connection refusals. The 26-file native pack
matches its manifest and thirty-one patched-source digests, links only system
libraries, and declares macOS 12.0 as its load-command minimum. This is structural
pack evidence, not clean-machine compatibility.

The source runtime now exposes typed create/import/inspect/edit/cook/export/preview jobs with
portable initial-source preservation. The Dobe-only evaluate route shares raster
counters across instances, refuses numeric and budget failures without recovery
images, and retains source bytes. Material is included in unsigned dev.45;
dev.44 remains unchanged. The new package qualifies installed Material CLI/MCP
operations and local cancellation/crash recovery on the development Mac.
Map export and CPU preview consume that same bounded cook with explicit output
policies and complete decoding. Managed portable export/import and Texture handoff use the qualified runtime
adapters, preserving exact source and verifying maps with a bounded recook.
The maintained reader now resolves immutable archived packages using stable
member identities. Managed routes omit disk-path aliases and return the complete
package registry for independent runtime comparison. All declared packages,
including unused ones, are checked. Shared evaluation budgets include nested
instances; ambient loading stays disabled. General clean-machine/reboot recovery,
Linux/Cloud and release gates remain open. See the [Material contract](../runtime/MATERIAL.md).


The maintained Material reader also restores custom output labels in the Dobe
feature. A retained counterexample showed the earlier reader silently replacing
a custom title with its identifier. The rebuilt engine preserves that title,
changes no unrelated native fields and passes exact cold member preservation.
The original upstream behavior remains selected when the Dobe feature is off.
Outer graph validation now covers all 29 native node definitions and 25 filter
mappings, but complete parameter/type/reference and whole-job admission remain
prerequisites for public Material runtime operations.

The Dobe Material reader also preserves sibling folder order during collection.
The prior stack traversal reversed sibling graphs and flipped serialized folders
on successive cold saves. A Dobe-only queue fixes the real preservation failure;
non-Dobe builds retain the original traversal. Both the title and folder fixes
remain in the same fourteenth patched source file. Native call/default, alias,
eight-level graph, image-pixel and exact compound-preservation evidence covers
the rebuilt engine; public runtime and external dependency handoff remain open.

The Dobe node feature also normalizes numeric widget values at function getters.
Enum defaults retain their editable choices but evaluate as checked Integer;
Color defaults retain their color editor but evaluate as Float4. Real native
counterexamples showed enum casts failing and equal color/numeric vectors
comparing unequal. The maintained boundary fixes both without rewriting stored
defaults. Independent default/connected call oracles and exact cold preservation
qualify the behavior. All 85 function intrinsics additionally have actual CPU
evaluation examples and operand contracts; this does not establish full numeric
domain safety, user-variable flow or aggregate execution admission.

## Write source package

Use `--engine write` with the pinned WordCraft checkout. The `dobe-write/` pack
contains the separately named CPU document executable, the pinned embedded fonts
and their notices. The default upstream executable remains available in source.
The Dobe entry point rejects standalone MCP, editor bridge and Zotero routes.
Printing and language-store management commands are disabled. The durable product
MCP remains the intended customer endpoint; Write has not yet been integrated
into that runtime or the installed twelve-application development package.

The private CLI can create and revise documents through native commands, retain
editable JSON or DOCX, and export PDF or PNG. Use `--strict` for visual exports:
missing glyphs or pictures must refuse the output rather than silently omit
content. The Dobe font database does not scan host font directories. Embedded
document fonts still require explicit admission by the future runtime. Formats
without page metadata default to A4 independently of the caller's locale;
explicit document dimensions remain authoritative. Cached DATE/TIME field values
are retained on open; field updates require an explicit command. Saves still
record modification time and increment the document revision.

The Dobe document model also supplies the nine character styles named by its
built-in heading links. The pinned upstream template names those links without
defining their targets. The maintained feature adds matching character formatting
and reciprocal links so selecting a linked heading style does not silently fall
back. The original non-Dobe feature configuration is unchanged.

`snapshot FILE` exposes every serialized native document field without a save or
layout pass. It preserves the native serializer's float representation. Its
`sourceState` also reports missing pictures and the presence, format and byte
count of retained source markup. Those states are omitted from native document
JSON. This report is not a complete copy of retained markup, an arbitrary-import
admission check or proof that format conversion is lossless. Keep the original
source bytes. In particular, `inspect` is a summary, DOCX dimensions use twips,
and DOCX comments acquire durable IDs on export. Comparing only text or a render
cannot establish a faithful editable round trip.

`picture FILE` decodes one bounded raster with the document renderer's own
decoder, without opening a document or loading embedded fonts. Its private
stdout packet contains `DOBEPIC1`, a little-endian u32 header length, a JSON
header and RGBA8 pixels. The independent runtime decoder compares dimensions,
source size, alpha and complete pixels. Inputs are limited to 32 MiB, 8192 pixels
per side and 16,777,216 pixels, with a 128 MiB native decoder peak budget. This
diagnostic does not grant document admission or prove original high-depth color
fidelity; the complete source bytes remain authoritative.

Local qualification uses original fixtures with a heading, formatted paragraph,
comment story, four editable table cells and an embedded image. It compares the
complete serialized model after native JSON and DOCX cold reopen, predicts a
precise text revision, checks unchanged original bytes and repeatable strict
raster output, and independently reads/renders the PDF with the maintained MuPDF
engine. It also checks missing-picture diagnostics, retained ODT markup, cached
field updates and failed-output behavior. Run it with the bundled Python/Pillow:

```sh
python3 craft/tests/write_native_check.py \
  --engine /path/to/dobe-write/bin/dobe-write \
  --pdf-engine /path/to/dobe-pdf/bin/dobe-pdf \
  --output /path/to/new-evidence-directory
```

The build excludes personal language-data overrides. Pinned proofing and
hyphenation data have not been admitted or embedded; the upstream proof library
can consult ambient dictionaries. Proofing is therefore unqualified. The private
CLI accepts file paths and a broad native command registry; it is not an
untrusted-document sandbox. Strict admission, resource budgets, supported-format
preservation, typed revision contracts, durable jobs, cancellation/recovery,
portable project ownership and installation qualification remain necessary
before public Write operations are enabled. Full upstream CI, supported-OS,
clean-machine, Linux/Cloud and production release qualification remain separate
requirements.


## Slides native integration

`slides.lock.json` pins DeckCraft 0.18.1 at
`7cc73ab1895ed2e30c8afbcada20c70b9ea0a440`, Rust 1.100.0, the unchanged Cargo lock
and a maintained `dobe-slides` CLI target. The upstream CLI and its optional MCP
remain available under their existing default feature; the Dobe build excludes
that dependency and provides no app bridge, MCP listener or arbitrary command
route. The product MCP belongs to the durable runtime and is not integrated for
Slides yet.

The required font input is craft-fonts
`37827adc41fd165f9a9234ac40f94dbad353aa69`, the exact revision selected by the pinned
upstream CI/release configuration. The older shared font pin lacks its Latin
manifest and correctly fails the required Inter gate. The build retains that gate;
it does not substitute fonts or weaken the required catalog to obtain a binary.
The Dobe feature uses an empty system-font directory list and disables automatic
system fallback. Owned embedded fonts remain a separate admission requirement.

Private commands are `new OUTPUT`, `snapshot INPUT`, `encode MODEL_JSON OUTPUT`,
`render INPUT OUTPUT SLIDE_INDEX SCALE`, and
`convert INPUT OUTPUT FORMAT`, where format is explicitly `deckcraft`, `pptx` or
`pdf`. Outputs require fresh paths. They operate on controlled local inputs and
are not public source admission. Source-level read and render budgets supplement,
but do not replace, process isolation and preflight before native opening.

The snapshot includes the complete serialized presentation and exact media bytes
as canonical `dataHex` fields. Upstream serde deliberately skips media payloads;
the maintained observation explicitly includes and restores them. Requested-family
availability is reported separately. PNG and PDF refuse unavailable requested
families, but this is not actual shaped-glyph identity, complete font fallback
qualification or source-format fidelity. Native repair/default insertion, package
semantics, opaque payloads and rendered clipping require independent runtime checks.

`craft/tests/slides_native_check.py` exercises the real binary: creation, complete
cold model comparison, exact original PNG sidecar ownership, native model encoding,
precise text revision, two byte-identical cold PNG renders, PDF output, editable
PPTX slide XML, and refusal of unsafe command routes, overwrites and invalid render
requests. It does not claim full PPTX round-trip equivalence, independently validated
PDF, installed runtime or production quality. The visual fixture is a simple title
and subtitle, not a product design approval.

Build with `--engine slides --source /path/to/deckcraft --fonts /path/to/craft-fonts`
and the other common arguments above. Slides remains outside the thirteen-engine
dev.47 installed candidate until its durable operations, admission, editable project
ownership, delivery and recovery are implemented and qualified. CAD, Sheets,
Inspect, remaining application fidelity, billing, Linux/Cloud and external release
gates remain required for the complete seventeen-application software.


Slides build 3 corrects private native format dispatch for compressed or reordered
MIME members. It reads and bounds the actual ZIP MIME entry instead of depending
on a plaintext marker near the file start. The source inspector independently
reconstructs full media and chart payload ownership; see
[Slides source ownership](../runtime/SLIDES.md). This does not register public
runtime operations or qualify complete source/rendered fidelity.

## CAD native transport

`--engine cad` builds `dobe-cad` from the maintained CAD source lock and local font
checkout. Its private file-oriented commands preserve the full native drawing
model, including previously omitted paper/block entities and foreign source data.
System font and filesystem SHX discovery are disabled. The source build is not
public runtime or installed qualification. See [CAD.md](../runtime/CAD.md) for the
controlled evidence, DXF round-trip differences and remaining CAD requirements.

## Sheets source package

Use `--engine sheets` with the pinned GridCraft checkout. `sheets.lock.json`
binds the complete source patch, unchanged Cargo.lock and Rust toolchain. The
private `dobe-sheets` executable creates, validates, edits and recalculates
complete native Workbook JSON, then exports active-sheet values as CSV or a
styled HTML preview. It does not dispatch the upstream editor, MCP server,
macro/Python runner, external-link resolver or arbitrary command interpreter.

The initial `cells-and-formulas-v1` profile admits bounded multi-sheet scalar
cells, a documented formula subset and bold/italic/numeric styles. Unsupported
state, unknown fields, implicit defaults, malformed sparse storage and stale
formula caches at export fail explicitly. Recalculation uses the native engine
and verifies that only cached formula results changed. Save/reopen checks the
complete emitted native model; no XLSX or broader Office compatibility is claimed.
See the maintained source document `docs/dobe-private-transport.md` in the patch
for the exact protocol, supported expressions and limits.

Native f32 values are compared through their serialized JSON bytes, avoiding
the precision expansion caused by direct conversion to serde_json::Value.
A separate iterator correction preserves the existing first-three-sheet UI
assertions while satisfying Rust 1.100 Clippy. No assertion is removed.

The bundled font-source notices establish provenance only. The current HTML
preview uses browser font selection; pinned-font raster rendering is not
qualified. The durable adapter, portable project history and installed CLI
qualification are described in `craft/runtime/SHEETS.md` and
`craft/local/README.md`. Linux qualification and the remaining release gates
remain separate work.

## Inspect source package

Use `--engine inspect` with the pinned Craft Anything checkout. The maintained
`inspect.lock.json` binds a seven-file source patch, Rust 1.100.0 and the patched
Cargo.lock. The lock adds only the private application package; all external
dependency versions and checksums remain unchanged. The private executable is
`dobe-inspect`; existing upstream applications and tool defaults are unchanged.

The `static-artifact-v1` profile uses the upstream native, WebAssembly and
JavaScript analyzers. It reads one explicitly authorized regular input and writes
one new JSON artifact:

```sh
dobe-inspect inspect native --owned-or-authorized SHA256 INPUT OUTPUT
```

Replace `native` with `wasm` or `javascript` for those inputs. Native containers
are ELF, PE and Mach-O. The SHA-256 must match the exact supplied bytes. The
transport refuses missing consent, unknown operations/formats, symlink inputs,
nonregular files, changed inputs and existing output paths. Input is capped at
16 MiB, JavaScript at 2 MiB and output at 32 MiB. JavaScript uses a 256-level
nesting threshold and 100,000-token budget; fallback remains explicit.

Reports preserve parser warnings, partial results, validation failures, native
triage inference, source identity and canonical evidence IDs. They mark embedded
target content as untrusted. No input code, dependency, source map or URL is
executed or resolved. Static findings do not establish runtime behavior, safety,
ownership or a complete dependency graph. Input permission is a caller assertion;
the public runtime must additionally enforce project, tenant and filesystem
policy before invoking this private transport.

`craft/tests/inspect_engine_check.py` exercises independently authored ELF/PE,
a locally compiled Mach-O fixture, JavaScript and WebAssembly. It checks native
symbols with the host symbol tool, independently recomputes a canonical evidence
ID, verifies exact cold-repeat output, and checks refusal behavior with network
denial on macOS. This source engine does not yet register public runtime
operations or establish installed, Linux execution or Cloud qualification.
