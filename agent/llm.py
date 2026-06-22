"""DeepSeek/OpenAI-compatible LLM wrapper."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from agent.trace import Trace

MODEL = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com"
INPUT_CACHE_HIT = 0.0028
INPUT_CACHE_MISS = 0.14
OUTPUT = 0.28


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class LLMResult:
    content: str | None
    tool_calls: list[ToolCall]
    assistant_message: dict[str, Any]
    prompt_tokens: int
    completion_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int
    cost_usd: float


class LLMClient:
    def __init__(self, client: Any | None = None, trace: Trace | None = None, model: str = MODEL):
        # DeepSeek uses the OpenAI SDK against its base URL. Prompt caching is automatic
        # when loop messages keep the system/repo overview prefix stable.
        self.client = client or OpenAI(api_key=os.environ.get("DEEPSEEK_API_KEY"), base_url=BASE_URL)
        self.trace = trace
        self.model = model
        self.step = 0

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResult:
        response = self.client.chat.completions.create(model=self.model, messages=messages, tools=tools)
        message = response.choices[0].message
        raw_tool_calls = getattr(message, "tool_calls", None) or []
        tool_calls = [
            ToolCall(id=call.id, name=call.function.name, args=json.loads(call.function.arguments or "{}"))
            for call in raw_tool_calls
        ]
        usage = getattr(response, "usage", None)
        hit = int(getattr(usage, "prompt_cache_hit_tokens", 0) or 0)
        miss = int(getattr(usage, "prompt_cache_miss_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        prompt_tokens = hit + miss
        cost = (hit * INPUT_CACHE_HIT + miss * INPUT_CACHE_MISS + completion * OUTPUT) / 1_000_000
        assistant_message = {"role": "assistant", "content": getattr(message, "content", None)}
        if raw_tool_calls:
            assistant_message["tool_calls"] = raw_tool_calls
        self.step += 1
        if self.trace:
            self.trace.llm_call(step=self.step, model=self.model, prompt_tokens=prompt_tokens, completion_tokens=completion, cache_hit_tokens=hit, cache_miss_tokens=miss, latency_ms=0, cost_usd=cost, tool_calls=[call.name for call in tool_calls])
        return LLMResult(getattr(message, "content", None), tool_calls, assistant_message, prompt_tokens, completion, hit, miss, cost)
