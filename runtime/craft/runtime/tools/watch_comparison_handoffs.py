#!/usr/bin/env python3
"""Finalize structured agent reviews without another language-model roundtrip.

The registry names only the current run's rollout files and private folders.
This local controller does not author artwork, evaluate images, or retry jobs.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import signal
import subprocess
import time
from production_file_io import png_bytes, publish_files, json_bytes, image_path_from_hint


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def validate_review(review):
    if not isinstance(review, dict):
        raise ValueError("Final review must be a JSON object")
    if review.get("status") == "blocked":
        raise ValueError("Agent reported a blocked run: " + str(review.get("reason")))
    for key in ("visual_findings", "limitations"):
        if not isinstance(review.get(key), list) or not all(isinstance(v, str) for v in review[key]):
            raise ValueError("Missing review string list: " + key)
    for key in ("environment_failures", "workflow_failures", "recovery_actions", "troubleshooting_actions"):
        if type(review.get(key)) is not int or review[key] != 0:
            raise ValueError("Clean review requires zero: " + key)
    if review.get("earlier_assets_recipes_history_read") is not False:
        raise ValueError("Prior artwork/history use must be false")


def finish_image(folder, review, session_id):
    if review.get("reference_images_used") is not False:
        raise ValueError("Reference images are not permitted")
    metadata_paths = review.get("attempt_metadata")
    if metadata_paths is None:
        metadata_paths = [str(p) for p in sorted(folder.glob("attempt-??-metadata.json"))]
    if not isinstance(metadata_paths, list) or not 1 <= len(metadata_paths) <= 2:
        raise ValueError("Expected one or two attempt metadata files")
    attempts = []
    allowed_generated = (Path.home() / ".codex/generated_images" / session_id).resolve()
    for item in metadata_paths:
        path = Path(item).resolve()
        if not path.is_relative_to(folder):
            raise ValueError("Metadata must belong to the current private folder")
        metadata = json.loads(path.read_text())
        if "output_hint" in metadata:
            image = image_path_from_hint(metadata["output_hint"])
            if "source_image" in metadata and Path(metadata["source_image"]).resolve() != image:
                raise ValueError("Image path differs from original tool output hint")
            metadata["source_image"] = str(image)
        else:
            image = Path(metadata["source_image"]).resolve()
        prompt = Path(metadata["prompt_path"]).resolve()
        if not (image.is_relative_to(folder) or image.is_relative_to(allowed_generated)):
            raise ValueError("Image must belong to this fresh run")
        if not image.is_file() or not prompt.is_file() or not prompt.is_relative_to(folder):
            raise ValueError("Current image and prompt must exist")
        attempts.append(metadata)
    index = review.get("selected_attempt")
    if type(index) is not int or not 1 <= index <= len(attempts):
        raise ValueError("Invalid selected attempt")
    selected = attempts[index - 1]
    image = Path(selected["source_image"])
    raw, dimensions = png_bytes(image)
    final = folder / "final.png"
    completion_path = folder / "completion.json"
    if final.exists() or completion_path.exists():
        raise ValueError("Final deliverables already exist")
    prompt = folder / "prompt.txt"
    completion = dict(review, final_image=str(final), actual_dimensions=list(dimensions),
                      render_attempts=len(attempts), generation_metadata=attempts,
                      prompt_paths=[a["prompt_path"] for a in attempts],
                      started_at=attempts[0]["started_at"], finished_at=now(),
                      provider_model_identity=None, provider_usage=None, provider_billing=None,
                      final_image_sha256=hashlib.sha256(raw).hexdigest(), originals_retained=True)
    publish_files(folder, {"final.png": raw,
                          "prompt.txt": Path(selected["prompt_path"]).read_bytes(),
                          "completion.json": json_bytes(completion)})


def finish_api_image(folder, review):
    """Finalize a measured API attempt without discarding provider usage."""
    folder = Path(folder).resolve()
    if review.get('reference_images_used') is not False:
        raise ValueError('Reference images are not permitted')
    paths = sorted(folder.glob('attempt-??/attempt-result.json'))
    if not 1 <= len(paths) <= 2:
        raise ValueError('Expected one or two API attempts')
    attempts = []
    for path in paths:
        result = json.loads(path.read_text())
        if result.get('status') != 'succeeded':
            raise ValueError('Failed API attempts must remain separately reported')
        source = Path(result['preview_path']).resolve()
        if not source.is_relative_to(folder) or not source.is_file():
            raise ValueError('API image must belong to this run')
        raw, dimensions = png_bytes(source)
        if hashlib.sha256(raw).hexdigest() != result['image_sha256']:
            raise ValueError('API image hash changed')
        attempts.append(dict(result, provider_response=json.loads((path.parent/'api-result.json').read_text()),
                             request=json.loads((path.parent/'request.json').read_text()),
                             prompt_path=str(path.parent/'prompt.txt')))
    selected = review.get('selected_attempt')
    if type(selected) is not int or not 1 <= selected <= len(attempts):
        raise ValueError('Invalid selected API attempt')
    chosen = attempts[selected-1]
    raw, dimensions = png_bytes(chosen['preview_path'])
    completion = dict(review, final_image=str(folder/'final.png'), actual_dimensions=list(dimensions),
                      render_attempts=len(attempts), attempts=attempts, finished_at=now(),
                      provider_model_identity=chosen['request']['model'],
                      provider_usage=[a['provider_response'].get('usage') for a in attempts],
                      provider_billing=None, originals_retained=True,
                      final_image_sha256=hashlib.sha256(raw).hexdigest())
    publish_files(folder, {'final.png':raw, 'prompt.txt':Path(chosen['prompt_path']).read_bytes(),
                           'completion.json':json_bytes(completion)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--completion-tool", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--awake", action="store_true")
    parser.add_argument("--deadline-seconds", type=int, default=1200)
    args = parser.parse_args()
    registry_path = args.registry.resolve()
    root = registry_path.parent
    status_path = root / "controller-status.json"
    state = {"started_at": now(), "status": "running", "routes": {},
             "max_heartbeat_gap_seconds": 0, "sleep_or_stall_detected": False,
             "awake_guard_enabled": args.awake, "finalization_model_requests": 0}
    guard = None
    streams = {}
    start = last = time.time()

    def stop(signum, frame):
        raise SystemExit("Controller stopped by signal")

    signal.signal(signal.SIGTERM, stop)
    try:
        if args.awake:
            lid = subprocess.run(["/usr/sbin/ioreg", "-r", "-k", "AppleClamshellState", "-d", "4"],
                                 capture_output=True, text=True, check=True, timeout=10).stdout
            if re.search(r'"AppleClamshellState"\s*=\s*Yes', lid):
                raise RuntimeError("Open the laptop lid before the comparison")
            state["lid_open_at_start"] = bool(re.search(r'"AppleClamshellState"\s*=\s*No', lid))
            guard = subprocess.Popen(["/usr/bin/caffeinate", "-di", "-t", "1800"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            state["awake_guard_pid"] = guard.pid
        write(status_path, state)
        while time.time() - start < args.deadline_seconds:
            current = time.time()
            gap = current - last
            last = current
            state["max_heartbeat_gap_seconds"] = round(max(gap, state["max_heartbeat_gap_seconds"]), 3)
            if gap > 15:
                state["sleep_or_stall_detected"] = True
            registry = json.loads(registry_path.read_text())
            for route, entry in registry["routes"].items():
                if route in state["routes"]:
                    continue
                folder = Path(entry["folder"]).resolve()
                if not folder.is_relative_to(root):
                    raise ValueError("Run folders must be inside the registry root")
                source = Path(entry["rollout"])
                if not source.exists():
                    continue
                if route not in streams:
                    with source.open() as stream:
                        session_id = json.loads(stream.readline())["payload"]["id"]
                    streams[route] = {"offset": 0, "partial": "", "session_id": session_id}
                cursor = streams[route]
                with source.open() as stream:
                    stream.seek(cursor["offset"])
                    data = cursor["partial"] + stream.read()
                    cursor["offset"] = stream.tell()
                lines = data.split("\n")
                cursor["partial"] = lines.pop()
                for line in lines:
                    if not line:
                        continue
                    row = json.loads(line)
                    payload = row.get("payload", {})
                    if row.get("type") != "event_msg" or payload.get("type") != "task_complete":
                        continue
                    try:
                        review = json.loads(payload["last_agent_message"])
                        validate_review(review)
                        review_path = folder / "visual-review.json"
                        write(review_path, review)
                        if route == "adopecli":
                            selected = review.get("selected_run")
                            if selected is None:
                                attempt = review.get("selected_attempt")
                                if type(attempt) is not int or attempt not in (1, 2):
                                    raise ValueError("Selected attempt must be 1 or 2")
                                selected = str(folder / f"attempt-{attempt:02d}.run" / "run.json")
                            result = subprocess.run([str(args.python), str(args.completion_tool),
                                                     "--root", str(folder), "--selected", selected,
                                                     "--review", str(review_path)],
                                                    capture_output=True, text=True, timeout=10)
                            (folder / "finalization.stdout").write_text(result.stdout)
                            (folder / "finalization.stderr").write_text(result.stderr)
                            if result.returncode:
                                raise RuntimeError("Completion utility failed: " + result.stderr[-1000:])
                        elif route == "imagegen":
                            if entry.get('provider') == 'openai-api':
                                finish_api_image(folder, review)
                            else:
                                finish_image(folder, review, cursor["session_id"])
                        else:
                            raise ValueError("Unknown comparison route")
                        state["routes"][route] = {"status": "succeeded", "agent_finished_at": row["timestamp"],
                                                  "artifacts_finished_at": now(), "model_requests": 0}
                    except Exception as error:
                        state["routes"][route] = {"status": "failed", "error": str(error), "finished_at": now()}
                    break
            state["heartbeat_at"] = now()
            write(status_path, state)
            if set(state["routes"]) == set(registry["expected_routes"]):
                state["status"] = "succeeded" if all(v["status"] == "succeeded" for v in state["routes"].values()) else "failed"
                if state["status"] == "succeeded" and state["sleep_or_stall_detected"]:
                    state["status"] = "timing_invalid"
                break
            time.sleep(1)
        else:
            state["status"] = "timed_out"
    except BaseException as error:
        state.update(status="failed", error=str(error))
        raise
    finally:
        if guard is not None:
            guard.terminate()
            guard.wait(timeout=5)
            state["awake_guard_released"] = True
        state["finished_at"] = now()
        write(status_path, state)
    return 0 if state["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
