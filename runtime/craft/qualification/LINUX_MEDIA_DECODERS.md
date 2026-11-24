# Fixed media decoders for Linux portable replay

Video and Motion portable imports now select supporting decoders by platform.
macOS retains its existing exact FFmpeg and FFprobe binary hashes. Linux x86-64
uses only `lib/dobe/media-decoders` inside the worker distribution. A complete
worker cannot be assembled without this explicit decoder pack.

The pack records the exact Debian archive identity, the two executable hashes,
original package copyright, version responses and immutable base-image identity.
The worker receipt binds the pack manifest and every pack file. Resolution
rejects changed bytes, links, wrong architecture, missing tools, duplicate
components, incompatible receipt fields and a different base image. Project
parameters, PATH and environment overrides cannot choose Linux decoders.

See worker preparation (`craft/hosted/WORKER_BUILD.md`) for the offline producer and
assembler commands. The producer extracts only named regular files. It executes
neither package installation nor maintainer scripts. Version checks run only on
Linux x86-64, with bounded output and time. Operator approval of an archive and
the base image is a separate provenance requirement; self-consistent receipts
are not signatures.

## Qualification on 19 November 2026

- Thirteen local checks cover static synthetic ELF-shaped receipts, fixed
  paths, changed files, links, architecture/mode, worker consistency, mandatory
  decoder admission and safe selected-file extraction. The synthetic bytes are
  never executed and do not establish Linux operation.
- The existing 34 hosted admission, native-contract, image-contract and portable
  checks pass. The image-assembly check copies synthetic decoder fixtures through
  the real assembler. Docker and native engine execution are not part of these
  checks.
- Real macOS Video/Motion replay passes seven accepted cases and twenty-three
  refusals, including altered frames and audio. Six additional production calls
  create, revise and restore native output. Every picture frame, timing/color
  metadata and applicable decoded audio PCM is compared. This uses explicitly
  overlaid source modules with the retained read-only package, not a new sealed
  distribution. Original inputs and supporting decoder pins remain unchanged.
- Offline dependency resolution for the Linux target succeeds for fifteen of
  seventeen maintained source graphs on macOS. PDF and Photo require the locked
  `curve25519-dalek-derive` 0.1.1 archive. No Linux compilation occurs in that
  check. Source preparation verifies seventeen families, 2,951 context files,
  1,521 cached registry archives and 32 Git pins.

Machine-local evidence is retained in
`.verify/linux-worker-prerequisites-20261119/`. This directory is not part of
the public distribution. The previous real PostgreSQL evidence remains scoped
as documented in [database cutover](HOSTED_DATABASE_CUTOVER.md).

## Portable replay preflight correction on 19 November 2026

A subsequent source inspection found that Video and Motion portable replay still
called the macOS-only supporting-binary check before observing the project. That
preflight rejected Linux even when the later replay stage could resolve its
fixed worker decoder pack. The preflight now uses the same platform-aware
`media_decoders.resolve()` boundary. macOS retains its exact supporting-binary
pins; Linux retains its fixed worker path and receipt validation.

The existing decoder suite now passes sixteen checks. Before the correction,
the added regression cases produced two errors on accepted Linux receipts and
two failures where altered Linux decoders encountered the macOS-only refusal
instead of inventory validation. After the correction, both Video and Motion
reach the native observer only with accepted decoder receipts. Changed decoder
bytes are refused first. The macOS cases also verify accepted pins and changed
FFprobe refusal. These checks simulate platform identity and use static,
unexecuted binary fixtures; the native observer is a sentinel. They do not prove
native Linux execution or codec behavior.

The existing hosted admission, worker image and portable suites pass 8, 9 and 9
checks respectively. At the initial run, the native-contract suite passed six
of eight checks: two unchanged total-count assertions expected 96 operations
and 11 excluded routes, while the source catalog contained 97 and 12. Both
failures also reproduced with the original replay module loaded in memory. The
capabilities owner is reconciling those separate assertions; this correction
does not hide or change them. The capabilities owner subsequently reports all
eight checks passing with an exact assertion for the twelve excluded routes.
Four initial suite
invocations could not import Pillow; a private copy of the existing environment
with the already cached Pillow 13.0.0 wheel allowed the checks to execute. No
dependency was downloaded. Checks run with network access denied by the OS.

Machine-local before/after logs and environment details are retained in
`.verify/linux-replay-preflight-20261119/`. This correction changes current
runtime source only. It does not alter the ongoing Linux engine build inputs,
the guest, or the retained V12 and V13 development packages.

The required repository verifier finishes at 25/26 with its original skips
(18 explicitly; 21 and 22 under CI mode), including 43 build tests. The only
remaining failure is the history scan: 24 findings across 675 commits from the
canonical repository scope. The publishable-file scan is clean. This broader
history scope differs from the previously recorded sparse-clone scan, so the
count difference is not evidence of newly introduced findings. An initial run
without the complete offline npm cache scored 18/26; its failure and an
interrupted setup retry remain recorded. The successful retry reuses the
existing cache under OS network denial without downloading dependencies.

## LGPL decoder build on 22 November 2026

The licence inventory of the qualified worker image showed that the Debian
`ffmpeg` pack linked Debian's FFmpeg 7.1 libraries, built with `--enable-gpl`
and x264, x265 and Xvid, reaching 191 runtime packages. The owner chose a
reduced decoder. Linux packs now use receipt schema 2: FFmpeg compiled from an
upstream release with one fixed LGPL configuration limited to this profile.
Schema 1 packs are refused, as are programs whose embedded configuration
differs or carries GPL, nonfree or version 3 flags.

Twenty decoder checks pass, including refusal of a schema 1 pack, of programs
with a GPL or different embedded configuration, and of builder archives with
members outside the release folder or links. Removing the embedded-configuration
check makes three of them fail. The nine worker image contract checks pass. A
derived runtime-base manifest keeps 107 of the 295 base packages (30 Debian
archives instead of 218) and prepares offline. These are static checks: the
FFmpeg source is not yet acquired, nothing was compiled for Linux, and the
changed decoder and base need a new image and all 105 native cases.

Later on 22 November the signed FFmpeg 7.1.5 release archive was acquired and
one native run built the decoder, the 107-package base and a new worker image,
`sha256:8f83786a…`. All 105 native cases passed on it, and the portable image
was recovered. The image probe found decoded frames equal to the Debian
decoder's; decoded PCM differs and is recorded. The decoder links only libc and
libm. See `docs/launch/linux-stage-b-vercel-105-lgpl-2026-11-22.json` and
`docs/launch/linux-image-licence-inventory-lgpl-2026-11-22.json`. This page was
updated after that run; the image carries the earlier text of this file.

## Remaining release requirements

The Linux producer still needs execution using approved real Debian inputs on
the intended runtime. The immutable image must include compatible Python,
Pillow 13.0.0 and complete native/decoder library dependencies. Actual Linux
codec behavior, all seventeen engine builds, portable replay, isolation,
cancellation/recovery and complete hosted publication remain to be qualified.
Notice presence does not finish redistribution review. No image pull, VM start,
remote test, payment, Supabase deployment or publication is authorized by these
local checks. Full Local/Cloud release readiness remains unproven.
