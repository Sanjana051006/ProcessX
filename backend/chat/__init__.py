"""The ProcessX conversational agent.

A small, self-contained agentic loop: one provider (Groq), a tool registry, and
a controller that runs `model -> tool calls -> model` until the model answers.
Ported down from the Namma Agent architecture and cut to the one provider and
the one domain this project needs.
"""
