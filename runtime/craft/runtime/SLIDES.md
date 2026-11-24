# Slides source ownership

Slides is being integrated into the complete seventeen-application Dobe Local/Cloud
software. The maintained private native worker builds from pinned source. The
installed dev.47 candidate still contains thirteen application profiles. The source
runtime now exposes seven Slides operations through the same CLI/MCP, including
independently checked PNG/PDF delivery for an explicit text profile. Installed
Slides qualification and broader rendering remain unfinished.

`slides_source.inspect_bytes(data, kind)` owns exact `json` or `deckcraft` input
bytes and independently reconstructs the native presentation model. It does not
execute the engine, decode pictures or fonts, follow links, extract files or grant
execution permission. Direct PPTX source admission remains required work.

## Exact originals and native members

Source bytes and their SHA-256 remain authoritative. Native ZIP inspection uses
the existing strict archive primitives: complete member ownership, header and CRC
checks, bounded expansion, normalized name collision refusal, no symbolic links,
no escaping paths and no overlapping or unaccounted payload intervals. Limits are
128 MiB source, 256 MiB total archive expansion and 64 MiB per archive member.
The presentation JSON has a separate 32 MiB limit.

A supported native package has the exact DeckCraft MIME value and version-one
manifest with `format`, `version`, `generator` and `presentation`. Every media
entry has one explicit owner. Duplicate media IDs, missing unlinked media and
unowned binary members are refused instead of being silently discarded. Directory
records and all original member bytes remain in the inspection result. The
preservation check compares complete source bytes; equivalent repacking cannot
replace the original container.

The private native snapshot uses `dataHex` for media bytes omitted by upstream
serde. The source inspector reconstructs those fields from exact `media/<id>`
members. Native manifest metadata cannot inject a competing `dataHex` value.
Explicit JSON models must provide bounded, lowercase hexadecimal media bytes.
Media links remain metadata with an explicit external-link policy gate. They are
never fetched by this inspector, and their presence does not authorize fetching.

## Chart payload ownership

The native writer separates opaque chart payloads into `chart-parts/<index>` ZIP
members. The inspector walks the same model owners: slides, main masters, all
layouts, notes master and handout master, including nested groups. Each canonical
member reference must exist and have exactly one owner; inline bytes cannot
compete with a sidecar reference. Reconstructed models restore original payload
bytes and remove the consumed native storage reference, matching native runtime
serialization. Legacy inline byte arrays are retained and checked without coercing
booleans into byte values.

Media and chart payloads share a 16 MiB aggregate budget, with at most 4,096 items
of either class. These payload checks occur after bounded archive/JSON inspection;
they do not replace those parser budgets or future native process limits. Chart
relationships, workbook contents and other embedded semantics remain unqualified.

## Repair detection and remaining semantics

The source layer checks native u32 identities, unique slides/layouts/media and
shape IDs within each owning story. It preserves legitimate ID reuse between
separate stories. Every slide references an existing layout; `nextId` covers all
observed identities. Missing masters, stale identities and native-clamped slide
or notes dimensions are refused. Shapes have an aggregate 100,000-item budget and
groups a depth limit of sixteen. This detects these repair triggers, not every
normalization the native reader can perform.

JSON rejects duplicate keys, invalid Unicode, nonfinite values, oversized integer
tokens, excessive depth and aggregate item count. Finite native binary64 values
remain exact rather than being constrained to another application's binary32
profile. Unknown model fields remain in the predicted model and are reported for
later qualification or refusal; inspection never silently removes them.

Every result has `engine_admission_complete: false`. Complete field/value schemas,
shape/table/text semantics, animation and reference checks, resources/fonts,
opaque content, native full-model comparison, source-format fidelity and rendered
fidelity must be composed before public execution. Native PNG/PDF output is not
proof of complete PPTX or glyph fidelity.

## Native MIME correction and evidence

Source qualification exposed a native dispatcher bug: it searched only the first
200 byte positions for a plaintext MIME marker. A valid package with compressed
or reordered `mimetype` was refused despite owning the complete model. Maintained
Slides build 3 reads that ZIP member with a 128-byte limit and compares its actual
value. The upstream default build retains its previous dispatch behavior. Original
source bytes are not rewritten to accommodate dispatch.

`slides_source_check.py` compares independently reconstructed complete models
against actual native snapshots. Fixtures include exact original PNG bytes,
distinct chart sidecars under a group, a master layout, notes and handout masters,
legacy inline chart bytes, compressed/reordered MIME members, and byte-exact
original preservation. Malformed ownership, IDs, payloads, Unicode, numbers and
archive namespaces are refused. No remote action or native execution occurs
inside the inspector itself.

The next integration work is broader model/resource admission, independent delivery
checks and installed cancellation/recovery. The recipe and initial durable
operations are described below.
CAD, Sheets, Inspect, remaining Write and other application fidelity, Linux/Cloud,
billing and external release requirements remain part of the full goal.

## Exact typed revisions

`slides_revision.revise_bytes` binds an edit batch to the exact original model
SHA-256. All selectors and expectations refer to that original revision. The
supported operations are:

