# Local native video contract

The source runtime supports `video.create` and `video.edit` through the same durable
CLI/MCP job contract as Image and Vector. They currently require a FilmCraft 0.20.1
CLI on the private runtime PATH. The base source revision is
`cedf0c9bd060eb06a977d532402be2097c9ebe42`. The maintained `dobe-video` source build takes
precedence when present. The CLI package builder includes it when supplied with
`--video-engine`; Image and Vector remain the default package subset. Hosted admission remains disabled until its worker pack, migration and
hosted acceptance are completed together.

`video.create` accepts an even `width` and `height` between 16 and 1920, integer
`fps` of 24, 25, 30, 50 or 60, and three named lists:

- `clips`: 1–100 picture clips. Each has `name`, `start` and `frames`, plus exactly
  one of `asset` (an imported project asset ID) or `color` (`#rrggbb`). Media may
  specify `source_in`. Optional `transition` adds an incoming cross dissolve in
  frames, at most 120 and no longer than the clip.
- `audio`: up to 32 separate audio placements. Each has `name`, imported `asset`,
  `start`, `frames`, optional `source_in` and optional `gain_db` from -60 to 12.
  Sound embedded in picture clips is not automatically placed; import and place
  it explicitly as audio when needed.
- `titles`: up to 32 editable native text graphics. Each has `name`, `text`,
  `start`, `frames`, `x`, `y`, `size` and `color`. Positions are baseline pixel
  coordinates. Text uses Inter Regular. Glyph coverage remains unqualified and
  the returned validation explicitly says so.

All timing uses integer sequence frames. Each list is ordered without overlapping
items on its track. Names are unique across all three lists. The maximum timeline
is 36,000 frames. Output is a CPU-rendered H.264 MP4 with stereo 48 kHz audio.

A targeted edit takes an existing source revision and one to 100 edits:

```json
{
  "edits": [
    {"type":"text","name":"caption","text":"Final cut"},
    {"type":"trim","name":"ending","edge":"out","delta_frames":48},
    {"type":"trim","name":"caption","edge":"out","delta_frames":48},
    {"type":"gain","name":"music","gain_db":-12}
  ]
}
```

At 24 fps, the two trims extend an ending and its title by two seconds. Trims are
regular, not ripple edits. A clamped trim fails rather than silently accepting a
different duration. Source native files, media and earlier exports stay immutable.
Edits address stable native clip identities; they do not rebuild the timeline.

The revision includes `native/document.fcproj`, a named clip map, a sequence
inspection, a dependency manifest, the MP4, its native probe and three sampled
PNG frames. Native media paths are relative to the project and restricted to its
retained assets. External references, proxies, custom scratch destinations and
ingest settings are refused. Cold processes reopen the native source, export,
inspect and reproduce sampled frames. Publication checks exact requested timing,
text, dimensions, rate, duration, missing media and unaffected clip identities.
This is a bounded native contract, not support for arbitrary imported editor
projects or every FilmCraft command.

Local acceptance uses a real source-built engine, network denial and independent
FFmpeg/FFprobe oracles. The oracles are test tools, not production dependencies.
A synthetic 15-second timeline was revised to 17 seconds, exported, imported and
edited again through separate durable worker processes. All 360/408 frames decoded;
color endpoints, a linear-light dissolve, changed caption pixels, preserved picture
pixels and audio levels were measured. This establishes technical behavior. It is
not aesthetic approval, clean-machine packaging, Linux or Cloud qualification.

The unsigned dev.33 macOS package also passed installed native creation, scoped
revision, portable re-edit, update/rollback and reinstallation. Cancellation
stopped an observed native Video process group without publishing. Killing the
fixture supervisor stopped its orphan engine; explicit reconciliation published
nothing, and the restarted service completed another native revision. Independent
frame/audio measurements passed on those installed outputs. Fixture services
were removed while retaining projects and evidence.

The maintained engine's automation tests (29) and CLI tests (19) pass, as does
format checking. Strict Clippy currently stops in unchanged upstream HEVC filter
code under Rust 1.100; this is an open source qualification gate, not a passing
full-workspace check.

Remaining Video work includes complete public identity coverage, typography
beyond the static Inter profile below, broader media fidelity and adversarial cases, final
release qualification, and matching Linux x86-64/Cloud acceptance. Development
package evidence does not establish signing or clean-machine/reboot behavior.

## Static title glyph qualification

Successful `video.create` and `video.edit` revisions now require native glyph
diagnostics before rendering. The maintained FilmCraft query
`graphics.textDiagnostics` uses the same evaluated text layout as the renderer.
It reports actual glyph IDs, UTF-8 cluster offsets, font faces, missing-family
resolution, synthetic styles and overflow. Every used face must have bytes
identical to the pinned Inter Regular font compiled into the engine. A matching
family name is insufficient.

The admitted profile is a single static point-text layer per title, using Inter
Regular without per-character styles, synthetic bold/italic, case conversion,
vertical layout or paragraph boxes. Animated title parameters and multiple
graphic layers are refused because one layout cannot qualify those timelines.
Missing characters, fallback fonts and unsupported profiles fail the job rather
than publish a successful revision with a misleading title. The previous accepted
revision remains available.

