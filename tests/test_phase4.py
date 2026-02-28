"""
Phase 4 tests — Processing Engine: Artifact Registry, Pipelines, Worker Scheduler,
Event System, Backfill Engine, Version Tracker, and all 4 new API routers.

All tests use TestClient (no running server).
Pattern: same as test_phase3.py — shared DB, unique IDs, INSERT OR IGNORE for fixtures.
"""

from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Schema — verify v6 tables exist
# ---------------------------------------------------------------------------

def test_schema_v6_tables():
    r = client.post("/sql/query", json={
        "sql": "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
        "params": [],
    })
    assert r.status_code == 200
    table_names = [row[0] for row in r.json()["rows"]]
    for expected in [
        "artifacts_extracted",
        "artifacts_analysis",
        "processing_jobs",
        "pipeline_versions",
        "event_log",
        "webhook_subscribers",
    ]:
        assert expected in table_names, f"Missing table: {expected}"


def test_schema_version_is_6():
    r = client.post("/sql/query", json={
        "sql": "SELECT MAX(version) AS v FROM schema_version",
        "params": [],
    })
    assert r.status_code == 200
    assert r.json()["rows"][0][0] >= 6


# ---------------------------------------------------------------------------
# Artifact Registry — unit-level (via direct imports)
# ---------------------------------------------------------------------------

def test_artifact_create():
    from app.processing.registry import create_artifact
    row = create_artifact(source_type="pdf", source_hash="sha256_test_create_001")
    assert row["id"]
    assert row["processing_state"] == "RECEIVED"
    assert row["source_type"] == "pdf"


def test_artifact_dedup_by_hash():
    """Same source_hash returns the same artifact."""
    from app.processing.registry import create_artifact
    h = "sha256_dedup_test_001"
    row1 = create_artifact(source_type="pdf", source_hash=h)
    row2 = create_artifact(source_type="pdf", source_hash=h)
    assert row1["id"] == row2["id"]


def test_artifact_get_not_found():
    r = client.get("/artifacts/nonexistent-id-xyz")
    assert r.status_code == 404


def test_artifact_list_pagination():
    from app.processing.registry import create_artifact
    # Create a few artifacts with unique hashes
    for i in range(3):
        create_artifact(source_type="image", source_hash=f"sha256_list_test_{i:03d}")

    r = client.get("/artifacts?limit=2&offset=0&source_type=image")
    assert r.status_code == 200
    body = r.json()
    assert "artifacts" in body
    assert "total" in body
    assert len(body["artifacts"]) <= 2


def test_artifact_state_transition_valid():
    """RECEIVED → PROCESSING is a valid transition."""
    import uuid as _uuid
    from app.processing.registry import create_artifact
    # Use a unique hash each run to avoid DB state pollution
    unique_hash = f"sha256_state_valid_{_uuid.uuid4().hex[:8]}"
    row = create_artifact(source_type="pdf", source_hash=unique_hash)
    artifact_id = row["id"]

    r = client.post(f"/artifacts/{artifact_id}/state", json={"new_state": "PROCESSING"})
    assert r.status_code == 200, r.text
    assert r.json()["processing_state"] == "PROCESSING"


def test_artifact_state_transition_invalid():
    """RECEIVED → EXPORTED is invalid; should return 409."""
    from app.processing.registry import create_artifact
    row = create_artifact(source_type="pdf", source_hash="sha256_state_invalid_001")
    artifact_id = row["id"]

    r = client.post(f"/artifacts/{artifact_id}/state", json={"new_state": "EXPORTED"})
    assert r.status_code == 409, r.text


def test_artifact_export_shape():
    """Export returns {raw, extracted, analysis} keys."""
    from app.processing.registry import create_artifact
    row = create_artifact(source_type="pdf", source_hash="sha256_export_test_001")
    artifact_id = row["id"]

    r = client.get(f"/artifacts/{artifact_id}/export")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "raw" in body
    assert "extracted" in body
    assert "analysis" in body
    assert isinstance(body["extracted"], list)
    assert isinstance(body["analysis"], list)


