from pathlib import Path
from aiogram import Bot
from aiogram.enums.chat_member_status import ChatMemberStatus


# Кэш супер-админов
_superadmins: set[int] | None = None


def load_superadmins(filepath: Path | None = None) -> set[int]:
    """Загрузить список супер-админов из файла."""
    global _superadmins
    if _superadmins is not None:
        return _superadmins

    if filepath is None:
        # Ищем файл относительно корня проекта
        filepath = Path(__file__).parent.parent / "superadmins.txt"

    _superadmins = set()
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # Пропускаем пустые строки и комментарии
                if line and not line.startswith("#"):
                    try:
                        _superadmins.add(int(line))
                    except ValueError:
                        pass
    return _superadmins


def is_superadmin(user_id: int) -> bool:
    """Проверить, является ли пользователь супер-админом."""
    return user_id in load_superadmins()


def reload_superadmins() -> set[int]:
    """Перезагрузить список супер-админов."""
    global _superadmins
    _superadmins = None
    return load_superadmins()


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
