import os
import httpx
import asyncio

async def test():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("Error: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set in the environment.")
        return
        
    print(f"Testing Telegram Bot...")
    print(f"Bot Token (first 6 chars): {token[:6]}...")
    print(f"Chat ID: {chat_id}")
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "🤖 *IT Elevplads Scraper*\nТестовое сообщение: Бот успешно подключен к каналу!",
        "parse_mode": "Markdown"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, timeout=10.0)
            if resp.status_code == 200:
                print("✅ Success! Test message sent to Telegram.")
            else:
                print(f"❌ Failed! Telegram API returned {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"❌ Error sending message: {e}")

if __name__ == "__main__":
    asyncio.run(test())
