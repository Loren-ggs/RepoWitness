"""RepoWitness tool registry.

Capabilities are granted explicitly per agent. The inherited CoreCoder tools
remain importable, but none are registered implicitly.
"""

from .agent import AgentTool as AgentTool
from .bash import BashTool as BashTool
from .edit import EditFileTool as EditFileTool
from .glob_tool import GlobTool as GlobTool
from .grep import GrepTool as GrepTool
from .read import ReadFileTool as ReadFileTool
from .write import WriteFileTool as WriteFileTool

ALL_TOOLS = []


def get_tool(name: str):
    """Look up a tool by name."""
    for t in ALL_TOOLS:
        if t.name == name:
            return t
    return None


def build_contract_tools(catalog, collector):
    from .contract_sources import ContractSourcesTool
    from .submit_rules import SubmitRulesTool

    return [
        ContractSourcesTool(catalog),
        SubmitRulesTool(collector),
    ]


def build_review_tools(
    repository,
    evidence,
    collector,
    *,
    include_untracked=True,
):
    from .changed_files import ChangedFilesTool
    from .diff import DiffTool
    from .read import ReadRepositoryFileTool
    from .submit_assessments import SubmitAssessmentsTool

    return [
        ChangedFilesTool(repository, include_untracked=include_untracked),
        DiffTool(repository, evidence),
        ReadRepositoryFileTool(repository, evidence),
        SubmitAssessmentsTool(collector),
    ]
