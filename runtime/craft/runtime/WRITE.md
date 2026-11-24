# Write source ownership and admission

Write is being integrated into the complete Dobe Local/Cloud suite. Its maintained
native engine is built and qualified against original document fixtures. The
current unsigned development candidate contains thirteen applications. Six durable
Write operations are qualified through the installed CLI and product MCP on this
Mac. Complete source fidelity and release qualification remain open; this does not
narrow the seventeen-application release goal.

## Immutable source boundary

`write_container.inspect_bytes(data, kind)` requires an explicit `json` or `docx`
format. It never guesses from an extension, extracts an archive, opens a link,
normalizes source bytes or launches a native process. `read_source(path, kind)`
adds a bounded regular-file snapshot. The caller must own ancestor directories;
the final input cannot be a symlink, directory, FIFO or device.

The source bytes and their SHA-256 remain authoritative. DOCX inspection also
retains every exact decoded member, directory record, content type, XML tree and
resolved relationship. Native JSON retains the complete parsed input, including
unknown fields. Inventory is not semantic support: every result explicitly has
`engine_admission_complete: false`.

`check_preservation` requires the original source container to remain byte-identical
for import or checkout. A ZIP with equivalent members but different compression,
metadata or ordering fails this check. Edits and format exports must supply a
separate predicted-change contract; they cannot relax source preservation.

## Container and package checks

The source limit is 128 MiB. ZIP expansion is limited to 256 MiB, with at most
4096 entries and 64 MiB per entry. The shared strict ZIP primitives validate local
and central headers, supported flags and extra fields, streaming descriptors,
member intervals, exact decompression lengths and CRCs. Entry names cannot escape
the archive, collide under Unicode normalization/case folding, introduce symlinks
or conflict with descendant paths. Empty ordinary directory records are retained.

XML is limited to 32 MiB and 250,000 nodes across the package, with a depth of 64
and 128 attributes per element. Limits apply while parsing, before tree growth.
UTF-8 and UTF-16 XML are supported. DTDs, entity declarations and processing
instructions are refused. Namespace identity is checked independently of prefix
spelling. Original XML bytes remain available; the parsed tree is not an export.

The package must have exactly one non-macro Word main document, declared content
types for every member and at most 16,384 relationships. Each relationship table
belongs to its actual source part. Internal targets resolve within the package,
including legitimate parent-relative references. Escaping paths, ambiguous URI
encodings, missing targets, duplicate IDs and missing Office/VML relationship
references are refused. A relationship cannot grant filesystem access.

External resources, attached templates, alternative-format imports, controls,
OLE and macro payloads are not admitted. Passive HTTP(S) or mail hyperlinks are
retained as metadata; inspection never follows them. Unknown inert XML and other
declared content remain inventoried for later semantic classification. Their
presence does not authorize native execution.

Native JSON has a 32 MiB byte limit and a bounded parser preflight. Duplicate
keys, invalid Unicode, nonfinite/oversized numbers and excessive nesting are
refused. Integer identities remain exact through the unsigned 64-bit range.
Unknown fields are preserved here so a later model comparison can refuse silent
native loss rather than drop them during import.

## Evidence and remaining integration

`write_structure.inspect` adds independent validation of native document structure.
It checks complete UTF-8 character-run coverage, object replacement markers,
owned story references, header/footer and note kinds, comment/revision ownership,
balanced field/bookmark/comment/permission ranges, table spans and vertical merges,
section text areas, column dimensions, style inheritance and list definitions.
Stable source paths and text hashes identify paragraphs and inline objects without
rewriting them. Duplicate identities, native-clamped cell spans, missing references
and cycles are refused.

Text boxes distinguish linked overflow chains from nested story expansion. Chains
are bounded at 256 parts; nested boxes must remain within the native four-level
and 64-nested-box limits, including repeated references to the same child. A note's
own reference mark is a label, not recursive story expansion. Empty drawing canvases
and zero-height horizontal connectors remain editable. Tables may nest within the
managed JSON parser budget; skipped columns must be explicit and agree with the grid.

This check exposed nine missing linked heading-style definitions in the original
native template. The maintained Dobe source now supplies those character styles.
The old fixture remains a refusal counterexample; the corrected native fixture
owns all nine reciprocal links and applies a linked character style successfully.

The structure result still has `engine_admission_complete: false`. It lists pending
property, resource, source-format and native-comparison work, plus complex payloads
present in the document. It does not validate every formatting value, equation,
graphic, opaque XML object or content-control payload. Recognized external and
executable field codes are refused; complete field semantics remain unqualified.
No caller may treat this stage as permission to render an untrusted document.

`write_resources.inspect` independently checks the native media and retained-part
byte stores. Base64 must be canonical, including its padding bits; legacy byte
arrays contain actual bytes, not booleans. Names stay inside their own namespace,
with Unicode/case collisions and file/ancestor conflicts refused. Original
encoding and SHA-256 are reported without rewriting the document. Per-part bytes,
aggregate bytes and aggregate decoded image pixels have separate limits.

