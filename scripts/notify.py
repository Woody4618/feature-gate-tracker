"""
Read data/notifications.json and send alerts to configured channels:
- Slack (via Incoming Webhook)
- Twitter/X (via API v2 with OAuth 1.0a)
- Telegram (via Bot API)

Each channel is optional -- skipped if its environment variables are not set.
"""

import json
import os

import requests

NOTIFICATIONS_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'notifications.json')
EXPLORER_BASE_URL = 'https://explorer.solana.com/address'

SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')
TWITTER_API_KEY = os.environ.get('TWITTER_API_KEY')
TWITTER_API_SECRET = os.environ.get('TWITTER_API_SECRET')
TWITTER_ACCESS_TOKEN = os.environ.get('TWITTER_ACCESS_TOKEN')
TWITTER_ACCESS_SECRET = os.environ.get('TWITTER_ACCESS_SECRET')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')


def _explorer_url(key: str) -> str:
    return f"{EXPLORER_BASE_URL}/{key}"


def load_notifications() -> dict:
    if not os.path.exists(NOTIFICATIONS_PATH):
        print("No notifications file found")
        return {}
    with open(NOTIFICATIONS_PATH, 'r') as f:
        return json.load(f)


def has_anything_to_send(data: dict) -> bool:
    return bool(
        data.get('new_features')
        or data.get('pending_mainnet')
        or data.get('newly_activated')
    )


def _cluster_status(feat: dict) -> str:
    """Which clusters this feature is active on."""
    active = []
    if feat.get('mainnet_epoch'):
        active.append('Mainnet')
    if feat.get('testnet_epoch'):
        active.append('Testnet')
    if feat.get('devnet_epoch'):
        active.append('Devnet')
    return ', '.join(active) if active else 'Pending'


def _epoch_comparison(label: str, activation_epoch, current_epoch) -> str:
    """Format 'Label: 907 (current: 920)' or 'Label: not activated (current: 920)'."""
    current_str = f"current: {current_epoch}" if current_epoch else "current: ?"
    if activation_epoch:
        return f"{label}: {activation_epoch} ({current_str})"
    else:
        return f"{label}: not activated ({current_str})"


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------

def _feature_line_plain(feat: dict, data: dict) -> str:
    parts = [f"  {feat['simds']}: {feat['title']}"]
    parts.append(f"  {_epoch_comparison('Mainnet', feat.get('mainnet_epoch'), data.get('current_mainnet_epoch'))}")
    parts.append(f"  {_epoch_comparison('Testnet', feat.get('testnet_epoch'), data.get('current_testnet_epoch'))}")
    parts.append(f"  {_epoch_comparison('Devnet', feat.get('devnet_epoch'), data.get('current_devnet_epoch'))}")
    parts.append(f"  Key: {feat['key']}")
    parts.append(f"  Explorer: {_explorer_url(feat['key'])}")
    return '\n'.join(parts)


def build_plain_message(data: dict) -> str:
    sections = []

    if data.get('new_features'):
        lines = ["NEW SOLANA FEATURE GATES DETECTED"]
        for feat in data['new_features']:
            status = _cluster_status(feat)
            lines.append("")
            lines.append(f"  {feat['simds']}: {feat['title']}  [Active on: {status}]")
            lines.append(f"  {_epoch_comparison('Mainnet', feat.get('mainnet_epoch'), data.get('current_mainnet_epoch'))}")
            lines.append(f"  {_epoch_comparison('Testnet', feat.get('testnet_epoch'), data.get('current_testnet_epoch'))}")
            lines.append(f"  {_epoch_comparison('Devnet', feat.get('devnet_epoch'), data.get('current_devnet_epoch'))}")
            lines.append(f"  Key: {feat['key']}")
            lines.append(f"  Explorer: {_explorer_url(feat['key'])}")
        sections.append('\n'.join(lines))

    if data.get('pending_mainnet'):
        lines = ["PENDING MAINNET ACTIVATION"]
        for feat in data['pending_mainnet']:
            lines.append("")
            lines.append(_feature_line_plain(feat, data))
        sections.append('\n'.join(lines))

    if data.get('newly_activated'):
        lines = ["NEWLY ACTIVATED ON MAINNET"]
        for feat in data['newly_activated']:
            lines.append("")
            lines.append(_feature_line_plain(feat, data))
        sections.append('\n'.join(lines))

    return '\n\n'.join(sections)


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

