# Dobe CAD maintained engine

The maintained CAD engine is a source-built, private headless transport based on
CADCraft v0.20.1 at `7526dc62c14e71b3c8d46e73bbf1fa29ef506af1`. The source and
font pins, patch, compiler and unchanged Cargo dependency lock are recorded in
`craft/engines/cad.lock.json`. Building it does not enable CAD in the public runtime
or make it part of an installed Dobe package.

## Source and editable state

The Dobe feature serializes all 29 fields of the native `Drawing`. The transport
includes model-space entities, paper-space entities, block definitions, source
paper geometry, constraints, parameters, foreign DXF records, decoded raster
pixels and session state. Entity stores retain draw order and handles; their
implementation indexes are reconstructed. Duplicate handles within a store and
duplicate compound foreign-record keys are rejected rather than overwritten.
Compound foreign-record keys use ordered pairs because JSON object keys cannot
represent those identities. Raster geometry, byte counts, aggregate bytes and
opacity are checked before rendering.

These changes are feature-gated. Upstream JSON continues to skip its original
session and entity-store fields unless the Dobe feature is selected. The upstream
CLI remains the default build. The private binary excludes the upstream MCP
server and does not run the editor, command scripts, startup LISP, path-resolving
OPEN commands or the DWG bridge. System/personal font discovery and filesystem
SHX lookup are disabled; original stroke glyphs and pinned embedded fonts remain.

## Private commands

```
dobe-cad --version
dobe-cad new metric|imperial OUTPUT
dobe-cad snapshot dxf INPUT OUTPUT
dobe-cad encode INPUT OUTPUT
dobe-cad solve INPUT OUTPUT
dobe-cad panel-solid INPUT REQUEST OUTPUT
dobe-cad panel-obj INPUT HANDLE OUTPUT
dobe-cad convert dxf|svg|pdf INPUT OUTPUT
dobe-cad render INPUT OUTPUT WIDTH HEIGHT
```

`snapshot dxf` calls the DXF reader directly. It does not resolve images or xrefs.
`encode` takes the complete native JSON model, compares the parsed model with its
full serialization, and refuses fields or implicit defaults that would disappear.
Every snapshot cold-deserializes its output and compares the entire native state
before writing. Outputs use exclusive creation. Private file payloads are bounded
at 128 MiB, drawings at 100,000 entities, loaded rasters at 64 MiB and PNG output at
8,192 pixels per side and 16,777,216 pixels total. Public hostile-source admission,
process limits and source ownership still belong in the durable runtime layer;
these transport limits do not replace that work.

## Current evidence and required completion

`craft/tests/cad_native_check.py` runs the real binary with a minimal PATH and an
isolated HOME. An original synthetic DXF provides a line, circle and drafting
label. The check covers full native cold equality, paper/block entity ownership,
source-only paper geometry, foreign data, decoded pixels, a precise endpoint
revision and unchanged unrelated state. Two independent process invocations
produce identical PNG bytes, independently decoded by Pillow. DXF export reopens
with identical controlled entity geometry. PDF and SVG files are generated;
independent PDF fidelity and complete SVG semantics are not yet qualified.

The controlled DXF round trip changes header and layout state. Those differences
are retained as evidence, not accepted as a new source baseline. Complete native
model equality does not establish complete DXF interchange fidelity. DWG is not a
private command and is not qualified.

The metric drawing/panel profile now has public admission and durable CLI/MCP
operations, including explicit migration and local cancellation/crash recovery.
Completion still requires broader source admission, independent interchange/render
checks and broader release qualification. Dev.49 now contains fifteen controlled
app profiles, including the locally installed CAD profile; immutable dev.48 remains
its fourteen-profile predecessor. Sheets, Inspect, broader app fidelity, billing,
Linux/Cloud and the remaining release requirements remain part of the full goal.

The local upstream `cargo xtask ci` run passes its formatting and strict Clippy
steps, then stops at the unchanged `usage::non_unicode_output_names` test. That
test expects a Latin-1 byte in an output filename to work. This Mac filesystem
returns `Illegal byte sequence (os error 92)` for the same byte path in a direct
filesystem probe. The test is identical to the pinned upstream source; it is not
skipped or weakened. Subsequent i18n/assets/layers/WASM steps therefore remain
unrun in that command. The separate private Dobe Clippy check and controlled
native checks pass, but the full upstream gate remains unpassed on this host.

