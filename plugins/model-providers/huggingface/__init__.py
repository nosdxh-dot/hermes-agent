"""Hugging Face Inference Providers router — 20+ open models via unified endpoint."""

import logging

from providers import register_provider
from providers.base import ProviderProfile

logger = logging.getLogger(__name__)

_CACHE: list[str] | None = None


class HuggingFaceProfile(ProviderProfile):
    """HuggingFace Inference Providers router.

    Routes to 20+ open models (Qwen, DeepSeek, Kimi, MiniMax, GLM, MiMo, …)
    through a unified OpenAI-compatible endpoint at router.huggingface.co.
    Each request is dispatched to the cheapest available backend (Cerebras,
    Together AI, Fireworks, SambaNova, …) that hosts the requested model —
    you pay provider rates with no markup, billed to your HF credits.

    Token requirements: create a token at huggingface.co/settings/tokens
    with the "Make calls to Inference Providers" permission enabled.
    """

    def fetch_models(
        self,
        *,
        api_key: str | None = None,
        timeout: float = 8.0,
    ) -> list[str] | None:
        """Fetch live model catalog from the HF inference router.

        Results are cached for the process lifetime to avoid repeated round
        trips — the HF router may rate-limit frequent /models probes.
        """
        global _CACHE  # noqa: PLW0603
        if _CACHE is not None:
            return _CACHE
        result = super().fetch_models(api_key=api_key, timeout=timeout)
        if result is not None:
            _CACHE = result
        return result


huggingface = HuggingFaceProfile(
    name="huggingface",
    aliases=("hf", "hugging-face", "huggingface-hub"),
    env_vars=("HF_TOKEN",),
    display_name="HuggingFace",
    description="HuggingFace Inference Providers — 20+ open models via unified router",
    signup_url="https://huggingface.co/settings/tokens",
    base_url="https://router.huggingface.co/v1",
    models_url="https://router.huggingface.co/v1/models",
    fallback_models=(
        "moonshotai/Kimi-K2.5",
        "Qwen/Qwen3.5-397B-A17B",
        "deepseek-ai/DeepSeek-V3.2",
        "MiniMaxAI/MiniMax-M2.5",
        "zai-org/GLM-5",
        "Qwen/Qwen3.5-35B-A3B",
        "XiaomiMiMo/MiMo-V2-Flash",
        "moonshotai/Kimi-K2-Thinking",
        "moonshotai/Kimi-K2.6",
    ),
)

register_provider(huggingface)
