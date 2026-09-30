# Astra Resolve v2.5 — Hackathon Build Notes

## Product pitch

**Astra Resolve — Speak the problem. Astra resolves it.**

Astra turns a natural voice description of a digital problem into a mission: clarify missing details, investigate with real tools, route work through the QuantumX AOB, and return an evidence-backed result.

## Demo path

1. Start the AssemblyAI Voice Agent session.
2. Say: `Check https://example.com and tell me whether it is healthy.`
3. The Voice Agent creates a tool call for `astra_resolve`.
4. Astra's AOB routes the task to `operator_agent`.
5. The operator performs a real public HTTP diagnostic.
6. Mission telemetry shows the agent/tool work and the voice agent speaks the result.
7. Interrupt Astra while it is speaking to demonstrate barge-in.
8. Say another instruction; the same session continues naturally.

## What the UI demonstrates

- premium AI command-center visual hierarchy
- live voice state and audio visualizer
- live transcript
- mission phases: Listen -> Understand -> Investigate -> Resolve
- active allowlisted tools
- agent/event telemetry
- persistent mission list

## Architecture

```text
Browser
  |
  | short-lived token
  v
AssemblyAI Voice Agent API
  |\
  | \-- reply.audio / transcripts / tool.call
  |
  +---- astra_resolve tool ----> FastAPI /api/voice/resolve
                                   |
                                   v
                                Astra AOB
                                   |
                         +---------+---------+
                         |                   |
                   web_agent          operator_agent
                         |                   |
                  live web search      public URL check
                         |                   |
                         +---------+---------+
                                   |
                                   v
                              tool result
                                   |
                                   v
                         AssemblyAI voice reply
```
