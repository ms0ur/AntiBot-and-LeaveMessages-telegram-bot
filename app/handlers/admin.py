import logging
from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.database import ACTION_LABELS, ChatSettings, Database, DEFAULT_WARN_MESSAGES
from app.utils import is_admin, is_superadmin

router = Router()

logger = logging.getLogger(__name__)


# FSM состояния для редактирования сообщений
class EditMessageState(StatesGroup):
    waiting_for_message = State()


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
    except TelegramAPIError as exc:
        logger.warning("Failed to validate admin in chat %s: %s", chat_id, exc)
        return False


async def _available_chats(bot: Bot, db: Database, user_id: int) -> list[tuple[int, str]]:
    known_chats = await db.get_known_chats()
    allowed: list[tuple[int, str]] = []
    chats_to_remove: list[int] = []

    for chat_id, title in known_chats:
        try:
            bot_member = await bot.get_chat_member(chat_id, bot.id)
            user_member = await bot.get_chat_member(chat_id, user_id)
        except TelegramBadRequest as exc:
            error_msg = str(exc).lower()
            # Группа мигрировала в супергруппу или чат не найден
            if "migrated" in error_msg or "chat not found" in error_msg or "upgraded" in error_msg:
                chats_to_remove.append(chat_id)
                logger.info("Chat %s will be removed (migrated or not found)", chat_id)
            else:
                logger.warning("Failed to check memberships for chat %s: %s", chat_id, exc)
            continue
        except TelegramAPIError as exc:
            logger.warning("Failed to check memberships for chat %s: %s", chat_id, exc)
            continue

        if bot_member.status not in {
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.MEMBER,
        }:
            continue

        if user_member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
            allowed.append((chat_id, title))

    # Удаляем устаревшие чаты
    for chat_id in chats_to_remove:
        await db.remove_chat(chat_id)

    return allowed


def _main_menu_keyboard(user_id: int | None = None) -> InlineKeyboardBuilder:
    """Главное меню бота."""
    kb = InlineKeyboardBuilder()
    kb.button(text="⚙️ Настройки (выбор чата)", callback_data="settings")
    kb.button(text="🛡️ Ограничения контента", callback_data="menu:restrictions")
    kb.button(text="⚡ Действия при нарушениях", callback_data="menu:actions")
    kb.button(text="💬 Сообщения при нарушениях", callback_data="menu:messages")
    kb.button(text="👥 Управление пользователями", callback_data="menu:users")
    kb.button(text="🚫 Банлист слов", callback_data="menu:words")
    kb.button(text="ℹ️ Помощь", callback_data="menu:help")
    # Кнопка для супер-админов
    if user_id and is_superadmin(user_id):
        kb.button(text="👑 Супер-админ панель", callback_data="menu:superadmin")
    kb.adjust(1)
    return kb


def _back_to_main_keyboard() -> InlineKeyboardBuilder:
    """Кнопка возврата в главное меню."""
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад в меню", callback_data="menu:main")
    return kb


def _settings_keyboard(chats: list[tuple[int, str]], selected_chat_id: int | None = None) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for chat_id, title in chats:
        prefix = "✅ " if chat_id == selected_chat_id else ""
        label = f"{prefix}{title[:35]} ({chat_id})"
        kb.button(text=label, callback_data=f"set_chat:{chat_id}")
    kb.adjust(1)
    kb.button(text="🔄 Обновить список", callback_data="settings:refresh")
    kb.button(text="◀️ Назад в меню", callback_data="menu:main")
    kb.adjust(1)
    return kb


def _users_menu_keyboard() -> InlineKeyboardBuilder:
    """Меню управления пользователями."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Доверенные пользователи", callback_data="users:confirmed:list")
    kb.button(text="◀️ Назад в меню", callback_data="menu:main")
    kb.adjust(1)
    return kb


def _words_menu_keyboard() -> InlineKeyboardBuilder:
    """Меню управления запрещенными словами."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Список слов", callback_data="words:list")
    kb.button(text="◀️ Назад в меню", callback_data="menu:main")
    kb.adjust(1)
    return kb


def _list_back_keyboard(back_callback: str) -> InlineKeyboardBuilder:
    """Клавиатура для списков с кнопкой назад."""
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Назад", callback_data=back_callback)
    kb.button(text="🏠 В меню", callback_data="menu:main")
    kb.adjust(2)
    return kb


