# Alina Bot

Advanced Telegram bot with AI-powered conversations, subscription management, and payment processing.

## Features

- 🤖 **AI Conversations** - Natural dialogue powered by OpenAI GPT-4
- 💳 **Payment Integration** - Built-in subscription system with PayMaster
- 📊 **Usage Tracking** - Token and message limits for free users
- 🔐 **Admin Controls** - Special commands for bot administrators
- 🗂️ **Conversation History** - Persistent storage with SQLite
- ⚡ **Performance Optimized** - Efficient token counting and caching

## Quick Start

### Prerequisites

- Python 3.10+
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- OpenAI API Key
- PayMaster Payment Token (optional, for payments)

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/alina_bot.git
cd alina_bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment:
```bash
cp .env.example .env
# Edit .env with your credentials
```

4. Run the bot:
```bash
python bot.py
```

## Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | Yes | - |
| `OPENAI_API_KEY` | OpenAI API key | Yes | - |
| `OPENAI_MODEL` | GPT model to use | No | gpt-4o-mini |
| `USE_PROXY` | Enable proxy for API calls | No | false |
| `PROXY_URL` | Proxy URL if enabled | Conditional | - |
| `PAYMENTS_TOKEN` | PayMaster payment token | No | - |
| `SUBSCRIPTION_REQUIRED` | Enforce subscription limits | No | true |
| `FREE_MESSAGES_LIMIT` | Free messages per user | No | 15 |
| `FREE_TOKENS_LIMIT` | Free tokens per user | No | 2000 |

### Admin Configuration

Admin user IDs are configured in `config.py`:
```python
ADMIN_IDS = [367288553, 7372093786, 916411940]
```

## Bot Commands

### User Commands
- `/start` - Start conversation with the bot
- `/subscribe` - View subscription options
- `/subscription` - Check subscription status

### Admin Commands
- `/restart` - Restart bot process
- `/reset_limits` - Reset usage limits (testing)

## Subscription Plans

| Plan | Duration | Price |
|------|----------|-------|
| Day | 1 day | 99 ₽ |
| Week | 7 days | 499 ₽ |
| Month | 30 days | 1499 ₽ |

## Architecture

### Core Modules

- **`bot.py`** - Main application and command handlers
- **`llm.py`** - OpenAI API client with token counting
- **`database.py`** - SQLite storage for conversations
- **`payments.py`** - Subscription and payment management
- **`personality.py`** - AI personality configuration
- **`config.py`** - Environment configuration

### Database Schema

```sql
-- Users table
CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    created_at TIMESTAMP,
    last_active TIMESTAMP,
    total_messages INTEGER,
    total_tokens INTEGER,
    user_data TEXT
);

-- Messages table
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    role TEXT,
    content TEXT,
    timestamp TIMESTAMP
);

-- Subscriptions table
CREATE TABLE subscriptions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    plan_type TEXT,
    end_date TIMESTAMP,
    is_active BOOLEAN
);
```

## Development

### Project Structure
```
alina_bot/
├── bot.py              # Main application
├── llm.py              # AI integration
├── database.py         # Data storage
├── payments.py         # Payment processing
├── personality.py      # Character config
├── config.py           # Settings
├── requirements.txt    # Dependencies
├── .env               # Environment variables
└── alina.db           # SQLite database
```

### Testing Payments

Use test card for payment testing:
- Card: `4242 4242 4242 4242`
- Expiry: Any future date
- CVV: Any 3 digits

### Logging

Logs include:
- User messages and bot responses
- Token usage and costs
- Payment transactions
- System events

## Production Deployment

### Using systemd

Create service file `/etc/systemd/system/alina-bot.service`:
```ini
[Unit]
Description=Alina Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/alina_bot
ExecStart=/usr/bin/python3 /home/ubuntu/alina_bot/bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable alina-bot
sudo systemctl start alina-bot
```

### Using Docker

```dockerfile
FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
```

## Security Notes

- Never commit `.env` file to repository
- Rotate API keys regularly
- Use webhook instead of polling in production
- Enable rate limiting for public bots
- Validate all user inputs

## License

MIT

## Support

For issues and questions, please open an issue on GitHub.
