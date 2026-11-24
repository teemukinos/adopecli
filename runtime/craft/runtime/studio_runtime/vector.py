"""Qualified command subset for editable vector documents; no arbitrary commands."""
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time


OPERATIONS = ("vector.create", "vector.revise_text", "vector.revise_geometry")
# Object type -> native node kind. Shapes take a bounding box; text takes a size.
KINDS = {"rectangle": "Rectangle", "text": "Type", "ellipse": "Ellipse", "polygon": "Polygon"}
SHAPES = ("rectangle", "ellipse", "polygon")


def validate(operation, params, source_revision):
    if operation not in OPERATIONS:
        raise ValueError("unsupported capability")
    if not isinstance(params, dict):
        raise ValueError("parameters must be an object")
    if operation == "vector.revise_geometry":
        changes = params.get("objects")
        if (not source_revision or set(params) != {"objects"} or not isinstance(changes, dict)
                or not 1 <= len(changes) <= 200):
            raise ValueError("geometry revisions require a source revision and 1 to 200 named objects")
        for name, bounds in changes.items():
            if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name)
                    or not isinstance(bounds, dict) or not bounds or set(bounds) - {"x", "y", "width", "height"}):
                raise ValueError("geometry requires named objects and x/y/width/height bounds")
            for key, value in bounds.items():
                low = -8192 if key in ("x", "y") else 1
                if type(value) not in (int, float) or not low <= value <= 8192:
                    raise ValueError("geometry position must be -8192..8192 and size 1..8192 points")
        return
    if operation == "vector.revise_text":
        if not source_revision or set(params) != {"text"} or not isinstance(params["text"], dict) or not params["text"]:
            raise ValueError("text revisions require a source revision and a nonempty text mapping")
        for name, text in params["text"].items():
            if not isinstance(name, str) or not isinstance(text, str) or len(text) > 10000:
                raise ValueError("invalid text revision")
        return
    if source_revision is not None or set(params) - {"width", "height", "objects"}:
        raise ValueError("vector.create requires a new project and supported parameters")
    for name in ("width", "height"):
        value = params.get(name)
        if type(value) not in (int, float) or not 1 <= value <= 8192:
            raise ValueError("dimensions must be between 1 and 8192 points")
    objects = params.get("objects")
    if not isinstance(objects, list) or not 1 <= len(objects) <= 200:
        raise ValueError("provide 1 to 200 objects")
    names = set()
    for obj in objects:
        if not isinstance(obj, dict) or obj.get("type") not in KINDS:
            raise ValueError("supported object types: " + ", ".join(KINDS))
        name = obj.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name) or name in names:
            raise ValueError("object names must be unique identifiers")
        names.add(name)
        shape = obj["type"] in SHAPES
        allowed = ({"type", "name", "x", "y", "color"} | ({"width", "height"} if shape else {"text", "size", "font"})
                   | ({"sides"} if obj["type"] == "polygon" else set()))
        if set(obj) - allowed:
            raise ValueError("unsupported object property")
        for key in ("x", "y"):
            if type(obj.get(key)) not in (int, float) or not -8192 <= obj[key] <= 8192:
                raise ValueError("invalid object position")
        if not isinstance(obj.get("color"), str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", obj["color"]):
            raise ValueError("object color must be #rrggbb")
        for key in (("width", "height") if shape else ("size",)):
            if type(obj.get(key)) not in (int, float) or not 1 <= obj[key] <= 8192:
                raise ValueError("invalid object size")
        if obj["type"] == "polygon" and (type(obj.get("sides")) is not int or not 3 <= obj["sides"] <= 64):
            raise ValueError("polygon sides must be an integer from 3 to 64")
        if obj["type"] == "text":
            if not isinstance(obj.get("text"), str) or len(obj["text"]) > 10000:
                raise ValueError("invalid text")
            if not isinstance(obj.get("font"), str) or not 1 <= len(obj["font"]) <= 200:
                raise ValueError("text requires an explicit font family")


def engine():
    return "dobe-vector" if shutil.which("dobe-vector") else "vectorcraft-cli"


class Engine:
    label = 'vector'

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.proc = subprocess.Popen([engine(), "--safe-mode", "mcp", "--automation-read-root", str(self.root),
                                      "--automation-write-root", str(self.root)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.messages = queue.Queue(); self.counter = 0
        threading.Thread(target=self._reader, daemon=True).start()
        try:
            result = self.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                              "clientInfo": {"name": "studio-runtime", "version": "0.1.0"}})
            self.version = result["serverInfo"]["version"]
            if self.version != "0.24.1":
                raise ValueError("VectorCraft version is not qualified; expected 0.24.1")
            self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except BaseException:
            self.close()
            raise

    def _reader(self):
        try:
            for line in self.proc.stdout:
                try:
                    self.messages.put(json.loads(line))
                except ValueError:
                    pass
        finally:
            self.messages.put(None)

    def send(self, msg):
        self.proc.stdin.write(json.dumps(msg) + "\n"); self.proc.stdin.flush()

    def call(self, method, params):
        self.counter += 1; request_id = self.counter
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            message = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if message is None:
                raise RuntimeError(f"{self.label} engine exited before replying")
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(json.dumps(message["error"]))
                return message["result"]
        raise TimeoutError("engine response deadline exceeded")

    def command(self, command, params):
        result = self.call("tools/call", {"name": "command_run", "arguments": {"id": command, "params": params}})
        texts = [c["text"] for c in result.get("content", []) if c.get("type") == "text"]
        if result.get("isError"):
            raise RuntimeError("; ".join(texts)[:1000])
        parsed = [json.loads(t) for t in texts]
        if len(parsed) != 1:
            raise RuntimeError("unexpected engine command result")
        return parsed[0]

    def close(self):
        try:
            self.proc.stdin.close(); self.proc.wait(timeout=5)
        except (BrokenPipeError, subprocess.TimeoutExpired):
            self.proc.kill(); self.proc.wait()


def inspect_native(path):
    result = subprocess.run([engine(), "info", str(path)], capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise ValueError("native vector inspection failed")
    info = json.loads(result.stdout)
    if info.get("warnings") or any(font.get("missing") or font.get("missingGlyphs") or font.get("status") != "exact"
                                   for font in info.get("fonts", [])):
        raise ValueError("native vector contains missing fonts, glyphs or inspection warnings")
    return {"fonts": info.get("fonts", [])}


def polygon_fit(sides, box):
    """Largest regular polygon, one corner straight up, centred in box [x, y, width, height].

    Returns the engine's {cx, cy, radius} and the drawn bounds."""
    x, y, width, height = box
    xs = [math.sin(2 * math.pi * k / sides) for k in range(sides)]
    ys = [-math.cos(2 * math.pi * k / sides) for k in range(sides)]
    radius = min(width / (max(xs) - min(xs)), height / (max(ys) - min(ys)))
    drawn = {"width": radius * (max(xs) - min(xs)), "height": radius * (max(ys) - min(ys))}
    drawn["x"] = x + (width - drawn["width"]) / 2
    drawn["y"] = y + (height - drawn["height"]) / 2
    return {"cx": drawn["x"] - radius * min(xs), "cy": drawn["y"] - radius * min(ys), "radius": radius}, drawn


def revise_geometry(engine, objects, changes):
    """Set absolute bounds on one selected object at a time, preserving other objects.

    A polygon's bounds are its bounding box: the polygon is refitted into the new box and
    its mapping entry keeps the box. Returns True when a mapping entry changed."""
    ids = [obj["id"] for obj in objects.values()]
    before = {node["id"]: node for node in engine.command("document.inspect", {"ids": ids, "depth": 0})["nodes"]}
    expected = {}; mapping_changed = False
    for name, bounds in changes.items():
        if name not in objects:
            raise ValueError("revision names an unknown geometry object")
        obj = objects[name]; node = before.get(obj["id"])
        if node is None or node["kind"] != KINDS.get(obj["type"]):
            raise ValueError("geometry mapping does not match the native object")
        if obj["type"] == "text" and set(bounds) - {"x", "y"}:
            raise ValueError("text geometry supports position only; text size is not supported by this operation")
        if obj["type"] == "polygon":
            box = dict(zip(("x", "y", "width", "height"), obj["box"]), **bounds)
            obj["box"] = [box[key] for key in ("x", "y", "width", "height")]
            _, expected[obj["id"]] = polygon_fit(obj["sides"], obj["box"])
            mapping_changed = True
        else:
            expected[obj["id"]] = {**node["bounds"], **bounds}
        engine.command("select.set", {"ids": [obj["id"]]})
        engine.command("object.setBounds", {**expected[obj["id"]], "reference": 0,
                                            "proportional": False, "strokes": False})
    after = {node["id"]: node for node in engine.command("document.inspect", {"ids": ids, "depth": 0})["nodes"]}
    if set(before) != set(after):
        raise ValueError("geometry revision changed object identities")
    for identity, original in before.items():
        current = after[identity]
        if identity not in expected:
            if current != original:
                raise ValueError("geometry revision changed an untargeted object")
            continue
        if ({k: v for k, v in current.items() if k != "bounds"}
                != {k: v for k, v in original.items() if k != "bounds"}):
            raise ValueError("geometry revision changed another object property")
        if any(not math.isclose(current["bounds"][key], value, rel_tol=1e-9, abs_tol=1e-6)
               for key, value in expected[identity].items()):
            raise ValueError("native geometry does not match requested absolute bounds")
    return mapping_changed


def read_objects(path):
    # Portable projects are user input. Bound their mapping before parsing or
    # sending IDs to the native command server.
    with path.open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("editable object mapping exceeds 64 KiB")
    objects = json.loads(raw)
    if not isinstance(objects, dict) or not 1 <= len(objects) <= 200:
        raise ValueError("editable object mapping requires 1 to 200 objects")
    ids = set()
    for name, obj in objects.items():
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name)
                or not isinstance(obj, dict) or obj.get("type") not in KINDS
                or set(obj) != ({"id", "type", "sides", "box"} if obj["type"] == "polygon" else {"id", "type"})
                or type(obj["id"]) is not int or not 0 < obj["id"] < 2**64 or obj["id"] in ids):
            raise ValueError("invalid editable object mapping")
        if obj["type"] == "polygon" and (
                type(obj["sides"]) is not int or not 3 <= obj["sides"] <= 64
                or not isinstance(obj["box"], list) or len(obj["box"]) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in obj["box"])
                or not all(1 <= v <= 8192 for v in obj["box"][2:])):
            raise ValueError("invalid editable object mapping")
        ids.add(obj["id"])
    return objects


