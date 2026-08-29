"""The ProcessX conversational agent.

A small, self-contained agentic loop: one provider (OpenCode Zen), a tool
registry, and a controller that runs `model -> tool calls -> model` until the
model answers. Every turn is also published to the event bus, so the analyst's
tool calls sit in the same timeline as the simulator's and the agent's.
"""
