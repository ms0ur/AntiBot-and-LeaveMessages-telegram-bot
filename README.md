# AntiBot-and-LeaveMessages-telegram-bot

[![built with Codeium](https://codeium.com/badges/main)](https://codeium.com)

this bot will delete all added bot from non-admin users of chat. Additionaly removes a "X joined to chat"(or something like that) or "X leave chat" messages

##WARNING!
all messages(only one message lol) now only in russian. To change messages go to line 48 and modificate:
```
reply_message = await message.reply(f"Был забанен бот || {member.first_name} || за добавление пользователем, неимеющего админских прав.")
```
to 
```
reply_message = await message.reply(f"Bot || {member.first_name} || was banned, for beeing added by user, without admin rights.")
```

## Requried packages
- aiogram

## How to setup
Change `API_TOKEN ` in line 9
run `python3 bot.py`
add bot to chats
enjoy!
