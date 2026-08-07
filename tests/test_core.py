"""Tests for core modules: config, context, session, imports."""

from repowitness import Agent, LLM, Config, ALL_TOOLS, __version__
from repowitness import config as config_module
from repowitness import session as session_module
from repowitness.context import ContextManager, estimate_tokens
from repowitness.llm import LLMResponse, ToolCall
from repowitness.session import save_session, load_session, list_sessions
from repowitness.tools.edit import EditFileTool
from repowitness.tools.read import ReadFileTool
from repowitness.tools.write import WriteFileTool


_LEGACY_TOOL_FACTORIES = {
    "edit_file": EditFileTool,
    "read_file": ReadFileTool,
    "write_file": WriteFileTool,
}


def _legacy_tool(name):
    return _LEGACY_TOOL_FACTORIES[name]()


def test_version():
    assert __version__ == "0.4.2"


def test_public_api_exports():
    """Users should be able to import key classes from the top-level package."""
    assert Agent is not None
    assert LLM is not None
    assert Config is not None
    assert ALL_TOOLS == []


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("CORECODER_MODEL", "test-model")
    monkeypatch.setenv("REPOWITNESS_REASONING_EFFORT", "low")
    c = Config.from_env()
    assert c.model == "test-model"
    assert c.reasoning_effort == "low"