- `text.replace`: an owned plain-text run, nonempty original UTF-8 byte range,
  exact expected substring and replacement text. Disjoint edits on one run apply
  in descending original offset order. Variable-length Unicode replacements do
  not move another edit's reference point. Field, break and equation runs require
  their own operation; this path never overwrites their cached display text.
- `run.properties`: the complete expected native property object, or `null` when
  inherited, and a patch to explicit font families, size, emphasis, spacing,
  baseline, language, proofing properties and bounded text fill. Fill accepts an
  explicit solid RGBA byte color, `{"kind":"none"}` or `null` for inheritance;
  gradients, theme colors, links and other unqualified fills are refused through
  the same color checks used before native execution. Existing unrelated properties remain
  exact. Clearing the final explicit property restores inheritance; no broad style
  replacement or implicit substitution occurs.
- `shape.transform`: the exact expected transform, including `null` for inherited
  placement, and a complete replacement or `null` to restore inheritance. Numeric
  values stay within native unrepaired ranges. Native-default rotation/flip fields
  must be omitted, and floating coordinates are recorded as native binary64 values.
- `slide.properties`: exact expectations for selected `name`, `hidden` and
  `showMasterShapes` fields, plus their requested values.

Selectors enumerate actual model owners: shapes in slides, masters, layouts and
nested groups, shape text, table-cell text and speaker notes. A JSON path to some
other string cannot become an editable run. Batches reject overlapping text spans,
competing operations on one owner, stale expectations and no-op revisions. Requests
are bounded to 128 edits and 1 MiB. Editable text is bounded to 100,000 bodies/runs
and 16 MiB of aggregate UTF-8 text. Original formatting and run boundaries outside
the selected operation remain intact. Resources must have identical ownership
before and after the edit.

These typed predictions do not yet establish complete model semantics or grant
native execution. The existing original source, full predicted model and later
native comparisons remain independent evidence.

## Portable editable projects

`slides_project` creates new version-one `.dobeslides` packages with four fixed
members: `project.json`, `original.json` or `original.deckcraft`, `baseline.json`
and `document.json`. The original container is byte-exact. A JSON baseline equals
the original bytes; a native-package baseline equals the independently reconstructed
complete model. There is no caller-supplied replacement baseline.

The manifest records product/version/source/dependency-lock pins, every payload's
hash and size, and a chained typed revision history. Inspection replays every edit
from the immutable baseline and requires the current model to match byte-for-byte.
Rewriting a payload hash cannot hide a detached current model, changed original
or broken history. Limits are 32 revision records, 128 aggregate edits, 256 MiB
of replayed models, 1 MiB manifest and 128 MiB project archive, in addition to the
source/member limits.

Engine-pin comparison accepts a separately verified installation pin; project
metadata cannot authenticate its own engine. The private receipt-bound observer
described below supplies that pin. The durable adapter described later composes
this with execution admission and the existing worker.
Checkout writes only fixed members into a fresh
owned descendant directory, refuses symlink ancestors and existing destinations,
checks written bytes, and removes only its newly created files on cancellation.
It does not publish a runtime revision.

`slides_project_check.py` qualifies deterministic native/JSON project creation,
variable-length Unicode edits using original offsets, font changes and restored
inheritance, exact geometry/name changes, speaker-note and table-cell revisions,
complete native encode/cold-open comparisons, real PNG output, portable cold
reopening, original resource preservation and cancelled checkout cleanup. Tests
also reject detached payloads with recomputed hashes, broken chains, stale pins,
UTF-8 splits, overlapping/competing edits, cached-field edits and invalid properties.
No installed or public runtime claim follows from these private project checks.

## Receipt-bound native preservation

`slides_binding.resolve()` uses the current runtime's fixed `lib/dobe` layout and
the shared distribution receipt reader. Neither a project, `PATH` nor a resource
environment variable selects the executable. The reader requires the qualified
macOS ARM64 platform, exactly one Slides component, the compiled source-lock hash,
the engine manifest hash and the actual binary hash and size in both receipts.
This checks consistency with the admitted installation; it is not a signature
verifier. Linux remains a separate required qualification.

`slides_engine.Engine` checks the exact source pin and dependency-lock digest,
hashes the bounded regular executable and obtains its real version response.
Each native call checks the executable identity and symlink-free path again.
Calls share a deadline, bounded stdout/stderr, CPU and output-file limits, an owned
working directory and the existing cancellable process transport. Standalone
checks own and reap their process groups; a durable worker may later use the
existing attempt-group context. These controls are not an operating-system sandbox
or complete imported-model/resource admission.

Project verification checks out exact originals and revision history, encodes
the baseline and current models into private temporary native files, independently
reconstructs the resulting containers and compares every model field and resource
byte with the prediction. It then cold-opens the baseline once and the current
model twice in independent native processes. Native-package originals also receive
a direct cold-open comparison with the independent source reconstruction. Unknown
fields discarded by native serde cause failure; the observer never accepts the
engine's normalized model as a replacement prediction. Original files, manifests
and history remain byte-exact. Temporary native files are removed, and a failed
verification removes only its newly created checkout.