## Native parametric solving

The private `solve INPUT OUTPUT` command evaluates parameters and constraints in
CADCraft's native solver. It returns one JSON report containing the complete
solved `document`, parameter values, dimension targets and measurements, moved
handles and every residual. It refuses duplicate identities or names, invalid
references, unused parameter data on geometric constraints, invalid expressions
including unused user parameters, skipped constraints and changed fixed geometry.
It requires 1–256 constraints and at most 256 user parameters. Each residual must
be within 0.000001 in the native solver's residual units. Measured dimensions must
match their targets within 0.000001 drawing units, or degrees for angular
dimensions. The complete model must survive cold serialization. The report makes no general manufacturing
claim. It does not expose the upstream command interpreter or scripts.

`studio_runtime/cad_parametric.py` supplies the `rectangular_panel_sketch` v1
recipe. It creates four editable lines, eleven geometric/dimensional constraints,
explicit millimetre units, a fixed origin and named width/height parameters.
Dimensions range from 0.1 to 10,000 mm. A precise parameter edit requires the
previous expression and changes only that expression. The native solver then
moves the constrained geometry. Recipe construction and measurement verification
perform no native rendering or solving themselves.

Independent verification checks every endpoint against the requested dimensions,
the fixed origin, closed rectangle, exact constraint inventory and all unrelated
state. This is stronger than trusting a native residual alone: a newly evaluated
Fix residual can be zero after an anchor has moved. The checker also matches the
source parameter literals and reported dimensions to the independently requested
width and height. The recipe reuses configuration and constraints, not prior user
content.

The real-engine check creates a 120 by 80 mm sketch, changes its width to 150 mm,
reopens the complete native result and renders both versions. The largest endpoint
error in the revised case is about 0.00000005532 mm. Separate cases cover a 0.1 by
0.2 mm sketch, a width revision to 10,000 mm and identical reports from two cold
solves. Conflicts, missing references, duplicate identities, shadowed names,
cyclic/divide-by-zero expressions, stale edits and tampered measurement reports
are refused. These cases qualify the stated sketch recipe, not every possible
constraint system. The public metric profile now connects these operations to durable jobs. Broader
source/mesh operations, installation and full release qualification remain required.


## Exact sources and portable revisions

`cad_source.py` retains exact JSON or DXF bytes with their hash. JSON decoding
rejects duplicate keys, invalid Unicode, nonfinite values and excessive nesting.
The structural inventory includes all drawing stores, globally unique entity
handles, the next handle, constraint references, compound foreign records, decoded
raster geometry and pixel hashes. Unknown fields remain owned and are reported as
unqualified. Xref/image paths are passive metadata; inspection never opens them.

The DXF inspector independently reads text and R13 binary wire types, preserving
raw string/codepage bytes, sections, records, tag spans, large integer values and
binary chunks. It refuses numeric repairs, truncated payloads, nonfinite values,
ambiguous section structure and non-whitespace content after EOF. Sources are
limited to 128 MiB, JSON to 32 MiB, DXF to 250,000 tags and complete drawing stores
to 100,000 entities. This is bounded source ownership, not complete independent
DXF semantics or permission to execute the native reader. Native source binding
is verified separately by the observer. Complete codepage/escape interpretation
remains explicit qualification work.

`cad_revision.py` supports optimistic, typed changes using stable entity handles:
line endpoints, circle centre/radius, single-line text, existing layer assignment,
visibility, linetype scale and thickness. Parameter expression edits use a unique
name and the expected expression. Every revision requires the previous source
hash and selected prior values. Full unrelated state, resource bytes and foreign
records remain unchanged. Entity handles resolve model, paper and block owners;
callers cannot provide arbitrary JSON paths. Geometry is stored as native floating
point values. Parameter edits leave geometry unchanged and explicitly require a
subsequent verified native solve; replay does not claim solved dimensions.

