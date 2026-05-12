"""Constants for HARO."""

from __future__ import annotations

DOMAIN = "haro"
NAME = "HARO"
VERSION = "0.0.1"

CONF_REPLAY_URL = "replay_url"
CONF_TOKEN = "token"
CONF_HAEO_CONFIG_ENTRY_ID = "haeo_config_entry_id"
CONF_EXTRA_ENTITY_IDS = "extra_entity_ids"
CONF_BATCH_SIZE = "batch_size"
CONF_FLUSH_INTERVAL = "flush_interval"
CONF_QUEUE_LIMIT = "queue_limit"

DEFAULT_REPLAY_URL = "wss://haro.replay.haeo.io/"
DEFAULT_BATCH_SIZE = 100
DEFAULT_FLUSH_INTERVAL = 1.0
DEFAULT_QUEUE_LIMIT = 10_000
