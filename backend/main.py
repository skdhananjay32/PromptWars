import os
import base64
import json
import logging
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional, List, Literal, Dict, Any
from google import genai
from google.genai import types
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import uuid

# ── Google Cloud Logging ────────────────────────────────────────────────
try:
    import google.cloud.logging
    log_client = google.cloud.logging.Client()
    log_client.setup_logging()
except Exception:
    logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("universal-intent-bridge")

app = FastAPI(title="Universal Intent Bridge - AI Logic Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://localhost:3000", "https://bridge-app-119835048295.us-central1.run.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Firebase Init (optional, graceful fallback) ────────────────────────────────
# Uses serviceAccountKey.json locally; Application Default Credentials on Cloud Run
db = None
FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "")
try:
    if not firebase_admin._apps:
        if os.path.exists("serviceAccountKey.json"):
            cred = credentials.Certificate("serviceAccountKey.json")
            firebase_admin.initialize_app(cred)
        elif FIREBASE_PROJECT_ID:
            firebase_admin.initialize_app(options={"projectId": FIREBASE_PROJECT_ID})
    db = firestore.client()
except Exception as e:
    logger.warning(f"Firebase init skipped: {e}")

# ── Secret Manager: load GEMINI_API_KEY if running on GCP ────────────────────────
def _load_secret(project_id: str, secret_id: str) -> str:
    """Fetch latest secret version from Google Cloud Secret Manager."""
    try:
        from google.cloud import secretmanager
        sm_client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response = sm_client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8")
    except Exception as e:
        logger.warning(f"Secret Manager unavailable, falling back to env var: {e}")
        return ""

_project_id = os.environ.get("FIREBASE_PROJECT_ID", "")
_gemini_key = (
    _load_secret(_project_id, "GEMINI_API_KEY")
    if _project_id
    else os.environ.get("GEMINI_API_KEY", "")
) or os.environ.get("GEMINI_API_KEY", "")

_maps_key = (
    _load_secret(_project_id, "MAPS_API_KEY")
    if _project_id
    else os.environ.get("MAPS_API_KEY", "")
) or os.environ.get("MAPS_API_KEY", "")

# ── Gemini Client ──────────────────────────────────────────────
gemini_client = genai.Client(api_key=_gemini_key)
logger.info("Gemini client initialized", extra={"gemini_ready": bool(_gemini_key), "maps_ready": bool(_maps_key)})

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
    actions: List[ActionStep] = Field(..., min_length=1)
    verification: VerificationResult
    raw_extracted_facts: Dict[str, Any]
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
        logger.warning("Bridge called with no input")
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
        logger.info(
            "Bridge processed",
            extra={"domain": result.domain, "severity": result.severity,
                   "confidence": result.verification.confidence_score, "session_id": result.session_id}
        )

        if db:
            doc_ref = db.collection("bridge_sessions").document(result.session_id)
            doc_ref.set({**result.model_dump(), "user_id": user_id or "anonymous"})

        return result

    except json.JSONDecodeError as e:
        logger.error(f"Gemini non-JSON response: {e}")
        raise HTTPException(status_code=502, detail=f"Gemini returned non-JSON response: {str(e)}")
    except Exception as e:
        logger.error(f"Bridge processing failed: {e}")
        raise HTTPException(status_code=500, detail=f"Bridge processing failed: {str(e)}")


# ── Endpoint: Fetch Session History ───────────────────────────────────────────

@app.get("/api/history/{user_id}")
async def get_history(user_id: str) -> dict:
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


@app.get("/api/recent")
async def get_recent() -> dict:
    """Returns the 5 most recent bridge sessions across all users."""
    if not db:
        return {"sessions": [], "note": "Firebase not configured"}
    try:
        sessions = db.collection("bridge_sessions") \
            .order_by("timestamp", direction=firestore.Query.DESCENDING) \
            .limit(5) \
            .stream()
        return {"sessions": [
            {"session_id": s.id, "domain": s.get("domain"), "severity": s.get("severity"),
             "intent_summary": s.get("intent_summary"), "timestamp": s.get("timestamp")}
            for s in sessions
        ]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/location-context")
async def location_context(location: str) -> dict:
    """Geocode a location via Google Maps and fetch live weather via Open-Meteo."""
    import urllib.request
    import urllib.parse

    result: Dict[str, Any] = {"location": location, "map_embed_url": None, "weather": None}

    if not _maps_key:
        return result

    try:
        encoded = urllib.parse.quote(location)
        geo_url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded}&key={_maps_key}"
        with urllib.request.urlopen(geo_url, timeout=5) as resp:
            geo = json.loads(resp.read())

        if geo.get("results"):
            loc = geo["results"][0]["geometry"]["location"]
            lat, lng = loc["lat"], loc["lng"]
            formatted = geo["results"][0]["formatted_address"]

            result["lat"] = lat
            result["lng"] = lng
            result["formatted_address"] = formatted
            result["map_embed_url"] = (
                f"https://www.google.com/maps/embed/v1/place"
                f"?key={_maps_key}&q={urllib.parse.quote(formatted)}&zoom=13"
            )
            result["maps_link"] = f"https://www.google.com/maps/search/?api=1&query={encoded}"

            weather_url = (
                f"https://api.open-meteo.com/v1/forecast"
                f"?latitude={lat}&longitude={lng}"
                f"&current=temperature_2m,weathercode,windspeed_10m,relative_humidity_2m"
                f"&temperature_unit=celsius&windspeed_unit=kmh&timezone=auto"
            )
            with urllib.request.urlopen(weather_url, timeout=5) as wresp:
                w = json.loads(wresp.read())

            current = w.get("current", {})
            code = current.get("weathercode", 0)
            weather_desc = {
                0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                45: "Foggy", 48: "Icy fog", 51: "Light drizzle", 61: "Light rain",
                63: "Moderate rain", 65: "Heavy rain", 71: "Light snow", 73: "Moderate snow",
                80: "Rain showers", 95: "Thunderstorm", 99: "Thunderstorm with hail"
            }.get(code, "Unknown")

            result["weather"] = {
                "temperature_c": current.get("temperature_2m"),
                "description": weather_desc,
                "windspeed_kmh": current.get("windspeed_10m"),
                "humidity_pct": current.get("relative_humidity_2m"),
            }
            logger.info("Location context fetched", extra={"location": formatted, "lat": lat, "lng": lng})
    except Exception as e:
        logger.warning(f"Location context fetch failed: {e}")

    return result


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "gemini": bool(_gemini_key),
        "firebase": db is not None,
        "maps": bool(_maps_key),
        "secret_manager": bool(_project_id),
    }


@app.get("/")
async def root():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))

app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