def _slack_feature_block(feat: dict, data: dict, show_status: bool = False) -> dict:
    text_parts = [f"*{feat['simds']}*: {feat['title']}"]
    if show_status:
        text_parts[0] += f"  _{_cluster_status(feat)}_"
    if feat.get('simd_links'):
        text_parts.append(f"<{feat['simd_links'][0]}|View SIMD>")
    text_parts.append(f"<{_explorer_url(feat['key'])}|View on Explorer> | `{feat['key']}`")

    text_parts.append(_epoch_comparison('Mainnet', feat.get('mainnet_epoch'), data.get('current_mainnet_epoch')))
    text_parts.append(_epoch_comparison('Testnet', feat.get('testnet_epoch'), data.get('current_testnet_epoch')))
    text_parts.append(_epoch_comparison('Devnet', feat.get('devnet_epoch'), data.get('current_devnet_epoch')))

    if feat.get('agave_versions'):
        text_parts.append(f"Agave: {', '.join(feat['agave_versions'])}")

    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": '\n'.join(text_parts)}
    }


def send_slack(data: dict):
    if not SLACK_WEBHOOK_URL:
        print("Slack: skipped (SLACK_WEBHOOK_URL not set)")
        return

    blocks = []

    if data.get('new_features'):
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": "New Solana Feature Gates Detected"}
        })
        for feat in data['new_features']:
            blocks.append(_slack_feature_block(feat, data, show_status=True))
        blocks.append({"type": "divider"})

    if data.get('pending_mainnet'):
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": "Pending Mainnet Activation"}
        })
        for feat in data['pending_mainnet']:
            blocks.append(_slack_feature_block(feat, data))
        blocks.append({"type": "divider"})

    if data.get('newly_activated'):
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": "Newly Activated on Mainnet"}
        })
        for feat in data['newly_activated']:
            blocks.append(_slack_feature_block(feat, data))

    if not blocks:
        return

    payload = {"blocks": blocks}
    resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=30)
    if resp.status_code == 200:
        print("Slack: sent successfully")
    else:
        print(f"Slack: failed ({resp.status_code}): {resp.text}")


# ---------------------------------------------------------------------------
# Twitter/X
# ---------------------------------------------------------------------------

def _build_tweets(data: dict) -> list[str]:
    """Build a list of tweet texts. Each must be <= 280 chars."""
    tweets = []
    cm = data.get('current_mainnet_epoch')
    ct = data.get('current_testnet_epoch')
    cd = data.get('current_devnet_epoch')

    for feat in data.get('new_features', []):
        status = _cluster_status(feat)
        explorer = _explorer_url(feat['key'])
        tweet = (
            f"New Solana feature gate [{status}]\n\n"
            f"{feat['simds']}: {feat['title']}\n"
            f"{explorer}"
        )
        tweets.append(tweet[:280])

    for feat in data.get('pending_mainnet', []):
        explorer = _explorer_url(feat['key'])
        parts = []
        if feat.get('testnet_epoch') and ct:
            parts.append(f"Testnet: {feat['testnet_epoch']} (now: {ct})")
        if feat.get('devnet_epoch') and cd:
            parts.append(f"Devnet: {feat['devnet_epoch']} (now: {cd})")
        epochs = ' | '.join(parts)
        mainnet_str = f"Mainnet: pending (now: {cm})" if cm else "Mainnet: pending"
        tweet = (
            f"Pending mainnet activation\n\n"
            f"{feat['simds']}: {feat['title']}\n"
            f"{mainnet_str}\n"
            f"{explorer}"
        )
        tweets.append(tweet[:280])

    for feat in data.get('newly_activated', []):
        explorer = _explorer_url(feat['key'])
        epoch_str = f"Activated epoch: {feat.get('mainnet_epoch', '?')}"
        if cm:
            epoch_str += f" (now: {cm})"
        tweet = (
            f"Solana feature gate activated on mainnet\n\n"
            f"{feat['simds']}: {feat['title']}\n"
            f"{epoch_str}\n"
            f"{explorer}"
        )
        tweets.append(tweet[:280])

    return tweets


def send_twitter(data: dict):
    if not all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET]):
        print("Twitter: skipped (credentials not fully configured)")
        return

    try:
        import tweepy
    except ImportError:
        print("Twitter: skipped (tweepy not installed)")
        return

    client = tweepy.Client(
        consumer_key=TWITTER_API_KEY,
        consumer_secret=TWITTER_API_SECRET,
        access_token=TWITTER_ACCESS_TOKEN,
        access_token_secret=TWITTER_ACCESS_SECRET,
    )

    tweets = _build_tweets(data)
    if not tweets:
        return

    previous_tweet_id = None
    for i, tweet_text in enumerate(tweets):
        try:
            if i == 0:
                resp = client.create_tweet(text=tweet_text)
            else:
                resp = client.create_tweet(
                    text=tweet_text,
                    in_reply_to_tweet_id=previous_tweet_id
                )
            previous_tweet_id = resp.data['id']
            print(f"Twitter: posted tweet {i + 1}/{len(tweets)}")
        except Exception as e:
            print(f"Twitter: failed to post tweet {i + 1}: {e}")
            break

    print(f"Twitter: sent {len(tweets)} tweet(s)")


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r'_*[]()~`>#+-=|{}.!'
    for char in special:
        text = text.replace(char, f'\\{char}')
    return text


