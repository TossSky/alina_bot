# 🚀 Быстрый старт Webhook

## Что сделано:

✅ Создан webhook сервер с SSL  
✅ Бот работает в режиме webhook (мгновенная активация подписок)  
✅ Автоматическая проверка платежей отключена (не нужна с webhook)  

---

## Установка (за 5 минут):

### 1️⃣ На daemon сервере (192.168.16.79):
```bash
cd /home/vtotskiy/GitRepo/alina_bot
chmod +x setup_webhook.sh
./setup_webhook.sh
```

### 2️⃣ На jump сервере (185.233.93.99):
```bash
# Скопируйте файл на jump
scp setup_jump_port.sh jump:~/

# Выполните на jump
ssh jump
chmod +x ~/setup_jump_port.sh
sudo ~/setup_jump_port.sh
```

### 3️⃣ Запуск бота:
```bash
# На daemon сервере
sudo systemctl start alina-bot
sudo systemctl status alina-bot
```

### 4️⃣ В ЮКассе:
- Откройте: https://yookassa.ru/
- Настройки → Уведомления → HTTP-уведомления
- URL: `https://tosssky.hopto.org/yookassa/webhook`
- Сохранить

---

## Проверка работы:

```bash
# Проверка webhook
curl -k https://tosssky.hopto.org/health

# Должен вернуть:
# {"status": "healthy", "bot_ready": true}

# Логи бота
sudo journalctl -u alina-bot -f

# В логах должно быть:
# 🚀 Starting YooKassa Webhook Server
# 📡 Payment checker disabled (webhook mode)
```

---

## Тестирование платежа:

1. В боте: `/subscribe`
2. Выберите "День - 99 ₽"
3. Нажмите "💳 Оплатить"
4. Тестовая карта: **4111 1111 1111 1111**
5. **Сразу после оплаты** → бот пришлёт уведомление! ⚡

---

## Основные команды:

```bash
# Перезапуск бота
sudo systemctl restart alina-bot

# Остановка бота
sudo systemctl stop alina-bot

# Просмотр логов
sudo journalctl -u alina-bot -f

# Статус сервиса
sudo systemctl status alina-bot

# Проверка портов на jump
ssh jump "sudo iptables -t nat -L -n -v | grep 443"
```

---

## Troubleshooting:

### Webhook не работает?
```bash
# 1. Проверьте доступность
curl -k https://tosssky.hopto.org/health

# 2. Проверьте логи
sudo journalctl -u alina-bot -f

# 3. Проверьте проброс портов на jump
ssh jump "sudo iptables -t nat -L -n -v | grep 443"
```

### Ошибка SSL?
```bash
# Проверьте права на сертификаты
ls -la /etc/letsencrypt/live/tosssky.hopto.org-0001/

# Должно быть доступно для чтения
sudo chmod 644 /etc/letsencrypt/live/tosssky.hopto.org-0001/*.pem
```

### Порт 5000 занят?
```bash
# Найдите процесс
sudo lsof -i :5000

# Убейте если нужно
sudo kill -9 <PID>
```

---

## URL для Юкассы:

**Основной (порт 443):**
```
https://tosssky.hopto.org/yookassa/webhook
```

**Альтернативный (порт 8443):**
```
https://tosssky.hopto.org:8443/yookassa/webhook
```

---

## Важно:

✅ **USE_WEBHOOK=true** в `.env`  
✅ **YOOKASSA_SHOP_ID** должен быть указан  
✅ Webhook URL настроен в ЮКассе  
✅ Порт 443 или 8443 проброшен на jump  

---

## Файлы проекта:

- `run_with_webhook.py` - запуск бота с webhook
- `webhook_server.py` - Flask сервер для webhook
- `setup_webhook.sh` - автоустановка на daemon
- `setup_jump_port.sh` - настройка портов на jump
- `WEBHOOK_SETUP.md` - подробная документация

---

## Готово! 🎉

После настройки платежи будут активироваться **мгновенно** через webhook!
