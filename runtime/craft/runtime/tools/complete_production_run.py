#!/usr/bin/env python3
"""Assemble a checked-out production delivery after the agent's visual review."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from production_file_io import png_bytes, publish_files, json_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--selected", type=Path, required=True,
                        help="Selected attempt's .run/run.json")
    parser.add_argument("--review", type=Path, required=True,
                        help="Authored visual_findings, limitations and provenance")
    args = parser.parse_args()
    root = args.root.resolve()
    selected_path = args.selected.resolve()
    if not selected_path.is_relative_to(root):
        parser.error("Selected record must be inside the private run root")
    review = json.loads(args.review.read_text())
    for key in ("visual_findings", "limitations"):
        if not isinstance(review.get(key), list) or not all(isinstance(s, str) for s in review[key]):
            parser.error(f"Review must contain a string list: {key}")
    for key in ("environment_failures", "workflow_failures", "recovery_actions", "troubleshooting_actions"):
        if type(review.get(key)) is not int or review[key] != 0:
            parser.error(f"Clean completion requires an explicitly reported zero: {key}")
    if review.get("earlier_assets_recipes_history_read") is not False:
        parser.error("Review must report earlier_assets_recipes_history_read as false")
    paths = sorted(root.glob("*.run/run.json"))
    if selected_path not in [p.resolve() for p in paths]:
        parser.error("Selected record must be a direct attempt under the run root")
    attempts = [json.loads(p.read_text()) for p in paths]
    if not attempts or any(a.get("status") != "succeeded" or not a.get("revision")
                           or any(c["exit_code"] != 0 for c in a["commands"])
                           for a in attempts):
        parser.error("Every recorded attempt must have published and checked out successfully")
    selected = json.loads(selected_path.read_text())
    targets = [root / "final.png", root / "final.blend", root / "completion.json"]
    if any(p.exists() for p in targets):
        parser.error("Final deliverables must not already exist")
    image, native = Path(selected["final_image"]), Path(selected["native_scene"])
    for source in (image, native):
        if not source.resolve().is_relative_to(root) or not source.is_file():
            parser.error("Selected artifacts must exist inside the private run root")
    raw, dimensions = png_bytes(image)
    native_bytes = native.read_bytes()
    completion = dict(review, final_image=str(targets[0]), native_scene=str(targets[1]),
                      actual_dimensions=list(dimensions), render_attempts=len(attempts),
                      started_at=min(a["started_at"] for a in attempts),
                      started_at_basis="First render start; transcript start includes prior authoring",
                      finished_at=datetime.now(timezone.utc).isoformat(),
                      publication_status="succeeded", selected_revision=selected["revision"],
                      spec_paths=[a["spec"] for a in attempts],
                      engine_metrics=[a["engine_metrics"] for a in attempts],
                      attempts=attempts, final_image_sha256=hashlib.sha256(raw).hexdigest())
    publish_files(root, {"final.png": raw, "final.blend": native_bytes,
                         "completion.json": json_bytes(completion)})
    print(json.dumps({"status": "succeeded", "completion": str(targets[2]),
                      "final_image": str(targets[0]), "render_attempts": len(attempts)}))


if __name__ == "__main__":
    main()
