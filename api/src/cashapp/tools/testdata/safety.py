"""Pre-flight refusal: test data is never written to a production pod.

The CLI runs this before a Fusion client is even built, and `generate` / `cleanup` take the same
check as a `guard` hook, so a library caller cannot skip it. s05's `WriteGuard` is the second rail.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit

from cashapp.settings import FusionPodSettings


class ProductionPodRefused(Exception):  # noqa: N818 - name pinned by the plan
    def __init__(self, pod_name: str, reason: str) -> None:
        super().__init__(f"pod '{pod_name}' refused: {reason}")
        self.pod_name = pod_name
        self.reason = reason


def _host(value: str) -> str | None:
    """Lower-cased host without port, path or trailing dot; accepts a URL or a bare host."""
    text = value.strip()
    if not text:
        return None
    parts = urlsplit(text if "://" in text else f"//{text}")
    host = parts.hostname
    return host.rstrip(".") if host else None


def production_hosts(
    all_pods: Mapping[str, FusionPodSettings], extra: Iterable[str] = ()
) -> frozenset[str]:
    """Hosts of every configured production pod plus the extra hosts given on the command line."""
    hosts: set[str] = set()
    for pod in all_pods.values():
        if pod.is_production:
            host = _host(pod.base_url)
            if host is not None:
                hosts.add(host)
    for value in extra:
        host = _host(value)
        if host is not None:
            hosts.add(host)
    return frozenset(hosts)


def assert_non_production(
    pod_name: str,
    pod: FusionPodSettings,
    *,
    all_pods: Mapping[str, FusionPodSettings],
    extra_production_hosts: Iterable[str] = (),
    require_testdata: bool = True,
) -> None:
    if pod.is_production:
        raise ProductionPodRefused(pod_name, "the pod is marked is_production")
    host = _host(pod.base_url)
    if host is None:
        raise ProductionPodRefused(pod_name, "the pod base URL has no host")
    if host in production_hosts(all_pods, extra_production_hosts):
        raise ProductionPodRefused(pod_name, f"host '{host}' is a production host")
    if require_testdata and pod.testdata is None:
        raise ProductionPodRefused(pod_name, "the pod has no testdata block configured")
