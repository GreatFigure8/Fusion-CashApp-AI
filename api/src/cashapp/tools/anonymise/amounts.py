"""Amount scaling that keeps the relationships the matcher depends on.

Amounts are scaled per relationship *cluster*, not per customer: a pay-on-behalf receipt and the
invoices it pays must share one factor or their equality is lost. Within a cluster the mapping is:

1. zero stays zero and the sign is kept (credit memo balances stay negative);
2. memo: the same absolute amount (and currency) always maps to the same output, so a line equals
   its invoice balance and a receipt equals its payment header;
3. sums first: a payment header that equals the sum of its lines is the sum of the mapped lines;
4. small residuals: an amount within ``RESIDUAL_BAND`` of an already-mapped one keeps its absolute
   difference exactly (bank fees, short pays, tolerances);
5. otherwise ``to_money(|x| * factor)``;
6. INR: the paise are carried over unchanged and only the whole-rupee part is scaled, so a
   whole-rupee amount stays whole and a non-whole one never lands on a whole rupee, and sums of
   such amounts keep that property.

Order matters for 2 to 4, so the caller registers every amount first (``request``) and the mapper
resolves them all in one pinned, input-order-independent sequence.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import IntEnum
from typing import Final

from cashapp.domain.money import money_eq, to_money

RESIDUAL_BAND: Final = Decimal("5.00")
FACTOR_LOW: Final = 70
FACTOR_SPAN: Final = 61
IDENTITY_LOW: Final = Decimal("0.97")
IDENTITY_HIGH: Final = Decimal("1.03")
INR: Final = "INR"
_WHOLE: Final = Decimal(1)
_ZERO: Final = Decimal(0)


class AmountGroup(IntEnum):
    """Processing order inside a cluster."""

    HEADER = 1
    LINE = 2
    TRANSACTION = 3
    RECEIPT = 4
    APPLICATION = 5
    LABEL = 6


class ClusterIndex:
    """Union-find over string keys."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def add(self, key: str) -> None:
        self._parent.setdefault(key, key)

    def find(self, key: str) -> str:
        self.add(key)
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[key] != root:
            self._parent[key], key = root, self._parent[key]
        return root

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            low, high = sorted((a, b))
            self._parent[high] = low

    def groups(self) -> dict[str, list[str]]:
        """Root to sorted members."""
        result: dict[str, list[str]] = {}
        for key in self._parent:
            result.setdefault(self.find(key), []).append(key)
        return {root: sorted(members) for root, members in result.items()}

    def __len__(self) -> int:
        return len(self.groups())


@dataclass(frozen=True)
class _Request:
    handle: str
    member: str
    value: Decimal
    currency: str
    group: AmountGroup
    sort_key: str


@dataclass
class _Cluster:
    key: str
    factor: Decimal
    memo: dict[tuple[str, Decimal], Decimal]


