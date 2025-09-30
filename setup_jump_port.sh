#!/bin/bash

# Настройка проброса портов на Jump сервере
# Запускайте на jump сервере (185.233.93.99)

set -e

echo "🔀 Настройка проброса портов на Jump сервере"
echo "============================================="
echo ""

# Проверка, что мы на jump
if [ "$(hostname)" != "jump" ] && [ "$(hostname)" != "ssh-custom" ]; then
    echo "⚠️  Внимание: Этот скрипт должен запускаться на Jump сервере!"
    read -p "Вы уверены что хотите продолжить? (y/N): " confirm
    if [ "$confirm" != "y" ]; then
        echo "Отменено"
        exit 1
    fi
fi

# Выбор порта
echo "Выберите внешний порт для webhook:"
echo "1) 443 (рекомендуется, стандартный HTTPS)"
echo "2) 8443 (альтернативный HTTPS)"
echo ""
read -p "Ваш выбор (1/2): " choice

if [ "$choice" = "1" ]; then
    PORT=443
    URL="https://tosssky.hopto.org/yookassa/webhook"
elif [ "$choice" = "2" ]; then
    PORT=8443
    URL="https://tosssky.hopto.org:8443/yookassa/webhook"
else
    echo "❌ Неверный выбор"
    exit 1
fi

echo ""
echo "Настраиваем проброс порта $PORT -> 192.168.16.79:5000"

# Проверка существующих правил
echo ""
echo "Текущие правила NAT:"
sudo iptables -t nat -L PREROUTING -n -v | grep -E "tcp dpt:($PORT|443|8443)" || echo "Нет правил для портов 443/8443"

# Удаление старых правил для этого порта
echo ""
echo "Удаляем старые правила для порта $PORT (если есть)..."
sudo iptables -t nat -D PREROUTING -p tcp --dport $PORT -j DNAT --to-destination 192.168.16.79:5000 2>/dev/null || true

# Добавление нового правила
echo ""
echo "Добавляем новое правило..."
sudo iptables -t nat -A PREROUTING -p tcp --dport $PORT -j DNAT --to-destination 192.168.16.79:5000
sudo iptables -t nat -A POSTROUTING -j MASQUERADE

# Сохранение правил
echo ""
echo "Сохраняем правила..."
if command -v netfilter-persistent &> /dev/null; then
    sudo netfilter-persistent save
    echo "✅ Правила сохранены через netfilter-persistent"
elif [ -d /etc/iptables ]; then
    sudo iptables-save > /etc/iptables/rules.v4
    echo "✅ Правила сохранены в /etc/iptables/rules.v4"
else
    echo "⚠️  Установите iptables-persistent для автосохранения:"
    echo "   sudo apt-get install iptables-persistent"
fi

# Проверка правил
echo ""
echo "Новые правила NAT:"
sudo iptables -t nat -L PREROUTING -n -v | grep -E "tcp dpt:($PORT|443|8443)"

echo ""
echo "=================================="
echo "✅ Проброс портов настроен!"
echo "=================================="
echo ""
echo "📋 Используйте этот URL в ЮКассе:"
echo "   $URL"
echo ""
echo "🔍 Для проверки с daemon сервера выполните:"
echo "   curl -k $URL"
echo ""
echo "📊 Для просмотра всех правил NAT:"
echo "   sudo iptables -t nat -L -n -v"
echo ""
echo "🗑️  Для удаления правила:"
echo "   sudo iptables -t nat -D PREROUTING -p tcp --dport $PORT -j DNAT --to-destination 192.168.16.79:5000"
echo ""
