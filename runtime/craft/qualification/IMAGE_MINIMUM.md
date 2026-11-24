# Installed Image minimum contract — 18 November 2026

Three real Image jobs pass through the installed, sealed macOS CLI: layered
creation, a targeted revision and another revision after portable import into a
second fresh state. Two deliberately invalid edits fail without publishing a
revision or changing the project head. These results qualify the bounded fixture
below; they are not a complete Image release decision or full V08 acceptance.

## Artifact and execution boundary

- Source: `c2b0200eb09bfd266c3677112bce8f3d5b3a21d1`.
- Installed package: `0.1.0-sealed-signing-qualification`, macOS ARM64.
- Native Image engine: `dobe-image 0.23.1 (45066c482)`, using the maintained
  [Image lock](../engines/image.lock.json) and its patches.
- Guard SHA-256:
  `d586ca6c1c3004da2d955e1043a9845c3ec4cabd6cddc180ce9f73d7cbe155b0`.
- Payload seal SHA-256:
  `6d3d73538429d766eabdf8d62cbb9f08a7ff33bf5eb0509b7d967fdba2842781`.

The installed native guard verifies the complete payload before and after the
jobs. Each command uses a fresh process, a private state and a minimal system
PATH. Runtime and engine processes use the package's network-denial policy.
No editor, provider, global MCP configuration or installed service is involved.
This is an ad-hoc signing rehearsal on a development Mac, not an authenticated
publisher, clean-machine or Linux run.

## Fixture and independent checks

The 640 by 400, 8-bit RGB canvas has a transparent background and three named
layers: `panel`, `logo` and `caption`. The panel is `#204080`, at 50 percent
opacity, masked to `[20, 20, 200, 160]`. The 64 by 48 PNG logo has four asymmetric
color regions and is placed at center `[420, 100]`, at 100 percent scale. The
caption uses bundled Inter at 22 points with Latin, accented Latin, Greek and
Cyrillic characters: `Editable image / Åäö Ω Ж`.

Creation checks read the actual `.pcraft` ZIP manifest and PNG pixels, rather
than accepting the worker's validation flags alone. They establish:

- A raster background, editable fill, embedded smart object and editable text.
- Byte-identical retained source PNG and exact logo pixels at canvas rectangle
  `[388, 76, 452, 124]`.
- Transparent pixels outside the mask and exact RGBA `(32, 64, 128, 128)` at its
  included corners; the first excluded corner remains transparent.
- Actual shaped-glyph coverage, with no missing glyphs, recorded in
  `native/fonts-manifest.json`.

The first revision changes only the caption text, panel opacity to 25 percent
and mask density to 50 percent. Layer IDs and order stay unchanged. Background
and logo records, embedded source bytes and rendered logo pixels stay unchanged.
The original exported revision retains every file hash. Inside-mask alpha is
64; outside-mask alpha is 32, matching the engine's partial-density semantics.

The exported project then imports into a second fresh state. A further edit sets
the panel mask to `[40, 40, 120, 80]`, density to 100 percent and opacity to
100 percent. Boundary pixels and alpha match the new rectangle. Caption and
logo records remain unchanged, and the original asset hash remains intact.
All three native saved composites exactly match their separately cold-reopened
PNG exports. The import uses the same installed package and bundled fonts; it
does not establish cross-machine or cross-platform portability.

An edit naming an absent layer returns `engine_failure` with
`edit names an unknown native layer: missing`. An unsupported Unicode codepoint
returns `engine_failure` with `text contains missing glyphs; choose a supported
font or revise the text`. Both jobs are terminal failures. Neither publishes a
new revision, and the project record remains identical across both attempts.

The assistant inspected the original and final PNGs directly. The asymmetric
logo retains its position and appearance, the caption revision is visible without
replacement boxes, and the final panel has the requested smaller mask. Numeric
alpha checks establish transparency independently of the viewer's black
background. This is technical visual inspection, not owner design acceptance.

## Retained evidence

Machine-local evidence identifier: `image-minimum-vldb0htp`. Its `evidence.json`
binds every delivered file hash, native job record, glyph report and payload
verification. `commands.json` retains every command, exit status and duration.
Inputs, request JSON and all three native/PNG exports remain available. The
ignored runtime checkpoint is `.verify/image-minimum/checkpoint.json`.

PNG SHA-256 values:

- Original: `fb00cdc579b04fea24304b3281fd7ea8ec51d90152b7554b705c0c523084582d`.
- First revision: `eecf5a02329d1e80961bf7d7ca3ce53662292dbaa2372ed93f71419636863d16`.
- Imported revision: `7c3ccf3ecd8ca2ca7a61e06a55aec483c2b0b17372bdb42fae0f57d910859d8d`.

An earlier probe, `image-minimum-ultmr48k`, incorrectly required every native
blob to remain unchanged after editing text. Text-cache blobs necessarily changed;
unrelated layer records and the embedded source did not. That failed probe is
retained. The corrected probe compares the embedded source and independent logo
pixels, while allowing the requested text revision. No product fix was needed.

## Remaining acceptance

This evidence covers layered composition/import of a PNG, text/mask/layer
revisions, editable native delivery and PNG cold reopen for this fixture.
It does not cover JPEG/SVG placement, arbitrary external native documents,
ICC-profile fidelity, higher bit depths, wider font coverage, native-format
interchange, vector fidelity, hosted execution or the required 30 consecutive
jobs spanning the full catalog. The existing `image.adjust` and `image.revise`
contracts retain their own earlier qualification; this run exercises
`image.create` and `image.edit` only. Font redistribution, complete dependency
notices and product release approval remain separate gates.
