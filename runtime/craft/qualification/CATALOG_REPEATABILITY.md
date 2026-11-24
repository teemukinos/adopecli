# Installed seventeen-application execution and repeatability

Date: 18 November 2026. This is local macOS ARM64 qualification of a specific sealed rehearsal package. It is not a complete minimum-contract audit, owner visual acceptance, signed release or Cloud qualification.

## Result

Eighty-six consecutive native jobs succeeded on their first attempt. Two complete rounds each created and revised a fresh project in all seventeen application families, then ran the additional calculation, geometry and delivery operations listed below. Those 84 jobs used the installed CLI's stdio MCP endpoint and a separate durable worker. After a clean worker restart, two additional Material map exports succeeded through the installed CLI. No retry or omitted family contributes to the passing sequence.

Seventy-one exported-artifact comparisons passed across the rounds. PNGs matched as decoded pixels. PDFs matched when rendered independently by Poppler at 96 dpi. MP4, WAV, SVG, CSV and OBJ deliveries matched byte for byte. Inspect's exact report and annotation bytes also matched across both rounds. Native containers are not claimed to be byte-deterministic: fresh asset identifiers and container metadata differ. Every original difference is retained in the comparison evidence; no result was rewritten to obtain equality. Vector PNG container bytes differ, but their decoded pixels match.

A further 106 assertions cover native cold reopen, changed native content after the requested revisions, retained source assets, output integrity after later revisions, and independent checks of CAD dimensions, spreadsheet calculations, evidence annotations, media streams and texture/material maps. These assertions supplement each operation's native validator; they do not establish every application's full minimum contract.

## Workload

| Family | Fresh creation and targeted revision | Additional delivery or independent observation |
| --- | --- | --- |
| Image | Transparent layered artwork, exact embedded asset, Unicode caption, opacity and mask density revision | Matching PNG pixels; existing separate layered Image minimum qualification remains applicable |
| Vector | Named rectangle and text; rectangle position and size revision | Matching SVG bytes and decoded PNG pixels; this workload does not revise text |
| Video | Three clips with trims, transitions, caption and music; revised caption and longer ending | Independent 160 × 96, 24 fps streams: 360 frames become 408; audio remains present; matching MP4 and sampled frames |
| Motion | Media, text and shape layers; caption and opacity keyframe revision | Matching rendered MP4 and sampled frames |
| Audio | Three tracks with imported clips, trims, fades and gains; opening clip gain revision | Matching WAV; native validation retains source hashes and verifies PCM reopen |
| Photo | Synthetic DNG and PNG, exposure, white balance and crop; RAW exposure revision | Matching photo exports; no general camera RAW fidelity claim |
| PDF | Two-page text/vector document; title text and color revision | Matching native page previews and independently rasterized PDF pages |
| Layout | Two-page styled text document; targeted Unicode text revision | Matching previews and independently rasterized PDF pages; untargeted page preservation remains checked by the adapter |
| Interface | Component, instance, frames and editable text; heading replacement | Matching previews; native validation checks untargeted roots and unrequested fields |
| Animate | Editable two-keyframe scene with shapes and text; targeted text replacement | Matching frame previews; this workload does not qualify interactive playback or video export |
| Texture | Plane with editable color and roughness layers; roughness source revision | Five matching map exports per round; changed roughness pixels verified |
| Material | Editable graph source; red-to-blue parameter revision | Finite native cook and 16-bit PNG map export; independent blue-map size and color check |
| Write | Paragraphs, styles, table, comments and embedded picture; targeted Unicode replacement | PDF export with explicit bundled font substitutions; independently rasterized pages match |
| Slides | Editable five-slide production proposal; targeted text replacement | Five matching slide previews; this workload does not qualify imported-picture editing |
| CAD | Editable 120 × 80 × 12 mm panel; width/height parameters become 150 × 90 | Explicit solve, solid regeneration and OBJ export; eight mesh vertices independently bound 150 × 90 × 12 mm |
| Sheets | Editable production budget with formulas; quantity changes from 10 to 12 | Explicit calculate and CSV export; subtotal 230, tax 55.2 and total 285.2 verified |
| Inspect | Explicitly authorized, job-owned JavaScript fixture; evidence-bound annotation | Static analysis only; input is never executed, report bytes persist, and resolved annotation matches exact evidence |

