"""Image adjustments with retained native layers and cold-reopen pixel checks."""
import json
import hashlib
from pathlib import Path
import struct
import subprocess
import shutil
import zipfile

OPERATIONS = ("image.adjust", "image.revise")


def validate(operation, params, source_revision):
    if operation not in OPERATIONS or not isinstance(params, dict):
        raise ValueError("unsupported image operation or parameters")
    allowed = {"brightness", "contrast", "vibrance", "saturation", "width", "height"}
    if operation == "image.adjust":
        allowed.add("asset")
        if source_revision or not isinstance(params.get("asset"), str) or not params["asset"]:
            raise ValueError("image.adjust requires an imported asset and no source revision")
    elif not source_revision:
        raise ValueError("image.revise requires a source revision")
    if set(params) - allowed:
        raise ValueError("unsupported image parameter")
    for name, low, high in (("brightness", -150, 150), ("contrast", -50, 100), ("vibrance", -100, 100), ("saturation", -100, 100)):
        if name in params and (type(params[name]) not in (int, float) or not low <= params[name] <= high):
            raise ValueError(f"{name} is outside its supported range")
    for name in ("width", "height"):
        if name in params and (type(params[name]) is not int or not 1 <= params[name] <= 8192):
            raise ValueError("image dimensions must be integers between 1 and 8192")


def engine():
    return 'dobe-image' if shutil.which('dobe-image') else 'photocraft-cli'


def run(args):
    if args and args[0] == 'photocraft-cli':
        args = [engine(), *args[1:]]
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr[-1000:] or result.stdout[-1000:] or "image engine failed")
    return result.stdout


def pixel_hash(path):
    try:
        from PIL import Image
    except ImportError:
        # Source-run installations can reuse their existing FFmpeg. Offline
        # application bundles include Pillow and do not need an external binary.
        return run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "hash", "-hash", "sha256", "-pix_fmt", "rgba", "-"]).strip()
    with Image.open(path) as image:
        if image.format != "PNG" or image.width > 8192 or image.height > 8192:
            raise ValueError("image validation requires a bounded PNG")
        return "SHA256=" + hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()


def retained_assets(root):
    artifacts = []
    directory = Path(root) / 'assets'
    if directory.is_symlink():
        raise ValueError('image assets must not use a symlinked directory')
    for path in sorted(directory.rglob('*')) if directory.exists() else []:
        if path.is_symlink():
            raise ValueError('image assets must not contain symlinks')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('image assets must be regular files')
        artifacts.append({'path': path.relative_to(root).as_posix(), 'role': 'asset'})
    return artifacts


def execute(root, operation, params):
    version_text = run(["photocraft-cli", "--version"]).strip()
    version = version_text.split()[1]
    if version != "0.23.1":
        raise ValueError("image engine version is not qualified; expected 0.23.1")
    root = Path(root).resolve(); native = root / "native"; exports = root / "exports"
    native.mkdir(exist_ok=True); exports.mkdir(exist_ok=True)
    source = root / "assets" / "input" if operation == "image.adjust" else native / "document.pcraft"
    # Detect the input's actual format; a user-controlled filename never selects commands.
    info = json.loads(run(["photocraft-cli", "info", "--compact", str(source)]))
    if info.get("depth") != 8 or any(type(info.get(k)) is not int or not 1 <= info[k] <= 8192 for k in ("width", "height")):
        raise ValueError("qualified images require 8-bit depth and dimensions up to 8192 pixels")
    args = ["photocraft-cli", "run", str(source), "--no-gpu"]
    for keys, command in ((('brightness', 'contrast'), 'image.adjustments.brightnessContrast'),
                          (('vibrance', 'saturation'), 'image.adjustments.vibrance'),
                          (('width', 'height'), 'image.imageSize')):
        changes = {k: params[k] for k in keys if k in params}
        if changes:
            args += ["--cmd", command, "--params", json.dumps(changes)]
    pending = native / "pending.pcraft"
    run(args + ["--out", str(pending), "--pcraft-full-composite"])
    pending.replace(native / "document.pcraft")
    output = exports / "document.png"
    run(["photocraft-cli", "convert", "--no-gpu", str(native / "document.pcraft"), str(output)])
    # The native save's full composite is the pre-reopen visual reference.
    reference = exports / "saved-composite.png"
    with zipfile.ZipFile(native / "document.pcraft") as archive:
        entry = archive.getinfo("composite/full.png")
        if entry.file_size > (512 << 20):
            raise ValueError("native composite exceeds validation budget")
        with archive.open(entry) as src, open(reference, "wb") as dst:
            import shutil
            shutil.copyfileobj(src, dst)
    if pixel_hash(reference) != pixel_hash(output):
        raise ValueError("native cold-reopen changed image pixels")
    reference.unlink()
    reopened_info = json.loads(run(["photocraft-cli", "info", "--compact", str(native / "document.pcraft")]))
    if info.get("warnings") or reopened_info.get("warnings"):
        raise ValueError("image engine reported inspection warnings")
    # Adjustment and resize operations must retain editable layer identity and masks.
    structure_keys = ("id", "kind", "name", "hasMask", "hasVectorMask", "blend", "opacity", "visible")
    structure = lambda value: [{k: layer.get(k) for k in structure_keys} for layer in value.get("layers", [])]
    if not info.get("layers") or structure(info) != structure(reopened_info):
        raise ValueError("image operation changed layer identity or mask structure")
    with open(output, "rb") as f:
        header = f.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("invalid PNG export")
    width, height = struct.unpack(">II", header[16:24])
    if not 1 <= width <= 8192 or not 1 <= height <= 8192:
        raise ValueError("image output exceeds qualified dimensions")
    for key in ("file", "path"):
        if key in reopened_info:
            reopened_info[key] = "native/document.pcraft"
    (native / "structure.json").write_text(json.dumps(reopened_info, sort_keys=True) + "\n")
    from . import font_policy
    font_manifest = native / 'fonts-manifest.json'
    glyphs = font_policy.write(native / 'document.pcraft', font_manifest)
    if glyphs is None and font_manifest.exists():
        # A legacy engine must not carry a positive claim from an earlier Dobe
        # revision into an output whose shaped fonts it did not inspect.
        font_manifest.write_text(json.dumps({'schema_version': 1, 'glyph_coverage_verified': False,
                                             'reason': 'engine lacks shaped-font diagnostics'}) + '\n')
    artifacts = [{"path": "native/document.pcraft", "role": "native"},
                 {"path": "native/structure.json", "role": "native"},
                 {"path": "exports/document.png", "role": "export"}]
    artifacts += retained_assets(root)
    if (native / 'fonts-manifest.json').is_file():
        artifacts.append({'path': 'native/fonts-manifest.json', 'role': 'asset'})
    return {"engine": {"name": "photocraft", "version": version, "build": version_text}, "artifacts": artifacts,
            "validation": {"passed": True, "native_cold_reopen": True, "pixel_roundtrip_equal": True, "layer_structure_preserved": True,
                           "png_width": width, "png_height": height, "glyph_coverage_verified": glyphs is not None,
                           "font_validation_scope": glyphs['scope'] if glyphs else 'not_revalidated'}}
