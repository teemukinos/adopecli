# Editable PDF production minimum

Date: 2026-11-18. Scope: all six typed PDF operations on a private, sealed
macOS ARM64 candidate. This is bounded functional evidence, not general PDF
fidelity, PDF/A or PDF/X conformance, accessibility qualification, Linux/Cloud
execution, redistribution approval or owner visual acceptance.

## Produced work

The fixture creates a two-page production brief with named text, transparent
vector annotations, consistent margins and editable metadata. It changes one
headline and annotation, replaces exactly one phrase, then changes only the
headline color. The replacement remains the sole visible wording and stays
editable. A separate private state imports the portable project and restores
every original page pixel.

Deliverables include native PDF files, stable object mappings, independently
decoded PNG previews, file receipts and the reusable creation/revision
specification. Five portable ZIPs represent the original, named revision,
counted replacement, color-only revision and restoration. A four-page PDF
combines the original and replacement for comparison. Visual inspection finds
no clipped or duplicated headline; final aesthetic acceptance remains open.

## Executable acceptance

```sh
"$PACKAGE/lib/dobe/python/bin/python3" -I -B \
  craft/runtime/tools/pdf_acceptance.py \
  "$PACKAGE" /absolute/path/to/new-pdf-evidence
```

The [fixture](../runtime/tools/pdf_acceptance.py) uses the guarded public CLI,
private states and locally generated documents. The unchanged native guard
denies network access to those CLI/worker commands. No editor, installed
service, external API or model service is used. `--resume` checks saved inputs,
reuses completed jobs and refuses to replay admitted nonterminal work. An
exclusive process lock prevents concurrent drivers.

The completed fixture passes **57 checks across 16 durable jobs**: ten succeed
and six deliberately fail. It covers:

- Create, import, inspect, merge, extract and edit, including exact page order
  and pixel preservation through import, inspection, extraction and merging.
- Incremental saves retaining the preceding PDF bytes, named text and annotation
  revisions, metadata changes and an added named text object.
- Counted replacement followed by a color-only revision, with no stale or
  duplicated wording and no change to unrelated editable records.
- Portable integrity import followed by native reopening and exact restoration.
  Import alone correctly claims only bundle integrity.
- Refusal of a stale source revision, a later invalid batch target, an incorrect
  match count, an unsupported glyph, an inert automatic-action PDF and a
  receipt-consistent bundle containing duplicate native object targets. Each
  refusal publishes no revision and preserves the current project head.
- Native cold reopening, exact receipts, both SQLite integrity checks, absence
  of all sixteen execution groups and identical full payload verification
  before and after the fixture.

The sixteen worker commands take **37.792 seconds** in total on this local run.
This includes verification and validation overhead. It is not CPU time, peak
memory, energy use, cloud cost or the duration of the entire qualification.

## Native replacement correction

The original engine rewrites rendered paragraphs without updating named text
metadata. Four baseline jobs prove the defect: replacement changes the visible
words but leaves the old editable value; a later color-only revision draws both
old and new wording. Three native regressions fail against that implementation.

The maintained correction resolves content-stream ownership and updates named
items through the native editable-content operation. Ordinary imported
paragraphs retain their existing replacement route. Visible text must agree
with stored metadata before a named replacement is admitted. Ambiguous or
unsupported ownership is refused rather than guessed. Paragraph grouping can
combine several named items, so visible text is checked independently for each
source stream. The first correction incorrectly required ownership of a whole
geometric paragraph; its private-candidate refusal is retained and an additional
realistic regression covers the production brief.

Eight new regressions cover later restyling, unchanged properties, undo/redo,
cold reopening, ordinary and named content on one page, repeated/multiline and
empty replacements, highlighted matches, missing glyphs, stale metadata,
no-op preservation and grouped named items. All **26 find/replace tests** and
**770 engine library tests** pass; two existing engine tests remain ignored.
Strict engine Clippy and formatting checks pass, with the unchanged dependency
warning retained. Four runtime boundary tests reject unrelated style,
identity and placement changes. No dependency versions or original maintained
patch-file contents change; five native replacement files are added to the lock.

The initial fixture also expected inspection from an older revision to succeed
after restyling advanced the head. The runtime correctly refused it. That job
and its original failure log remain intact; the final fixture explicitly checks
stale-source refusal and inspects the latest revision. Completed jobs are not
replayed and no production check is weakened.

## Packaging correction and release boundary

The pinned Pillow wheel carries mode `0664` on its RECORD file. The unchanged
payload seal correctly rejects that group-writable entry. Wheel extraction now
preserves executable bits while removing group/world-write access before
assembling the package. Two local tests pass. The real RECORD bytes remain
identical while mode changes from `0664` to `0644`; the guard policy is unchanged.

Candidate `0.1.0-pdf-minimum-qualification.2` has seventeen maintained engine
packs and **7,048 sealed entries**. Its final disk image is privately mounted
read-only and authenticated using the trusted source guard before qualification.
Seal SHA-256:
`53220316c77710ce971894dfd7324e47a38d962007e1fa51777df0f7a8011e0e`.

The public preview builder still refuses incomplete dependency notices. The
PDF build records 352 compiler packages and 23 missing notice entries; other
reused engine inventories are also missing or incomplete. The existing internal
package builder produces this private functional rehearsal only. No public
preview gate is relaxed and no redistribution approval is inferred. Developer
ID, notarization, stock-host installation, Linux/Cloud execution, provider
qualification, broader application minima and full release gates remain open.