PNG, JPEG, single-frame GIF, WebP, BMP and supported single-page TIFF pictures are
fully decoded independently. TIFF compression matches the native decoder's bounded
set; animated/multipage inputs need explicit selection. The maintained native
`picture` command provides a second complete decode without opening a document or
loading fonts. `compare_picture` checks its packet, dimensions, source size and
alpha. Lossless formats require exact RGBA8 agreement. JPEG and lossy WebP allow
at most three levels of channel rounding error and a mean error of 0.5 across all
RGBA channels; alpha always matches exactly. Lossless WebP is identified from its
actual payload and receives no lossy tolerance.

For unsigned 16-bit gray samples, the comparison uses rounded full-range scaling,
`(sample + 128) // 257`, matching the pinned native conversion. This is a diagnostic
projection, not lossless 16-bit qualification. Color profiles, orientation, CMYK
and 16-bit source fidelity remain explicit gates. Retained package parts can
contain embedded-font manifests and font data; their byte inventory is never
permission to open them in the native document reader. Font identity, glyph
coverage, retained-package semantics and source-format fidelity remain open.

`write_retained.inspect` checks the native retained-part manifest before any font
loading. The byte-store layer recognizes the six exact non-macro `wordcraft:`
bookkeeping keys used by the pinned reader; these are control records, never
filesystem paths. Unknown control keys and macro bookkeeping remain refused.
This corrects the earlier blanket colon refusal, which also rejected legitimate
embedded-font manifests.

Manifest part declarations and source-scoped relationships must have owned bytes,
unique identities and valid fields. Unknown rows, duplicate declarations,
relationships before their owner, missing targets and active/external resources
are refused instead of reproducing the native parser's silent skips. Retained
XML uses the same bounded, namespace-aware parser as the container layer. Font
table lookup follows the native case-insensitive path rule while relationship
targets retain their exact stored spelling.

Embedded regular/bold/italic/bold-italic slots bind to owned font relationships.
GUID keys reverse their sixteen bytes and XOR the first 32 font bytes; absent
keys leave bytes unchanged. Exact repeated target/key/family tuples are decoded
once, while distinct aliases count separately against the 64-font/64-MiB copy
budget. Conflicting targets for the same family slot are refused. Original and
decoded SHA-256 values are recorded without rewriting source bytes. Extracted
fonts remain unqualified until outline/program validation, actual native font
identity, embedding rights and shaped-glyph coverage are established. Other retained
control records and package semantics remain explicit gates.

`write_fonts.inspect` now runs on every extracted font before any native font
load. Its current profile is standalone TrueType: at most 32 MiB, 128 tables,
32 character-map records and two million mapping visits. Collections, WOFF/WOFF2,
CFF outlines and unsupported table versions or cmap formats are refused rather
than passed to a native decoder. This limited profile does not claim support for
every font the upstream application can open.

The independent parser verifies directory ordering, unique tags, aligned and
nonoverlapping table intervals, zero padding, individual checksums and the whole
file checksum. It checks required tables, units and bounds, glyph count,
horizontal metric coverage and monotone glyph locations. Name strings have
bounded lengths and strict Unicode decoding. Cmap formats 4, 6 and 12 have owned
offsets, ordered ranges and glyph bounds. Requested-character reports retain
missing glyphs and disagreements across Unicode maps; they do not substitute a
fallback font or claim that character maps describe actual shaped glyphs.

OS/2 embedding bits are recorded as declared restrictions. They do not grant a
license or authorize embedding, editing or subsetting. Font rendering, hint
execution, layout/variation tables and independently verified shaping remain
explicit pending gates. No font parser result grants
document execution permission, even when all structural checks pass. The current
inspector neither runs font programs nor decompresses compressed font files.

`write_outlines.inspect` now decodes every simple TrueType outline's contours,
repeat flags and signed coordinate deltas. Coordinates must stay within their
declared glyph bounds. Composite records own their referenced glyphs, point
attachments, argument bytes and F2DOT14 transforms. Conflicting flags, early
instruction blocks, invalid contour types, trailing payloads and malformed
records are refused before native loading.

An iterative dependency graph rejects cycles and checks every repeated component
occurrence when calculating expanded point, contour and node counts. Scheduling
may share a dependency, but resource accounting never treats repeated references
as one occurrence. Limits include two million aggregate expanded points/nodes,
200,000 component records, 128 direct components, 4096 expanded nodes per glyph
and depth sixteen. Actual counts must also fit the font's maxp declarations.
Conservative transformed-coordinate bounds prevent explosive geometry without
copying expanded point arrays. Exact composite raster fidelity is still pending.