class AmountMapper:
    def __init__(
        self,
        index: ClusterIndex,
        *,
        label: Callable[[str], str],
        digest: Callable[[str, str], int],
    ) -> None:
        self._index = index
        self._label = label
        self._digest = digest
        self._requests: dict[str, _Request] = {}
        self._sums: list[tuple[str, tuple[str, ...]]] = []
        self._out: dict[str, Decimal] = {}

    # --- registration ----------------------------------------------------------------------------

    def request(
        self,
        handle: str,
        member: str,
        value: Decimal,
        currency: str,
        group: AmountGroup,
        sort_key: str,
    ) -> None:
        if handle in self._requests:
            raise ValueError("duplicate amount handle")
        self._index.add(member)
        self._requests[handle] = _Request(handle, member, value, currency, group, sort_key)

    def declare_sum(self, header: str, lines: Sequence[str]) -> None:
        """Ask for ``header`` to be the sum of the mapped ``lines`` (if it was in the source)."""
        self._sums.append((header, tuple(lines)))

    # --- resolution ------------------------------------------------------------------------------

    def cluster_key(self, root: str) -> str:
        return min(self._label(member) for member in self._index.groups()[root])

    def factor_for(self, cluster_key: str) -> Decimal:
        attempt = 0
        while True:
            seed = cluster_key if attempt == 0 else f"{cluster_key}#{attempt}"
            factor = Decimal(FACTOR_LOW + self._digest("factor", seed) % FACTOR_SPAN) / 100
            if not IDENTITY_LOW <= factor <= IDENTITY_HIGH:
                return factor
            attempt += 1

    def resolve(self) -> None:
        by_root: dict[str, list[_Request]] = {}
        for request in self._requests.values():
            by_root.setdefault(self._index.find(request.member), []).append(request)
        sums_by_root: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
        for header, lines in self._sums:
            if header in self._requests:
                root = self._index.find(self._requests[header].member)
                sums_by_root.setdefault(root, []).append((header, lines))
        groups = self._index.groups()
        for root in sorted(by_root, key=lambda r: min(self._label(m) for m in groups[r])):
            key = min(self._label(member) for member in groups[root])
            cluster = _Cluster(key, self.factor_for(key), {})
            self._resolve_cluster(cluster, by_root[root], sums_by_root.get(root, []))

    def _resolve_cluster(
        self,
        cluster: _Cluster,
        requests: list[_Request],
        sums: list[tuple[str, tuple[str, ...]]],
    ) -> None:
        for header_handle, line_handles in sorted(
            sums, key=lambda s: (self._requests[s[0]].sort_key, s[0])
        ):
            header = self._requests[header_handle]
            lines = [self._requests[h] for h in line_handles if h in self._requests]
            if not lines or not money_eq(header.value, sum((x.value for x in lines), _ZERO)):
                continue
            for line in sorted(lines, key=lambda r: (r.sort_key, r.handle)):
                self._map_single(cluster, line)
            total = sum((self._out[x.handle] for x in lines), _ZERO)
            self._out[header.handle] = total
            if total > 0:
                cluster.memo.setdefault((header.currency, abs(header.value)), total)
        for request in sorted(requests, key=lambda r: (r.group, r.sort_key, r.handle)):
            self._map_single(cluster, request)

    def _map_single(self, cluster: _Cluster, request: _Request) -> None:
        if request.handle in self._out:
            return
        value = request.value
        if value == 0:
            self._out[request.handle] = to_money(0)
            return
        magnitude = abs(value)
        memo_key = (request.currency, magnitude)
        mapped = cluster.memo.get(memo_key)
        if mapped is None:
            mapped = self._residual(cluster, request.currency, magnitude)
        if mapped is None:
            mapped = self._scaled(cluster.factor, request.currency, magnitude)
        cluster.memo[memo_key] = mapped
        self._out[request.handle] = mapped if value > 0 else -mapped

    @staticmethod
    def _residual(cluster: _Cluster, currency: str, magnitude: Decimal) -> Decimal | None:
        best: tuple[Decimal, Decimal] | None = None
        for cur, other in cluster.memo:
            if cur != currency or other == magnitude:
                continue
            gap = abs(magnitude - other)
            if gap > RESIDUAL_BAND:
                continue
            if best is None or (gap, other) < (best[0], best[1]):
                best = (gap, other)
        if best is None:
            return None
        other = best[1]
        candidate = cluster.memo[(currency, other)] + (magnitude - other)
        return to_money(candidate) if candidate > 0 else None

    @staticmethod
    def _scaled(factor: Decimal, currency: str, magnitude: Decimal) -> Decimal:
        if currency != INR:
            return to_money(magnitude * factor)
        whole = magnitude.to_integral_value(rounding=ROUND_FLOOR)
        paise = magnitude - whole
        scaled = (whole * factor).quantize(_WHOLE, rounding=ROUND_HALF_UP)
        return to_money(scaled + paise)

    # --- results ---------------------------------------------------------------------------------

    def mapped(self, handle: str) -> Decimal:
        return self._out[handle]

    def mapped_optional(self, handle: str) -> Decimal | None:
        return self._out.get(handle)
