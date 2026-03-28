# Universal Intent Bridge 🌉

> **Gemini 1.5 Pro · FastAPI · Next.js · Pydantic · Firebase · Cloud Run**

Convert messy, unstructured real-world inputs — handwritten notes, voice recordings, accident photos, crisis WhatsApp messages — into **structured, Pydantic-verified, life-saving action plans**.

---

## What It Does

| Input | → | Output |
|-------|---|--------|
| Scribbled patient history | → | Structured triage + drug interactions + 911 dispatch card |
| 20 conflicting WhatsApp flood messages | → | Unified incident map + resource priorities |
| Photo of a damaged road sign | → | Maintenance ticket + rerouting advisory |
| Distressed 2am text message | → | Risk assessment + escalation path + helpline routing |
| Confusing legal notice | → | Plain-language summary + deadlines + required actions |

**The Pydantic Guardian Layer** ensures no hallucinated or incomplete action ever reaches an external system.

---

## Architecture

```
[Messy Input: Voice / Photo / Text]
         ↓
[Next.js Frontend — File uploads, Voice streaming, UI]
         ↓  (multipart/form-data)
[FastAPI Backend — Python]
         ↓
[Gemini 1.5 Pro — Multimodal Understanding]
         ↓
[Pydantic Schema Validation — Guardian Layer]
         ↓
[BridgedOutput JSON: domain, severity, actions, verification]
         ↓
[Firebase Firestore — Session History]
         ↓
[Action Cards UI with confidence scores + gap detection]
```

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Frontend | **Next.js 14** | First-class Antigravity support, file uploads, voice streaming |
| AI Engine | **Gemini 1.5 Pro** (google-genai SDK) | Multimodal: text + image + audio in one call |
| Validation | **Pydantic v2** | Strict schema enforcement — the "Guardian" layer |
| Backend | **FastAPI** | Async, fastest Python API framework, native Pydantic integration |
| Auth + Storage | **Firebase Auth + Firestore** | Google-grade security, auto-provisioned |
| Hosting | **Google Cloud Run** | Serverless, scales to zero, identical local→cloud environment |
| Local Dev | **Docker Compose** | Environment parity guaranteed |

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey)

### 1. Clone and configure
```bash
git clone <this-repo>
cd universal-intent-bridge
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### 2. Run locally
```bash
docker-compose up --build
```

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

### 3. Test without Docker (development)

**Backend:**
```bash
cd backend
pip install -r requirements.txt
export GEMINI_API_KEY=your_key_here
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

---

## Deploy to Google Cloud Run

```bash
# 1. Authenticate
gcloud auth login
gcloud auth application-default login

# 2. Set your project in .env
# GCP_PROJECT_ID=your-project-id

# 3. One command deploy
chmod +x deploy-cloudrun.sh
./deploy-cloudrun.sh
```

This creates two Cloud Run services:
- `bridge-ui` — Next.js frontend (public)
- `bridge-logic` — FastAPI backend (public, CORS-locked to frontend)

---

## API Reference

### `POST /api/bridge`

Accepts `multipart/form-data`:

| Field | Type | Description |
|-------|------|-------------|
| `text_input` | string (optional) | Free-form text of any messiness |
| `image_file` | file (optional) | Photo, scan, handwritten note |
| `audio_file` | file (optional) | Voice memo (webm/mp3/wav) |

Returns `BridgedOutput`:
```json
{
  "session_id": "uuid",
  "domain": "MEDICAL|DISASTER|TRAFFIC|MENTAL_HEALTH|LEGAL|INFRASTRUCTURE|GENERAL",
  "intent_summary": "One-line situation summary",
  "severity": "CRITICAL|HIGH|MEDIUM|LOW",
  "actions": [
    {
      "step_number": 1,
      "who": "First Responder",
      "what": "Call 112 and report unconscious patient at...",
      "when": "Immediately",
      "via": "Emergency Services Dispatch",
      "priority": "CRITICAL"
    }
  ],
  "verification": {
    "confidence_score": 0.87,
    "verified": true,
    "gaps": [],
    "contradictions": [],
    "warnings": ["Patient allergy not confirmed"]
  },
  "raw_extracted_facts": {
    "patient_name": "Raj",
    "age": "67",
    "medications": "metformin, lisinopril, aspirin"
  },
  "timestamp": "2026-03-28T06:35:00Z"
}
```

### `GET /api/health`
Returns backend status and service connectivity.

### `GET /api/history/{user_id}`
Returns last 20 bridge sessions for a Firebase-authenticated user.

---

## Firebase Setup (Optional)

1. Create a Firebase project at [console.firebase.google.com](https://console.firebase.google.com)
2. Enable Firestore Database
3. Download `serviceAccountKey.json` → place in `backend/`
4. Add web app config to `.env`

---

## Safety Design

- **Pydantic Guardian**: Every Gemini response is parsed through strict Pydantic models. If Gemini hallucinates an action without `who/what/when/via`, the API returns a 422 with the exact field that failed
- **Confidence Scores**: Any response below 0.7 is flagged as unverified
- **Gap Detection**: Missing critical fields (patient DOB, location coordinates, etc.) are surfaced explicitly
- **No action dispatched automatically** — the UI requires human confirmation before any external system is contacted

---

## Societal Impact Domains

| Domain | Example Use Case |
|--------|-----------------|
| 🏥 MEDICAL | ER triage from handwritten patient notes |
| 🌊 DISASTER | Flood coordination from conflicting field reports |
| 🚦 TRAFFIC | Infrastructure damage reporting from photos |
| 🧠 MENTAL HEALTH | Crisis escalation from distress messages |
| ⚖️ LEGAL | Legal notice deadline extraction |
| 🏗️ INFRASTRUCTURE | Maintenance ticketing from field observations |

---

## Antigravity / AI Studio Integration

This project is structured for **Google Antigravity Agent** compatibility:

1. Open Google AI Studio → Launch Antigravity
2. Point it at this repository
3. It will auto-detect `docker-compose.yml` for local orchestration
4. Use the Cloud Run MCP Server for `./deploy-cloudrun.sh` execution
5. Firebase resources can be auto-provisioned via Antigravity's Secrets Manager

---

*Built for the Gemini Developer Challenge 2026 — Universal Bridge between human intent and complex systems.*
