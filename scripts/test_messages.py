"""
Test script to preview notification messages for different scenarios.
Run: python scripts/test_messages.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from notify import build_plain_message, _slack_feature_block, _build_tweets, _build_telegram_message, _get_countdowns
import json

CURRENT_EPOCHS = {
    'current_mainnet_epoch': 758,
    'current_testnet_epoch': 928,
    'current_devnet_epoch': 1045,
    'mainnet_countdown': {
        'remaining_slots': 180000,
        'remaining_hours': 20.0,
        'next_epoch': 759,
    },
    'testnet_countdown': {
        'remaining_slots': 200000,
        'remaining_hours': 22.2,
        'next_epoch': 929,
    },
    'devnet_countdown': {
        'remaining_slots': 50000,
        'remaining_hours': 5.6,
        'next_epoch': 1046,
    },
}


def scenario_new_feature():
    """A brand new feature gate just appeared on the wiki (on testnet only so far)."""
    return {
        **CURRENT_EPOCHS,
        'new_features': [
            {
                'key': 'ptokFjwyJtrwCa9Kgo9xoDS59V4QccBGEaRFnRPnSdP',
                'title': 'Efficient Token program',
                'simds': 'SIMD-0266',
                'simd_links': ['https://github.com/solana-foundation/solana-improvement-documents/blob/main/proposals/0266-efficient-token-program.md'],
                'agave_versions': ['v3.1.7'],
                'fd_versions': ['v0.811.30108'],
                'testnet_epoch': 920,
                'devnet_epoch': None,
                'mainnet_epoch': None,
            }
        ],
        'pending_mainnet': [],
        'newly_activated': [],
    }


def scenario_pending_mainnet():
    """Features active on testnet + devnet, pending mainnet activation."""
    return {
        **CURRENT_EPOCHS,
        'new_features': [],
        'pending_mainnet': [
            {
                'key': 'rent6iVy6PDoViPBeJ6k5EJQrkj62h7DPyLbWGHwjrC',
                'title': 'Deprecate rent exemption threshold',
                'simds': 'SIMD-0194',
                'simd_links': ['https://github.com/solana-foundation/solana-improvement-documents/blob/main/proposals/0194-deprecate-rent-exemption-threshold.md'],
                'agave_versions': ['v3.1.0'],
                'fd_versions': ['v0.806.30102'],
                'testnet_epoch': 907,
                'devnet_epoch': 1023,
                'mainnet_epoch': None,
            },
            {
                'key': 'CHaChatUnR3s6cPyPMMGNJa3VdQQ8PNH2JqdD4LpCKnB',
                'title': 'Reduce ChaCha rounds for Turbine from 20 to 8',
                'simds': 'SIMD-0332',
                'simd_links': [],
                'agave_versions': ['v3.1.0'],
                'fd_versions': ['v0.812.30108'],
                'testnet_epoch': 909,
                'devnet_epoch': 1029,
                'mainnet_epoch': None,
            },
        ],
        'newly_activated': [],
    }


def scenario_newly_activated():
    """A feature just got activated on mainnet."""
    return {
        **CURRENT_EPOCHS,
        'new_features': [],
        'pending_mainnet': [],
        'newly_activated': [
            {
                'key': '5xXZc66h4UdB6Yq7FzdBxBiRAFMMScMLwHxk2QZDaNZL',
                'title': 'Instruction Data Pointer in VM Register 2',
                'simds': 'SIMD-0321',
                'simd_links': ['https://github.com/solana-foundation/solana-improvement-documents/blob/main/proposals/0321-instruction-data-pointer.md'],
                'agave_versions': ['v3.1.0'],
                'fd_versions': ['v0.806.30102'],
                'testnet_epoch': 911,
                'devnet_epoch': 1034,
                'mainnet_epoch': 758,
            }
        ],
    }


def scenario_pending_devnet():
    """Feature active on testnet, account exists on devnet, pending devnet activation."""
    return {
        **CURRENT_EPOCHS,
        'new_features': [],
        'pending_mainnet': [],
        'pending_devnet': [
            {
                'key': 'ptokFjwyJtrwCa9Kgo9xoDS59V4QccBGEaRFnRPnSdP',
                'title': 'Efficient Token program',
                'simds': 'SIMD-0266',
                'simd_links': ['https://github.com/solana-foundation/solana-improvement-documents/blob/main/proposals/0266-efficient-token-program.md'],
                'agave_versions': ['v3.1.8'],
                'fd_versions': ['v0.811.30108'],
                'testnet_epoch': 931,
                'devnet_epoch': None,
                'mainnet_epoch': None,
            }
        ],
        'pending_testnet': [],
        'newly_activated': [],
        'newly_activated_devnet': [],
        'newly_activated_testnet': [],
    }


def scenario_newly_activated_devnet():
    """A feature just got activated on devnet."""
    return {
        **CURRENT_EPOCHS,
        'new_features': [],
        'pending_mainnet': [],
        'pending_devnet': [],
        'pending_testnet': [],
        'newly_activated': [],
        'newly_activated_devnet': [
            {
                'key': 'ptokFjwyJtrwCa9Kgo9xoDS59V4QccBGEaRFnRPnSdP',
                'title': 'Efficient Token program',
                'simds': 'SIMD-0266',
                'simd_links': ['https://github.com/solana-foundation/solana-improvement-documents/blob/main/proposals/0266-efficient-token-program.md'],
                'agave_versions': ['v3.1.8'],
                'fd_versions': ['v0.811.30108'],
                'testnet_epoch': 931,
                'devnet_epoch': 1044,
                'mainnet_epoch': None,
            }
        ],
        'newly_activated_testnet': [],
    }


def scenario_newly_activated_testnet():
    """A feature just got activated on testnet."""
    return {
        **CURRENT_EPOCHS,
        'new_features': [],
        'pending_mainnet': [],
        'pending_devnet': [],
        'pending_testnet': [],
        'newly_activated': [],
        'newly_activated_devnet': [],
        'newly_activated_testnet': [
            {
                'key': 'ptokFjwyJtrwCa9Kgo9xoDS59V4QccBGEaRFnRPnSdP',
                'title': 'Efficient Token program',
                'simds': 'SIMD-0266',
                'simd_links': ['https://github.com/solana-foundation/solana-improvement-documents/blob/main/proposals/0266-efficient-token-program.md'],
                'agave_versions': ['v3.1.8'],
                'fd_versions': ['v0.811.30108'],
                'testnet_epoch': 931,
                'devnet_epoch': None,
                'mainnet_epoch': None,
            }
        ],
    }


def scenario_combined():
    """All types happening at once (busy day)."""
    s1 = scenario_new_feature()
    s2 = scenario_pending_mainnet()
    s3 = scenario_newly_activated()
    s4 = scenario_newly_activated_devnet()
    s5 = scenario_newly_activated_testnet()
    s6 = scenario_pending_devnet()
    return {
        **CURRENT_EPOCHS,
        'new_features': s1['new_features'],
        'pending_mainnet': s2['pending_mainnet'],
        'pending_devnet': s6['pending_devnet'],
        'pending_testnet': [],
        'newly_activated': s3['newly_activated'],
        'newly_activated_devnet': s4['newly_activated_devnet'],
        'newly_activated_testnet': s5['newly_activated_testnet'],
    }


DIVIDER = "=" * 70


def print_scenario(name, data):
    print(f"\n{DIVIDER}")
    print(f"  SCENARIO: {name}")
    print(DIVIDER)

    # Plain text (used in logs and as a preview)
    print(f"\n--- Plain Text ---\n")
    print(build_plain_message(data))

    # Slack blocks (show the JSON structure)
    print(f"\n--- Slack (Block Kit preview) ---\n")
    countdowns = _get_countdowns(data)
    if data.get('new_features'):
        for feat in data['new_features']:
            block = _slack_feature_block(feat, data, show_status=True, countdowns=countdowns)
            print(block['text']['text'])
            print()
    for pending_key in ['pending_mainnet', 'pending_devnet', 'pending_testnet']:
        if data.get(pending_key):
            for feat in data[pending_key]:
                block = _slack_feature_block(feat, data, countdowns=countdowns)
                print(block['text']['text'])
                print()
    if data.get('newly_activated'):
        for feat in data['newly_activated']:
            block = _slack_feature_block(feat, data)
            print(block['text']['text'])
            print()
    if data.get('newly_activated_devnet'):
        for feat in data['newly_activated_devnet']:
            block = _slack_feature_block(feat, data, countdowns=countdowns)
            print(block['text']['text'])
            print()
    if data.get('newly_activated_testnet'):
        for feat in data['newly_activated_testnet']:
            block = _slack_feature_block(feat, data, countdowns=countdowns)
            print(block['text']['text'])
            print()

    # Twitter
    print(f"--- Twitter ---\n")
    tweets = _build_tweets(data)
    for i, tweet in enumerate(tweets):
        print(f"Tweet {i+1} ({len(tweet)} chars):")
        print(tweet)
        print()

    # Telegram (raw MarkdownV2)
    print(f"--- Telegram (MarkdownV2) ---\n")
    tg = _build_telegram_message(data)
    print(tg)
    print()


if __name__ == "__main__":
    print_scenario("New feature gate added (testnet only)", scenario_new_feature())
    print_scenario("Pending mainnet activation", scenario_pending_mainnet())
    print_scenario("Pending devnet activation", scenario_pending_devnet())
    print_scenario("Newly activated on mainnet", scenario_newly_activated())
    print_scenario("Newly activated on devnet", scenario_newly_activated_devnet())
    print_scenario("Newly activated on testnet", scenario_newly_activated_testnet())
    print_scenario("All types at once", scenario_combined())
