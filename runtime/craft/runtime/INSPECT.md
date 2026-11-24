# A dope CLI Inspect runtime contract

The `static-artifact-v1` profile inspects an explicitly permitted project asset
with the maintained Craft Anything engine. It produces exact native findings,
editable analyst annotations and portable original bytes. It never executes the
target, follows dependencies or URLs, reads a caller-selected filesystem path,
or starts an upstream agent, browser or device integration.

This is source-runtime qualification on macOS ARM64. Installed packaging,
Linux execution, Cloud isolation and complete release qualification remain
separate gates. A Linux compile check is not execution evidence. A successful
inspection of an invalid input does not make that input valid or safe.

## Public operations

These operations share the product's MCP endpoint and CLI. All
require `permission: "owned-or-authorized"` and `input_sha256`, the SHA-256 of
the exact original input. Supplying a portable archive does not grant consent.
An existing authorization can be reused for operations on the same input; the
explicit fields ensure the submitted job records the authorized bytes.

| Operation | Additional parameters | Result |
| --- | --- | --- |
| `inspect.analyze` | `asset`, `format` (`native`, `wasm`, `javascript`) | New native findings and empty annotation layer |
| `inspect.import` | `asset`, `expected_sha256` of the `.dobeinspect` archive | Exact portable project, verified again by the native engine |
| `inspect.inspect` | `expected_sha256` of the current portable project | Fresh native replay and verification |
| `inspect.annotate` | `expected_sha256`, `edits` | Precise annotation revision; original input and native report unchanged |
| `inspect.export` | `expected_sha256`, `format` (`json`, `html`) | Structured JSON or a self-contained findings preview |
| `inspect.bundle` | `expected_sha256` | Portable `.dobeinspect` delivery |

Analyze/import require a new project with no source revision. Other operations
require a source revision. Assets must belong to the requesting workspace and
project. Unknown fields, arbitrary paths, missing permission and malformed hashes
fail admission. Stale portable hashes, consent for different bytes, malformed
archives and nonexistent finding references fail before any native command.

`native` supports ELF, PE and Mach-O. `wasm` preserves structural validation
results, including invalid or partial modules. JavaScript preserves parser
fallbacks and imported names without fetching or executing them. Parser warnings,
native triage inference and incomplete coverage remain visible in every report.

## Editable findings

An annotation upsert takes `kind: "upsert"`, a stable `id`, a JSON `pointer`
under `/evidence/result`, `title`, `text`, `status` (`open` or `resolved`) and
`severity` (`note`, `info` or `warning`). For example:

```json
{
  "kind": "upsert",
  "id": "PublicExport",
  "pointer": "/evidence/result/facts/exports/esm/0",
  "title": "Export contract",
  "text": "Keep the answer export in the next revision.",
  "status": "open",
  "severity": "note"
}
```

A removal takes only `kind: "remove"` and `id`; missing targets are refused.
One batch cannot edit the same ID twice. Stored annotations bind their pointer
to the input hash, native report hash and evidence ID. Annotation status is an
analyst statement, not native verification or a safety judgment.

Portable history starts with an empty annotation layer and replays each typed
edit. Exact original bytes and the complete native report are immutable. Every
intermediate annotation state is checked; rewriting checksums cannot make a
state that differs from its recorded edits valid.

## Native replay and provenance

The fixed distribution receipt selects `dobe-inspect 0.6.1` and its maintained
source lock. Neither project data, PATH nor environment overrides select code.
The executable's hash, file identity, receipt and version are checked. Native
calls use bounded pipes, output files and CPU time inside the runtime's existing
attempt process group. The supervisor owns cancellation, fencing and publication.

Each verification runs the actual analyzer twice against the exact original
bytes. Cold reports must be byte-identical. On the same host platform, they must
match the entire stored report byte for byte.
This includes display fields that the upstream canonical evidence ID excludes.
A self-consistent archive or evidence ID alone is not execution proof. The
annotation history is replayed separately, without changing native findings.

The source supports explicit report reconstruction between `macos-aarch64` and
`linux-x86_64`. The pinned native implementation includes the host in its
canonical evidence ID. For a different host, verification rebuilds that ID and
host field from the fresh native report, then compares the complete reconstructed
bytes with the original. Every finding, display field, limitation and numeric
token still compares. Original report, project bytes and annotation history are
preserved. Other host combinations are refused.

The operation receipt records `host_migration` with both hosts and the fresh
report's SHA-256; `complete_report_equal` is false when reconstruction is needed.
An earlier binary hash from a different declared execution host is preserved as
unauthenticated historical provenance. A same-host receipt must still match the
current pinned binary. Stored recipes and receipts never grant input consent or
permission to execute target content.

Real macOS replay and explicitly synthetic foreign-host fixtures qualify this
source behavior. Actual Linux execution and deployment remain open. See
[host reconstruction qualification](../qualification/INSPECT_HOST_MIGRATION.md)
for the exact tested boundary.

## Deliverables and limits

Native files include `source.bin`, `report.json`, `annotations.json`, complete
annotation states and `project.dobeinspect`. Production records retain the
original and latest typed operations. JSON exports separate native findings from
analyst annotations. HTML shows the summary, scope, limitations, editable notes,
structured findings and traceable hashes. All target and analyst strings are
escaped as text; a restrictive content policy prevents active content or remote
resources. Browser fonts are used; no pinned-font rendering claim is made.

Input is limited to 16 MiB, or 2 MiB for JavaScript; native reports to 32 MiB;
portable and HTML deliveries to 128 MiB. JSON has a 64-level nesting limit and
a two-million-node budget. Portable manifests are limited to 1 MiB, history to
32 revisions, aggregate edits to 4,096, each batch to 128 edits and the current
annotation layer to 256 notes. Titles allow 160 UTF-8 bytes, note text 4,096 and
pointers 1,024. Duplicate keys/members, ambiguous paths, symlinks, nonfinite
numbers, unsupported integer ranges and malformed Unicode are refused.

`inspect_project_check.py` checks private native replay, annotation fidelity,
escaped delivery and hostile containers. `inspect_runtime_check.py` exercises
all six operations through separate CLI/MCP clients and real workers, including
project transfer, forged reports, stale requests and permission boundaries.
`inspect_recovery_check.py` observes actual native children during cancellation
and supervisor death, then verifies natural lease expiry and explicit retry.
These checks do not qualify installation, reboot, clean machines or Cloud.
