# Offline construction execution

The public macOS runtime enters an OS network-denial policy before bundled
Python starts. The native payload guard verifies the complete sealed package,
protects its files from writes and launches the fixed bootstrap under that
policy. Development package launchers also apply network denial. The separate
lifecycle helper does not execute creative jobs and does not enter the offline
execution scope.

Construction and photographic production must inherit this policy. Applying
another `sandbox-exec` inside an already sandboxed process fails on macOS. The
retained Slides qualification package reproduces that failure through public
`construct.create`; a ready plan establishes dependency availability only.

## Trusted control flow

`studio_runtime.offline` records process-local context established by the fixed
bundle bootstrap. This context is not kernel attestation or authentication of
arbitrary Python callers. It cannot be selected by a public operation parameter,
CLI option or environment variable.

The local supervisor registers each attempt's process group before releasing its
private admission pipe. Byte `1` admits an ordinary source attempt; byte `O`
admits an attempt that inherits the bootstrap's offline boundary. The child
accepts only these two bytes. EOF or another byte refuses execution. The worker
creates the pipe, retains its write end, and passes only the read end to its own
child. It does not obtain either the descriptor or admission value from job data.
The existing process-group cancellation, parent watchdog and resource limits
continue to apply.

Inside this scope, supporting engines execute directly and inherit the OS
policy. Outside it, construction requires a fresh `sandbox-exec` around its fixed
private bootstrap; that bootstrap records the established scope for supporting
children. Standalone supporting-process and photographic-production calls also
require a fresh sandbox. A failed sandbox launch fails the operation. There is
no retry without confinement.

The old `DOBE_CONSTRUCTION_OFFLINE` environment flag no longer selects execution
behavior. Generic `sandbox_check` results are not used to infer inherited policy:
local counterexamples show that unfiltered denial can coexist with permitted
endpoint or path exceptions.

Direct execution of private bootstrap Python files or native engine executables
is outside the sealed public-entry contract. This change does not claim to make
arbitrary caller-controlled Python code trusted. Scripts importing an internal
scope function are trusted program code, not supported job input. Linux hosted
workers retain their separate isolation and admission contracts; this helper
does not authorize construction in an ordinary native Cloud worker.

## Qualification

`craft/tests/construction_offline_check.py` checks actual macOS denial for IPv4,
IPv6 and UDP loopback attempts in standalone and inherited supporting-process
routes. It also checks ordinary versus inherited admission, EOF/invalid-byte
refusal, ignored environment spoofing, failed nested-policy refusal, scope reset
and adapter provenance. Run this focused check directly: its cases establish
their own OS policies. Wrapping the entire check in an additional sandbox would
prevent its standalone cases from establishing theirs.

These checks do not replace real sealed-package construction, native cold
reopening, inherited payload-write protection or campaign acceptance. An updated
package must be rebuilt and sealed, then exercised through its public CLI. The
old failed package and its durable failure remain evidence. Publisher signing,
stock-host installation, visual approval and complete Local/Cloud release gates
remain separate.