`cad_project.py` produces deterministic `.dobecad` archives containing the exact
original, complete baseline, current JSON and typed history. Inspection verifies
member ownership/hashes and replays every revision to the exact current bytes.
History is bounded to 32 revisions, 128 edits and 256 MiB of replayed documents.
JSON baselines must equal original bytes. DXF baselines are explicitly **unbound
candidates**: even a valid package with internally consistent hashes cannot
prove that its candidate came from the DXF source. The receipt-bound native observer must cold-read that original using the verified
binary and compare the complete baseline. Its report belongs to that observation;
the source archive itself continues to declare an unbound candidate. Packages cannot assert verification themselves.
Engine pins record provenance requirements but grant no execution rights.

`craft/tests/cad_project_check.py` checks original text/binary DXF sources, exact
whole-model native equality, rich source/resource ownership, paper/block edits,
parameter edits, multi-revision replay and malformed/stale/tampered inputs. These
modules perform no native execution themselves. The public adapter now connects
the admitted metric drawing/panel profile to durable native CAD jobs. Dev.49 now
passes isolated installed qualification for this profile; full release qualification
remains incomplete.


## Receipt-bound native observation

`cad_binding.py` resolves the fixed engine inside the current runtime's CLI bundle.
It checks the compiled source lock, component uniqueness, distribution/platform,
engine manifest hash and binary size/hash against the bundle receipt. Project
parameters, PATH and environment variables cannot select an executable. This
checks receipt consistency, not a signature. Dev.49 includes the verified CAD pack;
the immutable dev.48 predecessor has no CAD component and remains unavailable
through this binding.

`cad_engine.py` additionally checks the native version and executable identity
before and after each fixed command. Symlink ancestors and changes to the binary
after receipt verification are refused. Execution uses the existing cancellable
process transport, a shared deadline, bounded pipes, CPU limits and a 32 MiB file
limit. The observer is private and is not a hostile-process sandbox or public
CAD admission policy. The caller must exclusively own the attempt directory.

Project observation checks out fixed, hash-verified members into a fresh owned
directory. For DXF, it directly parses the exact original with the verified
binary, compares every native model field with the candidate baseline, then
cold-encodes the result and compares again. It never uses a DXF re-export to
replace the baseline. JSON baselines are already byte-bound to their originals.
The observer cold-encodes the baseline, every intermediate typed revision and
the final model twice. Intermediate states remain checked even when a later edit
restores the original values. Original, baseline, history, resources and current
bytes are checked again after execution. A failure removes only its newly
created checkout and temporary files.

The observation report binds the original, current model, engine pin, binary hash
and every observed revision hash. Native source binding removes the pending
baseline-comparison requirement only from that report. Full interchange
semantics, rendered fidelity, public admission and durable publication remain
unqualified. Unknown fields that native serialization would discard fail; their
presence in an owned archive never grants execution or fidelity approval.

`solve_panel` runs the real native constraint solver, checks the editable panel
recipe's independent endpoints, origin and dimensions, then verifies two complete
cold reopens. It returns solved bytes without modifying the original or publishing
a revision. Merely observing a parameter-expression edit keeps its pending solve
requirement. Typed portable solve/solid history now preserves these results and
requires actual native replay. The public adapter now publishes admitted results
through the existing durable job supervisor.

`craft/tests/cad_engine_check.py` uses a disposable distribution layout and the
real maintained binary. It exercises exact text/binary original binding, every
revision, rich native state, unrelated candidate rejection, receipt/path
refusals, an actual parameter solve and cancellation after observing the live
CAD executable. It checks process reaping and absent process groups. This
evidence does not establish an installed CAD package, durable job recovery,
public hostile-source admission or full release readiness.


## Bounded parametric solids and mesh delivery

Maintained build6 adds native `panel-solid` creation/regeneration and `panel-obj`
delivery. `panel-solid INPUT REQUEST OUTPUT` takes an exact native drawing and a
small JSON request containing `width`, `height`, `depth`, four ordered
`sketch_handles` (bottom, right, top, left), and a nullable `mesh_handle`. Each
dimension is 0.1–10,000 mm. The sketch must use millimetres, have finite solved
constraints and match the width/height parameters and expected closed rectangle
within 0.000001 mm. Global handles must be unique and below the next handle.

