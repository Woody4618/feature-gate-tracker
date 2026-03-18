"""
Read data/notifications.json and send alerts to configured channels:
- Slack (via Incoming Webhook)
- Twitter/X (via API v2 with OAuth 1.0a)
- Telegram (via Bot API)

Each channel is optional -- skipped if its environment variables are not set.
"""

import json
import os
import sys
from datetime import datetime

import requests

NOTIFICATIONS_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'notifications.json')

# Slack
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')

# Twitter/X
TWITTER_API_KEY = os.environ.get('TWITTER_API_KEY')
TWITTER_API_SECRET = os.environ.get('TWITTER_API_SECRET')
TWITTER_ACCESS_TOKEN = os.environ.get('TWITTER_ACCESS_TOKEN')
TWITTER_ACCESS_SECRET = os.environ.get('TWITTER_ACCESS_SECRET')

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')


def load_notifications() -> dict:
    if not os.path.exists(NOTIFICATIONS_PATH):
        print("No notifications file found")
        return {}
    with open(NOTIFICATIONS_PATH, 'r') as f:
        return json.load(f)


def has_anything_to_send(data: dict) -> bool:
    return bool(
        data.get('new_features')
        or data.get('upcoming_activations')
        or data.get('newly_activated')
    )


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

def _feature_line_plain(feat: dict) -> str:
    parts = [f"  {feat['simds']}: {feat['title']}"]
    if feat.get('estimated_activation_date'):
        try:
            dt = datetime.fromisoformat(feat['estimated_activation_date'])
            parts.append(f"  Est. activation: ~{dt.strftime('%B %d, %Y')}")
        except ValueError:
            pass
    if feat.get('mainnet_epoch'):
        parts.append(f"  Mainnet epoch: {feat['mainnet_epoch']}")
    parts.append(f"  Key: {feat['short_key']}")
    return '\n'.join(parts)


def build_plain_message(data: dict) -> str:
    sections = []

    if data.get('new_features'):
        lines = ["NEW SOLANA FEATURE GATES DETECTED"]
        for feat in data['new_features']:
            lines.append("")
            lines.append(_feature_line_plain(feat))
        sections.append('\n'.join(lines))

    if data.get('upcoming_activations'):
        lines = ["UPCOMING MAINNET ACTIVATIONS (next 7 days)"]
        for feat in data['upcoming_activations']:
            lines.append("")
            lines.append(_feature_line_plain(feat))
            if feat.get('testnet_epoch'):
                lines.append(f"  Testnet epoch: {feat['testnet_epoch']}")
            if feat.get('devnet_epoch'):
                lines.append(f"  Devnet epoch: {feat['devnet_epoch']}")
        sections.append('\n'.join(lines))

    if data.get('newly_activated'):
        lines = ["NEWLY ACTIVATED ON MAINNET"]
        for feat in data['newly_activated']:
            lines.append("")
            lines.append(_feature_line_plain(feat))
        sections.append('\n'.join(lines))

    return '\n\n'.join(sections)


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

