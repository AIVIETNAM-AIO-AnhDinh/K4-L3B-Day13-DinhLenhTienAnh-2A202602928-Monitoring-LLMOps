from __future__ import annotations

from contextlib import contextmanager

import pytest

from app import agent as agent_module
from app.incidents import STATE


class ManagedPrompt:
    version = 3

    def compile(self, **variables: str) -> str:
        return (
            f"Feature={variables['feature']}\n"
            f"Docs={variables['docs']}\n"
            f"Question={variables['message']}"
        )


class RecordingObservation:
    def __init__(self, **kwargs) -> None:
        self.start = kwargs
        self.updates: list[dict] = []

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)

    def merged(self) -> dict:
        out = dict(self.start)
        for update in self.updates:
            out.update(update)
        return out


class RecordingLangfuseClient:
    def __init__(self) -> None:
        self.prompt = ManagedPrompt()
        self.span_updates: list[dict] = []
        self.observations: list[RecordingObservation] = []

    def get_prompt(self, name: str, **kwargs):
        return self.prompt

    def update_current_span(self, **kwargs) -> None:
        self.span_updates.append(kwargs)

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        observation = RecordingObservation(**kwargs)
        self.observations.append(observation)
        yield observation


def _install_client(monkeypatch) -> RecordingLangfuseClient:
    monkeypatch.setenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "production")
    client = RecordingLangfuseClient()
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    monkeypatch.setattr(agent_module, "tracing_enabled", lambda: True)
    return client


def _run_agent(message: str):
    return agent_module.LabAgent.run.__wrapped__(
        agent_module.LabAgent(),
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message=message,
        correlation_id="req-12345678",
    )


def test_agent_records_prompt_version_with_v4_observation_api(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "production")
    client = RecordingLangfuseClient()
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    monkeypatch.setattr(agent_module, "tracing_enabled", lambda: True)

    propagated: list[dict] = []

    @contextmanager
    def record_attributes(**kwargs):
        propagated.append(kwargs)
        yield

    monkeypatch.setattr(agent_module, "propagate_attributes", record_attributes)

    agent = agent_module.LabAgent()
    agent_module.LabAgent.run.__wrapped__(
        agent,
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message="Explain traces",
        correlation_id="req-12345678",
    )

    span_update = client.span_updates[-1]
    assert span_update["metadata"] == {
        "doc_count": 1,
        "query_preview": "Explain traces",
        "prompt_name": "day13-chat",
        "prompt_label": "production",
        "prompt_version": "3",
        "prompt_source": "langfuse",
        "prompt_fetch_error": "",
    }
    assert span_update["version"] == "3"
    assert propagated[0]["metadata"]["correlation_id"] == "req-12345678"
    assert propagated[-1]["prompt"] is client.prompt


def test_retrieval_and_generation_are_child_observations(monkeypatch) -> None:
    client = _install_client(monkeypatch)
    result = _run_agent("Explain the monitoring policy")

    retrieval, generation = client.observations
    assert (retrieval.start["name"], retrieval.start["as_type"]) == ("retrieval", "retriever")
    assert retrieval.merged()["output"]["doc_count"] == 1

    gen = generation.merged()
    assert gen["as_type"] == "generation"
    assert gen["model"] == "claude-sonnet-4-5"
    assert gen["prompt"] is client.prompt
    assert gen["metadata"]["ttft_ms"] == result.ttft_ms
    assert gen["usage_details"] == {
        "input": result.tokens_in,
        "output": result.tokens_out,
        "total": result.tokens_in + result.tokens_out,
    }
    assert gen["cost_details"]["total"] == result.cost_usd
    assert gen["cost_details"]["input"] + gen["cost_details"]["output"] == pytest.approx(
        result.cost_usd
    )
    assert gen["completion_start_time"] is not None


def test_observations_never_receive_raw_pii(monkeypatch) -> None:
    client = _install_client(monkeypatch)
    _run_agent("Policy for student@vinuni.edu.vn and 0987654321?")

    recorded = repr([o.merged() for o in client.observations]) + repr(client.span_updates)
    assert "student@vinuni.edu.vn" not in recorded
    assert "0987654321" not in recorded
    assert "[REDACTED_EMAIL]" in recorded


def test_retrieval_failure_marks_the_retrieval_span_as_error(monkeypatch) -> None:
    client = _install_client(monkeypatch)
    monkeypatch.setitem(STATE, "tool_fail", True)

    with pytest.raises(RuntimeError):
        _run_agent("Explain traces")

    (retrieval,) = client.observations
    assert retrieval.start["as_type"] == "retriever"
    assert retrieval.updates[-1]["level"] == "ERROR"
    assert "Vector store timeout" in retrieval.updates[-1]["status_message"]
