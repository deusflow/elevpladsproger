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

    url = f"{SUPABASE_URL}/rest/v1/state?key=eq.scraper_state"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    print(f"Подключение к Supabase: {SUPABASE_URL}")
    print("Удаление ключа 'scraper_state'...")

    async with httpx.AsyncClient() as client:
        # Отправляем DELETE запрос
        resp = await client.delete(url, headers=headers)
        
        if resp.status_code in [200, 204]:
            print("✅ Состояние (scraper_state) успешно удалено из Supabase!")
        else:
            print(f"❌ Ошибка при удалении: {resp.status_code} - {resp.text}")
            
    # Также очищаем локальные fallback-файлы, если они есть
    for file in ["jobs_db.json", "jobs_db_fallback.json"]:
        if os.path.exists(file):
            os.remove(file)
            print(f"🗑 Удален локальный кэш: {file}")

if __name__ == "__main__":
    asyncio.run(clear_supabase_state())
