# test_openai.py - быстрый тест OpenAI подключения
import asyncio
import httpx
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os

load_dotenv()

async def test_openai_connection():
    """Тестирует подключение к OpenAI через прокси"""
    
    api_key = os.getenv("OPENAI_API_KEY")
    use_proxy = os.getenv("OPENAI_USE_PROXY", "false").lower() == "true"
    proxy_address = os.getenv("OPENAI_PROXY_ADDRESS", "")
    model = os.getenv("OPENAI_MODEL", "gpt-5-mini-2025-08-07")
    
    if not api_key:
        print("❌ OPENAI_API_KEY не задан")
        return
    
    print(f"🔑 API Key: {api_key[:10]}...")
    print(f"🌐 Прокси: {'включен' if use_proxy else 'отключен'}")
    print(f"📡 Адрес прокси: {proxy_address if use_proxy else 'не используется'}")
    print(f"🤖 Модель: {model}")
    print()
    
    # Создаем HTTP клиент
    if use_proxy and proxy_address:
        http_client = httpx.AsyncClient(
            proxy=proxy_address,
            timeout=httpx.Timeout(20.0, connect=5.0)
        )
        print("✅ HTTP клиент с прокси создан")
    else:
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=5.0)
        )
        print("✅ HTTP клиент без прокси создан")
    
    # Создаем OpenAI клиент
    try:
        client = AsyncOpenAI(
            api_key=api_key,
            http_client=http_client,
            max_retries=2
        )
        print("✅ OpenAI клиент создан")
    except Exception as e:
        print(f"❌ Ошибка создания клиента: {e}")
        return
    
    # Тестируем запрос
    try:
        print("🚀 Отправляем тестовый запрос...")
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Ответь коротко и дружелюбно."},
                {"role": "user", "content": "Привет! Как дела?"}
            ],
            max_completion_tokens=100,
            temperature=1
        )
        
        message = response.choices[0].message.content
        print(f"✅ Ответ получен: {message}")
        print(f"📊 Использовано токенов: {response.usage.total_tokens if response.usage else 'неизвестно'}")
        
    except Exception as e:
        print(f"❌ Ошибка запроса: {e}")
    
    finally:
        # Закрываем клиенты
        try:
            await client.close()
            print("✅ Клиенты закрыты")
        except Exception as e:
            print(f"⚠️ Ошибка при закрытии: {e}")

if __name__ == "__main__":
    asyncio.run(test_openai_connection())