Creation allocates one native `PolyfaceMesh` with eight vertices and six outward
quad faces and adds a named editable depth parameter. Regeneration keeps the
selected mesh handle, entity order and unrelated state, and changes only its
geometry and depth expression. Width/height revisions first use the real native
constraint solver. The existing mesh stays unchanged until explicit extrusion
regenerates it from the solved sketch. The extrusion constructs exact requested
corners after checking the solved sketch's tolerance; it does not modify the
sketch to erase its residual. Native cold serialization must preserve every
field. This is a closed polyface solid, not an ACIS/B-rep or general CSG kernel.

`cad_solid.py` predicts the precise model changes and independently checks actual
mesh vertices, bounding dimensions, all six boundary planes, outward face
orientation, opposite paired edges, Euler characteristic, volume and surface
area. Volume/area comparisons use 1e-12 relative tolerance with a 1e-9 absolute
floor in the respective cubic/square millimetre units; this numerical check is
not a manufacturing tolerance claim. The observer compares the entire predicted
drawing and verifies two cold reopens. Solving a sketch inside a solid additionally
proves that the mesh, depth parameter, paper state and other entities remain
unchanged before checking the actual solved sketch independently.

`panel-obj` writes actual native mesh coordinates and quad topology as
geometry-only OBJ. It names the mesh handle and explicitly records millimetres
in its header. The exporter refuses unsupported panel topology/coordinates. An
independent parser rejects unsupported/external records and remeasures the
delivered geometry, then compares it exactly with the native source mesh. OBJ
does not carry the complete CAD model, constraints, paper layouts or parameter
history; retain the editable native model alongside it.

The local solid check creates a 120 × 80 × 12 mm panel, changes width/height with
the native solver, regenerates the same mesh as 150 × 90 × 20 mm and exports it
twice with identical bytes. The revised volume is 270,000 mm³ and surface area
36,600 mm². Small (0.1 × 0.2 × 0.3 mm) and large (10,000 × 9,000 × 8,000 mm)
cases also pass. Invalid dimensions, open/nonplanar sketches, handle collisions,
duplicate parameters, inward/folded/open mesh boundaries, invalid indices,
falsified measurements and unrelated state changes are refused.

A separate headless Blender 5.3.0 Beta process imports the actual revised OBJ.
Its independent mesh reader and BMesh measurements find the same dimensions,
eight vertices, twelve manifold edges, six outward faces, volume and area. A
saved `.blend` and inspection PNG show the delivered solid with visible depth.
Blender is an independent qualification reader here; it does not author the CAD
solid and is not a new dependency of the Dobe CAD package. The native CAD renderer
continues to provide its existing 2D drawing projection.

The maintained source lock changed from build4 to build6. Existing portable
archives retain their prior pin and must not be relabelled automatically; an
explicit qualified migration is provided for the build4-to-build6 transition.
The private solid observer returns native JSON, measured reports and OBJ bytes.
The public adapter now connects admitted results to durable CLI/MCP operations,
recovery and explicit migration. Dev.49 packaging and isolated installed checks
pass for the metric profile; broader admission and release gates remain required.
No B-rep, manufacturing-format, complete interchange or full release claim is made.


## Portable production history and pin migration

`cad_history.py` adds atomic `panel.solid` and `panel.solve` entries alongside
ordinary geometry, text, property and parameter edits. A solid entry owns its
recipe, dimensions and optional existing mesh handle; pure replay predicts only
the permitted geometry/depth/handle changes. A solve entry stores exact selected
line geometry before and after the observed solve, plus its recipe and requested
dimensions. Candidate geometry is independently checked against the known sketch,
fixed origin, source parameters and unchanged unrelated model. Numeric JSON types
also remain exact. Compound operations must occupy their own revision and cannot
compete with primitive edits.

