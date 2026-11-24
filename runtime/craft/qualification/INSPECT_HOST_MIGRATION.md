# Inspect report host reconstruction

The source now supports the two intended runtime platforms without discarding
the host field or silently normalizing findings. Reports still use the unchanged
maintained Inspect source lock and engine binary interface. No engine, model,
remote service or additional application is introduced.

## Comparison rule

The pinned Craft Anything revision
`48a9c5a60ff83ff620f98661339be6281a7debc6` derives evidence IDs from canonical JSON.
The host is included; display summary, target-content marker and subject display
name are excluded from that ID. The runtime comparison retains those display
fields even though the upstream ID excludes them.

Same-host reports must remain byte-identical. Across macOS ARM64 and Linux
x86-64, the runtime reconstructs only the host and evidence ID from fresh native
output, then requires the complete resulting bytes to equal the retained report.
Object keys use the upstream UTF-16 canonical order. Native JSON number tokens
are preserved verbatim, avoiding a separate approximation of Rust floating-point
formatting. Unsupported environments and non-native serialization are refused.

Original source, report, portable project and prior annotation states remain
unchanged during import. The new operation receipt declares the reconstruction
profile, source host, replay host and fresh native report hash. Its
`complete_report_equal` field is false when the reports differ by host.
Annotations continue to bind the original evidence ID and report hash.

Portable outer bundles can retain an earlier execution receipt. A prior host
migration must have the correct reconstructed-report digest. A same-host binary
hash must match the current pinned binary. A different-host binary hash is only
bounded historical data, never authentication of an earlier execution. All
other receipt and delivery fields still compare against fresh native replay.
Every import still needs fresh explicit permission for exact input/project
hashes. Target content is never treated as instructions or executed.

## Local qualification on 19 November 2026

- The existing eighteen real macOS Inspect portable replays and fifty-three
  refusal cases pass with explicit source overlays on the retained read-only
  package. Same-host receipts retain their previous bytes.
- Eighteen retained native reports independently reproduce their real Rust
  evidence IDs. Host reconstruction round-trips preserve their original bytes,
  including reports for JavaScript, WebAssembly, Mach-O, ELF and PE inputs.
- Eighteen explicitly synthetic Linux-host projects replay through the actual
  macOS engine and preserve their native bytes and annotation history. Two outer
  bundle cases cover a real macOS migration receipt and a deliberately synthetic
  earlier Linux execution receipt. Neither case executes Linux code.
- Five additional refusals cover changed foreign findings, a host change with
  an unrecomputed evidence ID, a forged migration digest, a substituted same-host
  binary hash and a malformed foreign binary claim.
- Six real macOS operations revise, export JSON/HTML, bundle, inspect and remove
  a temporary annotation. The original source/report stay unchanged, prior notes
  return exactly, and both new annotation steps remain in editable history.
- Eleven static checks cover host selection, full-field equality, number tokens,
  UTF-16 ordering, exact serialization and historical receipt boundaries.

Evidence and pinned upstream source excerpts are retained locally in
`.verify/inspect-host-migration-20261119/`; they are not part of the public export.
The fixture names synthetic foreign reports explicitly. It does not present
them as Linux-generated artifacts, authenticate prior runtime execution or
claim a newly sealed package.

## Remaining qualification

Build and execute the unchanged maintained Inspect source on the intended Linux
x86-64 worker. Run the original inputs on both real platforms and compare every
report field under the explicit reconstruction rule, then qualify bidirectional
portable editing, durable jobs, isolation, cancellation and hosted publication.
If native findings differ for reasons beyond host and evidence ID, admission
must continue to refuse them until an explicit, evidence-backed migration exists.
No Linux/Cloud release readiness follows from synthetic-host fixtures alone.
