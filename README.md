# Alina Bot

Человекоподобный чат-бот для Telegram.

## Быстрый старт

1. **Установка зависимостей:**
```bash
pip install -r requirements.txt
```

2. **Настройка:**
```bash
cp .env.example .env
# Заполните .env вашими токенами
```

3. **Запуск:**
```bash
python bot.py
```

## Требования

- Python 3.8+
- Telegram Bot Token (от @BotFather)
- OpenAI API Key

## Модели

- `gpt-4o-mini` - рекомендуется (баланс скорости/качества)
- `gpt-4o` - максимальное качество
- `gpt-3.5-turbo` - быстро но менее человечно

## Поддержка альтернативных API

Можно использовать OpenRouter, Together AI и др.:
```env
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_API_KEY=your_openrouter_key
```
