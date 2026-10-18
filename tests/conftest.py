import io
import os
import zipfile

# Settings are read at import time, so set test values before importing the app.
os.environ["GEMINI_API_KEY"] = "test-key"
os.environ["DEMO_ACCESS_CODE"] = ""
os.environ["RATE_LIMIT_PER_MINUTE"] = "100"
os.environ["RATE_LIMIT_PER_DAY"] = "1000"
os.environ["DAILY_RESUME_BUDGET"] = "10000"

import pytest  # noqa: E402
from docx import Document  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from google.genai import types  # noqa: E402

from app.main import app  # noqa: E402
from app.services import ai_client, matcher  # noqa: E402
from app.services.limits import limiter  # noqa: E402

JD = "Backend engineer with Python, FastAPI and PostgreSQL experience. 3+ years building REST APIs."
RESUME_TEXT = "Jane Doe. Backend developer, 4 years of Python and FastAPI. Built REST APIs on PostgreSQL."


class FakeModels:
    """Stands in for client.aio.models. Behaviour is set per test."""

    def __init__(self):
        self.embed_calls = 0
        self.generate_calls = []
        self.embed_behaviour = lambda text: [0.1, 0.2, 0.3]
        self.generate_behaviour = lambda model, contents, config: _analysis_response()

    async def embed_content(self, model, contents, config=None):
        self.embed_calls += 1
        values = self.embed_behaviour(contents)
        return types.EmbedContentResponse(embeddings=[types.ContentEmbedding(values=values)])

    async def generate_content(self, model, contents, config=None):
        self.generate_calls.append((model, contents, config))
        return self.generate_behaviour(model, contents, config)


class FakeClient:
    def __init__(self):
        self.models = FakeModels()
        self.aio = self


def text_response(text: str, finish_reason=types.FinishReason.STOP) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=text)]),
                finish_reason=finish_reason,
            )
        ]
    )


def _analysis_response() -> types.GenerateContentResponse:
    return text_response(
        '{"summary": "Python backend developer.", "strengths": ["FastAPI"], "gaps": [],'
        ' "recommendations": ["Verify PostgreSQL depth"], "match_explanation": "Relevant stack."}'
    )


@pytest.fixture
def fake_ai(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(ai_client, "_client", fake)
    matcher._embedding_cache.clear()
    return fake.models


@pytest.fixture
def client(fake_ai):
    limiter.reset()
    with TestClient(app) as c:
        yield c
    limiter.reset()


def make_docx(text: str) -> bytes:
    doc = Document()
    for line in text.split(". "):
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


_DOCX_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:v="urn:schemas-microsoft-com:vml"'
)


def make_raw_docx(body: str, headers: dict = None, footers: dict = None, sect: str = None, styles: str = None) -> bytes:
    """Builds a DOCX from raw WordprocessingML, for markup python-docx cannot write (text boxes,
    content controls, tracked changes). headers/footers map a part name to its inner XML; each is
    referenced from the section properties in the order given unless `sect` overrides them."""
    headers, footers = headers or {}, footers or {}
    rels, refs = [], []
    for i, (kind, parts) in enumerate((("header", headers), ("footer", footers))):
        for j, name in enumerate(parts):
            rid = f"rId{i * 100 + j + 1}"
            rel_type = f"http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}"
            rels.append(f'<Relationship Id="{rid}" Type="{rel_type}" Target="{name}"/>')
            refs.append(f'<w:{kind}Reference w:type="default" r:id="{rid}"/>')
    sect = sect if sect is not None else f"<w:sectPr>{''.join(refs)}</w:sectPr>"
    files = {
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/></Types>',
        "word/document.xml": f'<?xml version="1.0"?><w:document {_DOCX_NS}><w:body>{body}{sect}</w:body></w:document>',
        "word/_rels/document.xml.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rels)
        + "</Relationships>",
    }
    if styles is not None:
        files["word/styles.xml"] = f'<?xml version="1.0"?><w:styles {_DOCX_NS}>{styles}</w:styles>'
    for name, xml in headers.items():
        files[f"word/{name}"] = f'<?xml version="1.0"?><w:hdr {_DOCX_NS}>{xml}</w:hdr>'
    for name, xml in footers.items():
        files[f"word/{name}"] = f'<?xml version="1.0"?><w:ftr {_DOCX_NS}>{xml}</w:ftr>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def p(text: str, rpr: str = "", ppr: str = "") -> str:
    """One WordprocessingML paragraph with a single run, optionally with run/paragraph properties."""
    ppr = f"<w:pPr>{ppr}</w:pPr>" if ppr else ""
    rpr = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
    return f"<w:p>{ppr}<w:r>{rpr}<w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def text_box(*paragraphs: str) -> str:
    """A paragraph anchoring a text box, written the way Word writes it: a modern drawing plus a
    VML fallback that repeats the same text."""
    inner = "".join(paragraphs)
    return (
        "<w:p><w:r><mc:AlternateContent>"
        f"<mc:Choice Requires=\"wps\"><w:drawing><wp:anchor><a:graphic><a:graphicData><wps:wsp><wps:txbx><w:txbxContent>{inner}"
        "</w:txbxContent></wps:txbx></wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice>"
        f"<mc:Fallback><w:pict><v:shape><v:textbox><w:txbxContent>{inner}</w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback>"
        "</mc:AlternateContent></w:r></w:p>"
    )


def make_pdf(text: str = "", content: bytes = None) -> bytes:
    """Builds a minimal one-page PDF. With no text it behaves like a scan (no text layer).
    `content` replaces the page's content stream, for tests that need colours or render modes."""
    if content is None:
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)
