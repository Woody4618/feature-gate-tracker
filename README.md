# Solana Feature Gate Tracker

Automated tracker for Solana feature gates. Runs nightly via GitHub Actions to scrape the [Agave wiki](https://github.com/anza-xyz/agave/wiki/Feature-Gate-Tracker-Schedule), query on-chain activation data from all clusters, and send notifications about new features and upcoming mainnet activations.

## What It Does

1. **Scrapes** the Agave Feature Gate Tracker Schedule wiki for the latest feature gate data
2. **Queries** Devnet, Testnet, and Mainnet RPC endpoints for on-chain activation epochs
3. **Detects** newly added features and features estimated to activate on mainnet within 7 days
4. **Notifies** via Slack, Twitter/X, and Telegram

## Setup

### Prerequisites

- Python 3.10+
- A private Solana mainnet RPC endpoint (recommended)

### Local Development

```bash
pip install -r requirements.txt

# Run the full pipeline
python scripts/parse_feature_gates.py
python scripts/fetch_mainnet_activations.py
python scripts/detect_changes.py
python scripts/notify.py
```

### GitHub Actions

The workflow runs daily at 3:23 AM UTC and can also be triggered manually.

Configure the following repository secrets:

| Secret | Required | Description |
|--------|----------|-------------|
| `MAINNET_RPC_URL` | Yes | Private Solana mainnet RPC endpoint |
| `SLACK_WEBHOOK_URL` | No | Slack Incoming Webhook URL |
| `TWITTER_API_KEY` | No | Twitter/X API consumer key |
| `TWITTER_API_SECRET` | No | Twitter/X API consumer secret |
| `TWITTER_ACCESS_TOKEN` | No | Twitter/X user access token |
| `TWITTER_ACCESS_SECRET` | No | Twitter/X user access token secret |
| `TELEGRAM_BOT_TOKEN` | No | Telegram bot token (from @BotFather) |
| `TELEGRAM_CHAT_ID` | No | Telegram group/channel chat ID |

Notification channels are optional -- if secrets are not configured, that channel is skipped.

### Twitter/X Setup

1. Create a project and app at [developer.twitter.com](https://developer.twitter.com)
2. The Free tier (1,500 tweets/month) is sufficient
3. Enable OAuth 1.0a with Read + Write permissions
4. Generate consumer keys and access tokens
5. Add them as GitHub secrets

### Telegram Setup

1. Message [@BotFather](https://t.me/BotFather) to create a bot and get the token
2. Add the bot to your group/channel
3. Get the chat ID (send a message in the group, then check `https://api.telegram.org/bot<TOKEN>/getUpdates`)
4. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as GitHub secrets

## Data

Feature gate state is persisted in `data/feature_gates.json` and committed back to the repo after each run. This enables diffing between runs to detect changes.

## License

MIT
