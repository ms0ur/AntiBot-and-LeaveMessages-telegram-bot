from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.enums.chat_member_status import ChatMemberStatus
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.database import Database

router = Router()


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


def _ensure_private(message: Message) -> bool:
    return message.chat.type == ChatType.PRIVATE


def _extract_command_arguments(message: Message) -> list[str]:
    if not message.text:
        return []
    return message.text.split()[1:]


async def _resolve_chat_id(message: Message, db: Database, args: list[str]) -> tuple[int | None, list[str]]:
    chat_id: int | None = None
    remaining = args
    if args and args[0].lstrip("-+").isdigit():
        chat_id = int(args[0])
        remaining = args[1:]
    else:
        selected = await db.get_admin_selected_chat(message.from_user.id)
        if selected is not None:
            chat_id = selected
    return chat_id, remaining


async def _validate_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        return await is_admin(bot, chat_id, user_id)
    except Exception:
        return False


async def _available_chats(bot: Bot, db: Database, user_id: int) -> list[tuple[int, str]]:
    known_chats = await db.get_known_chats()
    allowed: list[tuple[int, str]] = []
    for chat_id, title in known_chats:
        try:
            bot_member = await bot.get_chat_member(chat_id, bot.id)
            user_member = await bot.get_chat_member(chat_id, user_id)
        except Exception:
            continue

        if bot_member.status not in {
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.MEMBER,
        }:
            continue

        if user_member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
            allowed.append((chat_id, title))
    return allowed


