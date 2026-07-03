"""Chat endpoints with optional SSE streaming."""

from fastapi import APIRouter, Depends

from agents.manager import ManagerAgent
from core.dependencies import get_manager_agent, get_memory_store
from memory.composite import CompositeMemory
from schemas.chat import ChatRequest, ChatResponse
from schemas.memory import MemoryEntry, MemoryScope
from streaming.publisher import StreamPublisher
from streaming.sse import SSEResponse

router = APIRouter()


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    manager: ManagerAgent = Depends(get_manager_agent),
    memory: CompositeMemory = Depends(get_memory_store),
) -> ChatResponse | SSEResponse:
    task = manager.create_task(session_id=body.session_id, query=body.message)

    await memory.save(
        MemoryEntry(
            session_id=body.session_id,
            key="user_message",
            content=body.message,
            scope=MemoryScope.SHORT_TERM,
        ),
    )

    if body.stream:
        publisher = StreamPublisher(manager)
        return SSEResponse(publisher.publish(task))

    result = await manager.run(task)

    await memory.save(
        MemoryEntry(
            session_id=body.session_id,
            key="assistant_message",
            content=result.output,
            scope=MemoryScope.SHORT_TERM,
        ),
    )

    return ChatResponse(
        session_id=body.session_id,
        message=result.output,
        specialist=result.specialist_used,
    )