Hint programs are inventoried, not executed. PUSH/NPUSH immediate operands must
fit their owned bytes, including inside glyph programs, fpgm and prep. Declared
stack/twilight/storage/function limits and control-value lengths are bounded.
Glyph instructions are limited to 8 MiB in aggregate; each global program is at
most 256 KiB. These checks do not resolve jumps, function calls or instruction
semantics, prove termination, or make a native hint interpreter safe. Native
execution still requires its separate qualification and process limits.

The private native `glyphs FILE` diagnostic now observes the same print layout and
display options as PNG export. It returns actual selected faces, exact font bytes,
glyph IDs, UTF-8 cluster ranges, positions, sizes, synthetic styles and enclosing
transforms/clips. A fresh process can reproduce the packet and expose a font
substitution that a requested-family inventory alone cannot detect. The packet
uses `DOBEGLY1`, a little-endian u32 header length, bounded JSON and a contiguous
font-byte payload. It is not a public runtime operation.

`write_glyphs.inspect` verifies that every selected font exactly matches a
caller-owned source and passes the independent TrueType profile. It checks face
indices, units, font-byte ownership, UTF-8 ranges, glyph bounds, geometry, draw
identity and aggregate counts. Each single-character glyph is compared against
all Unicode character maps. Contextual substitutions and ligatures remain
explicitly separate from direct cmap matches: a native trace observes shaping but
does not independently prove that shaping is correct. This distinction also
applies to fallback fonts and synthetic bold or italic styles.

The trace is limited to 256 pages, 200,000 draw items/glyphs, 50,000 runs, 64 faces,
4 MiB of text, 16 MiB of header and 64 MiB of font bytes. It refuses missing
glyphs/pictures, invalid text ranges, watermark text and text converted to
outlines. Generated labels without cluster ranges retain their actual glyph and
font identity with `rangesKnown: false`; their glyph count and unresolved text
mapping are explicit. No text ranges are guessed. These
are output diagnostic limits, not bounds on the work already done while opening
and laying out a document. The caller must complete admission and process limits
before invoking it. Font programs, independent shaping, embedding rights and
source fidelity remain open; the inspector always returns admission as false.

The structural visitor also checks typed character, paragraph, table, row and
cell properties through `write_properties`. Unknown names, invalid enums,
booleans disguised as integers, invalid colors, over-budget dimensions and
malformed nested values are refused. Character size, scale, spacing, position,
kerning and paragraph line spacing use the pinned native resolver's limits.
Table percentages above 100 remain valid, bounded at the native 1000% width-share
limit. Zero, false, inherited nulls, negative offsets, clear tab stops and native
snake-case border names retain their meaning. Native JSON uses canonical color
arrays or the `Auto`/`Rgb` text-color representation; command-input color aliases
are not silently converted by this inspector.

Conditional table regions now participate in character-style and font ownership,
including tracked old row exceptions. Cell background pictures must name owned
media and enter the resource inventory. Hyperlinks either bind to an owned
bookmark or pass the passive HTTP/HTTPS/mailto policy without fetching anything.
Font family requests are inventoried; this does not prove font availability,
embedding permissions, glyph coverage or substitution fidelity.

Text effects, East Asian layout, character-based indent resolution and tiled
cell-picture rendering retain explicit pending gates. Drawing properties and
complete inherited layout still require
qualification. Passing these value checks does not remove the overall
`formatting-properties` or engine-admission gate.

`write_page_properties` checks section values, document settings, core metadata,
bibliography/custom-property inventories and style/list metadata. Section history
is recursively checked with the same page geometry and owned header/footer rules.
Columns must fit the native maximum of 45 and its 18-point minimum width; values
that the native layout would clamp are refused. This corrects the earlier
structural allowance of up to 63 section columns. Table-column limits are separate.
Grid pitches, line numbering, note settings, printer tray IDs and page-number
formats have explicit types and bounds. Native number-format variants are
recognized, but rendered label fidelity remains a separate gate: some upstream
formats render as decimal or clamp large label values.

Theme/watermark font requests and page-background media enter the resource
inventory. External attached templates and automatic template style updates are
refused. Protection settings remain explicit pending state; validation does not
authorize edits to a protected document. Math settings, latent-style XML, typed
custom properties, bibliography evaluation, hyphenation resources, backgrounds,
watermarks and resolved grids retain their respective qualification gates. No
template, bibliography URL or other external resource is fetched.

`craft/tests/write_container_check.py` runs against actual maintained-native
fixtures and adversarial mutations. It checks exact original bytes, independent
ZIP member decoding, package ownership, namespace handling, supported XML
encodings, URI resolution, malformed/active content, aggregate budgets and
nonregular file refusal. It performs no native or remote operation.

