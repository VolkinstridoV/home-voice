"""Constants for the Guarded Agent integration."""

DOMAIN = "guarded_agent"

CONF_PRIMARY_AGENT = "primary_agent"
CONF_FALLBACK_PHRASE = "fallback_phrase"
CONF_TIMEOUT = "timeout"
CONF_RATE_PER_MINUTE = "rate_per_minute"
CONF_RATE_PER_HOUR = "rate_per_hour"
CONF_RATE_PER_DAY = "rate_per_day"
CONF_BREAKER_FAILURES = "breaker_failures"
CONF_BREAKER_SECONDS = "breaker_seconds"
CONF_DUP_SECONDS = "duplicate_seconds"

DEFAULT_FALLBACK_PHRASE = (
    "Sorry, I can't reach my brain right now. Please check the AI connection."
)
DEFAULT_TIMEOUT = 30
DEFAULT_RATE_PER_MINUTE = 6
DEFAULT_RATE_PER_HOUR = 60
DEFAULT_RATE_PER_DAY = 400
DEFAULT_BREAKER_FAILURES = 3
DEFAULT_BREAKER_SECONDS = 300
DEFAULT_DUP_SECONDS = 10
