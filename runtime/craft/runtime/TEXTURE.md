# Texture development contract

The maintained `dobe-texture` engine builds from the pinned native source. The
source runtime registers eight typed operations: `texture.create`, `texture.import`,
`texture.inspect`, `texture.edit`, `texture.export`, `texture.render` and
`texture.bake` and `texture.material`. The latter requires the maintained
Material engine. Unsigned CLI-only candidate `0.1.0-dev.45` includes both engines
and qualifies the eighth operation on the development Mac through the existing
fifteen-tool product MCP. It contains twelve of the required seventeen applications. Linux,
Cloud, clean-machine, reboot and release-signing qualification remain open.

## Archive admission

`studio_runtime.texture_archive` takes an immutable byte snapshot and returns
its SHA-256 digest and every exact decompressed ZIP member. It does not extract
files, rewrite inputs, parse project semantics, open the engine or authorize a
public operation. Its checks are an initial prerequisite for native import.

The container limits are 256 MiB of input, 256 MiB of total expanded data,
64 MiB per member, 8 MiB for `project.json`, 4,096 members and 2 MiB of central
directory data. File reads refuse final symlinks and non-regular files; the caller
must own and confine ancestor directories. These are development admission
limits, not a claim that every project within them can be rendered safely.

Supported ZIP layouts include stored and raw-deflate members, ordinary and
streaming headers, and bounded ZIP64 member size fields. The native serial writer
uses ZIP64 size sentinels even for small members. Its parallel writer retains
redundant ZIP64 size fields after writing ordinary sizes. Both forms are admitted
only when all size interpretations agree. ZIP64 directory records and extra
fields other than the qualified size/offset fields are refused. A valid archive
using another extra-field convention can therefore require additional
qualification; admission never strips that metadata to make it pass.

The reader checks central and local names, sizes, flags, methods, checksums and
streaming descriptors. Member payloads must cover their region exactly, without
a preamble, overlaps, gaps or ignored trailers. Unsafe names, duplicate names,
directories, devices, encryption, unsupported methods and ambiguous metadata are
refused. Actual decompression is bounded independently of declared sizes and must
consume exactly one complete stream with the stated length and CRC.

## Local evidence

Run the maintained container checks without network access:

```sh
python3 -B craft/tests/texture_archive_check.py
```

Use repeated `--native PATH` arguments to compare real engine archives against an
independent decoder. `--evidence PATH` retains the result. Current local evidence
covers 117 checks, including four engine-produced archives, and 3,000 deterministic
mutations. Accepted mutations agree with Python's independent ZIP decoder;
malformed inputs fail with a controlled error.

A separate real-engine fixture contains a layered project, allocated paint tile,
PNG resource and opaque embedded material package. Two fresh native processes
save and reopen it while preserving every parsed project field and every resource
and paint byte. Nine checks cover this preservation and the maintained process
guard: requesting a linked-material recook reaches the explicit refusal, does not
run the host executable override, creates no native link workspace and publishes
no output. This qualifies the exercised recook path; it is not a general sandbox
or a full native workspace CI result.

An initial container implementation rejected the native serial ZIP64 layout.
The first multi-member fixture then exposed the native parallel writer's redundant
size fields. Both layouts now have positive preservation checks and conflicting
size checks. Historical failed evidence remains preserved.

## Project and pixel preflight

`texture_structure.inspect_json` now checks the bounded native JSON, texture-set
atlas sizes, shared layer/effect ID space, ownership tree, group/instance graph
and expansion cost. It retains the complete parsed project for later native
preservation checks. It reuses the qualified strict JSON decoder to reject
invalid UTF-8, duplicate keys, nonfinite or out-of-range numbers, excessive
nesting and more than 100,000 JSON items. This is not yet a complete semantic
schema for every native effect or resource.

