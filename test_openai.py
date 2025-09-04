# test_gpt_4o_mini.py - тест новой быстрой модели gpt-4o-mini
import asyncio
import httpx
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os
import time

load_dotenv()

async def test_gpt_4o_mini():
    """Тестирует подключение и скорость gpt-4o-mini"""
    
    api_key = os.getenv("OPENAI_API_KEY")
    use_proxy = os.getenv("OPENAI_USE_PROXY", "false").lower() == "true"
    proxy_address = os.getenv("OPENAI_PROXY_ADDRESS", "")
    model = "gpt-4o-mini"  # Принудительно используем gpt-4o-mini
    
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
            timeout=httpx.Timeout(30.0, connect=10.0)
        )
        print("✅ HTTP клиент с прокси создан")
    else:
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0)
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
    
    # Тест 1: Короткий ответ
    try:
        print("\n📝 Тест 1: Короткий ответ")
        start = time.time()
        
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Отвечай коротко и дружелюбно."},
                {"role": "user", "content": "Привет! Как дела?"}
            ],
            max_tokens=100,
            temperature=0.3,
            presence_penalty = 0,
            frequency_penalty = 0,
            top_p=1
        )
        
        elapsed = time.time() - start
        message = response.choices[0].message.content
        
        print(f"✅ Ответ получен за {elapsed:.2f} сек")
        print(f"📝 Ответ: {message}")
        print(f"📊 Токены: {response.usage.total_tokens if response.usage else 'неизвестно'}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    
    # Тест 2: Средний ответ
    try:
        print("\n📝 Тест 2: Средний ответ")
        start = time.time()
        
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Ты Алина, дружелюбная девушка."},
                {"role": "user", "content": "Расскажи мне что-нибудь интересное о космосе"}
            ],
            max_tokens=500,
            temperature=0.3,
            presence_penalty = 0,
            frequency_penalty = 0,
            top_p=1
        )
        
        elapsed = time.time() - start
        message = response.choices[0].message.content
        
        print(f"✅ Ответ получен за {elapsed:.2f} сек")
        print(f"📝 Ответ ({len(message)} символов): {message[:200]}...")
        print(f"📊 Токены: {response.usage.total_tokens if response.usage else 'неизвестно'}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    
    # Тест 3: Длинный список
    try:
        print("\n📝 Тест 3: Длинный список")
        start = time.time()
        
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Отвечай полно, с переносами строк между пунктами."},
                {"role": "user", "content": "Назови 10 интересных фактов о зебрах"}
            ],
            max_tokens=1500,
            temperature=0.3,
            presence_penalty = 0,
            frequency_penalty = 0,
            top_p=1
        )
        
        elapsed = time.time() - start
        message = response.choices[0].message.content
        
        print(f"✅ Ответ получен за {elapsed:.2f} сек")
        print(f"📝 Ответ ({len(message)} символов):")
        print(message)
        print(f"📊 Токены: {response.usage.total_tokens if response.usage else 'неизвестно'}")
        print(f"📊 Finish reason: {response.choices[0].finish_reason}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    
    finally:
        # Закрываем клиенты
        try:
            await client.close()
            await http_client.aclose()
            print("\n✅ Клиенты закрыты")
        except Exception as e:
            print(f"⚠️ Ошибка при закрытии: {e}")
    
    print("\n📈 ИТОГИ:")
    print("- gpt-4o-mini - самая быстрая модель для чат-ботов")
    print("- Оптимальные настройки: max_tokens=800-1500 для обычных ответов")
    print("- Для списков можно увеличить до 1500 токенов")
    print("- Короткие ответы можно ограничить 300 токенами")

if __name__ == "__main__":
    asyncio.run(test_gpt_4o_mini())