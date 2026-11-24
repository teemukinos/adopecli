# Capabilities

The [operation matrix](../runtime/craft/CAPABILITIES.md) and its
[machine-readable form](../runtime/craft/CAPABILITIES.json) list every registered
operation, its adapter and the pinned engine revision. Check that they match the
source with:

```sh
.venv/bin/python -B runtime/craft/capability_inventory.py --check
```

`bin/dope capabilities` shows what this machine can run: an operation needs its
engine in `.engines/`. `bin/dope describe OPERATION` shows the parameters, an
example and the editing rules for one operation.

The seventeen families are Image, Vector, Video, Motion, Audio, Photo, PDF,
Layout, Interface, Animate, Texture, Material, Write, Slides, CAD, Sheets and
Inspect. They are bounded native adapters, not full copies of every upstream
editor feature, and they do not accept arbitrary imported files. Each family's
contract is linked from the matrix.

Construction profiles that use Blender or Rive need those applications installed
separately. Generative image and video models are not part of this release.
