"""
API v1 root router — aggregates all endpoint routers.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import conflicts, events, questions, testimony, timeline, ws

api_router = APIRouter()

api_router.include_router(testimony.router)
api_router.include_router(events.router)
api_router.include_router(timeline.router)
api_router.include_router(conflicts.router)
api_router.include_router(questions.router)
api_router.include_router(ws.router)
