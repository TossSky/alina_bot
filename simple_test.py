# simple_test.py - упрощенный тест без transport
import asyncio
import httpx
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os

load_dotenv()

async def simple_test():
    """Простой тест без дополнительных параметров"""
    
    api_key = os.getenv("OPENAI_API_KEY")
    use_proxy = os.getenv("OPENAI_USE_PROXY", "false").lower() == "true"
    proxy_address = os.getenv("OPENAI_PROXY_ADDRESS", "")
    model = os.getenv("OPENAI_MODEL", "gpt-5-mini-2025-08-07")
    
    print("🧪 Простой тест подключения...")
    print(f"🌐 Прокси: {'включен' if use_proxy else 'отключен'}")
    
    try:
        # Простой HTTP клиент
        if use_proxy and proxy_address:
            print(f"📡 Используем прокси: {proxy_address}")
            http_client = httpx.AsyncClient(proxy=proxy_address)
        else:
            print("📡 Прямое подключение")
            http_client = httpx.AsyncClient()
        
        print("✅ HTTP клиент создан")
        
        # OpenAI клиент
        client = AsyncOpenAI(
            api_key=api_key,
            http_client=http_client
        )
        print("✅ OpenAI клиент создан")
        
        # Тест запроса
        print("🚀 Тестовый запрос...")
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say 'Hello test'"}],
            max_tokens=10
        )
        
        print(f"✅ Успех! Ответ: {response.choices[0].message.content}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        print(f"   Тип ошибки: {type(e).__name__}")
    
    finally:
        try:
            await http_client.aclose()
            print("✅ Клиент закрыт")
        except:
            pass

if __name__ == "__main__":
    asyncio.run(simple_test())