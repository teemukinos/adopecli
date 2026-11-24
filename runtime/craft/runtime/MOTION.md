# Native Motion production contract

The local runtime supports `motion.create` and `motion.edit` through the same
durable CLI/MCP journal as Image, Vector and Video. The maintained `dobe-motion`
engine builds from EffectCraft 0.24.1 at source revision
`582344dd4ef462362c02e56e3094de7af01847ab`, with the exact patch and build inputs
in `craft/engines/motion.lock.json`. Include its source pack with the local
builder's `--motion-engine` option. The unsigned dev.34 package includes Motion.
Hosted admission remains disabled until the matching worker, storage contract
and hosted acceptance are complete.

## Create an editable composition

`motion.create` requires `width`, `height`, `fps`, `frames`, `background` and
`layers`. Dimensions are even integers from 16 to 1920. Supported frame rates
are 24, 25, 30, 50 and 60 fps. Duration is 1 to 36000 frames. Colors use
`#rrggbb`. Layers are ordered from back to front, with 1 to 64 unique identifier
names.

Every layer requires `name`, `type`, `start`, `frames` and `position: [x,y]`.
Timing uses integer composition frames and must fit within the composition.
Layer types add these fields:

- `shape`: `shape` (`rect` or `ellipse`), `width`, `height`, `color`.
- `text`: `text`, `size`, `color`. The current face policy is Inter Regular.
- `media`: an authorized imported `asset` identifier and `format` (`png`, `jpg`
  or `mp4`). Still images and video retain their native footage references.
  An MP4 layer cannot extend beyond its source duration.

Optional `scale: [x,y]` uses percentages, `rotation` uses degrees and `opacity`
uses 0–100. Position bounds are ±8192 pixels, scale is 0.01–1000 percent,
rotation is ±36000 degrees, shape dimensions are 1–8192 pixels and text size is
1–512. Imported media dimensions are limited to 8192 in each direction. Files
must be regular, match their declared format and stay within project assets.

`animation` maps any of `position`, `scale`, `rotation`, `opacity` to a track:

```json
{
  "keys": [
    {"frame": 0, "value": [25, 30]},
    {"frame": 24, "value": [135, 30]}
  ],
  "interpolation": "linear"
}
```

Keys use absolute composition frames, including for layers that start later.
They must be ordered, unique and inside the layer's visible interval. Each
track admits 1–200 keys; the native composition admits at most 2000 keys.
Interpolation is `linear`, `hold` or `easyEase`. Animation replaces the static
value for that property.

## Revise named native layers

`motion.edit` requires a source revision and 1–100 `edits`:

```json
{
  "edits": [
    {"type": "text", "name": "caption", "text": "Final cut"},
    {"type": "property", "name": "block", "property": "position", "value": [80, 30]},
    {
      "type": "property",
      "name": "block",
      "property": "opacity",
      "animation": {
        "keys": [{"frame": 0, "value": 100}, {"frame": 24, "value": 25}],
        "interpolation": "easyEase"
      }
    }
  ]
}
```

A property edit replaces that entire static value or animation track. A static
replacement removes its previous keys. Duplicate targets in one request are
refused. Layer identities remain stable. After editing, every native field
outside the explicitly targeted property leaves must match the source, except
for the saved composition view. The source revision remains immutable.

## Deliverables and validation

Each successful job publishes a native `document.ecproj` (schema 2), editable
layer mapping, composition/property inspection, media fingerprints, H.264 MP4,
render metadata and sampled PNG frames. Referenced media travels with the
project, using relative `../assets/` paths. Local bundle import establishes
integrity only; a subsequent Motion edit validates its native document before
opening the engine.

Publication requires native save, cold reopen and save with all native
properties preserved; repeated sample renders in separate processes; unchanged
native and media hashes; and matching encoded dimensions, sample count and
frame timing. A bounded MP4 metadata reader checks the native H.264 output
without requiring FFmpeg or another engine at runtime. Independent acceptance
uses FFmpeg/FFprobe to decode all output frames and measure visible changes.

Arbitrary scripts, expressions, effect plugins, proxies, nested compositions,
3D layers, render queue destinations and external file references are outside
this contract. MP4 output is video-only; use the Video contract for qualified
audio assembly. The maintained native `text.diagnostics` command now inspects
the same `layout_doc` shaping path used by the renderer. Publication checks
nonzero glyph IDs, valid UTF-8 clusters and the exact compiled Inter Regular
face bytes, then repeats the diagnostics in a cold process after rendering.
Reports travel in `native/text-diagnostics.json`. Validation records
`glyph_coverage_verified: true`, `glyph_coverage_scope: static-point-text` and
the verified text-layer count, including zero for a composition without text.
This is a per-project result; broader engine glyph coverage remains unqualified.

Source text remains editable and transform animation remains supported. Foreign
source-text keyframes, character animators, rich character/paragraph runs,
paragraph boxes, vertical text, synthetic styles, case transformations and
variable axes are explicitly refused. Missing glyphs and fallback fonts fail
before export publication. Both native `expr` and inspection `expression`
fields are rejected before engine admission. Retained validation reports from
an imported project do not substitute for fresh native inspection.

This operation creates and edits native media under coding-agent direction;
it calls no paid generation model.

## Current evidence and remaining work

Local durable workers have produced PNG/JPEG/MP4 compositions with shapes,
editable titles, linear/eased/held keyframes, precise revisions, static property
replacement, portable re-edit and immutable source artifacts. Invalid timing
fails without publication or changing the project head. Independent decoding
and pixel measurements confirm changed captions, unchanged picture regions,
25-percent opacity and the requested revised position.

Installed dev.34 qualification also covers precise native revisions, portable
re-edit, rollback to dev.33 with newer history retained, reinstallation, observed
native cancellation, supervisor crash and orphan termination, explicit attempt
reconciliation, resumed editing and retained-data uninstall. The packaged MCP
retains fifteen `dobe_` tools; submitted Motion work survives client disconnect
and executes through a separate worker. These checks use bundled dependencies
and network denial on the development Mac.

This is a local technical contract, not aesthetic or complete release approval.
Complete upstream source qualification, typography beyond the bounded static
Inter profile, broader native fidelity, clean-machine/reboot, Linux x86-64 and
Cloud qualification remain open. The complete seventeen-application goal is unchanged.

The later [editable film suite](../qualification/VIDEO_SHOT_REVISION.md) qualifies
the first Effects target with actual rotation and scale keyframe revisions,
preserved layer IDs and unchanged native fields outside those targets. Three
portrait Motion shots carry an exact imported Vector mark. The revised ending
passes to Video as a new authorized picture source while its editable Motion
project remains in the delivery. This evidence uses shape/media layers and does
did not close Motion's separate text glyph or full-application qualification
gaps. The subsequent [Motion glyph qualification](../qualification/MOTION_GLYPHS.md)
records the bounded native text check and editable animated-title evidence.
