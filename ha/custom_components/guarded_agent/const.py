"""Constants for the Guarded Agent integration."""

DOMAIN = "guarded_agent"

CONF_PRIMARY_AGENT = "primary_agent"
CONF_FALLBACK_PHRASE = "fallback_phrase"
CONF_TIMEOUT = "timeout"

DEFAULT_FALLBACK_PHRASE = (
    "Sorry, I can't reach my brain right now. Please check the AI connection."
)
DEFAULT_TIMEOUT = 30