def _tg_epoch_line(label: str, activation_epoch, current_epoch) -> str:
    current_str = f"current: {current_epoch}" if current_epoch else "current: \\?"
    if activation_epoch:
        return f"{label}: *{activation_epoch}* \\({current_str}\\)"
    else:
        return f"{label}: not activated \\({current_str}\\)"


def _build_telegram_message(data: dict) -> str:
    sections = []
    cm = data.get('current_mainnet_epoch')
    ct = data.get('current_testnet_epoch')
    cd = data.get('current_devnet_epoch')

    if data.get('new_features'):
        lines = [r"*New Solana Feature Gates Detected*", ""]
        for feat in data['new_features']:
            title = _escape_md(feat['title'])
            simds = _escape_md(feat['simds'])
            status = _escape_md(_cluster_status(feat))
            explorer = _explorer_url(feat['key'])
            lines.append(f"{simds}: {title}  \\[{status}\\]")
            lines.append(_tg_epoch_line('Mainnet', feat.get('mainnet_epoch'), cm))
            lines.append(_tg_epoch_line('Testnet', feat.get('testnet_epoch'), ct))
            lines.append(_tg_epoch_line('Devnet', feat.get('devnet_epoch'), cd))
            lines.append(f"Key: `{feat['key']}`")
            lines.append(f"[View on Explorer]({explorer})")
            if feat.get('simd_links'):
                lines.append(f"[View SIMD]({feat['simd_links'][0]})")
            lines.append("")
        sections.append('\n'.join(lines))

    if data.get('pending_mainnet'):
        lines = [r"*Pending Mainnet Activation*", ""]
        for feat in data['pending_mainnet']:
            title = _escape_md(feat['title'])
            simds = _escape_md(feat['simds'])
            explorer = _explorer_url(feat['key'])
            lines.append(f"{simds}: {title}")
            lines.append(_tg_epoch_line('Mainnet', feat.get('mainnet_epoch'), cm))
            lines.append(_tg_epoch_line('Testnet', feat.get('testnet_epoch'), ct))
            lines.append(_tg_epoch_line('Devnet', feat.get('devnet_epoch'), cd))
            lines.append(f"Key: `{feat['key']}`")
            lines.append(f"[View on Explorer]({explorer})")
            lines.append("")
        sections.append('\n'.join(lines))

    if data.get('newly_activated'):
        lines = [r"*Newly Activated on Mainnet*", ""]
        for feat in data['newly_activated']:
            title = _escape_md(feat['title'])
            simds = _escape_md(feat['simds'])
            explorer = _explorer_url(feat['key'])
            lines.append(f"{simds}: {title}")
            lines.append(_tg_epoch_line('Mainnet', feat.get('mainnet_epoch'), cm))
            lines.append(_tg_epoch_line('Testnet', feat.get('testnet_epoch'), ct))
            lines.append(_tg_epoch_line('Devnet', feat.get('devnet_epoch'), cd))
            lines.append(f"Key: `{feat['key']}`")
            lines.append(f"[View on Explorer]({explorer})")
            lines.append("")
        sections.append('\n'.join(lines))

    return '\n'.join(sections)


def send_telegram(data: dict):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram: skipped (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set)")
        return

    message = _build_telegram_message(data)
    if not message.strip():
        return

    if len(message) > 4000:
        message = message[:4000] + "\n\n\\.\\.\\. _truncated_"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }

    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code == 200:
        print("Telegram: sent successfully")
    else:
        print(f"Telegram: failed ({resp.status_code}): {resp.text}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    data = load_notifications()
    if not has_anything_to_send(data):
        print("Nothing to notify about, exiting")
        return

    print(f"Notifications to send: "
          f"{len(data.get('new_features', []))} new, "
          f"{len(data.get('pending_mainnet', []))} pending mainnet, "
          f"{len(data.get('newly_activated', []))} activated")

    plain = build_plain_message(data)
    print("\n--- Notification Preview ---")
    print(plain)
    print("--- End Preview ---\n")

    send_slack(data)
    send_twitter(data)
    send_telegram(data)

    print("Done")


if __name__ == "__main__":
    main()
