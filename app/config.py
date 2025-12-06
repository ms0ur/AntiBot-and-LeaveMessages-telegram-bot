from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass
class Config:
    bot_token: str
    database_path: Path


def load_config() -> Config:
    load_dotenv()

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is not set")

    database_path = Path(os.getenv("DATABASE_PATH", "data/bot_data.sqlite")).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return Config(bot_token=token, database_path=database_path)
