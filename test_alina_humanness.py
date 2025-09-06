# test_alina_humanness.py - Быстрый тест человечности ответов
"""
Скрипт для быстрой проверки, насколько человечно отвечает Алина.
Запустите для диагностики проблем.
"""

import asyncio
import os
from typing import List, Dict
import sys

# Добавляем путь к модулям
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

async def test_responses():
    """Тестирует различные типы запросов."""
    
    print("=" * 60)
    print("ТЕСТ ЧЕЛОВЕЧНОСТИ АЛИНЫ")
    print("=" * 60)
    
    # Загружаем конфигурацию
    from dotenv import load_dotenv
    load_dotenv()
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ Ошибка: OPENAI_API_KEY не найден в .env")
        return
    
    # Импортируем нужные модули
    try:
        # Пробуем импортировать исправленную версию
        from enhanced_personality import ALINA_CORE, generate_contextual_prompt, get_generation_params
        from advanced_llm import HumanLikeAlinaLLM
        print("✅ Используем исправленные модули")
    except ImportError:
        try:
            # Fallback на старые версии
            from personality import ALINA_PERSONALITY as ALINA_CORE
            from llm import AlinaLLM as HumanLikeAlinaLLM
            print("⚠️ Используем базовые модули")
            
            # Создаем заглушки для отсутствующих функций
            def generate_contextual_prompt(base, context, history):
                return base
            
            def get_generation_params(context):
                return {
                    "temperature": 0.9,
                    "frequency_penalty": 0.4,
                    "presence_penalty": 0.4,
                    "max_tokens": 200
                }
        except ImportError as e:
            print(f"❌ Не удалось импортировать модули: {e}")
            return
    
    # Создаем клиент
    llm = HumanLikeAlinaLLM(
        api_key=api_key,
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    )
    
    # Тестовые запросы
    test_cases = [
        {
            "name": "Приветствие",
            "message": "Привет! Как дела?",
            "expected": ["неформальный ответ", "строчные буквы", "возможны эмодзи"]
        },
        {
            "name": "Просьба о фактах",
            "message": "Напиши 10 фактов о котах",
            "expected": ["отказ или 2-3 факта", "не список", "человеческая реакция"]
        },
        {
            "name": "Вопрос про бота",
            "message": "Ты же бот, да?",
            "expected": ["отрицание", "ответ как человек", "возможно обида"]
        },
        {
            "name": "Эмоциональное",
            "message": "Мне грустно сегодня",
            "expected": ["поддержка", "неформально", "эмпатия без клише"]
        },
        {
            "name": "Спам-тест",
            "message": "Сколько времени?",
            "expected": ["ответ про время", "неформально"],
            "repeat": 3  # Повторим 3 раза
        }
    ]
    
    print("\n" + "=" * 60)
    print("НАЧИНАЕМ ТЕСТИРОВАНИЕ")
    print("=" * 60)
    
    for test in test_cases:
        print(f"\n📝 Тест: {test['name']}")
        print(f"Сообщение: {test['message']}")
        print(f"Ожидаем: {', '.join(test['expected'])}")
        print("-" * 40)
        
        repeat_count = test.get('repeat', 1)
        
        # История для контекста
        history = []
        
        for i in range(repeat_count):
            # Создаем контекст
            context = {
                "relationship": "friend" if i > 0 else "stranger",
                "message_count": i * 10,
                "user_memory": {}
            }
            
            # Генерируем промпт
            try:
                system_prompt = generate_contextual_prompt(
                    ALINA_CORE,
                    context,
                    history
                )
            except:
                system_prompt = ALINA_CORE
            
            # Формируем сообщения
            messages = [
                {"role": "system", "content": system_prompt}
            ]
            
            # Добавляем историю
            for msg in history:
                messages.append(msg)
            
            # Добавляем текущее сообщение
            messages.append({"role": "user", "content": test['message']})
            
            try:
                # Генерируем ответ
                if hasattr(llm, 'generate_response'):
                    response = await llm.generate_response(messages, context)
                else:
                    response = await llm.generate(messages)
                
                if i == 0 or repeat_count > 1:
                    print(f"\n🤖 Ответ {i+1}: {response}")
                
                # Добавляем в историю
                history.append({"role": "user", "content": test['message']})
                history.append({"role": "assistant", "content": response})
                
                # Анализируем ответ
                if i == repeat_count - 1:  # Последняя итерация
                    print("\n📊 Анализ:")
                    
                    # Проверяем характеристики
                    checks = {
                        "Строчные буквы": response[0].islower() if response else False,
                        "Короткий ответ": len(response) < 300,
                        "Нет списков": "1." not in response and "•" not in response,
                        "Есть сокращения": any(s in response for s in ["оч", "мб", "норм", "крч"]),
                        "Неформальный стиль": not any(f in response for f in ["Я могу помочь", "Чем могу быть полезна"]),
                        "Есть эмоции": any(e in response for e in [")", "😊", "😅", "ахаха", "блин", "ой"])
                    }
                    
                    for check, result in checks.items():
                        emoji = "✅" if result else "❌"
                        print(f"  {emoji} {check}")
                    
                    # Оценка человечности
                    score = sum(1 for v in checks.values() if v)
                    total = len(checks)
                    percentage = (score / total) * 100
                    
                    if percentage >= 80:
                        print(f"\n✨ Человечность: {percentage:.0f}% - Отлично!")
                    elif percentage >= 60:
                        print(f"\n⚠️ Человечность: {percentage:.0f}% - Можно лучше")
                    else:
                        print(f"\n❌ Человечность: {percentage:.0f}% - Слишком формально!")
                
            except Exception as e:
                print(f"❌ Ошибка: {e}")
        
        print("-" * 40)
    
    print("\n" + "=" * 60)
    print("РЕКОМЕНДАЦИИ")
    print("=" * 60)
    
    print("""
    Если ответы слишком формальные:
    1. Увеличьте temperature в fixed_advanced_llm.py до 0.92-0.95
    2. Проверьте, что используется ALINA_CORE без лишних правил
    3. Убедитесь, что не добавляются множественные system промпты
    4. Используйте модель gpt-4o-mini или gpt-4o
    
    Если все тесты провалены:
    - Вернитесь к базовой версии (bot.py + personality.py)
    - Проверьте API ключ и модель в .env
    """)

