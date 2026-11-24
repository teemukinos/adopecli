# Whole-image adjustment and portable revision

Date: 19 November 2026. This qualifies the existing `image.adjust` and
`image.revise` entry points on the private macOS ARM64 package. The separate
[layered Image fixture](IMAGE_MINIMUM.md) covers `image.create` and `image.edit`.
Neither fixture establishes complete Image acceptance or arbitrary-format
fidelity.

## Reusable fixture

Run the fixture with the package's Python and a previously authenticated guard
verification record. The output directory must not exist.

```sh
"$PACKAGE/lib/dobe/python/bin/python3" -I -B \
  craft/runtime/tools/image_adjustment_acceptance.py \
  "$PACKAGE" /absolute/path/to/new-evidence \
  --expect-verification /absolute/path/to/verified-package.json
```

The fixture creates a small four-color, eight-bit PNG. It drives the public CLI
and stdio MCP with private state and no account, service registration, editor or
network access. Native work remains owned by durable jobs after each submitting
client exits. If a check fails, inspect its recorded job and native process
before deciding whether to resume; do not blindly repeat an uncertain attempt.

## Observed behavior

Thirty-one grouped checks pass over five native jobs: four successes and one
expected unsupported-depth failure. An oversized request also fails before
native execution.

- Neutral `image.adjust` retains every source pixel and the exact imported PNG.
- Positive brightness changes actual decoded pixels without darkening any
  source channel, while retaining dimensions, alpha and native layer identity.
- An explicit 64 × 48 to 32 × 24 resize reaches both requested dimensions and
  preserves the four interior colors and their placement.
- A fresh state imports the resized project. MCP submits a desaturation revision
  that retains the native layer and canvas and exports neutral pixels within
  one eight-bit channel level.
- The saved native full composite equals every pixel of the separately reopened
  PNG for all four successful deliveries. Every delivered file matches its
  manifest, and each revision retains the original asset bytes.
- A sixteen-bit PNG fails without publishing a revision or changing the project
  head. A width of 8,193 is refused before native work. Later jobs leave earlier
  native deliveries byte-identical.

All five recorded native process groups are absent afterward. Guard verification
matches before and after execution. The package and production runtime are
unchanged; this adds a reusable qualification fixture and its documentation.

## Exact artifact and coverage boundary

Candidate: `0.1.0-local-cloud-private.2`, built from `7ccba2f`.
DMG SHA-256:
`95e88a12dfc0e7912e160d772731afc7ebeb9742cd002a56e2d19d1123001f8e`.
The payload contains 7,063 entries and 176 source-bound runtime modules. Its
signature is an ad-hoc private rehearsal, not publisher authentication.

Machine-local evidence identifier: `image-adjustment-20261119`. The preceding
`sealed-catalog-20261119` fixture exercised 83 of the 85 native operation names;
these two additional operations complete that **name-coverage** boundary on the
same artifact. The source-bound Slides operation suffix is normalized only to
its corresponding registered operation. Name coverage does not establish every
parameter, format, resource boundary, failure mode or professional workflow.
The eleven separately registered construction, production and synthesis
operations are outside this 85-operation native catalog.

This fixture does not qualify wider color management, ICC profiles, sixteen-bit
editing, arbitrary layered inputs, every adjustment combination, cross-host
reproduction, owner aesthetic acceptance or Linux/Cloud execution. Complete
notices and redistribution rights, real signing, stock-host installation and
the remaining Local/Cloud release requirements remain separate gates.
