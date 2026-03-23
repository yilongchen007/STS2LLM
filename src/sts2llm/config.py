from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    openai_api_key: str
    openai_model: str = "gpt-5"
    sts2_base_url: str = "http://127.0.0.1:15526"


def load_settings() -> Settings:
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set. Create .env from .env.example first.")

    model = os.getenv("OPENAI_MODEL", "gpt-5").strip() or "gpt-5"
    base_url = os.getenv("STS2_BASE_URL", "http://127.0.0.1:15526").strip() or "http://127.0.0.1:15526"

    return Settings(
        openai_api_key=api_key,
        openai_model=model,
        sts2_base_url=base_url.rstrip("/"),
    )
