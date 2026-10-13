import io
import os

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


def make_pdf(text: str = "") -> bytes:
    """Builds a minimal one-page PDF. With no text it behaves like a scan (no text layer)."""
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