Pure replay never declares that a solver or extrusion ran. It retains a pending
native-replay requirement even when saved geometry lies within the dimension
tolerance. The receipt-bound observer reexecutes the actual native solve or
extrusion from each prior model and requires exact equality with recorded result
bytes. It rejects plausible fabricated endpoints that pass the dimensional
tolerance but differ from actual engine output. Every native operation also
passes independent measurement and cold serialization checks.

Changing parameters keeps both solving and mesh regeneration pending. Actual
solve replay verifies the sketch while leaving the existing mesh unchanged and
pending regeneration. Actual extrusion then verifies the regenerated solid. A
later parameter/geometry edit invalidates earlier final-state claims. Reports
record each actual recipe replay with its predecessor/result hashes; saved
archives cannot provide their own native-verification flags. The original bytes,
baseline and every prior typed revision remain immutable.

Portable format version 2 adds an exact `predecessor.dobecad` archive and a
migration record. The only admitted transition is the maintained build4 lock
`46620256f0d0de9e29a4275df32af29f2809885efa8631243ce4a7ff821d60d9` to build6
`383362c1a5e33c1623563d3c407206d0a3669fc723af644dfebdbe0460835059`, with the same
CADCraft version and upstream revision. Migration retains original/baseline bytes,
current model and the exact history prefix; new operations may append afterward.
The predecessor archive is checked recursively once, with its replay charged to
the same aggregate budget before executing that replay. Nested/invented/reverse
transitions and rewritten predecessor history are refused. The old pin cannot
claim typed panel production operations added by the new maintained build.

The local history check saves, transfers and cold-replays a complete parametric
solid with four revisions and five edits, then obtains byte-identical native OBJ
delivery. It tests false saved solve candidates, changed anchors, unrelated state
loss, stale hashes, competing edits and invalidation after later parameter changes.
The migration check compares actual complete models under both real binaries for
JSON, text DXF, binary DXF, parametric and rich paper/raster/foreign-state cases,
then appends and natively verifies solid production after migration. These are
controlled portable/native qualifications. The public metric profile now includes
durable migration/recovery. Installed release qualification and broader source
admission remain required.


## Public CAD jobs and execution admission

`cad.py` registers nine typed operations on the existing product CLI and MCP
endpoint: `cad.create`, `cad.import`, `cad.inspect`, `cad.edit`, `cad.solve`,
`cad.solid`, `cad.export`, `cad.bundle` and `cad.migrate`. Execution uses the
existing independent supervisor, attempt process group, leases, immutable revision
store and atomic publication. The adapter writes only its disposable attempt;
it does not install applications, submit provider work or select code from PATH.

`cad_admission.py` covers every field of `metric-drawing-panel-v1`. The complete
model must match the source-pinned metric defaults except for explicitly checked
model entities, handle seed, source notes and known panel parameters/constraints.
The bundled `cad_recipe_base.json` is the byte-exact `new metric` output from
maintained build6, SHA-256
`597a1e95c2e7f66eb38740cd82ef6281616c8c68280737100155f82e31209629`.
Its upstream MIT notice ships in `notices/cad-recipe-base-LICENSE-MIT.txt`.
The defaults/configuration are reusable; user content never becomes shared data.

Admission permits up to 2,048 native line, circle and single-line text entities,
or the constrained four-line panel with its optional closed polyface mesh.
Coordinates are bounded native floating values, aggregate source-note/text content
is limited to 100,000 UTF-8 bytes, properties use owned default layers/styles and
all parameter expressions are bounded numeric literals. Unknown fields, external
resources, changed tables/layouts/fonts, unsupported entity kinds and arbitrary
constraint programs are preserved by the broader source layer but refused for
public execution. A typed edit that temporarily exceeds admission cannot hide
behind a later edit restoring the original value: every intermediate model is
checked before the first native version probe. Imported DXF still requires its
own complete wire-semantic admission; it is not exposed as a public import yet.

Creation accepts either a complete admitted `document` or one of these recipes:

```json
{"recipe":"rectangular_panel_sketch","version":1,"width":120,"height":80}
{"recipe":"rectangular_panel_solid","version":1,"width":120,"height":80,"depth":12}
```