def execute(root, operation, params):
    root = Path(root).resolve()
    native = root / "native"; exports = root / "exports"
    native.mkdir(exist_ok=True); exports.mkdir(exist_ok=True)
    source = native / "document.vectorcraft"
    objects_file = native / "objects.json"
    engine = Engine(root)
    try:
        if operation == "vector.create":
            engine.command("file.new", {"width": params["width"], "height": params["height"], "units": "Points", "colorMode": "rgb"})
            objects = {}
            for obj in params["objects"]:
                entry = {"type": obj["type"]}
                if obj["type"] == "text":
                    result = engine.command("text.create", {k: obj[k] for k in ("x", "y", "text", "size", "font", "color")})
                    if result.get("warning") or result.get("overflow"):
                        raise ValueError("font substitution or text overflow is not qualified")
                else:
                    if obj["type"] == "polygon":
                        entry.update(sides=obj["sides"], box=[obj[k] for k in ("x", "y", "width", "height")])
                        circle, _ = polygon_fit(obj["sides"], entry["box"])
                        result = engine.command("shape.polygon", {**circle, "sides": obj["sides"]})
                    else:
                        result = engine.command("shape." + obj["type"], {k: obj[k] for k in ("x", "y", "width", "height")})
                    engine.command("paint.setFill", {"color": obj["color"]})
                    engine.command("paint.setStroke", {"none": True})
                objects[obj["name"]] = {"id": result["id"], **entry}
            objects_file.write_text(json.dumps(objects, sort_keys=True) + "\n")
        else:
            inspect_native(source)
            engine.command("file.open", {"path": str(source)})
            objects = read_objects(objects_file)
            if operation == "vector.revise_geometry":
                if revise_geometry(engine, objects, params["objects"]):
                    objects_file.write_text(json.dumps(objects, sort_keys=True) + "\n")
            else:
                for name, text in params["text"].items():
                    if name not in objects or objects[name]["type"] != "text":
                        raise ValueError("revision names an unknown text object")
                    result = engine.command("text.setText", {"id": objects[name]["id"], "text": text})
                    if result.get("overflow"):
                        raise ValueError("revised text overflows its frame")
        engine.command("file.saveAs", {"path": str(source)})
        engine.command("document.export", {"path": str(exports / "document.svg")})
        engine.command("document.export", {"path": str(exports / "document.png"), "scale": 1})
        version = engine.version
    finally:
        engine.close()
    dependencies = inspect_native(source)
    (native / "dependencies.json").write_text(json.dumps(dependencies, sort_keys=True) + "\n")
    # A fresh engine must reopen the native document and independently export it.
    reopened = Engine(root)
    try:
        reopened.command("file.open", {"path": str(source)})
        reopened.command("document.export", {"path": str(exports / "reopened.svg")})
    finally:
        reopened.close()
    if (exports / "document.svg").read_bytes() != (exports / "reopened.svg").read_bytes():
        raise ValueError("native cold-reopen changed SVG export")
    import struct
    with open(exports / "document.png", "rb") as stream:
        data = stream.read(33)
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 33:
        raise ValueError("invalid PNG export")
    width, height = struct.unpack(">II", data[16:24])
    if not 1 <= width <= 8192 or not 1 <= height <= 8192:
        raise ValueError("vector export exceeds qualified dimensions")
    (exports / "reopened.svg").unlink()
    return {"engine": {"name": "vectorcraft", "version": version, "dependencies": dependencies},
            "validation": {"passed": True, "native_cold_reopen": True, "svg_roundtrip_equal": True,
                           "png_width": width, "png_height": height,
                           **({"geometry_bounds_verified": True, "untargeted_objects_unchanged": True}
                              if operation == "vector.revise_geometry" else {})},
            "artifacts": [{"path": "native/document.vectorcraft", "role": "native"},
                          {"path": "native/objects.json", "role": "native"},
                          {"path": "native/dependencies.json", "role": "asset"},
                          {"path": "exports/document.svg", "role": "export"},
                          {"path": "exports/document.png", "role": "export"}]}
