"""Regression tests for uncached WebUI streaming-agent teardown."""

from api import streaming


class _FakeSessionDB:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeAgent:
    def __init__(self, *, owns_session_db):
        self._session_db = _FakeSessionDB()
        self._owns_session_db = owns_session_db
        self._session_messages = [{"role": "user", "content": "one"}]
        self.shutdown_messages = None
        self.closed = False

    def shutdown_memory_provider(self, messages=None):
        self.shutdown_messages = messages

    def close(self):
        self.closed = True
        # Mirror AIAgent.close(): it is the owner-aware lifecycle boundary.
        self.shutdown_memory_provider(self._session_messages)
        if self._owns_session_db:
            self._owns_session_db = False
            self._session_db.close()


def test_ephemeral_cleanup_delegates_full_teardown_to_agent_owner():
    agent = _FakeAgent(owns_session_db=True)

    streaming._close_ephemeral_agent(agent)

    assert agent.closed is True
    assert agent.shutdown_messages == agent._session_messages
    assert agent._session_db.closed is True


def test_ephemeral_cleanup_does_not_close_borrowed_session_db():
    agent = _FakeAgent(owns_session_db=False)

    streaming._close_ephemeral_agent(agent)

    assert agent.closed is True
    assert agent.shutdown_messages == agent._session_messages
    assert agent._session_db.closed is False


def test_streaming_finally_closes_ephemeral_agent(monkeypatch, tmp_path):
    """The real worker path must invoke teardown, not just the helper."""
    import queue
    from api.models import Session

    stream_id = "ephemeral-cleanup-worker"
    agent_holder = {}
    fake_session = Session(session_id="ephemeral-session", title="Ephemeral")
    fake_session.workspace = str(tmp_path)

    class WorkerAgent(_FakeAgent):
        def __init__(self, **kwargs):
            super().__init__(owns_session_db=True)
            agent_holder["agent"] = self
            self.stream_delta_callback = kwargs.get("stream_delta_callback")

        def run_conversation(self, **kwargs):
            return {"status": "success", "messages": [{"role": "assistant", "content": "answer"}]}

    streaming.STREAMS[stream_id] = queue.Queue()
    monkeypatch.setattr(streaming, "_get_ai_agent", lambda: WorkerAgent)
    monkeypatch.setattr(streaming, "resolve_model_provider", lambda *args, **kwargs: ("model", "provider", None))
    monkeypatch.setattr("api.config.get_config", lambda: {})
    monkeypatch.setattr("api.config._resolve_cli_toolsets", lambda *args, **kwargs: [])
    monkeypatch.setattr(streaming, "get_session", lambda _session_id: fake_session)
    monkeypatch.setattr(streaming, "RunJournalWriter", lambda *args: None)

    streaming._run_agent_streaming(
        session_id="ephemeral-session",
        msg_text="question",
        model="model",
        workspace=str(tmp_path),
        stream_id=stream_id,
        ephemeral=True,
    )

    agent = agent_holder["agent"]
    assert agent.closed is True
    assert agent._session_db.closed is True
    assert stream_id not in streaming.AGENT_INSTANCES
