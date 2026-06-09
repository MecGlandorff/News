from pathlib import Path


DEFAULT_INK = (0.08, 0.08, 0.08)


class PDFDocument:
    def __init__(self):
        self.pages = []

    def add_page(self, width, height):
        page = PDFPage(width, height)
        self.pages.append(page)
        return page

    def save(self, path):
        objects = {}
        next_id = 1
        font_ids = {}
        for name, base_font in {
            "F1": "Helvetica",
            "F2": "Helvetica-Bold",
            "F3": "Times-Roman",
            "F4": "Times-Bold",
            "F5": "Times-Italic",
        }.items():
            font_ids[name] = next_id
            objects[next_id] = f"<< /Type /Font /Subtype /Type1 /BaseFont /{base_font} /Encoding /WinAnsiEncoding >>".encode("ascii")
            next_id += 1

        pages_id = next_id
        next_id += 1
        catalog_id = next_id
        next_id += 1

        page_ids = []
        font_refs = " ".join(f"/{name} {obj_id} 0 R" for name, obj_id in font_ids.items())
        for page in self.pages:
            stream = "\n".join(page.ops).encode("latin-1", "replace")
            content_id = next_id
            next_id += 1
            objects[content_id] = b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"
            page_id = next_id
            next_id += 1
            page_ids.append(page_id)
            objects[page_id] = (
                f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {page.width:.2f} {page.height:.2f}] "
                f"/Resources << /Font << {font_refs} >> >> /Contents {content_id} 0 R >>"
            ).encode("ascii")

        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
        objects[pages_id] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")
        objects[catalog_id] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii")

        max_id = max(objects)
        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0] * (max_id + 1)
        for obj_id in range(1, max_id + 1):
            offsets[obj_id] = len(output)
            output.extend(f"{obj_id} 0 obj\n".encode("ascii"))
            output.extend(objects[obj_id])
            output.extend(b"\nendobj\n")
        xref_offset = len(output)
        output.extend(f"xref\n0 {max_id + 1}\n".encode("ascii"))
        output.extend(b"0000000000 65535 f \n")
        for obj_id in range(1, max_id + 1):
            output.extend(f"{offsets[obj_id]:010d} 00000 n \n".encode("ascii"))
        output.extend(
            f"trailer\n<< /Size {max_id + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
        )
        Path(path).write_bytes(output)


class PDFPage:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.ops = []

    def text(self, x, y, text, font, size, fill=DEFAULT_INK):
        self.ops.append(
            f"BT {_rgb(fill, fill_op=True)} /{font} {size:.2f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({_escape_text(text)}) Tj ET"
        )

    def line(self, x1, y1, x2, y2, width=0.5, stroke=DEFAULT_INK):
        self.ops.append(f"{_rgb(stroke)} {width:.2f} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def rect(self, x, y, width, height, fill=None, stroke=DEFAULT_INK, line_width=0.5):
        op = []
        if fill:
            op.append(_rgb(fill, fill_op=True))
        if stroke:
            op.append(_rgb(stroke))
        op.append(f"{line_width:.2f} w {x:.2f} {y:.2f} {width:.2f} {height:.2f} re")
        if fill and stroke:
            op.append("B")
        elif fill:
            op.append("f")
        else:
            op.append("S")
        self.ops.append(" ".join(op))

    def polygon(self, points, fill=DEFAULT_INK, stroke=None, line_width=0.25):
        if not points:
            return
        ops = []
        if fill:
            ops.append(_rgb(fill, fill_op=True))
        if stroke:
            ops.append(_rgb(stroke))
        ops.append(f"{line_width:.2f} w")
        first = points[0]
        ops.append(f"{first[0]:.2f} {first[1]:.2f} m")
        for x, y in points[1:]:
            ops.append(f"{x:.2f} {y:.2f} l")
        ops.append("h")
        if fill and stroke:
            ops.append("B")
        elif fill:
            ops.append("f")
        else:
            ops.append("S")
        self.ops.append(" ".join(ops))

    def circle(self, x, y, radius, fill=DEFAULT_INK, stroke=None, line_width=0.5):
        k = 0.5522847498
        c = radius * k
        ops = []
        if fill:
            ops.append(_rgb(fill, fill_op=True))
        if stroke:
            ops.append(_rgb(stroke))
        ops.append(f"{line_width:.2f} w")
        ops.append(f"{x + radius:.2f} {y:.2f} m")
        ops.append(f"{x + radius:.2f} {y + c:.2f} {x + c:.2f} {y + radius:.2f} {x:.2f} {y + radius:.2f} c")
        ops.append(f"{x - c:.2f} {y + radius:.2f} {x - radius:.2f} {y + c:.2f} {x - radius:.2f} {y:.2f} c")
        ops.append(f"{x - radius:.2f} {y - c:.2f} {x - c:.2f} {y - radius:.2f} {x:.2f} {y - radius:.2f} c")
        ops.append(f"{x + c:.2f} {y - radius:.2f} {x + radius:.2f} {y - c:.2f} {x + radius:.2f} {y:.2f} c")
        ops.append("h")
        if fill and stroke:
            ops.append("B")
        elif fill:
            ops.append("f")
        else:
            ops.append("S")
        self.ops.append(" ".join(ops))


def _rgb(color, fill_op=False):
    op = "rg" if fill_op else "RG"
    return f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} {op}"


def _escape_text(text):
    encoded = str(text or "").encode("cp1252", "replace").decode("latin-1")
    return (
        encoded
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", " ")
        .replace("\n", " ")
    )
