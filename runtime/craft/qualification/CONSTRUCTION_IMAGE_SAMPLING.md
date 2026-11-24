# Explicit image sampling in construction

A Blender construction image accepts `image_extension: "clip"` or `"repeat"`.
Use `clip` for a placed logo or photograph: sampling must not wrap the opposite
edge into the boundary. Missing fields retain the historical `repeat` behavior,
so reopening an old project does not silently change its pixels.

Correct an existing image with an explicit `construct.edit` transaction: replace
the selected object with the same fields plus `image_extension: "clip"`, guarded
by the complete document hash and the exact prior object. The source revision
stays immutable. This updates the native image node without rebuilding the
geometry or changing unrelated objects. Changing the field is a creative
revision, not an automatic repair applied during inspection or rendering.

Native verification checks the declared extension, linear interpolation, flat
projection, the UV-coordinate connection and all four UV corners. An altered
native sampling property cannot pass merely because the packed image bytes and
ordinary file receipts still match. This does not qualify arbitrary shader
graphs, color spaces, texture filtering profiles or general image fidelity.

The maintained `construction_image_sampling_acceptance.py` fixture accepts a
sealed package, a complete legacy campaign checkout and two independently
hash-bound reference PNGs. It requires exact legacy pixels, an explicit clip
revision and fresh creation, preserved native geometry/camera and unrelated
objects, then refusal of four native-only sampling mutations under both verify
and render. It records durable jobs, stopped process groups and unchanged input
and package hashes. These requirements are not a completed exact-artifact
result until the fixture's retained evidence establishes them.

Owner creative acceptance, publisher signing, stock-host installation and the
complete Local/Cloud release remain separate gates. No package publication is
part of this qualification.
