# Sealed worker lifecycle — 18 November 2026

The native CLI now admits `local` through a dedicated sealed management helper.
A new private installation ran two real native Image jobs through its independent
launchd worker: initial creation, then a queued revision after stop and restart.
No manually running worker was required. This is local transient-service evidence,
not a production, login/reboot or complete Local/Cloud release qualification.

## Qualified artifact

Machine-local evidence identifier: `sealed-service-arddukwy`. The isolated
qualification package retains the development input's version
`0.1.0-guarded-launch-qualification`; its exact identity is the following new
seal and guard, not that version string alone:

- Payload seal: `b3324e29521258b63c65c36b4db20edecf1ba30ddd5968931584a621ec39f4f9`.
- Native guard: `3cfdf3d51f8ca40198cee95e9af0e8512c167b03bedfcf8685d2203bd89e096c`.
- Seal entries: 3,309, including the new sealed management helper.
- Platform: development macOS ARM64; ad-hoc rehearsal, publisher unauthenticated.

The probe builds from frozen copies of the four changed implementation files,
installs into a new private prefix and verifies the installed native seal. Both
implementation hashes and complete command results are retained in
`evidence.json`, `source-hashes.json` and `commands.json`. The original package
and the user's existing installation remain unchanged. A retained version with
different authenticated contents is still refused within one prefix.

## Execution and ownership evidence

Four integration groups pass:

1. The installed CLI starts a transient launchd worker from a private plist;
   repeated start retains its PID. Status distinguishes registration, loaded
   state and the running worker observation.
2. The independent worker completes `image.create` after the submitting process
   exits. Checkout delivers editable `.pcraft` and PNG files.
3. Stop unloads the worker while retaining registration. An `image.edit` job
   remains queued while stopped and succeeds after restart. Installation is
   refused both while running and while stopped with registration retained.
4. Disable unloads the owned service, archives its ownership files and retains
   projects and versions. The completed job remains readable, and installation
   succeeds again after disabling. No login plist is created.

The boundary probe adds twelve groups. It refuses management from an uninstalled
package, symlinked prefixes, unsafe receipt permissions, changed guard identity,
non-object ownership JSON, competing installation locks, dangling installation
journals, unrecorded plists, symlinked log directories and hardlinked logs.
Outside marker bytes and foreign plist bytes remain unchanged. Modifying the
sealed helper is rejected by the native guard before Python management starts.
Unknown management actions are rejected by the fixed command parser.

An actual process in a separate private process group supplies an orphan fixture.
Disable refuses while that group is alive, without terminating it. After the
probe terminates its own process and kernel absence is established, disable
succeeds. An unknown origin remains refused. This fixture checks the shutdown
proof against real kernel observations; it is separate from a real native
engine crash/reconciliation test.

The probe also kills its own idle launchd worker and observes launchd restart it
with a new PID. Changed ownership arguments and a modified loaded plist cannot
redirect stop or replace that running worker. After restoring the exact owned
records, disable succeeds and repeated disable is harmless. Final status and
native verification pass; every run-owned launchd job is absent. Boundary logs
and `boundary-evidence.json` retain these outcomes.

## Management exception and retained failure

The first probe, `sealed-service-lzoiaioh`, failed at bootstrap because launchd
refused the sandboxed management caller. launchd recorded `Operation not
permitted`; the private registration was disabled and its exact label was
confirmed absent. The failed run remains available.

Only the fixed sealed management helper now runs outside the runtime OS
sandbox. The native guard still verifies its signature and complete payload,
uses isolated bundled Python, strips unrelated environment variables and closes
extra descriptors. The helper accepts only its fixed lifecycle actions and
requires the exact active installation. Every launchd worker executes the
retained guard's normal runtime route, which applies network and payload-write
denial. Management itself does not have those OS denials. This is an explicit
trusted management boundary, not a general unsandboxed runtime command.

Intermediate passing probes are retained. The final probe includes additional
receipt-permission, journal-symlink and JSON-shape validation. The final source
hashes, rather than an earlier passing probe, identify the implementation qualified
here.

## Remaining requirements

Explicit `enable` implements login registration, but this unit does not execute
it or qualify login, logout, reboot or locked-screen behavior. All actual service
runs use new transient private plists; the user's LaunchAgents directory,
existing services, shell profiles and MCP configuration are untouched.

Updates currently require explicit disable/install/start (or enable) sequencing.
Automatic stop/switch/resume, a package-uninstall command, legacy-prefix
migration, service-log rotation, real in-flight native engine shutdown under
launchd, authenticated publisher/stock-host qualification and the remaining
complete-product gates are unfinished. Existing runtime attempt recovery and
resource limits retain their separate qualification. No remote action,
deployment or production-readiness claim is made by this record.
