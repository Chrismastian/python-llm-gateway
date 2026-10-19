"""Provider list: what an upstream is, and how to load a list of them.

This module is data shape + loading only. The DECISION about which provider to
use lives in router.py -- mixing the two would make the decision untestable.
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path(os.environ.get("LLMGW_PROVIDERS", "providers.json"))


@dataclass
class Provider:
    """One upstream that speaks the OpenAI API.

    api_key is resolved from the environment at load time, so the key never
    has to be written into a file that could be committed.
    """

    name: str
    base_url: str
    api_key: str
    model: str


def load_providers(path: Path = DEFAULT_PATH) -> list[Provider]:
    """Read the provider list. The ORDER in the file IS the failover priority."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy providers.example.json to providers.json "
            "and fill in the environment variable names."
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        Provider(
            name=item["name"],
            base_url=item["base_url"].rstrip("/"),
            api_key=os.environ.get(item["api_key_env"], ""),
            model=item["model"],
        )
        for item in raw["providers"]
    ]