# test_gemini_proxy.py
import os
import asyncio
import google.generativeai as genai
from dotenv import load_dotenv
from google.api_core import exceptions

async def run_test():
    """
    Тестовый скрипт для проверки Gemini API через прокси.
    Эта версия напрямую использует переменные окружения, которые
    автоматически подхватываются библиотекой Google.
    """
    print("--- Запуск теста Gemini API с поддержкой прокси ---")
    load_dotenv()

    # 1. Применение настроек прокси
    use_proxy_str = os.getenv("GEMINI_USE_PROXY", "False").lower()
    use_proxy = use_proxy_str in ("true", "1", "t")
    proxy_address = os.getenv("GEMINI_PROXY_ADDRESS")

    if use_proxy:
        if not proxy_address:
            print("\n[ОШИКА] `GEMINI_USE_PROXY` установлен в True, но `GEMINI_PROXY_ADDRESS` не указан в .env файле.")
            return

        # Устанавливаем переменные окружения, которые использует google-generativeai
        os.environ['HTTPS_PROXY'] = proxy_address
        os.environ['HTTP_PROXY'] = proxy_address
        print(f"✓ Установлен прокси для этого сеанса: {proxy_address}")
    else:
        print("... Прокси не используется (GEMINI_USE_PROXY=False).")

    # 2. Проверка API ключа
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("\n[ОШИБКА] Ключ GEMINI_API_KEY не найден в .env файле.")
        return
    print("✓ Ключ API найден.")

    try:
        # 3. Конфигурация и вызов API
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name="gemini-1.5-flash")
        print("✓ Модель gemini-1.5-flash инициализирована.")

        print("... Отправляю тестовый запрос: 'Почему небо голубое?'")
        response = await model.generate_content_async("Почему небо голубое?")

        print("\n--- УСПЕШНЫЙ ОТВЕТ ОТ GEMINI ---")
        print(response.text)
        print("---------------------------------")
        print("\n✓ Тест пройден успешно!")

    except exceptions.PermissionDenied as e:
        print("\n[ОШИБКА] Отказ в доступе (Permission Denied).")
        print("Проверьте, что ваш API ключ действителен и что биллинг для проекта Google Cloud активен.")
        print("\nДетали ошибки:", e)

    except exceptions.ResourceExhausted as e:
        print("\n[ОШИБКА] Исчерпаны квоты (Resource Exhausted).")
        print("Возможно, вы превысили бесплатный лимит запросов. Проверьте квоты в Google Cloud Console.")
        print("\nДетали ошибки:", e)

    except Exception as e:
        error_message = str(e)
        if "User location is not supported" in error_message:
            print(f"\n[ОШИБКА ГЕОЛОКАЦИИ] {error_message}")
            print("Даже с прокси, Google мог определить ваше реальное местоположение. Убедитесь, что прокси надежный.")
        elif "proxy" in error_message.lower():
            print("\n[ОШИБКА ПРОКСИ] Не удалось подключиться через прокси.")
            print("Убедитесь, что адрес и данные для входа в прокси верны, и что он работает.")
            print("\nДетали ошибки:", e)
        else:
            print(f"\n[НЕИЗВЕСТНАЯ ОШИБКА] Произошла непредвиденная ошибка.")
            print("Детали:", e)

if __name__ == "__main__":
    asyncio.run(run_test())