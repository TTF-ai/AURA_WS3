# AURA Emergency Alert System

This package subscribes to `/behavior/event` and `/camera/image_raw` to capture evidence and notify guardians via Telegram when a fall is confirmed.

## Telegram Bot & Group Setup Instructions

Follow these steps to configure the Telegram notification channel:

1. **Create a Telegram Bot**:
   - Open Telegram and search for **@BotFather**.
   - Send `/newbot` and follow the instructions to choose a name and username.
   - Save the **API Token** provided (e.g., `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`).

2. **Create the Guardian Group**:
   - Create a new Telegram Group containing the family members or caregivers (guardians).
   - Add your newly created Bot as a member of this group.

3. **Obtain the Chat ID**:
   - Send a test message in the group (e.g., "Hello AURA").
   - Open your web browser or run curl to query the bot updates:
     `curl https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
   - Search for `"chat":{"id":-...` in the JSON response. Note that group chat IDs are typically negative numbers (e.g., `-1002234567890`).

4. **Configure Environment Variables**:
   - Copy the `.env.example` file to `.env`:
     `cp src/aura_alert/.env.example src/aura_alert/.env`
   - Open `.env` and fill in the token and chat ID:
     ```env
     TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
     TELEGRAM_CHAT_ID=-1002234567890
     ```
   - Export these environment variables in your terminal:
     ```bash
     export TELEGRAM_BOT_TOKEN="..."
     export TELEGRAM_CHAT_ID="..."
     ```

5. **Run the Telegram Connection Test**:
   - Launching the ROS 2 node will automatically run a connection check (`getMe`).
   - Look at the logs for `Telegram connection verified` or check `/alert/status`.

6. **Trigger a Test Alert**:
   - Run the manual test ROS 2 service:
     ```bash
     ros2 service call /aura_alert/test std_srvs/srv/Trigger "{}"
     ```
   - The bot will immediately post a test alert containing the latest camera frame to your Telegram group.