Layer and effect IDs must be unique; map keys must agree with IDs, and `next_id`
must have allocation headroom. Every layer has one owner. Group and instance
edges must resolve without cycles or excessive depth. Memoized graph checks
count repeated instances and include the height of cached subgraphs. Anchors
must reference existing anchor effects. Image, environment and linked-package
resource names are collected for the remaining resource-admission stage.

Current development limits are 16 texture sets, 4,096 layers, 8,192 total IDs,
16 group/render edges in depth, 8,192 pixels per atlas side and 16,777,216 total
atlas texels. Atlas area includes holes between occupied UDIM tiles. Per-tile
resolution overrides follow the native maximum-block rule. Composite storage is
bounded at 268,435,456 component texels including coverage, expanded graphs at
65,536 weighted nodes per set, and aggregate compositing work at 1,073,741,824
weighted component texels. These are conservative admission counters, not
measured RAM consumption, render times or billing units. The process supervisor's
actual memory, storage, CPU and wall-time limits remain necessary.

`texture_pixels.inspect_members` checks sparse paint and masks against their
owning atlas and channel component count. It refuses unknown owners, ambiguous
names, duplicate/out-of-range tile coordinates, invalid headers and mismatched
lengths. Dense baked maps have independent bounded dimensions; maps in one set
must agree on dimensions. Dense values must be finite IEEE-754 `f32` values.
The aggregate pixel-data limit is 128 MiB and 16,384 allocated sparse tiles.
Neither reader changes source bytes or silently drops fields or payloads.

The maintained local checks are:

```sh
python3 -B craft/tests/texture_structure_check.py
```

Current evidence contains 122 checks, including four real native archives.
Eleven separate real-engine checks cover a group, linked instance, paint and mask
effects, an atlas with an empty UDIM tile, dense baked data and cage paint. Fresh
native saves retain every parsed field and every payload byte; a cold save
retains all decompressed bytes, and decoded exports for both occupied UDIM tiles
remain identical. This demonstrates the exercised fixture's preservation, not
full native-import or visual-quality qualification.

## Image resources and native decoder agreement

`texture_images` now validates bounded PNG, JPEG, TGA, TIFF, BMP and WebP
resources with complete Pillow decoding, plus Radiance RGBE and qualified flat
OpenEXR through bounded stream readers. Source bytes and embedded metadata remain
unchanged. Images are limited to 64 MiB encoded, 8,192 pixels per side,
16,777,216 texels per image and 33,554,432 aggregate resource texels. Animated
and multipage images are refused. These limits do not establish process peak
memory; native decoding and compositing still run under the shared supervisor.

Radiance admission covers the `#?RADIANCE` RGBE signature, ordinary scanlines,
old repeats and component RLE with the qualified `-Y +X` orientation. It checks
complete runs, dimensions, metadata bounds and the exact end of the stream.
OpenEXR admission covers one flat RGB/RGBA scanline or single-level tiled part
with half/float channels and uncompressed, RLE, ZIPS or ZIP chunks. Tiles are
limited to 256 pixels per side and 65,536 chunks. Data and display windows are bounded
separately. Offset tables, chunks, channel encodings, predictor reconstruction,
stream lengths and finite samples are checked. Deep, multilevel and multipart layouts,
other compression modes and unqualified channel arrangements remain refused.
These are explicit codec variants, not a promise to read every file carrying
one of these extensions.

The exact `.mcraft` suffix remains an opaque embedded package, matching the
native engine. Admission never decompresses or executes it. Image and linked
package references are tracked separately, so a package cannot satisfy an image
reference even if both roles name the same resource. Missing dependencies and
names the native writer would change are refused.

A successful native open does not prove image decoding succeeded: native
`sync_images` logs decode failures and continues. The new
`check_native_resources` gate therefore requires the private `resource.list`
reply to match every admitted name, byte length and image dimension, including
zero dimensions for opaque packages. Cold reopen must repeat that check and
retain all source fields and bytes before a public revision can be accepted.

