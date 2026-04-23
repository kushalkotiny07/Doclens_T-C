import io
import os
import re
import json
import base64
from pathlib import Path
from typing import Dict, List, Tuple

import pdfplumber
import pytesseract
import requests
from PIL import Image
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="T&C Summary App")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

MAX_CHARS_FOR_MODEL = 24000
ALLOWED_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
}

RISK_PATTERNS: Dict[str, List[Tuple[str, str]]] = {
    "Data Collection": [
        (r"collect(?:ion|s|ed)?\s+(?:your\s+)?(?:personal|usage|location|financial)?\s*data", "Collects personal or usage data."),
        (r"track(?:ing)?\s+(?:your\s+)?(?:activity|usage|location)", "Tracks activity or location."),
        (r"biometric|face scan|voice print", "Mentions biometric data."),
    ],
    "Data Sharing": [
        (r"share(?:s|d)?\s+(?:your\s+)?data\s+with\s+third\s+part(?:y|ies)", "Shares data with third parties."),
        (r"sell(?:ing|s)?\s+(?:your\s+)?data", "May sell data."),
        (r"affiliate|partner|advertiser", "Mentions affiliates, partners, or advertisers."),
    ],
    "Payments & Renewal": [
        (r"auto(?:-|\s)?renew|automatic(?:ally)?\s+renew", "Auto-renewal is mentioned."),
        (r"subscription fee|billing cycle|recurring charge", "Recurring billing terms found."),
        (r"non-refundable|no refund", "Refund restrictions are present."),
    ],
    "Liability": [
        (r"limit(?:ation)?\s+of\s+liability", "Liability is limited."),
        (r"as is|without warranty|no warranty", "Service may be provided without warranty."),
        (r"indemnif(?:y|ication)", "User indemnity obligation found."),
    ],
    "Termination": [
        (r"terminate(?:d|s)?\s+(?:your\s+)?account", "Company can terminate the account."),
        (r"suspend(?:ed|sion)?\s+(?:your\s+)?access", "Access suspension is allowed."),
        (r"without notice", "Action without notice is permitted."),
    ],
    "Dispute Resolution": [
        (r"arbitration", "Arbitration clause found."),
        (r"class action waiver", "Class action waiver found."),
        (r"governed by the laws of|jurisdiction", "Jurisdiction or governing law is specified."),
    ],
}


def extract_text_from_pdf(file_bytes: bytes) -> str:
    parts: List[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text)
    return "\n\n".join(parts).strip()


def extract_text_from_image(file_bytes: bytes) -> str:
    image = Image.open(io.BytesIO(file_bytes))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    return pytesseract.image_to_string(image).strip()


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> List[str]:
    text = normalize_whitespace(text)
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if s.strip()]


def classify_clauses(text: str) -> Dict[str, List[str]]:
    findings: Dict[str, List[str]] = {}
    normalized = text.lower()
    for category, patterns in RISK_PATTERNS.items():
        hits = []
        for pattern, message in patterns:
            if re.search(pattern, normalized, flags=re.IGNORECASE):
                hits.append(message)
        if hits:
            findings[category] = sorted(set(hits))
    return findings


def calculate_risk(findings: Dict[str, List[str]]) -> Tuple[str, int, List[str]]:
    score = 0
    reasons = []
    weights = {
        "Data Sharing": 25,
        "Payments & Renewal": 20,
        "Liability": 20,
        "Termination": 15,
        "Dispute Resolution": 10,
        "Data Collection": 10,
    }
    for category, items in findings.items():
        score += weights.get(category, 5)
        reasons.extend(items[:2])
    score = min(score, 100)
    if score >= 60:
        label = "High"
    elif score >= 30:
        label = "Medium"
    else:
        label = "Low"
    return label, score, reasons[:6]


