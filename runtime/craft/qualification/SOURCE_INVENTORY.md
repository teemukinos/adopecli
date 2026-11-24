# Source inventory and export consistency

Date: 2026-11-18. Scope: unpublished source candidates. This does not qualify an
installed package, engine behavior, Linux/Cloud execution or publisher identity.

## Corrected boundary

The source export at `8009437a3fb65bd293a7c22463c0e2613a58bb68` retained ten stale
capability fingerprints after the Video and Motion increments. The affected
inputs were both native locks and patches, both contracts, and the Motion,
Video, worker and store modules. The earlier export's per-file checksums were
correct; they did not prove that its capability inventory described those files.
Historical exports remain unchanged as evidence of that distinction.

The generator now also records the digest of its generated Markdown. Export
checks the exact captured input set and bytes against the JSON inventory, its
aggregate digest and the Markdown digest before creating the destination. The
input set is selected independently from the exported source paths, not from
the inventory's claims. Added and removed inputs therefore invalidate it too.

The exporter never imports the selected revision's generator or adapters. It
reads immutable Git blobs and explicitly named overlays, then verifies the
captured bytes. Its result and `PUBLIC_CONTENTS.json` record this bounded check.
Regeneration remains a separate developer action. `build-preview.py` retains
its stronger check that regenerates the matrix from the trusted build source.

This is consistency evidence, not authentication or a proof that an inventory
author described operations correctly. An author can deliberately create a
self-consistent but false inventory. Operation execution, source review,
publisher trust and exact-artifact acceptance remain separate requirements.

## Local qualification

Seven local regression tests cover immutable revision selection despite dirty
working files, every input class as a stale overlay, added and removed inputs,
missing/malformed inventory, stale Markdown, a consistent explicit overlay,
unrelated evidence files and preservation of an existing destination. Candidate
Python fixtures raise if executed; exports succeed without executing them.
Each test uses a private temporary Git repository without remote access.

The full current source is exported with explicit overlays and independently
passes the generator's `--check` inside that exported tree. The old committed
inventory is refused before creating its output directory. Every exported file
matches its checksum manifest. The source surface remains 96 local operations,
17 native application families and 7 admitted hosted operations; no capability
or release flag is widened.

Private evidence is indexed by `.verify/source-inventory/checkpoint.json`.
An initial read from the synchronized checkout stalled and returned macOS
`Operation canceled`; a fresh copy of the previous immutable source export
provided stable qualification inputs. No historical evidence was modified.

## Remaining release work

The complete seventeen-application Local/Cloud goal remains open. Source
consistency does not clear per-operation acceptance, dependency notices,
application-manager migration, publisher signing, stock-host qualification,
Linux workers, hosted admission or real-provider billing qualification.