```sh
python3 -B craft/tests/texture_images_check.py
```

Earlier local evidence contains 95 image checks, 72 actual native checks across
eight exercised encodings, and three real checks for a mixed image/package
project. Native color exports match independently decoded integer images or
analytic linear-to-sRGB values for HDR/EXR. Original resource bytes, every native
member and all decoded cold-export pixels remain unchanged. The existing 122
structure/pixel checks also pass after separating image and package references.

The shared image check now covers 293 independent cases plus supplied native
images, including tile edges, reversed physical chunk order, both channel sample
sizes, all four admitted compression modes, exact byte reconstruction and invalid
RLE/chunk/level/finite-value cases. Material-produced tiled RLE EXR files now pass
this same reader. Additional Texture native probes require resource decoder
agreement and complete cold-save preservation for each supplied file. The latest
probe passes 97 checks across 71 native calls, including 21 additional native
TGA/EXR and independent spatial RGB/RGBA files.

## Compound inventory and imported previews

`texture_document` composes the archive, structure, pixel and image readers into
one complete member inventory. Every member receives a role, byte length and
digest. Unknown members are refused before any native invocation. Primary mesh
references must agree with the stored member or a recognized built-in mesh;
ambiguous primary meshes and cages are refused. Mesh bodies use the qualified
profiles below. Original mesh paths remain inert provenance and must never
be resolved by public operations. Thumbnail pixels count toward the same
aggregate image budget as resources.

`check_preservation` requires the exact member set, every parsed project field
and every non-project payload byte. A typed edit must provide its independently
predicted project. Canonical JSON comparison distinguishes scalar types as well
as values; boolean-to-number changes cannot pass through Python's loose numeric
equality. Embedded changes require a separate explicit contract. Passing this
check does not establish mesh safety, native decoder agreement or visual quality.

The pinned upstream session drops imported thumbnails on save. The maintained
Dobe-only source patch now retains their exact bytes through native save, cold
reopen and edits, and clears them when switching to a new project. These retained
bytes are **imported preview provenance**, not a newly rendered preview of the
edited project. Public operations must label that distinction or explicitly
regenerate a current preview. Default upstream builds are unchanged.

```sh
python3 -B craft/tests/texture_document_check.py
python3 -B craft/tests/texture_document_native_check.py --engine PATH_TO_DOBE_TEXTURE --output NEW_OUTPUT_FOLDER
```

Current local evidence contains 32 compound checks, including five real native
archives; thirteen actual engine checks cover thumbnail retention, complete
field/payload preservation, image/package decoder agreement, a precise roughness
revision, cold reopen, reset and original-byte preservation. Unknown members are
refused before engine invocation. The focused Rust thumbnail regression passes,
as do the existing 23 native CLI/MCP, compositing, map export and CPU preview
checks against the rebuilt binary. This remains development qualification, not
full native CI or installed runtime qualification. Historical thumbnail-loss
evidence is preserved and superseded only for the maintained patched build.

## Embedded mesh profiles

`texture_mesh` checks self-contained OBJ, binary STL and ASCII STL bodies before
native import. The compound reader applies it to primary, high-poly and cage
members. Other native mesh formats remain explicit refusals until their bodies,
dependencies and fidelity are qualified; recognizing an archive member's
extension does not authorize decoding it.

The OBJ profile covers bounded ASCII records, positions, complete vertex colors,
UVs, normals, material/part names, positive and negative indices, triangles and
convex planar polygons. Values are checked in the native `f32` domain. Absent or
mixed attribute indices, nonfinite or excessive values, zero-area geometry,
nonplanar/concave polygons, partial colors and unsupported records are refused.
External material libraries and command-like records are refused, as are ignored
point/line primitives and smoothing directives. Sources are not rewritten into
an accepted profile. Supplied UVs support the qualified UDIM range; allocation
for new projects still needs a resolution-specific runtime budget.

