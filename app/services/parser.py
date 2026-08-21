import io
import gc
from docx import Document

def parse_pdf(file_bytes: bytes) -> str:
    """
    Extracts text from a PDF file in-memory.
    Uses pypdfium2 (C++ PDFium engine) as primary fast parser (<5ms, negligible RAM).
    Falls back to pdfplumber only if needed.
    """
    text = ""
    # 1. Primary Fast C++ Engine: pypdfium2 (low memory, blazing fast)
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(file_bytes)
        extracted = []
        for page in pdf:
            textpage = page.get_textpage()
            page_text = textpage.get_text_range()
            if page_text:
                extracted.append(page_text)
            textpage.close()
            page.close()
        pdf.close()
        text = "\n".join(extracted).strip()
    except Exception:
        pass

    # 2. Secondary fallback: pdfplumber (if pypdfium2 returns empty)
    if not text:
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                pages_text = []
                for page in pdf.pages:
                    pt = page.extract_text()
                    if pt:
                        pages_text.append(pt)
                text = "\n".join(pages_text).strip()
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
            clean_p = paragraph.text.strip()
            if clean_p:
                text_content.append(clean_p)
                
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
    except Exception:
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


