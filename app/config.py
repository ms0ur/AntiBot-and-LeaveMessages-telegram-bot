from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv
from aiogram.enums import ParseMode


@dataclass
class Config:
    bot_token: str
    database_path: Path
    default_parse_mode: ParseMode
    debug: bool


def load_config() -> Config:
    load_dotenv()

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is not set")

    database_path = Path(os.getenv("DATABASE_PATH", "data/bot_data.sqlite")).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    parse_mode_name = os.getenv("PARSE_MODE", "HTML").upper()
    try:
        default_parse_mode = ParseMode[parse_mode_name]
    except KeyError as exc:
        raise RuntimeError(
            "PARSE_MODE environment variable must be one of: "
            + ", ".join(mode.name for mode in ParseMode)
        ) from exc

    debug = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

    return Config(
        bot_token=token,
        database_path=database_path,
        default_parse_mode=default_parse_mode,
        debug=debug,
    )
