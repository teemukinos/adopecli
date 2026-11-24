# Interface development contract

The maintained `dobe-interface` engine builds and passes native document probes.
The runtime registers typed creation, native import, inspection and edits through
the shared durable job pipeline. Unsigned development distribution `0.1.0-dev.42`
contains nine maintained applications, including Interface. These operations do not establish a complete Interface app
or the complete seventeen-application Local/Cloud release.

## Operations and artifacts

- `interface.create` accepts the title and node list described below.
- `interface.import` accepts an imported native asset ID as `asset`.
- `interface.inspect` takes a source revision and preserves its native document.
- `interface.edit` takes a source revision and an ordered `edits` list.

All four accept optional `previews`, a list of up to 64 unique node mapping names,
and `font_fallbacks`, explicit `[requested family, requested style, actual family,
actual style]` pairs. Omitted previews select page roots in paint order; an empty
list requests native/text inspection without raster previews. The returned
mapping gives stable usable names for imported duplicate or unsuitable names.

Artifacts include `native/document.figcraft`, `native/objects.json`,
`exports/inspection.json`, selected PNG previews and retained imported assets.
Every native field and embedded asset hash must survive import, inspection and a
fresh engine reopen. Cold diagnostic reports and decoded preview pixels must
match. Untouched source bytes remain unchanged. Unknown native fields silently
dropped by the upstream parser cause refusal before a revision is published.

Creation and edits refuse missing glyphs, unavailable or unapproved fallback fonts,
truncation and other failed shaping checks. Import and inspection can preserve a
document with shaping issues and report those issues without approving its design.
Clipping and visual approval remain explicitly false for every operation. Storing
an immutable inspected revision is not a claim that its design is ready to ship.
Selected nested previews export that subtree, without its ancestors' clipping or
opacity; the inspection report states this scope.

Local source-runtime evidence covers MCP submission after client exit, idempotent
submission, separate worker processes, creation, inspection, native asset import,
portable export/import and cold reopen, failed inspection preserving the project
head, missing-glyph creation refusal and cancellation before publication.

Installed development-Mac evidence also covers the shared fifteen-tool MCP,
component text/fill revisions, exact untouched root pixels, native and portable
imports, and retained revision hashes. Rollback to dev.41 keeps an unsupported
Interface job queued; reinstalling dev.42 completes it. Running cancellation
removes the native process group. A real supervisor crash removes the orphan
engine, leaves the job interrupted, and permits explicit reconciliation without
publishing a result. A restarted service completes a later precise move revision.
The fixture service is uninstalled after qualification. Clean-machine, reboot,
Linux and Cloud execution remain unqualified.

## Precise revisions

Edits use unique node mapping names and explicit actions:

- `replace_text`: `expected` is the complete current plain text; `text` is its
  replacement. Styled runs and paragraph list metadata require a separate range
  contract and are refused by this whole-text operation.
- `fill`: `expected` and `color` are the current and replacement `#rrggbb` values.
  The target must have one ordinary opaque solid paint. Bound styles, variables
  and character-level paints require separate qualification.
- `move`: `dx` and `dy` move the layer origin in its parent frame. Flow children
  must be repositioned through layout settings; group-relative movement is not
  yet qualified by this operation.

The contract predicts component propagation through native source links and
preserves existing overrides. Restoring an instance value to its main component's
value clears the corresponding override, so later main edits can propagate again.
Moving a main component does not move independently placed instances. Locked
targets and locked ancestors are refused.

Every saved field, node ID, asset hash and document metadata value must match the
expected revision. Text changes may remeasure text and reflow dependent auto
layout. Only eligible dimensions and translations within that dependency scope
can change, and each change is recorded in the inspection report. Fixed dimensions,
rotations, unrelated content and unrelated geometry stay protected. Absolute moves
preserve dimensions and child-local geometry. Previews of untargeted page roots
must retain their exact decoded pixels, independently of the requested delivery
preview list. Final shaping and cold reopen checks run before publication.

A failed later edit in a batch leaves the source native file and project head
unchanged. Successful batches remain separate immutable runtime revisions.
Thirty-one contract cases and twenty real adapter cases pass, including component
propagation, instance override restoration, independently placed instances,
absolute moves, rejected field/asset loss and partial-batch failure. A real MCP
submission also publishes and reopens an edited revision through a separate worker.

## Typed scene authoring

