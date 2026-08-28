"""Tool registry.

A tool is `{name, description, parameters (JSON Schema), handler}`. The registry
hands the model provider-neutral definitions and runs the handlers, normalising
whatever comes back into a string the model can read.

Every tool here is read-only by construction — the chat agent answers questions
about the world, it does not change it — so there is no approval gate and no
destructive flag. The one write path the product has (apply an intervention)
stays on its own HTTP endpoint, behind a button a person presses.
"""

import json
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[[dict], Any]
    category: str = "general"

    def definition(self):
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters or {"type": "object", "properties": {}},
        }


@dataclass
class ToolResult:
    ok: bool
    content: str
    data: Any = None
    error: str = ""

    def as_message_content(self):
        return self.content if self.ok else "ERROR: " + self.error


def _coerce(value):
    if isinstance(value, str):
        return value
    if isinstance(value, ToolResult):
        return value.as_message_content()
    try:
        return json.dumps(value, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, name, description, parameters, handler, category="general"):
        self._tools[name] = Tool(name=name, description=description,
                                 parameters=parameters, handler=handler,
                                 category=category)
        return self._tools[name]

    def get(self, name):
        return self._tools.get(name)

    def names(self):
        return sorted(self._tools)

    def all(self):
        return list(self._tools.values())

    def definitions(self):
        return [t.definition() for t in self._tools.values()]

    def detail(self):
        return [
            {"name": t.name, "category": t.category,
             "description": " ".join(t.description.split())[:220]}
            for t in sorted(self._tools.values(), key=lambda t: (t.category, t.name))
        ]

    def execute(self, name, args=None):
        args = args or {}
        if "_json_error" in args:
            return ToolResult(
                ok=False, content="",
                error=("Your tool arguments were not valid JSON (%s). Raw: %s. "
                       "Re-issue the call with arguments that match the schema."
                       % (args["_json_error"], args.get("_raw_args", ""))))
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, content="",
                              error="Unknown tool: %s. Available: %s"
                                    % (name, ", ".join(self.names())))
        try:
            result = tool.handler(args)
            if isinstance(result, ToolResult):
                return result
            return ToolResult(ok=True, content=_coerce(result), data=result)
        except Exception as exc:  # noqa: BLE001 - surfaced back to the model
            return ToolResult(ok=False, content="",
                              error="%s: %s" % (type(exc).__name__, exc))
