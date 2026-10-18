import io
import logging
import re
import zipfile

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


def parse_pdf(file_bytes: bytes) -> str:
    """Extracts the text layer of a PDF.

    Returns '' for a readable PDF with no text layer (a scan), so the caller can try OCR.
    Raises DocumentError for corrupt or password-protected files, which OCR cannot fix.
    """
    errors = []

    # 1. Primary fast C++ engine: pypdfium2
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(file_bytes)
        try:
            extracted = []
            for page in pdf:
                textpage = page.get_textpage()
                page_text = textpage.get_text_range()
                if page_text:
                    extracted.append(page_text)
                textpage.close()
                page.close()
        finally:
            pdf.close()
        text = "\n".join(extracted).strip()
        if text:
            return text
    except Exception as e:
        errors.append(e)

    # 2. Secondary: pdfplumber
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages_text = [pt for pt in (page.extract_text() for page in pdf.pages) if pt]
        return "\n".join(pages_text).strip()
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

# Uncompressed size caps protect against zip bombs. A 5 MB upload never legitimately needs more.
MAX_DOCX_PART_BYTES = 50 * 1024 * 1024
MAX_DOCX_TOTAL_BYTES = 100 * 1024 * 1024

# No DTDs, no entity expansion, no network: defends against XXE and entity-expansion attacks.
_XML_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)

# Elements whose content is not visible text: properties, tracked deletions, moved-from text,
# field codes (e.g. HYPERLINK "..."). The visible result of a field is kept.
_SKIP = {f"{{{_W}}}{t}" for t in ("pPr", "rPr", "tblPr", "trPr", "tcPr", "sectPr", "del", "moveFrom", "delText", "instrText")}
_TAB = {f"{{{_W}}}tab", f"{{{_W}}}ptab"}
_BREAK = {f"{{{_W}}}br", f"{{{_W}}}cr"}


def _w(tag: str) -> str:
    return f"{{{_W}}}{tag}"


def _chosen_branch(alternate):
    """mc:AlternateContent holds the same object twice (modern drawing and a VML fallback).
    Reading both would duplicate text-box text, so only the first branch is used."""
    for branch in alternate:
        if branch.tag in (f"{{{_MC}}}Choice", f"{{{_MC}}}Fallback"):
            return branch
    return None


def _inline(el, parts: list, boxes: list) -> None:
    """Collects the visible text of a paragraph. Text boxes found inside it are set aside."""
    for child in el:
        tag = child.tag
        if tag in _SKIP:
            continue
        if tag == _w("t"):
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
                _inline(branch, parts, boxes)
        else:
            _inline(child, parts, boxes)


def _paragraph(p, out: list) -> None:
    parts, boxes = [], []
    _inline(p, parts, boxes)
    line = "".join(parts).strip()
    if line:
        out.append(line)
    # A text box is anchored to a paragraph; its text is read right after the host paragraph.
    for box in boxes:
        _blocks(box, out)


def _children(el, tag: str):
    """Direct children with this tag, including ones wrapped in content controls (w:sdt)."""
    for child in el:
        if child.tag == tag:
            yield child
        elif child.tag in (_w("sdt"), _w("sdtContent"), _w("customXml")):
            yield from _children(child, tag)


def _table(tbl, out: list) -> None:
    for row in _children(tbl, _w("tr")):
        cells = []
        for cell in _children(row, _w("tc")):
            lines = []
            _blocks(cell, lines)
            if lines:
                cells.append(lines)
        if not cells:
            continue
        if all(len(lines) == 1 and "\n" not in lines[0] for lines in cells):
            out.append(" | ".join(lines[0] for lines in cells))  # a data row: keep it on one line
        else:
            for lines in cells:  # a layout row (e.g. a sidebar column): read each cell in turn
                out.extend(lines)


def _blocks(el, out: list) -> None:
    """Reads block-level content (paragraphs, tables, content controls) in document order."""
    for child in el:
        tag = child.tag
        if tag == _w("p"):
            _paragraph(child, out)
        elif tag == _w("tbl"):
            _table(child, out)
        elif tag == f"{{{_MC}}}AlternateContent":
            branch = _chosen_branch(child)
            if branch is not None:
                _blocks(branch, out)
        elif tag in _SKIP:
            continue
        elif tag in (_w("sdt"), _w("sdtContent"), _w("customXml"), _w("ins"), _w("moveTo"), _w("smartTag")):
            _blocks(child, out)


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


def _read_parts(pkg: _DocxPackage, names: list) -> list:
    """Reads headers or footers. The default, first-page and even-page variants usually repeat
    the same contact line, so a line already read from an earlier variant is not added again."""
    lines = []
    for name in names:
        part_lines = []
        _blocks(pkg.xml(name), part_lines)
        lines.extend(line for line in part_lines if line not in lines)
    return lines


def parse_docx(file_bytes: bytes) -> str:
    """Extracts the visible text of a DOCX file: headers, then the body (paragraphs, tables,
    text boxes and content controls in document order), then footers. Each text appears once."""
    try:
        pkg = _DocxPackage(file_bytes)
        document = pkg.xml("word/document.xml")
        body = document.find(_w("body"))
        if body is None:
            raise DocumentError("This DOCX file could not be opened. It may be corrupt.")
        headers, footers = _header_footer_parts(pkg, document)
        body_lines = []
        _blocks(body, body_lines)
        lines = _read_parts(pkg, headers) + body_lines + _read_parts(pkg, footers)
    except DocumentError:
        raise
    except Exception as e:
        logger.info("docx could not be opened", extra={"error": type(e).__name__})
        raise DocumentError("This DOCX file could not be opened. It may be corrupt.") from None

    return "\n".join(lines).strip()


def extract_text(file_bytes: bytes, file_format: str) -> str:
    """Extracts raw text in memory. Returns '' for images and scanned PDFs (OCR is the caller's job)."""
    if file_format == "pdf":
        return parse_pdf(file_bytes)
    if file_format == "docx":
        return parse_docx(file_bytes)
    if file_format == "txt":
        return file_bytes.decode("utf-8", errors="replace").strip()
    if file_format in IMAGE_MIME_TYPES:
        return ""
    raise DocumentError(f"Unsupported file type. {SUPPORTED_HINT}")
