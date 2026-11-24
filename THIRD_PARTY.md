# Third-party software

The [MIT license](LICENSE) covers the original software and documentation in this
repository. It does not cover third-party components, fonts, artwork or trademarks.

This repository ships no prebuilt binaries. `scripts/setup` fetches each engine's
source from its upstream repository at the exact commit pinned in
`runtime/craft/engines/*.lock.json`, applies the maintained patch next to it, and
builds it on your machine. The upstream engines are under their own licenses
(Apache-2.0 for the storytold engine repositories). Fonts come from the pinned
`craft-fonts` commit under their own licenses.

Each built engine in `.engines/FAMILY/` contains `engine.json`, which records the
source, patch and compiler inputs and every file's hash, and a `notices/` folder
with the dependency inventory and copied notice files from that build.

The Python environment installs the packages pinned in
`runtime/craft/runtime/requirements.txt` (Pillow) under their own licenses.

If you redistribute built engines or a packaged copy, you are responsible for
meeting the licenses of everything you include.
