"""Load-bearing wording for engine control, shared by the router docs, the chat tool descriptions
and the confirmation previews, so the claims never drift apart (the model reads these strings).
"""

from typing import Final

PAUSE_EFFECT: Final = (
    "In-flight work finishes. New deliveries stay uncommitted on the bus, so nothing is lost "
    "and resuming continues from the same place."
)
DRAIN_EFFECT: Final = (
    "The station is paused, then reported DRAINED once nothing is in flight. "
    "It stays paused until it is resumed."
)
RESUME_EFFECT: Final = "The station takes new deliveries again, from the first uncommitted one."
THROTTLE_EFFECT: Final = (
    "Applies to new work only. Items already running finish at their current concurrency."
)
REPLAY_EFFECT: Final = (
    "Each chosen dead letter is sent back to its stage through the normal event path. "
    "Items a person has locked, items already done and events already replayed are skipped, "
    "never re-run."
)
PROPAGATION_NOTE: Final = (
    "Workers read the pause list from the shared settings cache, so a change can take up to "
    "the cache lifetime (about 15 seconds) to reach every worker."
)
EXTRACT_SHARED_NOTE: Final = (
    "Reader A and reader B run inside one extract consumer: pausing either holds both."
)
FAST_PATH_NOTE: Final = "The fast-path consumer is held together with receipt matching."

SKIP_REASONS: Final = {
    "locked": "A person holds the item (or it is being processed right now).",
    "done": "The item is already finished.",
    "already_replayed": "This dead letter was already replayed.",
    "moved_on": "The item is no longer at the stage that dead-lettered it.",
    "not_found": "No such dead letter, or its item no longer exists.",
}

TOOL_DESC_STATUS: Final = (
    "Read the processing engine: per station the state, consumer lag, throughput per minute, "
    "in-flight work against its limit and dead letters; plus bus health and the two pollers. "
    "Read-only."
)
TOOL_DESC_PAUSE: Final = "Pause one station of the processing engine. " + PAUSE_EFFECT
TOOL_DESC_RESUME: Final = "Resume one paused or drained station. " + RESUME_EFFECT
TOOL_DESC_DRAIN: Final = "Drain one station of the processing engine. " + DRAIN_EFFECT
TOOL_DESC_THROTTLE: Final = (
    "Set engine concurrency: items per stage (1 to 32) and Fusion applies per receipt (1 to 8). "
    + THROTTLE_EFFECT
)
TOOL_DESC_REPLAY: Final = (
    "Replay dead-lettered events by event id. " + REPLAY_EFFECT + " Needs the event ids from the "
    "dead-letter list."
)