async def quick_chat():
    """Интерактивный чат для быстрой проверки."""
    
    print("\n" + "=" * 60)
    print("ИНТЕРАКТИВНЫЙ ТЕСТ")
    print("=" * 60)
    print("Введите 'выход' для завершения\n")
    
    from dotenv import load_dotenv
    load_dotenv()
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY не найден")
        return
    
    # Импортируем модули
    try:
        from enhanced_personality import ALINA_CORE, generate_contextual_prompt
        from advanced_llm import HumanLikeAlinaLLM
    except:
        from personality import ALINA_PERSONALITY as ALINA_CORE
        from llm import AlinaLLM as HumanLikeAlinaLLM
        def generate_contextual_prompt(base, context, history):
            return base
    
    llm = HumanLikeAlinaLLM(api_key=api_key, model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    
    history = []
    message_count = 0
    
    while True:
        user_input = input("\n👤 Вы: ")
        
        if user_input.lower() in ['выход', 'exit', 'quit']:
            print("До свидания!")
            break
        
        # Контекст
        context = {
            "relationship": "friend" if message_count > 5 else "acquaintance",
            "message_count": message_count,
            "user_memory": {}
        }
        
        # Промпт
        try:
            system_prompt = generate_contextual_prompt(ALINA_CORE, context, history[-10:])
        except:
            system_prompt = ALINA_CORE
        
        # Сообщения
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history[-10:]:
            messages.append(msg)
        messages.append({"role": "user", "content": user_input})
        
        try:
            # Генерируем ответ
            if hasattr(llm, 'generate_response'):
                response = await llm.generate_response(messages, context)
            else:
                response = await llm.generate(messages)
            
            print(f"🤖 Алина: {response}")
            
            # Обновляем историю
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": response})
            message_count += 1
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")

async def main():
    """Главная функция."""
    
    print("\nВыберите режим тестирования:")
    print("1. Автоматические тесты")
    print("2. Интерактивный чат")
    print("3. Оба режима")
    
    choice = input("\nВаш выбор (1-3): ")
    
    if choice == "1":
        await test_responses()
    elif choice == "2":
        await quick_chat()
    elif choice == "3":
        await test_responses()
        await quick_chat()
    else:
        print("Неверный выбор")

if __name__ == "__main__":
    asyncio.run(main())