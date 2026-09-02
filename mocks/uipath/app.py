"""mock-uipath — stand-in for the RPA execution queue.

Released recommendations land here as jobs; a worker executes each against the
claims platform (mock-unet) with simulated latency and a transient-failure rate,
retrying once — the failure handling real RPA queues force on you.
"""

import os
import random
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

JOBS: dict[str, dict] = {}
_seq = 0
_rng = random.Random()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _seq
    JOBS.clear()  # restart = reset, like the other mocks
    _seq = 0
    app.state.unet = httpx.Client(
        base_url=os.environ.get("UNET_URL", "http://localhost:8001"), timeout=10
    )
    yield
    app.state.unet.close()


app = FastAPI(title="mock-uipath (RPA execution queue)", lifespan=lifespan)


class JobIn(BaseModel):
    ticket_id: str
    claim_id: str
    action: str
    amount: str | None = None


@app.get("/health")
def health():
    return {"status": "ok", "jobs": len(JOBS)}


def _execute(job_id: str) -> None:
    job = JOBS[job_id]
    job["status"] = "running"
    latency = float(os.environ.get("EXECUTION_LATENCY_SECONDS", "0.1"))
    failure_rate = float(os.environ.get("FAILURE_RATE", "0.05"))
    max_attempts = 2

    for attempt in range(1, max_attempts + 1):
        job["attempts"] = attempt
        time.sleep(latency)
        if _rng.random() < failure_rate:
            job["last_error"] = "transient robot failure (simulated)"
            continue
        try:
            resp = app.state.unet.post(
                f"/claims/{job['claim_id']}/adjustments",
                json={
                    "action": job["action"],
                    "amount": job["amount"],
                    "source_ticket": job["ticket_id"],
                },
            )
            resp.raise_for_status()
        except Exception as exc:  # a robot execution error must fail the job, not the queue
            job["last_error"] = str(exc)
            continue
        job["status"] = "succeeded"
        job["result"] = resp.json()
        return
    job["status"] = "failed"


@app.post("/queues/claims-rework/jobs", status_code=201)
def enqueue(job_in: JobIn, background: BackgroundTasks):
    global _seq
    _seq += 1
    job_id = f"JOB-{_seq:06d}"
    JOBS[job_id] = {
        "job_id": job_id,
        **job_in.model_dump(),
        "status": "queued",
        "attempts": 0,
        "last_error": None,
        "result": None,
    }
    background.add_task(_execute, job_id)
    return JOBS[job_id]


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(404, f"job {job_id} not found")
    return JOBS[job_id]


@app.get("/queues/claims-rework/jobs")
def list_jobs(status: str | None = None):
    jobs = list(JOBS.values())
    if status:
        jobs = [j for j in jobs if j["status"] == status]
    return jobs