def test_config_defaults(monkeypatch):
    # clear relevant env vars without leaking the change into other tests
    monkeypatch.setattr(config_module, "_load_dotenv", lambda: None)
    monkeypatch.delenv("REPOWITNESS_MODEL", raising=False)
    monkeypatch.delenv("REPOWITNESS_MAX_TOKENS", raising=False)
    monkeypatch.delenv("REPOWITNESS_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("CORECODER_MODEL", raising=False)
    monkeypatch.delenv("CORECODER_MAX_TOKENS", raising=False)
    monkeypatch.delenv("CORECODER_REASONING_EFFORT", raising=False)

    c = Config.from_env()
    assert c.model == "gpt-5.5"
    assert c.max_tokens == 4096
    assert c.temperature == 0.0
    assert c.reasoning_effort is None


# --- Context ---

def test_estimate_tokens():
    msgs = [{"role": "user", "content": "hello world"}]
    t = estimate_tokens(msgs)
    assert t > 0
    assert t < 100


def test_context_snip():
    ctx = ContextManager(max_tokens=3000)
    msgs = [
        {"role": "tool", "tool_call_id": "t1", "content": "x\n" * 1000},
    ]
    before = estimate_tokens(msgs)
    ctx._snip_tool_outputs(msgs)
    after = estimate_tokens(msgs)
    assert after < before


def test_context_compress():
    ctx = ContextManager(max_tokens=2000)
    msgs = []
    for i in range(20):
        msgs.append({"role": "user", "content": f"msg {i} " + "a" * 200})
        msgs.append({"role": "tool", "tool_call_id": f"t{i}", "content": "b" * 2000})
    before = estimate_tokens(msgs)
    ctx.maybe_compress(msgs, None)
    after = estimate_tokens(msgs)
    assert after < before
    assert len(msgs) < 40  # should be compressed


def test_safe_split_never_orphans_a_tool_message():
    """The kept tail must not begin with a 'tool' message - it would be severed
    from the assistant tool_calls that produced it, which the API rejects."""
    ctx = ContextManager(max_tokens=1000)
    messages = [
        {"role": "user", "content": "do it"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "result"},
        {"role": "tool", "tool_call_id": "c2", "content": "result2"},
    ]
    split = ctx._safe_split(messages, keep_recent=1)
    assert messages[split].get("role") != "tool"


def test_compress_never_leaves_an_orphan_tool_reply():
    """After summarisation every tool reply must still follow its tool_calls."""
    ctx = ContextManager(max_tokens=2000)
    msgs = []
    for i in range(20):
        msgs.append({"role": "user", "content": f"msg {i} " + "a" * 200})
        msgs.append({"role": "assistant", "content": None, "tool_calls": [{"id": f"c{i}"}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": "b" * 800})
    ctx.maybe_compress(msgs, None)
    for i, m in enumerate(msgs):
        if m.get("role") == "tool":
            prev = msgs[i - 1]
            assert prev.get("role") == "tool" or prev.get("tool_calls"), f"orphan tool at {i}"


# --- Session ---

def test_session_save_load(tmp_path, monkeypatch):
    monkeypatch.setattr(session_module, "SESSIONS_DIR", tmp_path)
    msgs = [{"role": "user", "content": "test message"}]
    save_session(msgs, "test-model", "pytest_test_session")
    loaded = load_session("pytest_test_session")
    assert loaded is not None
    assert loaded[0] == msgs
    assert loaded[1] == "test-model"


def test_session_name_is_sanitized(tmp_path, monkeypatch):
    monkeypatch.setattr(session_module, "SESSIONS_DIR", tmp_path)
    msgs = [{"role": "user", "content": "test message"}]
    sid = save_session(msgs, "test-model", "../Research Notes!")

    assert sid == "Research-Notes"
    assert (tmp_path / "Research-Notes.json").exists()
    assert load_session("../Research Notes!") is not None


def test_session_not_found():
    assert load_session("nonexistent_session_id") is None


def test_list_sessions():
    sessions = list_sessions()
    assert isinstance(sessions, list)


# --- Cost estimation ---

def test_cost_estimation_known_model():
    from repowitness.llm import LLM
    llm = LLM.__new__(LLM)
    llm.model = "gpt-5.4"
    llm.total_prompt_tokens = 1_000_000
    llm.total_completion_tokens = 500_000
    cost = llm.estimated_cost
    assert cost is not None
    assert cost == 2.5 + 7.5  # $2.5/M in + $15/M out * 0.5M

def test_cost_estimation_unknown_model():
    from repowitness.llm import LLM
    llm = LLM.__new__(LLM)
    llm.model = "some-custom-model"
    llm.total_prompt_tokens = 1000
    llm.total_completion_tokens = 500
    assert llm.estimated_cost is None


# --- Changed files tracking ---

def test_edit_tracks_changed_files(tmp_path):
    from repowitness.tools.edit import _changed_files
    _changed_files.clear()
    edit = _legacy_tool("edit_file")
    path = tmp_path / "sample.py"
    path.write_text("aaa\nbbb\n")
    edit.execute(file_path=str(path), old_string="aaa", new_string="zzz")
    assert any(str(path) in p for p in _changed_files)
    _changed_files.clear()


def test_write_tracks_changed_files(tmp_path):
    from repowitness.tools.edit import _changed_files
    _changed_files.clear()
    write = _legacy_tool("write_file")
    path = tmp_path / "tracked.txt"
    write.execute(file_path=str(path), content="tracked\n")
    assert any(path.name in p for p in _changed_files)
    _changed_files.clear()


# --- Agent tool execution ---

def test_agent_tool_scope_is_per_instance():
    """An Agent restricted to a subset of tools must not resolve tools outside it."""
    only_read = [_legacy_tool("read_file")]
    agent = Agent(llm=LLM.__new__(LLM), tools=only_read)
    assert set(agent._tool_by_name) == {"read_file"}

    class _TC:
        name = "bash"  # a real, registered tool - but not in this agent's set
        id = "x"
        arguments = {"command": "echo hi"}

    assert "unknown tool 'bash'" in agent._exec_tool(_TC())


def test_exec_tool_distinguishes_bad_args_from_internal_error():
    """A TypeError raised inside a tool must not be reported as bad arguments."""
    from repowitness.tools.base import Tool

    class _Boom(Tool):
        name = "boom"
        description = "raises TypeError internally"
        parameters = {"type": "object", "properties": {}, "required": []}

        def execute(self):
            raise TypeError("internal explosion")

    agent = Agent(llm=LLM.__new__(LLM), tools=[_Boom()])

    class _BadArgs:
        name, id, arguments = "boom", "1", {"unexpected": 1}

    class _Good:
        name, id, arguments = "boom", "2", {}

    assert "bad arguments" in agent._exec_tool(_BadArgs())
    assert "Error executing boom" in agent._exec_tool(_Good())
    assert "bad arguments" not in agent._exec_tool(_Good())


def test_agent_does_not_replay_an_empty_assistant_message():
    class _EmptyThenCompleteLLM:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, tools=None, on_token=None):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse()
            assert not any(
                message["role"] == "assistant"
                and message.get("content") is None
                and not message.get("tool_calls")
                for message in messages
            )
            return LLMResponse(content="done")

    agent = Agent(llm=_EmptyThenCompleteLLM(), tools=[], system="test")

    assert agent.chat("first") == ""
    assert agent.chat("second") == "done"


def test_agent_replays_reasoning_content_after_a_tool_call():
    from repowitness.tools.base import Tool

    class _ProbeTool(Tool):
        name = "probe"
        description = "Return evidence."
        parameters = {"type": "object", "properties": {}, "required": []}

        def execute(self):
            return "evidence"

    class _ReasoningToolLLM:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, tools=None, on_token=None):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    reasoning_content="inspect evidence",
                    tool_calls=[ToolCall("call-1", "probe", {})],
                )
            assistant = next(
                message
                for message in messages
                if message.get("tool_calls")
            )
            assert assistant["reasoning_content"] == "inspect evidence"
            return LLMResponse(content="done")

    agent = Agent(llm=_ReasoningToolLLM(), tools=[_ProbeTool()], system="test")

    assert agent.chat("review") == "done"


def test_interrupt_backfills_missing_tool_replies():
    """A half-finished tool round must be repaired so history stays valid."""
    agent = Agent(llm=LLM.__new__(LLM), tools=[])
    agent.messages = [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "a"}, {"id": "b"}]},
        {"role": "tool", "tool_call_id": "a", "content": "done"},
    ]

    class _TC:
        def __init__(self, i):
            self.id = i

    agent._answer_pending_tool_calls([_TC("a"), _TC("b")])
    replies = [m for m in agent.messages if m.get("role") == "tool"]
    ids = [m["tool_call_id"] for m in replies]
    assert sorted(ids) == ["a", "b"]
    assert ids.count("a") == 1  # the already-answered call wasn't duplicated