def _settings_keyboard(chats: list[tuple[int, str]]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for chat_id, title in chats:
        label = f"{title[:40]} ({chat_id})"
        kb.button(text=label, callback_data=f"set_chat:{chat_id}")
    kb.adjust(1)
    kb.button(text="Обновить список", callback_data="settings:refresh")
    kb.adjust(1)
    return kb


@router.message(Command("confirm"))
async def confirm_user(message: Message, bot: Bot, db: Database) -> None:
    if not message.from_user or not _ensure_private(message):
        return

    args = _extract_command_arguments(message)
    chat_id, remaining = await _resolve_chat_id(message, db, args)
    if chat_id is None or len(remaining) != 1 or not remaining[0].isdigit():
        await message.answer("Укажите /confirm <chat_id> <user_id> или выберите чат в настройках.")
        return

    chat_id_int = chat_id
    user_id_int = int(remaining[0])

    if not await _validate_admin(bot, chat_id_int, message.from_user.id):
        await message.answer("Нужны права администратора в целевой группе.")
        return

    await db.add_confirmed_user(chat_id_int, user_id_int)
    await message.answer("Пользователь добавлен в список подтвержденных.")


@router.message(Command("unconfirm"))
async def unconfirm_user(message: Message, bot: Bot, db: Database) -> None:
    if not message.from_user or not _ensure_private(message):
        return

    args = _extract_command_arguments(message)
    chat_id, remaining = await _resolve_chat_id(message, db, args)
    if chat_id is None or len(remaining) != 1 or not remaining[0].isdigit():
        await message.answer("Укажите /unconfirm <chat_id> <user_id> или выберите чат в настройках.")
        return

    chat_id_int = chat_id
    user_id_int = int(remaining[0])

    if not await _validate_admin(bot, chat_id_int, message.from_user.id):
        await message.answer("Нужны права администратора в целевой группе.")
        return

    await db.remove_confirmed_user(chat_id_int, user_id_int)
    await message.answer("Пользователь удален из списка подтвержденных.")


@router.message(Command("confirmed"))
async def list_confirmed(message: Message, bot: Bot, db: Database) -> None:
    if not message.from_user or not _ensure_private(message):
        return

    args = _extract_command_arguments(message)
    chat_id, remaining = await _resolve_chat_id(message, db, args)
    if chat_id is None or remaining:
        await message.answer("Укажите /confirmed <chat_id> или выберите чат в настройках.")
        return

    chat_id_int = chat_id

    if not await _validate_admin(bot, chat_id_int, message.from_user.id):
        await message.answer("Нужны права администратора в целевой группе.")
        return

    confirmed = await db.get_confirmed_users(chat_id_int)
    if not confirmed:
        await message.answer("Список подтвержденных пуст.")
        return

    lines = ["Список подтвержденных пользователей:"]
    for user_id in confirmed:
        lines.append(f" • <code>{user_id}</code>")
    await message.answer("\n".join(lines))


@router.message(Command("banword"))
async def add_banned_word(message: Message, bot: Bot, db: Database) -> None:
    if not message.from_user or not _ensure_private(message) or not message.text:
        return

    args = _extract_command_arguments(message)
    chat_id, remaining = await _resolve_chat_id(message, db, args)
    if chat_id is None or not remaining:
        await message.answer("Укажите /banword <chat_id> <слово> или выберите чат в настройках.")
        return

    chat_id_int = chat_id
    word = " ".join(remaining).strip()
    if not word:
        await message.answer("Слово не должно быть пустым.")
        return

    if not await _validate_admin(bot, chat_id_int, message.from_user.id):
        await message.answer("Нужны права администратора в целевой группе.")
        return

    await db.add_banned_word(chat_id_int, word)
    await message.answer(f"Слово <b>{word}</b> добавлено в банлист.")


@router.message(Command("unbanword"))
async def remove_banned_word(message: Message, bot: Bot, db: Database) -> None:
    if not message.from_user or not _ensure_private(message) or not message.text:
        return

    args = _extract_command_arguments(message)
    chat_id, remaining = await _resolve_chat_id(message, db, args)
    if chat_id is None or not remaining:
        await message.answer("Укажите /unbanword <chat_id> <слово> или выберите чат в настройках.")
        return

    chat_id_int = chat_id
    word = " ".join(remaining).strip()

    if not await _validate_admin(bot, chat_id_int, message.from_user.id):
        await message.answer("Нужны права администратора в целевой группе.")
        return

    await db.remove_banned_word(chat_id_int, word)
    await message.answer(f"Слово <b>{word}</b> удалено из банлиста.")


@router.message(Command("banwords"))
async def list_banned_words(message: Message, bot: Bot, db: Database) -> None:
    if not message.from_user or not _ensure_private(message):
        return

    args = _extract_command_arguments(message)
    chat_id, remaining = await _resolve_chat_id(message, db, args)
    if chat_id is None or remaining:
        await message.answer("Укажите /banwords <chat_id> или выберите чат в настройках.")
        return

    chat_id_int = chat_id

    if not await _validate_admin(bot, chat_id_int, message.from_user.id):
        await message.answer("Нужны права администратора в целевой группе.")
        return

    words = await db.get_banned_words(chat_id_int)
    if not words:
        await message.answer("Банлист пуст.")
        return

    lines = ["Запрещенные слова:"]
    for word in words:
        lines.append(f" • {word}")
    await message.answer("\n".join(lines))


@router.message(Command("banuser"))
async def ban_user(message: Message, bot: Bot, db: Database) -> None:
    if not message.from_user or not _ensure_private(message):
        return

    args = _extract_command_arguments(message)
    chat_id, remaining = await _resolve_chat_id(message, db, args)
    if chat_id is None or len(remaining) != 1 or not remaining[0].isdigit():
        await message.answer("Укажите /banuser <chat_id> <user_id> или выберите чат в настройках.")
        return

    chat_id_int = chat_id
    user_id_int = int(remaining[0])

    if not await _validate_admin(bot, chat_id_int, message.from_user.id):
        await message.answer("Нужны права администратора в целевой группе.")
        return

    await db.add_banned_user(chat_id_int, user_id_int)
    await message.answer("Пользователь добавлен в банлист группы.")


@router.message(Command("unbanuser"))
async def unban_user(message: Message, bot: Bot, db: Database) -> None:
    if not message.from_user or not _ensure_private(message):
        return

    args = _extract_command_arguments(message)
    chat_id, remaining = await _resolve_chat_id(message, db, args)
    if chat_id is None or len(remaining) != 1 or not remaining[0].isdigit():
        await message.answer("Укажите /unbanuser <chat_id> <user_id> или выберите чат в настройках.")
        return

    chat_id_int = chat_id
    user_id_int = int(remaining[0])

    if not await _validate_admin(bot, chat_id_int, message.from_user.id):
        await message.answer("Нужны права администратора в целевой группе.")
        return

    await db.remove_banned_user(chat_id_int, user_id_int)
    await message.answer("Пользователь удален из банлиста группы.")


@router.callback_query(F.data == "settings")
async def show_settings(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    if not callback.from_user:
        return

    chats = await _available_chats(bot, db, callback.from_user.id)
    builder = _settings_keyboard(chats)
    text = "Выберите группу, где вы админ и добавлен бот."
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "settings:refresh")
async def refresh_settings(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    await show_settings(callback, bot, db)


@router.callback_query(F.data.startswith("set_chat:"))
async def set_chat(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    if not callback.from_user:
        return

    try:
        chat_id = int(callback.data.split(":", maxsplit=1)[1])
    except Exception:
        await callback.answer("Некорректный чат.", show_alert=True)
        return

    chats = await _available_chats(bot, db, callback.from_user.id)
    allowed_chat_ids = {chat for chat, _ in chats}
    if chat_id not in allowed_chat_ids:
        await callback.answer("Нет доступа к этому чату.", show_alert=True)
        return

    await db.set_admin_selected_chat(callback.from_user.id, chat_id)
    await callback.answer("Чат выбран для команд.")
    builder = _settings_keyboard(chats)
    await callback.message.edit_text(
        f"Активный чат: <code>{chat_id}</code>.",
        reply_markup=builder.as_markup(),
    )
