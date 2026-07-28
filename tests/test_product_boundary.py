def test_repowitness_package_exports_the_reused_agent_framework():
    from repowitness import (
        Agent,
        AuditEngine,
        AuditReport,
        AuditRequest,
        Config,
        LLM,
    )

    assert Agent is not None
    assert AuditEngine is not None
    assert AuditReport is not None
    assert AuditRequest is not None
    assert Config is not None
    assert LLM is not None


def test_agent_has_no_implicit_tools():
    from repowitness import Agent, LLM

    agent = Agent(llm=LLM.__new__(LLM))

    assert agent.tools == []
    assert agent._tool_by_name == {}


def test_default_agent_tool_lists_are_isolated_per_instance():
    from repowitness import Agent, LLM
    from repowitness.tools.bash import BashTool

    first = Agent(llm=LLM.__new__(LLM))
    first.tools.append(BashTool())
    second = Agent(llm=LLM.__new__(LLM))

    assert second.tools == []
    assert second._tool_by_name == {}


def test_inherited_mutating_and_subagent_tools_remain_explicitly_available():
    from repowitness import Agent, LLM
    from repowitness.tools.agent import AgentTool
    from repowitness.tools.bash import BashTool
    from repowitness.tools.edit import EditFileTool
    from repowitness.tools.write import WriteFileTool

    subagent = AgentTool()
    tools = [BashTool(), WriteFileTool(), EditFileTool(), subagent]
    agent = Agent(llm=LLM.__new__(LLM), tools=tools)

    assert set(agent._tool_by_name) == {"bash", "write_file", "edit_file", "agent"}
    assert subagent._parent_agent is agent


def test_agent_accepts_a_product_specific_system_prompt():
    from repowitness import Agent, LLM

    agent = Agent(llm=LLM.__new__(LLM), tools=[], system="RepoWitness review policy")

    assert agent._full_messages()[0] == {
        "role": "system",
        "content": "RepoWitness review policy",
    }


def test_agent_preserves_corecoder_positional_constructor_compatibility():
    from repowitness import Agent, LLM

    agent = Agent(LLM.__new__(LLM), [], 4096, 7)

    assert agent.context.max_tokens == 4096
    assert agent.max_rounds == 7


def test_repowitness_environment_variables_configure_the_model(monkeypatch):
    from repowitness import Config

    monkeypatch.setenv("REPOWITNESS_MODEL", "review-model")
    monkeypatch.setenv("REPOWITNESS_API_KEY", "review-key")
    monkeypatch.setenv("REPOWITNESS_BASE_URL", "https://models.example/v1")

    config = Config.from_env()

    assert config.model == "review-model"
    assert config.api_key == "review-key"
    assert config.base_url == "https://models.example/v1"


def test_audit_prompts_require_simplified_chinese_report_content():
    from repowitness.prompt import contract_compiler_prompt, review_prompt

    assert "Simplified Chinese" in contract_compiler_prompt()
    assert "Simplified Chinese" in review_prompt(())


def test_contract_prompt_requires_bounded_model_source_selection():
    from repowitness.prompt import contract_compiler_prompt

    prompt = contract_compiler_prompt()

    assert "selected_paths" in prompt
    assert "CLAUDE.md" in prompt
    assert "12" in prompt
