from __future__ import annotations

from agents.base import Agent
from agents.coding import CodingAgent
from agents.general import GeneralAgent
from agents.math_agent import MathAgent
from agents.validation import ValidationAgent
from llm.base import LLMClient


def build_agents(llm: LLMClient, log=None) -> dict[str, Agent]:
    return {
        "general": GeneralAgent(llm, log),
        "coding": CodingAgent(llm, log),
        "math": MathAgent(llm, log),
        "validation": ValidationAgent(llm, log),
    }
