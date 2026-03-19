"""
Compare the previous and current feature_gates.json to detect:
1. Newly added features (keys that didn't exist before)
2. Features pending mainnet activation (active on devnet + testnet, not yet on mainnet)
3. Features that were just activated on mainnet (got mainnet_activation_epoch since last run)

Outputs data/notifications.json with structured messages for notify.py.

The previous state is read from git (HEAD:data/feature_gates.json) before any
modifications were made in the current run.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

from solana.rpc.async_api import AsyncClient

FEATURE_GATES_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'feature_gates.json')
NOTIFICATIONS_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'notifications.json')
MAINNET_RPC_URL = os.environ.get('MAINNET_RPC_URL', 'https://api.mainnet-beta.solana.com')
TESTNET_RPC_URL = os.environ.get('TESTNET_RPC_URL', 'https://api.testnet.solana.com')
DEVNET_RPC_URL = os.environ.get('DEVNET_RPC_URL', 'https://api.devnet.solana.com')


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


async def get_current_epoch(rpc_url: str, cluster_name: str) -> int | None:
    try:
        async with AsyncClient(rpc_url) as connection:
            epoch_info_resp = await connection.get_epoch_info()
            epoch = epoch_info_resp.value.epoch
            print(f"Current {cluster_name} epoch: {epoch}")
            return epoch
    except Exception as e:
        print(f"Failed to get current epoch from {cluster_name}: {e}")
        return None


async def get_all_current_epochs() -> dict:
    mainnet, testnet, devnet = await asyncio.gather(
        get_current_epoch(MAINNET_RPC_URL, "mainnet"),
        get_current_epoch(TESTNET_RPC_URL, "testnet"),
        get_current_epoch(DEVNET_RPC_URL, "devnet"),
    )
    return {
        'current_mainnet_epoch': mainnet,
        'current_testnet_epoch': testnet,
        'current_devnet_epoch': devnet,
    }


def find_pending_mainnet(features: list[dict]) -> list[dict]:
    """
    Features that are active on devnet + testnet but not yet on mainnet.
    These are in the pipeline for mainnet activation -- no estimated date
    since we don't know when the activation will be triggered.
    Sorted by testnet activation epoch (earliest first = likely activated sooner).
    """
    candidates = [
        f for f in features
        if f.get('devnet_activation_epoch')
        and f.get('testnet_activation_epoch')
        and not f.get('mainnet_activation_epoch')
    ]
    candidates.sort(key=lambda f: f.get('testnet_activation_epoch', 0))
    return candidates


def format_feature_summary(feat: dict) -> dict:
    """Extract the key fields for notification messages."""
    key = feat.get('key', 'unknown')
    simds = feat.get('simds', [])
    simd_str = ', '.join(f'SIMD-{s.zfill(4)}' for s in simds) if simds else 'N/A'
    simd_links = feat.get('simd_link', [])
    title = feat.get('title') or feat.get('description') or 'Untitled'

    title = re.sub(r'^SIMD-\d+:\s*', '', title)

    return {
        'key': key,
        'title': title,
        'simds': simd_str,
        'simd_links': [l for l in simd_links if l],
        'agave_versions': feat.get('min_agave_versions', []),
        'fd_versions': feat.get('min_fd_versions', []),
        'testnet_epoch': feat.get('testnet_activation_epoch'),
        'devnet_epoch': feat.get('devnet_activation_epoch'),
        'mainnet_epoch': feat.get('mainnet_activation_epoch'),
    }


async def main():
    previous = load_previous_features()
    current = load_current_features()

    new_features = find_new_features(previous, current)
    newly_activated = find_newly_activated(previous, current)
    pending_mainnet = find_pending_mainnet(current)
    current_epochs = await get_all_current_epochs()

    notifications = {
        'run_date': datetime.now(timezone.utc).isoformat(),
        **current_epochs,
        'new_features': [format_feature_summary(f) for f in new_features],
        'pending_mainnet': [format_feature_summary(f) for f in pending_mainnet],
        'newly_activated': [format_feature_summary(f) for f in newly_activated],
    }

    total = len(new_features) + len(pending_mainnet) + len(newly_activated)
    print(f"Detected {len(new_features)} new features, "
          f"{len(pending_mainnet)} pending mainnet, "
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