`craft/tests/write_structure_check.py` creates original documents with multilingual
text, editable lists, bookmarks, footnotes/endnotes, headers/footers, a text box and
a horizontal connector. It compares complete cold native snapshots, exercises an
actual tracked replacement and linked character-style application, and mutates
references, ranges, table spans, cycles and expansion limits independently. These
are local structural/source tests, not installed runtime qualification.

`craft/tests/write_properties_check.py` checks malformed values and references,
retains valid native boundary cases, and predicts a precise formatting edit over
the entire serialized document. The prediction accounts for the native
`format.set` rule that size, bold and italic also set complex-script values
unless explicitly overridden. A fresh process reopens the complete model; strict
raster output is independently decoded and differs from the original fixture.

`craft/tests/write_page_check.py` checks malformed settings, old section history,
native column-clamping boundaries, metadata duplicates and resource ownership.
It predicts complete native revisions to margins, columns, page numbering,
document grid and odd/even-header settings. The saved model survives a cold
reopen, and the strict revised A4 raster is independently decoded.

`craft/tests/write_resources_check.py` compares both decoders on original images
across all six raster families, including alpha, lossless/lossy WebP and 16-bit
gray. It exercises malformed byte encodings, paths, frames, compression, size
budgets, packet tampering, FIFO refusal and unchanged original bytes.

`craft/tests/write_retained_check.py` uses an original document and a pinned
upstream Source Sans 3 font. It checks malformed manifests/relationships, exact
GUID de-obfuscation, namespace variants, repeated references and control records.
Fresh native processes report a unique document alias as missing without the
embedded font and available with it. Complete native JSON snapshots preserve the
manifest and obfuscated bytes; DOCX export/reopen preserves the decoded font hash
and alias use. This controlled font evidence does not qualify arbitrary font
files, every glyph's identity or all source-format semantics.

`craft/tests/write_fonts_check.py` checks all thirteen pinned bundled TrueType
fonts, independently reconstructed checksum-correct malformed fonts and tiny
hand-authored character maps. Semantic mutations retain correct outer checksums
so they exercise internal validation. It also verifies that corrupt embedded
font bytes are refused through retained-package inspection, before a native call.

`craft/tests/write_outlines_check.py` decodes all thirteen pinned fonts and uses
independently authored triangle/composite programs to check repeated references,
point attachments, cycles, transform growth, aggregate expansion, declarations
and truncated hint operands. It performs no native call or hint execution.

`craft/tests/write_glyphs_check.py` verifies actual selected font bytes under an
embedded alias, direct glyph identities, cold packet determinism, a precise font
change, DOCX font retention and a real ligature cluster. Packet mutations exercise
ownership, ranges, face references, counts, geometry and unsupported variants.

The initial public operation profile combines bounded model/resource inspection,
unsupported-content classification, complete native snapshot comparison and cold
reopen. Full semantic, font and source-format qualification remains open. The native
snapshot reports read-time missing pictures and retained markup separately:
those states are not fully represented by native JSON. Original source bytes
must stay available for revisions, portable projects and fidelity checks.

Creation, typed revisions and exports must preserve editable paragraphs, tables,
styles, comments, fields, sections and admitted resources. Visual exports need
strict glyph/picture checks and independent output validation. Durable job
publication, cancellation and native-process crash recovery now have local
distribution-layout evidence described below. Operation metering, installed
package checks and the remaining Local/Cloud release gates remain separately
required. Native source qualification and structural admission alone do not
satisfy those gates.

## Typed revision contract

`write_revision.revise_bytes` now predicts edits against the complete native JSON
model. It takes the exact original SHA-256 and one to 128 typed edits. Selectors
come from the structural paragraph inventory, including table cells, notes,
comments, headers, footers and text boxes; section edits select existing section
records. Arbitrary JSON pointers, native commands and filesystem paths are not
accepted. The source stays immutable, and the caller must retain its exact bytes.

Supported edit kinds are `text.replace`, `text.format`, `paragraph.properties`
and `section.properties`. Text ranges use original UTF-8 byte offsets and exact
expected text. Disjoint edits resolve against one source revision and apply in
descending offset order, so variable-length changes do not redirect later edits.
Replacement text inherits one uniform selected character format; mixed-format
replacement requires a separately defined selection instead of silently losing
formatting. Replacements cannot consume object/range markers or create paragraph
breaks. Character formatting preserves unselected run properties and text bytes.

Property edits use explicit `set` and `unset` keys. Paragraph/section edits also
require their complete original property object as an optimistic expectation.
These are exact native property values: for example, text color uses the native
`{"Rgb": [r, g, b]}` representation, and complex-script values are explicit keys.
No implicit complex-script mirroring or command-alias normalization occurs.

The complete resulting model is structurally revalidated before any new bytes
are returned. Overlapping text edits, duplicate property targets, stale hashes,
invalid values, split UTF-8, forged revision history and no-op requests fail
atomically. Tracked/protected editing and stories containing permission, content
control or complex-field ranges require their own qualified edit path. This
method does not erase their restrictions or invent acceptance/rejection history.

