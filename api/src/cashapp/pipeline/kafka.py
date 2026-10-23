# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false
"""``EventBus`` on OCI Streaming through its Kafka-compatible endpoint (SASL_SSL / PLAIN)."""

import asyncio
import logging
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient
from pydantic import SecretStr

from cashapp.domain.stages import Stage
from cashapp.pipeline.bus import CommitTracker as _CommitTracker
from cashapp.pipeline.bus import Delivery
from cashapp.pipeline.events import TopicNamer, default_namer
from cashapp.services.runtime_settings import StreamingConfig

logger = logging.getLogger(__name__)

_MAX_POLL_RECORDS = 10


class KafkaEventBus:
    """Producer per bus, one consumer per ``subscribe`` call.

    The consumer group is used exactly as given (``streaming.consumer_group``): the bus
    never derives, suffixes or resets it. Offsets are committed only when a delivery's
    ``commit()`` is called, and only up to the highest contiguous completed offset.
    """

    def __init__(
        self,
        streaming: StreamingConfig,
        secret: Callable[[str], Awaitable[SecretStr]],
        *,
        namer: TopicNamer | None = None,
        client_id: str = "cashapp",
    ) -> None:
        self._streaming = streaming
        self._secret = secret
        self._namer = namer
        self._client_id = client_id
        self._producer: Any = None
        self._producer_lock = asyncio.Lock()

    async def _auth(self) -> dict[str, Any]:
        """Connection arguments; the SASL password is resolved from Vault each time a client is
        built, so a rotated token is picked up on the next connect."""
        password = await self._secret(self._streaming.sasl_password_ref)
        return {
            "bootstrap_servers": self._streaming.bootstrap_servers,
            "security_protocol": "SASL_SSL",
            "sasl_mechanism": "PLAIN",
            "sasl_plain_username": self._streaming.sasl_username,
            "sasl_plain_password": password.get_secret_value(),
            "ssl_context": ssl.create_default_context(),
            "client_id": self._client_id,
        }

    def _topic_namer(self) -> TopicNamer:
        return self._namer if self._namer is not None else default_namer()

    async def _started_producer(self) -> Any:
        async with self._producer_lock:
            if self._producer is None:
                producer = AIOKafkaProducer(
                    **await self._auth(), acks="all", enable_idempotence=False
                )
                await producer.start()
                self._producer = producer
            return self._producer

    async def publish(
        self,
        topic: str,
        key: str | None,
        payload: bytes,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        producer = await self._started_producer()
        record = await producer.send_and_wait(
            topic,
            value=payload,
            key=key.encode("utf-8") if key is not None else None,
            headers=[(name, value.encode("utf-8")) for name, value in (headers or {}).items()],
        )
        logger.debug(
            "published",
            extra={"topic": topic, "partition": record.partition, "offset": record.offset},
        )

    async def subscribe(self, topics: Sequence[str], group: str) -> AsyncIterator[Delivery]:
        consumer: Any = AIOKafkaConsumer(
            *topics,
            group_id=group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            max_poll_records=_MAX_POLL_RECORDS,
            **await self._auth(),
        )
        await consumer.start()
        trackers: dict[str, _CommitTracker] = {topic: _CommitTracker() for topic in topics}
        commit_lock = asyncio.Lock()

        def make_delivery(message: Any) -> Delivery:
            tracker = trackers.setdefault(message.topic, _CommitTracker())
            tracker.start(message.partition, message.offset)

            async def commit() -> None:
                async with commit_lock:
                    watermark = tracker.complete(message.partition, message.offset)
                    if watermark is not None:
                        await consumer.commit(
                            {TopicPartition(message.topic, message.partition): watermark}
                        )

            headers = {
                name: value.decode("utf-8", errors="replace")
                for name, value in (message.headers or ())
            }
            key = message.key.decode("utf-8") if message.key is not None else None
            logger.debug(
                "delivered",
                extra={
                    "topic": message.topic,
                    "partition": message.partition,
                    "offset": message.offset,
                },
            )
            return Delivery(
                message.topic,
                message.partition,
                message.offset,
                key,
                message.value,
                headers,
                commit,
            )

        try:
            async for message in consumer:
                yield make_delivery(message)
        finally:
            await consumer.stop()

    async def _offsets(self, topic: str) -> tuple[list[Any], dict[Any, int], dict[Any, int]]:
        """Partitions, end offsets and beginning offsets of ``topic`` (empty when it has none)."""
        consumer: Any = AIOKafkaConsumer(**await self._auth())
        await consumer.start()
        try:
            partitions = consumer.partitions_for_topic(topic)
            if not partitions:
                return [], {}, {}
            tps = [TopicPartition(topic, partition) for partition in sorted(partitions)]
            ends = await consumer.end_offsets(tps)
            begins = await consumer.beginning_offsets(tps)
            return tps, dict(ends), dict(begins)
        finally:
            await consumer.stop()

    async def consumer_lag(self, topic: str) -> int:
        try:
            tps, ends, begins = await self._offsets(topic)
            if not tps:
                return -1
            admin: Any = AIOKafkaAdminClient(**await self._auth())
            await admin.start()
            try:
                committed = await admin.list_consumer_group_offsets(self._streaming.consumer_group)
            finally:
                await admin.close()
            lag = 0
            for tp in tps:
                meta = committed.get(tp)
                position = meta.offset if meta is not None and meta.offset >= 0 else begins[tp]
                lag += max(ends[tp] - position, 0)
            return lag
        except Exception:
            logger.warning("consumer lag unavailable", extra={"topic": topic}, exc_info=True)
            return -1

    async def dlq_depth(self, stage: Stage) -> int:
        topic = self._topic_namer().for_stage(stage, "dlq")
        try:
            tps, ends, begins = await self._offsets(topic)
            if not tps:
                return -1
            return sum(max(ends[tp] - begins[tp], 0) for tp in tps)
        except Exception:
            logger.warning("dlq depth unavailable", extra={"topic": topic}, exc_info=True)
            return -1

    async def close(self) -> None:
        async with self._producer_lock:
            producer, self._producer = self._producer, None
        if producer is not None:
            await producer.stop()