def _restrictions_keyboard(settings: ChatSettings) -> InlineKeyboardBuilder:
    """Клавиатура настроек ограничений контента."""
    kb = InlineKeyboardBuilder()

    # Эмодзи для статуса
    def status(enabled: bool) -> str:
        return "🔴" if enabled else "🟢"

    # Настройка бустеров
    booster_status = "✅" if settings.trust_boosters else "❌"
    kb.button(
        text=f"{booster_status} Доверять бустерам",
        callback_data="restrict:toggle:trust_boosters"
    )

    # Обычные пользователи
    kb.button(
        text=f"{status(settings.restrict_media_regular)} Медиа (обычные)",
        callback_data="restrict:toggle:restrict_media_regular"
    )
    kb.button(
        text=f"{status(settings.restrict_stickers_regular)} Стикеры (обычные)",
        callback_data="restrict:toggle:restrict_stickers_regular"
    )
    kb.button(
        text=f"{status(settings.restrict_links_regular)} Ссылки (обычные)",
        callback_data="restrict:toggle:restrict_links_regular"
    )
    kb.button(
        text=f"{status(settings.restrict_voice_regular)} Голосовые (обычные)",
        callback_data="restrict:toggle:restrict_voice_regular"
    )

    # Доверенные пользователи
    kb.button(
        text=f"{status(settings.restrict_media_confirmed)} Медиа (доверенные)",
        callback_data="restrict:toggle:restrict_media_confirmed"
    )
    kb.button(
        text=f"{status(settings.restrict_stickers_confirmed)} Стикеры (доверенные)",
        callback_data="restrict:toggle:restrict_stickers_confirmed"
    )
    kb.button(
        text=f"{status(settings.restrict_links_confirmed)} Ссылки (доверенные)",
        callback_data="restrict:toggle:restrict_links_confirmed"
    )
    kb.button(
        text=f"{status(settings.restrict_voice_confirmed)} Голосовые (доверенные)",
        callback_data="restrict:toggle:restrict_voice_confirmed"
    )

    kb.adjust(1)
    kb.button(text="◀️ Назад в меню", callback_data="menu:main")
    kb.adjust(1)
    return kb


def _actions_keyboard(settings: ChatSettings) -> InlineKeyboardBuilder:
    """Клавиатура настроек действий при нарушениях."""
    kb = InlineKeyboardBuilder()

    def action_label(action: int) -> str:
        return ACTION_LABELS.get(action, "❓")

    kb.button(
        text=f"📷 Медиа: {action_label(settings.action_media)}",
        callback_data="action:cycle:action_media"
    )
    kb.button(
        text=f"😀 Стикеры: {action_label(settings.action_stickers)}",
        callback_data="action:cycle:action_stickers"
    )
    kb.button(
        text=f"🔗 Ссылки: {action_label(settings.action_links)}",
        callback_data="action:cycle:action_links"
    )
    kb.button(
        text=f"🎤 Голосовые: {action_label(settings.action_voice)}",
        callback_data="action:cycle:action_voice"
    )
    kb.button(
        text=f"💬 Запрещ. слова: {action_label(settings.action_words)}",
        callback_data="action:cycle:action_words"
    )
    kb.button(
        text=f"🤖 Добавление ботов: {action_label(settings.action_bots)}",
        callback_data="action:cycle:action_bots"
    )
    kb.button(
        text=f"🚫 Глоб. бан-лист: {action_label(settings.action_global_ban)}",
        callback_data="action:cycle:action_global_ban"
    )

    kb.adjust(1)
    kb.button(text="◀️ Назад в меню", callback_data="menu:main")
    kb.adjust(1)
    return kb


def _messages_keyboard(settings: ChatSettings) -> InlineKeyboardBuilder:
    """Клавиатура настроек кастомных сообщений."""
    kb = InlineKeyboardBuilder()

    def has_custom(field: str) -> str:
        value = getattr(settings, field, "")
        return "✏️" if value else "📝"

    kb.button(
        text=f"{has_custom('warn_message_media')} Медиа",
        callback_data="msg:edit:media"
    )
    kb.button(
        text=f"{has_custom('warn_message_stickers')} Стикеры",
        callback_data="msg:edit:stickers"
    )
    kb.button(
        text=f"{has_custom('warn_message_links')} Ссылки",
        callback_data="msg:edit:links"
    )
    kb.button(
        text=f"{has_custom('warn_message_voice')} Голосовые",
        callback_data="msg:edit:voice"
    )
    kb.button(
        text=f"{has_custom('warn_message_words')} Запрещ. слова",
        callback_data="msg:edit:words"
    )
    kb.button(
        text=f"{has_custom('warn_message_bots')} Добавление ботов",
        callback_data="msg:edit:bots"
    )
    kb.button(
        text=f"{has_custom('warn_message_global_ban')} Глоб. бан-лист",
        callback_data="msg:edit:global_ban"
    )

    kb.adjust(2)
    kb.button(text="◀️ Назад в меню", callback_data="menu:main")
    kb.adjust(1)
    return kb