`craft/tests/write_revision_check.py` checks complete native cold snapshots for
variable-length Unicode replacements, deletions, partial formatting, composed
page/paragraph changes, table cells and note stories. It independently predicts
all changed fields, decodes a real strict PNG, reads revised text from exported
DOCX XML and checks a cold native save against its explicit revision/time metadata
contract. Original comments, media and source files remain exact.

This revision work advances editable deliverables while the separately recorded
font, complex payload, source-format and runtime gates remain open. Returning a
predicted document does not authorize native execution, durable publication or
claim full DOCX fidelity. The durable adapter below composes this revision
contract with complete native observations and the supervisor's publication fence.

## Portable project ownership

`write_project` combines container, structural, resource and embedded-font
inspection with the typed revision contract. Its version-one `.dobewrite` archive
contains four fixed files: `project.json`, `original.json` or `original.docx`,
`baseline.json` and `document.json`. Originals are exact source bytes. Baselines
and current models remain distinct from the original container; JSON baselines
must initially be byte-identical to the original JSON.

For DOCX, the caller supplies a complete native model observation. The archive
retains both that observation and the exact DOCX, but packaging alone cannot
prove that the model represents every source feature. Inspection therefore
always reports `docx-baseline-source-correspondence` as pending. Read-time states,
unsupported content and original package markup cannot disappear merely because
the serialized native model does not contain them.

The manifest pins the maintained engine product/version, upstream source revision
and complete source/dependency lock hash. This identifies a reproducible source
build across hosts without requiring the Mac binary to run on Linux. Operation
adapters must compare the pin against a verified installed-engine receipt; the
manifest is neither a signature nor proof that an engine was executed. A pin
mismatch cannot silently select another engine.

Every payload has an exact SHA-256 and byte length. Each history entry records
the preceding model hash, typed edits and expected result hash. Inspection
replays the complete chain and requires byte-for-byte equality with the current
model. Revisions never replace the immutable original or baseline. ZIPs are
deterministic and use the existing strict header, path, interval, decompression
and CRC checks. Unexpected files, directories, forged hashes, broken chains and
unrecorded current-model changes are refused.

Limits are 128 MiB per archive, 64 MiB per ZIP member, 32 MiB per native model,
1 MiB per manifest, 32 history entries, 128 total typed edits and 256 MiB of
aggregate replayed model bytes. These are explicit managed-project limits,
not a claim that every upstream document fits this profile.

Checkout writes only the fixed owned files into a new disposable attempt
directory, refuses existing destinations and symlink ancestors, verifies written
bytes and removes its own partial files on cancellation or failure. It does not
overwrite owner files or serve as the durable publication boundary. The worker
must still complete native checks, cancellation/lease checks and atomic revision
publication before exposing a customer result.

`craft/tests/write_project_check.py` creates and revises real JSON and DOCX
projects, checks independent whole-model predictions and relocates them into
fresh directories. Native cold snapshots and a strict PNG use the relocated
model; a retained embedded-font alias resolves there too. Tampered archives,
history, engine pins and checkout paths are refused. Complete runtime admission
and installed-package qualification remain open. This project module does not
publish revisions; the durable adapter below owns that integration.

## Receipt-bound native observation

`write_engine.Engine` connects portable projects to the maintained executable
through the existing bounded process transport. The caller supplies a source pin
and binary SHA-256 from a verified engine receipt. Construction independently
checks the embedded lock, manifest file record, complete binary bytes and exact
native version/source response. Malformed metadata, symbolic-link executable
paths and changed executables are refused. This comparison does not authenticate
an arbitrary caller-supplied receipt or replace installer verification.

The observer exposes version and complete JSON snapshot commands. The typed
export adapter additionally uses fixed picture/glyph diagnostics and strict
PNG/PDF commands through the same bounded transport.
It checks the project pin before checkout, combines model/resource/font inspection
before each observation, and compares the complete returned model with the exact
prediction. Missing or defaulted fields are differences, not silently accepted
normalization. The baseline is observed once and the revised model twice in fresh
native processes. Read-time state must show neither retained package markup nor
missing pictures for these native JSON observations. Original source, baseline,
current model and manifest bytes must remain unchanged after every observation.

All child calls share one wall deadline, bounded stdout/stderr and kernel CPU/file
limits. They use the existing process-group transport, including supervisor group
ownership when entered from a durable attempt. Cancellation, native failure or
model mismatch removes only the newly created disposable checkout. Existing
destinations are never reused or deleted. This adapter alone does not enforce
aggregate resident memory or provide an operating-system sandbox; those controls
still require the durable worker and its supervisor.

