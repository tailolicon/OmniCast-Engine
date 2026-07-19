"""Fallback LLM clients for dry-run and Ollama."""

from __future__ import annotations

from omnicast.llm import LLMResponse


def _build_stub(schema: type) -> object:
    """Build a stub instance of a Pydantic model with sensible defaults for required fields."""
    try:
        # Try default construction first
        return schema()
    except Exception:
        pass

    # Introspect required fields and provide type-appropriate defaults
    try:
        fields = schema.model_fields  # Pydantic v2
    except AttributeError:
        try:
            fields = schema.__fields__  # Pydantic v1
        except AttributeError:
            return object.__new__(schema)

    kwargs: dict = {}
    for name, field_info in fields.items():
        # Check if field has a default
        try:
            # Pydantic v2
            if field_info.is_required():
                annotation = field_info.annotation
                kwargs[name] = _default_for_type(annotation)
        except AttributeError:
            # Pydantic v1
            if field_info.required:
                outer_type = getattr(field_info, "outer_type_", None)
                kwargs[name] = _default_for_type(outer_type)

    try:
        return schema.model_construct(**kwargs)  # Pydantic v2 - skips validation
    except AttributeError:
        return schema(**kwargs)  # Pydantic v1


def _default_for_type(annotation: type | None) -> object:
    """Return a sensible default for a given type annotation."""
    if annotation is None:
        return None
    origin = getattr(annotation, "__origin__", None)
    # Handle Optional / Union
    if origin is not None:
        import types
        import typing
        args = getattr(annotation, "__args__", ())
        # Pick first non-None arg
        for arg in args:
            if arg is not type(None):
                return _default_for_type(arg)
        return None
    if annotation is str or annotation == "str":
        return ""
    if annotation is int or annotation == "int":
        return 0
    if annotation is float or annotation == "float":
        return 0.0
    if annotation is bool or annotation == "bool":
        return False
    if annotation is list or annotation == "list":
        return []
    if annotation is dict or annotation == "dict":
        return {}
    # Try constructing it
    try:
        return annotation()
    except Exception:
        return None


class DryRunClient:
    """Returns deterministic mock responses. For testing and dry_run mode."""

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Return mock LLMResponse with content='[DRY RUN] ...'"""
        return LLMResponse(
            content="[DRY RUN] Mock response for testing",
            model="claude-sonnet-4-6",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            stop_reason="end_turn",
        )

    async def complete_structured(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        output_schema: type,
        max_tokens: int | None = None,
        temperature: float = 0.3,
    ) -> tuple[LLMResponse, object]:
        """Return mock response + stub instance of output_schema."""
        response = LLMResponse(
            content="[DRY RUN] Mock structured response",
            model="claude-sonnet-4-6",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            stop_reason="end_turn",
        )
        parsed = _build_stub(output_schema)
        return response, parsed
