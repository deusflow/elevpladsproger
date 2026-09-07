import httpx
import os
import asyncio
from dotenv import load_dotenv

async def clear_supabase_state():
    load_dotenv()
    
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Ошибка: SUPABASE_URL или SUPABASE_KEY не найдены в переменных окружения.")
        return

    state_keys = ["jobs_state", "news_state", "scraper_state"]
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    print(f"Подключение к Supabase: {SUPABASE_URL}")

    async with httpx.AsyncClient() as client:
        for key in state_keys:
            url = f"{SUPABASE_URL}/rest/v1/state?key=eq.{key}"
            resp = await client.delete(url, headers=headers)
            if resp.status_code in [200, 204]:
                print(f"✅ Ключ '{key}' успешно удален из Supabase!")
            else:
                print(f"⚠️ Ошибка при удалении '{key}': {resp.status_code} - {resp.text}")
            
    # Также очищаем локальные fallback-файлы, если они есть
    for file in ["jobs_db.json", "jobs_db_fallback.json", "jobs_state_fallback.json", "news_state_fallback.json"]:
        if os.path.exists(file):
            os.remove(file)
            print(f"🗑 Удален локальный кэш: {file}")

if __name__ == "__main__":
    asyncio.run(clear_supabase_state())
