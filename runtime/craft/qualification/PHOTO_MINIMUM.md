# Editable Photo library minimum

Date: 2026-11-18. Scope: the two typed Photo operations on a private sealed
macOS ARM64 candidate, four input formats and portable native editing. This
does not qualify a complete photography application, camera-wide RAW fidelity,
Linux/Cloud execution, new image synthesis or owner visual approval.

## Produced work and revisions

The fixture imports an existing owned 1024 × 1024 product image. Photo produces
a 16-bit original, a restrained 640 × 800 editorial crop and a monochrome
revision with the same composition. Each delivery includes its editable native
library, unchanged original source, object mapping, PNG export and portable
receipt. This is native development of existing photographic material, not a
claim that Photo generated the subject.

The crop is `[0.1875, 0.15625, 0.8125, 0.9375]` in normalized coordinates.
The monochrome revision changes only `color.saturation` to `-100`. A fresh-state
portable import restores saturation to `0` and crop to `[0, 0, 1, 1]`. Every
restored 16-bit pixel equals the original native export. Unrequested settings,
object identities, prior history and original source bytes remain intact.

Visual inspection confirms that the bottle and label remain fully visible in
both cropped versions. Final aesthetic acceptance remains with the owner.

## Executable acceptance

```sh
"$PACKAGE/lib/dobe/python/bin/python3" -I -B \
  craft/runtime/tools/photo_acceptance.py \
  "$PACKAGE" /absolute/path/to/new-photo-evidence \
  --photo /absolute/path/to/owned-photograph.png
```

The source must be an opaque RGB/RGBA PNG no larger than 2048 pixels per side.
The fixture uses private states and only the guarded CLI. It installs no
service, opens no editor and requires no network or model API. `--resume`
checks recorded inputs, reuses completed jobs and refuses to replay admitted
nonterminal work. A process lock prevents concurrent fixture drivers.

The final fixture passes **51 checks across 10 durable jobs**: seven succeed
and three deliberately fail. Its evidence covers:

- PNG, JPEG, TIFF and synthetic sensor DNG inputs; 8-bit and 16-bit exports.
- Independent PNG decoding and **9,600 distinct red-channel levels** in each
  16-bit PNG/TIFF precision fixture. This does not turn an 8-bit source into
  higher-fidelity photographic information.
- EXIF orientation 6, independently checked JPEG corner colors, and cropping
  in the oriented coordinate system.
- Sensor RAW decoding without an embedded preview, explicit white balance,
  exposure and crop. A subsequent exposure revision leaves every unrelated
  photo's metadata and export bytes unchanged.
- Complete refusal of an invalid later batch target, a false source-format
  declaration and an unsupported external native profile. Each refusal
  preserves the original project head and publishes no revision.
- Portable integrity import followed by native reopening and precise revision.
  Import alone correctly reports only bundle integrity.
- Exact artifact receipts, both SQLite integrity checks, absence of all ten
  native execution groups and identical complete package verification before
  and after execution.

The ten worker commands took **42.247 seconds** in total on this local run.
That includes their verification and validation overhead. It is not CPU time,
peak memory, energy use, a cloud price or the duration of the whole fixture.

## Precision limits and retained oracle failures

The first fixture incorrectly required an 8-bit photographic input to round
trip through the native floating-point working space within two 16-bit levels.
The observed maximum difference was **14/65535**. Every original 8-bit RGB value
reconstructs exactly by nearest rounding. The corrected invariant checks that
source precision; genuine 16-bit source precision is checked separately.

The second fixture incorrectly required numerically identical monochrome
channels within two 16-bit levels. The native path zeros OkLab chroma and
converts through approximate floating-point color matrices. The measured
maximum channel spread is **36/65535**, within the fixture's one-8-bit-display-
level bound of 257/65535. Exact neutral 16-bit channels are not claimed.

Both initial failures, their logs and the completed jobs are retained. Neither
correction changes the native engine or replays an already completed job.

## Package verification repair

Finder metadata appeared inside the previously sealed Audio candidate after
its completed acceptance. The guard correctly refused the undeclared entries.
The bounded recovery preserves that metadata separately and restores the exact
original seal; the guard has no metadata exception. The final private image is
read-only, and attempted Finder metadata writes at three package levels fail.

The maintained macOS packager now mounts its final signed disk image privately
and read-only, then uses the trusted source guard's `verify-copy` operation to
verify the shipped payload before reporting success. It does not execute the
candidate guard. It checks the image hash before and after verification,
detaches normally and never recursively removes a mounted directory. A detach
failure preserves the directory for diagnosis. Signing the image or verifying
only its staging directory no longer substitutes for verifying its contents.

Seven local regression tests pass. Real native checks reject the retained
contaminated image and accept the repaired image, with unchanged image hashes
and clean detachment in both cases.

Candidate: `0.1.0-audio-minimum-qualification`, seventeen unchanged native engines
and 5,842 sealed entries. Seal SHA-256:
`944588b386245fdd70690493a93b644533f09c66f6378a71acd350dceea241e2`.
Guard SHA-256:
`93fd61e0c1e8b08515a28532ef5f698a5689bdb7c3eb6c6e6df2c2dccdbecde9`.
Repaired disk image SHA-256:
`afdf8f26a7b9803a81ef7924d0753303beaedb2bcfcdeeea4f040dede1c7da0d`.

The repaired image is an unsigned private qualification artifact containing an
ad-hoc rehearsal guard. It is not a notarized or publisher-authenticated release.
This Photo record does not qualify the latest source packaging the separate
legacy-manager migration. Full Local/Cloud admission, Linux workers, notices
and rights, stock-host installation, signing, real billing-provider checks and
the remaining application requirements remain open.
