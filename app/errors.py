"""Error taxonomy.

Every failure belongs to one layer and one kind, so it can be handled at the
right place instead of crashing the whole request.

  unknown / unclear input  ->  NOT an error (handled by clarification/fallback)
  everything below         ->  a real error with a layer
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Layer = Literal["input", "stt", "network", "llm", "agent", "tool", "validation", "output", "tts", "render", "system"]


class ErrorInfo(BaseModel):
    kind: str
    layer: Layer
    message: str
    recoverable: bool = True


class NexusError(Exception):
    kind = "system_error"
    layer: Layer = "system"
    recoverable = True

    def __init__(self, message: str, *, kind: str | None = None, layer: Layer | None = None, recoverable: bool | None = None):
        super().__init__(message)
        self.message = message
        if kind:
            self.kind = kind
        if layer:
            self.layer = layer
        if recoverable is not None:
            self.recoverable = recoverable

    def info(self) -> ErrorInfo:
        return ErrorInfo(kind=self.kind, layer=self.layer, message=self.message, recoverable=self.recoverable)


class MicrophoneError(NexusError):
    kind, layer = "microphone_failure", "input"


class STTError(NexusError):
    kind, layer = "stt_failure", "stt"


class NetworkError(NexusError):
    kind, layer = "network_failure", "network"


class APIError(NexusError):
    kind, layer = "api_failure", "network"


class LLMError(NexusError):
    kind, layer = "llm_failure", "llm"


class LLMUnavailable(LLMError):
    """No provider is configured / all providers failed."""
    kind = "llm_unavailable"


class LLMRateLimited(LLMError):
    kind = "llm_rate_limited"


class AgentError(NexusError):
    kind, layer = "agent_failure", "agent"


class AgentTimeout(AgentError):
    kind = "agent_timeout"


class ToolError(NexusError):
    kind, layer = "tool_failure", "tool"


class InvalidAgentOutput(NexusError):
    kind, layer = "invalid_agent_output", "validation"


class ValidationFailure(NexusError):
    kind, layer = "validation_failure", "validation"


class UnsupportedRequest(NexusError):
    kind, layer = "unsupported_request", "input"


class TTSError(NexusError):
    kind, layer = "tts_failure", "tts"


class RenderError(NexusError):
    kind, layer = "rendering_failure", "render"