Reports distinguish completed native model comparison from outstanding semantics,
resource/font admission, rendering and source-format fidelity. Requested and missing
font inventories are observations, not proof of actual shaped glyph identities.
Successful verification never grants public execution or durable publication.

`slides_engine_check.py` exercises the real maintained engine in an unpublished
distribution-layout fixture. It covers complete revised/native-source preservation,
receipt tampering, fixed executable selection, source-pin mismatch, stale bytes,
unknown-field loss, checkout ownership, changed binaries, shared deadlines and
cancellation after observing the actual native encoder alive with pending output.
Every launched process is reaped and every standalone group is gone. No fake
engine, installed-package qualification, remote action or editor is involved.

## Reusable editable proposal recipe

`slides_recipes.compile_recipe(request)` compiles a versioned
`production_proposal` into the complete editable native model. It creates a cover,
one page per section and delivery specifications with four rows per page. Speaker
notes, titles, paragraphs and each delivery cell have semantic selectors for exact
typed revisions. Every visible element remains native text or a shape. No text is
flattened into an image. Up to 24 sections and 28 deliverables fit the 32-page
structural budget; these counts are not a guarantee that arbitrary text fits.

```json
{
  "recipe": "production_proposal",
  "version": 1,
  "title": "A campaign worth keeping",
  "subtitle": "Direction, scope and editable delivery",
  "label": "Creative proposal",
  "sections": [
    {
      "heading": "One clear idea",
      "paragraphs": ["Explain the creative decision and why it serves the brief."],
      "notes": "Keep review questions and presentation notes with this page."
    }
  ],
  "deliverables": [
    {"asset": "Campaign stills", "source": "Layered image project", "delivery": "PNG"}
  ],
  "controls": {"accent": "#D8E96B"}
}
```

The 960 by 540 point layout uses 48 point margins, bundled Inter and a 20 point
base with a 1.25 type ratio. Paper/ink pages, consistent footers and aligned source
and delivery columns make the proposal readable. An accent control chooses its
contrasting black or white text. Compilation is deterministic and offline. Only
native defaults and layout configuration are reusable; caller content remains in
the caller's result and is never added to a global template or content cache.

The recipe owns the exact request, base hash, native source revision and font source
revision. `slides_recipe_base.json` is the untouched complete default model emitted
by the maintained DeckCraft worker at source revision
`7cc73ab1895ed2e30c8afbcada20c70b9ea0a440`. Its SHA-256 is
`c1abdcef0f3423c8dcc9e82d17b195c1a6377b59bdafb44b8dd973a9b15f0dec`.
Compilation checks this hash before using the defaults. The copyright and MIT
license for those defaults ship in
`studio_runtime/notices/slides-recipe-base-LICENSE-MIT.txt`. The Inter input comes
from pinned craft-fonts revision `37827adc41fd165f9a9234ac40f94dbad353aa69` under
OFL-1.1; the maintained engine pack retains the font notices. The recipe layout and
example content are original. No vendor template, stock image or customer work is
included in the reusable configuration.

Text is retained without truncation or automatic font shrinking. Byte and item
limits bound the request but do not establish visual fit. The compiler exposes text
box geometry and explicitly leaves `text_fit_qualified` and
`engine_admission_complete` false. Actual layout overflow, glyph identity/coverage,
complete model and resource admission, independent delivery fidelity and public
runtime integration remain required work. A recipe is not a general quality
guarantee or permission to send imported models to a native process.

`slides_recipe_check.py` compiles an original five-page example, checks complete
native encoding and cold models, and packages an editable portable project. It
revises one selected paragraph while preserving all other model fields and exact
cover PNG bytes. The example produces native PNG, PDF and PPTX outputs. Independent
PPTX XML inspection verifies every slide's exact editable text inventory and speaker
notes; this is not complete PPTX source fidelity. A PDF signature is observed, with
independent PDF qualification still open. The five representative PNG pages are
visually inspected separately; that evidence does not certify arbitrary inputs.

## Actual placed-text diagnostics

Maintained Slides build 4 adds the private `text-layout INPUT SLIDE_INDEX` command.
It uses the native renderer's placed-text layout, including resolved field values,
font fallback, character attribution, line geometry and saved autofit. The Dobe-only
render feature retains each text body's source shape identity. The default upstream
build remains unchanged. This is a fixed diagnostic command, not an arbitrary
engine-command bridge.

The binary packet begins with `DOBESLY1`, a little-endian u32 JSON-header length,
the UTF-8 header and its owned font bytes. The header records slide dimensions,
shape identities, resolved paragraphs, local-to-slide transforms, inner text boxes,
line extents, native overflow, font scaling, line reduction and glyph runs. Each
run includes actual glyph IDs, positions, paragraph character ranges/cells, selected
face and synthetic-style flags. Each face includes its actual bytes, collection
index and variation coordinates. Private diagnostic budgets are 4,096 text bodies,
100,000 lines, 200,000 glyphs, 4 MiB paragraph text, 64 faces, 32 MiB aggregate font
bytes and 16 MiB header. These output limits do not replace complete model admission
before native parsing and layout.

