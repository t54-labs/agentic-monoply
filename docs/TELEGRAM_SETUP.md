# Telegram Notification Setup Guide

This guide will help you set up a Telegram Bot to monitor the status of the Monopoly game server.

## 🤖 Step 1: Create a Telegram Bot

1. Find [@BotFather](https://t.me/botfather) in Telegram
2. Send the `/newbot` command
3. Follow the prompts to set your bot’s name and username
4. Save the **Bot Token** provided by BotFather

## 📢 Step 2: Create a Notification Group

1. Create a new Telegram group to receive game notifications
2. Add the bot you just created to the group
3. Grant the bot admin rights (ability to send messages)

## 🔍 Step 3: Get the Group Chat ID

1. Send any message in the group
2. Visit the following URL (replace `<YOUR_BOT_TOKEN>` with your actual bot token):

   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
   ```
3. In the returned JSON, find the value of the `chat.id` field
4. Save this **Chat ID** (it is usually a negative number)

## ⚙️ Step 4: Configure Environment Variables

Add the following configuration to your `.env` file:

```env
# Telegram Bot Notification Configuration
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_group_chat_id
```

### Example configuration:

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=-1001234567890
```

## 🚀 Step 5: Verify the Setup

1. Restart the Monopoly game server
2. Check the server startup log, you should see:

   ```
   ✅ Telegram notifier initialized successfully
   ```
3. If configured correctly, the group will receive a server startup notification

## 📱 Notification Content

Once configured, you will receive the following types of notifications:

### 🚀 Server Status Notifications

* **Server Start**: When the game server starts
* **Server Shutdown**: When the server shuts down
* **Maintenance Check**: Periodic system maintenance updates

### 🎮 Game-Related Notifications

* **Game Start**: New game begins, includes player info
* **Turn Summary**: Sent every 5 turns to avoid spamming
* **Game End**: Game over with final rankings
* **Special Events**: Key game events (e.g. jail, bankruptcy, major trades)

### 🚨 Error Notifications

* **Critical Errors**: Detailed messages when the server encounters major issues

## 🔧 Troubleshooting

### Problem: Not Receiving Notifications

1. Check if the Bot Token is correct
2. Make sure the bot is added to the group and has permission to send messages
3. Verify the Chat ID is correct (usually a negative number)
4. Review error messages in the server log

### Problem: Notification Format Issues

* Ensure you are using `python-telegram-bot>=20.0`
* Check if all server dependencies are correctly installed

### Problem: Too Many Notifications

* Turn summary notifications are sent every 5 turns by default
* You can adjust the frequency in `game_event_handler.py`

## 📝 Advanced Configuration

You can customize the following in `game_event_handler.py`:

* Notification frequency
* Message format
* Notification type filtering

## 🔒 Security Tips

1. **Do not share** your Bot Token and Chat ID publicly
2. Regularly check group members to ensure only authorized personnel are present
3. Consider creating a dedicated notification group for the production environment

---

If you encounter any issues, check the `[GameEventHandler]` and `[Telegram]` messages in the server logs.