def test_artifact_add_extracted():
    from app.processing.registry import create_artifact, add_extracted
    row = create_artifact(source_type="pdf", source_hash="sha256_extracted_001")
    extracted = add_extracted(
        row["id"],
        pipeline_name="ocr",
        pipeline_version="1.0",
        extraction_data={"blocks": [], "confidence": 0.9},
        confidence_score=0.9,
    )
    assert extracted["id"]
    assert extracted["artifact_id"] == row["id"]
    assert extracted["pipeline_name"] == "ocr"


def test_artifact_add_analysis():
    from app.processing.registry import create_artifact, add_analysis
    row = create_artifact(source_type="pdf", source_hash="sha256_analysis_001")
    analysis = add_analysis(
        row["id"],
        summary_text="Test summary",
        tags=["tag1", "tag2"],
        validation_score=0.85,
    )
    assert analysis["id"]
    assert analysis["artifact_id"] == row["id"]
    assert analysis["summary_text"] == "Test summary"


# ---------------------------------------------------------------------------
# Pipelines — availability + stub outputs
# ---------------------------------------------------------------------------

def test_pipeline_registry_all_registered():
    from app.processing.pipeline_registry import list_pipelines
    pipelines = list_pipelines()
    names = [p["name"] for p in pipelines]
    assert "ocr" in names
    assert "audio" in names
    assert "llm_analysis" in names


def test_ocr_pipeline_stub():
    """OCR returns structured stub when surya not installed."""
    from app.processing.pipeline_registry import get_pipeline
    ocr = get_pipeline("ocr")
    result = ocr.process({"id": "test-artifact", "source_type": "pdf", "file_path": "/tmp/test.pdf"}, {})
    assert "extraction_data" in result
    assert "confidence_score" in result
    # When surya is unavailable: blocks/tables/signatures in extraction_data
    if not ocr.available:
        assert result["extraction_data"]["available"] is False
        assert "blocks" in result["extraction_data"]
        assert "tables" in result["extraction_data"]


def test_audio_pipeline_stub():
    """Audio returns structured stub when faster_whisper not installed."""
    from app.processing.pipeline_registry import get_pipeline
    audio = get_pipeline("audio")
    result = audio.process({"id": "test-artifact", "source_type": "audio", "file_path": "/tmp/test.mp3"}, {})
    assert "extraction_data" in result
    if not audio.available:
        assert result["extraction_data"]["available"] is False
        assert "transcript" in result["extraction_data"]
        assert "segments" in result["extraction_data"]


def test_llm_pipeline_always_available():
    """LLM analysis pipeline is always available (no hard ML deps)."""
    from app.processing.pipeline_registry import get_pipeline
    llm = get_pipeline("llm_analysis")
    assert llm.available is True
    result = llm.process({"id": "test-artifact", "source_type": "pdf"}, {})
    assert "extraction_data" in result
    assert result["extraction_data"]["available"] is True


# ---------------------------------------------------------------------------
# Worker Scheduler
# ---------------------------------------------------------------------------

def test_enqueue_job():
    from app.processing.worker import enqueue_job
    job = enqueue_job("ocr", payload={"test": True}, priority=5)
    assert job["id"]
    assert job["job_status"] == "QUEUED"
    assert job["job_type"] == "ocr"


def test_enqueue_idempotency():
    """Same idempotency_key returns the same job."""
    from app.processing.worker import enqueue_job
    key = "idem-test-key-001"
    job1 = enqueue_job("ocr", payload={"x": 1}, idempotency_key=key)
    job2 = enqueue_job("ocr", payload={"x": 2}, idempotency_key=key)
    assert job1["id"] == job2["id"]


def test_claim_and_complete_job():
    from app.processing.worker import enqueue_job, claim_next_job, complete_job
    job = enqueue_job("audio", payload={"claim_test": True}, priority=1)
    claimed = claim_next_job(worker_id="worker-001")
    assert claimed is not None
    assert claimed["job_status"] == "RUNNING"

    finished = complete_job(claimed["id"], result={"output": "done"})
    assert finished["job_status"] == "COMPLETED"
    assert finished["completed_at"] is not None


def test_fail_job_retry():
    """First failure sets RETRYING, not FAILED."""
    from app.processing.worker import enqueue_job, claim_next_job, fail_job
    job = enqueue_job("ocr", max_retries=3, priority=2)
    claim_next_job(worker_id="worker-002")
    failed = fail_job(job["id"], "Test error")
    # retry_count=1, max_retries=3 → should be RETRYING
    assert failed["job_status"] == "RETRYING"
    assert failed["retry_count"] == 1
    assert failed["error_message"] == "Test error"