`slides_text.inspect` checks complete packet ownership, structure, counts, indices,
finite geometry and character attribution. Actual font bytes must match four
source-pinned bundled Inter faces or separately supplied owned font bytes. The
existing independent TrueType inspector verifies font tables, checksums, glyph
bounds, names and units. Collection indices and variable-font coordinates require
separate qualification and are refused by this reader. Built-in font hashes come
from craft-fonts revision `37827adc41fd165f9a9234ac40f94dbad353aa69`; no system font
scan or downloaded replacement is used.

The report identifies native vertical overflow, horizontal line/width overflow,
lines outside the text box or transformed outside the slide, saved automatic text
shrink, synthetic styles and actual missing-glyph IDs. `require_clear` refuses a
report containing any of those issues. The receipt-bound observer exposes this
through `observe_text`, with exact source-byte checks, the existing shared deadline,
bounded pipes and process cleanup. Inspection does not rewrite text or reduce type
to force a pass.

The first diagnostic run found a real recipe defect that visual inspection had
missed: 16 point footer text required 26.88 points of line height, while its box
provided only 25. The section-number box also needed more height. Both boxes now
provide explicit room. All five example PNGs remain byte-identical because the
previous recipe allowed visible overflow; the corrected model now satisfies the
actual text geometry. The original diagnostic report is preserved as evidence.

`slides_text_check.py` verifies all five example pages and 989 observed glyphs,
exact independent source text owners, pinned font identities and identical packets
from separate cold native processes. Real authored fixtures produce vertical and
horizontal overflow, off-slide text, saved shrink and missing glyph zero; each
fails the delivery check. Corrupt packet ownership, counts, names, character
attribution and source bytes are refused. Recipe and receipt/cancellation checks
also pass against the new maintained binary.

These reports deliberately retain `complete_render_coverage: false` and
`independent_shaping_qualified: false`. Placed text excludes chart labels and text
converted to geometry; effects, clipping, transformed ink bounds, inherited-owner
ambiguities and broader source fidelity need separate coverage. An actual glyph
trace is evidence of what this engine selected, not an independent proof that its
shaping is correct. No imported-model admission, public runtime operation, installed
qualification or complete release claim follows from these diagnostics.

## Durable CLI/MCP operations and execution admission

The source runtime exposes seven Slides operations through the existing
`dope_submit_job` tool and `dobe submit` command. They use the same durable jobs,
project-scoped assets, immutable revisions, worker supervision, lease fencing and
atomic publication as the other applications. There is no additional MCP endpoint.
The installed dev.47 artifact is unchanged and does not yet contain these operations.

| Operation | Parameters | Result |
| --- | --- | --- |
| `slides.create` | A versioned recipe request, or `{"document": complete_model}` | New editable presentation with exact original and baseline |
| `slides.import` | `{"asset": project_asset_id, "format": "json"}`; also `deckcraft` or `dobeslides` | Exact admitted source or existing portable history |
| `slides.inspect` | `{}` and a source revision | New verified inspection revision |
| `slides.edit` | `{"expected_sha256": portable_hash, "edits": typed_changes}` and a source revision | Precisely predicted and natively verified editable revision |
| `slides.bundle` | `{}` and a source revision | Verified `.dobeslides` delivery |
| `slides.export` | `{"format": "png", "slides": [3, 1], "scale": 1.25}` or `{"format": "pdf"}` and a source revision | Checked PNG pages or complete PDF with exact editable originals |
| `slides.migrate` | `{"expected_sha256": predecessor_hash}` and a source revision, or add `"asset": owned_asset_id` in a new project | Explicit maintained engine migration preserving the exact predecessor package |

Creation, import and asset migration require a new project; the other operations require a source
revision owned by that project and the DeckCraft engine. Idempotency survives client
exit. Stale hashes, foreign assets, caller-selected executables and arbitrary native
commands are refused. PNG/PDF delivery uses the stricter profile below. PPTX
delivery is not yet a public runtime operation; private examples do not substitute
for that integration.

Before even constructing the native observer, `slides_admission.inspect_project`
checks both the independent baseline and the replayed current model against
`simple-editable-slides-v1`. This is a complete, explicit execution profile, not
general DeckCraft or PPTX admission. Every admitted field has a defined type,
value check or exact source-pinned default comparison. The profile supports:

- One to 32 slides with bounded dimensions, names, visibility, notes and solid
  backgrounds over the exact source-pinned default masters and themes.
- Up to 2,048 native rectangle, rounded rectangle, ellipse, triangle, diamond or
  line shapes, explicit transforms, placeholders, solid fills and plain text.
- Up to 4,096 paragraphs, 8,192 runs and 100,000 Unicode characters, including
  bounded paragraph placement, spacing, emphasis, color and Inter typography.
- Exact native JSON, native containers and portable projects whose full baseline
  and current model satisfy that same profile. Original container bytes and edit
  histories remain unchanged.