Binary STL requires the exact declared facet length, finite geometry and zero
facet attributes; colored variants and trailing bytes are refused. ASCII STL
requires a complete solid and exact facet grammar rather than the native
reader's permissive word skipping. STL normals are derived from geometry and
UVs are generated by the native importer. Missing OBJ UVs are also reported as
requiring explicit generated-UV acceptance. These reports do not silently
authorize generated attributes in a public operation.

Development limits are 32 MiB per mesh, 64 MiB across embedded meshes, 64 meshes,
100,000 aggregate triangles and 300,000 aggregate expanded vertex bounds. Each
mesh allows 16 materials and 4,096 material/part groups. Primary meshes requiring
automatic UV generation are limited to 10,000 triangles. These are admission
counters, not measured peak memory, CPU time or compute prices. Bake meshes use
the native geometry-only import path and do not generate UVs.

`check_native` compares native triangle/material counts, material names, vertex
bounds and UV-generation policy with admission. `check_native_bake` detects
native recovery that logs and skips a high-poly mesh or cage. Neither check
replaces complete field/payload preservation, warning handling or visual review.

```sh
python3 -B craft/tests/texture_mesh_check.py --output NEW_OUTPUT_FOLDER
python3 -B craft/tests/texture_mesh_check.py --engine PATH_TO_DOBE_TEXTURE --output NEW_NATIVE_OUTPUT_FOLDER
```

Current evidence contains 64 admission/agreement checks and 38 real-engine
checks. Actual OBJ, negative-index OBJ, OBJ with a UDIM hole, binary STL and ASCII
STL retain exact original embedded bytes and complete native fields across cold
save. Exported geometry matches an independent triangle oracle; supplied OBJ
UVs/normals and cold generated attributes agree. Primary/high-poly/cage inventory
and bytes also survive cold reopen. Two initial harness failures are preserved:
`new` has empty stdout, and private CLI mesh export uses `file.exportMesh` rather
than the MCP dispatch name. The corrected route passes. All 32 existing compound
checks pass after integrating mesh admission. Subsequent runtime and installed
qualification are recorded below.

## Layer, source and effect semantics

`texture_layers` now checks the pinned layer/source/effect schema before the
compound reader invokes any native code. It refuses unknown fields, wrong scalar
types, invalid blend modes, opacity/range errors, invalid projections and effects
placed in the wrong content or mask stack. Supported shapes include all 23 native
procedural patterns, six projection variants, 26 filters, seven generator kinds,
levels, comparisons, color selection, material effects, anchors, groups and
instances. Structural graph/reference checks remain the separate prerequisite.

Numeric ranges are explicit development limits. General layer vectors/scalars
are finite and bounded to ±65,504; individual parameters have tighter contracts.
Filter radii are at most 8,192 texels at the native reference resolution. Seeds
must be unsigned 32-bit integers. Colors, parameter lists and stored paths have
bounded lengths; total stored path control points cannot exceed 16,384. Projection
frames and scales must be nondegenerate. The reader retains source values rather
than clamping or repairing them to obtain acceptance.

Sampling admission charges the existing expanded component-texel work by a
conservative maximum source/filter factor, up to 256, and a possible prefix
evaluation for every expanded node when an anchor is read. Anchor cuts add a
further multiplier. This includes repeated instances instead of counting only
stored anchor readers. The current limit is 8,589,934,592 weighted work units;
it is neither a runtime benchmark nor a measured memory or billing estimate.

Linked parameter values and stored path paint remain bounded inert JSON metadata.
Their native fields and bytes can be retained, but this does **not** authorize
linked-material cooking, path replay or external brush/alpha loading. Stored
paths use existing paint pixels during the qualified import/export probes. A
future path-edit operation needs its own brush, camera, dependency and replay
contract. Missing optional native fields can still cause serialization defaults;
complete cold-field preservation remains mandatory after schema admission.

