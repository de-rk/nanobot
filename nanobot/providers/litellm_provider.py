"""LLM provider using OpenAI SDK for multi-provider support."""

import json_repair
from typing import Any

from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.registry import find_by_model, find_gateway


class LiteLLMProvider(LLMProvider):
    """
    LLM provider backed by the OpenAI SDK.

    All supported providers expose OpenAI-compatible APIs, so we point the SDK
    at each provider's own endpoint rather than routing through LiteLLM.
    Provider metadata (base URLs, overrides) lives in providers/registry.py.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        extra_headers: dict[str, str] | None = None,
        provider_name: str | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}
        self._gateway = find_gateway(provider_name, api_key, api_base)

    def _get_base_url(self, model: str) -> str | None:
        """Return the OpenAI-compatible base URL for this request."""
        if self.api_base:
            return self.api_base
        if self._gateway:
            return self._gateway.default_api_base or None
        spec = find_by_model(model)
        return (spec.default_api_base or None) if spec else None

    def _resolve_model(self, model: str) -> str:
        """
        Strip routing prefixes so the bare model name reaches the provider endpoint.

        Gateways with strip_model_prefix (e.g. AiHubMix) want just the model name.
        OpenRouter and direct providers receive the model as-is or stripped of
        any provider/ namespace that was added for routing.
        """
        if self._gateway:
            if self._gateway.strip_model_prefix and "/" in model:
                return model.split("/")[-1]
            return model
        # Custom api_base: user controls the endpoint, pass model name as-is
        if self.api_base:
            return model
        # Direct registry provider: strip routing namespace (e.g. "anthropic/claude-3" → "claude-3")
        if "/" in model:
            return model.split("/")[-1]
        return model

    def _apply_model_overrides(self, model: str, kwargs: dict[str, Any]) -> None:
        """Apply per-model parameter overrides from the registry (e.g. kimi-k2.5 temperature)."""
        model_lower = model.lower()
        spec = find_by_model(model)
        if spec:
            for pattern, overrides in spec.model_overrides:
                if pattern in model_lower:
                    kwargs.update(overrides)
                    return

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        raw_model = model or self.default_model
        resolved = self._resolve_model(raw_model)
        base_url = self._get_base_url(raw_model)

        kwargs: dict[str, Any] = {
            "model": resolved,
            "messages": messages,
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }

        self._apply_model_overrides(resolved, kwargs)

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        client = AsyncOpenAI(
            api_key=self.api_key or "no-key",
            base_url=base_url,
            default_headers=self.extra_headers or None,
        )

        try:
            response = await client.chat.completions.create(**kwargs)
            return self._parse_response(response)
        except Exception as e:
            return LLMResponse(
                content=f"Error calling LLM: {str(e)}",
                finish_reason="error",
            )

    def _parse_response(self, response: Any) -> LLMResponse:
        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                args = tc.function.arguments
                if isinstance(args, str):
                    args = json_repair.loads(args)
                tool_calls.append(ToolCallRequest(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
            reasoning_content=getattr(message, "reasoning_content", None),
        )

    def get_default_model(self) -> str:
        return self.default_model
