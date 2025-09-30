# 🚀 Запуск Alina Bot с Webhook от Юкассы

## Шаг 1: Установка зависимостей
```bash
cd /home/vtotskiy/GitRepo/alina_bot
source venv/bin/activate
pip install flask yookassa
```

## Шаг 2: Настройка .env
Убедитесь что в `.env` есть:
```bash
YOOKASSA_SHOP_ID=ваш_shop_id_из_личного_кабинета_юкассы
YOOKASSA_SECRET_KEY=test_G61l2gtd7V3fmf3lHcNsncRQcyuLUdpDFyZlx_Tm-CA
USE_WEBHOOK=true
```

## Шаг 3: Проброс порта на Jump сервере
```bash
ssh jump
sudo iptables -t nat -A PREROUTING -p tcp --dport 443 -j DNAT --to-destination 192.168.16.79:5000
sudo iptables -t nat -A POSTROUTING -j MASQUERADE
sudo netfilter-persistent save
exit
```

## Шаг 4: Запуск бота
```bash
python run_with_webhook.py
```

## Шаг 5: В ЮКассе настройте webhook
- URL: `https://tosssky.hopto.org/yookassa/webhook`
- Настройки → Уведомления → HTTP-уведомления

## Проверка
```bash
curl -k https://tosssky.hopto.org/health
```

Должен вернуть: `{"status": "healthy", "bot_ready": true}`

---

## Автозапуск через systemd

Создайте файл `/etc/systemd/system/alina-bot.service`:
```bash
sudo nano /etc/systemd/system/alina-bot.service
```

Содержимое:
```ini
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
```

Запуск:
```bash
sudo systemctl daemon-reload
sudo systemctl enable alina-bot
sudo systemctl start alina-bot
sudo systemctl status alina-bot

# Логи
sudo journalctl -u alina-bot -f
```