The fixtures are small engineering workloads. They are not a coherent customer campaign or a professional-design quality acceptance set. The recorded unsupported and pending flags in each manifest remain authoritative.

## Exact artifact and local evidence

The package is the retained private installation from the recoverable-uninstall qualification, version `0.1.0-guarded-launch-qualification`. Source at the start of this unit was local commit `caf33bc0c8a7cdb754143e175e59f55b73ad8c64`. No runtime or engine code changed during this unit.

- Native guard SHA-256: `0fe9dde1adf5b1db2735f1c1c4140584bbcaecb4044134e9e17127aedaa8aaa0`.
- Payload seal SHA-256: `7d7ea4bac30f40036fe782985b0fa1787cc8b22a1d29852710e57091c3917ccf`.
- Full native payload verification passed before and after execution, with 3,309 entries. Signatures are rehearsal signatures; publisher authentication remains false.
- Machine-local evidence directory: `catalog-repeatability-h_mscubk` under the private qualification root. The ignored `.verify/catalog-repeatability/checkpoint.json` records its absolute path and final hashes.
- `selection.json` pins both historical parameter sources and their manifest hashes. All 144 selected source files were checked against their recorded size and SHA-256 before use. Fresh asset imports replace only exact source asset identifiers; expected native hashes bind the actual newly created revision.
- `requests.jsonl`, `jobs.json` and `material-export-commands.json` retain actual MCP/CLI requests and results. Every successful operation has a portable checkout with a verified manifest.
- `comparison.json` records all 71 comparisons and every observed container difference. `semantics.json` records 106 assertions. `independent-pdf/` retains independent PDF rasters.
- Both private workers and the MCP process exited normally. All 86 observed native attempt process groups are absent. No login registration, installed service, global MCP configuration, provider or remote repository changed.

The sum of measured submission-to-terminal intervals is 114.93 seconds; median 1.29 seconds and maximum 3.54 seconds. These include worker scheduling and status polling. They exclude setup and independent verification. CPU consumption, peak memory and billing cost were not measured in this workload, so these intervals must not be marketed as compute cost.

## Preserved failures and corrections

The first source-selection probe assumed the wrong benign JavaScript fixture text and stopped before any job submission. Inspection identified the retained fixture containing a literal HTML-like string; only static analysis was authorized and performed. The corrected selection retains and hashes that exact local input.

The first execution harness stopped before submitting jobs because its helper parameter collided with the project-name argument. Its private worker and MCP process stopped normally. That harness error is not a product job failure.

The next execution attempt completed seven jobs, then correctly rejected CAD OBJ delivery with `CAD mesh bounds differ from requested dimensions`. Parameter editing and sketch solving do not regenerate the solid. The workload omitted the existing explicit `cad.solid` operation. The failed job published no result revision. Its evidence remains in `catalog-repeatability-maghzuds`; it is excluded from the later 86-job passing sequence. The passing workload includes solve, solid regeneration and export without weakening mesh validation.

Native guard verification also refused an inspection invocation with inherited heredoc input because it could not establish standard-stream ownership. Verification succeeded with explicitly owned standard streams and the same clean environment used by the workload. No guard check was bypassed.

## Remaining release work

This establishes representative all-catalog execution and repeated output equality on one exact local artifact. It supplies workload evidence toward V26's consecutive-job requirement. It does not close V26's full agreed acceptance gate or the complete release objective by itself.

Remaining work includes broader operation-specific minimum contracts, portable import and revision across supported hosts, owner visual/audio acceptance and the coherent campaign fixture, remaining packaging/update/migration requirements, complete dependency notices and redistribution rights, publisher signing/notarization, clean-machine/reboot/security-baseline checks, Linux x86-64 execution, full seventeen-application hosted admission and isolation, and real-provider commercial qualification. Current Cloud admission remains narrower than the local catalog.
