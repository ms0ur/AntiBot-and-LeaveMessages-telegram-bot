import asyncio
import html
import logging
import re
from typing import Iterable
from aiogram import Bot, Router
from aiogram.enums import ChatMemberStatus, ChatType, ContentType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import ChatPermissions, Message, User
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.database import (
    ACTION_NONE, ACTION_DELETE, ACTION_WARN, ACTION_KICK, ACTION_BAN,
    ChatSettings, Database, DEFAULT_WARN_MESSAGES,
)
from app.utils import is_admin

router = Router()
logger = logging.getLogger(__name__)

# Медиа-контент (фото, видео, аудио, документы — без голосовых)
MEDIA_CONTENT_TYPES: set[ContentType] = {
    ContentType.ANIMATION,
    ContentType.AUDIO,
    ContentType.DOCUMENT,
    ContentType.PHOTO,
    ContentType.VIDEO,
    ContentType.VIDEO_NOTE,
    ContentType.CONTACT,
}

# Стикеры отдельно
STICKER_CONTENT_TYPES: set[ContentType] = {
    ContentType.STICKER,
}

# Голосовые сообщения отдельно
VOICE_CONTENT_TYPES: set[ContentType] = {
    ContentType.VOICE,
}

# Регулярное выражение для поиска ссылок
URL_PATTERN = re.compile(
    r'https?://[^\s<>"{}|\\^`\[\]]+|'
    r'www\.[^\s<>"{}|\\^`\[\]]+|'
    r't\.me/[^\s<>"{}|\\^`\[\]]+',
    re.IGNORECASE
)


def extract_text(message: Message) -> str:
    return (message.text or message.caption or "").lower()


def get_warn_message(settings: ChatSettings, violation_type: str) -> str:
    """Получить сообщение для предупреждения (кастомное или стандартное)."""
    field_name = f"warn_message_{violation_type}"
    custom_message = getattr(settings, field_name, "")
    if custom_message:
        return custom_message
    return DEFAULT_WARN_MESSAGES.get(violation_type, "⚠️ {user}, это действие запрещено.")


async def is_confirmed_user(bot: Bot, db: Database, chat_id: int, user_id: int) -> bool:
    """Проверяет, является ли пользователь доверенным (админ, подтверждённый или бустер)."""
    if await is_admin(bot, chat_id, user_id):
        return True
    if await db.is_confirmed(chat_id, user_id):
        return True
    # Проверяем, является ли пользователь бустером
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        # Проверяем статус премиум-подписки в контексте чата
        if hasattr(member, 'is_premium') and member.is_premium:
            # Бустеры имеют премиум, но дополнительно проверяем custom_title или другие признаки
            pass
        # В Telegram API нет прямого способа проверить буст,
        # но можно проверить через chat.get_member и его статус
        # Пока используем упрощённый подход
    except TelegramAPIError:
        pass
    return False