```sh
python3 -B craft/tests/texture_layers_check.py --output NEW_OUTPUT_FOLDER
python3 -B craft/tests/texture_layers_check.py --engine PATH_TO_DOBE_TEXTURE --output NEW_NATIVE_OUTPUT_FOLDER
```

Current evidence contains 92 layer admission checks and 217 actual native checks
across 71 documents. Every exercised document retains complete native fields and
payloads through cold save, reproduces identical decoded cold-export pixels and
leaves its input unchanged. Independent analytic color checks cover uniform fill,
inversion and an anchor reader; a procedural checker produces spatial variation.
These are executable preservation and selected pixel oracles, not a claim of
human visual approval for every effect. The compound regression passes 43 checks
including sixteen earlier native archives with images, meshes, paint, masks,
groups, linked metadata and thumbnails. Initial harness failures and their exact
fixtures remain preserved; the corrected runs pass.

## Project settings, recovery and bake planning

`texture_project` validates root metadata, texture-set metadata, display settings,
saved cameras and the complete pinned bake-setting tree. It refuses unknown
fields, invalid enums/types, malformed parameterless maps, reversed ray distances,
invalid manual curvature ranges and duplicate texture-set material indices.
Embedded primary meshes also bound material references before native invocation.
The environment must be a known built-in or an admitted embedded resource.

Pinned defaults match the actual native writer. Missing defaulted fields are
reported separately and are never written into source bytes by admission. This
matters because schema-compatible omission can still change fields on native
save. The cold preservation check must accept only a separately predicted
conversion or retain every original field. Schema admission alone remains
insufficient to publish a native revision.

Saved bake settings are inert: a large configured bake can be imported without
authorizing that bake. The separate `bake_budget` planner bounds requested output
dimensions, float payload bytes, supersamples and nominal ray work. It includes
holes and excluded cells in the allocation, supports rectangular bake maps, and
squares the per-axis antialiasing factor. An all-disabled selection cannot create
a job, and a custom cage must be admitted before planning its use.

Current execution limits are 128 MiB of new baked payloads, 16,777,216 supersamples
and 536,870,912 nominal ray-work units, plus the existing atlas dimension limits.
Map headers count toward payload bytes. Ray-work counters are planning estimates,
not guarantees about traversal cost, peak RAM, duration or provider charges; the
shared process supervisor remains required. The planner never starts a bake.

```sh
python3 -B craft/tests/texture_project_check.py --output NEW_OUTPUT_FOLDER
python3 -B craft/tests/texture_project_check.py --engine PATH_TO_DOBE_TEXTURE --output NEW_NATIVE_OUTPUT_FOLDER
```

Current evidence contains 50 schema/planning checks and fourteen actual native
checks. Display, depth-of-field, saved camera and bake settings survive native
cold save; decoded 64×64 CPU preview pixels remain identical. A real 16×16 CPU
normal/AO bake produces exactly 4,144 planned payload bytes with analytic flat-plane
normal and AO values, retains every baked float on cold reopen, and leaves its
input unchanged. This small fixture is not a cinematic-production benchmark.

A deliberate malformed ray-distribution fixture demonstrates native recovery:
the private batch command succeeds while replacing the invalid enum with its
default. Compound admission refuses that same input before launching the engine;
both the original malformed input and the recovered output are retained as
evidence. The compound regression passes 114 checks including 87 earlier native
archives. These schema tests alone do not establish runtime or installed qualification.

## Durable import, inspection and map export

`texture.import` accepts an imported native asset ID and no source revision:

```json
{"asset": "IMPORTED_ASSET_ID", "accept_generated_uvs": false}
```

`texture.inspect` and `texture.export` require a source revision from the same
Texture project. Their only optional parameter is `accept_generated_uvs`, which
defaults to false. Meshes without UVs require explicit acceptance on each native
open. Missing defaulted project settings require an explicit conversion that is
not yet exposed; this adapter refuses them before launching the native engine.
No generic command, path, preset file, executable or output directory is accepted.

