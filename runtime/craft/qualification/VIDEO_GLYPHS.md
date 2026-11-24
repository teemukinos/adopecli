# Video title glyph qualification

## Result and boundary

On 18 November 2026, the installed A dope CLI accepted three native Video jobs
and refused seven invalid jobs, with 30 local checks passing. All ten recorded
native execution process groups were absent afterward. The existing native
Graphics test group also passed all 32 tests, including the new glyph diagnostic
regression. Formatting passed for both changed Rust files.

This qualifies the current static Inter Regular title profile on this macOS
ARM64 machine. It does not qualify arbitrary fonts, animated typography, full
Video functionality, a finished campaign, Linux, Supabase workers, or a released
product. The package is an ad-hoc rehearsal, not publisher authenticated or
notarized. No editor window or global service was used.

## Reproduced defect

Before the change, the existing sealed installation successfully created a
640 × 240, 24 fps, one-second video with the title `Missing U+10FFFF` (the actual
unassigned code point, not those printed characters). Its rendered frame visibly
contained the missing-glyph box. The revision truthfully reported
`glyph_coverage_verified: false`, but still published the movie as a successful
job. The baseline project, output and receipt are retained separately.

The new adapter queries the native renderer's actual layout before exporting.
The native query reports the glyph IDs and faces used, not an independent font
lookup that could disagree with rendering. It compares font bytes against the
Inter Regular embedded in the pinned engine. The accepted profile excludes
fallback, missing characters, synthetic styles, rich text, animated parameters,
case conversion, paragraph boxes and vertical layout. It requires exactly one
text layer per title.

Successful revisions retain `native/title-diagnostics.json`, identify the
coverage scope and title count, and compare diagnostics from two cold native
processes. Stored diagnostics and prior success receipts are never accepted as
proof for an edited native project.

## Actual production and refusals

The three successful jobs created `NORTH / FORM`, changed it to
`Åäö / Ω / Ж — ffi`, and imported the portable project into fresh state before
changing the title to `Åäö / Ω / Ж — editable`.

Independent native JSON inspection established that the text revision changed
only the requested text value. Clip identities, timing, background, title style,
position and object mapping remained exact. Native PNG comparisons preserved
pixels outside the changed title. FFprobe independently confirmed H.264,
640 × 240, 24/1 fps and all 24 frames. The original portable checkout remained
byte-identical after the imported revision.

The seven refused jobs covered:

- U+10FFFF in a new title and in a revision.
- An imported project requesting an unavailable font.
- Imported Japanese text requiring a font outside the admitted Inter face.
- Imported synthetic bold.
- Imported animated text.
- Imported per-character font styles.

Each refusal published no result revision and left its accepted project head
unchanged. The five imported negative cases retained successful diagnostic and
validation receipts while updating the native file and its inventory hash. The
runtime rejected the actual native content despite those receipts. Every failure
was an expected terminal engine failure, not a cancellation or timeout.

The final frame was visually inspected: accented Latin, Greek and Cyrillic
characters and the em dash render clearly, without missing-glyph boxes. This
small title card is a typography specimen, not owner aesthetic acceptance or a
cinematic showcase.

## Build and package identity

FilmCraft remains pinned to source
`cedf0c9bd060eb06a977d532402be2097c9ebe42`, version 0.20.1. The maintained patch adds
the query and its regression test; the dependency lock and source revision do
not change. The exact new patch and patched-file hashes are recorded in
`craft/engines/video.lock.json`.

The real offline Rust 1.100.0 build used the pinned fonts, no default features,
the `dobe` feature, four build jobs, and the development profile. Compiler path
remapping and symbol stripping passed. The source build and package collection
took 128.48 seconds. This is elapsed build time, not measured inference cost or
production rendering throughput.

The built executable SHA-256 is
`86b470d363ebffdee1236c1ef46fb42a897fc0c1cb7db5d29e47dc29fdd29b28`.
The sealed package version is `0.1.0-video-glyphs-qualification`, with all
seventeen engine families retained. Only Video was rebuilt in this unit; the
other engines came from the existing local development package. The installed
Video adapter exactly matched the maintained source. Native guard verification
passed before and after every job sequence:

- Guard SHA-256: `66978d29b009f38ed5b0767d7298c538ae24f3cb0cbd401d3644ca7b7822841c`.
- Payload seal SHA-256: `503a097d5f4607842ca8807d41b30c3a6dd3d076ed609ba9a8c9489d514b784b`.

The new build records 247 Cargo compiler packages and their available notices.
Notice collection remains incomplete; binary linkage and redistribution are not
approved. Existing upstream full-workspace Clippy and broader release gates are
not replaced by the passing Graphics tests.

## Retained evidence and remaining work

The machine-local `video-glyphs` qualification checkpoint identifies the baseline,
source build, Cargo messages, dependency notice inventory, native tests, all CLI
commands, job records, portable projects, images, FFprobe result, source hashes,
repository checks and measurement. These generated fixtures are not part of the
portable public source package.

The next Video acceptance work remains the complete timeline/media minimum and
coherent campaign, followed by broader typography and adversarial fidelity.
Motion's separate typography gap remains open. Linux/Cloud runtime qualification,
actual signing and stock-host testing, complete dependency notices, and real
billing/provider qualification remain full-product release requirements. Nothing
was downloaded, pushed, deployed, or remotely tested in this unit.
