"""Optional localhost viewer. Separate process; no StormCheck server routes change."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from eval.rule_lab.runner import PRESETS, run_lab

STATIC = Path(__file__).with_name("static")
app = FastAPI(title="StormCheck Rule Lab", docs_url=None, redoc_url=None)


@app.get("/api/scenarios")
def scenarios():
    return {"scenarios": [{"id": key, **value} for key, value in PRESETS.items()]}


@app.get("/api/report")
def report(preset: str = "scoped"):
    if preset not in PRESETS:
        raise HTTPException(status_code=422, detail="Choose one of the four demo scenarios.")
    return JSONResponse(run_lab(preset), headers={"Cache-Control": "no-store"})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
