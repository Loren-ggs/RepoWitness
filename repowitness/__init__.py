"""RepoWitness - evidence-backed review against repository rules."""

__version__ = "0.4.0"

from repowitness.agent import Agent
from repowitness.audit import AuditEngine
from repowitness.llm import LLM
from repowitness.config import Config
from repowitness.domain import AuditReport, AuditRequest
from repowitness.tools import ALL_TOOLS

__all__ = [
    "Agent",
    "AuditEngine",
    "AuditReport",
    "AuditRequest",
    "LLM",
    "Config",
    "ALL_TOOLS",
    "__version__",
]