Preparation snapshots the source into an owned temporary directory, compares
native geometry, bake-mesh and decoded-resource inventories, saves and reopens in
fresh engine processes, and requires complete field and embedded-byte preservation.
UV diagnostics are retained in the inspection report. These checks detect the
qualified recovery cases; they are not a claim to expose every native session log.
Only a fully prepared result is returned for the worker's fenced publication.
The transport inherits the registered attempt process group, wall/CPU/file limits
and bounded output pipes. It launches neither an editor nor a network listener.

Every revision carries `native/document.tcraft`, the exact original
`native/source.tcraft`, stable object IDs in `native/objects.json`, and
`exports/inspection.json`. The original imported source stays unchanged across
inspection and export revisions. An embedded thumbnail is explicitly labeled as
imported source provenance; it is not advertised as a newly rendered preview.

`texture.export` writes the fixed Document channels + Normal + AO preset as
8-bit PNG maps with no padding. This is an explicit integer export; floating-point
native channels remain editable in the retained project. Native output planning
must have no warnings, unsafe names or case-insensitive collisions before any
maps are written. The adapter bounds the plan to 256 files, 33,554,432 conservatively
counted texels and 128 MiB of encoded output. UDIM holes count toward allocation;
each exported tile must match its declared resolution. A separate cold export
must reproduce every encoded file and decoded RGBA pixel hash. These are selected
format and preservation guarantees, not visual approval or universal export fidelity.

The maintained local workflow check passes 37 checks, including ordinary and
mixed-resolution UDIMs, OBJ/STL geometry, baked maps, paint, image resources,
linked package retention, source thumbnails, an independent BaseColor oracle,
pre-execution refusals and failed-publication fences. Five durable jobs exercise
import, inspection, map export, portable bundle reopening and invalid import
through fresh product MCP clients; all fifteen existing tools remain unchanged.

The separate recovery check confirms actual live `dobe-texture` children share
their registered attempt groups. Running-job cancellation publishes no revision.
Killing the supervisor terminates its orphan attempt and native child; after
controlled local lease expiry, reconciliation records `interrupted` without
replay. Explicit retry succeeds as attempt two. This does not qualify a real
reboot, clean-machine installation or hosted tenant isolation.

```sh
python3 -B craft/tests/texture_workflow_check.py --engine /path/to/dobe-texture \
  --fixtures /path/to/retained-native-evidence --output /path/to/new-evidence
python3 -B craft/tests/texture_recovery_check.py --engine /path/to/dobe-texture \
  --source /path/to/uniform-plane.tcraft --output /path/to/new-recovery-evidence
```

The workflow harness requires the named earlier native fixtures and fails if
they are absent. It never downloads them or silently skips qualification.

## Remaining admission and runtime requirements

Qualify explicit default conversion, image-resource authoring and broader export
choices. Keep remaining mesh formats and dependencies explicit in the qualification
backlog. The individual admission modules remain prerequisites, not authorization
to open an arbitrary native document. Unknown native fields, ignored members or
recovered settings must not silently disappear during import or revision.

Customer access remains through CLI or MCP. Native commands are private
implementation details. Linked-material cooking requires a separately managed
runtime job. Path replay and new group/mask/effect authoring remain outside the
current typed operations. Linux and Cloud execution, full native CI,
clean-machine installation, reboot and release gates remain open.

Thumbnail byte retention and unknown-member refusal are implemented as above.
New CPU previews are separate artifacts; they do not relabel the retained imported
thumbnail as a current render. Remaining mesh profiles and general visual-fidelity
qualification remain requirements for the full application release.

## Declarative authoring and precise layer revisions