def test_job_stats():
    from app.processing.worker import get_worker_stats
    stats = get_worker_stats()
    assert "queued" in stats
    assert "completed" in stats
    assert "failed" in stats
    assert "total" in stats
    assert stats["total"] >= 0


# ---------------------------------------------------------------------------
# Event System
# ---------------------------------------------------------------------------

def test_emit_event_logged():
    from app.processing.events import emit_event, get_recent_events
    event_id = emit_event("artifact.ingested", artifact_id="art-001", payload={"test": True})
    assert event_id

    events, total = get_recent_events(limit=10, event_type="artifact.ingested")
    ids = [e["id"] for e in events]
    assert event_id in ids


def test_webhook_create_and_list():
    import uuid as _uuid
    from app.processing.events import add_webhook, list_webhooks
    url = f"http://localhost:9999/hook-{_uuid.uuid4().hex[:8]}"
    wh = add_webhook(url, event_types=["artifact.ingested"])
    assert wh["id"]
    assert wh["url"] == url

    all_hooks = list_webhooks()
    ids = [w["id"] for w in all_hooks]
    assert wh["id"] in ids


def test_webhook_delete():
    import uuid as _uuid
    from app.processing.events import add_webhook, remove_webhook, list_webhooks
    url = f"http://localhost:9998/hook2-{_uuid.uuid4().hex[:8]}"
    wh = add_webhook(url, event_types=[])
    removed = remove_webhook(wh["id"])
    assert removed is True

    all_hooks = list_webhooks()
    ids = [w["id"] for w in all_hooks]
    assert wh["id"] not in ids


# ---------------------------------------------------------------------------
# Backfill Engine
# ---------------------------------------------------------------------------