Custom masters, unknown fields, media, embedded fonts, charts, tables, custom
geometry, effects, links, actions, animation, cached field runs and unsupported font
families are refused before native execution. The source and portable layers still
preserve broader models; preservation alone does not grant execution permission.
Those broader features remain required integration work. The profile never drops
unsupported fields to make a source pass. Native full-model comparison remains a
second requirement after admission, so normalization or inserted defaults cannot
silently replace the requested state.

The adapter resolves its installed engine receipt, validates exact published source
files, admits the model, obtains complete native preservation evidence and prepares
owned native, recipe and inspection artifacts. Only the existing worker may publish
those artifacts under its live lease. Failed admission, native checks or damaged
receipts publish no partial revision and leave the project head unchanged. Temporary
inputs and native scratch directories never enter the durable artifact inventory.

Recipe creation persists caller-owned content, semantic selectors, text-box geometry
and production provenance in the project. Subsequent edits, inspection and delivery
retain that origin configuration byte-for-byte. Complete project export/import and
portable transfer remain editable in another project. This is project-local reuse,
not sharing customer content between users.

`slides_runtime_check.py` exercises actual CLI and MCP clients that exit before the
worker runs, all seven durable operations, JSON/native/portable imports, exact text
revision, whole-project transfer, stale-edit refusal, foreign-asset rejection and
receipt failure/recovery in a local distribution-layout fixture. A separate adapter
probe prevents native observer construction and verifies unsupported source refusal
still succeeds. Malformed or unsupported model cases exercise the execution
profile directly. The same fixture tests ordered/scaled PNG delivery, independent
PDF verification and atomic refusal of overflow, missing glyphs and absent pages.
Installed service cancellation/recovery and broader rendered delivery remain
separate gates. Capabilities state the admitted profile and separate delivery
profile. Revision reports set `render_qualified` only for successful exports;
`general_admission_complete` and `installed_qualification` remain false.


## Independently checked PNG and PDF delivery

`slides.export` composes exact portable originals, complete native model comparison
and the `explicit-plain-inter-slides-v1` delivery profile. Every visible, nonempty
text owner must have an explicit unrotated, unflipped rectangle and a single text
column. Its complete paragraph inventory must match actual native diagnostics.
Inherited placeholder placement, nonrectangular text and transformed text need
separate qualification. All selected faces must be the exact pinned Inter font
bytes, without synthetic styles or missing glyphs. Native overflow, automatic
shrinking and lines outside text boxes or slides cause failure; the operation
does not truncate text or alter the author's model to make it fit.

PNG accepts an ordered, unique list of one-based slide numbers and a finite scale
from 0.25 through 4. Omitting the list exports every slide in document order. Each
page is rendered twice in independent native processes and must have identical
bytes. Independent PNG decoding verifies complete pixels, color representation
and exact dimensions, including upward rounding of scaled point dimensions. The
limits are 8,192 pixels per side, 16,777,216 pixels per page, 64 million pixels in
aggregate and 128 MiB output bytes. Invalid or missing slide selections fail.

PDF exports the complete presentation. It requires the separately receipt-bound
Dobe PDF engine and permits only font embedding flags compatible with subsetting.
Two cold reader processes independently open the output, compare its complete
reader state, verify every page's dimensions and rotation, and rasterize every
page. The two raster pixel inventories must match. Extracted text must equal the
source's normalized, non-whitespace character inventory on each page. This check
does not establish reading order, independent shaping or pixel equivalence between
PNG and PDF. The PDF has a separate 64 MiB reader budget.

Delivery writes `exports/delivery/slide-NNN.png` or
`exports/delivery/presentation.pdf`, together with `delivery.json` and exact text
diagnostics. The operation verifies the original source again after all output
checks. Temporary native inputs and reader probes are removed before publication.
The existing durable worker publishes the complete revision atomically; failed
exports leave the project head unchanged. Exact native originals and the editable
`.dobeslides` package remain in the same revision.

Reports name the delivery profile and leave general source fidelity, independent
shaping and visual approval false. A successful technical check does not certify
all supported DeckCraft content or approve a design. Direct PPTX import/export,
resources, custom masters, charts, tables and broader render semantics remain
required work for the complete product.


## PPTX package ownership and observed precision changes

`slides_pptx.inspect_bytes` now inventories an exact PPTX source before native
execution. It reuses the bounded ZIP/XML/OPC reader used by Write; the fixed DOCX
entry point retains its previous profile. The inspector keeps the whole original
archive, every decoded member, member hashes, original XML and relationship tables.
It does not extract files, fetch links, create a native model or grant execution
admission. It is not yet a `slides.import` format or a `slides.export` format.

Slide order comes from the presentation's relationship IDs, never filename sorting.
The inspector verifies unique slide IDs and targets, declared dimensions, each
slide's layout, every declared layout's master backlink, master IDs, notes ownership
and each notes part's backlink and declared notes master. It retains editable text
run order and shape identities for subsequent comparison. Both transitional and
strict namespace families are inventoried. Unsupported XML and unreferenced parts
remain owned source information, with unreferenced members listed explicitly.
Passive external web/mail hyperlinks remain metadata and are never fetched.

