# Native PDF operations

Dobe PDF uses the maintained `dobe-pdf` executable. The runtime does not accept
arbitrary native commands, scripts, file paths, passwords or external converters.
The operations use the existing durable job API and publish editable PDFs,
inspection data and one PNG preview per page. The complete product still requires
all seventeen applications; this adapter is one part of that release.

## Operations

- `pdf.create`: new project; `pages` contains `width`, `height` and `objects`.
  Dimensions and coordinates are points, measured from the displayed top left.
  Objects have a unique `name`, `type` (`text`, `rectangle`, `oval`) and `rect`
  (`[left, top, right, bottom]`). Optional `metadata` supports `Title`, `Author`,
  `Subject` and `Keywords`.
- `pdf.import`: new project; `asset` identifies a PDF previously imported into
  that project. Original PDF bytes are preserved.
- `pdf.merge`: new project; `assets` is an ordered list of imported PDFs.
- `pdf.inspect`: source revision, empty parameters. Re-admit and reopen the native
  PDF, verify the object mapping and produce fresh inspection data and previews.
- `pdf.extract`: source revision; `pages` is an ordered list of unique, one-based
  page numbers. Existing named objects on those pages retain their names.
- `pdf.edit`: source revision; supply `edits`, `additions`, `replacements` or
  `metadata`. An edit identifies an existing `name` and `type` (`text` or
  `annotation`). An addition uses the creation object fields plus `page` and a
  new name. A replacement supplies `find`, `replace`, `pages` and
  `expected_matches`. Replacement is case-sensitive and fails if any requested
  match is skipped or the match count differs. Use separate revisions for a
  replacement and a named change on the same page.

Text supports `text`, `font` (`helvetica`, `times`, `courier`), `size`, `bold`,
`italic`, `color` (`#RRGGBB`), `align` (`left`, `center`, `right`) and
`char_spacing`. Text height follows measured lines; the supplied rectangle limits
its height. A placement that overflows the requested rectangle is refused.
Native text production refuses unsupported glyphs rather than silently replacing
them. General imported-font glyph coverage is not certified.

Vector annotations support `color`, `fill` (`#RRGGBB` or `none`), `width`,
`opacity`, `contents` and `rect`. They remain editable PDF annotations.
Inspection lists imported added-text items as `text_PAGE_INDEX` and annotations
as `annotation_PAGE_INDEX`. Ordinary imported paragraphs can be changed through
scoped text replacement; they are not relabelled as added text.

## Example

Submit `pdf.create` with:

```json
{
  "pages": [
    {
      "width": 612,
      "height": 792,
      "objects": [
        {
          "name": "headline",
          "type": "text",
          "text": "Production brief",
          "rect": [72, 60, 540, 110],
          "font": "helvetica",
          "size": 24,
          "bold": true,
          "color": "#1659A0"
        }
      ]
    }
  ],
  "metadata": {"Title": "Production brief"}
}
```

Submit `pdf.edit` against the returned revision with:

```json
{
  "edits": [
    {"name": "headline", "type": "text", "text": "Approved production brief"}
  ]
}
```

## Admission and evidence

Before opening any imported PDF in an editable session, the native COS parser
checks its reachable structure, exact references, page tree and resource bounds.
The contract admits static PDFs of at most 64 MiB and 256 pages. It refuses
repaired or encrypted documents, document actions/scripts, XFA, embedded or
external files, rich media and signing surfaces. Ordinary static URI links are
retained as data. No document scripts are enabled. An isolated temporary home,
configuration and cache are used for each native process.

Output must reproduce its pixels and editable records in a separate native
process. Named changes are checked against native geometry, ink and style.
Untargeted page pixels, editable records and previously reachable objects outside
edited page/metadata dependencies must remain unchanged. Incremental revisions
retain the original byte prefix. The PDF save timestamp may change; other
untargeted Info entries must remain exact. Inspection warnings, approximate font
substitution and incomplete rendering are failures.

These checks are not a PDF/A, PDF/X, accessibility, print-production or general
renderer fidelity certification. The unsigned macOS development package has
installed MCP, rollback, cancellation, supervisor-crash recovery and portable
reopen evidence. Linux workers, signing, clean-machine/reboot qualification and
the full product release remain separately gated. Importing a portable project initially proves
bundle integrity only; a successful PDF job supplies native reopen validation.
