"""
Compare the previous and current feature_gates.json to detect:
1. Newly added features (keys that didn't exist before)
2. Features pending activation on any cluster (account exists but not yet activated)
3. Features that were just activated on any cluster (got activation_epoch since last run)

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


MAX_ACTIVATION_AGE_EPOCHS = 2


def find_newly_activated(
    previous: list[dict],
    current: list[dict],
    epoch_field: str = 'mainnet_activation_epoch',
    current_epoch: int | None = None,
) -> list[dict]:
    """Features that just got an activation epoch (had None before, has value now).
    Filters out activations older than MAX_ACTIVATION_AGE_EPOCHS to avoid
    reporting stale backfilled data as new activations."""
    prev_by_key = {f['key']: f for f in previous if f.get('key')}
    result = []
    for feat in current:
        key = feat.get('key')
        if not key:
            continue
        prev = prev_by_key.get(key)
        if prev and not prev.get(epoch_field) and feat.get(epoch_field):
            if current_epoch is not None:
                age = current_epoch - feat[epoch_field]
                if age > MAX_ACTIVATION_AGE_EPOCHS:
                    print(f"  Skipping {key}: {epoch_field} = {feat[epoch_field]} "
                          f"({age} epochs ago, stale backfill)")
                    continue
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


FEATURE_GATE_PROGRAM_ID = Pubkey.from_string("Feature111111111111111111111111111111111111")


async def check_feature_account(connection: AsyncClient, key: str) -> bool:
    """Check if a feature account exists and is owned by the Feature Gate program.
    Accounts that exist but are owned by another program (e.g. System Program
    because someone just sent SOL to the address) are not real feature accounts."""
    for attempt in range(MAX_RETRIES):
        try:
            await asyncio.sleep(RATE_LIMIT_DELAY)
            account = await connection.get_account_info(Pubkey.from_string(key))
            if account.value is None:
                return False
            return account.value.owner == FEATURE_GATE_PROGRAM_ID
        except Exception as e:
            if '429' in str(e) and attempt < MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                print(f"Rate limited checking {key}, retrying in {wait}s...")
                await asyncio.sleep(wait)
            else:
                print(f"Failed to check {key}: {e}")
                return False
    return False


async def find_pending_cluster(
    features: list[dict],
    rpc_url: str,
    cluster_name: str,
    activation_field: str,
    prerequisite_fields: list[str] | None = None,
) -> list[dict]:
    """
    Find features pending activation on a cluster: not yet activated there,
    but the feature account exists (submitted for activation).
    prerequisite_fields: optional list of epoch fields that must already be set
    (e.g. devnet+testnet must be active before mainnet).
    """
    prereqs = prerequisite_fields or []
    candidates = [
        f for f in features
        if not f.get(activation_field)
        and all(f.get(p) for p in prereqs)
    ]
    candidates.sort(key=lambda f: f.get('testnet_activation_epoch') or 0)

    if not candidates:
        return []

    print(f"Checking which features have accounts on {cluster_name}...")
    async with AsyncClient(rpc_url) as connection:
        pending = []
        for feat in candidates:
            key = feat.get('key')
            if not key:
                continue
            is_feature = await check_feature_account(connection, key)
            if is_feature:
                print(f"  {key}: feature account on {cluster_name} (pending activation)")
                pending.append(feat)
            else:
                print(f"  {key}: no feature account on {cluster_name}, skipping")
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
    cluster_info = await get_all_cluster_info()

    newly_activated = find_newly_activated(
        previous, current, 'mainnet_activation_epoch', cluster_info.get('current_mainnet_epoch'))
    newly_activated_devnet = find_newly_activated(
        previous, current, 'devnet_activation_epoch', cluster_info.get('current_devnet_epoch'))
    newly_activated_testnet = find_newly_activated(
        previous, current, 'testnet_activation_epoch', cluster_info.get('current_testnet_epoch'))

    pending_mainnet = await find_pending_cluster(
        current, MAINNET_RPC_URL, "mainnet",
        'mainnet_activation_epoch',
    )
    pending_devnet = await find_pending_cluster(
        current, DEVNET_RPC_URL, "devnet",
        'devnet_activation_epoch',
    )
    pending_testnet = await find_pending_cluster(
        current, TESTNET_RPC_URL, "testnet",
        'testnet_activation_epoch',
    )

    notifications = {
        'run_date': datetime.now(timezone.utc).isoformat(),
        **cluster_info,
        'new_features': [format_feature_summary(f) for f in new_features],
        'pending_mainnet': [format_feature_summary(f) for f in pending_mainnet],
        'pending_devnet': [format_feature_summary(f) for f in pending_devnet],
        'pending_testnet': [format_feature_summary(f) for f in pending_testnet],
        'newly_activated': [format_feature_summary(f) for f in newly_activated],
        'newly_activated_devnet': [format_feature_summary(f) for f in newly_activated_devnet],
        'newly_activated_testnet': [format_feature_summary(f) for f in newly_activated_testnet],
    }

    total = (len(new_features)
             + len(pending_mainnet) + len(pending_devnet) + len(pending_testnet)
             + len(newly_activated) + len(newly_activated_devnet) + len(newly_activated_testnet))
    print(f"Detected {len(new_features)} new, "
          f"{len(pending_mainnet)} pending mainnet, "
          f"{len(pending_devnet)} pending devnet, "
          f"{len(pending_testnet)} pending testnet, "
          f"{len(newly_activated)} activated mainnet, "
          f"{len(newly_activated_devnet)} activated devnet, "
          f"{len(newly_activated_testnet)} activated testnet")

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
