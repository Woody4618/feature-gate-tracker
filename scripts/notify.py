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

from detect_changes import format_countdown

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
        or data.get('pending_devnet')
        or data.get('pending_testnet')
        or data.get('newly_activated')
        or data.get('newly_activated_devnet')
        or data.get('newly_activated_testnet')
    )


def _cluster_status(feat: dict) -> str:
    """Which clusters this feature is active on."""
    active = []
    if feat.get('mainnet_epoch'):
        active.append('Mainnet')
    if feat.get('devnet_epoch'):
        active.append('Devnet')
    if feat.get('testnet_epoch'):
        active.append('Testnet')
    return ', '.join(active) if active else 'Pending'


def _epoch_line(label: str, activation_epoch, current_epoch, countdown: dict | None = None) -> str:
    if activation_epoch and current_epoch:
        diff = current_epoch - activation_epoch
        if diff == 0:
            age = "current epoch"
        elif diff == 1:
            age = "1 epoch ago"
        else:
            age = f"{diff} epochs ago"
        return f"{label}: activated epoch {activation_epoch} ({age})"
    elif activation_epoch:
        return f"{label}: activated epoch {activation_epoch}"
    elif countdown and countdown.get('next_epoch') and countdown.get('remaining_hours') is not None:
        cd = format_countdown(countdown['remaining_hours'])
        return f"{label}: pending \u23f3 activates epoch {countdown['next_epoch']} ({cd})"
    else:
        return f"{label}: pending \u23f3"


def _get_countdowns(data: dict) -> dict:
    """Extract per-cluster countdown dicts from notification data."""
    return {
        'mainnet': data.get('mainnet_countdown', {}),
        'testnet': data.get('testnet_countdown', {}),
        'devnet': data.get('devnet_countdown', {}),
    }


def _countdown_header(countdown: dict) -> str | None:
    if not countdown:
        return None
    next_epoch = countdown.get('next_epoch')
    remaining_hours = countdown.get('remaining_hours')
    if next_epoch is None or remaining_hours is None:
        return None
    return f"Next epoch: {next_epoch} (in {format_countdown(remaining_hours)})"


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------

def _feature_line_plain(feat: dict, data: dict, countdowns: dict | None = None) -> str:
    cd = countdowns or {}
    parts = [f"  {feat['simds']}: {feat['title']}"]
    parts.append(f"  {_epoch_line('Mainnet', feat.get('mainnet_epoch'), data.get('current_mainnet_epoch'), cd.get('mainnet'))}")
    parts.append(f"  {_epoch_line('Devnet', feat.get('devnet_epoch'), data.get('current_devnet_epoch'), cd.get('devnet'))}")
    parts.append(f"  {_epoch_line('Testnet', feat.get('testnet_epoch'), data.get('current_testnet_epoch'), cd.get('testnet'))}")
    parts.append(f"  Key: {feat['key']}")
    parts.append(f"  Explorer: {_explorer_url(feat['key'])}")
    return '\n'.join(parts)


