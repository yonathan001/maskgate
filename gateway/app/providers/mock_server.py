import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Maskgate Standalone Mock Provider")

# Global mock state for simulating failures
state: dict[str, str | None] = {
    "failure_mode": None,  # None, "500", "429", "timeout", etc.
}


class ChatMessageModel(BaseModel):
    role: str
    content: str
    name: str | None = None


class ChatCompletionInput(BaseModel):
    model: str
    messages: list[ChatMessageModel]
    temperature: float | None = None
    stream: bool = False


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/set-failure")
def set_failure(mode: str | None = None) -> dict[str, Any]:
    state["failure_mode"] = mode
    return {"failure_mode": mode}


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionInput) -> dict[str, Any]:
    mode = state.get("failure_mode")
    if mode == "500":
        raise HTTPException(status_code=500, detail="Mock provider internal error")
    if mode == "429":
        raise HTTPException(status_code=429, detail="Mock provider rate limit exceeded")
    if mode == "400":
        raise HTTPException(status_code=400, detail="Mock provider client error")

    last_user = ""
    for m in reversed(req.messages):
        if m.role == "user":
            last_user = m.content
            break

    reply = f"Mock response for: {last_user}" if last_user else "Hello from Mock Provider!"
    prompt_tokens = max(1, sum(len(m.content.split()) for m in req.messages))
    completion_tokens = max(1, len(reply.split()))

    return {
        "id": f"chatcmpl-mock-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
