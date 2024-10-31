import asyncio
import re
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware

##BY MS0UR


API_TOKEN = 'TOKEN'
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

# Regular expression pattern to match RTL characters
rtl_pattern = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u0590-\u05FF]+')

def has_rtl(text):
    """
    Checks if the given text contains any right-to-left (RTL) characters.

    Parameters:
        text (str): The text to be checked.

    Returns:
        bool: True if the text contains RTL characters, False otherwise.
    """
    return bool(rtl_pattern.search(text))
####################################################################################################################################################################################################################################################################################################BY ms0ur
async def delete_bot_messages(chat_id, bot_user_id):
    """
    Deletes recent messages from the specified bot in the chat.
    """
    async for message in bot.get_chat_history(chat_id, limit=100):  # Укажите лимит, например 100
        if message.from_user and message.from_user.id == bot_user_id:
            try:
                await bot.delete_message(chat_id, message.message_id)
            except Exception as e:
                print(f"Не удалось удалить сообщение: {e}")

async def delete_message_delayed(chat_id, message_id, delay=0):
    """
    Deletes a message with a delay.

    Parameters:
        chat_id (int): ID of the chat.
        message_id (int): ID of the message.
        delay (int): Delay in seconds before deleting the message (default is 0).
    """
    await asyncio.sleep(delay)
    await bot.delete_message(chat_id=chat_id, message_id=message_id)

@dp.message_handler(content_types=types.ContentType.NEW_CHAT_MEMBERS)
async def on_new_chat_members(message: types.Message):
    for member in message.new_chat_members:
        if member.is_bot:
            chat_member = await bot.get_chat_member(message.chat.id, message.from_user.id)
            if chat_member.status not in ['administrator', 'creator']:
                await bot.kick_chat_member(message.chat.id, member.id)
                reply_message = await message.reply(f"Был забанен бот || {member.first_name} || за добавление пользователем, неимеющего админских прав.") ##BY MS0UR
                await delete_bot_messages(message.chat.id, member.id)
                asyncio.create_task(delete_message_delayed(message.chat.id, reply_message.message_id, delay=5))
                asyncio.create_task(delete_message_delayed(message.chat.id, message.message_id, delay=5))
                
            else:
                asyncio.create_task(delete_message_delayed(message.chat.id, message.message_id, delay=5))
        else:
            asyncio.create_task(delete_message_delayed(message.chat.id, message.message_id, delay=5))

@dp.message_handler(content_types=types.ContentType.LEFT_CHAT_MEMBER)
async def cleanup_leave_messages(message: types.Message):
    asyncio.create_task(delete_message_delayed(message.chat.id, message.message_id, delay=5)) 

# Start the bot
if __name__ == '__main__':
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
