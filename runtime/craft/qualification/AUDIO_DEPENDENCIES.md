# Installed Audio dependency refusals

The existing Audio profile requires owned relative WAV sources and supports no
instrument or mixer plugins. The earlier [Audio minimum](AUDIO_MINIMUM.md)
qualifies mixing, revisions and five other refusal cases. This unit adds the
specific missing-media and unsupported-plugin cases required by the dependency
handling gate. It does not expand plugin support or repeat the full Audio suite.

`craft/runtime/tools/audio_dependency_acceptance.py` passes **43 checks**:
22 collection checks and 21 read-only verification checks. It uses the sealed
public CLI, private state and a synthetic 100 ms mono source at 48 kHz. Four Audio
jobs each run one bounded attempt: two succeed and two deliberately fail. Three
separate project imports record integrity only, with no native attempt.

## Observed behavior

- The control is a native editable session with one named track, one named clip
  and one packaged WAV. Actual native creation and fresh-process reopening verify
  complete source preservation and produce the reference WAV delivery.
- A copied portable bundle deliberately omits its required native WAV and removes
  that file's manifest entry. Its remaining files pass bundle-integrity import.
  A subsequent edit fails during worker dependency admission with `engine_failure`
  and `No such file or directory`, identifying the missing WAV. No edit revision
  is published and the imported head remains unchanged.
- Another copied bundle declares an unavailable mixer plugin and recomputes the
  native file's manifest entry. Integrity import does not imply plugin support.
  Editing fails with `native audio contains unsupported mixer routing, automation
  or plugins`, with no edit revision or head movement. No plugin is loaded or
  replaced with an invented substitute.
- Repair restores the exact omitted WAV and original manifest to the actual
  missing-media bundle. That complete bundle becomes byte-identical to the
  control. Importing it and applying an explicit zero-gain revision succeeds;
  the entire native model, packaged media and delivered WAV, including PCM,
  match the original control exactly.
- Every failed input, original source and control artifact remains unchanged.
  Read-only journal snapshots confirm the terminal states, absence of failed
  revisions and three integrity-only imports. All four attempt process groups
  are absent. The complete package seal remains unchanged.

Collection runs once; verification does not repeat native jobs:

```sh
python3 -B craft/runtime/tools/audio_dependency_acceptance.py \
  /path/to/AdopeCLI /path/to/new-private-output \
  --expect-verification /path/to/guard-receipt.json --stage collect
python3 -B craft/runtime/tools/audio_dependency_acceptance.py \
  /path/to/AdopeCLI /path/to/new-private-output \
  --expect-verification /path/to/guard-receipt.json --stage verify
```

## Artifact and limits

The 19 November 2026 run uses read-only private candidate
`0.1.0-notice-client-private.2`, 644,501,989 bytes, SHA-256
`31796c0dc1b5094c9b3b69333da496d61dd15e2c3131a4d7b62d16214e7d2f68`.
Its seal SHA-256 is
`a4bc051e702ee9cb60638636170eb6fa8a90ee2659f0385ea3208771f53ec797`.
No production adapter, native engine, installed service or package changes are
needed. The observed refusals are correct behavior, not repaired product defects.

The separate Audio bundle-replay fixture already covers external native source
references; that earlier proof is not rerun or promoted here. This unit establishes
two declared dependency refusals and repair on this private Mac candidate. It does
not qualify plugin hosting, all corrupt media, peak resource consumption, Linux,
Cloud deployment, listening approval, final signing or the complete release.
