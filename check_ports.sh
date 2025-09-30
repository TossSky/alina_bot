#!/bin/bash

# Проверка занятых портов для Alina Bot
# Использование: ./check_ports.sh

echo "🔍 Проверка портов для Alina Bot"
echo "=================================="
echo ""

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Функция проверки порта
check_port() {
    local port=$1
    local name=$2
    
    echo -e "${BLUE}Порт $port ($name):${NC}"
    
    # Проверка через lsof
    local lsof_result=$(sudo lsof -i :$port 2>/dev/null)
    
    if [ ! -z "$lsof_result" ]; then
        echo -e "${RED}❌ ЗАНЯТ${NC}"
        echo "$lsof_result" | grep -v "^COMMAND" | awk '{printf "   PID: %-8s Command: %-20s User: %s\n", $2, $1, $3}'
    else
        echo -e "${GREEN}✅ СВОБОДЕН${NC}"
    fi
    
    # Проверка через netstat
    local netstat_result=$(sudo netstat -tulpn 2>/dev/null | grep ":$port ")
    if [ ! -z "$netstat_result" ]; then
        echo "   Netstat: $netstat_result"
    fi
    
    echo ""
}

# Проверка основных портов для проекта
echo "📋 Внутренние порты (daemon):"
echo "------------------------------"
check_port 5000 "Webhook Server"
check_port 5001 "Reserve 1"
check_port 5002 "Reserve 2"

echo ""
echo "📋 Внешние порты (jump должен пробрасывать):"
echo "---------------------------------------------"
check_port 443 "HTTPS Standard"
check_port 8443 "HTTPS Alternative"

echo ""
echo "📋 SSH порты:"
echo "-------------"
check_port 22 "SSH Standard"
check_port 5022 "SSH Jump"

echo ""
echo "=================================="
echo "📊 Общая статистика:"
echo ""

# Все LISTEN порты
echo "Все порты в режиме LISTEN:"
sudo netstat -tulpn | grep LISTEN | awk '{print $4}' | awk -F: '{print $NF}' | sort -n | uniq -c | sort -rn | head -n 10

echo ""
echo "=================================="
echo ""
echo "💡 Полезные команды:"
echo ""
echo "Все занятые порты:"
echo "  sudo netstat -tulpn | grep LISTEN"
echo ""
echo "Конкретный порт (например 5000):"
echo "  sudo lsof -i :5000"
echo ""
echo "Убить процесс на порту:"
echo "  sudo lsof -ti :5000 | xargs sudo kill -9"
echo ""
echo "Проверить порт с другого сервера:"
echo "  telnet your-server 5000"
echo "  nc -zv your-server 5000"
echo ""