`interface_scene.py` now creates native scenes from a closed, bounded request.
It supports frames, components, instances, text, rectangles, ellipses and embedded
PNG/JPEG artwork. A request contains a title and an ordered `nodes` list. Each
node has a unique name, type, parent name when nested, x/y coordinates and width
and height. Parents and referenced components must appear earlier in the list.
No caller-supplied command, script or filesystem path is accepted in this request.

Frame and component options include horizontal/vertical auto layout, gap, uniform
padding, alignment, fixed/hug sizing, clipping and corner radius. Text requires
an explicit bundled family, style and size, with fixed, height or content resizing.
Artwork uses imported asset identifiers and cover/contain fitting. Instances
retain their native component links, editable children and fixed requested size.

Admission bounds both the authored list and its expanded component copies.
Recursive components, excessive depth, malformed properties and unsupported
fields fail before authoring. Artwork and exact font availability are checked
before resetting the native session. Output must be a new file within the
attempt directory; an existing output or source asset cannot be overwritten.

Saved native readback checks names, types, parents, paint order, fixed geometry,
typography, fills, artwork hashes, clipping, layout configuration and instance
content/source links. Native derived layout geometry remains distinct from fixed
requested dimensions. Explicit titles, including `Untitled`, survive native
Save As filename behavior. Source asset bytes remain unchanged.

Fifty-six local cases pass against the maintained binary. They include all seven
node types, nested instances, actual derived layout coordinates, editable component
propagation, eight preview exports, complete cold-save equality, identical cold
preview pixels, invalid input, expanded/deep graph limits, readback contradictions
and refusal without resetting an existing session. The authoring helper now feeds
`interface.create`; its checks alone do not approve clipping or visual quality.

## Native admission

`interface_document.py` reads native `.figcraft` format version 1 without
extracting or rewriting files. It checks ZIP paths, duplicates, entry types,
compression, sizes and CRCs, then parses JSON with duplicate-key, Unicode,
number, depth and node-count limits. The archive is limited to 128 MiB, JSON to
8 MiB and each raster entry to 32 MiB.

The document contract admits at most 64 pages and 2,048 nodes, with consistent
parent/child identities and no detached nodes or recursive component dependencies.
Tree depth, transforms, dimensions and aggregate rectangular pixel bounds are
bounded. Text has a 1 MiB aggregate budget. Native typography supplies explicit
family, style and size. This is structural admission, not complete rendering
resource qualification.

PNG/JPEG artwork is embedded under its SHA-256 key. Its decoded dimensions must
match the native image index, and image paints must reference admitted artwork.
Decoded raster pixels have an aggregate budget. Unknown archive entries,
history, branches, linked/published libraries and repeating pattern paints need
separate qualification and are refused rather than silently discarded.

The native parser can ignore unknown JSON fields without reporting a repair.
`require_state` therefore compares the complete expected native document and
embedded artwork after saving. A clean native open alone does not prove
preservation. Typed revision edits must supply the expected changes and
perform this comparison before publishing a revision.

## Private transport

`interface_engine.py` starts the maintained binary with a private configuration
directory and explicit read/write roots, checks its exact MCP identity and bounds
response frames. Native warnings, repairs, stale opens, missing font families
and unavailable styles are refused. Temporary configuration is removed when the
engine closes. Its native command method is private implementation machinery,
not a customer command endpoint.

Font catalog checks establish family/style availability only. The report
explicitly sets `shaped_glyph_coverage_verified` to false. The maintained native
source now includes the Dobe-only `dobe.textDiagnostics` command. It inspects one
text node through the same `layout_node` function used by the renderer. It reports
actual face bytes by SHA-256, collection indices, variable coordinates, glyph
IDs, source character clusters, requested styles, unmapped characters and native
truncation. Version 2 adds each style's selected primary face and coordinates,
font axis limits, glyph coordinate agreement, and ink bounds before node strokes,
effects and ancestor clipping. It does not edit the document or approve publication.

Diagnostic input and output have explicit budgets. A nonzero missing-glyph count,
a missing requested family/style, fallback faces, truncation and unmapped source
characters remain separate observations. Whitespace, bidirectional controls,
ligatures and generated markers cannot be judged by glyph count alone. The
command's `publication_approved` field remains false.

Twenty real native diagnostic cases pass. These include Latin and combining
characters, Japanese and Arabic fallback with actual bundled font hashes, mixed
styles, case expansion, newlines, empty text, a missing Unicode glyph, unavailable
requested fonts, truncation, variable fonts, ignored/clamped axes, the
16,384-character boundary and refusal beyond it.
Complete native state stays unchanged across inspection. The private parser
allows one million JSON items only for this glyph report; native document
admission retains its 200,000-item limit and passes its 59 existing cases.

