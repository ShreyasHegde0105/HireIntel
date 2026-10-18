import ctypes
import io
import logging
import re
import zipfile
from dataclasses import dataclass
from typing import List, NamedTuple, Optional

from lxml import etree

logger = logging.getLogger(__name__)


class DocumentError(ValueError):
    """A problem with an uploaded document. The message is safe to show to users."""


IMAGE_MIME_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
EXTENSION_TO_FORMAT = {
    "pdf": "pdf",
    "docx": "docx",
    "txt": "txt",
    "png": "png",
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "webp": "webp",
}
SUPPORTED_HINT = "Supported formats: PDF, DOCX, TXT, PNG, JPG, WEBP."


# pypdfium2 marks a hyphenated line break with U+FFFE after joining the word halves
# ("soft￾ware"), and Word uses U+00AD soft hyphens; both are dropped. Other control
# characters (often from icon fonts in contact lines) are dropped too, keeping newlines and tabs.
_INVISIBLE_CHARS = re.compile("[￾­\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def clean_text(text: str) -> str:
    """Normalises extracted text so words match the way they read in the document."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _INVISIBLE_CHARS.sub("", text).strip()


def _extension(filename: str) -> str:
    return filename.lower().rsplit(".", 1)[-1] if "." in filename else ""


def _sniff(file_bytes: bytes) -> str:
    """Identifies the real file type from its first bytes. Returns '' when unknown."""
    head = file_bytes[:1024]
    if b"%PDF-" in head:
        return "pdf"
    if file_bytes.startswith(b"\xd0\xcf\x11\xe0"):
        return "ole"  # legacy .doc / .xls / .ppt
    if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if file_bytes.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WEBP":
        return "webp"
    if file_bytes.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                if "word/document.xml" in zf.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            pass
        return "zip"
    return ""


def detect_format(file_bytes: bytes, filename: str) -> str:
    """Checks that the extension is supported and matches the file's actual content.

    Returns one of: pdf, docx, txt, png, jpeg, webp.
    """
    if not file_bytes:
        raise DocumentError("The file is empty.")

    ext = _extension(filename)
    if ext == "doc":
        raise DocumentError("Legacy .doc files are not supported. Please re-save the file as DOCX or PDF.")
    expected = EXTENSION_TO_FORMAT.get(ext)
    if expected is None:
        if not ext:
            raise DocumentError(f"The file has no extension. {SUPPORTED_HINT}")
        raise DocumentError(f"Unsupported file type '.{ext}'. {SUPPORTED_HINT}")

    actual = _sniff(file_bytes)
    if expected == "txt":
        if actual or b"\x00" in file_bytes[:4096]:
            raise DocumentError("This .txt file does not contain plain text.")
        return "txt"
    if actual == "ole":
        raise DocumentError("This looks like a legacy Word (.doc) file. Please re-save it as DOCX or PDF.")
    if actual != expected:
        raise DocumentError(f"The file content does not match its .{ext} extension.")
    return expected


class Extraction(NamedTuple):
    text: str
    # Text a reader of the document cannot see (hidden, white, tiny or off-page). It is left out
    # of `text` and reported so a recruiter can look at it: hidden keywords or instructions
    # aimed at AI screeners are a known way to game resume screening.
    hidden: List[str]


# Hidden-text heuristics are deliberately conservative: white text on a coloured sidebar or
# banner is normal design, and dropping it would lose real content. White text is only treated
# as hidden when nothing coloured could be behind it.
_TINY_TEXT_PT = 1.5


def _near_white(r: int, g: int, b: int) -> bool:
    return min(r, g, b) >= 240


# --- PDF ----------------------------------------------------------------------------------


def _pdf_covers(page, pdfium_raw) -> tuple:
    """Bounding boxes of images and filled, non-white shapes (white text on them is visible),
    and whether the page has an image at all."""
    covers, has_image = [], False
    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    fill_mode, stroke = ctypes.c_int(), ctypes.c_int()
    for obj in page.get_objects():
        if obj.type == pdfium_raw.FPDF_PAGEOBJ_IMAGE:
            has_image = True
            covers.append(obj.get_bounds())
        elif obj.type == pdfium_raw.FPDF_PAGEOBJ_SHADING:
            covers.append(obj.get_bounds())
        elif obj.type == pdfium_raw.FPDF_PAGEOBJ_PATH:
            if not pdfium_raw.FPDFPath_GetDrawMode(obj.raw, ctypes.byref(fill_mode), ctypes.byref(stroke)) or not fill_mode.value:
                continue
            if pdfium_raw.FPDFPageObj_GetFillColor(obj.raw, *(ctypes.byref(c) for c in (r, g, b, a))):
                if a.value and not _near_white(r.value, g.value, b.value):
                    covers.append(obj.get_bounds())
    return covers, has_image


def _pdf_page_text(page, textpage, pdfium_raw) -> tuple:
    """Returns (visible text, hidden snippets) for one page."""
    full_text = textpage.get_text_range()
    tp = textpage.raw
    covers, has_image = _pdf_covers(page, pdfium_raw)
    left, bottom, right, top = page.get_cropbox()
    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    box = pdfium_raw.FS_RECTF()

    # None: whitespace or a space/line break pdfium inserted itself; it takes no side.
    flags = []
    for i in range(pdfium_raw.FPDFText_CountChars(tp)):
        if pdfium_raw.FPDFText_IsGenerated(tp, i) == 1 or chr(pdfium_raw.FPDFText_GetUnicode(tp, i)).isspace():
            flags.append(None)
            continue
        pdfium_raw.FPDFText_GetLooseCharBox(tp, i, ctypes.byref(box))
        cx, cy = (box.left + box.right) / 2, (box.bottom + box.top) / 2
        hidden = box.top - box.bottom < _TINY_TEXT_PT or not (left - 1 <= cx <= right + 1 and bottom - 1 <= cy <= top + 1)
        if not hidden:
            mode = pdfium_raw.FPDFTextObj_GetTextRenderMode(pdfium_raw.FPDFText_GetTextObject(tp, i))
            # Invisible text over a scanned image is a normal OCR layer, not hidden text.
            hidden = mode == pdfium_raw.FPDF_TEXTRENDERMODE_INVISIBLE and not has_image
        if not hidden and pdfium_raw.FPDFText_GetFillColor(tp, i, *(ctypes.byref(c) for c in (r, g, b, a))):
            if a.value == 0:
                hidden = True
            elif _near_white(r.value, g.value, b.value):
                hidden = not any(cl <= cx <= cr and cb <= cy <= ct for cl, cb, cr, ct in covers)
        flags.append(hidden)

    if not any(flags):
        return full_text, []

    # Rebuild the text without hidden characters. Whitespace between two hidden characters
    # belongs to the hidden phrase; elsewhere it stays in the visible text.
    visible, snippets, current = [], [], None
    for i, flag in enumerate(flags):
        char = textpage.get_text_range(i, 1)
        if flag:
            current = (current or "") + char
        elif flag is None and current is not None:
            current += char
        else:
            if current is not None:
                snippets.append(current)
                current = None
            visible.append(char)
    if current is not None:
        snippets.append(current)
    return "".join(visible), [s.strip() for s in snippets if s.strip()]


def parse_pdf(file_bytes: bytes) -> Extraction:
    """Extracts the visible text layer of a PDF.

    Returns '' for a readable PDF with no text layer (a scan), so the caller can try OCR.
    Raises DocumentError for corrupt or password-protected files, which OCR cannot fix.
    """
    errors = []

    # 1. Primary fast C++ engine: pypdfium2
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as pdfium_raw

        pdf = pdfium.PdfDocument(file_bytes)
        try:
            extracted, hidden = [], []
            for page in pdf:
                textpage = page.get_textpage()
                try:
                    page_text, page_hidden = _pdf_page_text(page, textpage, pdfium_raw)
                except Exception as e:
                    # Detection is a safety net; never lose the text because of it.
                    logger.warning("pdf hidden-text check failed", extra={"error": type(e).__name__})
                    page_text, page_hidden = textpage.get_text_range(), []
                if page_text:
                    extracted.append(page_text)
                hidden.extend(page_hidden)
                textpage.close()
                page.close()
        finally:
            pdf.close()
        text = "\n".join(extracted).strip()
        if text or hidden:
            return Extraction(text, hidden)
    except Exception as e:
        errors.append(e)

    # 2. Secondary: pdfplumber (no hidden-text check)
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages_text = [pt for pt in (page.extract_text() for page in pdf.pages) if pt]
        return Extraction("\n".join(pages_text).strip(), [])
    except Exception as e:
        errors.append(e)

    logger.info("pdf could not be opened", extra={"errors": [type(e).__name__ for e in errors]})
    raise DocumentError("This PDF could not be opened. It may be corrupt or password-protected.")


# --- DOCX ---------------------------------------------------------------------------------
# python-docx does not read text boxes, content controls or headers in document order, so the
# OOXML is walked directly. Resume templates put names, contact lines and whole sidebars in
# text boxes and headers, and losing them silently makes a candidate look weaker than they are.

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"

# Uncompressed size caps protect against zip bombs. A 5 MB upload never legitimately needs more.
MAX_DOCX_PART_BYTES = 50 * 1024 * 1024
MAX_DOCX_TOTAL_BYTES = 100 * 1024 * 1024

# No DTDs, no entity expansion, no network: defends against XXE and entity-expansion attacks.
_XML_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


def _w(tag: str) -> str:
    return f"{{{_W}}}{tag}"


# Elements whose content is not visible text: properties, tracked deletions, moved-from text,
# field codes (e.g. HYPERLINK "..."). The visible result of a field is kept.
_SKIP = {_w(t) for t in ("pPr", "rPr", "tblPr", "trPr", "tcPr", "sectPr", "del", "moveFrom", "delText", "instrText")}
_TAB = {_w("tab"), _w("ptab")}
_BREAK = {_w("br"), _w("cr")}
_WRAPPERS = {_w(t) for t in ("sdt", "sdtContent", "customXml", "ins", "moveTo", "smartTag")}


def _wval(el, tag: str):
    """The w:val of child `tag`: None if the child is absent, '' if it has no value."""
    child = el.find(_w(tag)) if el is not None else None
    return None if child is None else child.get(_w("val"), "")


def _hex_colour(value) -> Optional[tuple]:
    value = (value or "").lstrip("#")
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _is_fill(value) -> bool:
    """True for a shading or fill colour that is visibly coloured (not auto, none or white)."""
    rgb = _hex_colour(value)
    return rgb is not None and not _near_white(*rgb)


def _shaded(props) -> bool:
    shd = props.find(_w("shd")) if props is not None else None
    return shd is not None and _is_fill(shd.get(_w("fill")))


@dataclass(frozen=True)
class _RunFormat:
    """The run properties that decide whether text is visible. None means not set at this level."""

    vanish: Optional[bool] = None
    size: Optional[int] = None  # half-points
    color: Optional[str] = None
    background: Optional[bool] = None  # highlight or run shading

    @classmethod
    def of(cls, rpr) -> "_RunFormat":
        if rpr is None:
            return cls()
        vanish, size, highlight = _wval(rpr, "vanish"), _wval(rpr, "sz"), _wval(rpr, "highlight")
        background = None
        if highlight is not None or rpr.find(_w("shd")) is not None:
            background = (highlight not in (None, "", "none")) or _shaded(rpr)
        return cls(
            vanish=None if vanish is None else vanish.lower() not in ("0", "false", "off"),
            size=int(size) if size and size.isdigit() else None,
            color=_wval(rpr, "color"),
            background=background,
        )

    def over(self, base: "_RunFormat") -> "_RunFormat":
        """This format layered on top of `base`."""
        return _RunFormat(
            vanish=base.vanish if self.vanish is None else self.vanish,
            size=base.size if self.size is None else self.size,
            color=base.color if self.color is None else self.color,
            background=base.background if self.background is None else self.background,
        )


def _chosen_branch(alternate):
    """mc:AlternateContent holds the same object twice (modern drawing and a VML fallback).
    Reading both would duplicate text-box text, so only the first branch is used."""
    for branch in alternate:
        if branch.tag in (f"{{{_MC}}}Choice", f"{{{_MC}}}Fallback"):
            return branch
    return None


def _children(el, tag: str):
    """Direct children with this tag, including ones wrapped in content controls (w:sdt)."""
    for child in el:
        if child.tag == tag:
            yield child
        elif child.tag in (_w("sdt"), _w("sdtContent"), _w("customXml")):
            yield from _children(child, tag)


def _has_coloured_background(root) -> bool:
    """True if the part has images, filled shapes or a page colour that white text could sit on."""
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue  # comments and processing instructions
        if el.tag in (f"{{{_A}}}blip", _w("background")) or el.get("fillcolor"):
            return True
        if el.tag == f"{{{_A}}}solidFill" and not el.getparent().tag.endswith("}ln"):
            return True  # a shape fill (a solidFill under a:ln is only an outline)
    return False


class _DocxPackage:
    def __init__(self, file_bytes: bytes):
        self._zip = zipfile.ZipFile(io.BytesIO(file_bytes))
        self._read_total = 0

    def xml(self, name: str):
        info = self._zip.getinfo(name)
        self._read_total += info.file_size
        if info.file_size > MAX_DOCX_PART_BYTES or self._read_total > MAX_DOCX_TOTAL_BYTES:
            raise DocumentError("This DOCX file is too large once uncompressed.")
        return etree.fromstring(self._zip.read(name), _XML_PARSER)

    def has(self, name: str) -> bool:
        return name in self._zip.namelist()


class _DocxReader:
    """Reads visible text in document order and sets hidden text aside."""

    def __init__(self, pkg: _DocxPackage):
        self.hidden: List[str] = []
        self.white_check = True
        self.defaults = _RunFormat()
        self.default_paragraph_style = None
        self._styles = {}  # styleId -> (basedOn, rPr)
        self._resolved = {}
        if pkg.has("word/styles.xml"):
            styles = pkg.xml("word/styles.xml")
            self.defaults = _RunFormat.of(styles.find(f"{_w('docDefaults')}/{_w('rPrDefault')}/{_w('rPr')}"))
            for style in styles.iter(_w("style")):
                style_id = style.get(_w("styleId"))
                self._styles[style_id] = (_wval(style, "basedOn"), style.find(_w("rPr")))
                if style.get(_w("type")) == "paragraph" and style.get(_w("default")) in ("1", "true"):
                    self.default_paragraph_style = style_id

    def style(self, style_id, depth: int = 0) -> _RunFormat:
        if style_id not in self._styles or depth > 20:
            return _RunFormat()
        if style_id not in self._resolved:
            based_on, rpr = self._styles[style_id]
            self._resolved[style_id] = _RunFormat.of(rpr).over(self.style(based_on, depth + 1))
        return self._resolved[style_id]

    def part(self, root, container=None) -> list:
        """Reads one part (body, header or footer). White text is only checked in parts with no
        images, filled shapes or page colour, because it may sit on one of those."""
        self.white_check = not _has_coloured_background(root)
        out = []
        self.blocks(root if container is None else container, out, shaded=False)
        return out

    def _is_hidden(self, fmt: _RunFormat, shaded: bool) -> bool:
        if fmt.vanish:
            return True
        if fmt.size is not None and fmt.size / 2 < _TINY_TEXT_PT:
            return True
        if self.white_check and not shaded and not fmt.background:
            rgb = _hex_colour(fmt.color)
            return rgb is not None and _near_white(*rgb)
        return False

    def inline(self, el, parts: list, hidden_parts: list, boxes: list, para_fmt: _RunFormat, shaded: bool) -> None:
        """Collects the text of a paragraph. Text boxes found inside it are set aside."""
        for child in el:
            tag = child.tag
            if tag in _SKIP:
                continue
            if tag == _w("r"):
                rpr = child.find(_w("rPr"))
                fmt = _RunFormat.of(rpr).over(self.style(_wval(rpr, "rStyle")).over(para_fmt))
                target = hidden_parts if self._is_hidden(fmt, shaded) else parts
                self.inline(child, target, hidden_parts, boxes, para_fmt, shaded)
            elif tag == _w("t"):
                parts.append(child.text or "")
            elif tag in _TAB:
                parts.append("\t")
            elif tag in _BREAK:
                parts.append("\n")
            elif tag == _w("noBreakHyphen"):
                parts.append("-")
            elif tag == _w("txbxContent"):
                boxes.append(child)
            elif tag == f"{{{_MC}}}AlternateContent":
                branch = _chosen_branch(child)
                if branch is not None:
                    self.inline(branch, parts, hidden_parts, boxes, para_fmt, shaded)
            else:
                self.inline(child, parts, hidden_parts, boxes, para_fmt, shaded)

    def paragraph(self, p, out: list, shaded: bool) -> None:
        ppr = p.find(_w("pPr"))
        para_fmt = self.style(_wval(ppr, "pStyle") or self.default_paragraph_style).over(self.defaults)
        shaded = shaded or _shaded(ppr)

        parts, hidden_parts, boxes = [], [], []
        self.inline(p, parts, hidden_parts, boxes, para_fmt, shaded)
        line = "".join(parts).strip()
        if line:
            out.append(line)
        hidden = "".join(hidden_parts).strip()
        if hidden:
            self.hidden.append(hidden)
        # A text box is anchored to a paragraph; its text is read right after the host paragraph.
        # Text boxes usually have a fill, so white text inside one counts as visible.
        for box in boxes:
            self.blocks(box, out, shaded=True)

    def table(self, tbl, out: list, shaded: bool) -> None:
        for row in _children(tbl, _w("tr")):
            cells = []
            for cell in _children(row, _w("tc")):
                lines = []
                self.blocks(cell, lines, shaded or _shaded(cell.find(_w("tcPr"))))
                if lines:
                    cells.append(lines)
            if not cells:
                continue
            if all(len(lines) == 1 and "\n" not in lines[0] for lines in cells):
                out.append(" | ".join(lines[0] for lines in cells))  # a data row: keep it on one line
            else:
                for lines in cells:  # a layout row (e.g. a sidebar column): read each cell in turn
                    out.extend(lines)

    def blocks(self, el, out: list, shaded: bool) -> None:
        """Reads block-level content (paragraphs, tables, content controls) in document order."""
        for child in el:
            tag = child.tag
            if tag == _w("p"):
                self.paragraph(child, out, shaded)
            elif tag == _w("tbl"):
                self.table(child, out, shaded)
            elif tag == f"{{{_MC}}}AlternateContent":
                branch = _chosen_branch(child)
                if branch is not None:
                    self.blocks(branch, out, shaded)
            elif tag in _WRAPPERS:
                self.blocks(child, out, shaded)


def _header_footer_parts(pkg: _DocxPackage, document) -> tuple:
    """Header and footer part names, in the order the sections reference them."""
    targets = {}
    rels_name = "word/_rels/document.xml.rels"
    if pkg.has(rels_name):
        for rel in pkg.xml(rels_name).iter(f"{{{_REL}}}Relationship"):
            target = rel.get("Target", "")
            if rel.get("TargetMode") != "External" and not target.startswith("/"):
                targets[rel.get("Id")] = "word/" + target
    headers, footers = [], []
    for kind, names in (("headerReference", headers), ("footerReference", footers)):
        for ref in document.iter(_w(kind)):
            name = targets.get(ref.get(f"{{{_R}}}id"))
            if name and name not in names and pkg.has(name):
                names.append(name)
    return headers, footers


def _read_parts(reader: _DocxReader, pkg: _DocxPackage, names: list) -> list:
    """Reads headers or footers. The default, first-page and even-page variants usually repeat
    the same contact line, so a line already read from an earlier variant is not added again."""
    lines = []
    for name in names:
        lines.extend(line for line in reader.part(pkg.xml(name)) if line not in lines)
    return lines


def parse_docx(file_bytes: bytes) -> Extraction:
    """Extracts the visible text of a DOCX file: headers, then the body (paragraphs, tables,
    text boxes and content controls in document order), then footers. Each text appears once;
    hidden text is set aside."""
    try:
        pkg = _DocxPackage(file_bytes)
        document = pkg.xml("word/document.xml")
        body = document.find(_w("body"))
        if body is None:
            raise DocumentError("This DOCX file could not be opened. It may be corrupt.")
        reader = _DocxReader(pkg)
        headers, footers = _header_footer_parts(pkg, document)
        header_lines = _read_parts(reader, pkg, headers)
        body_lines = reader.part(document, container=body)
        lines = header_lines + body_lines + _read_parts(reader, pkg, footers)
    except DocumentError:
        raise
    except Exception as e:
        logger.info("docx could not be opened", extra={"error": type(e).__name__})
        raise DocumentError("This DOCX file could not be opened. It may be corrupt.") from None

    return Extraction("\n".join(lines).strip(), list(dict.fromkeys(reader.hidden)))


def extract_document(file_bytes: bytes, file_format: str) -> Extraction:
    """Extracts visible text in memory, with any hidden text set aside.
    The text is '' for images and scanned PDFs (OCR is the caller's job)."""
    if file_format == "pdf":
        return parse_pdf(file_bytes)
    if file_format == "docx":
        return parse_docx(file_bytes)
    if file_format == "txt":
        return Extraction(file_bytes.decode("utf-8", errors="replace").strip(), [])
    if file_format in IMAGE_MIME_TYPES:
        return Extraction("", [])
    raise DocumentError(f"Unsupported file type. {SUPPORTED_HINT}")


def extract_text(file_bytes: bytes, file_format: str) -> str:
    return extract_document(file_bytes, file_format).text
