#!/usr/bin/env python3
"""Render a new scene through the durable CLI, in a fresh project each time.

This is orchestration only: the caller supplies the complete scene document.
It never supplies artistic defaults, repairs failed jobs, or bypasses publication.
Use a private state directory without another worker or queued jobs.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--title", default="Independent photographic scene")
    args = parser.parse_args()
    cli, state, spec, output = [p.resolve() for p in
                                (args.cli, args.state, args.spec, args.output)]
    logs = output.with_name(output.name + ".run")
    if output.exists() or logs.exists():
        parser.error("Output and its .run log directory must not already exist")
    if not cli.is_file() or not spec.is_file():
        parser.error("CLI and scene specification must be existing files")
    document = json.loads(spec.read_text())
    logs.mkdir(parents=True)
    records = []
    start = time.monotonic()
    record = {"started_at": datetime.now(timezone.utc).isoformat(),
              "status": "running", "state": str(state), "spec": str(spec),
              "output": str(output), "commands": records}

    def save():
        (logs / "run.json").write_text(json.dumps(record, indent=2) + "\n")

    def call(*arguments):
        begin = time.monotonic()
        result = subprocess.run([str(cli), "--state", str(state), *arguments],
                                capture_output=True, text=True, timeout=7320)
        index = len(records) + 1
        (logs / f"{index:02d}-{arguments[0]}.stdout").write_text(result.stdout)
        (logs / f"{index:02d}-{arguments[0]}.stderr").write_text(result.stderr)
        records.append({"arguments": arguments, "exit_code": result.returncode,
                        "wall_seconds": round(time.monotonic() - begin, 3)})
        save()
        if result.returncode:
            raise RuntimeError(f"CLI {arguments[0]} failed; see {logs}")
        return json.loads(result.stdout) if result.stdout.strip() else None

    try:
        parameters = logs / "parameters.json"
        parameters.write_text(json.dumps({"document": document}, indent=2) + "\n")
        plan = call("production", "plan", "--spec", str(spec))
        if not plan.get("ready"):
            raise RuntimeError(f"Production engine is unavailable: {plan.get('reason')}")
        # production.create has no source revision. Its project head must be empty.
        # A corrected full specification is an independent creation, so it also
        # gets a new project. Existing project heads are never reset or overwritten.
        project = call("create-project", args.title)
        record["project_id"] = project["id"]
        call("limits", "--wall-seconds", "7200", "--cpu-seconds", "7200",
             "--memory-mib", "8192")
        job = call("submit", project["id"], "production.create", "--parameters",
                   str(parameters), "--key", "create-" + uuid.uuid4().hex,
                   "--timeout", "7200")
        record["job_id"] = job["id"]
        call("worker", "--once")
        status = call("job", job["id"])
        if status["state"] != "succeeded" or not status.get("result_revision"):
            raise RuntimeError(f"Production job did not publish successfully: {status}")
        revision = status["result_revision"]
        call("checkout", revision, str(output))
        image = output / "production/exports/photograph.png"
        native = output / "production/native/scene.blend"
        metrics = output / "production/metrics.json"
        if not all(p.is_file() for p in (image, native, metrics)):
            raise RuntimeError("Published checkout is missing required production files")
        record.update(status="succeeded", revision=revision,
                      final_image=str(image), native_scene=str(native),
                      engine_metrics=json.loads(metrics.read_text()))
    except Exception as error:
        record.update(status="failed", error=str(error))
        raise
    finally:
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        record["wall_seconds"] = round(time.monotonic() - start, 3)
        save()
    print(json.dumps({key: record[key] for key in
                      ("status", "project_id", "job_id", "revision", "final_image",
                       "native_scene", "wall_seconds")}, indent=2))


if __name__ == "__main__":
    main()
