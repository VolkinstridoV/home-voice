"""Constants for Robot TTS."""

DOMAIN = "robot_tts"

CONF_PIPER_HOST = "piper_host"
CONF_PIPER_PORT = "piper_port"
CONF_VOICE_EN = "voice_en"
CONF_VOICE_RU = "voice_ru"
CONF_ROBOT_FILTER = "robot_filter"
CONF_ROBOT_ENABLED = "robot_enabled"
CONF_RVC_ENABLED = "rvc_enabled"
CONF_RVC_URL = "rvc_url"
CONF_RVC_PITCH = "rvc_pitch"
CONF_RVC_INDEX_RATE = "rvc_index_rate"
CONF_RVC_F0_METHOD = "rvc_f0_method"

DEFAULT_RVC_URL = "http://127.0.0.1:10500"
DEFAULT_RVC_PITCH = 0
DEFAULT_RVC_INDEX_RATE = 0.5
DEFAULT_RVC_F0_METHOD = "rmvpe"

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