The solid recipe retains the initial editable sketch and a native-replayed solid
revision. Imports name a project-owned `asset` and explicit `json` or `dobecad`
format. Existing projects use their immutable source revision and the exact
portable archive `expected_sha256` for edit, solve, solid, export and migration.
`cad.edit` accepts the documented primitive edits; saved callers cannot fabricate
compound native-operation entries through that endpoint.

Parameter edits preserve geometry and leave solving/regeneration pending.
`cad.solve` derives stable recipe selectors from the admitted current model,
runs the actual native solver and stores its exact geometry changes in portable
history. If already solved, it records the actual independent native observation
without inventing a no-op history entry. `cad.solid` additionally takes `depth`,
creates or regenerates the same mesh handle and records native production history.
A separate `cad.export` with `format: "obj"` requires the current sketch, mesh and
parameter dimensions to agree; unsolved parameters or an old mesh refuse delivery.
Every successful delivery contains the editable project as well as the measured
geometry-only OBJ. `cad.bundle` emits `drawing.dobecad` unchanged. Explicit migration
accepts the qualified predecessor archive from either an owned asset or an existing
revision, retaining every original and predecessor byte.

The local runtime check uses separate CLI/MCP clients and real worker/native
processes in a receipt-bearing distribution fixture. It exercises all nine
operations, native line/circle/Unicode-text revision, the full parameter/solve/solid
sequence, actual independently measured OBJ, portable and whole-project transfer,
post-transfer edits, native pin migration, stale inputs, unadmitted intermediate
states, cross-project assets and altered receipts. Rejected jobs publish no partial
revision. Every persisted execution is terminal and its process group is absent.
A separate recovery check stops an observed real native child, cancels one job and
kills another supervisor. It verifies complete group cleanup, no partial head,
controlled lease expiry, no automatic replay and successful explicit retry with
byte-exact originals and complete production history.

The distribution-fixture evidence above is distinct from the installed dev.49
qualification below. Dev.48 remains immutable and contains no CAD engine.
CAD PNG/PDF/SVG/DXF delivery, broader model/resource/font
admission, complete interchange semantics, clean-machine/reboot, Linux/Cloud and
remaining release gates remain open. No ACIS/B-rep, general CSG, manufacturing,
complete CAD fidelity or full release claim follows from this profile.


## Installed CLI qualification

Unsigned candidate `0.1.0-dev.49` contains the maintained CAD build6 and current
runtime alongside the fourteen unchanged earlier engine packs. Its archive has
2,463 manifest entries and 2,464 archived files/symlinks; complete contents, file
modes, symlink targets and all 145 runtime files match their build inputs. No GUI
application, system CAD installation or additional model service is used.

`craft/tests/cad_package_check.py` installs dev.48 then dev.49 into a new isolated
root and uses the installed CLI, one fifteen-tool MCP endpoint and launchd
supervisor. All fifteen bundled profiles report available. All nine CAD operations
pass for the documented metric profile. The check creates a 120 × 80 × 12 mm solid,
changes width/height without modifying geometry, runs the actual solver, regenerates
the same mesh as 150 × 90 × 20 mm and independently verifies native OBJ delivery.
An attempted delivery before solving fails without publishing a revision.

Portable and whole-project transfers retain exact originals, editable geometry
and caller-owned recipe configuration. Explicit migration retains a predecessor
archive byte-identical to the one already observed by the real build4 binary.
Rollback to dev.48 preserves queued unsupported CAD work and existing revisions;
reinstallation completes that same queued job.

The check observes actual installed native encode children during cancellation
and supervisor SIGKILL. Both groups disappear without a partial revision. Natural
lease expiry marks the interrupted job; explicit reconciliation and retry produce
the same OBJ bytes. Fourteen submitted execution jobs finish with twelve successes,
one intentional failed export and one cancellation; the retried job accounts for
fifteen registered process groups, all absent at completion. Whole-project import
also records its own successful, non-executing import job. The isolated service is
uninstalled while projects, versions and evidence remain.

This qualifies the stated installed metric profile on the development Mac. It
does not qualify clean-machine installation, actual reboot, signing/notarization,
Linux/Cloud, broader CAD fidelity or the complete seventeen-app software release.