`texture.create` authors a new layered material on a pinned built-in mesh. It
accepts a name, mesh ID, power-of-two resolution from 128 to 8192 (subject to the
aggregate work limits), and 1–128 fill layers in bottom-to-top order. Each layer
has a name and channel sources; optional fields select the texture-set index,
projection, channel blends and visibility. Sources can be uniform linear values
or any of the 23 qualified procedural patterns. All 21 material channels and six
projection types use the pinned native schemas. Geometry comes from the actual
native built-in material inventory. The UDIM plane retains both UV tiles.

```json
{
  "name": "Painted enclosure",
  "mesh": "plane",
  "resolution": 128,
  "layers": [
    {
      "name": "Blue base",
      "sources": {
        "BaseColor": {"Uniform": [0, 0, 1]},
        "Roughness": {"Uniform": [0.25, 0.25, 0.25]}
      }
    },
    {
      "name": "Red finish",
      "sources": {"BaseColor": {"Uniform": [1, 0, 0]}},
      "channels": {"BaseColor": {"mode": "Normal", "opacity": 0.5}}
    }
  ]
}
```

The adapter builds a bounded native document, then uses the real engine to save,
reopen, composite and export it. Complete schemas and work limits apply before
native project execution. Creation does not replay stored paths, cook linked
packages or invoke user commands. New image-resource bindings, arbitrary mesh
creation and new group/mask/effect authoring remain outside this creation contract;
qualified imported projects retain those existing structures.

`texture.edit` requires a source revision and 1–128 compare-and-set edits. Every
edit names a stable layer ID, a property, the exact expected current value and
the requested value. Supported properties are `name`, `visible`, `source`,
`projection` and `blend`; source/blend edits also name a channel. The inspection
report includes the complete current native project for constructing these
preconditions. Duplicate targets, absent properties and stale expected values
are refused. For example:

```json
{
  "edits": [
    {
      "layer": 1,
      "property": "source",
      "channel": "Roughness",
      "expected": {"Uniform": [0.25, 0.25, 0.25]},
      "value": {"Uniform": [0.75, 0.75, 0.75]}
    }
  ]
}
```

The predicted project changes only those slots. Native saves must retain every
unrequested field, JSON scalar type, signed zero and embedded byte. Only authored
float values may serialize to an equivalent native f32; exact bit equivalence is
checked and every changed decimal representation is reported. This exception
never permits default insertion, enum repair, added fields or numeric changes
outside the native f32 value. Import preservation remains strict.

Creation and edits also export document maps and verify them after cold reopen.
Edits independently prepare the source and preserve map bytes/pixels outside the
conservatively affected texture sets. Instances and anchor readers widen that
dependency set; the report does not claim independent maps where it cannot prove
them. Name-only revisions preserve every map. The original source and creation
recipe remain in subsequent revisions, alongside the latest edit recipe.

The authoring check passes 52 checks. Actual native evidence covers ten built-in
mesh shapes, all 21 material channels, all six projections, procedural variation, all five revision
properties and mixed-precision input. Independent pixel oracles establish the
blue/red linear composite, a roughness-only change preserving every other map,
an opaque green revision and restoration of the blue layer after hiding it.
Separate crate materials retain ten untouched map files. Four durable jobs cover
fresh-MCP creation/edit, a failed stale precondition with unchanged project head,
and portable native reopening. Installed distribution qualification follows below.

```sh
python3 -B craft/tests/texture_authoring_check.py --engine /path/to/dobe-texture \
  --output /path/to/new-authoring-evidence
```

## Bounded CPU preview and mesh-map baking

`texture.render` requires a source revision and an explicit `render` object:

```json
{"render": {"width": 64, "height": 64, "samples": 2, "bounces": 2}}
```

Each dimension is 16–4096 pixels, with at most 4,194,304 pixels, 256 samples,
32 bounces and 268,435,456 pixel-sample-bounce work units. Optional yaw and pitch
are bounded finite degrees. An optional camera name must uniquely identify a
saved native camera. Execution explicitly selects CPU; users cannot select a GPU,
command, executable or output path. Original and cold-reopened documents must
produce identical encoded PNG bytes and decoded RGBA pixels. The new preview is
published separately from the preserved editable native document and thumbnail.

