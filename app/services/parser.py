import io
import pdfplumber
import pypdfium2 as pdfium
from docx import Document

def parse_pdf(file_bytes: bytes) -> str:
    """
    Extracts text from a PDF file in-memory.
    First attempts pdfplumber for layout structure; if empty or errors,
    falls back to pypdfium2 (C++ PDFium engine) which handles complex fonts & layouts.
    """
    text = ""
    # 1. Primary: Try pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception:
        pass

    # 2. Secondary fallback: pypdfium2
    if not text.strip():
        try:
            pdf = pdfium.PdfDocument(file_bytes)
            extracted = []
            for page in pdf:
                textpage = page.get_textpage()
                page_text = textpage.get_text_range()
                if page_text:
                    extracted.append(page_text)
            text = "\n".join(extracted)
        except Exception:
            pass

    return text.strip()

def parse_docx(file_bytes: bytes) -> str:
    """
    Extracts text from a DOCX (Word) file in-memory using python-docx.
    Does not write any files to local disk.
    """
    try:
        doc = Document(io.BytesIO(file_bytes))
        text_content = []
        
        # Extract text from paragraphs
        for paragraph in doc.paragraphs:
            if paragraph.text.strip():
                text_content.append(paragraph.text)
                
        # Extract text from tables (often used in resumes for layout)
        for table in doc.tables:
            for row in table.rows:
                row_text = []
                for cell in row.cells:
                    cell_text = cell.text.strip()
                    if cell_text and cell_text not in row_text:
                        row_text.append(cell_text)
                if row_text:
                    text_content.append(" | ".join(row_text))
                    
        return "\n".join(text_content).strip()
    except Exception as e:
        return ""

def extract_text(file_bytes: bytes, filename: str) -> str:
    """
    Detects file type by filename extension and extracts raw text in-memory.
    """
    ext = filename.lower().split('.')[-1]
    if ext == 'pdf':
        return parse_pdf(file_bytes)
    elif ext in ['docx', 'doc']:
        return parse_docx(file_bytes)
    elif ext == 'txt':
        return file_bytes.decode('utf-8', errors='ignore').strip()
    elif ext in ['png', 'jpg', 'jpeg', 'webp']:
        # Return empty string to trigger OCR fallback in the router
        return ""
    else:
        raise ValueError(f"Unsupported file format: .{ext}. Only PDF, DOCX, TXT, and images (PNG, JPG, JPEG, WEBP) are allowed.")

