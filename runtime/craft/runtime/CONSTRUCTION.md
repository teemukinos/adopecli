# Dobe Construction

Construction builds editable artwork, rendered animation, video assemblies and
interactive animation inside the existing Dobe runtime. The model supplies a
closed, versioned document; creative engines create the native objects and render
the deliverables. There is no image/video model route, shell command field or
user-supplied Blender/Rive program.

The implementation reuses the current Store, worker, leases, process supervisor,
immutable revisions, asset imports, CLI and MCP server. It does not add a second
queue, service, database or editor. The first implementation is qualified on this
Mac with the pinned supporting binaries in `construction_data/support.json`.
It is not a Linux or hosted-worker qualification.

## Commands and lifecycle

```sh
dobe construct plan --spec construction.json
dobe create-project "Constructed artwork"
dobe submit PROJECT construct.create --parameters create.json --key create-1
dobe worker --once
dobe job JOB
dobe checkout REVISION portable-directory
```

`create.json` is `{"document": <construction document>}`. The submitter can exit
before the worker starts. Use the existing `limits` command and a suitable submit
`--timeout` for long frame renders. The acceptance run uses a 7,200-second wall
budget, 14,400 CPU seconds and 8,192 MiB for the long revised ring render. These
are explicit local budgets, not promises about production capacity.

`construct.create` authors sources and look frames. `construct.render` requests
final outputs, for example:

```json
{"outputs":[{"component":"intro","format":"mp4"}]}
```

A Blender PNG may include a zero-based `frame`. The `native` format checks the
saved native source. A final render opens the saved project; it does not rebuild
it from an unrelated template. `construct.inspect` and `construct.verify` reopen
supported native profiles and write readback evidence. Technical verification
always leaves `creative_status` as `review_required`.

Use `dope_plan_construction` over MCP for the same read-only plan. Submit all five
operations through the existing `dope_submit_job`. The CLI and MCP call the same
validation and execution code. Plans do not submit work or claim visual quality.

## Construction document

```json
{
  "schema_version": 1,
  "policy": {"media_generation":"disabled","network":"offline"},
  "components": [
    {"id":"poster","engine":"image","parameters":{}},
    {"id":"edit","engine":"video","parameters":{},
     "inputs":{"00000000000000000000000000000000":{
       "component":"poster","artifact":"exports/document.png"
     }}}
  ]
}
```

The empty parameter objects above illustrate graph structure, not a runnable
recipe. Complete fixtures are in `fixtures/construction/`. Each profile validates
its native parameters. IDs remain stable. The graph rejects duplicate IDs,
cycles, missing dependencies, unsafe paths, unknown properties, oversized input
and any policy that enables network access or media generation.

`inputs` binds a component-local asset ID to a declared artifact from another
component. External assets use the existing project-scoped `import-asset` flow.
Source revisions retain imported bytes. Component manifests hash every published
file. Revisions verify those hashes before opening sources. Unchanged components
are reused; dependencies are invalidated by the referenced artifact's hash,
not by an unrelated log or metadata change. A video/motion refresh reuses the
native timeline and reopens its portable media references.

## Editable profiles

- **Image:** existing Dobe Image layers, native text, embedded assets, masks and
  supported layer properties. Existing named layers can be revised without
  changing native IDs or unaffected content. Native `.pcraft` files and PNGs are
  preserved. Structural layer edits outside the maintained adapter are refused.
- **Video:** existing Dobe Video clips, titles, source trims, audio and native
  timeline. Text and clip-end revisions preserve native identity. A changed linked
  image refreshes the render without reconstructing the native timeline. Native
  `.fcproj` files, media, sample frames and H.264 exports are preserved.
- **Blender:** general 2D composition from groups, planes, native editable Bezier
  paths/ellipses, native text, packed images, gradients, noise and independently
  adjustable glow. Typed transforms, rectangular masks and scalar keyframes are
  supported. Root coordinates are pixels from the upper left; child coordinates
  are local offsets. Rotation is in degrees. Native `.blend` files pack fonts and
  images. The adapter cold-checks geometry, colors, parent identity and evaluated
  keyframes. This profile does not claim general 3D modeling support.
- **Rive:** script-free RML with stable native IDs, text and shapes, numeric state
  input, native listeners and animated transitions between typed poses. Rotation
  uses Rive's radians. Saved RML, compiled `.riv`, a reduced-motion `.riv`, fonts
  and a portable local web player are delivered. The host player implements hit
  testing, pointer/touch, keyboard and numeric data input. It deliberately disables
  duplicate native browser listeners; the `.riv` also retains native listeners for
  other integrations. Keyboard behavior belongs to the delivered web host, not
  to a claim that every Rive platform implements keyboard access. Reduced motion
  uses a separately compiled zero-duration transition variant.
- **Vector, Motion and Animate:** existing native creation adapters can participate
  in a graph. General construction edits and all cold-reopen operations for these
  profiles are not yet qualified. Plans report their smaller supported operation
  set. Unsupported operations fail explicitly; they never silently flatten or
  rebuild an entire document. These maintained engines retain their independent
  existing Dobe operations.

