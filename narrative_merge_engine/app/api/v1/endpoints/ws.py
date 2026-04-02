"""
WebSocket endpoint for real-time LLM streaming.
Clients connect and send a JSON payload; the server streams back token chunks.

Message protocol:
  Client → Server: { "task": "narrative_merge", "testimony_ids": [...], ... }
  Server → Client: { "type": "chunk", "data": "<token>" }
             then: { "type": "done" }
             or:   { "type": "error", "message": "..." }
"""

from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.ai.base_provider import LLMMessage, LLMRequest
from app.core.ai.orchestrator import get_orchestrator
from app.core.ai.prompt_registry import prompt_registry
from app.core.logging import get_logger

router = APIRouter(tags=["WebSocket / Streaming"])
logger = get_logger(__name__)


@router.websocket("/ws/stream")
async def stream_llm(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for streaming LLM responses token-by-token.

    Expected client message:
        {
          "task": "narrative_merge",
          "testimonies_json": "[...]"   // or other task-specific fields
        }
    """
    await websocket.accept()
    logger.info("WebSocket connection opened", client=websocket.client)

    orchestrator = get_orchestrator()

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            task = message.get("task", "narrative_merge")

            # Build the prompt for the requested task
            try:
                if task == "narrative_merge":
                    prompt = prompt_registry.render(
                        "narrative_merge_v1",
                        testimonies_json=message.get("testimonies_json", "[]"),
                    )
                elif task == "timeline_alignment":
                    prompt = prompt_registry.render(
                        "timeline_alignment_v1",
                        events_json=message.get("events_json", "[]"),
                    )
                else:
                    await websocket.send_json({"type": "error", "message": f"Unknown task: {task}"})
                    continue
            except KeyError as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                continue

            request = LLMRequest(
                messages=[
                    LLMMessage(role="system", content="You are an AI assistant for testimony analysis."),
                    LLMMessage(role="user", content=prompt),
                ],
                stream=True,
            )

            try:
                async for chunk in orchestrator.stream(request, task_name=task):
                    await websocket.send_json({"type": "chunk", "data": chunk})
                await websocket.send_json({"type": "done"})
            except Exception as exc:
                logger.exception("Streaming error", exc_info=exc)
                await websocket.send_json({"type": "error", "message": str(exc)})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected", client=websocket.client)
