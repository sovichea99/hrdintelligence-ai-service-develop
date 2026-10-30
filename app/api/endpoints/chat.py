"""POST /api/v1/chat/stream: general chat, streamed as Server-Sent Events.

Requires `Authorization: Bearer <Keycloak JWT>`. Body: {"message": "...", "session_id": "<uuid>"?}.
The conversation history is stored by this service; send `session_id` to continue a conversation.

SSE contract (shared with backend/frontend):
    event: session data: {"session_id": "<uuid>"}   (first event; use it for the next message)
    event: token   data: {"text": "<delta>"}
    event: done    data: {}
    event: error   data: {"message": "<safe message>"}     (failure after streaming began)

Failures BEFORE the first token are normal HTTP errors: 401/403 (authentication), 404 (session not
found or not yours), 409 (new chat refused: the user already owns the maximum number of sessions),
422 (invalid body), 503 (LLM unreachable), 502 (LLM returned an error or nothing), so the caller
can handle them without parsing SSE. Nothing is saved in those cases.
"""

import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import CurrentUser, get_current_user
from app.llm.client import LLMError, LLMUnavailableError
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatService, SessionLimitReachedError, SessionNotFoundError

SESSION_LIMIT_MESSAGE = "Your session has reached the limit"  # wording from docs/workflows.md

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


def get_chat_service(request: Request) -> ChatService:
    state = request.app.state
    return ChatService(state.llm_client, state.session_factory, state.settings)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/stream")
async def stream_chat(
    body: ChatRequest,
    user: CurrentUser = Depends(get_current_user),
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    # Waits for the model's first token, so connection/model errors become a real HTTP status.
    try:
        turn = await service.start_turn(user.user_id, body)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Chat session not found")
    except SessionLimitReachedError:
        raise HTTPException(status_code=409, detail=SESSION_LIMIT_MESSAGE)
    except LLMUnavailableError:
        raise HTTPException(status_code=503, detail="AI model is unavailable")
    except LLMError:
        raise HTTPException(status_code=502, detail="AI model returned an error")

    async def events() -> AsyncIterator[str]:
        parts: list[str] = []
        try:
            yield _sse("session", {"session_id": str(turn.session_id)})
            async for delta in turn.deltas:
                parts.append(delta)
                yield _sse("token", {"text": delta})
            await service.save_answer(turn.session_id, "".join(parts))
            yield _sse("done", {})
        except LLMError:
            # The partial answer is not saved, and a cut-off answer is never reported as done.
            yield _sse("error", {"message": "The AI response was interrupted"})
        except SQLAlchemyError as exc:
            logger.error("Saving the answer failed: %s", type(exc).__name__)
            yield _sse("error", {"message": "The answer could not be saved"})
        finally:
            await turn.deltas.aclose()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
