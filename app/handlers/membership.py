import asyncio
import logging
from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import ChatBoostUpdated, Message
from app.database import ACTION_NONE, ACTION_DELETE, ACTION_WARN, ACTION_KICK, ACTION_BAN, Database
from app.utils import is_admin

router = Router()

logger = logging.getLogger(__name__)


async def _delete_join_leave(message: Message) -> None:
    try:
        await asyncio.sleep(3)
        await message.delete()
    except TelegramBadRequest:
        logger.debug("Join/leave message already removed or too old: %s", message.message_id)
    except TelegramAPIError as exc:
        logger.warning("Failed to delete join/leave message %s: %s", message.message_id, exc)


async def _apply_bot_action(bot: Bot, db: Database, message: Message, action: int, added_bot_id: int) -> None:
    """Применить действие за добавление бота не-админом."""
    user = message.from_user
    chat_id = message.chat.id

    if action == ACTION_NONE:
        return

    # Всегда баним добавленного бота
    try:
        await bot.ban_chat_member(chat_id, added_bot_id)
        await db.increment_stat("bots_banned")
    except TelegramAPIError as exc:
        logger.warning("Failed to ban bot %s: %s", added_bot_id, exc)

    # Удаляем сообщение о добавлении
    if action >= ACTION_DELETE:
        try:
            await message.delete()
        except TelegramAPIError:
            pass

    # Предупреждаем пользователя
    if action == ACTION_WARN and user:
        try:
            user_mention = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
            warn_msg = await bot.send_message(
                chat_id,
                f"⚠️ {user_mention}, добавлять ботов могут только администраторы!",
            )
            await asyncio.sleep(10)
            await warn_msg.delete()
        except TelegramAPIError:
            pass

    # Кикаем пользователя
    if action == ACTION_KICK and user:
        try:
            await bot.ban_chat_member(chat_id, user.id)
            await bot.unban_chat_member(chat_id, user.id)
        except TelegramAPIError as exc:
            logger.warning("Failed to kick user %s: %s", user.id, exc)

    # Баним пользователя
    if action == ACTION_BAN and user:
        try:
            await bot.ban_chat_member(chat_id, user.id)
        except TelegramAPIError as exc:
            logger.warning("Failed to ban user %s: %s", user.id, exc)


@router.message(F.new_chat_members)
async def handle_new_members(message: Message, bot: Bot, db: Database) -> None:
    if message.chat.type not in {ChatType.SUPERGROUP, ChatType.GROUP}:
        return

    if not message.from_user:
        return

    chat_title = message.chat.title or str(message.chat.id)
    await db.upsert_chat(message.chat.id, chat_title)

    adder_is_admin = await is_admin(bot, message.chat.id, message.from_user.id)
    settings = await db.get_chat_settings(message.chat.id)

    for member in message.new_chat_members:
        if member.is_bot and not adder_is_admin:
            # Применяем настроенное действие
            await _apply_bot_action(bot, db, message, settings.action_bots, member.id)
        elif not member.is_bot:
            await _delete_join_leave(message)


@router.message(F.left_chat_member)
async def handle_left_member(message: Message) -> None:
    if message.chat.type not in {ChatType.SUPERGROUP, ChatType.GROUP}:
        return

    await _delete_join_leave(message)


# Обработка миграции группы в супергруппу
@router.message(F.migrate_to_chat_id)
async def handle_migrate_to_supergroup(message: Message, db: Database) -> None:
    """Когда группа мигрирует в супергруппу, переносим все данные на новый ID."""
    old_chat_id = message.chat.id
    new_chat_id = message.migrate_to_chat_id

    logger.info("Chat %s migrated to supergroup %s", old_chat_id, new_chat_id)

    # Переносим все данные на новый ID
    await db.migrate_chat(old_chat_id, new_chat_id)

    # Обновляем название чата
    chat_title = message.chat.title or str(new_chat_id)
    await db.upsert_chat(new_chat_id, chat_title)


@router.message(F.migrate_from_chat_id)
async def handle_migrate_from_group(message: Message, db: Database) -> None:
    """Обработка события в новой супергруппе после миграции."""
    old_chat_id = message.migrate_from_chat_id
    new_chat_id = message.chat.id

    logger.info("Supergroup %s created from group %s", new_chat_id, old_chat_id)

    # На всякий случай переносим данные ещё раз
    await db.migrate_chat(old_chat_id, new_chat_id)

    # Регистрируем новый чат
    chat_title = message.chat.title or str(new_chat_id)
    await db.upsert_chat(new_chat_id, chat_title)


# Обработка бустов группы - бустеры автоматически становятся доверенными (если включено)
@router.chat_boost()
async def handle_chat_boost(boost: ChatBoostUpdated, db: Database) -> None:
    """Когда пользователь бустит группу, добавляем его в доверенные (если настройка включена)."""
    chat_id = boost.chat.id

    # Проверяем настройку trust_boosters
    settings = await db.get_chat_settings(chat_id)
    if not settings.trust_boosters:
        return

    # Получаем пользователя из буста
    if boost.boost and boost.boost.source:
        user = getattr(boost.boost.source, 'user', None)
        if user and not user.is_bot:
            await db.add_confirmed_user(chat_id, user.id)
            logger.info("User %s added to confirmed (boosted chat %s)", user.id, chat_id)


@router.removed_chat_boost()
async def handle_removed_chat_boost(boost: ChatBoostUpdated, db: Database) -> None:
    """Когда пользователь убирает буст, убираем его из доверенных (если настройка включена)."""
    chat_id = boost.chat.id

    # Проверяем настройку trust_boosters
    settings = await db.get_chat_settings(chat_id)
    if not settings.trust_boosters:
        return

    if boost.boost and boost.boost.source:
        user = getattr(boost.boost.source, 'user', None)
        if user:
            await db.remove_confirmed_user(chat_id, user.id)
            logger.info("User %s removed from confirmed (removed boost from chat %s)", user.id, chat_id)