def build_plain_message(data: dict) -> str:
    sections = []
    countdowns = _get_countdowns(data)

    if data.get('new_features'):
        lines = ["NEW SOLANA FEATURE GATES DETECTED"]
        for feat in data['new_features']:
            status = _cluster_status(feat)
            lines.append("")
            lines.append(f"  {feat['simds']}: {feat['title']}  [Active on: {status}]")
            lines.append(f"  {_epoch_line('Mainnet', feat.get('mainnet_epoch'), data.get('current_mainnet_epoch'))}")
            lines.append(f"  {_epoch_line('Devnet', feat.get('devnet_epoch'), data.get('current_devnet_epoch'))}")
            lines.append(f"  {_epoch_line('Testnet', feat.get('testnet_epoch'), data.get('current_testnet_epoch'))}")
            lines.append(f"  Key: {feat['key']}")
            lines.append(f"  Explorer: {_explorer_url(feat['key'])}")
        sections.append('\n'.join(lines))

    if data.get('pending_mainnet'):
        lines = ["PENDING MAINNET ACTIVATION"]
        header = _countdown_header(countdowns.get('mainnet'))
        if header:
            lines.append(f"  Mainnet {header}")
        cd_mainnet_only = {'mainnet': countdowns.get('mainnet')}
        for feat in data['pending_mainnet']:
            lines.append("")
            lines.append(_feature_line_plain(feat, data, countdowns=cd_mainnet_only))
        sections.append('\n'.join(lines))

    if data.get('pending_devnet'):
        lines = ["PENDING DEVNET ACTIVATION"]
        header = _countdown_header(countdowns.get('devnet'))
        if header:
            lines.append(f"  Devnet {header}")
        cd_devnet_only = {'devnet': countdowns.get('devnet')}
        for feat in data['pending_devnet']:
            lines.append("")
            lines.append(_feature_line_plain(feat, data, countdowns=cd_devnet_only))
        sections.append('\n'.join(lines))

    if data.get('pending_testnet'):
        lines = ["PENDING TESTNET ACTIVATION"]
        header = _countdown_header(countdowns.get('testnet'))
        if header:
            lines.append(f"  Testnet {header}")
        cd_testnet_only = {'testnet': countdowns.get('testnet')}
        for feat in data['pending_testnet']:
            lines.append("")
            lines.append(_feature_line_plain(feat, data, countdowns=cd_testnet_only))
        sections.append('\n'.join(lines))

    if data.get('newly_activated'):
        lines = ["NEWLY ACTIVATED ON MAINNET"]
        for feat in data['newly_activated']:
            lines.append("")
            lines.append(_feature_line_plain(feat, data))
        sections.append('\n'.join(lines))

    if data.get('newly_activated_devnet'):
        lines = ["NEWLY ACTIVATED ON DEVNET"]
        for feat in data['newly_activated_devnet']:
            lines.append("")
            lines.append(_feature_line_plain(feat, data))
        sections.append('\n'.join(lines))

    if data.get('newly_activated_testnet'):
        lines = ["NEWLY ACTIVATED ON TESTNET"]
        for feat in data['newly_activated_testnet']:
            lines.append("")
            lines.append(_feature_line_plain(feat, data))
        sections.append('\n'.join(lines))

    return '\n\n'.join(sections)


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

