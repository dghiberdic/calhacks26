"""Pitch insights routes (INSIGHTS_SPEC v1): computed on read from the runs' real data, never stored."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from contracts.models import EffortEstimate, LearningStep
from contracts.stub_app import ERRORS, ApiError

from . import insights


def install(app: FastAPI, rt: Any) -> None:
    @app.get("/api/runs/{run_id}/effort", response_model=EffortEstimate, responses=ERRORS)
    def effort(run_id: str) -> EffortEstimate:
        out = insights.effort(rt, run_id)
        if out is None:
            known = ", ".join(s.id for s in rt.storm_summaries()) or "none yet"
            raise ApiError(404, "not_found", f"No storm run {run_id}. Known: {known}.")
        return out

    @app.get("/api/learning", response_model=list[LearningStep])
    def learning() -> list[LearningStep]:
        return insights.learning(rt)
