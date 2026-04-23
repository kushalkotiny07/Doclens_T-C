# T&C Summary App

A simple MVP that accepts:
- PDF files
- Pasted legal text

It extracts text, summarizes Terms & Conditions / Privacy Policies in plain English, highlights likely risk areas, and shows a simple risk score.

## Features
- PDF text extraction with `pdfplumber`
- Image OCR with `pytesseract`
- Gemini-based legal summary when `GEMINI_API_KEY` is present
- Fallback keyword-based analyzer when no API key is configured
- Plain-English output with:
  - Overview
  - Key summary points
  - Clause categories
  - Red flags
  - User impact
  - Recommended action

## Run locally

```bash
cd tc_summary_app
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
export GEMINI_API_KEY=your_key_here   # Windows PowerShell: $env:GEMINI_API_KEY="your_key_here"
uvicorn main:app --reload
```

Then open:

```bash
http://127.0.0.1:8000
```

## Notes
- Scanned PDFs without embedded text may need OCR support page-by-page; this MVP currently extracts embedded PDF text directly and uses OCR for image uploads.
- To extend this into the larger project scope, you can add URL scanning, stored history, auth, PostgreSQL, and OWASP ZAP.
