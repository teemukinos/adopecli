# Motion glyph fidelity and editable typography

Date: 2026-11-18. Scope: native static Inter Regular point text with editable
content and transform animation, on the local macOS ARM64 package. This does not
qualify arbitrary fonts, rich typography, the complete Motion application,
Linux/Cloud execution or publisher signing.

## Corrected behavior

The previous installed runtime accepted a title containing U+10FFFF, rendered a
missing-character box and honestly recorded `glyph_coverage_verified: false`.
Family-name checks alone could not prevent that output from being published.

The maintained native `text.diagnostics` command now calls the same
`effectcraft_text::layout_doc` path used by the renderer. It reports actual glyph
IDs, UTF-8 clusters, resolved faces, synthetic styling and whether every used
face is the compiled Inter Regular bytes at face index zero. It bounds source
text to 4,000 characters, font size to 1–512 and shaped output to 16,000 glyphs.
It refuses source-text keys, character animators, rich runs, paragraph boxes,
vertical text, synthetic styles, case transformations and variable axes.

The runtime admits the same bounded profile, then requires nonzero glyph IDs,
exact bundled faces, valid source clusters and no missing-family or synthetic
style flags. It repeats diagnostics in a cold process after rendering and
requires identical results. Reports travel in `native/text-diagnostics.json`.
The per-project validation includes the static-point-text scope and text-layer
count; the whole-engine capability remains conservative.

Native `expr` and inspection `expression` fields are both rejected before engine
admission. Imported successful validation reports never replace fresh native
inspection. Unsupported typography fails without publishing a revision or
changing the project head. Transform animation and precise text edits remain
supported.

## Evidence

**86 local checks** cover native jobs, independent output inspection, the final
installed package and delivery. The native engine's existing text/text-edit test
selection passes **65 tests**, with one existing warm-listing benchmark ignored
and 1,108 unrelated tests filtered out. The two new regressions exercise actual
native shaping, the missing-character case, unchanged project data, character
substitution, source-text keys and synthetic styling. This is not a full
upstream test-suite result.

The first package qualification passed 34 checks across four successful and nine
expected failed native jobs:

- Create a 480 × 640, 24 fps, two-second original typography composition with a
  rotating cobalt accent and a moving/fading Unicode line. Accented Latin,
  combining accents, ligatures, Greek and Cyrillic use nonzero bundled glyphs.
- Change “Make it move.” to “Keep it editable.” Preserve all other native fields,
  layer identities, animation keys and editable mapping. The untouched detail
  line keeps identical shaping diagnostics.
- Import the portable delivery into fresh state and revise it again. Retain all
  original artifact bytes.
- Reject missing-glyph creation and revision, and imported missing fonts,
  fallback scripts, synthetic styling, animated source text, rich runs,
  expressions and character animators. Each preserves its accepted project head
  despite the imported fixture retaining a successful validation receipt.
- Accept a shape-only composition with an explicit count of zero text layers.
- Verify the installed payload before/after and confirm all thirteen native
  execution process groups are absent.

The independent media oracle passed eleven checks. Sampled PNG differences are
confined to the headline region. The accent visibly rotates and the Unicode
line visibly moves and fades in. Frames 24 and 47 of the final hold have identical
native pixels. FFprobe independently confirms 48 H.264 frames, 480 × 640, at
24 fps for the original, revision and portable revision. Every revised frame was
decoded. The encoded final hold's maximum mean RGB difference is
**0.0008778211805555554**, within the preselected 0.5-level tolerance.

An initial native test did not compile because its fixture tried to mutate an
`Arc<Project>` directly. The fixture was corrected to use `Arc::make_mut`; the
failed build evidence was retained. A fresh build bound the corrected test
source in the maintained patch. Its production binary was **byte-identical** to
the already exercised binary. The corrected test selection then passed.

The final package qualification passed 37 further checks. It compared every
runtime file and all seventeen native executables against the earlier qualified
candidate, verified the corrected source manifest, installed into another
private prefix, imported and revised the prior package's editable source,
rejected another missing-glyph revision, and created a fresh title. All six PNG
samples matched the prior qualified outputs exactly. Both final MP4 files were
also byte-identical, carrying the independent complete-frame oracle to the final
package. The final three native process groups and the separate baseline group
were absent. No service or global assistant configuration changed.

Four delivery checks verify those complete movies, baseline cleanup and the
portable handoff. The inspected revised frame has legible glyphs, a fitting
headline, consistent margins and the established charcoal/warm-white/cobalt
palette. This is agent visual inspection, not owner aesthetic approval.

## Exact final artifact

- Motion source: EffectCraft 0.24.1 at
  `582344dd4ef462362c02e56e3094de7af01847ab`.
- Font source: `b076417b5880bd4154bd22f00695b1d28c6bea83`.
- Cargo lock: `1e92be15976720f95b8b321ce64c2a27d4b79c30aa2ee0b46b97660c8b62af6a`, unchanged.
- Maintained patch SHA-256:
  `834eedf835cc81f43aeda14852a8957a430dd5bce4bd6829fc1733784d80db15`.
- Native executable SHA-256:
  `74d712c16c282f1e2df961dc607b7d5a63a6e691590c6f53b8ca211efd9e2674`.
- Package version: `0.1.0-motion-glyphs-qualification.2`.
- Guard SHA-256:
  `a0e47543d0d7143c2525be3762c6c9ca9a458aefa10ec4f21638e347fe4e34eb`.
- Seal SHA-256:
  `505f1063b96f873b53f6a23da30af274a996557aa3050061fc91818b0bd6d533`.

The offline Rust 1.100.0 build uses the existing pinned revisions, development
profile, no default features and the `dobe` feature. Public compiler paths are
normalized and symbols stripped. The final cached build/packaging measurement
is 57.34 seconds; this is build work, not image-inference cost. No downloads or
remote actions were performed. The compiler inventory contains 467 packages;
49 notice sets remain missing. Binary linkage and redistribution approval remain
open rather than being inferred from compilation.

Private evidence is indexed by `.verify/motion-glyphs/checkpoint.json`. The
30-file delivery contains two portable projects, editable `.ecproj` documents,
PNG samples, MP4s, actual glyph diagnostics, a comparison preview and reusable
agent-directed create/edit requests. Private evidence and machine paths are
excluded from source exports.

## Remaining work

Broader Motion fidelity and typography, owner campaign acceptance, remaining
per-application minimum contracts, old application-manager migration, dependency
notices, publisher signing/notarization, stock-host/login/reboot qualification,
Linux workers, full hosted admission and commercial/provider qualification
remain open. The complete seventeen-application Local/Cloud goal is unchanged.
