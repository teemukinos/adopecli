"""Vector ellipse and polygon objects: validator, polygon fitting, mapping and rendering."""
import json
import math
import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from studio_runtime import vector


def create(*objects):
    return {"width": 200, "height": 120, "objects": list(objects)}


ELLIPSE = {"name": "dot", "type": "ellipse", "x": 10, "y": 20, "width": 60, "height": 40, "color": "#FF0000"}
POLYGON = {"name": "hex", "type": "polygon", "x": 100, "y": 10, "width": 80, "height": 80, "sides": 6, "color": "#00FF00"}


class ValidatorTest(unittest.TestCase):
    def test_accepts_ellipse_and_polygon(self):
        vector.validate("vector.create", create(ELLIPSE, POLYGON), None)

    def test_unknown_type_names_all_four_types(self):
        with self.assertRaises(ValueError) as caught:
            vector.validate("vector.create", create({**ELLIPSE, "type": "star"}), None)
        for kind in ("rectangle", "text", "ellipse", "polygon"):
            self.assertIn(kind, str(caught.exception))

    def test_polygon_sides_bounds(self):
        for sides in (2, 65, 4.0, "6", True, None):
            with self.subTest(sides=sides), self.assertRaises(ValueError):
                vector.validate("vector.create", create({**POLYGON, "sides": sides}), None)
        for sides in (3, 64):
            vector.validate("vector.create", create({**POLYGON, "sides": sides}), None)

    def test_sides_only_on_polygons(self):
        with self.assertRaises(ValueError):
            vector.validate("vector.create", create({**ELLIPSE, "sides": 5}), None)

    def test_shapes_need_a_box(self):
        for key in ("width", "height"):
            broken = dict(ELLIPSE); del broken[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                vector.validate("vector.create", create(broken), None)


class PolygonFitTest(unittest.TestCase):
    def test_corner_up_and_largest_in_box(self):
        for sides in (3, 4, 5, 6, 7, 64):
            for box in ([0, 0, 100, 100], [10, 20, 300, 50], [5, 5, 40, 200]):
                with self.subTest(sides=sides, box=box):
                    circle, drawn = vector.polygon_fit(sides, box)
                    corners = [(circle["cx"] + circle["radius"] * math.sin(2 * math.pi * k / sides),
                                circle["cy"] - circle["radius"] * math.cos(2 * math.pi * k / sides)) for k in range(sides)]
                    xs = [p[0] for p in corners]; ys = [p[1] for p in corners]
                    self.assertAlmostEqual(min(ys), drawn["y"])  # the first corner points straight up
                    self.assertAlmostEqual(corners[0][0], box[0] + box[2] / 2)
                    self.assertAlmostEqual(min(xs), drawn["x"]); self.assertAlmostEqual(max(xs), drawn["x"] + drawn["width"])
                    self.assertAlmostEqual(max(ys), drawn["y"] + drawn["height"])
                    self.assertTrue(math.isclose(drawn["width"], box[2]) or math.isclose(drawn["height"], box[3]))
                    self.assertLessEqual(drawn["width"], box[2] + 1e-9); self.assertLessEqual(drawn["height"], box[3] + 1e-9)


class MappingTest(unittest.TestCase):
    def mapping(self, objects):
        directory = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, directory)
        path = directory / "objects.json"; path.write_text(json.dumps(objects))
        return path

    def test_reads_ellipse_and_polygon(self):
        objects = {"dot": {"id": 1, "type": "ellipse"}, "hex": {"id": 2, "type": "polygon", "sides": 6, "box": [0, 0, 10, 10]}}
        self.assertEqual(vector.read_objects(self.mapping(objects)), objects)

    def test_refuses_bad_polygon_entries(self):
        for entry in ({"id": 2, "type": "polygon"}, {"id": 2, "type": "polygon", "sides": 2, "box": [0, 0, 10, 10]},
                      {"id": 2, "type": "polygon", "sides": 6, "box": [0, 0, 10]},
                      {"id": 2, "type": "ellipse", "sides": 6, "box": [0, 0, 10, 10]}, {"id": 2, "type": "star"}):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                vector.read_objects(self.mapping({"shape": entry}))


def png_pixels(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    position, chunks, header = 8, [], None
    while position < len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        body = data[position + 8:position + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            chunks.append(body)
        position += 12 + length
    width, height, depth, color = header[:4]
    assert depth == 8 and color in (2, 6)
    channels = 4 if color == 6 else 3
    raw = zlib.decompress(b"".join(chunks)); stride = width * channels
    rows, previous, offset = [], bytearray(stride), 0
    for _ in range(height):
        kind = raw[offset]; line = bytearray(raw[offset + 1:offset + 1 + stride]); offset += 1 + stride
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = previous[i]; corner = previous[i - channels] if i >= channels else 0
            if kind == 1: line[i] = (line[i] + left) & 255
            elif kind == 2: line[i] = (line[i] + up) & 255
            elif kind == 3: line[i] = (line[i] + (left + up) // 2) & 255
            elif kind == 4:
                p = left + up - corner; pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                line[i] = (line[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 255
        rows.append(bytes(line)); previous = line
    return lambda x, y: tuple(rows[y][x * channels:x * channels + 3])


@unittest.skipUnless(shutil.which("dobe-vector") or shutil.which("vectorcraft-cli"), "vector engine not on PATH")
class RenderTest(unittest.TestCase):
    def assertColor(self, actual, expected):
        self.assertTrue(all(abs(a - b) <= 8 for a, b in zip(actual, expected)), (actual, expected))

    def test_shapes_render_and_move(self):
        root = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, root)
        background = {"name": "ground", "type": "rectangle", "x": 0, "y": 0, "width": 200, "height": 120, "color": "#000000"}
        params = create(background, ELLIPSE, POLYGON)
        vector.validate("vector.create", params, None)
        vector.execute(root, "vector.create", params)
        pixel = png_pixels(root / "exports/document.png")
        for shape, color in ((ELLIPSE, (255, 0, 0)), (POLYGON, (0, 255, 0))):
            cx = int(shape["x"] + shape["width"] / 2)
            self.assertColor(pixel(cx, int(shape["y"] + shape["height"] / 2)), color)
            self.assertColor(pixel(cx, int(shape["y"] + shape["height"] / 4)), color)
            self.assertColor(pixel(shape["x"] + 1, shape["y"] + 1), (0, 0, 0))
        mapping = json.loads((root / "native/objects.json").read_text())
        self.assertEqual(mapping["hex"]["box"], [100, 10, 80, 80])

        revised = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, revised)
        shutil.copytree(root / "native", revised / "native")
        moves = {"objects": {"dot": {"x": 120, "y": 60}, "hex": {"x": 10, "y": 30, "width": 60}}}
        vector.execute(revised, "vector.revise_geometry", moves)
        pixel = png_pixels(revised / "exports/document.png")
        self.assertColor(pixel(150, 80), (255, 0, 0))
        self.assertColor(pixel(40, 70), (0, 255, 0))
        self.assertEqual(json.loads((revised / "native/objects.json").read_text())["hex"]["box"], [10, 30, 60, 80])


if __name__ == "__main__":
    unittest.main()