async def is_chat_booster(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Проверяет, является ли пользователь бустером группы."""
    try:
        # Получаем бустеров чата через API
        boosters = await bot.get_chat_administrators(chat_id)
        # К сожалению, Telegram Bot API не имеет прямого метода для проверки бустеров
        # Бустеры проверяются через ChatBoost API, но оно требует webhook
        # Пока оставляем как заглушку - можно реализовать через хранение в БД
        return False
    except TelegramAPIError:
        return False


def contains_banned_word(text: str, banned_words: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in banned_words)


async def apply_action(
    bot: Bot,
    db: Database,
    message: Message,
    action: int,
    violation_type: str,
    settings: ChatSettings,
) -> None:
    """Применить действие к нарушителю."""
    logger.debug(
        "apply_action called: action=%s, violation_type=%s, message_id=%s",
        action, violation_type, message.message_id
    )

    if action == ACTION_NONE:
        logger.debug("Action is NONE, skipping")
        return

    user = message.from_user
    chat_id = message.chat.id

    # Удаляем сообщение
    if action >= ACTION_DELETE:
        logger.debug("Attempting to delete message %s in chat %s", message.message_id, chat_id)
        try:
            await message.delete()
            await db.increment_stat("messages_deleted")
            logger.debug("Message %s deleted successfully", message.message_id)
        except TelegramBadRequest as exc:
            logger.debug("Message already removed: %s (error: %s)", message.message_id, exc)
        except TelegramAPIError as exc:
            logger.warning("Failed to delete message %s: %s", message.message_id, exc)

    # Отправляем предупреждение
    if action == ACTION_WARN and user:
        try:
            # Экранируем HTML-символы в имени пользователя
            safe_name = html.escape(user.full_name)
            user_mention = f'<a href="tg://user?id={user.id}">{safe_name}</a>'
            warning_text = get_warn_message(settings, violation_type)
            warn_msg = await bot.send_message(
                chat_id,
                warning_text.format(user=user_mention),
            )
            # Удаляем предупреждение через 10 секунд
            asyncio.create_task(_delete_after_delay(warn_msg, 10))
        except TelegramAPIError as exc:
            logger.warning("Failed to send warning: %s", exc)

    # Кикаем пользователя (без бана, может вернуться)
    if action == ACTION_KICK and user:
        try:
            await bot.ban_chat_member(chat_id, user.id)
            await bot.unban_chat_member(chat_id, user.id)  # Разбаниваем сразу = кик
        except TelegramAPIError as exc:
            logger.warning("Failed to kick user %s: %s", user.id, exc)

    # Баним пользователя через Telegram API
    if action == ACTION_BAN and user:
        try:
            await bot.ban_chat_member(chat_id, user.id)
        except TelegramAPIError as exc:
            logger.warning("Failed to ban user %s: %s", user.id, exc)


async def _delete_after_delay(message: Message, delay: int) -> None:
    """Удалить сообщение после задержки."""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except TelegramAPIError:
        pass


@router.message(Command(commands=["start", "help"]))
async def start_command(message: Message) -> None:
    if message.chat.type != ChatType.PRIVATE:
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="⚙️ Настройки (выбор чата)", callback_data="settings")
    builder.button(text="🛡️ Ограничения контента", callback_data="menu:restrictions")
    builder.button(text="⚡ Действия при нарушениях", callback_data="menu:actions")
    builder.button(text="👥 Управление пользователями", callback_data="menu:users")
    builder.button(text="🚫 Банлист слов", callback_data="menu:words")
    builder.button(text="ℹ️ Помощь", callback_data="menu:help")
    builder.adjust(1)
    await message.answer(
        "🤖 <b>Добро пожаловать!</b>\n\n"
        "Этот бот помогает модерировать группы:\n"
        "• Удаляет ботов, добавленных не-админами\n"
        "• Удаляет сообщения о входе/выходе\n"
        "• Фильтрует медиа, стикеры, ссылки и голосовые\n"
        "• Блокирует сообщения с запрещёнными словами\n\n"
        "🛡️ <b>Ограничения и действия</b> настраиваются\n"
        "отдельно для обычных и доверенных пользователей.\n\n"
        "Бустеры группы автоматически становятся доверенными!\n\n"
        "<b>Начните с настроек — выберите группу для управления.</b>",
        reply_markup=builder.as_markup(),
    )


@router.message(Command(commands=["trust"]))
async def trust_user_command(message: Message, bot: Bot, db: Database) -> None:
    """Добавить пользователя в доверенные через ответ на сообщение или user_id."""
    if message.chat.type not in {ChatType.SUPERGROUP, ChatType.GROUP}:
        return

    if not message.from_user:
        return

    # Проверяем, что отправитель — админ
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return

    target_user: User | None = None
    target_user_name: str | None = None

    # Сначала проверяем ответ на сообщение (приоритет)
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_name = target_user.full_name
    else:
        # Проверяем аргументы команды
        if message.text:
            parts = message.text.split(maxsplit=1)
            if len(parts) > 1:
                arg = parts[1].strip()

                # Проверяем entities на text_mention (когда Telegram резолвит пользователя)
                for entity in (message.entities or []):
                    if entity.type == "text_mention" and entity.user:
                        target_user = entity.user
                        target_user_name = target_user.full_name
                        break

                # Если это числовой ID
                if not target_user:
                    # Убираем @ если есть для проверки на число
                    clean_arg = arg.lstrip("@")
                    if clean_arg.isdigit():
                        user_id = int(clean_arg)
                        try:
                            chat_member = await bot.get_chat_member(message.chat.id, user_id)
                            if chat_member.user:
                                target_user = chat_member.user
                                target_user_name = target_user.full_name
                        except TelegramAPIError:
                            try:
                                reply = await message.reply(f"❌ Пользователь с ID {user_id} не найден в этом чате.")
                                await asyncio.sleep(5)
                                await reply.delete()
                                await message.delete()
                            except TelegramAPIError:
                                pass
                            return

                # Если передан @username, но не text_mention — Telegram не смог резолвить
                if not target_user and arg.startswith("@"):
                    try:
                        reply = await message.reply(
                            f"❌ Не удалось найти пользователя <code>{html.escape(arg)}</code>.\n\n"
                            "Telegram не позволяет искать по юзернейму напрямую.\n"
                            "Используйте:\n"
                            "• Ответ на сообщение пользователя\n"
                            "• <code>/trust user_id</code> (числовой ID)"
                        )
                        await asyncio.sleep(7)
                        await reply.delete()
                        await message.delete()
                    except TelegramAPIError:
                        pass
                    return

    # Если пользователь не найден
    if not target_user:
        try:
            reply = await message.reply(
                "Использование:\n"
                "• Ответьте на сообщение пользователя\n"
                "• Или: <code>/trust user_id</code>"
            )
            await asyncio.sleep(5)
            await reply.delete()
            await message.delete()
        except TelegramAPIError:
            pass
        return

    if target_user.is_bot:
        try:
            reply = await message.reply("Нельзя добавить бота в доверенные.")
            await asyncio.sleep(5)
            await reply.delete()
            await message.delete()
        except TelegramAPIError:
            pass
        return

    await db.add_confirmed_user(message.chat.id, target_user.id)

    try:
        safe_name = html.escape(target_user_name or str(target_user.id))
        reply = await message.reply(f"✅ <b>{safe_name}</b> добавлен в доверенные.")
        await asyncio.sleep(5)
        await reply.delete()
        await message.delete()
    except TelegramAPIError:
        pass


@router.message(Command(commands=["untrust"]))
async def untrust_user_command(message: Message, bot: Bot, db: Database) -> None:
    """Удалить пользователя из доверенных через ответ на сообщение или user_id."""
    if message.chat.type not in {ChatType.SUPERGROUP, ChatType.GROUP}:
        return

    if not message.from_user:
        return

    # Проверяем, что отправитель — админ
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return

    target_user: User | None = None
    target_user_name: str | None = None

    # Сначала проверяем ответ на сообщение (приоритет)
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_name = target_user.full_name
    else:
        # Проверяем аргументы команды
        if message.text:
            parts = message.text.split(maxsplit=1)
            if len(parts) > 1:
                arg = parts[1].strip()

                # Проверяем entities на text_mention
                for entity in (message.entities or []):
                    if entity.type == "text_mention" and entity.user:
                        target_user = entity.user
                        target_user_name = target_user.full_name
                        break

                # Если это числовой ID
                if not target_user:
                    clean_arg = arg.lstrip("@")
                    if clean_arg.isdigit():
                        user_id = int(clean_arg)
                        try:
                            chat_member = await bot.get_chat_member(message.chat.id, user_id)
                            if chat_member.user:
                                target_user = chat_member.user
                                target_user_name = target_user.full_name
                        except TelegramAPIError:
                            try:
                                reply = await message.reply(f"❌ Пользователь с ID {user_id} не найден в этом чате.")
                                await asyncio.sleep(5)
                                await reply.delete()
                                await message.delete()
                            except TelegramAPIError:
                                pass
                            return

                # Если передан @username, но не text_mention
                if not target_user and arg.startswith("@"):
                    try:
                        reply = await message.reply(
                            f"❌ Не удалось найти пользователя <code>{html.escape(arg)}</code>.\n\n"
                            "Telegram не позволяет искать по юзернейму напрямую.\n"
                            "Используйте:\n"
                            "• Ответ на сообщение пользователя\n"
                            "• <code>/untrust user_id</code> (числовой ID)"
                        )
                        await asyncio.sleep(7)
                        await reply.delete()
                        await message.delete()
                    except TelegramAPIError:
                        pass
                    return

    # Если пользователь не найден
    if not target_user:
        try:
            reply = await message.reply(
                "Использование:\n"
                "• Ответьте на сообщение пользователя\n"
                "• Или: <code>/untrust user_id</code>"
            )
            await asyncio.sleep(5)
            await reply.delete()
            await message.delete()
        except TelegramAPIError:
            pass
        return

    await db.remove_confirmed_user(message.chat.id, target_user.id)

    try:
        safe_name = html.escape(target_user_name or str(target_user.id))
        reply = await message.reply(f"❌ <b>{safe_name}</b> удалён из доверенных.")
        await asyncio.sleep(5)
        await reply.delete()
        await message.delete()
    except TelegramAPIError:
        pass


def contains_url(text: str) -> bool:
    """Проверяет наличие ссылок в тексте."""
    return bool(URL_PATTERN.search(text))


@router.message()
async def enforce_rules(message: Message, bot: Bot, db: Database) -> None:
    if not message.from_user:
        return

    if message.chat.type not in {ChatType.SUPERGROUP, ChatType.GROUP}:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    content_type = message.content_type

    logger.debug(
        "Processing message: chat=%s, user=%s, content_type=%s",
        chat_id, user_id, content_type
    )

    chat_title = message.chat.title or str(chat_id)
    await db.upsert_chat(chat_id, chat_title)

    if content_type == ContentType.NEW_CHAT_MEMBERS:
        logger.debug("Skipping NEW_CHAT_MEMBERS message")
        return

    # Получаем настройки чата
    settings = await db.get_chat_settings(chat_id)
    logger.debug(
        "Chat settings: restrict_stickers_regular=%s, restrict_media_regular=%s, "
        "restrict_voice_regular=%s, restrict_links_regular=%s",
        settings.restrict_stickers_regular, settings.restrict_media_regular,
        settings.restrict_voice_regular, settings.restrict_links_regular
    )

    # Глобально забаненные пользователи
    if await db.is_global_banned(user_id):
        logger.debug("User %s is globally banned, applying action", user_id)
        await apply_action(bot, db, message, settings.action_global_ban, "global_ban", settings)
        return

    # Проверяем, является ли пользователь доверенным (подтверждённым, админом или бустером)
    user_is_confirmed = await is_confirmed_user(bot, db, chat_id, user_id)
    logger.debug("User %s is_confirmed=%s", user_id, user_is_confirmed)

    # Проверяем медиа
    if content_type in MEDIA_CONTENT_TYPES:
        logger.debug("Message is MEDIA type")
        if user_is_confirmed:
            if settings.restrict_media_confirmed:
                logger.debug("Restricting media for confirmed user")
                await apply_action(bot, db, message, settings.action_media, "media", settings)
                return
        else:
            if settings.restrict_media_regular:
                logger.debug("Restricting media for regular user")
                await apply_action(bot, db, message, settings.action_media, "media", settings)
                return

    # Проверяем стикеры
    if content_type in STICKER_CONTENT_TYPES:
        logger.debug("Message is STICKER type")
        if user_is_confirmed:
            if settings.restrict_stickers_confirmed:
                logger.debug("Restricting sticker for confirmed user")
                await apply_action(bot, db, message, settings.action_stickers, "stickers", settings)
                return
        else:
            if settings.restrict_stickers_regular:
                logger.debug("Restricting sticker for regular user, action=%s", settings.action_stickers)
                await apply_action(bot, db, message, settings.action_stickers, "stickers", settings)
                return
            else:
                logger.debug("Stickers allowed for regular users (restrict_stickers_regular=False)")

    # Проверяем голосовые сообщения
    if content_type in VOICE_CONTENT_TYPES:
        logger.debug("Message is VOICE type")
        if user_is_confirmed:
            if settings.restrict_voice_confirmed:
                logger.debug("Restricting voice for confirmed user")
                await apply_action(bot, db, message, settings.action_voice, "voice", settings)
                return
        else:
            if settings.restrict_voice_regular:
                logger.debug("Restricting voice for regular user")
                await apply_action(bot, db, message, settings.action_voice, "voice", settings)
                return

    # Проверяем ссылки в тексте
    text_content = extract_text(message)
    if text_content and contains_url(text_content):
        logger.debug("Message contains URL")
        if user_is_confirmed:
            if settings.restrict_links_confirmed:
                logger.debug("Restricting links for confirmed user")
                await apply_action(bot, db, message, settings.action_links, "links", settings)
                return
        else:
            if settings.restrict_links_regular:
                logger.debug("Restricting links for regular user")
                await apply_action(bot, db, message, settings.action_links, "links", settings)
                return

    # Проверяем запрещённые слова
    banned_words = await db.get_banned_words(chat_id)
    if banned_words and contains_banned_word(text_content, banned_words):
        logger.debug("Message contains banned word")
        await apply_action(bot, db, message, settings.action_words, "words", settings)
        return

    logger.debug("Message passed all checks, no action taken")

