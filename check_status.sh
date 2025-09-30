#!/bin/bash

# Проверка статуса Alina Bot с Webhook
# Запускать на daemon сервере

echo "🔍 Проверка статуса Alina Bot"
echo "=============================="
echo ""

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Функция для вывода статуса
check_status() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✅ $2${NC}"
    else
        echo -e "${RED}❌ $2${NC}"
    fi
}

# 1. Проверка сервиса
echo "1️⃣ Systemd Service:"
if systemctl is-active --quiet alina-bot; then
    echo -e "${GREEN}✅ Сервис запущен${NC}"
    systemctl status alina-bot --no-pager -l | head -n 10
else
    echo -e "${RED}❌ Сервис НЕ запущен${NC}"
    echo "Запустите: sudo systemctl start alina-bot"
fi

echo ""
echo "2️⃣ SSL Сертификаты:"
if [ -f "/etc/letsencrypt/live/tosssky.hopto.org-0001/fullchain.pem" ]; then
    echo -e "${GREEN}✅ Сертификаты найдены${NC}"
    openssl x509 -in /etc/letsencrypt/live/tosssky.hopto.org-0001/fullchain.pem -noout -dates | head -n 2
else
    echo -e "${RED}❌ Сертификаты НЕ найдены${NC}"
fi

echo ""
echo "3️⃣ Webhook доступность:"
response=$(curl -sk https://localhost:5000/health 2>/dev/null)
if [ ! -z "$response" ]; then
    echo -e "${GREEN}✅ Webhook доступен локально${NC}"
    echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
else
    echo -e "${RED}❌ Webhook НЕ доступен${NC}"
fi

echo ""
echo "4️⃣ Конфигурация (.env):"
cd /home/vtotskiy/GitRepo/alina_bot
if grep -q "USE_WEBHOOK=true" .env 2>/dev/null; then
    echo -e "${GREEN}✅ USE_WEBHOOK=true${NC}"
else
    echo -e "${YELLOW}⚠️  USE_WEBHOOK не установлен или false${NC}"
fi

shop_id=$(grep "YOOKASSA_SHOP_ID=" .env 2>/dev/null | cut -d'=' -f2)
if [ ! -z "$shop_id" ]; then
    echo -e "${GREEN}✅ YOOKASSA_SHOP_ID установлен: $shop_id${NC}"
else
    echo -e "${YELLOW}⚠️  YOOKASSA_SHOP_ID не установлен${NC}"
fi

echo ""
echo "5️⃣ Порты:"
port_5000=$(sudo lsof -i :5000 2>/dev/null | grep LISTEN)
if [ ! -z "$port_5000" ]; then
    echo -e "${GREEN}✅ Порт 5000 прослушивается${NC}"
    echo "$port_5000" | head -n 1
else
    echo -e "${RED}❌ Порт 5000 НЕ прослушивается${NC}"
fi

echo ""
echo "6️⃣ Последние логи (5 строк):"
sudo journalctl -u alina-bot -n 5 --no-pager 2>/dev/null || echo "Нет доступа к логам"

echo ""
echo "7️⃣ Проверка с внешнего адреса:"
external_health=$(curl -sk https://tosssky.hopto.org/health 2>/dev/null)
if [ ! -z "$external_health" ]; then
    echo -e "${GREEN}✅ Webhook доступен извне${NC}"
    echo "$external_health" | python3 -m json.tool 2>/dev/null || echo "$external_health"
else
    echo -e "${RED}❌ Webhook НЕ доступен извне${NC}"
    echo "Проверьте проброс портов на jump сервере"
fi

echo ""
echo "=============================="
echo "📋 Полезные команды:"
echo ""
echo "Логи в реальном времени:"
echo "  sudo journalctl -u alina-bot -f"
echo ""
echo "Перезапуск бота:"
echo "  sudo systemctl restart alina-bot"
echo ""
echo "Проверка портов на jump:"
echo "  ssh jump 'sudo iptables -t nat -L -n -v | grep 443'"
echo ""
echo "Проверка webhook извне:"
echo "  curl -k https://tosssky.hopto.org/health"
echo ""