def fallback_summary(text: str) -> Dict[str, object]:
    sentences = split_sentences(text)
    findings = classify_clauses(text)
    risk_label, risk_score, reasons = calculate_risk(findings)

    top_sentences = []
    strong_keywords = [
        "collect", "share", "third party", "auto-renew", "subscription", "liability",
        "terminate", "arbitration", "refund", "billing", "privacy", "data"
    ]
    for s in sentences:
        if any(k in s.lower() for k in strong_keywords):
            top_sentences.append(s)
        if len(top_sentences) >= 5:
            break
    if not top_sentences:
        top_sentences = sentences[:5]

    user_impact = []
    if "Data Sharing" in findings:
        user_impact.append("Your information may be shared with outside parties.")
    if "Payments & Renewal" in findings:
        user_impact.append("You may be charged automatically unless you cancel in time.")
    if "Liability" in findings:
        user_impact.append("Your legal protection may be limited if something goes wrong.")
    if "Termination" in findings:
        user_impact.append("The service can suspend or close your account under certain conditions.")
    if "Dispute Resolution" in findings:
        user_impact.append("You may have limited options for court-based disputes.")
    if not user_impact:
        user_impact.append("No major red flags were detected by the fallback analyzer, but manual review is still recommended.")

    return {
        "overview": "This document appears to explain how the service uses data, applies payment rules, limits responsibility, and controls account access.",
        "summary_points": top_sentences,
        "clause_categories": findings,
        "red_flags": reasons or ["No obvious high-risk phrases were detected by keyword analysis."],
        "user_impact": user_impact,
        "recommended_action": "Review billing, privacy, liability, and termination sections before accepting.",
        "risk_label": risk_label,
        "risk_score": risk_score,
        "source": "fallback",
    }


def call_gemini_summary(text: str) -> Dict[str, object]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return fallback_summary(text)

    trimmed = text[:MAX_CHARS_FOR_MODEL]
    prompt = f"""
You are a T&C and privacy policy analyzer.
Read the extracted text and return ONLY valid JSON with this exact schema:
{{
  "overview": "...",
  "summary_points": ["...", "..."],
  "clause_categories": {{
    "Data Collection": ["..."],
    "Data Sharing": ["..."],
    "Payments & Renewal": ["..."],
    "Liability": ["..."],
    "Termination": ["..."],
    "Dispute Resolution": ["..."]
  }},
  "red_flags": ["..."],
  "user_impact": ["..."],
  "recommended_action": "...",
  "risk_label": "Low or Medium or High",
  "risk_score": 0
}}

Rules:
- Use plain English.
- Keep the overview under 90 words.
- Give 4 to 6 summary points.
- Give concise clause bullets.
- Identify hidden risks like data sharing, auto-renewal, no refund, arbitration, broad termination rights, and liability limits.
- Risk score must be 0 to 100.
- Do not add markdown fences.

Extracted text:
{trimmed}
""".strip()

    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-flash-latest:generateContent"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    resp = requests.post(
        f"{endpoint}?key={api_key}",
        json=payload,
        timeout=45,
    )
    resp.raise_for_status()
    data = resp.json()

    try:
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(raw)
        parsed["source"] = "gemini"
        return parsed
    except Exception:
        return fallback_summary(text)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "result": None,
            "error": None,
            "raw_text": "",
        },
    )


@app.post("/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,
    file: UploadFile = File(None),
    pasted_text: str = Form(""),
):
    raw_text = ""
    filename = ""

    try:
        if file and file.filename:
            filename = file.filename
            if file.content_type not in ALLOWED_TYPES:
                raise HTTPException(status_code=400, detail="Upload a PDF, PNG, JPG, JPEG, or WEBP file.")
            file_bytes = await file.read()
            if file.content_type == "application/pdf":
                raw_text = extract_text_from_pdf(file_bytes)
            else:
                raw_text = extract_text_from_image(file_bytes)
        elif pasted_text.strip():
            raw_text = pasted_text.strip()
            filename = "Pasted text"
        else:
            raise HTTPException(status_code=400, detail="Upload a file or paste T&C text.")

        if not raw_text.strip():
            raise HTTPException(status_code=400, detail="No readable text was found in the file.")

        result = call_gemini_summary(raw_text)
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "result": result,
                "error": None,
                "raw_text": raw_text[:8000],
                "filename": filename,
            },
        )
    except HTTPException as exc:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "result": None,
                "error": exc.detail,
                "raw_text": raw_text[:8000],
            },
            status_code=exc.status_code,
        )
    except Exception as exc:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "result": None,
                "error": f"Unexpected error: {exc}",
                "raw_text": raw_text[:8000],
            },
            status_code=500,
        )