`craft/tests/write_engine_check.py` uses the actual maintained binary for complete
cold comparisons, native default-insertion refusal, receipt/version checks and
cancellation. Its cancellation probe waits for a large snapshot to emit output,
confirms that the native executable is alive, then cancels through the production
transport and checks that the child and its process group are gone. Local probes
also cover stale bytes, foreign pins, owned paths, existing owner files, malformed
metadata, shared deadlines and changed executables.

Successful reports clear the native-model comparison gates for the observed
models only. Complete source fidelity, font/hint/complex-content qualification,
DOCX baseline correspondence and durable publication remain explicit pending
requirements. DOCX originals are preserved and inspected as containers here;
they are never opened directly by this adapter. The durable adapter below uses
these observations; installed qualification covers the bounded profile below.

## Durable CLI and product MCP operations

The same `dope_submit_job` tool and `dobe submit` CLI now route six operations
through the existing journal, worker, attempt process group and atomic revision
publication. No additional MCP server or external model service is involved.

| Operation | Parameters | Result |
| --- | --- | --- |
| `write.create` | `{"document": complete_native_model}` or the versioned recipe below | New editable project with exact authored source |
| `write.import` | `{"asset": project_asset_id, "format": "json" or "dobewrite"}` | Owned source or portable project, with original bytes retained |
| `write.inspect` | `{}` | Complete baseline/current native comparison and structural inventory |
| `write.edit` | `{"expected_sha256": portable_project_hash, "edits": typed_changes}` | New revision with exact optimistic history replay |
| `write.bundle` | `{}` | Downloadable editable `exports/document.dobewrite` |
| `write.export` | Explicit `png`/`pdf` format and delivery options below | Strict page delivery with independent output decoding |

Creation/import require a new project. Other operations require a source revision.
Creation accepts the full native document structure or a versioned production
recipe. Requests are limited to 8 MiB; larger JSON sources
enter through imported assets. Import accepts project-scoped asset IDs only,
never local paths, URLs, executable paths or arbitrary native commands. Direct
DOCX import remains unavailable. A portable project may retain a DOCX original
with its separately observed native baseline; its source-correspondence gate
remains pending and the DOCX is not executed or converted by this route.

Typed edits use the exact `.dobewrite` archive hash, not a model-only hash. The
supported edit kinds are `text.replace`, `text.format`, `paragraph.properties`
and `section.properties`; their exact expectations and UTF-8 offsets are described
above. Failed or stale edits publish no revision. Initial source and origin recipe
remain immutable across edits, inspection, delivery and transfer to another project.

Every successful revision contains `native/project.dobewrite`, `native/baseline.json`,
`native/document.json`, the exact `native/original.json` or `native/original.docx`,
`exports/inspection.json`, `exports/structure.json` and origin/last-operation
recipes. Temporary asset staging and native checkouts are excluded from the
published artifact inventory. PNG/PDF delivery is described below. Direct DOCX
conversion and complete source-format fidelity remain pending; capabilities and
revision validation report those limits explicitly.

`write_binding` derives the engine location from the running runtime's fixed
`DobeCLI/lib/dobe` layout. It checks the distribution identity, qualified source
lock, engine-manifest receipt and executable bytes. Project parameters, PATH and
`STUDIO_BUNDLE_RESOURCES` cannot redirect Write to another executable. The bundle
installer remains responsible for signature policy or explicit unsigned developer
admission; receipt consistency is not a signature. The current binding qualifies
macOS ARM64 only. Linux worker packaging remains a separate required gate.

The package builder accepts `--write-engine` and copies the maintained pack and
its notices into the normal CLI distribution, with manifest hashes covering all
files. This does not turn an untested build into an installed or released product.

`craft/tests/write_runtime_check.py` exercises real CLI/MCP clients, twelve durable
jobs, exact complete-model edits, idempotency after client exit, portable reimport,
whole-project transfer and refusal of stale edits, omitted native defaults and
damaged bundle receipts. Nine jobs succeed; three expected failures preserve the
previous head and publish no revision. The fixture uses the current runtime and
actual maintained native pack in the distribution layout, without installation.

`craft/tests/write_recovery_check.py` observes real snapshot children in registered
attempt groups. It holds only the confirmed native child with SIGSTOP, then tests
owner cancellation and supervisor death while the attempt watcher continues.
Both groups disappear without publication. After controlled local lease expiry,
the crashed job becomes interrupted and never replays automatically. Explicit
retry succeeds with exact original bytes and complete native model comparison.
This is local durable recovery evidence, not reboot or hosted-isolation proof.

## Strict page delivery and typography

`write.export` accepts `{"format":"png"}` or `{"format":"pdf"}` on an existing
revision. PNG additionally accepts ordered unique `pages` and a `scale` from
0.25 to 4 pixels per point. Defaults are all pages at one pixel per point. The
adapter predicts dimensions using the native binary32 arithmetic, then refuses
more than 16,777,216 pixels per page or 64,000,000 aggregate pixels. It checks
decoded dimensions against that prediction instead of accepting native clamping
or downsampling. PDF exports the complete document and requires the maintained
Dobe PDF component in the same verified bundle.