def _slack_feature_block(feat: dict, include_estimate: bool = False) -> dict:
    text_parts = [f"*{feat['simds']}*: {feat['title']}"]
    if feat.get('simd_links'):
        text_parts.append(f"<{feat['simd_links'][0]}|View SIMD>")
    text_parts.append(f"`{feat['key']}`")

    if include_estimate and feat.get('estimated_activation_date'):
        try:
            dt = datetime.fromisoformat(feat['estimated_activation_date'])
            text_parts.append(f"Est. activation: *~{dt.strftime('%B %d, %Y')}*")
        except ValueError:
            pass

    if feat.get('mainnet_epoch'):
        text_parts.append(f"Mainnet epoch: *{feat['mainnet_epoch']}*")
    if feat.get('testnet_epoch'):
        text_parts.append(f"Testnet epoch: {feat['testnet_epoch']}")
    if feat.get('devnet_epoch'):
        text_parts.append(f"Devnet epoch: {feat['devnet_epoch']}")
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
            blocks.append(_slack_feature_block(feat))
        blocks.append({"type": "divider"})

    if data.get('upcoming_activations'):
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": "Upcoming Mainnet Activations (next 7 days)"}
        })
        for feat in data['upcoming_activations']:
            blocks.append(_slack_feature_block(feat, include_estimate=True))
        blocks.append({"type": "divider"})

    if data.get('newly_activated'):
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": "Newly Activated on Mainnet"}
        })
        for feat in data['newly_activated']:
            blocks.append(_slack_feature_block(feat))

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

    for feat in data.get('new_features', []):
        simd_link = feat['simd_links'][0] if feat.get('simd_links') else ''
        tweet = (
            f"New Solana feature gate detected\n\n"
            f"{feat['simds']}: {feat['title']}\n"
            f"Key: {feat['short_key']}"
        )
        if simd_link:
            tweet += f"\n{simd_link}"
        tweets.append(tweet[:280])

    for feat in data.get('upcoming_activations', []):
        date_str = ''
        if feat.get('estimated_activation_date'):
            try:
                dt = datetime.fromisoformat(feat['estimated_activation_date'])
                date_str = f" (~{dt.strftime('%b %d, %Y')})"
            except ValueError:
                pass
        tweet = (
            f"Heads up: Solana mainnet activation approaching{date_str}\n\n"
            f"{feat['simds']}: {feat['title']}\n"
            f"Key: {feat['short_key']}"
        )
        tweets.append(tweet[:280])

    for feat in data.get('newly_activated', []):
        tweet = (
            f"Solana feature gate activated on mainnet\n\n"
            f"{feat['simds']}: {feat['title']}\n"
            f"Epoch: {feat.get('mainnet_epoch', 'N/A')}\n"
            f"Key: {feat['short_key']}"
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


def _build_telegram_message(data: dict) -> str:
    sections = []

    if data.get('new_features'):
        lines = [r"*New Solana Feature Gates Detected*", ""]
        for feat in data['new_features']:
            title = _escape_md(feat['title'])
            simds = _escape_md(feat['simds'])
            lines.append(f"{simds}: {title}")
            lines.append(f"Key: `{feat['short_key']}`")
            if feat.get('simd_links'):
                link = feat['simd_links'][0]
                lines.append(f"[View SIMD]({link})")
            lines.append("")
        sections.append('\n'.join(lines))

    if data.get('upcoming_activations'):
        lines = [r"*Upcoming Mainnet Activations \(next 7 days\)*", ""]
        for feat in data['upcoming_activations']:
            title = _escape_md(feat['title'])
            simds = _escape_md(feat['simds'])
            lines.append(f"{simds}: {title}")
            lines.append(f"Key: `{feat['short_key']}`")
            if feat.get('estimated_activation_date'):
                try:
                    dt = datetime.fromisoformat(feat['estimated_activation_date'])
                    date_str = _escape_md(f"~{dt.strftime('%B %d, %Y')}")
                    lines.append(f"Est\\. activation: *{date_str}*")
                except ValueError:
                    pass
            if feat.get('testnet_epoch'):
                lines.append(f"Testnet epoch: {feat['testnet_epoch']}")
            if feat.get('devnet_epoch'):
                lines.append(f"Devnet epoch: {feat['devnet_epoch']}")
            lines.append("")
        sections.append('\n'.join(lines))

    if data.get('newly_activated'):
        lines = [r"*Newly Activated on Mainnet*", ""]
        for feat in data['newly_activated']:
            title = _escape_md(feat['title'])
            simds = _escape_md(feat['simds'])
            lines.append(f"{simds}: {title}")
            lines.append(f"Key: `{feat['short_key']}`")
            if feat.get('mainnet_epoch'):
                lines.append(f"Mainnet epoch: {feat['mainnet_epoch']}")
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

    # Telegram messages have a 4096 char limit; truncate if needed
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
          f"{len(data.get('upcoming_activations', []))} upcoming, "
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
