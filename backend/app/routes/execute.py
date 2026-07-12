"""Script execution route: runs a generated automation script server-side.

The script executes in a sandboxed subprocess against the twin — the exact
code a user would deploy on a real instrument. Events (logs, images, errors)
stream back over SSE. One run at a time: while a run is active, mutating
microscope/simulation endpoints return 409.
"""

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services import script_runner
from ..services import twin_session as ts

router = APIRouter(prefix="/execute", tags=["execute"])


class RunScriptRequest(BaseModel):
    code: str
    timeout_s: int = script_runner.DEFAULT_TIMEOUT_S
    label: Optional[str] = None


@router.get("/status")
def get_run_status():
    return ts.run_status()


@router.post("/run")
def run_script(request: RunScriptRequest):
    """Execute the script, streaming events as SSE. 409 if a run is active."""
    if not request.code.strip():
        raise HTTPException(status_code=400, detail="Script is empty.")
    timeout_s = max(5, min(request.timeout_s, 1800))

    if not ts.try_begin_run(label=request.label or "script"):
        raise HTTPException(
            status_code=409,
            detail="A script run is already in progress.",
        )

    def event_stream():
        try:
            for event in script_runner.run_script(request.code, timeout_s=timeout_s):
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            ts.end_run()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