Font substitutions are refused unless the request names the exact observed
mapping in `font_substitutions`, for example
`[{"requested":"Aptos","actual":"Source Sans 3"}]`. The complete set must
match: missing, extra or changed mappings fail. The adapter never silently treats
a fallback as the requested typeface. Prefer authoring with the intended available
font; explicit substitution is a deliberate delivery choice, retained in the
recipe and report. It does not rewrite the editable source's font requests.

The maintained glyph diagnostic now emits schema version two, including unique
requested/actual substitution pairs from the exact export layout with markup
disabled. Actual face bytes must match one of thirteen immutable built-in font
identities from the pinned source, or the document's independently checked
embedded font bytes. The packet still receives full range, geometry, glyph and
font-table checks. Observing actual glyphs does not independently prove shaping,
font outlines or typography quality. The original schema-one engine and earlier
prototype packages remain preserved; their source locks are not silently rebound.

Before rendering, each owned picture is decoded independently and compared with
the native picture diagnostic. Color-profile, orientation, CMYK and high-depth
sources requiring separate color qualification are refused by this delivery
profile. Source bytes remain intact. Native `--strict` checks reject missing
glyphs and pictures. Every PNG is generated twice in fresh processes, fully
decoded independently and required to be byte-identical across the cold runs.

PDF delivery is read twice by the separately maintained PDF engine. Both passes
perform static admission, disable document scripts, check the complete extracted
state, verify page geometry and render every page independently. Cold extracted
state and decoded raster hashes must agree. Per-page normalized character
inventories must match the native page glyph text. This compares visible text
content, not reading order; PDF reading order remains an explicit gate. Fonts
declaring restricted, bitmap-only or no-subsetting embedding are refused by the
current PDF path. Recorded rights bits do not grant a license.

Delivery artifacts live under `exports/delivery/`: `page-NNN.png` files or
`document.pdf`, plus `delivery.json`, `glyphs.json` and `pictures.json`. Reports
include exact source hashes, selected pages, effective scale, actual font bytes,
accepted substitutions and independent decode results. Temporary native decoder
probes and cold copies are removed. Failure removes only the fresh disposable
delivery; the durable supervisor publishes no partial revision. Editable source,
history and original bytes stay unchanged, including after rendered delivery.

The delivery report keeps `visual_approval` and `source_format_fidelity_qualified`
false. These are bounded production and fidelity checks, not artistic approval
or a claim of general DOCX, font-shaping or PDF conformance. The existing shared
deadline, CPU/file/pipe limits and worker aggregate limits apply throughout.

`write_exports_check.py` checks real one- and two-page PNG/PDF deliveries, scale,
page ordering, retained embedded fonts, exact originals, public durable exports,
missing-glyph refusal, unapproved substitutions and malformed requests. Recovery
checks separately hold actual PNG-render and PDF-reader children, cancel or kill
their supervisor, prove group removal and unchanged project heads, then complete
explicit retries with exact original bytes. Installed development qualification is
described below; reboot and hosted release qualification remain open.


## Reusable production brief

`write.create` also accepts `production_brief` version 1. The caller supplies all
content. The compiler reuses typography, spacing, page configuration and table
structure; it never retrieves another user's document or calls a generative model.
The result is the same complete editable native model used by typed revisions,
portable projects and strict delivery, not a flattened document template.

```json
{
  "recipe": "production_brief",
  "version": 1,
  "title": "A single visual language",
  "subtitle": "Identity and motion production brief",
  "sections": [
    {"heading": "Direction", "paragraphs": ["Use restrained colour, clear typography and deliberate motion."]},
    {"heading": "Revision rules", "paragraphs": ["Keep the approved composition and retain editable sources."]}
  ],
  "deliverables": [
    {"asset": "Campaign image", "editable_source": "Layered image project", "delivery": "PNG + original"},
    {"asset": "Motion sequence", "editable_source": "Editable timeline", "delivery": "MP4 + project"}
  ],
  "controls": {"paper": "a4", "margin": 54, "body_size": 11, "accent": "#123E49", "heading_face": "editorial"}
}
```

Submit this JSON as `write.create` parameters through the ordinary CLI or
`dope_submit_job`. Capabilities advertise the recipe and controls. `subtitle`,
`author`, `deliverables` and `controls` are optional. A4 defaults to 54-point
margins and 11-point Source Sans 3 body text, with a 30-point Source Serif 4 title.
The sans heading option uses Source Sans 3 for the title. Both are pinned built-in
fonts; the qualified examples require no font substitutions.

