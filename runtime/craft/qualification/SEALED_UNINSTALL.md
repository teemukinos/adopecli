# Recoverable uninstall with project retention — 18 November 2026

The sealed CLI now supports `local uninstall --retain-projects`. It stops and
unregisters its owned worker, removes the public command link and retains project
data, installed versions, logs and history. A durable journal permits recovery
through the retained native guard even after command removal. Reinstallation
restores activation without erasing projects or replaying stopped jobs.

This is a retaining uninstall/deactivation route. It does not reclaim retained
package storage or erase all application data. The flag makes retention an
explicit choice; selected project deletion remains the existing separate
preview/apply workflow. No recursive purge, global MCP removal or termination of
agent client processes is implied.

## Exact artifact

Machine-local evidence identifier: `sealed-uninstall-77o3e5w6`.

- Package version: `0.1.0-guarded-launch-qualification`, in a new private prefix.
- Native guard SHA-256:
  `0fe9dde1adf5b1db2735f1c1c4140584bbcaecb4044134e9e17127aedaa8aaa0`.
- Payload seal SHA-256:
  `7d7ea4bac30f40036fe782985b0fa1787cc8b22a1d29852710e57091c3917ccf`.
- Seal entries: 3,309. Platform: macOS ARM64 development host.
- Signing mode: ad-hoc rehearsal, with no authenticated publisher claim.

The development version string is retained from the build input; exact guard
and seal identities distinguish this fixture from earlier packages with that
string. Four frozen implementation sources are hashed in `source-hashes.json`.
The new behavior changes the sealed installer and lifecycle helper. The native
launcher and builder retain their previous implementation.

## Actual engine shutdown and recovery

Four integration groups pass:

1. The private launchd worker first creates an editable native image. A separate
   video job starts the real `dobe-video` engine. The probe observes its actual
   PID and registered process group while the job is running, then requests
   uninstall. The worker stops its engine group before deactivation. The job
   ends with `worker_stopped`, no result revision, no project head and proven
   process-group absence. The completed image remains available.
2. The retained guard reports uninstalled status with no MCP activation command.
   Worker startup refuses until explicit reinstall. Reinstallation restores the
   public command, and a targeted edit of the original image succeeds through
   launchd. The stopped video job remains at attempt 1; it is not replayed.
3. A second real native video job is running when the probe starts uninstall.
   After observing the durable `prepared` journal and a still-present engine
   group, the probe sends SIGKILL to its own uninstall process. Installation and
   worker startup refuse the pending transaction. The retained guard resumes
   uninstall, stops the native group and completes the journal. This second job
   also ends with `worker_stopped`, without publishing a revision.
4. Both completed uninstall journals are archived. Repeated uninstall is
   harmless. The original project's checkout remains byte-identical across
   uninstall, reinstall, subsequent editing and another uninstall.

There are two completed Image jobs and two deliberately stopped Video jobs in
this integration run. The Video jobs establish in-flight shutdown, not delivered
video quality or completed-video export acceptance. The probe observes actual
engine processes rather than inferring execution from a queued job alone.

## Boundary and interruption coverage

Eight further groups pass through the installed native entry point:

- Bare uninstall and a retention flag on another action are rejected before
  installation metadata changes.
- Explicit fixtures for all four journal phases (`prepared`,
  `services_disabled`, `command_removed`, `complete`) resume successfully.
  Installation refuses every pending phase. These phase fixtures supplement,
  and are distinct from, the actual SIGKILL run above.
- Changed guard identity, version, command target, phase, boolean schema and
  substituted deletion policy are refused without changing activation.
- Dangling symlinks and hardlinked journal files cannot supply ownership evidence.
- A foreign regular command or link to outside content is preserved and refused.
- An existing archive destination is preserved; recovery succeeds only after
  the probe explicitly moves its own collision fixture aside.
- A competing installation lock prevents uninstall from racing package mutation.
- A real live orphan process group leaves the journal prepared and public command
  intact. The helper does not terminate that remembered group. Only after the
  probe terminates its own process and absence is established can uninstall
  resume and remove activation.

`evidence.json`, `commands.json`, the two `*-running.json` records and
`killed-uninstall.json` retain native execution and interruption observations.
`boundary-evidence.json` and `boundary-commands.json` retain the refusal and
phase-recovery checks. Final native payload verification passes. Every run-owned
launchd job and observed native process group is absent.

An earlier passing rehearsal, `sealed-uninstall-aysu4r12`, predates the required
retention flag. It remains retained evidence; the final artifact and all twelve
qualification groups above use the explicit retention contract.

## Remaining release boundary

No existing user installation, persistent login registration, shell profile,
global MCP configuration or remote service is changed. The trusted management
helper still runs outside the runtime OS sandbox for launchd control; every
worker re-enters the native guarded runtime policy. Uninstall does not expand
that exception into arbitrary execution or recursive deletion.

Automatic update/resume, legacy-prefix migration, login/reboot and locked-session
qualification, service-log rotation, authenticated publisher/stock-host evidence,
Linux/Cloud execution, complete native-app contracts and remaining release gates
are still unfinished. This record does not establish a released or production-
ready product, a data-erasure guarantee or the complete-catalog repeatability gate.
