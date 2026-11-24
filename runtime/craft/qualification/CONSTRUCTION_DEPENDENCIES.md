# Native construction dependency binding

The fixed Blender observer compares each embedded image and font with the exact
bytes of its declared retained dependency. Both verification and rendering
refuse a different packed logo or font before producing a fresh successful
inspection. A packed-file presence check alone does not establish this binding.

`craft/runtime/tools/construction_dependency_acceptance.py` starts from the
complete retained campaign source. It independently observes original packed
bytes, creates separate native logo/font substitutions and correctly updates
the changed native-file and outer receipt hashes. Declared logo/font files and
construction parameters stay unchanged, so the negative cases isolate semantic
native dependency binding rather than a stale checksum. Inputs stay read-only.

The fixture requires an independently authenticated package verification JSON,
a pinned local replacement font and a pinned full-size baseline PNG from the
original package. It qualifies both `construct.verify` and `construct.render`
for each of three sources: correct original, changed packed image and changed
packed font. Expected failures publish no revision and retain their original
heads. Correct-source verification and rendering must preserve every native
object record and camera, all declared asset/font bytes, and every pixel of the
1920 × 1080 control. Durable job identities and all six native process groups
are recorded. `--resume` observes existing jobs; failed or live work is never
silently retried. Only an unstarted queued attempt may run.

The alternate font and deliberately changed native sources are private negative
fixtures, not release artwork. Exact dependency bytes do not prove every shader
connection, every native property or artistic quality. This unit does not claim
Linux/Cloud, clean-machine, reboot, signing, provider billing or public release.
