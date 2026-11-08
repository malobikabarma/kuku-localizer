"""All settings in one place. Values come from (in order): environment variables, a local .env file,
Streamlit secrets. Swap the model provider by changing API_BASE / API_KEY / MODEL_NAME only."""
import os
from dataclasses import dataclass

try:  # optional: local development with a .env file
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover
    pass


def _get(key: str, default=None):
    value = os.getenv(key)
    if value not in (None, ""):
        return value
    try:
        import streamlit as st
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return default


def _float(key: str, default: float) -> float:
    try:
        return float(_get(key, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    api_base: str = _get("API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai/")
    api_key: str = _get("API_KEY", "")
    model_name: str = _get("MODEL_NAME", "gemini-2.5-flash")
    target_language: str = _get("TARGET_LANGUAGE", "Hindi")
    app_password: str = _get("APP_PASSWORD", "")

    # timing heuristics (calibrate by reading ~10 lines aloud with a stopwatch)
    timing_unit: str = _get("TIMING_UNIT", "syllables")          # "syllables" or "words"
    max_syllables_per_sec: float = _float("MAX_SYLLABLES_PER_SEC", 6.0)
    max_words_per_sec: float = _float("MAX_WORDS_PER_SEC", 3.0)
    timing_grace_sec: float = _float("TIMING_GRACE_SEC", 0.3)   # actors can steal a little breath room

    # model behaviour
    temperature: float = _float("TEMPERATURE", 0.4)
    request_timeout: float = _float("REQUEST_TIMEOUT", 120)
    max_retries: int = int(_float("MAX_RETRIES", 3))
    use_json_mode: bool = str(_get("USE_JSON_MODE", "true")).lower() == "true"

    # cost estimate (USD per 1M tokens). Leave 0 on a free tier.
    price_in_per_m: float = _float("PRICE_IN_PER_M", 0.0)
    price_out_per_m: float = _float("PRICE_OUT_PER_M", 0.0)

    @property
    def max_rate(self) -> float:
        return self.max_syllables_per_sec if self.timing_unit == "syllables" else self.max_words_per_sec


settings = Settings()
