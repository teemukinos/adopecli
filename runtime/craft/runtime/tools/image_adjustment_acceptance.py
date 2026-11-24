"""Qualify whole-image operations through an exact sealed public CLI package.

Run with the package's Python, PACKAGE, NEW_OUTPUT and --expect-verification.
All artwork is a small procedural fixture. No network or installed service is
used. Failed evidence remains in place; never restart an uncertain native job.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
import zipfile

from PIL import Image, ImageChops, ImageStat


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--expect-verification", type=Path, required=True)
    args = parser.parse_args()
    package = args.package.resolve(strict=True)
    out = args.output.absolute()
    out.mkdir(parents=True, mode=0o700)
    (out / "home").mkdir(mode=0o700)
    state = out / "state"
    cli = package / "bin/a-dope-cli"
    env = {"HOME": str(out / "home"), "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}
    commands, cases, jobs = [], [], []

    def save(name, value):
        (out / name).write_text(json.dumps(value, indent=2) + "\n")

    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def check(value, label):
        assert value, label
        cases.append(label)
        save("cases.json", cases)

    def run(label, arguments, *, input_text=None, expected=0):
        started = time.monotonic()
        options = {"input": input_text} if input_text is not None else {"stdin": subprocess.DEVNULL}
        result = subprocess.run(list(map(str, arguments)), env=env, capture_output=True,
                                text=True, timeout=600, **options)
        commands.append({"label": label, "arguments": list(map(str, arguments)),
                         "exit": result.returncode, "seconds": time.monotonic() - started,
                         "stdout": result.stdout, "stderr": result.stderr})
        save("commands.json", commands)
        assert result.returncode == expected, (label, result.stderr[-1500:])
        return json.loads(result.stdout) if result.stdout.strip() else None

    def call(label, *arguments, expected=0):
        return run(label, [cli, "--state", state, *arguments], expected=expected)

    def snapshot(directory):
        return {str(p.relative_to(directory)): digest(p)
                for p in directory.rglob("*") if p.is_file()}

    def job(label, project, operation, parameters, source=None, *, success=True, mcp=False):
        save(label + "-request.json", parameters)
        if mcp:
            arguments = {"project": project, "operation": operation,
                         "parameters": parameters, "idempotency_key": label,
                         "timeout_seconds": 600, "source_revision": source}
            request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "dope_submit_job", "arguments": arguments}}
            reply = run(label + " MCP submit", [cli, "--state", state, "mcp"],
                        input_text=json.dumps(request) + "\n")["result"]
            assert not reply.get("isError"), reply
            submitted = json.loads(reply["content"][0]["text"])
        else:
            arguments = ["submit", project, operation, "--parameters",
                         out / (label + "-request.json"), "--key", label, "--timeout", "600"]
            if source:
                arguments += ["--source", source]
            submitted = call(label + " submit", *arguments)
        row = {"label": label, "id": submitted["id"], "operation": operation,
               "stateDirectory": str(state), "sourceRevision": source}
        jobs.append(row)
        save("jobs.json", jobs)
        call(label + " worker", "worker", "--once")
        result = call(label + " result", "job", submitted["id"])
        row["result"] = result
        save("jobs.json", jobs)
        check(result["state"] == ("succeeded" if success else "failed"),
              label + " reaches the expected durable terminal state")
        if not success:
            check(result["result_revision"] is None, label + " publishes no revision")
            return result
        delivery = out / label
        call(label + " checkout", "checkout", result["result_revision"], delivery)
        manifest = json.loads((delivery / "project.json").read_text())
        for entry in manifest["files"]:
            path = delivery / entry["path"]
            assert path.stat().st_size == entry["bytes"] and digest(path) == entry["sha256"]
        check(manifest["validation"]["native_cold_reopen"] and
              manifest["validation"]["pixel_roundtrip_equal"],
              label + " cold reopens the native source with equal pixels")
        row["checkout"] = str(delivery)
        save("jobs.json", jobs)
        return result["result_revision"], delivery

    def inspect(directory):
        with zipfile.ZipFile(directory / "native/document.pcraft") as archive:
            native = json.loads(archive.read("manifest.json"))
            composite = Image.open(io.BytesIO(archive.read("composite/full.png"))).convert("RGBA")
        pixels = Image.open(directory / "exports/document.png").convert("RGBA")
        check(composite.size == pixels.size and composite.tobytes() == pixels.tobytes(),
              directory.name + " saved native composite equals every reopened PNG pixel")
        identity = [{key: layer.get(key) for key in ("id", "name", "blend", "opacity", "visible")}
                    for layer in native["document"]["layers"]]
        assert identity
        return pixels, identity

    expected = json.loads(args.expect_verification.read_text())
    verified = run("verify package before", [package / "bin/a-dope-guard", "verify"])
    check(verified == expected and verified["verified"], "exact sealed package verifies before work")
    source = out / "source.png"
    original = Image.new("RGB", (64, 48))
    colors = ((48, 96, 144), (160, 64, 96), (80, 144, 48), (144, 128, 64))
    for y in range(48):
        for x in range(64):
            original.putpixel((x, y), colors[(x >= 32) + 2 * (y >= 24)])
    original.save(source)
    source_hash = digest(source)
    owner = call("project", "create-project", "Whole-image operation qualification")["id"]
    asset = call("source asset", "import-asset", owner, source)["id"]
    revision, neutral = job("neutral", owner, "image.adjust", {"asset": asset})
    neutral_pixels, identity = inspect(neutral)
    check(neutral_pixels.tobytes() == original.convert("RGBA").tobytes(),
          "neutral import retains every original eight-bit pixel")
    check(digest(neutral / "assets/input") == source_hash, "neutral import retains exact source bytes")
    original_files = snapshot(neutral)

    bright_revision, bright = job("brighter", owner, "image.revise", {"brightness": 30}, revision)
    bright_pixels, bright_identity = inspect(bright)
    before = list(neutral_pixels.convert("RGB").getdata())
    after = list(bright_pixels.convert("RGB").getdata())
    check(bright_pixels.size == (64, 48) and bright_identity == identity,
          "brightness revision preserves dimensions and native layer identity/order/style")
    check(all(b >= a for old, new in zip(before, after) for a, b in zip(old, new)) and
          sum(ImageStat.Stat(bright_pixels.convert("RGB")).mean) > sum(ImageStat.Stat(original).mean),
          "positive brightness increases measured color values without darkening any source channel")
    check(bright_pixels.getchannel("A").getextrema() == (255, 255),
          "brightness preserves opaque alpha")

    small_revision, small = job("resized", owner, "image.revise", {"width": 32, "height": 24}, bright_revision)
    small_pixels, small_identity = inspect(small)
    check(small_pixels.size == (32, 24) and small_identity == identity,
          "explicit width and height resize the native raster while retaining layer identity/order/style")
    expected_colors = [bright_pixels.getpixel(point)[:3] for point in ((8, 8), (56, 8), (8, 40), (56, 40))]
    check([small_pixels.getpixel(point)[:3] for point in ((4, 4), (28, 4), (4, 20), (28, 20))] == expected_colors,
          "resizing preserves the four independent interior colors and their placement")
    small_files = snapshot(small)

    state = out / "portable-state"
    imported = call("portable import", "import-project", small, "Portable whole-image revision")
    portable_owner = imported["project"]["id"]
    final_revision, final = job("monochrome", portable_owner, "image.revise", {"saturation": -100},
                                imported["revision"]["id"], mcp=True)
    final_pixels, final_identity = inspect(final)
    channels = final_pixels.convert("RGB").split()
    check(final_pixels.size == (32, 24) and final_identity == identity,
          "MCP-directed portable revision retains the resized canvas and native layer identity")
    check(ImageChops.difference(channels[0], channels[1]).getextrema()[1] <= 1 and
          ImageChops.difference(channels[1], channels[2]).getextrema()[1] <= 1,
          "complete desaturation produces neutral decoded pixels within one eight-bit channel level")
    check(final_pixels.tobytes() != small_pixels.tobytes(), "portable revision changes actual exported pixels")

    bad = out / "sixteen-bit.png"
    Image.new("I;16", (8, 8), 16384).save(bad)
    bad_owner = call("unsupported depth project", "create-project", "Depth refusal")["id"]
    bad_asset = call("unsupported depth asset", "import-asset", bad_owner, bad)["id"]
    head = call("depth head before", "project", bad_owner)
    refused = job("unsupported-depth", bad_owner, "image.adjust", {"asset": bad_asset}, success=False)
    check("8-bit" in json.dumps(refused) and call("depth head after", "project", bad_owner) == head,
          "unsupported native depth fails without changing the project or publishing output")
    head = call("dimension head before", "project", portable_owner)
    save("invalid-dimensions.json", {"width": 8193})
    call("invalid dimensions", "submit", portable_owner, "image.revise", "--source", final_revision,
         "--parameters", out / "invalid-dimensions.json", "--key", "invalid-dimensions", expected=1)
    check(call("dimension head after", "project", portable_owner) == head,
          "oversized requested dimensions are refused before native work")
    check(snapshot(neutral) == original_files and snapshot(small) == small_files and digest(source) == source_hash,
          "later jobs leave original input and prior native deliveries byte-identical")
    check(all(digest(d / "assets/input") == source_hash for d in (bright, small, final)),
          "each native and portable revision retains the exact original source asset")

    groups = []
    for directory in (out / "state", out / "portable-state"):
        with sqlite3.connect("file:" + str(directory / "studio.sqlite3") + "?mode=ro", uri=True) as db:
            groups.extend(row[0] for row in db.execute(
                "SELECT process_group FROM attempt_executions WHERE process_group IS NOT NULL"))
    for group in groups:
        try:
            os.killpg(group, 0)
        except ProcessLookupError:
            continue
        raise AssertionError("native process group remains: " + str(group))
    check(len(groups) == len(jobs), "every native attempt has an execution receipt and no live process group")
    check(run("verify package after", [package / "bin/a-dope-guard", "verify"]) == verified,
          "all successful and refused work leaves the sealed package unchanged")
    save("evidence.json", {"passed": True, "checks": len(cases), "cases": cases,
         "nativeJobs": len(jobs), "successfulNativeJobs": 4, "expectedFailedNativeJobs": 1,
         "operations": ["image.adjust", "image.revise"], "groups": groups,
         "allNativeGroupsAbsent": True, "verification": verified, "sourceSHA256": source_hash,
         "sourceOverlays": False, "wholeImageQualified": False, "completeReleaseQualified": False,
         "ownerDesignApproval": False, "LinuxQualified": False, "remoteActions": False})
    print(json.dumps({"passed": True, "checks": len(cases), "nativeJobs": len(jobs)}))


if __name__ == "__main__":
    main()
