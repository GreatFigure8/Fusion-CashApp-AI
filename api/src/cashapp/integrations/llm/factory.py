"""Builds the four role clients from settings and the model configuration."""

import anthropic

from cashapp.integrations.llm.anthropic_client import AnthropicLlmClient
from cashapp.integrations.llm.base import LlmClients
from cashapp.integrations.llm.oci_cohere_client import OciCohereLlmClient, OciGenAiTransport
from cashapp.services.config import ConfigSnapshot
from cashapp.settings import Settings


def build_llm_clients(settings: Settings, config: ConfigSnapshot | None = None) -> LlmClients:
    """One Anthropic SDK client shared by reader A, the adjudicator and the workhorse, and one
    OCI transport for reader B. Model ids come from ``config.models()``; without a snapshot the
    registry defaults apply. SDK retries are off: the auto-fix engine owns every retry.
    """
    models = (config or ConfigSnapshot({})).models()
    anthropic_client = anthropic.AsyncAnthropic(
        api_key=settings.anthropic.api_key.get_secret_value(),
        base_url=settings.anthropic.base_url,
        max_retries=0,
    )
    transport = OciGenAiTransport(settings.oci_genai.endpoint)
    return LlmClients(
        reader_a=AnthropicLlmClient(anthropic_client, models.reader_a.model_id),
        reader_b=OciCohereLlmClient(
            transport,
            model_id=models.reader_b.model_id,
            compartment_ocid=settings.oci_genai.compartment_ocid,
            endpoint_ocid=settings.oci_genai.dedicated_endpoint_ocid,
        ),
        adjudicator=AnthropicLlmClient(anthropic_client, models.adjudicator.model_id),
        workhorse=AnthropicLlmClient(anthropic_client, models.workhorse.model_id),
    )