def test_backfill_simulate():
    """simulate=True returns plan without enqueuing jobs."""
    from app.processing.version_tracker import register_version
    from app.processing.registry import create_artifact, add_extracted

    # Register a new pipeline version (v2.0) for ocr
    register_version("ocr", "2.0")

    # Create artifact with v1.0 extraction
    art = create_artifact(source_type="pdf", source_hash="sha256_backfill_test_001")
    add_extracted(
        art["id"],
        pipeline_name="ocr",
        pipeline_version="1.0",
        extraction_data={"blocks": []},
    )

    r = client.post("/backfill", json={"pipeline_name": "ocr", "simulate": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["simulated"] is True
    assert body["jobs_enqueued"] == 0
    assert body["pipeline_name"] == "ocr"
    assert "artifacts" in body


# ---------------------------------------------------------------------------
# Version Tracker
# ---------------------------------------------------------------------------

def test_register_version():
    from app.processing.version_tracker import register_version
    ver = register_version("audio", "1.5", model_version="whisper-small")
    assert ver["pipeline_name"] == "audio"
    assert ver["engine_version"] == "1.5"


def test_get_current_version():
    from app.processing.version_tracker import register_version, get_current_version
    register_version("image", "1.0")
    current = get_current_version("image")
    assert current is not None
    assert current["pipeline_name"] == "image"


def test_backfill_eligibility():
    """check_backfill_eligible returns artifacts needing reprocessing."""
    from app.processing.version_tracker import register_version, check_backfill_eligible
    from app.processing.registry import create_artifact, add_extracted

    # Register current version v3.0
    register_version("ocr", "3.0")

    art = create_artifact(source_type="pdf", source_hash="sha256_backfill_elig_001")
    add_extracted(
        art["id"],
        pipeline_name="ocr",
        pipeline_version="1.0",
        extraction_data={"blocks": []},
    )

    eligible = check_backfill_eligible(art["id"])
    # Should find that ocr 1.0 is behind 3.0
    ocr_eligible = [e for e in eligible if e["pipeline_name"] == "ocr"]
    assert len(ocr_eligible) > 0
    assert ocr_eligible[0]["target_version"] == "3.0"


# ---------------------------------------------------------------------------
# API — artifact lifecycle integration
# ---------------------------------------------------------------------------

def test_api_artifact_lifecycle():
    """Create → get → process → state transitions."""
    import uuid as _uuid
    # Create with unique hash to avoid DB state pollution across test runs
    r = client.post("/artifacts", json={
        "source_type": "pdf",
        "source_hash": f"sha256_lifecycle_api_{_uuid.uuid4().hex[:12]}",
        "file_path": "/data/test.pdf",
        "page_url": "https://example.com/doc",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    artifact_id = body["id"]
    assert body["processing_state"] == "RECEIVED"
    assert body["page_url"] == "https://example.com/doc"

    # Get
    r = client.get(f"/artifacts/{artifact_id}")
    assert r.status_code == 200
    assert r.json()["id"] == artifact_id

    # Enqueue processing
    r = client.post(f"/artifacts/{artifact_id}/process", json={
        "pipeline_name": "ocr",
        "priority": 5,
    })
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    assert job_id

    # State: RECEIVED → PROCESSING
    r = client.post(f"/artifacts/{artifact_id}/state", json={"new_state": "PROCESSING"})
    assert r.status_code == 200
    assert r.json()["processing_state"] == "PROCESSING"

    # State: PROCESSING → PROCESSED
    r = client.post(f"/artifacts/{artifact_id}/state", json={"new_state": "PROCESSED"})
    assert r.status_code == 200
    assert r.json()["processing_state"] == "PROCESSED"


def test_api_artifacts_list():
    r = client.get("/artifacts?limit=5&offset=0")
    assert r.status_code == 200
    body = r.json()
    assert "artifacts" in body
    assert "total" in body
    assert "limit" in body


def test_api_artifact_not_found():
    r = client.get("/artifacts/does-not-exist-999")
    assert r.status_code == 404


def test_api_artifact_invalid_transition():
    """RECEIVED → ARCHIVED is invalid → 409."""
    r = client.post("/artifacts", json={
        "source_type": "pdf",
        "source_hash": "sha256_invalid_trans_api_001",
    })
    assert r.status_code == 201
    artifact_id = r.json()["id"]

    r = client.post(f"/artifacts/{artifact_id}/state", json={"new_state": "ARCHIVED"})
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# API — workers
# ---------------------------------------------------------------------------

def test_api_workers_pipelines():
    r = client.get("/workers/pipelines")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    names = [p["name"] for p in body]
    assert "ocr" in names
    assert "audio" in names
    assert "llm_analysis" in names


def test_api_workers_jobs():
    r = client.get("/workers/jobs?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert "jobs" in body
    assert "total" in body


def test_api_workers_stats():
    r = client.get("/workers/stats")
    assert r.status_code == 200
    body = r.json()
    assert "queued" in body
    assert "completed" in body
    assert "total" in body


# ---------------------------------------------------------------------------
# API — backfill
# ---------------------------------------------------------------------------

def test_api_backfill_simulate():
    r = client.post("/backfill", json={"pipeline_name": "ocr", "simulate": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["simulated"] is True
    assert body["pipeline_name"] == "ocr"
    assert "eligible_count" in body
    assert "artifacts" in body


# ---------------------------------------------------------------------------
# API — events
# ---------------------------------------------------------------------------

def test_api_events_recent():
    from app.processing.events import emit_event
    emit_event("test.event.api", payload={"source": "test_api"})

    r = client.get("/events?limit=10")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "events" in body
    assert "total" in body


def test_api_webhooks_crud():
    import uuid as _uuid
    hook_url = f"http://localhost:7777/hook-{_uuid.uuid4().hex[:8]}"
    # Create
    r = client.post("/events/webhooks", json={
        "url": hook_url,
        "event_types": ["artifact.processed"],
    })
    assert r.status_code == 201, r.text
    webhook_id = r.json()["id"]
    assert webhook_id

    # List
    r = client.get("/events/webhooks")
    assert r.status_code == 200
    ids = [w["id"] for w in r.json()["webhooks"]]
    assert webhook_id in ids

    # Delete
    r = client.delete(f"/events/webhooks/{webhook_id}")
    assert r.status_code == 204

    # Verify removed from list
    r = client.get("/events/webhooks")
    ids_after = [w["id"] for w in r.json()["webhooks"]]
    assert webhook_id not in ids_after
