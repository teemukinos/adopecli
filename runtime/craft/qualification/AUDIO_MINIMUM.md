# Editable Audio cue and complete-session preservation

Date: 2026-11-18. Scope: a private sealed macOS ARM64 candidate, the two typed
Audio operations and portable editing. This is bounded Audio acceptance, not
complete application, Linux/Cloud, publishing or owner listening approval.

## Fixed preservation gap

The previous runtime compared tracks, sources, sample rate and bit depth after
native save/reopen. A real baseline job successfully revised an imported project
while silently discarding an unknown top-level session field. It nevertheless
reported `editable_audio_unchanged_on_reopen: true`. Matching PCM did not prove
preservation of the complete editable source.

The runtime now compares the complete native session. Only the existing native
f32 normalization for clip and track gain remains. Legitimate author comments
survive a fractional-gain revision with all unrelated fields unchanged. A field
that the native parser discards causes the job to fail without publishing a
revision or changing the imported project head. Native engine code is unchanged.

## Produced work and precise revision

The eight-second cue uses three original procedural stereo WAV stems: a rounded
pulse, a four-note motif and a short transition. SoundCraft performs all track
placement, source trimming, gains, fades and mixing. The native project retains
three named tracks and four editable clips. This is production from owned source
material, not a claim of model-based music synthesis.

The revision moves the returning motif from 4.00 to 4.25 seconds, starts its
source window 125 ms later, shortens it to 1.50 seconds, lowers its clip gain by
3 dB and changes its fades to 50/375 ms linear fades. The transition track also
falls by 3 dB. Every other native field and source byte remains exact. PCM before
4.00 seconds and after 7.50 seconds stays byte-identical. Fresh-state portable
editing restores the complete original session and its exact original PCM.

The production cues remain finite, below full scale and exactly eight seconds.
Listening approval remains open. Numeric checks establish timing, channel
levels, source integrity, gain, fade bounds and headroom; they do not establish
perceptual preference, mastering quality or a loudness delivery standard.

## Executable acceptance

```sh
"$PACKAGE/lib/dobe/python/bin/python3" -I -B \
  craft/runtime/tools/audio_acceptance.py \
  "$PACKAGE" /absolute/path/to/new-audio-evidence
```

The fixture generates its own owned source material and uses private states,
the guarded CLI and separate workers. It needs no network, service installation,
editor window or model API. `--resume` reuses recorded completed commands and
jobs, checks their inputs, and refuses to replay admitted nonterminal work.
A process lock prevents two fixture drivers from using the same output folder.

The final fixture passes **201 checks across 33 durable jobs**: 28 succeed and
five deliberately fail. It covers:

- Native creation, precise clip and track revisions, whole-session metadata,
  unchanged source bytes, exact cold-reopen PCM and portable restoration.
- Refusal of a discarded native field, an invalid later batch target, overlapping
  clips, a source overrun and an oversized fade. No refused job changes its head.
- **60 input combinations**: mono/stereo, 8/16/24/32-bit integer PCM and float32,
  standard RIFF and extensible WAV, each at 44.1/48/96 kHz. Native resampling to
  48 kHz retains independently calculated channel levels and clip/silence bounds.
- All three output session rates, clip-plus-track gain, and all three fade
  curves checked against numeric bounds at every output sample.
- Above-unity float output retaining requested headroom without normalization or
  integer clipping. This deliberately hot numeric fixture is separate from the
  listening deliverables.
- All artifact hashes, SQLite integrity, native execution-group absence and
  identical payload verification before and after the work.

The separate old-package baseline adds one successful job that reproduces the
preservation defect. It is retained as failed-behavior evidence, not acceptance
of the corrected runtime.

## Fade precision and retained corrections

The pinned native mixer samples gain every 32 samples and interpolates between
the first and last sample of each segment. Rendered curves therefore approximate
the ideal mathematical curve; exact per-sample analytic fades are not claimed.
The first fixture oracle incorrectly required that ideal at a linear fade cusp.
The successful native job and its output were retained without replay.

The corrected oracle compares every sample with independently derived bounds.
For a segment spanning at most 31 sample intervals, a linear cusp uses the
Lipschitz bound `L × h / 2`; smooth equal-power and S-curve fades use the
second-derivative bound `max(|f''|) × h² / 8`, plus `2e-7` for native float
rounding. Reports retain measured maxima and bounds per curve and rate. These
numeric fixtures use approximately 100 ms fades. Arbitrary very short or
overlapping fade envelopes require further fidelity qualification.

An initial private baseline helper tried to parse an empty successful worker
response as JSON. The completed job was inspected and exported without rerunning
it. The maintained driver handles empty successful responses. The extension
from standard to extensible WAV reused the completed standard-format jobs.

## Package and release boundary

Candidate: `0.1.0-audio-minimum-qualification`, all seventeen unchanged native
engines and 5,842 sealed entries. Seal SHA-256:
`944588b386245fdd70690493a93b644533f09c66f6378a71acd350dceea241e2`.
Guard SHA-256:
`93fd61e0c1e8b08515a28532ef5f698a5689bdb7c3eb6c6e6df2c2dccdbecde9`.

Private preparation used APFS filesystem clones to limit disk use. Files have
independent identities, not hard links. The maintained builder's complete byte,
mode, symlink and source/destination equality checks remained active. No installed
service or global configuration changed. The guard is an ad-hoc rehearsal,
not a publisher signature or notarized release.

Source registration remains 96 local operations and seven admitted hosted
operations. Audio is not hosted-admitted. Instruments, plugins, MIDI, general
native-session import and broader routing remain outside this typed contract.
Linux x86-64 workers, full hosted admission, notices and rights, publisher and
stock-host qualification, legacy application migration, real commercial-provider
checks and the other remaining application requirements stay within the complete
seventeen-application Local/Cloud goal.
