# Precise publication artwork replacement

Date: 2026-11-18. Scope: bounded Layout image replacement through a private
sealed macOS ARM64 CLI candidate. This extends `layout.edit`; it does not add
an operation name or widen hosted admission.

## Behavior

A named graphic frame accepts a PNG/JPEG project asset, an exact expected SHA-256
of its current embedded bytes, and explicit contain, cover or stretch fitting.
DesignCraft places the image. The runtime independently predicts the graphic
transform, asset allocation and compaction, then compares the entire native
state, embedded hashes and untouched page pixels before publication.

The frame identity, path, transform, styling and unrelated objects stay intact.
Another placement of the same image stays unchanged. Identical embedded images
merge into the lowest existing native asset identity; unused native assets are
removed. Original project assets remain retained for reuse. Reuse checks project
authorization and exact authoritative file bytes without replacing an existing
file, using the existing Video asset boundary.

Native placement resets graphic options. This route therefore refuses custom
clipping, crop, automatic fitting, alignment, graphic wrap, tint and layer
options. It requires a plain graphic in an unmodified rectangular path and
preserves a prior frame translation. Arbitrary imported graphic features are
not qualified.

## Executable production fixture

The 612 × 792 point publication combines live Inter text, a 540-point campaign
image and a footer. An appendix contains another placement of the same image
and independent live text. Campaign artwork comes from the Interface acceptance
fixture. A separate 240 × 120 native Vector image distinguishes fitting modes.
The original and revised page renders have been inspected for legibility,
spacing, clipping and coherent typography. Agent inspection is not owner approval.

```sh
"$PACKAGE/lib/dobe/python/bin/python3" -I -B \
  craft/runtime/tools/layout_replacement_acceptance.py \
  "$PACKAGE" /absolute/path/to/new-layout-evidence \
  /absolute/path/to/original-campaign.png \
  /absolute/path/to/revised-campaign.png
```

Supply the original and component-revision 720 × 720 PNGs produced by
`interface_acceptance.py`. The fixture uses private states and the package's
private Python. It needs no network, service installation or editor window.

Coverage includes shared embedding, single-frame revision, restoration, retained
asset reuse, same-image replacement, all fitting modes, two-frame replacement,
replacement after movement, native/IDML import, fresh-state portable revision and
inspection. Stale hashes, text targets, malformed raster data and a later invalid
batch target fail without publication or a changed project record. Foreign
project assets fail at submission. Each successful publication cold-reopens,
preserves exact native state, reproduces IDML pixels and passes independent PDF
page/text inspection. Artifact hashes and process-group absence are checked.

## Local result

The reusable fixture passes **68 checks** across **20 native jobs**: sixteen
succeed and four deliberately fail without publication. Six request/option
regressions and the nine existing asset-boundary regressions pass locally.
The earlier development probe adds two successful jobs and one implementation
failure before correction. All final fixture execution groups are absent.
The sealed package verifies identically before and after execution.

Candidate: `0.1.0-layout-replacement-qualification`, 5,842 sealed entries and all
seventeen native engines. Seal SHA-256:
`944820dadfe6bc5cb5ed540a203887edb0ffb34424bf4f2ad9496283de56d8e3`.
Guard SHA-256:
`54e1de1d1b378de1d6539327dbaabf18bb6c7df337c433dad37903225b4404f0`.

## Corrections and interruptions

The first implementation used `nextId` instead of `nextId + 1`. The native job
failed closed. The pinned allocator increments before returning; correcting the
expectation made the probe pass. No native engine was changed or rebuilt.

The initial cover oracle incorrectly expected a source edge band to remain
visible after cropping. A second version incorrectly required filtered boundary
pixels to equal the flat interior. The final check uses the calculated interior
and unchanged outside-frame pixels. Earlier successful native jobs were reused
from their durable receipts, not resubmitted. Failed oracle records remain.

A transient disk failure interrupted a foreign-project asset import with
`OperationalError: disk I/O error`. A read-only SQLite quick check returned `ok`
and confirmed no asset row had committed. Only that uncommitted asset import
was retried. Completed native jobs were not replayed and evidence was not deleted.

## Release boundary

The private candidate retains all seventeen native engines. Layout 0.20.1 is
unchanged; this is a runtime-only extension. Its native guard is an ad-hoc local
rehearsal, not a publisher signature or notarized release. The inventory remains
96 local operations and seven hosted operations. Layout is not hosted-admitted.

Linux x86-64, full hosted execution and metering, dependency notices and rights,
production signing, clean-host/service lifecycle, application-manager migration,
real billing/provider qualification and remaining per-application contracts stay
within the unchanged complete Local/Cloud goal. General IDML/PDF fidelity and
owner aesthetic approval are not claimed.
