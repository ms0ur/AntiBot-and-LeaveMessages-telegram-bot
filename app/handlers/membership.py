import asyncio
from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.enums.chat_member_status import ChatMemberStatus
from aiogram.types import Message
from app.database import Database

router = Router()


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


async def _delete_join_leave(message: Message) -> None:
    try:
        await asyncio.sleep(3)
        await message.delete()
    except Exception:
        pass


@router.message(F.new_chat_members)
async def handle_new_members(message: Message, bot: Bot, db: Database) -> None:
    if message.chat.type not in {ChatType.SUPERGROUP, ChatType.GROUP}:
        return

    if not message.from_user:
        return

    chat_title = message.chat.title or str(message.chat.id)
    await db.upsert_chat(message.chat.id, chat_title)

    adder_is_admin = await is_admin(bot, message.chat.id, message.from_user.id)

    for member in message.new_chat_members:
        if member.is_bot and not adder_is_admin:
            await bot.ban_chat_member(chat_id=message.chat.id, user_id=member.id)
            try:
                await message.delete()
            except Exception:
                pass
        elif not member.is_bot:
            await _delete_join_leave(message)


@router.message(F.left_chat_member)
async def handle_left_member(message: Message) -> None:
    if message.chat.type not in {ChatType.SUPERGROUP, ChatType.GROUP}:
        return

    await _delete_join_leave(message)
