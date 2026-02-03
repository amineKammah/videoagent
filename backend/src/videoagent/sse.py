"""
Server-Sent Events (SSE) module for real-time event streaming.

Replaces polling with push-based event delivery for better scalability.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Optional

from fastapi import Request
from fastapi.responses import StreamingResponse


async def create_event_stream(
    event_store,
    session_id: str,
    user_id: str,
    request: Request,
    check_interval: float = 0.1,
) -> AsyncGenerator[str, None]:
    """
    Async generator that yields SSE-formatted events as they're appended.
    
    Args:
        event_store: EventStore instance to read events from
        session_id: The session to stream events for
        user_id: The user ID for file path resolution
        request: FastAPI request to check for client disconnect
        check_interval: How often to check for new events (seconds)
    
    Yields:
        SSE-formatted strings: "data: {...}\n\n"
    """
    # Get initial cursor position (end of file)
    _, cursor = event_store.read_since(session_id, None, user_id=user_id)
    
    # Send initial connection event
    yield f"data: {json.dumps({'type': 'connected', 'cursor': cursor})}\n\n"
    
    while True:
        # Check if client disconnected
        if await request.is_disconnected():
            break
        
        # Check for new events
        events, new_cursor = event_store.read_since(session_id, cursor, user_id=user_id)
        
        if events:
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
            cursor = new_cursor
        
        # Small sleep to prevent busy-waiting
        await asyncio.sleep(check_interval)


def create_sse_response(
    event_store,
    session_id: str,
    user_id: str,
    request: Request,
) -> StreamingResponse:
    """
    Create a StreamingResponse for SSE.
    
    Args:
        event_store: EventStore instance
        session_id: The session to stream
        user_id: The user ID for path resolution
        request: FastAPI request object
    
    Returns:
        StreamingResponse configured for SSE
    """
    return StreamingResponse(
        create_event_stream(event_store, session_id, user_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
