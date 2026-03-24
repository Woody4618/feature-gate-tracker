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
from solders.pubkey import Pubkey

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


SLOT_DURATION_MS = 400


async def get_epoch_info_for_cluster(rpc_url: str, cluster_name: str) -> dict:
    """Fetch current epoch and countdown to next epoch for a cluster."""
    try:
        async with AsyncClient(rpc_url) as connection:
            epoch_info_resp = await connection.get_epoch_info()
            info = epoch_info_resp.value
            remaining_slots = info.slots_in_epoch - info.slot_index
            remaining_seconds = (remaining_slots * SLOT_DURATION_MS) / 1000
            remaining_hours = remaining_seconds / 3600
            print(f"Current {cluster_name} epoch: {info.epoch}")
            return {
                'epoch': info.epoch,
                'countdown': {
                    'remaining_slots': remaining_slots,
                    'remaining_hours': round(remaining_hours, 1),
                    'next_epoch': info.epoch + 1,
                },
            }
    except Exception as e:
        print(f"Failed to get epoch info from {cluster_name}: {e}")
        return {}


def format_countdown(hours: float) -> str:
    if hours < 1:
        return f"~{int(hours * 60)}m"
    days = int(hours // 24)
    h = int(hours % 24)
    if days > 0:
        return f"~{days}d {h}h"
    return f"~{h}h"


async def get_all_cluster_info() -> dict:
    mainnet, testnet, devnet = await asyncio.gather(
        get_epoch_info_for_cluster(MAINNET_RPC_URL, "mainnet"),
        get_epoch_info_for_cluster(TESTNET_RPC_URL, "testnet"),
        get_epoch_info_for_cluster(DEVNET_RPC_URL, "devnet"),
    )
    return {
        'current_mainnet_epoch': mainnet.get('epoch'),
        'current_testnet_epoch': testnet.get('epoch'),
        'current_devnet_epoch': devnet.get('epoch'),
        'mainnet_countdown': mainnet.get('countdown', {}),
        'testnet_countdown': testnet.get('countdown', {}),
        'devnet_countdown': devnet.get('countdown', {}),
    }


RATE_LIMIT_DELAY = 0.5
MAX_RETRIES = 3


async def check_mainnet_account_exists(connection: AsyncClient, key: str) -> bool:
    """Check if a feature account has been created on mainnet (submitted for activation)."""
    for attempt in range(MAX_RETRIES):
        try:
            await asyncio.sleep(RATE_LIMIT_DELAY)
            account = await connection.get_account_info(Pubkey.from_string(key))
            return account.value is not None
        except Exception as e:
            if '429' in str(e) and attempt < MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                print(f"Rate limited checking {key}, retrying in {wait}s...")
                await asyncio.sleep(wait)
            else:
                print(f"Failed to check {key}: {e}")
                return False
    return False


async def find_pending_mainnet(features: list[dict]) -> list[dict]:
    """
    Features that are active on devnet + testnet but not yet on mainnet,
    AND whose feature account has been created on mainnet (meaning Anza devops
    has submitted the activation). Features whose account doesn't exist on
    mainnet yet are not included -- they haven't entered the activation pipeline.
    Sorted by testnet activation epoch (earliest first = likely activated sooner).
    """
    candidates = [
        f for f in features
        if f.get('devnet_activation_epoch')
        and f.get('testnet_activation_epoch')
        and not f.get('mainnet_activation_epoch')
    ]
    candidates.sort(key=lambda f: f.get('testnet_activation_epoch', 0))

    if not candidates:
        return []

    async with AsyncClient(MAINNET_RPC_URL) as connection:
        pending = []
        for feat in candidates:
            key = feat.get('key')
            if not key:
                continue
            exists = await check_mainnet_account_exists(connection, key)
            if exists:
                print(f"  {key}: account exists on mainnet (pending activation)")
                pending.append(feat)
            else:
                print(f"  {key}: account not yet created on mainnet, skipping")
        return pending


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
    print("Checking which pending features have accounts on mainnet...")
    pending_mainnet = await find_pending_mainnet(current)
    cluster_info = await get_all_cluster_info()

    notifications = {
        'run_date': datetime.now(timezone.utc).isoformat(),
        **cluster_info,
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
