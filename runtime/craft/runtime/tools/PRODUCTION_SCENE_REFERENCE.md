# Complete scene contract

This reference describes the existing schema and renderer. It contains no scene
template, artistic parameters, or reference artwork. All listed fields are
required unless marked optional; unknown fields are rejected. Units are metres,
rotation values are degrees, colors are `#RRGGBB` converted from sRGB to linear.
IDs match `[A-Za-z][A-Za-z0-9_-]{0,63}`. Coordinates have three finite numbers in
[-100,100]; rotations are in [-360,360]. The document is limited to 256 KiB.

Top-level fields:

- `schema_version`: integer 1; `profile`: `"product-scene-v1"`.
- `policy`: exactly `{"network":"offline","media_generation":"disabled"}`.
- `render`: `width`, `height` (integer multiples of 8, 64–2048), `samples`
  (integer 1–512), `seed` (integer 0 through 2147483647).
- `camera`: `location`, distinct `target`, `lens` (18–200 mm), `fstop` (1–32).
  Camera points at target. Depth-of-field focus distance is distance to target.
- `world`: `color`, `strength` (0–2).
- `materials`: 1–32 objects, each with unique `id`, `color`, `roughness`,
  `metallic`, `transmission` (each 0–1), `ior` (1–2.5). Optional `coat` (0–1),
  `bump` (0–0.002 m), `bump_scale` (1–20000). Bump uses procedural noise,
  fixed strength 0.25 and noise detail 2; it does not supply a color texture.
- `objects`: 1–128 objects. Common fields: `id`, `kind`, `material` (existing
  material ID), `location`, `rotation`. IDs are unique. Additional fields depend
  on kind, listed below.
- `lights`: 1–16 rectangular area lights. Each has unique `id`, `location`,
  distinct `target`, `color`, `power` (0–10000 W), `size` and `size_y`
  (0.001–20 m). Light IDs cannot collide with object IDs. `Camera` is reserved.

Object kinds and their additional fields:

| Kind | Fields and limits |
| --- | --- |
| `box` | `size`: three full side lengths, each 0.0001–50; `bevel`: 0 through half the smallest side |
| `cylinder` | `radius`: 0.0001–25; `depth`: 0.0001–50; `bevel`: 0 through min(radius, depth/2) |
| `sphere` | `radius`: 0.0001–25 |
| `lathe` | `profile`: 3–128 `[radius,height]` points; radius 0.00001–25, height -50–50 |
| `text` | `text`: 1–256 printable ASCII characters or newlines; `size`: 0.0001–1; `extrude`: 0–0.01 |

Boxes, cylinders and spheres are centered at location. Cylinder axis is local Z. Lathe rotates the
profile around Z with 128 segments and caps the ends. Box/cylinder bevels have
six segments. Cylinder, sphere and lathe polygons are smooth; box polygons are
not. No boolean, hollow-wall, volume, arbitrary mesh, texture-file, font-selection,
or per-object visibility fields are supported.

Text uses packed Archivo, centered horizontally and vertically. Its initial
surface is the local XY plane, facing +Z. For example, rotating X by 90 degrees
faces the text toward -Y; this is a coordinate convention, not a scene template.

Rendering uses CPU Cycles, eight threads, denoising, no adaptive sampling,
12 total bounces, eight transmission bounces, AgX, and an 8-bit RGBA PNG. Each
successful creation includes a fresh-process native reopen check. The tool does
not claim visual acceptance: inspect the returned image against the actual brief.

For engine/schema changes, the authoritative files remain
`studio_runtime/production_schema.py` and `production_blender_engine.py`.
