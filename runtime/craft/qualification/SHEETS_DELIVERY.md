# Sheets numeric-format delivery on the installed Mac candidate

`craft/runtime/tools/sheets_delivery_acceptance.py` qualifies all seven numeric
formats already advertised by the `cells-and-formulas-v1` profile. It uses the
sealed public CLI and separate MCP clients, actual workers and the maintained
native Sheets engine. It does not render HTML or use a browser.

The completed local run passes **101 checks**: 32 collection checks and 69
read-only verification checks. Twelve Sheets jobs each complete in one native
attempt. A separate durable `project.import` record transfers the editable
project without claiming a native attempt. All twelve native process groups
are absent after completion.

## What the evidence establishes

The synthetic workbook contains 56 cells on its active sheet, including seven
formulas, plus a second sheet retained only in native source. Every declared
format is exercised: `General`, `0`, `0.00`, `#,##0`, `#,##0.00`, `0%` and `0.00%`.
Fixed independent expectations cover positive and negative amounts, zero,
fractional amounts and calculated zero. Unicode, literal markup, quotes, commas,
newlines and booleans retain their native types.

- Native creation changes only the seven expected formula caches. Complete-model
  comparisons expand style references and preserve every other admitted field.
- An MCP revision rotates all seven formats and changes bold/italic styles on
  exactly seven cells. Native values and formulas remain unchanged; CSV bytes
  remain identical. Existing style-table entries are not rewritten.
- A second MCP revision changes two inputs. Only those inputs and their one
  dependent formula cache change. Every other sheet, cell and style is preserved.
- CSV parsing checks exact raw values, independently of display formatting.
  Static HTML parsing checks the seven formatted values, all 56 cells' bold and
  italic declarations, escaping and active-sheet dimensions. The other sheet
  does not leak into either delivery.
- A complete project transfer to another private state remains editable through
  MCP. Restoring the original values and formats restores the original complete
  model and byte-identical CSV and HTML. Every checkout retains exact original
  source bytes; exports preserve the corresponding editable `.dobesheets` archive.
- Separate MCP clients retrieve the same durable result. Read-only snapshots of
  the ended databases pass integrity checks and leave the original bytes unchanged.
  Every checkout receipt and the complete package seal remain exact.

Run collection once with an exact expected guard receipt, then verify the ended
evidence. A verification failure does not repeat native jobs:

```sh
python3 -B craft/runtime/tools/sheets_delivery_acceptance.py \
  /path/to/AdopeCLI /path/to/new-private-output \
  --expect-verification /path/to/guard-receipt.json --stage collect
python3 -B craft/runtime/tools/sheets_delivery_acceptance.py \
  /path/to/AdopeCLI /path/to/new-private-output \
  --expect-verification /path/to/guard-receipt.json --stage verify
```

## Exact candidate and preserved fixture corrections

The read-only image is `0.1.0-notice-client-private.2`, 644,501,989 bytes, SHA-256
`31796c0dc1b5094c9b3b69333da496d61dd15e2c3131a4d7b62d16214e7d2f68`.
Its seal SHA-256 is
`a4bc051e702ee9cb60638636170eb6fa8a90ee2659f0385ea3208771f53ec797`.
The image was built from `8ce75a025e3e76c8b610d506999f71f93d4264db`.
This unit changes no production adapter, engine, package payload or installed
service. The package remains a private ad-hoc candidate.

The initial fixture changed workbook metadata outside the admitted profile. The
public CLI correctly refused it before admitting any job or publishing any
revision. The corrected fixture uses the unchanged native metadata baseline;
the initial refusal is preserved separately.

Two read-only oracle corrections are retained. A shared expected zero row also
served as the formula-result row; independent row copies prevent a formula
expectation from changing the zero expectation. The database oracle initially
counted the integrity-only project import as a native attempt; it now checks
that record separately from the twelve actual Sheets attempts. Neither correction
changes production output or repeats completed native work.

## Remaining boundaries

Static HTML parsing establishes serialized values and style declarations only.
It establishes no browser layout, clipping, font rendering or owner visual
acceptance. The earlier browser-policy refusal in [Sheets minimum](SHEETS_MINIMUM.md)
remains in force; this unit uses no alternate browser or transport. HTML fonts
remain browser-dependent. CSV is a values delivery, not an editable workbook or
a qualified CSV/XLSX import route.

[Sheets recovery](SHEETS_RECOVERY.md) separately records the live-child calculation
interruption, retry and cancellation proof. Other operation/failure combinations,
broader application fidelity, Linux and Cloud execution, signing, clean-machine
lifecycle, complete notices, owner acceptance and the full Local/Cloud release
remain separate requirements. The retained upstream Arabic-caret failure is
not cleared by these checks.