`texture.bake` requires a source revision and explicit settings, for example:

```json
{"bake": {"texture_sets": [0], "resolution": 16,
          "maps": ["normal", "ambientOcclusion"], "rays": 1,
          "use_low_as_high": true, "antialiasing": 1}}
```

Selections must name existing distinct texture sets. Resolution is a power of
two from 16 to 8192, rays are 1–256, and antialiasing is 1, 2, 4 or 8 samples per
axis. All ten pinned mesh-map kinds are supported. Selecting high-poly geometry
requires an admitted embedded high-poly mesh; no silent low-poly fallback is
allowed. The existing bake planner applies before native execution, and retained
plus requested pixel payloads must fit the aggregate 128 MiB limit. The planner's
`execution_authorized: false` describes planning alone; the typed adapter performs
execution and verifies the explicit CPU result separately.

The adapter predicts every setting and baked-member change. It then requires
exact preservation of every unrequested native field and embedded payload.
Partial rebakes at unchanged dimensions retain unrequested maps. Resizing requires
selecting every existing map; resizing retained excluded tiles is explicitly
unqualified. Excluded tile bytes must remain unchanged, or match the native
neutral value when newly allocated. Repeated execution from the same configured
source and a subsequent cold save must retain all fields and finite float data.
Original source bytes and creation recipes remain in later revisions.

The compute check passes 46 checks and four durable jobs. Evidence includes an
analytic plane normal/AO bake, partial rebakes, all ten map kinds, multiple texture
sets, UDIMs, excluded tiles, admitted high-poly/cage geometry, saved cameras,
portable reopening and refusal before engine launch. The 16×16 normal/AO fixture
produces 4,144 bytes from 256 supersamples and 512 nominal ray-work units. Reports
record two actual native command wall times. Neither these small timings nor
admission counters establish production compute prices or cinematic quality.

Installed dev.44 qualification exercises all seven operations through fresh MCP
clients, portable source reopening and twelve durable jobs. Ten jobs succeed;
explicit cancellation and supervisor death publish no result. Both observed
native process groups disappear. Recovery waits for actual lease expiry, records
interruption without replay and reconciles the abandoned attempt explicitly.
Rollback to dev.43 leaves an unsupported Texture request queued; reinstalling
dev.44 finishes that same request. The isolated qualification service is removed
while all evidence and projects remain. This is unsigned development-Mac evidence,
not clean-machine, reboot, Linux, Cloud or full visual-fidelity approval.

```sh
python3 -B craft/tests/texture_compute_check.py --engine /path/to/dobe-texture \
  --fixtures /path/to/retained-native-evidence --output /path/to/new-compute-evidence
python3 -B craft/tests/texture_package_check.py --package /path/to/dev-44/DobeCLI \
  --previous /path/to/dev-43/DobeCLI --output /path/to/new-installed-evidence
```


## Managed Material handoff

`texture.material` admits a project-owned version-2 portable Material bundle,
verifies its maps through a fresh bounded Material cook, and adds or replaces a
linked fill in an existing Texture revision. Exact source and bundle bytes remain
portable. The operation preserves unrelated native fields and resources, verifies
native cold reopening, and exports maps through the existing Texture workflow.
See [the complete handoff contract](MATERIAL.md#managed-portable-materials-and-texture-handoff)
for request fields, signed height conversion, channel and metadata projection,
source preconditions and recovery evidence. This typed conversion does not call
the native legacy version-1 portable reader or enable ambient linked cooking.
Installed dev.44 remains unchanged with its seven Texture operations. The new
dev.45 package qualifies this eighth operation with an archived Material
dependency, bounded map verification, exact editable source embedding and
original Texture preservation. Its broader installed lifecycle evidence is
recorded in [MATERIAL.md](MATERIAL.md#installed-development-package-dev45).
