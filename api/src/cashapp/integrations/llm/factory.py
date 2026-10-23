"""Builds the four role clients from settings and the model configuration."""

import anthropic

from cashapp.data.uow import UowFactory
from cashapp.domain.llm_usage import LlmRole
from cashapp.integrations.llm.anthropic_client import AnthropicLlmClient
from cashapp.integrations.llm.base import LlmClients
from cashapp.integrations.llm.metered import MeteredLlmClient, UsageRecorder
from cashapp.integrations.llm.oci_cohere_client import OciCohereLlmClient, OciGenAiTransport
from cashapp.services.config import ConfigSnapshot, RuntimeConfig
from cashapp.settings import Settings


def build_llm_clients(
    settings: Settings,
    config: RuntimeConfig | ConfigSnapshot | None = None,
    *,
    recorder: UsageRecorder | None = None,
    uow_factory: UowFactory | None = None,
) -> LlmClients:
    """One Anthropic SDK client shared by reader A, the adjudicator and the workhorse, and one
    OCI transport for reader B. Model ids come from ``config.models()``; without a snapshot the
    registry defaults apply. SDK retries are off: the auto-fix engine owns every retry.

    Every role is wrapped in a ``MeteredLlmClient``. Without a ``recorder`` one is built over
    ``uow_factory`` (or a small engine of its own), so usage rows land in their own transaction.
    """
    if recorder is None:
        # Imported here: the service layer sits above the integration layer.
        from cashapp.services.llm_usage.recorder import build_usage_recorder, default_uow_factory

        recorder = build_usage_recorder(uow_factory or default_uow_factory(settings), config)
    snapshot = config if isinstance(config, ConfigSnapshot) else None
    models = (snapshot or ConfigSnapshot({})).models()
    anthropic_client = anthropic.AsyncAnthropic(
        api_key=settings.anthropic.api_key.get_secret_value(),
        base_url=settings.anthropic.base_url,
        max_retries=0,
    )
    transport = OciGenAiTransport(settings.oci_genai.endpoint)
    return LlmClients(
        reader_a=MeteredLlmClient(
            AnthropicLlmClient(anthropic_client, models.reader_a.model_id),
            LlmRole.READER_A,
            recorder,
        ),
        reader_b=MeteredLlmClient(
            OciCohereLlmClient(
                transport,
                model_id=models.reader_b.model_id,
                compartment_ocid=settings.oci_genai.compartment_ocid,
                endpoint_ocid=settings.oci_genai.dedicated_endpoint_ocid,
            ),
            LlmRole.READER_B,
            recorder,
        ),
        adjudicator=MeteredLlmClient(
            AnthropicLlmClient(anthropic_client, models.adjudicator.model_id),
            LlmRole.ADJUDICATOR,
            recorder,
        ),
        workhorse=MeteredLlmClient(
            AnthropicLlmClient(anthropic_client, models.workhorse.model_id),
            LlmRole.WORKHORSE,
            recorder,
        ),
    )