A group supports transform keys. Apply opacity or masks to painted children.
Rive pointer targets in this profile must be shapes. The web player supports
Arrow Left/Right to choose among targets, then Enter/Space to activate one.
Interactive state transitions are real native interpolation, not CSS animation.

## Revisions and output ownership

```json
{
  "document_sha256":"EXPECTED_DOCUMENT_HASH",
  "edits":[{
    "component":"intro","action":"set",
    "path":["parameters","objects",4,"text"],
    "before":"Imagination. Executed.","value":"Built to be revised."
  }]
}
```

Submit with `construct.edit --source REVISION`. Changes require an exact document
hash and exact previous value. Components may be explicitly added or removed.
For new imported assets, add `"import_assets":["PROJECT_ASSET_ID"]` to the edit
request. Linked artifact aliases do not need this list. An engine change requires
a new component ID. Original revisions remain immutable.

Blender edits reopen the saved file. Text/color edits update existing objects;
other explicitly changed objects are reconstructed individually while retaining
their stable IDs. Unchanged objects are checked at the same comparison frame.
Derived final renders are invalidated when source changes. Rive edits preserve
stable object IDs and verify the previous saved RML before compiling the revised
source. Unsupported native edits fail without publishing a new revision.

Exports include `construction/document.json`, `construction/manifest.json`, native
sources, fonts/notices, inputs, render outputs and operation logs. The manifest
records source hashes, adapter hashes, engine pins, component actions and actual
verification scope. The typed document is authoritative. Importing arbitrary externally edited native
projects does not synchronize them back into this schema. The ordinary Dobe
`project.json` additionally owns the complete
portable bundle. Importing that bundle checks integrity; a subsequent construction
verification performs the native cold reopen.

## Execution and qualification boundaries

The CLI and composite worker process use macOS `sandbox-exec` network denial.
Trusted Blender/Rive calls stay inside the registered attempt process group and
inherit the existing supervisor's cancellation, memory, process and disk budgets.
No editor window, account login, Rive publishing or generated image/video is used.
This is a local trusted-adapter boundary, not a hostile-code sandbox or a
multi-tenant isolation claim.

Dobe engines and private Python are built with the existing offline package
builder. Blender, Rive and FFmpeg remain external, exact-hash supporting engines.
The local Rive browser runtime is retained at version 2.48.0 with its package
metadata. Its license metadata declares MIT; a public redistribution still needs
complete upstream notice packaging. No release signing or public distribution is
performed by this work.

Local browser evidence covers Chrome on this Mac and emulated touch. It does not
qualify physical mobile devices, React Native, native Rive hosts or older browser
versions. Native Apple/Adobe application bridges, Linux, hosted rendering, package
signing and clean-machine installation remain separate environment gates.

Blender uses Standard view transform and packed Archivo. PNGs are display-referred
sRGB-style output; FFmpeg encodes H.264/yuv420p. The technical fixture validator
checks actual media properties, not calibrated color accuracy. Human art-direction
approval, calibrated Rec.709 proof and agent token/cost accounting are not implied
by an execution pass.

## Reproduce local evidence

Use a fresh output directory for each run. These tools write only local evidence:

```sh
PYTHONPATH=craft/runtime python3.13 craft/runtime/tools/test_construction.py
python3.13 craft/runtime/tools/construction_acceptance.py PACKAGE EVIDENCE
python3.13 craft/runtime/tools/construction_ring_acceptance.py PACKAGE EVIDENCE
PACKAGE/lib/dobe/python/bin/python3 craft/runtime/tools/construction_recovery.py PACKAGE EVIDENCE
node craft/runtime/tools/construction_browser.mjs WEB_ROOT EVIDENCE PUPPETEER_MODULE CHROME_BINARY
```

The browser check serves only the retained local web assets, rejects external
requests, checks actual Rive input values, compares canvas pixels, observes an
intermediate transition frame and checks immediate reduced-motion settling. The
recovery check observes real Blender children, cancels a live attempt, kills a
worker, confirms process-group absence, expires only the local test lease, and
requires explicit retry. It is not a reboot test.

## Separate photographic production contracts

The `construct.*` contract above remains unchanged. New source-only photographic
routes use separate `production.*` and `synthesis.*` operations in the same durable
runtime. The former admits bounded editable 3D scenes; the latter requires an
explicit local open-weight policy and a separately provisioned model/runtime.
Synthesis emits raster images and a generation recipe, not a native 3D scene.
See photographic production evidence and gates (`adope-cli/photorealistic-production/README.md`).
These additions do not qualify the retained installed package or a GPU host.

For an independent photographic scene or a corrected full scene specification,
use [the production workflow helper](tools/PRODUCTION_WORKFLOW.md). It creates a
fresh project for each `production.create`, requires successful revision
publication, and checks out the published native and image. Reusing a populated
project for a second creation is invalid; publication protections are unchanged.
