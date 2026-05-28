"""Normalize LiteLLM request parameters.

This module validates provider/protocol/model/api_key/base_url and returns
a resolved request object suitable for passing to `litellm.completion()`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.litellm_presets import (
    get_default_base_url,
    get_default_protocol,
    get_provider_prefix,
    get_supported_protocols,
)


@dataclass(frozen=True)
class ResolvedLiteLLMRequest:
    provider_id: str
    protocol: str
    model: str
    api_key: str
    api_base: Optional[str]


def normalize_litellm_request(
    provider_id: str,
    protocol: Optional[str],
    model: str,
    api_key: str,
    base_url: Optional[str] = None,
) -> ResolvedLiteLLMRequest:
    if not api_key:
        raise ValueError("api_key is required")

    if not provider_id:
        raise ValueError("provider_id is required")

    selected_protocol = protocol or get_default_protocol(provider_id)
    if not selected_protocol:
        raise ValueError(f"unknown provider '{provider_id}' or no default protocol available")

    supported = get_supported_protocols(provider_id)
    if selected_protocol not in supported:
        raise ValueError(f"unknown protocol '{selected_protocol}' for provider '{provider_id}'")

    prefix = get_provider_prefix(provider_id, selected_protocol)
    normalized_model = model if model.startswith(prefix) else f"{prefix}{model}"

    api_base = base_url or get_default_base_url(provider_id) or None

    return ResolvedLiteLLMRequest(
        provider_id=provider_id,
        protocol=selected_protocol,
        model=normalized_model,
        api_key=api_key,
        api_base=api_base,
    )