Malformed ZIP ownership, ambiguous relationship targets, active Office content,
external resource relationships, entity declarations, broken slide/layout/master
ownership and duplicate identities are refused. The limits compose the existing
128 MiB source, 256 MiB archive expansion, 32 MiB aggregate XML and 250,000 XML-node
budgets with 256 slides, 256 masters and 4,096 layouts. These are ownership checks;
complete presentation semantics, inherited styles, resources, fonts, opaque content,
source-to-native comparison and rendered fidelity remain separate requirements.

`slides_pptx_check.py` qualifies the actual five-slide native export, all 49 package
members, 46 relationships and eleven declared layouts. It also checks relationship
ordering, a relocated main part, retained unreferenced XML, strict namespaces,
passive hyperlink inventory and malformed ownership. The shared DOCX reader's
existing source-container suite is rerun after the reader extraction.

A cold native reopen of the current recipe's PPTX exposed 76 model differences.
Most are regenerated identities, populated empty master paragraphs, a default
color map and an inserted notes master. The authored cover title also changes from
48.828125 points to 48.83 points: the maintained writer rounds the run size to an
integer number of hundredths of a point. Four reopened PNGs are byte-identical to
the native source renders; the cover is not. These observations are preserved in
`slides-pptx-probe-1`. They disprove complete byte/model or pixel fidelity for this
conversion. The original recipe and native project remain unchanged. A future PPTX
delivery contract must independently verify expected precision conversions and
inherited semantics and disclose conversion changes; it must not silently replace
the source model with the reopened model or label matching text as full fidelity.


## Numeric conversion reports and percentage-spacing correction

Every durable Slides inspection now includes a `pptx_precision` report bound to
the exact source model and maintained source lock. `slides_precision.inspect`
predicts numeric conversion in the admitted simple-shape/text model before an
export runs. It reports the source path, original value, encoded integer, converted
value, cold-reader value, unit, rounding rule and any clamp. The source model and
portable history are never rewritten. Capabilities expose this report separately
from the still-unqualified public PPTX import/export operations.

The planner covers slide/notes dimensions, shape coordinates and rotation, text
insets and rotation, paragraph margins/indent/tab size and spacing, run/default/end
text sizes, kerning, tracking, baseline and solid-color alpha. Coordinate units are
12,700 per point; rotation uses 60,000 units per degree; text size/spacing uses
hundredths of a point; percentages use 100,000 units per fraction. Nearest rounding
uses ties away from zero, including negative values. Values immediately below a
half step remain below it. Alpha uses exact integer multiplication/division rather
than a floating reciprocal, which would invent tiny changes for opaque colors.

The real native comparison found another conversion defect: the writer retains
percentage spacing through 132, but the earlier reader clamps it to 100. An
exported value of 120 therefore changes despite requiring no rounding; a source
value of 200 is written as 132 and then reduced again to 100. Maintained Slides
build 5 adds a Dobe-only PPTX feature that makes the reader retain the writer's
full range through 132. The upstream default feature behavior is unchanged. The
new runtime source lock binds this correction. The explicit migration below
qualifies the recorded build4-to-build5 transition; other source-lock transitions
require separate qualification rather than silent rebinding.

`slides_precision_check.py` compares predictions against real native encoding,
PPTX XML and cold reopened models. The cases cover the original five-page recipe,
fractional/negative/tie-boundary geometry and typography, percentage clamps and
all 256 source alpha bytes. Independent XML inspection distinguishes written
values from native-reader behavior. The source title still converts from 48.828125
to 48.83 points and is disclosed; the source is not changed to conceal it. The
report does not claim complete semantic projection, imported-format admission,
text-layout preservation or rendered fidelity. Those gates remain required before
public PPTX delivery.


## Explicit maintained engine migration

`slides.migrate` supports the recorded build4-to-build5 source-lock transition.
Ordinary import, inspection and editing still require the exact current engine pin.
Migration is an explicit operation with the predecessor archive's exact SHA-256;
it does not silently rewrite a project's engine metadata. The destination engine
comes from the verified installation, not from caller parameters. Unknown,
reverse, same-engine and nested migrations are refused.

An existing project migrates from its source revision with `expected_sha256`. A
new project may instead supply a project-scoped `asset` containing the old portable
package. Both routes create the same deterministic version-two `.dobeslides`
package. Version two retains `predecessor.dobeslides` byte-for-byte, alongside the
original source, baseline, current model and complete typed history. Its migration
record binds both engine pins, predecessor hash, history boundary and current-model
hash. Subsequent edits extend the old history; they cannot replace its prefix or
change the archived predecessor. Normal new projects still use version one.

Inspection independently replays both histories, checks the declared transition
against the maintained code-owned edge and verifies original/baseline equality.
Nested migration envelopes are refused before recursive replay. Expanded portable
payload remains bounded to 128 MiB, including the retained predecessor; aggregate
replayed models across both envelopes remain bounded to 256 MiB. Large packages
that exceed those limits fail explicitly before publication.

