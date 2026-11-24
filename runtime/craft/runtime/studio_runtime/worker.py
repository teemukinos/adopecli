"""A local supervisor independent of MCP client lifetimes."""
import fcntl
import json
import os
from pathlib import Path
import signal
import resource
import subprocess
import sys
import tempfile
import time
import uuid
from .store import Store, Conflict, LeaseLost
from . import capabilities, limits, capacity, execution
from . import offline


class Worker:
    def __init__(self, store, workspace="local"):
        self.store = store
        self.workspace = workspace
        self.name = "local-" + uuid.uuid4().hex
        self.stopping = False

    @staticmethod
    def stop_process(proc):
        # The process group belongs exclusively to this live Popen child.
        if proc.poll() is None:
            try:
                # These operations have no external effects to reconcile and
                # write only disposable attempt outputs. Stop the whole group
                # atomically: waiting only for a TERM-killed leader can leave a
                # child that ignores TERM running after cancellation is reported.
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            except ProcessLookupError:
                proc.wait()

    def fail(self, *args, process=None, **kwargs):
        if process is not None and not execution.wait_group_absent(process.pid):
            return self.store.interrupt(args[0], args[1], args[2], "Execution leader exited but process group absence is unproven; reconciliation required")
        # The engine has exited or its process group has been stopped before
        # releasing journal headroom. An active engine must not consume it.
        capacity.check(self.store.root, self.store.storage_generation, recovery=True)
        return self.store.fail(*args, **kwargs)

    def run_one(self):
        job = self.store.claim(self.workspace, self.name, capabilities.OPERATIONS)
        if job is None:
            return False
        token = job["token"]; job_id = job["id"]
        attempts = self.store.root / "attempts"
        root = attempts / token
        proc = None
        started = time.monotonic()
        before_usage=resource.getrusage(resource.RUSAGE_CHILDREN)
        measurements={}
        try:
            attempts.mkdir(exist_ok=True, mode=0o700)
            policy = limits.load(self.store.root)
            with self.store.transaction() as db:
                self.store._lease(db, self.workspace, job_id, token)
                self.store._event(db, job_id, "execution_limits", {"attempt": job["attempt"], **policy})
            request = {**job["request"], "limits": policy}
            capabilities.validate(request["operation"], request["parameters"], request["source_revision"])
            if job["source_revision"]:
                self.store.checkout(self.workspace, job["source_revision"], root)
            else:
                root.mkdir(mode=0o700)
            for asset, path in capabilities.asset_inputs(request['operation'], request['parameters']).items():
                self.store.materialize_asset(self.workspace, job['project'], asset, root / path,
                                             allow_existing=request['operation'] in ('video.edit', 'layout.edit'))
            (root / "request.json").write_text(json.dumps(request) + "\n")
            # No provider tokens, service keys or database configuration reach the engine.
            env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TZ") if k in os.environ}
            temporary = Path(tempfile.mkdtemp(prefix=".studio-tmp-", dir=root))
            env.update({"TMPDIR": str(temporary), "TMP": str(temporary), "TEMP": str(temporary), "HOME": str(root), "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                        "PYTHONDONTWRITEBYTECODE": "1", "VECTORCRAFT_NO_PREFS": "1"})
            with open(root / "engine.log", "wb") as log:
                read_gate, write_gate = os.pipe()
                try:
                    proc = subprocess.Popen([sys.executable, "-I", "-B", str(Path(__file__).with_name("attempt_boot.py")), str(root), str(os.getpid()), str(read_gate)],
                                            cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                            pass_fds=(read_gate,), start_new_session=True)
                    execution.register(self.store, self.workspace, job_id, token, proc.pid)
                    # The pipe belongs to this supervisor and is not reachable
                    # from public job data or caller environment variables.
                    os.write(write_gate, b'O' if offline.inherited() else b'1')
                finally:
                    os.close(read_gate); os.close(write_gate)
                next_check = time.monotonic()
                while proc.poll() is None:
                    state = self.store.heartbeat(self.workspace, job_id, token)
                    if time.monotonic() >= next_check:
                        violation = limits.observe(proc.pid, root, policy, measurements)
                        next_check = time.monotonic() + 1
                        if violation or time.monotonic() - started >= policy["wall_seconds"]:
                            self.stop_process(proc)
                            self.fail(self.workspace, job_id, token, "resource_exhausted", violation or "execution time budget exceeded", process=proc)
                            return True
                    if self.stopping or state["cancel_requested"] or state["deadline_exceeded"]:
                        self.stop_process(proc)
                        cancelled = state["cancel_requested"]
                        self.fail(self.workspace, job_id, token,
                                        "cancelled" if cancelled else "worker_stopped" if self.stopping else "deadline_exceeded",
                                        "Engine process group stopped", cancelled=cancelled, process=proc)
                        return True
                    time.sleep(0.25)
            if proc.returncode != 0:
                error = json.loads((root / "error.json").read_text()) if (root / "error.json").exists() else {
                    "code": "engine_exit", "message": f"Engine attempt exited with status {proc.returncode}"}
                self.fail(self.workspace, job_id, token, error["code"], error["message"], process=proc)
                return True
            if not execution.wait_group_absent(proc.pid):
                self.store.interrupt(self.workspace, job_id, token, "Execution process group absence is unproven after its leader exited")
                return True
            result = json.loads((root / "result.json").read_text())
            violation = limits.observe(proc.pid, root, policy, measurements)
            if violation or time.monotonic() - started >= policy["wall_seconds"]:
                self.fail(self.workspace, job_id, token, "resource_exhausted", violation or "execution time budget exceeded", process=proc)
                return True
            state = self.store.heartbeat(self.workspace, job_id, token)
            if state["cancel_requested"] or state["deadline_exceeded"]:
                self.fail(self.workspace, job_id, token, "cancelled" if state["cancel_requested"] else "deadline_exceeded",
                                "Result was not published", cancelled=state["cancel_requested"], process=proc)
                return True
            self.store.validating(self.workspace, job_id, token)
            self.store.publish(self.workspace, job_id, token, root, result["artifacts"], result["engine"], result["validation"])
        except LeaseLost:
            if proc:
                self.stop_process(proc)
        except Exception as e:
            if proc:
                self.stop_process(proc)
            try:
                self.fail(self.workspace, job_id, token, "runtime_failure", str(e)[:2000], process=proc)
            except LeaseLost:
                pass
        finally:
            after_usage=resource.getrusage(resource.RUSAGE_CHILDREN)
            measurements.update(attempt=job['attempt'],token=token,wall_seconds=time.monotonic()-started,
                                child_user_cpu_seconds=after_usage.ru_utime-before_usage.ru_utime,
                                child_system_cpu_seconds=after_usage.ru_stime-before_usage.ru_stime,
                                memory_basis='sampled process-group RSS; not an exact peak',energy_joules=None)
            try:
                with self.store.transaction() as db:
                    self.store._event(db,job_id,'execution_measurement',measurements)
            except (Conflict,OSError):
                pass
        return True

    def run(self, once=False, idle_exit=None):
        """Process jobs until stopped. idle_exit (seconds) ends the worker after that
        long without work; bin/dope uses it for the worker it starts on demand."""
        # Kernel lock, not a stale PID file. The OS releases it when this supervisor dies.
        with open(self.store.root / "worker.lock", "a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Conflict("a local worker already owns this runtime")
            def stop(_signal, _frame):
                self.stopping = True
            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            self.store.recover(self.workspace)
            last_work = time.monotonic()
            while not self.stopping:
                worked = self.run_one()
                if once:
                    return
                if worked:
                    last_work = time.monotonic()
                elif idle_exit is not None and time.monotonic() - last_work >= idle_exit:
                    return
                else:
                    time.sleep(0.25)
