"""
Compare the previous and current feature_gates.json to detect:
1. Newly added features (keys that didn't exist before)
2. Features estimated to activate on mainnet within the next 7 days
3. Features that were just activated on mainnet (got mainnet_activation_epoch since last run)

Outputs data/notifications.json with structured messages for notify.py.

The previous state is read from git (HEAD:data/feature_gates.json) before any
modifications were made in the current run.
"""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

from solana.rpc.async_api import AsyncClient

FEATURE_GATES_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'feature_gates.json')
NOTIFICATIONS_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'notifications.json')
MAINNET_RPC_URL = os.environ.get('MAINNET_RPC_URL', 'https://api.mainnet-beta.solana.com')

SLOTS_PER_EPOCH = 432_000
SLOT_DURATION_MS = 400
EPOCH_DURATION_SECONDS = SLOTS_PER_EPOCH * SLOT_DURATION_MS / 1000
WARNING_DAYS = 7


def load_previous_features() -> list[dict]:
    """Load the previous feature_gates.json from git HEAD."""
    try:
        result = subprocess.run(
            ['git', 'show', 'HEAD:data/feature_gates.json'],
            capture_output=True, text=True, check=True,
            cwd=os.path.join(os.path.dirname(__file__), '..')
        )
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        print("No previous feature_gates.json in git history, treating all as new")
        return []


def load_current_features() -> list[dict]:
    with open(FEATURE_GATES_PATH, 'r') as f:
        return json.load(f)


def find_new_features(previous: list[dict], current: list[dict]) -> list[dict]:
    prev_keys = {f['key'] for f in previous if f.get('key')}
    return [f for f in current if f.get('key') and f['key'] not in prev_keys]


def find_newly_activated(previous: list[dict], current: list[dict]) -> list[dict]:
    """Features that just got a mainnet_activation_epoch (had None before, has value now)."""
    prev_by_key = {f['key']: f for f in previous if f.get('key')}
    result = []
    for feat in current:
        key = feat.get('key')
        if not key:
            continue
        prev = prev_by_key.get(key)
        if prev and not prev.get('mainnet_activation_epoch') and feat.get('mainnet_activation_epoch'):
            result.append(feat)
    return result


async def estimate_activation_dates(features: list[dict]) -> list[dict]:
    """
    For features that are on devnet+testnet but not yet on mainnet,
    estimate when they might activate based on current epoch progression.
    """
    candidates = [
        f for f in features
        if f.get('devnet_activation_epoch')
        and f.get('testnet_activation_epoch')
        and not f.get('mainnet_activation_epoch')
    ]

    if not candidates:
        return []

    try:
        async with AsyncClient(MAINNET_RPC_URL) as connection:
            epoch_info_resp = await connection.get_epoch_info()
            epoch_info = epoch_info_resp.value
    except Exception as e:
        print(f"Failed to get epoch info from mainnet: {e}")
        return []

    current_epoch = epoch_info.epoch
    slot_index = epoch_info.slot_index
    slots_in_epoch = epoch_info.slots_in_epoch

    slots_remaining_in_epoch = slots_in_epoch - slot_index
    seconds_remaining = slots_remaining_in_epoch * SLOT_DURATION_MS / 1000
    epoch_end_time = datetime.now(timezone.utc) + timedelta(seconds=seconds_remaining)

    now = datetime.now(timezone.utc)
    warning_threshold = now + timedelta(days=WARNING_DAYS)

    upcoming = []
    for feat in candidates:
        # We don't know the exact mainnet target epoch, but features typically
        # follow testnet -> devnet -> mainnet order. The wiki "Pending Mainnet"
        # table indicates they're expected next. We estimate based on the
        # assumption they'll activate in one of the upcoming epochs.
        #
        # Heuristic: use the devnet epoch lag as a rough guide, but since we
        # don't have a specific target, we check if the feature has been on
        # both testnets and flag it as "upcoming" with an estimated date based
        # on next few epochs.

        # For features in "Pending Mainnet" status, the estimated activation
        # is typically within the next few epochs. We calculate the earliest
        # possible epoch (current + 1) and latest reasonable (current + 5).
        estimated_epoch = current_epoch + 1
        epochs_away = estimated_epoch - current_epoch
        estimated_seconds = seconds_remaining + (epochs_away - 1) * EPOCH_DURATION_SECONDS
        estimated_date = now + timedelta(seconds=estimated_seconds)

        if estimated_date <= warning_threshold:
            feat_with_date = dict(feat)
            feat_with_date['estimated_activation_date'] = estimated_date.isoformat()
            feat_with_date['estimated_epoch'] = estimated_epoch
            feat_with_date['epochs_away'] = epochs_away
            upcoming.append(feat_with_date)

    return upcoming


def format_feature_summary(feat: dict) -> dict:
    """Extract the key fields for notification messages."""
    key = feat.get('key', 'unknown')
    short_key = key[:8] + '...' if len(key) > 8 else key
    simds = feat.get('simds', [])
    simd_str = ', '.join(f'SIMD-{s.zfill(4)}' for s in simds) if simds else 'N/A'
    simd_links = feat.get('simd_link', [])
    title = feat.get('title') or feat.get('description') or 'Untitled'

    return {
        'key': key,
        'short_key': short_key,
        'title': title,
        'simds': simd_str,
        'simd_links': [l for l in simd_links if l],
        'agave_versions': feat.get('min_agave_versions', []),
        'fd_versions': feat.get('min_fd_versions', []),
        'testnet_epoch': feat.get('testnet_activation_epoch'),
        'devnet_epoch': feat.get('devnet_activation_epoch'),
        'mainnet_epoch': feat.get('mainnet_activation_epoch'),
        'estimated_activation_date': feat.get('estimated_activation_date'),
        'estimated_epoch': feat.get('estimated_epoch'),
        'epochs_away': feat.get('epochs_away'),
    }


async def main():
    previous = load_previous_features()
    current = load_current_features()

    new_features = find_new_features(previous, current)
    newly_activated = find_newly_activated(previous, current)
    upcoming_activations = await estimate_activation_dates(current)

    notifications = {
        'run_date': datetime.now(timezone.utc).isoformat(),
        'new_features': [format_feature_summary(f) for f in new_features],
        'upcoming_activations': [format_feature_summary(f) for f in upcoming_activations],
        'newly_activated': [format_feature_summary(f) for f in newly_activated],
    }

    total = len(new_features) + len(upcoming_activations) + len(newly_activated)
    print(f"Detected {len(new_features)} new features, "
          f"{len(upcoming_activations)} upcoming activations, "
          f"{len(newly_activated)} newly activated")

    with open(NOTIFICATIONS_PATH, 'w') as f:
        json.dump(notifications, f, indent=2)

    print(f"Wrote notifications to {NOTIFICATIONS_PATH}")

    if total == 0:
        print("Nothing to notify about")
    else:
        print(f"{total} notification(s) to send")

    return total > 0


if __name__ == "__main__":
    has_notifications = asyncio.run(main())
    sys.exit(0)
