"""
Fetch live data and write notification previews to files.
Run: python scripts/preview_live.py

Outputs:
  data/preview_slack.json   - Slack Block Kit payload
  data/preview_twitter.txt  - Tweet texts
  data/preview_telegram.txt - Telegram MarkdownV2 message
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')


async def main():
    from parse_feature_gates import parse_wiki
    from detect_changes import main as detect_main

    print("=== Step 1: Fetching feature gates from wiki + on-chain ===")
    await parse_wiki()

    print("\n=== Step 2: Detecting changes ===")
    await detect_main()

    from notify import (
        load_notifications,
        has_anything_to_send,
        build_plain_message,
        _get_countdowns,
        _slack_feature_block,
        _countdown_header,
        _build_tweets,
        _build_telegram_message,
    )

    data = load_notifications()
    if not has_anything_to_send(data):
        print("\nNothing to notify about. No preview files written.")
        return

    countdowns = _get_countdowns(data)

    # --- Slack ---
    blocks = []

    if data.get('new_features'):
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": "New Solana Feature Gates Detected"}})
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
            blocks.append({"type": "header", "text": {"type": "plain_text", "text": header_text[:150]}})
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
            blocks.append({"type": "header", "text": {"type": "plain_text", "text": f"Newly Activated on {cluster_name}"}})
            for feat in data[activated_key]:
                blocks.append(_slack_feature_block(feat, data))
            blocks.append({"type": "divider"})

    slack_path = os.path.join(OUTPUT_DIR, 'preview_slack.json')
    with open(slack_path, 'w') as f:
        json.dump({"blocks": blocks}, f, indent=2)
    print(f"\nSlack preview -> {slack_path}")

    # --- Twitter ---
    tweets = _build_tweets(data)
    twitter_path = os.path.join(OUTPUT_DIR, 'preview_twitter.txt')
    with open(twitter_path, 'w') as f:
        for i, tweet in enumerate(tweets):
            f.write(f"--- Tweet {i+1} ({len(tweet)} chars) ---\n")
            f.write(tweet)
            f.write("\n\n")
    print(f"Twitter preview -> {twitter_path}")

    # --- Telegram ---
    tg_message = _build_telegram_message(data)
    telegram_path = os.path.join(OUTPUT_DIR, 'preview_telegram.txt')
    with open(telegram_path, 'w') as f:
        f.write(tg_message)
    print(f"Telegram preview -> {telegram_path}")

    # --- Plain text summary to stdout ---
    print(f"\n{'=' * 60}")
    print("PLAIN TEXT PREVIEW")
    print('=' * 60)
    print(build_plain_message(data))


if __name__ == "__main__":
    asyncio.run(main())
