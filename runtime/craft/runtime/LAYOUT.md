# Layout integration in progress

Layout operations are registered in the runtime and included in the unsigned
eight-application development package `0.1.0-dev.41`. The source builder accepts
`--layout-engine` together with `--pdf-engine`; the independent PDF reader is a
required part of Layout's export validation. Development-Mac installed acceptance
passes; clean-machine/reboot, full native workspace CI and the complete seventeen-application
Local/Cloud release remain separate requirements.

## Typed operations

- `layout.create` takes `width`, `height`, `pages` and an optional `title`.
  Dimensions are points. Each page contains `objects` with unique `name`,
  `type` and `rect` (`[left, top, right, bottom]`). All pages use the requested
  dimensions. Supported types are `text`, `image`, `rectangle` and `ellipse`.
- Text requires `text`, `font_family`, `font_style` and `size`. Optional
  `leading` is measured in points. Optional `color` is `#RRGGBB`.
- Images require an imported PNG/JPEG `asset`. Optional `fit` is `contain`
  (default), `cover` or `stretch`. Placement embeds the original raster bytes.
  Rectangles and ellipses accept `color` and have no outline.
- `layout.import` takes an imported `asset` and `format` (`native` or `idml`).
  Native import requires exact saved-state preservation. IDML import refuses
  native warnings and checks page count and embedded artwork; general IDML
  semantic fidelity is not certified. Original imported bytes are retained.
- `layout.inspect` takes a source revision and empty parameters. It re-admits
  the native document and produces fresh deliverables and diagnostics.
- `layout.edit` takes a source revision and `edits`, with one edit per named
  target. `action: replace_text` requires UTF-8 byte `start` and `end`, exact
  `expected` source text and replacement `text`. `action: move` requires `dx`
  and `dy`, in points; moved frames must remain within a page. `action:
  typography` takes one or more of the text font fields above and applies them
  to the target frame's entire story. Locked targets are refused.
- `action: replace_image` requires `name`, an imported PNG/JPEG `asset`,
  `expected_sha256` for the target's currently embedded bytes, and explicit
  `fit` (`contain`, `cover` or `stretch`). Read the current hash from the
  frame's asset in `inspection.json`. Replacement preserves the frame identity,
  geometry, transform and other frame styling. This bounded route requires a
  plain graphic in an unmodified rectangular path: custom clipping, crop,
  automatic fitting, alignment, graphic wrap and tint are refused rather than
  silently reset. Another frame using the same image remains unchanged.
  Repeated revisions can reuse an asset already retained by the project;
  authorization and exact authoritative bytes are checked again.

Every successful job retains editable `native/document.designcraft` and its
object mapping. Exports contain `document.idml`, `document.pdf`, one PNG per page
and `inspection.json` with native structure, fonts, preflight and PDF evidence.
The source revision remains unchanged. Edits compare the complete expected
native document, preserve untargeted embedded bytes and compare untargeted page
pixels. Image replacement predicts native asset allocation, merges identical
embedded assets and drops only unused artwork. Original project assets remain
retained even when the native publication no longer uses them.
A separate process reopens the saved native file. A further process checks IDML
pixel round trips. The independent Dobe PDF engine checks PDF page geometry and
ordinary visible unthreaded stories; it does not certify every imported text
feature or PDF standard.

## Implemented foundations

`studio_runtime/layout_document.py` reads native publication archives without
extracting their contents or following links. It rejects duplicate or ambiguous
ZIP entries, unsupported compression, symlinks, encrypted entries, traversal
paths, excessive expansion, duplicate JSON keys and nonfinite numbers. It bounds
document complexity, page pixels, nested stories and frames, UTF-8 text and
embedded artwork. Every admitted native asset must have matching embedded bytes;
external links and missing assets are refused. PNG and JPEG artwork is decoded
within explicit pixel limits before native rendering.

The IDML admission helper bounds XML structure and page geometry, refuses DTDs,
checks package references, and verifies embedded raster bytes. Case aliases and
percent-encoded part aliases are refused because the native importer has lenient
part lookup. External artwork and placed PDF/EPS require further qualification.
Admission alone does not prove that an imported publication retains every feature.

The rich-text expectation helper models UTF-8 range replacements and insertions.
It requires the exact expected source text, preserves character formatting
outside the edit, and retains paragraph formats according to native merge/split
behavior. Its complete expected story can be substituted into a copy of the
original document for comparison with the engine's saved document. Native
table/anchor/note markers require a separate structural edit contract. This
helper does not rewrite native files or replace the production engine.

`studio_runtime/layout_engine.py` starts the maintained headless executable with
private HOME/cache directories and explicit read/write roots. It requires the
Dobe engine identity and bounded structured replies. Preflight requires no
issues and exact bundled font matches. Preview dimensions are compared with
native page dimensions before pixel hashes are accepted. These private helpers
are not exposed as an arbitrary command endpoint.

## Local evidence

Local primitive qualification covers 46 cases: malformed/native archive refusal,
eleven real-engine rich-text changes, invalid Unicode range refusal, exact
whole-document comparisons, unchanged appendix pixels and a distinct-process
cold reopen. Complete text deletion preserves the expected native structure but
fails publication preflight because the resulting frame is empty. That refusal
is explicit evidence, not a successful empty-publication claim.

A separate 14-case IDML qualification checks malformed and external dependencies,
DTD refusal, part-name ambiguity and a two-page embedded-artwork publication.
The admitted IDML produces equal page pixels and equal embedded asset bytes;
its saved native file reopens in another process with equal state and pixels.
These checks run locally with network and host font directory reads denied.
They are not general IDML fidelity, installed-runtime or release acceptance.

The local adapter qualification adds creation, inspection, native/IDML imports,
text/position/typography revisions and refused source mismatches, missing fonts
and overset. Real MCP submissions and separate workers verify durable creation,
revision, idempotency, failed-head preservation, portable native reopening,
native/IDML asset imports and cancellation after execution admission.

Installed `0.1.0-dev.41` acceptance covers fifteen MCP tools, creation, precise
text and typography revisions, independent PDF validation, portable native
reopening, failed-head preservation, cancellation with a live native process,
and supervisor-crash reconciliation without publication. Rolling back to
`0.1.0-dev.40` leaves unsupported Layout work queued; reinstalling completes it.
The fixture service is removed afterward. Every file, mode and symlink in the
unsigned archive is checked against the package manifest.

## Remaining integration

Frame resizing and additional styling revisions need further typed contracts
and preservation evidence. Bounded image replacement is covered by the
[publication revision qualification](../qualification/LAYOUT_REPLACEMENT.md).
The earlier maintained native source passes
48 targeted tests (MCP, file roots, CLI, bundled fonts and path operations) and
strict Clippy. The earlier editor-only test mismatch and loop warning are
corrected; their failed evidence is retained. Full native workspace CI is not
claimed. Linux hosted
workers, the other nine applications, complete billing and external release
gates remain part of the unchanged product goal.
