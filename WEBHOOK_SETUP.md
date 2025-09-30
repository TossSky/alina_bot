# Настройка Webhook для Юкассы

## Шаг 1: Настройка проброса портов на Jump сервере

На Jump сервере (`185.233.93.99`) настройте проброс порта 443 (или 8443):

### Вариант 1: Порт 443 (рекомендуется)
```bash
ssh jump
sudo iptables -t nat -A PREROUTING -p tcp --dport 443 -j DNAT --to-destination 192.168.16.79:5000
sudo iptables -t nat -A POSTROUTING -j MASQUERADE
sudo netfilter-persistent save
```

### Вариант 2: Порт 8443 (если 443 занят)
```bash
ssh jump
sudo iptables -t nat -A PREROUTING -p tcp --dport 8443 -j DNAT --to-destination 192.168.16.79:5000
sudo iptables -t nat -A POSTROUTING -j MASQUERADE
sudo netfilter-persistent save
```

### Проверка правил
```bash
sudo iptables -t nat -L -n -v
```

## Шаг 2: Установка зависимостей

```bash
cd /home/vtotskiy/GitRepo/alina_bot
source venv/bin/activate
pip install -r requirements.txt
```

## Шаг 3: Проверка SSL сертификатов

```bash
ls -la /etc/letsencrypt/live/tosssky.hopto.org-0001/
# Должны быть: fullchain.pem и privkey.pem
```

## Шаг 4: Запуск бота с webhook

```bash
cd /home/vtotskiy/GitRepo/alina_bot
source venv/bin/activate
python run_with_webhook.py
```

В логах вы должны увидеть:
```
🚀 Starting YooKassa Webhook Server
📡 Internal port: 5000
🔒 SSL Certificate: /etc/letsencrypt/live/tosssky.hopto.org-0001/fullchain.pem
📝 Configure in YooKassa dashboard:
   URL: https://tosssky.hopto.org/yookassa/webhook
```

## Шаг 5: Настройка в Юкассе

1. Войдите в личный кабинет ЮКасса: https://yookassa.ru/
2. Перейдите в **Настройки** → **Уведомления**
3. Найдите **HTTP-уведомления**
4. Введите URL:
   - Если проброшен порт 443: `https://tosssky.hopto.org/yookassa/webhook`
   - Если проброшен порт 8443: `https://tosssky.hopto.org:8443/yookassa/webhook`
5. Нажмите **Сохранить**

## Шаг 6: Тестирование

### Проверка доступности webhook
```bash
curl -k https://tosssky.hopto.org/health
# или
curl -k https://tosssky.hopto.org:8443/health
```

Ответ должен быть:
```json
{
  "status": "healthy",
  "webhook_url": "/yookassa/webhook",
  "bot_ready": true
}
```

### Тестовая оплата
1. В боте: `/subscribe`
2. Выберите план (например, "День - 99 ₽")
3. Нажмите "💳 Оплатить"
4. Оплатите тестовой картой: `4111 1111 1111 1111`, срок: любой будущий, CVV: любой
5. **Сразу после оплаты** бот должен прислать сообщение об активации!

## Шаг 7: Настройка автозапуска (systemd)

Создайте systemd service:

```bash
sudo nano /etc/systemd/system/alina-bot.service
```

Содержимое файла:
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

Активируйте service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable alina-bot
sudo systemctl start alina-bot
sudo systemctl status alina-bot
```

Просмотр логов:
```bash
sudo journalctl -u alina-bot -f
```

## Troubleshooting

### Webhook не получает уведомления
1. Проверьте доступность извне:
   ```bash
   curl -k https://tosssky.hopto.org/health
   ```

2. Проверьте логи бота:
   ```bash
   sudo journalctl -u alina-bot -f
   ```

3. Проверьте настройки в ЮКассе - URL должен быть точно таким

### SSL ошибки
```bash
# Проверьте права на сертификаты
sudo chmod 644 /etc/letsencrypt/live/tosssky.hopto.org-0001/*.pem
sudo chmod 755 /etc/letsencrypt/live/tosssky.hopto.org-0001/
sudo chmod 755 /etc/letsencrypt/live/
sudo chmod 755 /etc/letsencrypt/

# Добавьте пользователя в нужную группу
sudo usermod -a -G ssl-cert vtotskiy
```

### Порт занят
```bash
# Проверьте какой процесс использует порт 5000
sudo lsof -i :5000
sudo netstat -tulpn | grep 5000

# Убейте процесс если нужно
sudo kill -9 <PID>
```

## Преимущества webhook по сравнению с polling

✅ **Мгновенная активация** - подписка активируется сразу после оплаты
✅ **Меньше нагрузки** - не нужно постоянно опрашивать API
✅ **Более надежно** - Юкасса гарантирует доставку уведомлений
✅ **Продакшен-готово** - стандартный подход для работы с платежами

## Что делать дальше

1. Отключите payment_checker в bot.py (он больше не нужен с webhook)
2. Настройте мониторинг webhook endpoint
3. Добавьте логирование всех webhook запросов