def _superadmin_menu_keyboard() -> InlineKeyboardBuilder:
    """Меню супер-админа."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика бота", callback_data="sa:stats")
    kb.button(text="🚫 Глобальный бан-лист", callback_data="sa:banlist")
    kb.button(text="📋 Подключенные группы", callback_data="sa:groups")
    kb.button(text="◀️ Назад в меню", callback_data="menu:main")
    kb.adjust(1)
    return kb


def _superadmin_groups_keyboard(chats: list[tuple[int, str]]) -> InlineKeyboardBuilder:
    """Клавиатура списка групп для супер-админа."""
    kb = InlineKeyboardBuilder()
    for chat_id, title in chats[:20]:  # Ограничиваем 20 группами
        label = f"❌ {title[:30]} ({chat_id})"
        kb.button(text=label, callback_data=f"sa:disconnect:{chat_id}")
    kb.adjust(1)
    kb.button(text="◀️ Назад", callback_data="menu:superadmin")
    kb.adjust(1)
    return kb


@router.message(Command("confirm"))
async def confirm_user(message: Message, bot: Bot, db: Database) -> None:
    if not message.from_user or not _ensure_private(message):
        return

    args = _extract_command_arguments(message)
    chat_id, remaining = await _resolve_chat_id(message, db, args)
    if chat_id is None or len(remaining) != 1 or not remaining[0].isdigit():
        await message.answer("Укажите /confirm [chat_id] [user_id] или выберите чат в настройках.")
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
        await message.answer("Укажите /unconfirm [chat_id] [user_id] или выберите чат в настройках.")
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
        await message.answer("Укажите /confirmed [chat_id] или выберите чат в настройках.")
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
        await message.answer("Укажите /banword [chat_id] [слово] или выберите чат в настройках.")
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
        await message.answer("Укажите /unbanword [chat_id] [слово] или выберите чат в настройках.")
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
        await message.answer("Укажите /banwords [chat_id] или выберите чат в настройках.")
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


@router.callback_query(F.data == "menu:main")
async def show_main_menu(callback: CallbackQuery) -> None:
    """Показать главное меню."""
    user_id = callback.from_user.id if callback.from_user else None
    builder = _main_menu_keyboard(user_id)
    await callback.message.edit_text(
        "🤖 <b>Главное меню</b>\n\n"
        "Выберите действие:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:help")
async def show_help(callback: CallbackQuery) -> None:
    """Показать справку."""
    builder = _back_to_main_keyboard()
    await callback.message.edit_text(
        "ℹ️ <b>Справка</b>\n\n"
        "Этот бот помогает модерировать группы:\n"
        "• Удаляет ботов, добавленных не-админами\n"
        "• Удаляет сообщения о входе/выходе\n"
        "• Фильтрует медиа, стикеры и ссылки\n"
        "• Блокирует запрещённые слова\n\n"
        "<b>Как начать:</b>\n"
        "1. Добавьте бота в группу\n"
        "2. Дайте боту права админа\n"
        "3. Напишите что-нибудь в группе\n"
        "4. Выберите группу в настройках\n\n"
        "<b>🛡️ Ограничения медиа:</b>\n"
        "Настройте отдельно для обычных и доверенных:\n"
        "• Медиа (фото, видео, аудио, файлы)\n"
        "• Стикеры\n"
        "• Ссылки\n\n"
        "<b>Команды в группе:</b>\n"
        "<code>/trust</code> — ответьте на сообщение, чтобы добавить в доверенные\n"
        "<code>/untrust</code> — ответьте на сообщение, чтобы убрать из доверенных\n\n"
        "<b>Команды в личке:</b>\n"
        "<code>/confirm [user_id]</code> — добавить в доверенные\n"
        "<code>/unconfirm [user_id]</code> — убрать из доверенных\n"
        "<code>/banword [слово]</code> — добавить запрещённое слово\n"
        "<code>/unbanword [слово]</code> — удалить из списка",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:users")
async def show_users_menu(callback: CallbackQuery, db: Database) -> None:
    """Меню управления пользователями."""
    if not callback.from_user:
        return

    selected = await db.get_admin_selected_chat(callback.from_user.id)
    if selected is None:
        await callback.answer("Сначала выберите чат в настройках!", show_alert=True)
        return

    builder = _users_menu_keyboard()
    await callback.message.edit_text(
        "👥 <b>Управление пользователями</b>\n\n"
        f"Активный чат: <code>{selected}</code>\n\n"
        "Выберите категорию:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:words")
async def show_words_menu(callback: CallbackQuery, db: Database) -> None:
    """Меню управления словами."""
    if not callback.from_user:
        return

    selected = await db.get_admin_selected_chat(callback.from_user.id)
    if selected is None:
        await callback.answer("Сначала выберите чат в настройках!", show_alert=True)
        return

    builder = _words_menu_keyboard()
    await callback.message.edit_text(
        "🚫 <b>Банлист слов</b>\n\n"
        f"Активный чат: <code>{selected}</code>\n\n"
        "Сообщения с запрещёнными словами будут удаляться.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:restrictions")
async def show_restrictions_menu(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    """Меню настроек ограничений медиа."""
    if not callback.from_user:
        return

    selected = await db.get_admin_selected_chat(callback.from_user.id)
    if selected is None:
        await callback.answer("Сначала выберите чат в настройках!", show_alert=True)
        return

    if not await _validate_admin(bot, selected, callback.from_user.id):
        await callback.answer("Нет прав администратора в этом чате!", show_alert=True)
        return

    settings = await db.get_chat_settings(selected)
    builder = _restrictions_keyboard(settings)

    await callback.message.edit_text(
        "🛡️ <b>Ограничения контента</b>\n\n"
        f"Активный чат: <code>{selected}</code>\n\n"
        "🔴 = запрещено\n"
        "🟢 = разрешено\n\n"
        "<b>Обычные</b> — все, кто не доверенный и не админ.\n"
        "<b>Доверенные</b> — добавленные через /confirm или бустеры.\n\n"
        "Нажмите для переключения:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("restrict:toggle:"))
async def toggle_restriction(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    """Переключение настройки ограничения."""
    if not callback.from_user:
        return

    selected = await db.get_admin_selected_chat(callback.from_user.id)
    if selected is None:
        await callback.answer("Сначала выберите чат в настройках!", show_alert=True)
        return

    if not await _validate_admin(bot, selected, callback.from_user.id):
        await callback.answer("Нет прав администратора в этом чате!", show_alert=True)
        return

    # Извлекаем имя настройки
    setting_name = callback.data.split(":", 2)[2]
    valid_settings = {
        "restrict_media_regular", "restrict_stickers_regular", "restrict_links_regular", "restrict_voice_regular",
        "restrict_media_confirmed", "restrict_stickers_confirmed", "restrict_links_confirmed", "restrict_voice_confirmed",
        "trust_boosters",
    }

    if setting_name not in valid_settings:
        await callback.answer("Неизвестная настройка", show_alert=True)
        return

    # Переключаем настройку
    new_value = await db.toggle_chat_setting(selected, setting_name)

    # Формируем сообщение
    setting_labels = {
        "restrict_media_regular": "Медиа (обычные)",
        "restrict_stickers_regular": "Стикеры (обычные)",
        "restrict_links_regular": "Ссылки (обычные)",
        "restrict_voice_regular": "Голосовые (обычные)",
        "restrict_media_confirmed": "Медиа (доверенные)",
        "restrict_stickers_confirmed": "Стикеры (доверенные)",
        "restrict_links_confirmed": "Ссылки (доверенные)",
        "restrict_voice_confirmed": "Голосовые (доверенные)",
        "trust_boosters": "Доверять бустерам",
    }
    label = setting_labels.get(setting_name, setting_name)

    if setting_name == "trust_boosters":
        status = "✅ включено" if new_value else "❌ выключено"
    else:
        status = "🔴 запрещено" if new_value else "🟢 разрешено"
    await callback.answer(f"{label}: {status}")

    # Обновляем клавиатуру
    settings = await db.get_chat_settings(selected)
    builder = _restrictions_keyboard(settings)

    try:
        await callback.message.edit_text(
            "🛡️ <b>Ограничения контента</b>\n\n"
            f"Активный чат: <code>{selected}</code>\n\n"
            "🔴 = запрещено\n"
            "🟢 = разрешено\n\n"
            "<b>Обычные</b> — все, кто не доверенный и не админ.\n"
            "<b>Доверенные</b> — добавленные через /confirm или бустеры.\n\n"
            "Нажмите для переключения:",
            reply_markup=builder.as_markup(),
        )
    except TelegramBadRequest:
        pass  # Сообщение не изменилось


@router.callback_query(F.data == "menu:actions")
async def show_actions_menu(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    """Меню настроек действий при нарушениях."""
    if not callback.from_user:
        return

    selected = await db.get_admin_selected_chat(callback.from_user.id)
    if selected is None:
        await callback.answer("Сначала выберите чат в настройках!", show_alert=True)
        return

    if not await _validate_admin(bot, selected, callback.from_user.id):
        await callback.answer("Нет прав администратора в этом чате!", show_alert=True)
        return

    settings = await db.get_chat_settings(selected)
    builder = _actions_keyboard(settings)

    await callback.message.edit_text(
        "⚡ <b>Действия при нарушениях</b>\n\n"
        f"Активный чат: <code>{selected}</code>\n\n"
        "Что делать с нарушителем:\n"
        "🟢 Ничего — игнорировать\n"
        "🗑️ Удалить — только удалить сообщение\n"
        "⚠️ Предупредить — удалить + написать предупреждение\n"
        "👢 Кикнуть — удалить + исключить из группы\n"
        "🚫 Забанить — удалить + заблокировать через Telegram\n\n"
        "Нажмите для переключения:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("action:cycle:"))
async def cycle_action(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    """Переключение действия по кругу."""
    if not callback.from_user:
        return

    selected = await db.get_admin_selected_chat(callback.from_user.id)
    if selected is None:
        await callback.answer("Сначала выберите чат в настройках!", show_alert=True)
        return

    if not await _validate_admin(bot, selected, callback.from_user.id):
        await callback.answer("Нет прав администратора в этом чате!", show_alert=True)
        return

    setting_name = callback.data.split(":", 2)[2]
    valid_settings = {
        "action_media", "action_stickers", "action_links", "action_voice",
        "action_words", "action_bots", "action_global_ban",
    }

    if setting_name not in valid_settings:
        await callback.answer("Неизвестная настройка", show_alert=True)
        return

    new_value = await db.cycle_action_setting(selected, setting_name)

    setting_labels = {
        "action_media": "Медиа",
        "action_stickers": "Стикеры",
        "action_links": "Ссылки",
        "action_voice": "Голосовые",
        "action_words": "Запрещённые слова",
        "action_bots": "Добавление ботов",
        "action_global_ban": "Глобальный бан-лист",
    }
    label = setting_labels.get(setting_name, setting_name)
    action_text = ACTION_LABELS.get(new_value, "❓")
    await callback.answer(f"{label}: {action_text}")

    settings = await db.get_chat_settings(selected)
    builder = _actions_keyboard(settings)

    try:
        await callback.message.edit_text(
            "⚡ <b>Действия при нарушениях</b>\n\n"
            f"Активный чат: <code>{selected}</code>\n\n"
            "Что делать с нарушителем:\n"
            "🟢 Ничего — игнорировать\n"
            "🗑️ Удалить — только удалить сообщение\n"
            "⚠️ Предупредить — удалить + написать предупреждение\n"
            "👢 Кикнуть — удалить + исключить из группы\n"
            "🚫 Забанить — удалить + заблокировать через Telegram\n\n"
            "Нажмите для переключения:",
            reply_markup=builder.as_markup(),
        )
    except TelegramBadRequest:
        pass


# === Кастомные сообщения ===

# Названия типов сообщений
MESSAGE_TYPE_LABELS = {
    "media": "📷 Медиа",
    "stickers": "😀 Стикеры",
    "links": "🔗 Ссылки",
    "voice": "🎤 Голосовые",
    "words": "💬 Запрещённые слова",
    "bots": "🤖 Добавление ботов",
    "global_ban": "🚫 Глобальный бан-лист",
}


@router.callback_query(F.data == "menu:messages")
async def show_messages_menu(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    """Меню настроек кастомных сообщений."""
    if not callback.from_user:
        return

    selected = await db.get_admin_selected_chat(callback.from_user.id)
    if selected is None:
        await callback.answer("Сначала выберите чат в настройках!", show_alert=True)
        return

    if not await _validate_admin(bot, selected, callback.from_user.id):
        await callback.answer("Нет прав администратора в этом чате!", show_alert=True)
        return

    settings = await db.get_chat_settings(selected)
    builder = _messages_keyboard(settings)

    await callback.message.edit_text(
        "💬 <b>Сообщения при нарушениях</b>\n\n"
        f"Активный чат: <code>{selected}</code>\n\n"
        "Настройте текст предупреждений для каждого типа нарушения.\n"
        "Используйте <code>{user}</code> для упоминания пользователя.\n\n"
        "📝 = стандартное сообщение\n"
        "✏️ = кастомное сообщение",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("msg:edit:"))
async def edit_message_prompt(callback: CallbackQuery, bot: Bot, db: Database, state: FSMContext) -> None:
    """Начало редактирования кастомного сообщения."""
    if not callback.from_user:
        return

    selected = await db.get_admin_selected_chat(callback.from_user.id)
    if selected is None:
        await callback.answer("Сначала выберите чат в настройках!", show_alert=True)
        return

    if not await _validate_admin(bot, selected, callback.from_user.id):
        await callback.answer("Нет прав администратора в этом чате!", show_alert=True)
        return

    message_type = callback.data.split(":", 2)[2]
    if message_type not in MESSAGE_TYPE_LABELS:
        await callback.answer("Неизвестный тип", show_alert=True)
        return

    settings = await db.get_chat_settings(selected)
    field_name = f"warn_message_{message_type}"
    current_message = getattr(settings, field_name, "")

    from app.database import DEFAULT_WARN_MESSAGES
    default_message = DEFAULT_WARN_MESSAGES.get(message_type, "")

    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Сбросить на стандартное", callback_data=f"msg:reset:{message_type}")
    kb.button(text="❌ Отмена", callback_data="menu:messages")
    kb.adjust(1)

    current_text = current_message if current_message else f"(стандартное) {default_message}"

    await callback.message.edit_text(
        f"✏️ <b>Редактирование: {MESSAGE_TYPE_LABELS[message_type]}</b>\n\n"
        f"Текущее сообщение:\n<code>{current_text}</code>\n\n"
        "Отправьте новое сообщение для этого нарушения.\n"
        "Используйте <code>{user}</code> для упоминания пользователя.\n\n"
        "Пример: <code>⚠️ {user}, это запрещено!</code>",
        reply_markup=kb.as_markup(),
    )

    await state.set_state(EditMessageState.waiting_for_message)
    await state.update_data(message_type=message_type, chat_id=selected)
    await callback.answer()


@router.message(EditMessageState.waiting_for_message)
async def save_custom_message(message: Message, bot: Bot, db: Database, state: FSMContext) -> None:
    """Сохранение кастомного сообщения."""
    if not message.from_user or not message.text:
        return

    data = await state.get_data()
    message_type = data.get("message_type")
    chat_id = data.get("chat_id")

    if not message_type or not chat_id:
        await state.clear()
        return

    # Сохраняем сообщение
    await db.set_warn_message(chat_id, message_type, message.text)
    await state.clear()

    # Показываем подтверждение и возвращаемся в меню
    settings = await db.get_chat_settings(chat_id)
    builder = _messages_keyboard(settings)

    await message.answer(
        f"✅ Сообщение для <b>{MESSAGE_TYPE_LABELS[message_type]}</b> сохранено!\n\n"
        "💬 <b>Сообщения при нарушениях</b>\n\n"
        f"Активный чат: <code>{chat_id}</code>\n\n"
        "Настройте текст предупреждений для каждого типа нарушения.\n"
        "Используйте <code>{user}</code> для упоминания пользователя.\n\n"
        "📝 = стандартное сообщение\n"
        "✏️ = кастомное сообщение",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("msg:reset:"))
async def reset_custom_message(callback: CallbackQuery, bot: Bot, db: Database, state: FSMContext) -> None:
    """Сброс кастомного сообщения на стандартное."""
    if not callback.from_user:
        return

    selected = await db.get_admin_selected_chat(callback.from_user.id)
    if selected is None:
        await callback.answer("Сначала выберите чат в настройках!", show_alert=True)
        return

    message_type = callback.data.split(":", 2)[2]
    if message_type not in MESSAGE_TYPE_LABELS:
        await callback.answer("Неизвестный тип", show_alert=True)
        return

    await db.reset_warn_message(selected, message_type)
    await state.clear()

    settings = await db.get_chat_settings(selected)
    builder = _messages_keyboard(settings)

    await callback.message.edit_text(
        f"✅ Сообщение для <b>{MESSAGE_TYPE_LABELS[message_type]}</b> сброшено на стандартное!\n\n"
        "💬 <b>Сообщения при нарушениях</b>\n\n"
        f"Активный чат: <code>{selected}</code>\n\n"
        "Настройте текст предупреждений для каждого типа нарушения.\n"
        "Используйте <code>{user}</code> для упоминания пользователя.\n\n"
        "📝 = стандартное сообщение\n"
        "✏️ = кастомное сообщение",
        reply_markup=builder.as_markup(),
    )
    await callback.answer("Сообщение сброшено")


@router.callback_query(F.data == "users:confirmed:list")
async def show_confirmed_list(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    """Список подтверждённых пользователей."""
    if not callback.from_user:
        return

    selected = await db.get_admin_selected_chat(callback.from_user.id)
    if selected is None:
        await callback.answer("Сначала выберите чат в настройках!", show_alert=True)
        return

    if not await _validate_admin(bot, selected, callback.from_user.id):
        await callback.answer("Нет прав администратора в этом чате!", show_alert=True)
        return

    confirmed = await db.get_confirmed_users(selected)
    builder = _list_back_keyboard("menu:users")

    if not confirmed:
        text = (
            "✅ <b>Подтверждённые пользователи</b>\n\n"
            "Список пуст.\n\n"
            "Добавить: <code>/confirm [user_id]</code>"
        )
    else:
        lines = ["✅ <b>Подтверждённые пользователи</b>\n"]
        for user_id in confirmed:
            lines.append(f"• <code>{user_id}</code>")
        lines.append(f"\nВсего: {len(confirmed)}")
        lines.append("\nУдалить: <code>/unconfirm [user_id]</code>")
        text = "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "words:list")
async def show_words_list(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    """Список запрещённых слов."""
    if not callback.from_user:
        return

    selected = await db.get_admin_selected_chat(callback.from_user.id)
    if selected is None:
        await callback.answer("Сначала выберите чат в настройках!", show_alert=True)
        return

    if not await _validate_admin(bot, selected, callback.from_user.id):
        await callback.answer("Нет прав администратора в этом чате!", show_alert=True)
        return

    words = await db.get_banned_words(selected)
    builder = _list_back_keyboard("menu:words")

    if not words:
        text = (
            "📋 <b>Запрещённые слова</b>\n\n"
            "Список пуст.\n\n"
            "Добавить: <code>/banword [слово]</code>"
        )
    else:
        lines = ["📋 <b>Запрещённые слова</b>\n"]
        for word in words:
            lines.append(f"• {word}")
        lines.append(f"\nВсего: {len(words)}")
        lines.append("\nУдалить: <code>/unbanword [слово]</code>")
        text = "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "settings")
async def show_settings(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    if not callback.from_user:
        return

    chats = await _available_chats(bot, db, callback.from_user.id)
    selected = await db.get_admin_selected_chat(callback.from_user.id)

    if not chats:
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Обновить", callback_data="settings:refresh")
        builder.button(text="◀️ Назад в меню", callback_data="menu:main")
        builder.adjust(1)
        await callback.message.edit_text(
            "⚙️ <b>Настройки</b>\n\n"
            "❌ <b>Нет доступных групп.</b>\n\n"
            "Чтобы группа появилась:\n"
            "1. Добавьте бота в группу\n"
            "2. Дайте боту права администратора\n"
            "3. Напишите любое сообщение в группе\n"
            "4. Нажмите «Обновить»",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return

    builder = _settings_keyboard(chats, selected)
    selected_text = f"\n\n✅ Выбран: <code>{selected}</code>" if selected else ""
    await callback.message.edit_text(
        f"⚙️ <b>Настройки</b>\n\n"
        f"Выберите группу, где вы админ и добавлен бот:{selected_text}",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "settings:refresh")
async def refresh_settings(callback: CallbackQuery, bot: Bot, db: Database) -> None:
    try:
        await show_settings(callback, bot, db)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback.answer("Список групп не изменился", show_alert=False)
        else:
            raise


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
    chat_title = next((title for cid, title in chats if cid == chat_id), str(chat_id))
    await callback.answer(f"✅ Выбран: {chat_title}")

    builder = _settings_keyboard(chats, chat_id)
    await callback.message.edit_text(
        f"⚙️ <b>Настройки</b>\n\n"
        f"Выберите группу, где вы админ и добавлен бот:\n\n"
        f"✅ Выбран: <b>{chat_title}</b>\n"
        f"<code>{chat_id}</code>",
        reply_markup=builder.as_markup(),
    )


# === СУПЕР-АДМИН ПАНЕЛЬ ===

@router.callback_query(F.data == "menu:superadmin")
async def show_superadmin_menu(callback: CallbackQuery) -> None:
    """Меню супер-админа."""
    if not callback.from_user or not is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён!", show_alert=True)
        return

    builder = _superadmin_menu_keyboard()
    await callback.message.edit_text(
        "👑 <b>Супер-админ панель</b>\n\n"
        "Управление ботом на глобальном уровне:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "sa:stats")
async def show_stats(callback: CallbackQuery, db: Database) -> None:
    """Показать статистику бота."""
    if not callback.from_user or not is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён!", show_alert=True)
        return

    stats = await db.get_stats()
    chats_count = await db.get_chats_count()
    confirmed_count = await db.get_confirmed_users_count()
    global_banned_count = await db.get_global_banned_count()

    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="menu:superadmin")

    await callback.message.edit_text(
        "📊 <b>Статистика бота</b>\n\n"
        f"📋 Подключено групп: <b>{chats_count}</b>\n"
        f"✅ Доверенных пользователей: <b>{confirmed_count}</b>\n"
        f"🚫 Глобально забанено: <b>{global_banned_count}</b>\n\n"
        f"🗑️ Удалено сообщений: <b>{stats['messages_deleted']}</b>\n"
        f"🤖 Забанено ботов: <b>{stats['bots_banned']}</b>",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "sa:banlist")
async def show_global_banlist(callback: CallbackQuery, db: Database) -> None:
    """Показать глобальный бан-лист."""
    if not callback.from_user or not is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён!", show_alert=True)
        return

    banned = await db.get_global_banned_users()

    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="menu:superadmin")

    if not banned:
        text = (
            "🚫 <b>Глобальный бан-лист</b>\n\n"
            "Список пуст.\n\n"
            "Добавить: <code>/gban [user_id] [причина]</code>\n"
            "Удалить: <code>/ungban [user_id]</code>"
        )
    else:
        lines = ["🚫 <b>Глобальный бан-лист</b>\n"]
        for user_id, banned_by, banned_at, reason in banned[:20]:
            reason_text = f" — {reason}" if reason else ""
            lines.append(f"• <code>{user_id}</code>{reason_text}")
        if len(banned) > 20:
            lines.append(f"\n... и ещё {len(banned) - 20}")
        lines.append(f"\nВсего: {len(banned)}")
        lines.append("\nДобавить: <code>/gban [user_id] [причина]</code>")
        lines.append("Удалить: <code>/ungban [user_id]</code>")
        text = "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "sa:groups")
async def show_all_groups(callback: CallbackQuery, db: Database) -> None:
    """Показать все подключенные группы."""
    if not callback.from_user or not is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён!", show_alert=True)
        return

    chats = await db.get_known_chats()

    if not chats:
        builder = InlineKeyboardBuilder()
        builder.button(text="◀️ Назад", callback_data="menu:superadmin")
        await callback.message.edit_text(
            "📋 <b>Подключенные группы</b>\n\n"
            "Нет подключенных групп.",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return

    builder = _superadmin_groups_keyboard(chats)
    await callback.message.edit_text(
        f"📋 <b>Подключенные группы</b>\n\n"
        f"Всего: {len(chats)}\n\n"
        "Нажмите на группу, чтобы отключить её:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sa:disconnect:"))
async def disconnect_group(callback: CallbackQuery, db: Database) -> None:
    """Отключить группу."""
    if not callback.from_user or not is_superadmin(callback.from_user.id):
        await callback.answer("Доступ запрещён!", show_alert=True)
        return

    try:
        chat_id = int(callback.data.split(":", 2)[2])
    except Exception:
        await callback.answer("Некорректный ID чата.", show_alert=True)
        return

    await db.remove_chat(chat_id)
    await callback.answer(f"Группа {chat_id} отключена!")

    # Обновляем список
    await show_all_groups(callback, db)


# === Команды для супер-админов ===

@router.message(Command("gban"))
async def global_ban_command(message: Message, db: Database) -> None:
    """Глобально забанить пользователя."""
    if not message.from_user or not is_superadmin(message.from_user.id):
        return

    args = _extract_command_arguments(message)
    if not args or not args[0].isdigit():
        await message.answer(
            "Использование: <code>/gban [user_id] [причина]</code>\n"
            "Пример: <code>/gban 123456789 спам</code>"
        )
        return

    user_id = int(args[0])
    reason = " ".join(args[1:]) if len(args) > 1 else None

    await db.add_global_banned_user(user_id, message.from_user.id, reason)

    reason_text = f"\nПричина: {reason}" if reason else ""
    await message.answer(f"🚫 Пользователь <code>{user_id}</code> добавлен в глобальный бан-лист.{reason_text}")


@router.message(Command("ungban"))
async def global_unban_command(message: Message, db: Database) -> None:
    """Разбанить пользователя глобально."""
    if not message.from_user or not is_superadmin(message.from_user.id):
        return

    args = _extract_command_arguments(message)
    if not args or not args[0].isdigit():
        await message.answer("Использование: <code>/ungban [user_id]</code>")
        return

    user_id = int(args[0])
    await db.remove_global_banned_user(user_id)
    await message.answer(f"✅ Пользователь <code>{user_id}</code> удалён из глобального бан-листа.")


@router.message(Command("botstats"))
async def bot_stats_command(message: Message, db: Database) -> None:
    """Показать статистику бота (только для супер-админов)."""
    if not message.from_user or not is_superadmin(message.from_user.id):
        return

    stats = await db.get_stats()
    chats_count = await db.get_chats_count()
    confirmed_count = await db.get_confirmed_users_count()
    global_banned_count = await db.get_global_banned_count()

    await message.answer(
        "📊 <b>Статистика бота</b>\n\n"
        f"📋 Подключено групп: <b>{chats_count}</b>\n"
        f"✅ Доверенных пользователей: <b>{confirmed_count}</b>\n"
        f"🚫 Глобально забанено: <b>{global_banned_count}</b>\n\n"
        f"🗑️ Удалено сообщений: <b>{stats['messages_deleted']}</b>\n"
        f"🤖 Забанено ботов: <b>{stats['bots_banned']}</b>"
    )

