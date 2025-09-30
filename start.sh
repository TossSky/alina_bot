#!/bin/bash
# Быстрый запуск Alina Bot с Webhook

cd /home/vtotskiy/GitRepo/alina_bot
source venv/bin/activate

echo "🚀 Запуск Alina Bot с Webhook..."
echo ""

# Проверка зависимостей
echo "📦 Установка зависимостей..."
pip install -q flask yookassa

# Проверка конфигурации
if ! grep -q "USE_WEBHOOK=true" .env; then
    echo "⚠️  Добавляю USE_WEBHOOK=true в .env"
    echo "USE_WEBHOOK=true" >> .env
fi

# Запуск
echo "✅ Запускаю бота..."
python run_with_webhook.py
