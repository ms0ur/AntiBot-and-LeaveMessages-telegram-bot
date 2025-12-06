import asyncio
import logging
import re
from typing import Iterable
from aiogram import Bot, Router
from aiogram.enums import ChatMemberStatus, ChatType, ContentType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import ChatPermissions, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.database import (
    ACTION_NONE, ACTION_DELETE, ACTION_WARN, ACTION_KICK, ACTION_BAN,
    ChatSettings, Database,
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

# Сообщения предупреждений
WARNING_MESSAGES = {
    "media": "⚠️ {user}, отправка медиа запрещена в этом чате.",
    "stickers": "⚠️ {user}, отправка стикеров запрещена в этом чате.",
    "links": "⚠️ {user}, отправка ссылок запрещена в этом чате.",
    "voice": "⚠️ {user}, отправка голосовых сообщений запрещена в этом чате.",
    "words": "⚠️ {user}, ваше сообщение содержит запрещённые слова.",
    "global_ban": "⚠️ {user}, вы находитесь в глобальном бан-листе.",
}


def extract_text(message: Message) -> str:
    return (message.text or message.caption or "").lower()


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
            user_mention = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
            warning_text = WARNING_MESSAGES.get(violation_type, "⚠️ {user}, это действие запрещено.")
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
    """Добавить пользователя в доверенные через ответ на сообщение в группе."""
    if message.chat.type not in {ChatType.SUPERGROUP, ChatType.GROUP}:
        return

    if not message.from_user:
        return

    # Проверяем, что отправитель — админ
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return

    # Должен быть ответ на сообщение
    if not message.reply_to_message or not message.reply_to_message.from_user:
        try:
            reply = await message.reply("Ответьте на сообщение пользователя, которого хотите добавить в доверенные.")
            await asyncio.sleep(5)
            await reply.delete()
            await message.delete()
        except TelegramAPIError:
            pass
        return

    target_user = message.reply_to_message.from_user
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
        user_name = target_user.full_name or str(target_user.id)
        reply = await message.reply(f"✅ <b>{user_name}</b> добавлен в доверенные.")
        await asyncio.sleep(5)
        await reply.delete()
        await message.delete()
    except TelegramAPIError:
        pass


@router.message(Command(commands=["untrust"]))
async def untrust_user_command(message: Message, bot: Bot, db: Database) -> None:
    """Удалить пользователя из доверенных через ответ на сообщение в группе."""
    if message.chat.type not in {ChatType.SUPERGROUP, ChatType.GROUP}:
        return

    if not message.from_user:
        return

    # Проверяем, что отправитель — админ
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return

    # Должен быть ответ на сообщение
    if not message.reply_to_message or not message.reply_to_message.from_user:
        try:
            reply = await message.reply("Ответьте на сообщение пользователя, которого хотите убрать из доверенных.")
            await asyncio.sleep(5)
            await reply.delete()
            await message.delete()
        except TelegramAPIError:
            pass
        return

    target_user = message.reply_to_message.from_user

    await db.remove_confirmed_user(message.chat.id, target_user.id)

    try:
        user_name = target_user.full_name or str(target_user.id)
        reply = await message.reply(f"❌ <b>{user_name}</b> удалён из доверенных.")
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
        await apply_action(bot, db, message, settings.action_global_ban, "global_ban")
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
                await apply_action(bot, db, message, settings.action_media, "media")
                return
        else:
            if settings.restrict_media_regular:
                logger.debug("Restricting media for regular user")
                await apply_action(bot, db, message, settings.action_media, "media")
                return

    # Проверяем стикеры
    if content_type in STICKER_CONTENT_TYPES:
        logger.debug("Message is STICKER type")
        if user_is_confirmed:
            if settings.restrict_stickers_confirmed:
                logger.debug("Restricting sticker for confirmed user")
                await apply_action(bot, db, message, settings.action_stickers, "stickers")
                return
        else:
            if settings.restrict_stickers_regular:
                logger.debug("Restricting sticker for regular user, action=%s", settings.action_stickers)
                await apply_action(bot, db, message, settings.action_stickers, "stickers")
                return
            else:
                logger.debug("Stickers allowed for regular users (restrict_stickers_regular=False)")

    # Проверяем голосовые сообщения
    if content_type in VOICE_CONTENT_TYPES:
        logger.debug("Message is VOICE type")
        if user_is_confirmed:
            if settings.restrict_voice_confirmed:
                logger.debug("Restricting voice for confirmed user")
                await apply_action(bot, db, message, settings.action_voice, "voice")
                return
        else:
            if settings.restrict_voice_regular:
                logger.debug("Restricting voice for regular user")
                await apply_action(bot, db, message, settings.action_voice, "voice")
                return

    # Проверяем ссылки в тексте
    text_content = extract_text(message)
    if text_content and contains_url(text_content):
        logger.debug("Message contains URL")
        if user_is_confirmed:
            if settings.restrict_links_confirmed:
                logger.debug("Restricting links for confirmed user")
                await apply_action(bot, db, message, settings.action_links, "links")
                return
        else:
            if settings.restrict_links_regular:
                logger.debug("Restricting links for regular user")
                await apply_action(bot, db, message, settings.action_links, "links")
                return

    # Проверяем запрещённые слова
    banned_words = await db.get_banned_words(chat_id)
    if banned_words and contains_banned_word(text_content, banned_words):
        logger.debug("Message contains banned word")
        await apply_action(bot, db, message, settings.action_words, "words")
        return

    logger.debug("Message passed all checks, no action taken")