`native/title-diagnostics.json` records each named title's diagnostic. Two fresh
native processes must produce the same diagnostic, alongside the existing native
timeline, dependency and rendered-frame checks. Each successful revision records
`glyph_coverage_verified: true`, its explicit static Inter scope, title count and
`title_diagnostics_cold_reopen_equal: true`. A timeline without titles records an
empty diagnostic and a zero title count. The broader engine capability remains
conservative; this is not arbitrary typography qualification.

The local [glyph qualification record](../qualification/VIDEO_GLYPHS.md) includes
the reproduced missing-character defect, an offline source build, installed CLI
jobs, portable Unicode revision and refusal of altered imported projects even
when their saved validation receipts claim success. No paid image/video model,
editor window, remote worker or deployment is involved.

## Replace a picture clip without rebuilding the timeline

`video.edit` also accepts a `media` edit naming an existing picture clip and an
asset imported into that same project:

```json
{
  "edits": [
    {"type": "media", "name": "ending", "asset": "IMPORTED_ASSET_ID"},
    {"type": "text", "name": "final_caption", "text": "CHANGE THE RULES."},
    {"type": "trim", "name": "ending", "edge": "out", "delta_frames": 48},
    {"type": "trim", "name": "final_caption", "edge": "out", "delta_frames": 48},
    {"type": "trim", "name": "bed", "edge": "out", "delta_frames": 48}
  ]
}
```

At 24 fps this adds two seconds; a 15-second timeline becomes 17 seconds. The
replacement footage must already contain the desired motion and final hold.
This operation replaces the picture source; it does not synthesize frames or
infer a freeze-frame instruction. Revise an editable Motion source first when
its animation must change, render it, and import that movie for replacement.

The operation retains the clip ID, name, label, source offset, effects and
timing. Explicit trim edits may change timing in the same request. Other clips
and transitions remain unchanged. Each request may replace a named clip once.
The source must be finite video long enough for the clip. Titles, audio targets,
linked clips, reverse/retimed clips, frame holds, multicamera clips and custom
label colors are outside this replacement contract. Unsupported media, short
sources and clamped requested trims cannot publish a successful revision.

The native command's replaced IDs, source item, short-media report and source
offset are checked. After saving, the runtime verifies the authorized relative
asset reference, the final source range and every unaffected target-clip field.
Existing glyph, media, cold-reopen and export checks still apply. Original media
remains in the portable project, so the source revision and prior exports are
available after the change.

A replacement can reuse an asset already retained in its source revision. The
runtime first checks the asset's project authorization and authoritative blob,
then requires the retained file to be regular, unlinked and byte-identical. It
never overwrites a different retained file. This reuse is enabled only for Video
edits; other materialization calls retain exclusive-creation behavior. Importing
a portable project grants access to its retained files, but does not recreate
the old project's asset identifiers. Import a replacement into the new project
and use its returned identifier.

The [shot revision qualification](../qualification/VIDEO_SHOT_REVISION.md)
records the real four-engine suite, native property preservation, complete
15/17-second decodes, transitions, audio, exact repeated pixels, portable
replacement and rejected cases.

## Presentation timing in the maintained source

The maintained exporter preserves rational video timing in MP4/MOV presentation
metadata. Its movie timebase is a common multiple of the video and audio
timebases when that fits a signed 32-bit value. Otherwise it uses the largest
interoperable multiple of the video timebase. Video boundaries remain exact;
audio edit durations then round by at most half a movie tick, below one
nanosecond. The signed limit matters because common players read the unsigned
container field as signed. Unsupported video timebases fail explicitly.

Audio edit lists retain encoder priming and end at the requested mixed sample
count. Encoded tail packets remain available for decoding, but their padding
does not extend presentation. The previous millisecond movie timebase shortened
fractional video durations, and the previous automatic audio edit included flush
padding. Neither correction changes the coded picture or sound payloads.

This source correction is separate from installed dev.42 qualification. The
private Animate handoff now preserves the exact stored f32 rate, explicitly pads
odd or tiny stages, and supplies the exact native soundtrack length. Its bounded
container inspector validates every sample mapping, rational presentation timing,
AAC priming/edit endpoint and H.264 NAL boundary before returning an encoded file.
A separate private native command now decodes every selected H.264/AAC packet,
including decoder flush and audio priming/padding, and checks exact output counts.
It uses raw software decoders with explicit bounds and propagated errors; ordinary
playback concealment is not accepted as integrity evidence. The runtime binds the
result to the unchanged container with SHA-256. Private handoff processes now
inherit a kernel file-write cap of at most 512 MiB and tightened CPU limits, with
live native cancellation and process-group cleanup qualified locally. Durable
Animate video publication and its full worker cancellation journey remain unfinished.
Browser playback, Linux and installed lifecycle qualification remain open.

The native `audioSampleFrames` export setting permits an explicit sample count
within one sample of the range's usual floor-rounded length. It leaves picture
timing unchanged. This resolves the nearest-rounded endpoints of a previously
rendered soundtrack, including partial movie ranges. Omitting the setting keeps
the existing behavior; larger adjustments fail. The handoff extends only its
generated audio clip to the WAV's exact sample boundary because ordinary
`timeline.place` snaps clip ends to the picture grid. A cold native save must
preserve the complete generated project. This does not edit a caller's project
or change the public Video authoring schema.