## Runtime text policy

`interface_text.py` checks native version 2 evidence against a saved text node.
`Engine.inspect_text` also reads current native characters, refusing stale source
text even when its length matches. Requested typography must match the saved
node's styles. Missing requested fonts, missing glyphs, truncation, uncovered
visible characters and inconsistent reports cannot pass shaping qualification.
Cluster coverage is accumulated in linear time, including overlapping clusters.

Font substitutions require explicit requested/actual family and style pairs.
Approval of a substitution does not excuse a missing requested font or an ignored
variation. Axis limits apply to both primary and actual fallback faces, and
shaped coordinates must agree with the requested style. This permits actual
variable-font instances without treating their base face name as the requested
weight. Fifty-five local policy cases pass, including real transport calls,
explicit Arabic/Japanese fallback, variable weights, stale text/typography and
contradictory reports.

The resulting `shaping_verified` value is separate from publication approval.
`clipping_verified` and `publication_approved` remain false. Ink bounds provide
evidence for subsequent clipping checks; they do not yet qualify strokes,
effects, paint visibility, masks, ancestor clipping or the export crop. Complete
native state and artifact preservation still require their own checks.

## Native export resource guard

The upstream renderer can omit an isolated layer when its memory budget is
exhausted, logging a warning while returning a raster. The maintained Dobe
`export_file` path now audits these denials and returns an error before writing
the output. The audit applies a 256 MiB limit to simultaneous isolated layers;
nested scopes cannot raise it or conceal a denial, and unwind cleanup restores
the enclosing scope. This limit excludes the base image and codec allocations.

Dobe raster exports also check the selected output area before allocating layers:
at most 8,192 pixels on either side and 32 million pixels in total. Editable vector
exports retain their own geometry without inheriting that raster-area limit.
Export depth is checked before the bounds walk for raster and vector formats.
These guards cover the production `export_file` route, not every thumbnail or
standalone rendering helper, and do not establish clipping or visual correctness.

Five real MCP cases exercise raster dimensions, pixel area, scale, editable SVG
availability and recovery in the same process. Rejected raster exports write no
file, and a subsequent small export retains its original pixels. The maintained
build also retains its identity and eleven existing native preservation checks.
Seven targeted native tests cover audit nesting, unwind recovery, actual omitted
layers, refusal before file creation, raster allocation bounds and cyclic export
depth. Strict CLI Clippy passes. This is not full native workspace CI.

## Clipping observations

Seven synthetic native cases distinguish shaping from exported visibility. A
rectangular ancestor clip produces the exact expected cropped pixels while the
text shaping report remains unchanged. Exporting that same text as the root
bypasses the ancestor clip. Hidden and fully transparent ancestors remove the
text, and rounded clipping removes ink inside the rectangular frame bounds.
Restoring the properties restores complete native state and pixels; a fresh
process reopens and renders the saved source identically.

Visibility qualification must therefore include the selected export root,
ancestor visibility and opacity, and actual clip geometry. A text-only export or
successful shaping report cannot approve a frame export. These observations do
not yet qualify masks, effects, occlusion, arbitrary transforms or a general
clipping policy. Intentional clipping also needs an explicit project decision.

## Local evidence and remaining work

Admission has 59 checked cases, including real native/portable files and malformed
archives, invalid trees, recursive components, missing or changed artwork,
invalid typography and text/geometry budgets. The ten transport cases exercise
real native open/save/render, complete-state comparison, root refusal, missing
family/style refusal, collaboration refusal, cleanup and silent-field-loss
detection. These checks do not qualify unimplemented runtime operations.

Native probes independently preserve auto layout, main components, instance
overrides, untargeted frame pixels, embedded raster bytes and editable SVG text.
A new process reopens the portable native file while its original directory is
denied. The native input and earlier revisions retain their original bytes.

Native import/inspection has 28 local cases, and the three source runtime adapters
have 15 cases in addition to the durable MCP/worker evidence above.

Remaining work includes clipping policy and additional render-path qualification,
styled range and additional property edit contracts, installed lifecycle qualification and package assembly. Linux,
Cloud, billing and remaining application/release requirements stay in the full
product goal. The customer MCP connection remains `dobe mcp`.
