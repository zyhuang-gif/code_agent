from types import SimpleNamespace
from pathlib import Path
from agent.llm import LLMClient, MODEL
from agent.trace import Trace


class FakeCompletions:
    def __init__(self):
        self.calls = []
    def create(self, **kwargs):
        self.calls.append(kwargs)
        tool_call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="read_file", arguments='{"path":"a.py"}'))
        message = SimpleNamespace(content="hi", tool_calls=[tool_call])
        usage = SimpleNamespace(prompt_cache_hit_tokens=5, prompt_cache_miss_tokens=10, completion_tokens=20)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


def test_llm_client_passes_model_messages_tools_and_records_trace(tmp_path: Path):
    fake = FakeClient()
    trace = Trace(tmp_path / "trace.jsonl")
    client = LLMClient(client=fake, trace=trace)
    result = client.chat([{"role":"user","content":"x"}], tools=[{"type":"function"}])
    assert fake.chat.completions.calls[0]["model"] == MODEL
    assert result.tool_calls[0].args == {"path": "a.py"}
    assert result.cache_hit_tokens == 5
    assert result.cost_usd > 0
    assert "llm_call" in (tmp_path / "trace.jsonl").read_text(encoding="utf-8")


def test_llm_client_handles_content_without_tool_calls(tmp_path: Path):
    class NoTools(FakeCompletions):
        def create(self, **kwargs):
            message = SimpleNamespace(content="done", tool_calls=None)
            usage = SimpleNamespace(prompt_cache_hit_tokens=0, prompt_cache_miss_tokens=1, completion_tokens=1)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)
    fake = FakeClient(); fake.chat.completions = NoTools()
    result = LLMClient(client=fake, trace=Trace(tmp_path / "t.jsonl")).chat([], [])
    assert result.content == "done"
    assert result.tool_calls == []
