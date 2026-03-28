import os
import base64
import json
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Literal
from google import genai
from google.genai import types
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import uuid

app = FastAPI(title="Universal Intent Bridge - AI Logic Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Firebase Init (optional, graceful fallback) ────────────────────────────────
db = None
try:
    if os.path.exists("serviceAccountKey.json"):
        cred = credentials.Certificate("serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
        db = firestore.client()
except Exception:
    pass

# ── Gemini Client ──────────────────────────────────────────────────────────────
gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))

# ── Pydantic Schemas (the "Guardian" layer) ────────────────────────────────────

class ActionStep(BaseModel):
    step_number: int = Field(..., ge=1)
    who: str = Field(..., min_length=1, description="Actor responsible for this step")
    what: str = Field(..., min_length=5, description="Concrete action to take")
    when: str = Field(..., description="Deadline or timing (e.g. 'Immediately', 'Within 2 hours')")
    via: str = Field(..., description="System or channel to use")
    priority: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


class Gap(BaseModel):
    field: str
    reason: str


class VerificationResult(BaseModel):
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    verified: bool
    gaps: List[Gap] = []
    contradictions: List[str] = []
    warnings: List[str] = []


class BridgedOutput(BaseModel):
    session_id: str
    domain: Literal["MEDICAL", "DISASTER", "TRAFFIC", "MENTAL_HEALTH", "LEGAL", "INFRASTRUCTURE", "GENERAL"]
    intent_summary: str = Field(..., min_length=10)
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    actions: List[ActionStep] = Field(..., min_items=1)
    verification: VerificationResult
    raw_extracted_facts: dict
    timestamp: str


# ── System Prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the Universal Intent Bridge — a life-saving AI that converts messy, unstructured real-world inputs into structured, verified, actionable plans.

You MUST return ONLY valid JSON matching this exact schema. No prose, no markdown, just raw JSON.

Schema:
{
  "session_id": "<uuid>",
  "domain": "MEDICAL|DISASTER|TRAFFIC|MENTAL_HEALTH|LEGAL|INFRASTRUCTURE|GENERAL",
  "intent_summary": "<one sentence describing the core situation>",
  "severity": "CRITICAL|HIGH|MEDIUM|LOW",
  "actions": [
    {
      "step_number": 1,
      "who": "<actor>",
      "what": "<specific concrete action>",
      "when": "<timing>",
      "via": "<system/channel>",
      "priority": "CRITICAL|HIGH|MEDIUM|LOW"
    }
  ],
  "verification": {
    "confidence_score": 0.0-1.0,
    "verified": true|false,
    "gaps": [{"field": "<name>", "reason": "<why missing>"}],
    "contradictions": ["<description of contradiction>"],
    "warnings": ["<safety warning>"]
  },
  "raw_extracted_facts": {
    "<key>": "<value>"
  },
  "timestamp": "<ISO 8601>"
}

Rules:
1. Always extract maximum information from messy input — spelling errors, abbreviations, fragments are OK
2. Mark confidence_score below 0.7 if input is ambiguous
3. For MEDICAL/MENTAL_HEALTH domains — always include emergency service contact as first action if severity is CRITICAL
4. For DISASTER — always include evacuation priority in actions
5. For LEGAL — always include deadline dates if mentioned
6. verified=false means at least one CRITICAL gap exists
7. Minimum 3 action steps. Maximum 10.
"""


# ── Endpoint: Process Intent ───────────────────────────────────────────────────

@app.post("/api/bridge", response_model=BridgedOutput)
async def bridge_intent(
    text_input: Optional[str] = Form(None),
    audio_file: Optional[UploadFile] = File(None),
    image_file: Optional[UploadFile] = File(None),
    user_id: Optional[str] = Form(None),
):
    if not text_input and not audio_file and not image_file:
        raise HTTPException(status_code=400, detail="At least one input (text, audio, or image) is required.")

    parts = []
    parts.append(types.Part.from_text(text=SYSTEM_PROMPT))

    if text_input:
        parts.append(types.Part.from_text(text=f"USER INPUT:\n{text_input}"))

    if image_file:
        image_bytes = await image_file.read()
        mime = image_file.content_type or "image/jpeg"
        parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime))
        parts.append(types.Part.from_text(text="[Image provided above — extract all visible text, symbols, labels, and contextual cues from it]"))

    if audio_file:
        audio_bytes = await audio_file.read()
        mime = audio_file.content_type or "audio/webm"
        parts.append(types.Part.from_bytes(data=audio_bytes, mime_type=mime))
        parts.append(types.Part.from_text(text="[Audio provided above — transcribe it fully and treat the transcription as the primary input]"))

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=4096,
                response_mime_type="application/json",
            ),
        )
        raw_json = response.text.strip()
        data = json.loads(raw_json)
        data["session_id"] = str(uuid.uuid4())
        data["timestamp"] = datetime.utcnow().isoformat() + "Z"

        result = BridgedOutput(**data)

        if db and user_id:
            doc_ref = db.collection("bridge_sessions").document(result.session_id)
            doc_ref.set(result.dict())

        return result

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"Gemini returned non-JSON response: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bridge processing failed: {str(e)}")


# ── Endpoint: Fetch Session History ───────────────────────────────────────────

@app.get("/api/history/{user_id}")
async def get_history(user_id: str):
    if not db:
        return {"sessions": [], "note": "Firebase not configured"}
    try:
        sessions = db.collection("bridge_sessions") \
            .where("user_id", "==", user_id) \
            .order_by("timestamp", direction=firestore.Query.DESCENDING) \
            .limit(20) \
            .stream()
        return {"sessions": [s.to_dict() for s in sessions]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health():
    return {"status": "ok", "gemini": bool(os.environ.get("GEMINI_API_KEY")), "firebase": db is not None}


@app.get("/")
async def root():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))

app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
