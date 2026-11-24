# Sheets minimum on the sealed macOS candidate

The maintained `craft/runtime/tools/sheets_acceptance.py` fixture exercises all
seven Sheets operations through the package's public CLI and reconnecting MCP
clients. This record describes bounded native workbook qualification; it does
not qualify general XLSX conversion or the complete Local/Cloud release.

The completed run passes **95 checks across 29 durable jobs**: 24
successes, 5 expected worker refusals and 3 separate admission refusals.
The 29 worker commands take **89.440 seconds** in total, including package
verification and validation. This is local wall time, not CPU time, peak memory,
energy, cloud cost or elapsed time for the whole qualification unit.

## Observed behavior

The fictional production budget has three line items and a separate Rates sheet.
Original amounts are demonstration inputs, not market prices or tax guidance.
The original total is 331.80 EUR; changing quantity, price and rate produces
389.38 EUR. A line-formula change and explicit final rounding produce 380.44 EUR.

- Independent fixed-value expectations check line amounts, subtotal, tax and
  total. Precise edits cover values, formulas and formatting. A complete-model
  oracle expands cell style references and permits only the requested changes
  and explicitly expected formula caches. Existing style-table entries remain
  unchanged; original bytes and recipe records are retained.
- Native calculation runs in separate processes. Explicit recalculation leaves
  an already-correct workbook unchanged. Formula cases cover every declared
  scalar function, a comparison and division-by-zero error. Boolean, numeric
  and Unicode text cells remain typed; clearing them restores sparse storage.
- Independent CSV parsing preserves quoted commas, quotes and newlines. Native
  HTML escapes authored markup and displays formatted totals. CSV contains only
  active-sheet values; formulas, styles and other sheets remain in native source.
- Inspection and bundling preserve exact portable history. Native JSON and
  standalone archive imports retain their originals. A whole-project transfer
  to another private state remains editable. Reversing the changes restores
  original authored cells/styles/caches and byte-identical original CSV.
- Stale hashes, an unsupported formula in an atomic batch and a nonexistent
  document sheet publish no revision. Precision-losing integers, out-of-range
  addresses and a cross-project asset are refused before job admission.
- Recomputing every archive hash does not make a forged cache trusted: native
  history replay refuses it. A history-free archive is preserved without claiming
  calculation; stale caches prevent export until an explicit calculation repairs
  them while retaining the exact stale original.
- Separate MCP clients discover the same seven operations and retrieve the same
  durable CLI result after disconnection. Database integrity, native execution
  cleanup, all checkout receipts and the complete package seal are checked.

## Preserved fixture corrections

The first preparation driver inherited a standard-input pipe that the package
correctly refused with `cannot establish standard-stream ownership`. Explicit
owned standard input resolves this; the guard is unchanged.

The first full-model oracle shared expanded style dictionaries between expected
cells. A requested italic change therefore modified unrelated expected cells.
Deep-copying each expanded style corrects the oracle without changing production
code or replaying completed native jobs.

The initial arithmetic expectation treated `304.35 + 76.09` as exactly the same
binary64 value as `380.44`. The native unrounded addition instead produces
`380.44000000000005`. The fixture preserves that exact intermediate result and
adds a real `ROUND(D7+D8,2)` revision for final delivery. It reverses that formula
when restoring the original workbook. Native arithmetic is not relaxed or changed.

The historical contract and initial fixture also assumed fifteen MCP tools. The
sealed runtime exposes eighteen, including later planning and recovery tools.
The fixture checks actual discovery and all seven Sheets operations; the current
contract removes the stale count. This documentation-only correction updates its
capability hash without changing or rebuilding packaged production modules.

## Exact artifact and limits

The run uses private read-only candidate `0.1.0-slides-color-qualification.1`,
with seventeen engine packs and 7,049 sealed entries. Image SHA-256:
`4ea6968a6e2b776798cf9c4d30807de538ea0c1fd7d24ef3303465c0b6566227`.
Seal SHA-256:
`d02480c2c8570216fede88b767a26e4856a4b5fc38ad326f517bae9780f89ca8`.
All 163 top-level packaged runtime Python modules match the recorded source
boundary before execution. No production adapter or native engine is rebuilt.

The delivery includes native HTML and CSV, editable `.dobesheets` archives,
complete project ZIPs, the recipe and typed revisions. HTML content, escaping,
table cells, links and formatted totals are structurally checked. Browser policy
rejects local file-URL inspection; no alternate access route is attempted.
Rendered visual inspection and owner quality acceptance remain open. HTML fonts
remain browser-dependent, with no pinned-font raster claim.

This private ad-hoc candidate does not establish complete notices or rights,
production signing, stock-host lifecycle, Sheets-specific live-child crash and
cancellation qualification, Linux/Cloud execution or full release readiness.
The retained upstream Arabic-caret failure remains separate. No installed
service, global MCP configuration, remote service or VM is changed.
