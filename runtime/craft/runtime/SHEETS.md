# Dobe Sheets: native workbooks and durable jobs

Sheets uses maintained GridCraft v0.19.1 through the private `dobe-sheets` binary.
The user's coding assistant directs the application through the existing CLI/MCP
runtime. No paid generative model or editor window is required.

The source runtime implements seven operations: `sheets.create`, `sheets.import`,
`sheets.inspect`, `sheets.edit`, `sheets.calculate`, `sheets.export` and
`sheets.bundle`. They use the existing product MCP tools, durable journal,
idempotency keys, attempt process groups, fencing and atomic publication. They do
not introduce a separate agent endpoint. Availability requires the fixed CLI
bundle receipt and exact maintained engine lock; PATH, environment overrides and
project data cannot select an executable.

## Supported inputs and deliverables

The `cells-and-formulas-v1` profile accepts complete native Workbook JSON or an
owned `.dobesheets` archive. It preserves original bytes, all admitted native
fields, typed cells, formula text, styles and native operation history. Unknown
fields, unsupported model features and invalid sparse cell storage are rejected
instead of silently dropped. Importing CSV or XLSX is not supported by this
profile; CSV is a values delivery format.

The profile has up to eight sheets, 10,000 occupied cells, 512 rows and 64 columns
per sheet, 256 styles and 1,024 formulas. Each JSON model is at most 8 MiB. Native
formula validation allows scalar arithmetic/comparison, bounded references,
SUM, AVERAGE, MIN, MAX, COUNT, COUNTA, IF, IFERROR, ROUND and ABS. Ranges are
aggregate arguments only. The pinned native parser enforces AST depth, node and
referenced-area limits before calculation. Dynamic arrays, external workbooks,
Python, macros, volatile functions and arbitrary scripts are not dispatched.

Formatting supports bold, italic and seven numeric formats: General, 0, 0.00,
#,##0, #,##0.00, 0% and 0.00%. Text supports Unicode. CSV exports active-sheet
values; HTML exports a styled active-sheet preview with browser-dependent fonts.
HTML does not establish pinned-font raster fidelity. The native workbook remains
the editable source, including formulas and formatting that CSV cannot retain.

## Requests

Creation takes either `{"document": COMPLETE_NATIVE_MODEL}` or a production
budget recipe. A concrete recipe request is:

```json
{
  "recipe": "production_budget",
  "version": 1,
  "title": "Campaign assets",
  "currency": "EUR",
  "tax_rate": 0.24,
  "items": [
    {"name": "Product images", "quantity": 10, "unit_price": 12.5},
    {"name": "Motion exports", "quantity": 4, "unit_price": 20}
  ]
}
```

The recipe creates Budget and Rates sheets, editable quantity/unit-price cells,
native formulas, per-line rounding, subtotal, tax and total. The currency field is
a display label, not an exchange-rate source. Configuration is reusable; user
content remains only in the owned project. Up to 100 line items are supported.

An edit requires the current portable archive SHA-256 and a list of cell changes:

```json
{
  "expected_sha256": "CURRENT_PORTABLE_SHA256",
  "edits": [{"sheet": 0, "cell": "B3", "value": 12}]
}
```

Each edit names a zero-based sheet and A1 cell. Supply `value` or `formula`, plus
optional `format` with `bold`, `italic` or `number_format`. A null value clears
content. Values preserve scalar type; integers that would lose precision in the
native binary64 representation are refused. The native engine recalculates
dependents after the batch. An invalid later edit fails the whole job without
publishing a partial revision or advancing the project head.

`calculate` takes `expected_sha256`. `export` takes that hash and `format` (`csv`
or `html`). `inspect` and `bundle` take empty parameters. Import requires an owned
project asset ID and explicit `format` (`json` or `dobesheets`). JSON creation and
import append an actual native calculation to the original source. Portable
import retains the exact existing archive and replays its history. A history-free
portable import does not invent a calculation claim; stale caches must be
explicitly calculated before export. Creation/import need a new project; all
other operations name an explicit source revision through the normal job API.

## Portable history and trust

The version-one ZIP contains `project.json`, exact `original.json`, current
`document.json` and one `state-NNNN.json` for each native operation. The manifest
binds exact member bytes, a source pin and ordered typed requests. Archives are
limited to 64 MiB expanded/compressed, 32 history operations and 4,096 aggregate
cell edits. Strict ZIP checks reject traversal, symlinks, collisions, contradictory
headers, unexpected members and incorrect hashes. JSON rejects duplicate keys,
nonfinite numbers, invalid Unicode and unsupported fields. Every intermediate
model is statically checked before a native process starts.

Hashes and self-consistent history are only candidate data. The receipt-bound
observer cold-opens the original, executes every recorded edit/calculation with
the exact native binary, compares complete result bytes and cold-opens the final
model. It checks unchanged authored fields and styles around targeted changes.
Fresh native recalculation verifies output caches independently of the first
edit process. Export rechecks cached values before writing output. A forged
cache or request is refused even after every archive hash has been recomputed.
No Python spreadsheet evaluator or caller-supplied verification flag is trusted.

The observer uses bounded file/pipe/CPU transport and the existing attempt
supervisor. This is not a hostile-process sandbox. The fixed bundle receipt
provides consistency, not a cryptographic signature. Signing, machine isolation,
Linux qualification and installation evidence remain distinct release gates.

## Baseline and qualification

`sheets_base.json` is the exact native `new` output from maintained build3, SHA-256
`e6eba99a981a063871ac6cfa5b40656f68a46f9c32c46cec7b2bfb4b6e815763`.
Its upstream MIT notice is `notices/sheets-base-LICENSE-MIT.txt`. The full native
source/patch/font provenance remains in `craft/engines/sheets.lock.json`.

Local qualification commands use the bundled Python 3.12+ and real engine pack:

```sh
python3 -I -B craft/tests/sheets_project_check.py \
  --pack /path/to/dobe-sheets --fixture /path/to/native-check-5 \
  --output /path/to/new-project-check
python3 -I -B craft/tests/sheets_runtime_check.py \
  --engine /path/to/dobe-sheets/bin/dobe-sheets \
  --output /path/to/new-runtime-check
```

The project check verifies native replay, independent prior-fixture comparison,
CSV parsing, immutable sources and forged histories. The runtime check uses
separate CLI/MCP clients, actual workers/native children, portable re-edit, whole
project transfer, cross-project refusal and failure without partial publication.
It uses a staged receipt layout; it is not an installed-package claim. Later
[installed recovery qualification](../qualification/SHEETS_RECOVERY.md) covers a
real Sheets calculation child interrupted by supervisor failure, explicit retry,
and running MCP cancellation on the private receipt-client candidate. That proof
does not cover every Sheets operation/failure combination or another platform.
The historical Dev49 candidate remains fifteen installed profiles; later private
candidates have their own recorded seventeen-family package boundaries.
The upstream full native workspace CI also retains an unchanged Arabic caret
fixture failure; neither this runtime evidence nor targeted native checks turn
that gate green.
