"""Typed JSON out of any provider: enforce a schema where the API can, validate always.

OpenAI and Claude both enforce a JSON schema server-side. Local models behind an
OpenAI-compatible server may not, so every reply is validated with Pydantic and gets one
repair attempt with the validation error before we give up.
"""

import copy
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from agentic_rag.llm import LLM, Effort, Usage

_STRIP = ("default", "title", "discriminator")


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic schema -> the strict subset both providers accept.

    Every object closes with additionalProperties=false and lists all its properties as
    required (optional fields are nullable unions instead); oneOf becomes anyOf; const
    becomes a one-value enum; defaults and titles are dropped.
    """

    def fix(node: Any) -> Any:
        if isinstance(node, list):
            return [fix(item) for item in node]
        if not isinstance(node, dict):
            return node
        out = {key: fix(value) for key, value in node.items() if key not in _STRIP}
        if "oneOf" in out:
            out["anyOf"] = out.pop("oneOf")
        if "const" in out:
            out["enum"] = [out.pop("const")]
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])
        return out

    result: dict[str, Any] = fix(copy.deepcopy(model.model_json_schema()))
    return result


def extract_json(text: str) -> str:
    """Tolerate ```json fences or prose around the object (some local models add them)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


def complete_structured[T: BaseModel](
    llm: LLM,
    *,
    model: str,
    system: str,
    user: str,
    schema: type[T],
    effort: Effort | None = None,
    max_tokens: int = 8000,
) -> tuple[T, Usage]:
    json_schema = strict_schema(schema)
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    usage = Usage()
    for attempt in range(2):
        completion = llm.complete(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            effort=effort,
            json_schema=json_schema,
        )
        usage = usage + completion.usage
        try:
            return schema.model_validate_json(extract_json(completion.text)), usage
        except ValidationError as error:
            if attempt == 1:
                raise
            messages += [
                {"role": "assistant", "content": completion.text},
                {
                    "role": "user",
                    "content": f"That JSON was invalid:\n{error}\nReply with corrected JSON only.",
                },
            ]
    raise AssertionError("unreachable")
