# Editable project handoff across the native catalog

Date: 18 November 2026. This qualifies two successive local handoffs across all seventeen application families on the sealed macOS ARM64 rehearsal package. It does not establish cross-platform, hosted or owner visual acceptance.

## Result and method

Thirty-four complete project bundles import into two independent, initially empty states. Each state receives all seventeen native families. Fifty-two native jobs then succeed on their first attempt, including actual revisions, CAD solving and solid regeneration, spreadsheet calculation, graph cooking and final exports. No project is recreated from a specification, and no source asset is separately reimported through the asset API.

The first handoff starts with the verified creation checkouts from the [catalog repeatability workload](CATALOG_REPEATABILITY.md). The installed MCP endpoint imports each bundle as a new project. Import correctly reports only `bundle_integrity`; `native_cold_reopen` remains false. The importing client exits. The run-owned incoming directory moves, making every original import path unavailable. A new MCP client and separate worker revise each imported native project and produce its deliveries.

All 39 exported-artifact comparisons against the original creation/revision workload pass. PNGs match as decoded pixels. PDFs match when independently rendered by Poppler at 96 dpi. MP4, WAV, SVG, CSV and OBJ deliveries match byte for byte. Inspect's exact report and annotation bytes also match. Container differences remain recorded separately; native files are not claimed to be byte-deterministic when identifiers or metadata differ.

The second handoff starts with the **already revised and delivered** projects from the first handoff. It imports those final bundles into another empty state, exits the importing client, moves its input directory and starts a new client and worker. A different targeted revision succeeds in every family. This exercises retained revision history and final exported projects, rather than repeating only initial project creation.

The combined qualification has 244 named assertions, in addition to checking every declared artifact size and SHA-256. Original imported revisions remain byte-accurate and unchanged after later revisions. Both states contain exactly seventeen import jobs, seventeen projects, zero separately imported asset records and twenty-six successful native jobs. All fifty-two native attempt process groups are absent after shutdown. Both workers and all importing/revision clients exit normally.

## Second-handoff changes

| Family | Revision after importing the delivered project | Observed result |
| --- | --- | --- |
| Image | Change the caption again and lower mask density | Native text observation and changed PNG pixels; embedded source retained |
| Vector | Move the named rectangle to x=50 | Exact SVG geometry changes; caption remains unchanged |
| Video | Change the caption and extend the ending and title by another 24 frames | Independent stream inspection finds 432 frames at 24 fps, or 18 seconds, with audio |
| Motion | Change caption and final opacity keyframe | Native property observation and changed rendered media |
| Audio | Change opening clip gain from −6 dB to −3 dB | Changed rendered WAV; source assets remain unchanged |
| Photo | Change RAW exposure from 1.25 to 0.5 | RAW output pixels change; untargeted PNG photo stays identical |
| PDF | Change the title to “Portable brief” | Independent PDF text extraction confirms the title; untargeted page pixels stay identical |
| Layout | Change the heading to “Portable café — 2026” | Independent PDF text extraction preserves Unicode; appendix pixels stay identical |
| Interface | Change component heading to “Portable workspace” | Native inspection contains the new text and native cold reopen passes |
| Animate | Change timeline text to “Portable workspace” | Native inspection and changed frame pixels |
| Texture | Change roughness from 0.75 to 0.5 | Roughness pixels change; base-color map stays identical |
| Material | Change the graph parameter from blue to green | Cook and 16-bit map export succeed; independent 32 × 32 green-map check passes |
| Write | Replace the previously revised Unicode span with “Portable craft” | Native document changes; independent PDF extraction confirms the new text |
| Slides | Replace the previously revised phrase with “portable sentence” | Native document changes and PNG export succeeds |
| CAD | Change panel parameters to 160 × 100 mm, then solve and regenerate | OBJ vertices independently bound a 160 × 100 × 12 mm solid |
| Sheets | Change quantity from 12 to 14 and calculate | CSV contains subtotal 255, tax 61.2 and total 316.2 |
| Inspect | Reopen the evidence annotation and change its text | New annotation remains bound to the exact unchanged source bytes |

Every native edit records a successful cold reopen. Operation-specific limitations in the returned validation remain intact. Native inspection is not a substitute for professional visual or audio acceptance.

## Refusals and preserved probe issues

Each state rejects a hash-corrupt Image bundle before publishing a project. Each also rejects an Image edit using the other project's Vector source revision. These four expected admission errors create no extra projects or jobs and do not change published revisions.

One second-handoff preparation probe used an incorrect Vector parameter shape and stopped before launching a client or worker. The actual Vector operation takes an `objects` mapping, not an `edits` list. The corrected probe preserves that registered contract. No product job failed and no adapter was changed.

The independent verifier initially could not find `pdftotext` on PATH. It then used the already-installed Poppler binary and its private library directory explicitly. No package was downloaded or installed, and no global environment setting changed. Write, Layout and PDF text extraction all passed. The completed native jobs were retained; they were not rerun because of this verifier setup issue.

## Artifact and evidence boundary

The exact package is version `0.1.0-guarded-launch-qualification`, retained from the recoverable-uninstall qualification. The source baseline for this unit is local commit `dcdce0be53e3ac2fbd3be025d04828d9aac5237f`. No runtime, engine, installed service, login registration or global MCP configuration changed.

- Guard SHA-256: `0fe9dde1adf5b1db2735f1c1c4140584bbcaecb4044134e9e17127aedaa8aaa0`.
- Payload seal SHA-256: `7d7ea4bac30f40036fe782985b0fa1787cc8b22a1d29852710e57091c3917ccf`.
- Full native payload verification passes before and after each handoff, with 3,309 entries. Publisher authentication remains false; this is a rehearsal package.
- First evidence directory: `catalog-portability-omus13zk`. Second: `catalog-rerevision-dmdawx3e`. Both are under the machine-local private qualification root. The ignored `.verify/catalog-portability/checkpoint.json` records absolute paths, exact hashes and the local repository verification outcome.
- `imports.json` retains input manifests, imported identities and integrity-only validation. `handoff-moved.json` records source relocation after the importing client exits. `requests.jsonl` and `jobs.json` retain actual MCP exchanges and job outcomes.
- `comparison.json` retains the 39 comparisons and original byte differences. `handoff-qualification.json` records the 244 assertions. The second directory retains explicit second-revision specifications and independently extracted PDF text.
- Every published native result and retained original has its own portable checkout. No remote action or deployment was performed.

The producer's historical state and evidence remain untouched. This proves independent local-state handoff with relocated bundle paths and retained dependencies. It does not prove operation on an unavailable original machine, a stock host or a different OS. Linux/Cloud portability, broader application minimum contracts, coherent campaign acceptance, remaining packaging/update/migration behavior, redistribution rights, publisher signing and commercial/deployment gates remain open under the full product goal.
