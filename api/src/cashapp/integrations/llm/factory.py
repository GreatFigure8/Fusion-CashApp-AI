"""Builds the four role clients from settings and the model configuration."""

from cashapp.data.uow import UowFactory
from cashapp.domain.llm_usage import LlmRole
from cashapp.integrations.llm.anthropic_client import AnthropicClientProvider, AnthropicLlmClient
from cashapp.integrations.llm.base import LlmClients
from cashapp.integrations.llm.metered import MeteredLlmClient, UsageRecorder
from cashapp.integrations.llm.oci_cohere_client import OciCohereLlmClient, OciGenAiTransport
from cashapp.services.config import ConfigSnapshot, RuntimeConfig
from cashapp.services.runtime_settings import RuntimeSettings
from cashapp.settings import oci_signer


def build_llm_clients(
    runtime: RuntimeSettings,
    config: RuntimeConfig | ConfigSnapshot | None = None,
    *,
    recorder: UsageRecorder | None = None,
    uow_factory: UowFactory | None = None,
) -> LlmClients:
    """One Anthropic SDK client shared by reader A, the adjudicator and the workhorse, and one
    OCI transport for reader B. Model ids come from ``config.models()``; without a snapshot the
    registry defaults apply. SDK retries are off: the auto-fix engine owns every retry. The API
    key is resolved from Vault at call time (TTL-cached), so rotation needs no restart.

    Every role is wrapped in a ``MeteredLlmClient``. Without a ``recorder`` one is built over
    ``uow_factory`` (or a small engine of its own), so usage rows land in their own transaction.
    """
    if recorder is None:
        # Imported here: the service layer sits above the integration layer.
        from cashapp.services.llm_usage.recorder import build_usage_recorder, default_uow_factory

        recorder = build_usage_recorder(
            uow_factory or default_uow_factory(runtime.settings), config
        )
    snapshot = config if isinstance(config, ConfigSnapshot) else None
    models = (snapshot or ConfigSnapshot({})).models()
    anthropic_config = runtime.anthropic()
    genai = runtime.oci_genai()
    anthropic_client = AnthropicClientProvider(
        lambda: runtime.secret(anthropic_config.api_key_ref), base_url=anthropic_config.base_url
    )
    transport = OciGenAiTransport(genai.endpoint, oci_signer(runtime.settings))
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
                compartment_ocid=genai.compartment_ocid,
                endpoint_ocid=genai.dedicated_endpoint_ocid,
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
