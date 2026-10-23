"""Utilisation of the dedicated AI cluster from OCI Monitoring.

Exactly two implementations sit behind ``ClusterMetrics``: ``OciClusterMetrics`` (real) and
``FakeClusterMetrics``. The Monitoring namespace, metric name and dimension key for dedicated AI
clusters are UNVERIFIED against a live tenancy, so the metric is off until ``cluster_metric_query``
is configured. The ledger-derived value (``cohere_utilisation``) always works without it.
"""

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal, Protocol

import oci as _oci  # pyright: ignore[reportMissingTypeStubs]

from cashapp.domain.clock import Clock, SystemClock
from cashapp.settings import Settings

oci: Any = _oci

__all__ = [
    "ClusterMetrics",
    "ClusterUtilisation",
    "FakeClusterMetrics",
    "MonitoringQueryClient",
    "OciClusterMetrics",
    "build_cluster_metrics",
]


@dataclass(frozen=True, slots=True)
class ClusterUtilisation:
    pct: float
    source: Literal["oci_monitoring"]
    metric: str


class ClusterMetrics(Protocol):
    configured: bool

    async def utilisation(self, window_minutes: int) -> ClusterUtilisation | None: ...


class MonitoringQueryClient(Protocol):
    """Seam over ``oci.monitoring.MonitoringClient.summarize_metrics_data`` (synchronous)."""

    def summarize_metrics_data(self, compartment_id: str, details: Any) -> Any:
        """Returns the SDK response; its ``.data`` is a list of ``MetricData``."""
        ...


class OciClusterMetrics:
    def __init__(
        self,
        client: MonitoringQueryClient,
        *,
        compartment_ocid: str,
        cluster_ocid: str | None,
        namespace: str,
        query_template: str | None,
        clock: Clock | None = None,
    ) -> None:
        self._client = client
        self._compartment = compartment_ocid
        self._cluster = cluster_ocid
        self._namespace = namespace
        self._query_template = query_template
        self._clock: Clock = clock if clock is not None else SystemClock()
        self.configured = bool(cluster_ocid and query_template)

    async def utilisation(self, window_minutes: int) -> ClusterUtilisation | None:
        """Mean of the latest aggregated datapoint of each returned series, or ``None``."""
        if not (self.configured and self._cluster and self._query_template):
            return None
        query = self._query_template.format(cluster_ocid=self._cluster)
        end = self._clock.now()
        details = oci.monitoring.models.SummarizeMetricsDataDetails(
            namespace=self._namespace,
            query=query,
            start_time=end - timedelta(minutes=window_minutes),
            end_time=end,
        )
        response = await asyncio.to_thread(
            self._client.summarize_metrics_data, self._compartment, details
        )
        latest: list[float] = []
        series_list: list[Any] = list(response.data or [])
        for series in series_list:
            points: list[Any] = sorted(
                series.aggregated_datapoints or [], key=lambda p: p.timestamp
            )
            if points:
                latest.append(float(points[-1].value))
        if not latest:
            return None
        return ClusterUtilisation(
            pct=round(sum(latest) / len(latest), 1), source="oci_monitoring", metric=query
        )


class FakeClusterMetrics:
    """The test fake: returns a percentage, raises the given exception, or returns nothing."""

    def __init__(self, result: float | Exception | None = None) -> None:
        self._result = result
        self.configured = True

    async def utilisation(self, window_minutes: int) -> ClusterUtilisation | None:
        if isinstance(self._result, Exception):
            raise self._result
        if self._result is None:
            return None
        return ClusterUtilisation(pct=self._result, source="oci_monitoring", metric="fake")


def _monitoring_client() -> Any:
    """Resource principal, then instance principal, then ``~/.oci/config`` (the s08 order)."""
    if os.environ.get("OCI_RESOURCE_PRINCIPAL_VERSION"):
        return oci.monitoring.MonitoringClient(
            {}, signer=oci.auth.signers.get_resource_principals_signer()
        )
    try:
        return oci.monitoring.MonitoringClient(
            {}, signer=oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        )
    except Exception:
        # Not on OCI compute: fall back to the developer's config file.
        return oci.monitoring.MonitoringClient(oci.config.from_file())


_ClientFactory = Callable[[], MonitoringQueryClient]


def build_cluster_metrics(
    settings: Settings, *, client_factory: _ClientFactory = _monitoring_client
) -> ClusterMetrics | None:
    """``None`` unless the cluster OCID and the metric query are both configured."""
    genai = settings.oci_genai
    if not (genai.dedicated_cluster_ocid and genai.cluster_metric_query):
        return None
    return OciClusterMetrics(
        client_factory(),
        compartment_ocid=genai.compartment_ocid,
        cluster_ocid=genai.dedicated_cluster_ocid,
        namespace=genai.cluster_metric_namespace,
        query_template=genai.cluster_metric_query,
    )
