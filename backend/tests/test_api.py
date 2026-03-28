"""
Tests for Universal Intent Bridge API.
Run with: pytest tests/ -v
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import json
import os

os.environ.setdefault("GEMINI_API_KEY", "test-key")

from main import app

client = TestClient(app)


# ── Health endpoint ────────────────────────────────────────────────────────────

def test_health_returns_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "gemini" in data
    assert "firebase" in data


def test_root_serves_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


# ── Bridge endpoint validation ─────────────────────────────────────────────────

def test_bridge_requires_input():
    response = client.post("/api/bridge")
    assert response.status_code == 400
    assert "required" in response.json()["detail"].lower()


def test_bridge_with_text_calls_gemini():
    mock_output = {
        "session_id": "test-session",
        "domain": "MEDICAL",
        "intent_summary": "A patient requires immediate medical attention.",
        "severity": "CRITICAL",
        "actions": [
            {
                "step_number": 1,
                "who": "First Responder",
                "what": "Call emergency services immediately",
                "when": "Immediately",
                "via": "Phone/911",
                "priority": "CRITICAL"
            },
            {
                "step_number": 2,
                "who": "Bystander",
                "what": "Keep the patient stable and monitor breathing",
                "when": "Until ambulance arrives",
                "via": "Direct observation",
                "priority": "HIGH"
            },
            {
                "step_number": 3,
                "who": "Dispatcher",
                "what": "Send ambulance and notify hospital",
                "when": "Within 2 minutes",
                "via": "Emergency dispatch system",
                "priority": "CRITICAL"
            }
        ],
        "verification": {
            "confidence_score": 0.92,
            "verified": True,
            "gaps": [],
            "contradictions": [],
            "warnings": ["Unknown medical history"]
        },
        "raw_extracted_facts": {"location": "MG Road", "age": "58"},
        "timestamp": "2026-03-28T00:00:00Z"
    }

    mock_response = MagicMock()
    mock_response.text = json.dumps(mock_output)

    with patch("main.gemini_client") as mock_client:
        mock_client.models.generate_content.return_value = mock_response
        response = client.post("/api/bridge", data={"text_input": "Patient collapsed on MG Road"})

    assert response.status_code == 200
    data = response.json()
    assert data["domain"] == "MEDICAL"
    assert data["severity"] == "CRITICAL"
    assert len(data["actions"]) >= 1
    assert "confidence_score" in data["verification"]


def test_bridge_handles_gemini_failure():
    with patch("main.gemini_client") as mock_client:
        mock_client.models.generate_content.side_effect = Exception("Gemini unavailable")
        response = client.post("/api/bridge", data={"text_input": "test input"})

    assert response.status_code == 500
    assert "Bridge processing failed" in response.json()["detail"]


# ── History endpoint ───────────────────────────────────────────────────────────

def test_history_without_firebase_returns_empty():
    response = client.get("/api/history/test-user-123")
    assert response.status_code == 200
    data = response.json()
    assert "sessions" in data
    assert data["sessions"] == []
