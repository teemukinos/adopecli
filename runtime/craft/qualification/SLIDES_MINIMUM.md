# Slides minimum with precise text-color revisions

The maintained `craft/runtime/tools/slides_acceptance.py` fixture passes **102
checks across 32 durable CLI jobs**: 31 Slides jobs and one independent public
PDF import. There are 27 successes, five expected worker refusals and one
separate admission refusal. This is bounded macOS ARM64 evidence, not complete
presentation-format or Local/Cloud release qualification.

## Observed behavior

The fictional four-slide production proposal uses the versioned
`production_proposal` recipe, pinned Inter, editable speaker notes and original
material swatches. It exercises all seven Slides operations and all seven typed
edit kinds.

- Complete-model predictions constrain text, notes, picture insertion, cropping,
  replacement, placement, slide naming and text-color revisions. Every field
  outside the requested changes remains equal. Picture replacement retains the
  original embedded media and adds the exact replacement bytes.
- Full PNG delivery, ordered slides `[4, 2]` and fractional scaling preserve
  selection and dimensions. Repeated cold PNG exports are byte-identical.
  Revisions leave all untargeted slide pixels unchanged. PNG swatch samples match
  the source channel values exactly.
- PNG and PDF exports preserve checked text inventories, picture geometry and
  native source. The final PDF is also imported through the public PDF route,
  retaining its exact bytes; its independent raster contains the requested
  replacement color within two channel levels. This is not whole-page PNG/PDF
  pixel equivalence or proof of text reading order.
- Bundling, inspection, native JSON, standalone `.dobeslides` and actual
  `.deckcraft` imports preserve complete models and original bytes. Whole-project
  transfers into a separate private state reopen with equal models and pixels.
- Maintained migration uses an actual retained predecessor, rather than a
  fabricated old receipt. Both successive migration transitions survive, with
  the prior envelope, original container and current model preserved exactly.
- Stale hashes, incorrect picture identity, an invalid atomic batch, a missing
  document slide and same-engine migration publish no revision and leave the
  project head unchanged. Slide 99 is refused before job admission.
- Both state databases pass `quick_check`, all recorded execution groups are
  absent, successful checkout receipts remain exact, and the entire sealed
  package verifies unchanged before and after acceptance.

The 32 worker commands take **132.817 seconds** in total. This is local wall time
including package verification and validation, not CPU time, peak memory,
energy, cloud cost or elapsed time for the whole qualification unit.

## Bounded feature extension and preserved chronology

The previous typed revision contract did not support text fill. Its refusal of
a requested heading-color change was correct. This unit extends `run.properties`
with the same bounded fill admission already used by native execution: explicit
solid RGBA byte channels, no fill, or null/inherited fill. It does not add gradient
or scheme-color support. Four source regression methods cover exact edits,
no-fill/inheritance distinctions, invalid-fill atomicity and stale-style refusal.
The installed acceptance specifically qualifies an opaque solid-color revision;
no-fill and inheritance have source-level coverage only.

The original fixture also expected out-of-range slide selection to fail inside
a worker. The product correctly refused admission. Its original log remains,
and the corrected fixture asserts that boundary. After the text-color extension,
the full fixture runs in a fresh private state against a newly sealed candidate.
Successful jobs are retained on resume, not replayed. The final fixture adds the
public PDF cross-check and exact PNG sample oracle after the first candidate
pass; these are acceptance-only changes, not changes to packaged runtime code.

## Exact artifact and limits

The new private read-only candidate is `0.1.0-slides-color-qualification.1`, with
all seventeen existing engine packs and **7,049 sealed entries**. Image SHA-256:
`4ea6968a6e2b776798cf9c4d30807de538ea0c1fd7d24ef3303465c0b6566227`.
Seal SHA-256:
`d02480c2c8570216fede88b767a26e4856a4b5fc38ad326f517bae9780f89ca8`.
The candidate includes the later separate Write template notice. Its assembly
uses existing pinned local inputs with network access denied. No native engine
is rebuilt. All 163 packaged top-level runtime Python modules match current
source at the recorded inspection boundary.

The delivery contains twelve PNG slides, two PDFs, three native presentations,
three complete editable ZIPs, an explicitly separate migration example, original
swatches, the recipe and revision requests. Assistant visual inspection checks
hierarchy, alignment, clipping and the revised heading/picture relationship.
It does not constitute owner quality acceptance. The swatches do not claim
photographic generation.

The previous PDF candidate and its unsupported-color refusal remain separate
historical evidence. The new candidate is ad-hoc signed private functional
evidence; public assembly continues to refuse incomplete dependency notices.
This unit changes no installed service or global MCP configuration, starts no
VM, opens no editor and makes no remote request. General PPTX fidelity, broader
typography, owner acceptance, complete notices/rights, production signing,
stock-host lifecycle and Linux/Cloud qualification remain open.
