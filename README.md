# Alina Bot - Telegram бот с оплатой через ЮКассу

## 🚀 Быстрый запуск

### 1. Установите зависимости
```bash
cd /home/vtotskiy/GitRepo/alina_bot
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Настройте .env
Убедитесь что указаны:
```bash
YOOKASSA_SHOP_ID=ваш_shop_id
YOOKASSA_SECRET_KEY=test_G61l2gtd7V3fmf3lHcNsncRQcyuLUdpDFyZlx_Tm-CA
USE_WEBHOOK=true
```

### 3. Настройте проброс порта на Jump
```bash
ssh jump
sudo iptables -t nat -A PREROUTING -p tcp --dport 443 -j DNAT --to-destination 192.168.16.79:5000
sudo iptables -t nat -A POSTROUTING -j MASQUERADE
sudo netfilter-persistent save
```

### 4. Запустите бота
```bash
chmod +x start.sh
./start.sh
```

Или напрямую:
```bash
python run_with_webhook.py
```

### 5. Настройте webhook в ЮКассе
- URL: `https://tosssky.hopto.org/yookassa/webhook`
- Настройки → Уведомления → HTTP-уведомления

## 🔧 Автозапуск через systemd

```bash
sudo systemctl enable alina-bot
sudo systemctl start alina-bot
sudo journalctl -u alina-bot -f
```

## ✅ Проверка
```bash
curl -k https://tosssky.hopto.org/health
```

Должно вернуть: `{"status": "healthy", "bot_ready": true}`