The durable adapter admits the model and compares original, baseline and current
native models with the new receipt-bound engine before publishing any migration.
Existing revision metadata and production provenance remain unchanged. Failed
migration leaves the project head unchanged. The new revision includes a migration
report and `engine_migration_verified`; this is separate from PPTX fidelity or
installed release qualification. Complete project transfer, portable asset transfer,
post-migration edits and normal inspection preserve the archived predecessor.

The runtime qualification uses an actual earlier build4 durable project, rather
than fabricating a legacy receipt. It verifies both migration routes, continued
editing and transfer, stale/unknown pin refusal, migration-envelope tampering,
replay budgets and the immutable original project. Public PPTX import/export,
broader resource semantics, installed cancellation/recovery and complete release
qualification remain required work.


## CLI packaging and recovery qualification

The CLI builder accepts the maintained Slides pack together with the maintained
PDF pack. The dev.48 candidate contains the current runtime and all seven operations;
the earlier dev.47 artifact remains unchanged. Runtime receipts, source defaults,
licenses and the independent PDF reader travel in the same offline distribution.
The fourteen packaged profiles remain a subset of the required seventeen-app suite.

`slides_recovery_check.py` pauses only a confirmed native child in its registered
attempt group, leaving the parent-death watcher running. Cancellation and worker
death must remove the group and preserve the previous project head. After locally
controlled lease expiry, interrupted work must remain stopped until explicit retry.
The recovered revision must pass full native comparison and retain exact originals.
This covers native import, an actual build4 native-origin project migration, PNG
rendering and the independent PDF reader. It does not qualify a machine reboot or
hosted isolation.

The large-page PNG fixture uses a 2,400 by 1,350 point canvas at scale two. Reusing
that fixture for a five-page PDF exceeds the independent PDF reader's declared
image-pixel budget, so the operation correctly refuses publication. Its failed
recovery fixture is preserved. PDF interruption/retry is qualified on the normal
960 by 540 point five-page source that passes delivery admission. The reader's
resource limits remain enforced; no unrequested scaling or limit bypass is added.

The installed check adds launchd startup, minimal PATH, rollback/reinstall,
queued-work preservation, real supervisor death, natural lease expiry and explicit
reconciliation before retry. Its service is removed at completion. General source
fidelity, public PPTX conversion, broader resource/model admission and the full
Local/Cloud release remain open.

## Owned pictures and precise raster revisions

The current source runtime uses `editable-raster-slides-v2`. It extends the text,
shape and notes profile with embedded still PNG/JPEG pictures. The native worker's
`picture INPUT OUTPUT` command writes a bounded diagnostic packet containing the
actual renderer decoder's RGBA8 pixels. It does not open a document editor.
PNG/PDF delivery compares two cold native decodes with independent Pillow output
before rendering. Lossless pixels and alpha must match exactly; JPEG permits at
most three channel levels of difference and a mean error of 0.5. Diagnostics do
not claim color-managed output or artistic approval.

The existing `slides.edit` operation accepts three additional typed edits. Each
request retains its existing exact portable `expected_sha256` and source revision.

- `picture.insert`: `path` identifies a slide, such as `/slides/0`. `expected` is
  the SHA-256 of that slide serialized with `slides_revision.encoded`. `value`
  contains `image` and `transform`. The image contains `name`, `contentType`
  (`image/png` or `image/jpeg`) and canonical lowercase `dataHex`. The transform
  contains explicit `x`, `y`, `w` and `h` in points. Resource and shape identities
  are allocated deterministically from the document's `nextId`.
- `picture.replace`: `path` identifies a picture shape. `expected` contains its
  current `media` identity and the SHA-256 of its encoded bytes as `sha256`.
  `value` is a new image object with the three fields above. Replacement creates
  a new embedded resource and changes only the selected picture's reference.
  Existing resources, other pictures, placement and crop stay unchanged.
- `picture.crop`: `path` identifies a picture shape. `expected` is its current
  crop; `value` contains left, top, right and bottom fractions. Fractions must
  retain a positive source rectangle. The original encoded image stays exact.

Existing `shape.transform` moves or resizes a picture. The admitted profile
requires positive explicit dimensions and axis-aligned placement. The image
stretches into that rectangle after crop; clients can preserve its aspect ratio
by selecting corresponding dimensions. Native picture corrections, artistic
effects, rotation, flips and tiled fills require further qualification.

Admission checks every embedded image, including retained resources. It accepts
at most 128 images and 16 MiB of aggregate encoded bytes, at most 8,192 pixels per
side and 16,777,216 pixels per image, and 33,554,432 aggregate image pixels.
Animated images, external links, MIME mismatches, malformed bytes, embedded color
profiles, non-default EXIF orientation, CMYK and 16-bit samples are refused.
Resource names are labels; neither source parsing nor rendering opens them as
filesystem paths or URLs. Inline edit requests are limited to 8 MiB; larger
complete documents use project-scoped asset import within the model limits.
For MCP, use a project-scoped asset rather than sending photograph bytes through
the 1 MiB request channel. Both insertion and replacement accept an image object
containing `asset`, `sha256`, `name` and `contentType` instead of `dataHex`. The
worker materializes only that project's asset, checks the exact encoded-byte hash,
and embeds those bytes in portable edit history. No asset identifier is required
to replay or transfer the resulting project. The materialized edit batch remains
subject to its 8 MiB JSON budget; the MCP request limit is unchanged.
Typed history has a 16 MiB manifest budget, within the existing 128 MiB portable
archive and 256 MiB replay budgets. This admits photograph-sized image edits
without weakening the document's aggregate bounds.