def _slack_feature_block(feat: dict, data: dict, show_status: bool = False, countdowns: dict | None = None) -> dict:
    cd = countdowns or {}
    text_parts = [f"*{feat['simds']}*: {feat['title']}"]
    if show_status:
        text_parts[0] += f"  _{_cluster_status(feat)}_"
    if feat.get('simd_links'):
        text_parts.append(f"<{feat['simd_links'][0]}|View SIMD>")
    text_parts.append(f"<{_explorer_url(feat['key'])}|View on Explorer> | `{feat['key']}`")

    text_parts.append(_epoch_line('Mainnet', feat.get('mainnet_epoch'), data.get('current_mainnet_epoch'), cd.get('mainnet')))
    text_parts.append(_epoch_line('Devnet', feat.get('devnet_epoch'), data.get('current_devnet_epoch'), cd.get('devnet')))
    text_parts.append(_epoch_line('Testnet', feat.get('testnet_epoch'), data.get('current_testnet_epoch'), cd.get('testnet')))

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
    countdowns = _get_countdowns(data)

    if data.get('new_features'):
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": "New Solana Feature Gates Detected"}
        })
        for feat in data['new_features']:
            blocks.append(_slack_feature_block(feat, data, show_status=True))
        blocks.append({"type": "divider"})

    for pending_key, cluster_name, cd_key in [
        ('pending_mainnet', 'Mainnet', 'mainnet'),
        ('pending_devnet', 'Devnet', 'devnet'),
        ('pending_testnet', 'Testnet', 'testnet'),
    ]:
        if data.get(pending_key):
            hdr = _countdown_header(countdowns.get(cd_key))
            header_text = f"Pending {cluster_name} Activation"
            if hdr:
                header_text += f" \u2014 {cluster_name} {hdr}"
            blocks.append({
                "type": "header",
                "text": {"type": "plain_text", "text": header_text[:150]}
            })
            cd_scoped = {cd_key: countdowns.get(cd_key)}
            for feat in data[pending_key]:
                blocks.append(_slack_feature_block(feat, data, countdowns=cd_scoped))
            blocks.append({"type": "divider"})

    for activated_key, cluster_name in [
        ('newly_activated', 'Mainnet'),
        ('newly_activated_devnet', 'Devnet'),
        ('newly_activated_testnet', 'Testnet'),
    ]:
        if data.get(activated_key):
            blocks.append({
                "type": "header",
                "text": {"type": "plain_text", "text": f"Newly Activated on {cluster_name}"}
            })
            for feat in data[activated_key]:
                blocks.append(_slack_feature_block(feat, data))
            blocks.append({"type": "divider"})

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

    countdowns = _get_countdowns(data)
    for feat in data.get('pending_mainnet', []):
        explorer = _explorer_url(feat['key'])
        mainnet_str = _epoch_line('Mainnet', feat.get('mainnet_epoch'), cm, countdowns.get('mainnet'))
        devnet_str = _epoch_line('Devnet', feat.get('devnet_epoch'), cd)
        testnet_str = _epoch_line('Testnet', feat.get('testnet_epoch'), ct)
        tweet = (
            f"Pending mainnet activation\n\n"
            f"{feat['simds']}: {feat['title']}\n"
            f"{mainnet_str}\n"
            f"{devnet_str}\n"
            f"{testnet_str}\n"
            f"{explorer}"
        )
        tweets.append(tweet[:280])

    for feat in data.get('pending_devnet', []):
        explorer = _explorer_url(feat['key'])
        devnet_str = _epoch_line('Devnet', feat.get('devnet_epoch'), cd, countdowns.get('devnet'))
        testnet_str = _epoch_line('Testnet', feat.get('testnet_epoch'), ct)
        tweet = (
            f"Pending devnet activation\n\n"
            f"{feat['simds']}: {feat['title']}\n"
            f"{devnet_str}\n"
            f"{testnet_str}\n"
            f"{explorer}"
        )
        tweets.append(tweet[:280])

    for feat in data.get('pending_testnet', []):
        explorer = _explorer_url(feat['key'])
        testnet_str = _epoch_line('Testnet', feat.get('testnet_epoch'), ct, countdowns.get('testnet'))
        tweet = (
            f"Pending testnet activation\n\n"
            f"{feat['simds']}: {feat['title']}\n"
            f"{testnet_str}\n"
            f"{explorer}"
        )
        tweets.append(tweet[:280])

    for feat in data.get('newly_activated', []):
        explorer = _explorer_url(feat['key'])
        mainnet_epoch = feat.get('mainnet_epoch', '?')
        tweet = (
            f"Solana feature gate activated on mainnet \u2705\n\n"
            f"{feat['simds']}: {feat['title']}\n"
            f"Activated epoch {mainnet_epoch}\n"
            f"{explorer}"
        )
        tweets.append(tweet[:280])

    for feat in data.get('newly_activated_devnet', []):
        explorer = _explorer_url(feat['key'])
        devnet_epoch = feat.get('devnet_epoch', '?')
        tweet = (
            f"Solana feature gate activated on devnet\n\n"
            f"{feat['simds']}: {feat['title']}\n"
            f"Devnet epoch {devnet_epoch}\n"
            f"{explorer}"
        )
        tweets.append(tweet[:280])

    for feat in data.get('newly_activated_testnet', []):
        explorer = _explorer_url(feat['key'])
        testnet_epoch = feat.get('testnet_epoch', '?')
        tweet = (
            f"Solana feature gate activated on testnet\n\n"
            f"{feat['simds']}: {feat['title']}\n"
            f"Testnet epoch {testnet_epoch}\n"
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


def _tg_epoch_line(label: str, activation_epoch, current_epoch, countdown: dict | None = None) -> str:
    if activation_epoch and current_epoch:
        diff = current_epoch - activation_epoch
        if diff == 0:
            age = "current epoch"
        elif diff == 1:
            age = "1 epoch ago"
        else:
            age = f"{diff} epochs ago"
        return f"{label}: activated epoch *{activation_epoch}* \\({age}\\)"
    elif activation_epoch:
        return f"{label}: activated epoch *{activation_epoch}*"
    elif countdown and countdown.get('next_epoch') and countdown.get('remaining_hours') is not None:
        cd = _escape_md(format_countdown(countdown['remaining_hours']))
        return f"{label}: pending \u23f3 activates epoch *{countdown['next_epoch']}* \\({cd}\\)"
    else:
        return f"{label}: pending \u23f3"


def _build_telegram_message(data: dict) -> str:
    sections = []
    cm = data.get('current_mainnet_epoch')
    ct = data.get('current_testnet_epoch')
    cd = data.get('current_devnet_epoch')
    countdowns = _get_countdowns(data)

    if data.get('new_features'):
        lines = [r"*New Solana Feature Gates Detected*", ""]
        for feat in data['new_features']:
            title = _escape_md(feat['title'])
            simds = _escape_md(feat['simds'])
            status = _escape_md(_cluster_status(feat))
            explorer = _explorer_url(feat['key'])
            lines.append(f"{simds}: {title}  \\[{status}\\]")
            lines.append(_tg_epoch_line('Mainnet', feat.get('mainnet_epoch'), cm))
            lines.append(_tg_epoch_line('Devnet', feat.get('devnet_epoch'), cd))
            lines.append(_tg_epoch_line('Testnet', feat.get('testnet_epoch'), ct))
            lines.append(f"Key: `{feat['key']}`")
            lines.append(f"[View on Explorer]({explorer})")
            if feat.get('simd_links'):
                lines.append(f"[View SIMD]({feat['simd_links'][0]})")
            lines.append("")
        sections.append('\n'.join(lines))

    cluster_epoch_vars = {'mainnet': cm, 'devnet': cd, 'testnet': ct}
    for pending_key, cluster_label, cluster_cd_key in [
        ('pending_mainnet', 'Mainnet', 'mainnet'),
        ('pending_devnet', 'Devnet', 'devnet'),
        ('pending_testnet', 'Testnet', 'testnet'),
    ]:
        if data.get(pending_key):
            cl_cd = countdowns.get(cluster_cd_key, {})
            lines = [f"*Pending {cluster_label} Activation*"]
            next_ep = cl_cd.get('next_epoch')
            remaining_h = cl_cd.get('remaining_hours')
            if next_ep and remaining_h is not None:
                cd_str = _escape_md(format_countdown(remaining_h))
                lines.append(f"{cluster_label} next epoch: *{next_ep}* \\(in {cd_str}\\)")
            lines.append("")
            for feat in data[pending_key]:
                title = _escape_md(feat['title'])
                simds = _escape_md(feat['simds'])
                explorer = _explorer_url(feat['key'])
                lines.append(f"{simds}: {title}")
                lines.append(_tg_epoch_line('Mainnet', feat.get('mainnet_epoch'), cm,
                             countdowns.get('mainnet') if cluster_cd_key == 'mainnet' else None))
                lines.append(_tg_epoch_line('Devnet', feat.get('devnet_epoch'), cd,
                             countdowns.get('devnet') if cluster_cd_key == 'devnet' else None))
                lines.append(_tg_epoch_line('Testnet', feat.get('testnet_epoch'), ct,
                             countdowns.get('testnet') if cluster_cd_key == 'testnet' else None))
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
            lines.append(_tg_epoch_line('Devnet', feat.get('devnet_epoch'), cd))
            lines.append(_tg_epoch_line('Testnet', feat.get('testnet_epoch'), ct))
            lines.append(f"Key: `{feat['key']}`")
            lines.append(f"[View on Explorer]({explorer})")
            lines.append("")
        sections.append('\n'.join(lines))

    for activated_key, cluster_name in [
        ('newly_activated_devnet', 'Devnet'),
        ('newly_activated_testnet', 'Testnet'),
    ]:
        if data.get(activated_key):
            lines = [f"*Newly Activated on {cluster_name}*", ""]
            for feat in data[activated_key]:
                title = _escape_md(feat['title'])
                simds = _escape_md(feat['simds'])
                explorer = _explorer_url(feat['key'])
                lines.append(f"{simds}: {title}")
                lines.append(_tg_epoch_line('Mainnet', feat.get('mainnet_epoch'), cm))
                lines.append(_tg_epoch_line('Devnet', feat.get('devnet_epoch'), cd))
                lines.append(_tg_epoch_line('Testnet', feat.get('testnet_epoch'), ct))
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
          f"{len(data.get('pending_devnet', []))} pending devnet, "
          f"{len(data.get('pending_testnet', []))} pending testnet, "
          f"{len(data.get('newly_activated', []))} activated mainnet, "
          f"{len(data.get('newly_activated_devnet', []))} activated devnet, "
          f"{len(data.get('newly_activated_testnet', []))} activated testnet")

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