Paper can be A4 or Letter. Margins range from 36 to 90 points and body text from
9 to 14 points. The accent is an explicit RGB hex colour. Table headers retain
that exact fill and choose black or white text for at least 4.5:1 contrast.
Titles and headings use the accent or a darker derivative meeting the same ratio
against white. The report records the resolved colours and ratios. These checks
cover these text/background pairs, not complete document accessibility.

Content limits are 32 sections, 32 paragraphs per section, 128 deliverable rows
and 64 KiB of aggregate text. Paragraph strings cannot contain line breaks or
inline-object markers. Unknown fields, invalid controls and unsupported versions
are refused. Native scalar values use binary32-compatible decimals so complete
cold model comparison does not silently accept native normalization.

`recipes/write-production.json` retains normalized controls, source-model hash,
font choices and exact selectors for title, sections and table cells. It describes
the initial authored model and stays unchanged after typed revisions and delivery.
The original request remains in the origin-operation recipe. Whole-project transfer
preserves both records; a standalone `.dobewrite` contains the native source and
revision history, not these separate project recipe files. Native defaults are
held in a hash-pinned template derived from the maintained engine, with generated
timestamps removed. User content is never part of that shared template.

`write_recipes_check.py` qualifies seven real durable jobs: creation, PNG, PDF,
precise text revision, whole-project transfer/inspection, and a second creation
and PNG using Letter, a bright accent and fractional controls. Complete native
models match independently compiled expectations. Actual glyph faces match the
recipe, PDF text passes independent character-inventory comparison and originals
remain exact. Ten malformed requests are refused. The default and Letter samples
were visually inspected for hierarchy, readable colours, table alignment and
clipping. That inspection does not approve every possible recipe input: long
paragraphs, oversized unsplittable table rows, multi-page typography and broader
language coverage still require their own layout qualification. No automatic
artistic approval or installed-release claim is made.


## Installed development qualification

The immutable unsigned `0.1.0-dev.47` CLI distribution includes maintained Write
build 10 and the six-operation runtime with `production_brief` v1. It supersedes
the uninstalled dev.46 prototype for this bounded development profile. The twelve
previous engine packs remain byte-identical to dev.45. The archive covers every
manifest member, byte digest, mode and symlink target; release signing is pending.

`write_package_check.py` installs dev.45 into a new isolated local root, updates to
dev.47 and exercises actual installed launchers with only `/usr/bin:/bin` on PATH.
The launchd supervisor executes durable jobs after MCP clients exit. All six Write
operations run through the existing fifteen MCP tools, including recipe creation,
strict PNG/PDF, a precise CLI text revision, portable import and whole-project
transfer. Original bytes and production records remain exact. Rollback to dev.45
retains a queued unsupported Write job; reinstall completes that same request.

The recovery check holds a confirmed native PNG renderer, cancels its durable job
and proves the registered group disappears without moving the project head. It
then holds a real PDF reader, kills its actual supervisor and observes native
group removal and natural lease expiry. Explicit reconciliation publishes nothing;
an explicit retry produces the PDF and preserves the exact editable source. The
isolated service is uninstalled after qualification, while projects and evidence
remain available. No app window, remote action or paid model service is used.

This qualifies the installed bounded native-JSON/portable-project profile on the
development Mac. It does not qualify direct DOCX conversion, arbitrary documents,
all languages/fonts/layouts, clean-machine installation, reboot/login recovery,
Linux hosted workers, signing or provider deployment. Slides, CAD, Sheets and
Inspect and the remaining suite and billing requirements are still required.

## Installed images and pagination

Dev.53 additionally qualifies the existing image-bearing, two-page native model
through the installed CLI/MCP and launchd supervisor. This closes an evidence gap
in the earlier text-recipe installation check; it does not add a new image engine
or change the runtime. The fixture retains paragraph styles, comments, a table,
an owned embedded image and an explicit second-page break.

All six Write operations run in ten durable jobs. Nine succeed; one deliberately
refuses an unapproved font substitution without publishing a revision. The
successful exports explicitly permit the observed Aptos and Aptos Display
substitutions to pinned Source Sans 3. Those approvals belong to this fixture,
not a default rule for customer documents.

Both installed PNG pages exactly match the existing native raster oracles. The
separate PDF engine reads both pages and renders the embedded image with its
expected colors. A precise second-page text revision preserves the complete
surrounding model, original image and first-page PNG bytes while changing the
second page. Portable transfer, cold reopening and final PDF delivery retain
the revised document. The isolated service is removed after the check.

This establishes the declared paragraphs/styles/images/pagination minimum for
the tested development-Mac profile. Image insertion through a recipe, typed image
replacement, direct DOCX conversion, arbitrary Office fidelity, artistic approval,
Linux/Cloud and the remaining release requirements are separate capabilities or
gates. Availability of all seventeen bundled engines does not establish those
requirements.