Portable history replays image insertion, crop, replacement and placement from
the immutable baseline. It preserves all original resources and full original
container bytes. The maintained source transition from the prior text/shapes
engine preserves the predecessor archive. Already-migrated projects can retain
another exact predecessor archive through the bounded chain described below.

`craft/tests/slides_pictures_check.py` exercises native decoder comparison,
durable MCP creation/revision/export, image pixels in PNG and independently
rasterized PDF, portable transfer and stale-image refusal. Use `--resources` for
a staged current distribution, `--predecessor` for the prior engine's portable
project, and a fresh `--output` directory. This source-runtime evidence does not
qualify installed packaging, Linux, Cloud or the complete release.

## Successive maintained migrations

`slides.migrate` accepts a previously migrated portable project as either an
owned asset or an existing durable source revision. Each transition must appear
in the maintained `MIGRATION_EDGES` allowlist. The new project embeds the exact
prior archive; that archive retains its own exact predecessor. Every level checks
the original bytes, reconstructed baseline, typed edit replay, source pins and
transition hashes. Later revisions must preserve the predecessor's full history
as a prefix. The native engine then verifies the baseline and current document
through encoding and cold reopening before publication.

The chain is limited to eight migrations, 256 MiB of aggregate archive bytes,
256 MiB of aggregate expanded members and 256 MiB of cumulative replay. These
budgets are shared across all ancestors. Every individual archive still obeys
its 128 MiB bound. Migration does not reset a resource budget, flatten history,
discard original documents or authorize an unknown engine transition. Same-pin
and unqualified reverse transitions are refused. Inspection reports expose
`migration_count`; the portable format remains version two.

`slides_migration_chain_check.py` exercises the actual two-transition chain from
the earlier text engine through its successor to the image-capable engine. It
preserves an authored edit between migrations, checks both durable migration
entry points, then inserts an image, bundles, imports and renders the project.
It also checks tampered transitions, removed history, unknown engines and shared
depth/byte/replay limits. Source-runtime qualification remains separate from the
new engine's installed packaging and full Local/Cloud release qualification.

## Queued work across rollback

New Slides submissions persist a dispatch key derived from the explicit runtime
contract and maintained engine lock. The immutable request and current public
job responses retain the original operation name, such as `slides.create`.
Idempotency continues to compare the original request. No database schema or
public MCP operation changes are required.

The predecessor dev51 worker matches stored operation keys literally. It leaves
new qualified jobs queued, with no attempt or publication, instead of claiming
an image request that its older admission profile cannot execute. After returning
to the current runtime, the same queued job can complete. Normal queue deadlines
still apply. The older CLI may display the qualified stored operation name.

Current workers also accept historical unqualified jobs, subject to normal
admission and engine-pin checks. Unknown qualified contracts cannot be claimed
or explicitly retried through the current supported-operation list. Runtime
changes with incompatible semantics must change the contract identifier even
when the native engine lock stays unchanged. This mechanism currently applies
to Slides; it does not establish compatibility for every future engine or Cloud
worker version.

`slides_dispatch_check.py` runs the actual immutable predecessor worker against
a new image request, then completes that same persisted job with the current
worker. It checks explicit retry, unknown-contract refusal, original idempotency,
legacy submission compatibility and unrelated operation filtering. Installed
service update/rollback remains a separate qualification requirement.

`slides_raster_package_check.py` performs that installed qualification against a
new package and a real Slides-capable predecessor. It uses an isolated launchd
installation and minimal PATH. Its owned image exceeds the inline MCP request
limit and therefore enters through a project-scoped asset. The check exercises
all seven Slides operations, compares rendered PNG and independently rasterized
PDF pixels, and preserves other shapes during crop, replacement and placement
edits. It also checks a second maintained migration, a queued job during actual
service rollback, native cancellation, supervisor death, natural lease expiry,
explicit reconciliation and retry. Supply `--package`, `--previous`, `--prior`
(a real previously migrated portable project with a subsequent authored edit),
and a fresh `--output` directory. The script removes its isolated service while
retaining job evidence. This check does not establish clean-machine, reboot,
Linux, Cloud or artistic acceptance.

Explicit attempt reconciliation checks the persisted qualified contract against
the current safe-operation contracts, just as claim and retry do. It must not
authorize an unknown future contract merely because the immutable public request
names a familiar local operation. `slides_reconciliation_check.py` reproduces an
older package's reconciliation refusal on an actual interrupted qualification
job, applies the source fix, and explicitly retries that same native job. Use it
only with a stopped, isolated test installation: it changes the supplied job's
reconciliation and retry state. This source-level recovery check does not qualify
an unchanged package as containing the fix.
