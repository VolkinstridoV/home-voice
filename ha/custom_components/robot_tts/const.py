"""Constants for Robot TTS."""

DOMAIN = "robot_tts"

CONF_PIPER_HOST = "piper_host"
CONF_PIPER_PORT = "piper_port"
CONF_VOICE_EN = "voice_en"
CONF_VOICE_RU = "voice_ru"
CONF_ROBOT_FILTER = "robot_filter"
CONF_ROBOT_ENABLED = "robot_enabled"

DEFAULT_PIPER_HOST = "127.0.0.1"
DEFAULT_PIPER_PORT = 10200
DEFAULT_VOICE_EN = "en_US-amy-medium"
DEFAULT_VOICE_RU = "ru_RU-irina-medium"
# ffmpeg -af chain. Slight pitch-up (smaller robot), a touch faster, gentle
# amplitude tremolo for the "synthetic" colour. Intelligibility first.
DEFAULT_ROBOT_FILTER = (
    "asetrate=22050*1.12,aresample=22050,atempo=1.04,"
    "tremolo=f=55:d=0.25,highpass=f=120,lowpass=f=7000"
)
