"""Regression tests for uncached WebUI streaming-agent teardown."""

from api import streaming


class _FakeSessionDB:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeAgent:
    def __init__(self):
        self._session_db = _FakeSessionDB()
        self._session_messages = [{"role": "user", "content": "one"}]
        self.shutdown_messages = None
        self.closed = False

    def shutdown_memory_provider(self, messages=None):
        self.shutdown_messages = messages

    def close(self):
        self.closed = True


def test_ephemeral_agent_cleanup_closes_provider_and_session_db():
    agent = _FakeAgent()

    streaming._close_ephemeral_agent(agent)

    assert agent.shutdown_messages == agent._session_messages
    assert agent._session_db.closed is True
