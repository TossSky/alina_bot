#!/bin/bash

# Быстрая настройка Webhook для Алины
# Запускайте на сервере daemon (192.168.16.79)

set -e

echo "🚀 Настройка Webhook для Alina Bot"
echo "=================================="
echo ""

# Проверка SSL сертификатов
echo "1️⃣ Проверка SSL сертификатов..."
if [ -f "/etc/letsencrypt/live/tosssky.hopto.org-0001/fullchain.pem" ]; then
    echo "✅ SSL сертификаты найдены"
else
    echo "❌ SSL сертификаты НЕ найдены!"
    echo "Путь: /etc/letsencrypt/live/tosssky.hopto.org-0001/"
    exit 1
fi

# Проверка прав на сертификаты
echo ""
echo "2️⃣ Настройка прав на SSL сертификаты..."
sudo chmod 644 /etc/letsencrypt/live/tosssky.hopto.org-0001/*.pem 2>/dev/null || true
sudo chmod 755 /etc/letsencrypt/live/tosssky.hopto.org-0001/ 2>/dev/null || true
sudo chmod 755 /etc/letsencrypt/live/ 2>/dev/null || true
sudo chmod 755 /etc/letsencrypt/ 2>/dev/null || true
echo "✅ Права настроены"

# Установка зависимостей
echo ""
echo "3️⃣ Установка зависимостей..."
cd /home/vtotskiy/GitRepo/alina_bot
source venv/bin/activate
pip install flask yookassa -q
echo "✅ Зависимости установлены"

# Проверка конфигурации
echo ""
echo "4️⃣ Проверка .env конфигурации..."
if grep -q "USE_WEBHOOK=true" .env; then
    echo "✅ USE_WEBHOOK=true найден"
else
    echo "⚠️  Добавляем USE_WEBHOOK=true в .env"
    echo "USE_WEBHOOK=true" >> .env
fi

# Получение SHOP_ID
echo ""
echo "5️⃣ Настройка YOOKASSA_SHOP_ID..."
echo "Текущее значение YOOKASSA_SHOP_ID:"
grep "YOOKASSA_SHOP_ID" .env || echo "Не найдено"
echo ""
read -p "Введите ваш YOOKASSA_SHOP_ID (или Enter для пропуска): " shop_id
if [ ! -z "$shop_id" ]; then
    sed -i "s/YOOKASSA_SHOP_ID=.*/YOOKASSA_SHOP_ID=$shop_id/" .env
    echo "✅ YOOKASSA_SHOP_ID обновлен"
fi

# Создание systemd service
echo ""
echo "6️⃣ Создание systemd service..."
sudo tee /etc/systemd/system/alina-bot.service > /dev/null <<EOF
[Unit]
Description=Alina Bot with YooKassa Webhook
After=network.target

[Service]
Type=simple
User=vtotskiy
WorkingDirectory=/home/vtotskiy/GitRepo/alina_bot
Environment="PATH=/home/vtotskiy/GitRepo/alina_bot/venv/bin"
ExecStart=/home/vtotskiy/GitRepo/alina_bot/venv/bin/python run_with_webhook.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
echo "✅ Service создан"

# Финальные инструкции
echo ""
echo "=================================="
echo "✅ Настройка завершена!"
echo "=================================="
echo ""
echo "📋 Следующие шаги:"
echo ""
echo "1️⃣ На JUMP сервере (185.233.93.99) выполните:"
echo "   ssh jump"
echo "   sudo iptables -t nat -A PREROUTING -p tcp --dport 443 -j DNAT --to-destination 192.168.16.79:5000"
echo "   sudo iptables -t nat -A POSTROUTING -j MASQUERADE"
echo "   sudo netfilter-persistent save"
echo ""
echo "2️⃣ Запустите бота:"
echo "   sudo systemctl start alina-bot"
echo "   sudo systemctl status alina-bot"
echo ""
echo "3️⃣ Проверьте логи:"
echo "   sudo journalctl -u alina-bot -f"
echo ""
echo "4️⃣ Проверьте доступность webhook:"
echo "   curl -k https://tosssky.hopto.org/health"
echo ""
echo "5️⃣ В ЮКассе настройте URL:"
echo "   https://tosssky.hopto.org/yookassa/webhook"
echo ""
echo "🎉 Готово!"
