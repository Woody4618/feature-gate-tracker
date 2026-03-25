"""
Query mainnet RPC for feature gate activation status. For features that are
active on devnet and testnet but not yet on mainnet, checks the on-chain
account data to determine if/when they were activated.

Updates data/feature_gates.json in place.

Adapted from: https://github.com/solana-foundation/explorer/blob/master/scripts/fetch_mainnet_activations.py
"""

import asyncio
import json
import os

from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey

FEATURE_GATES_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'feature_gates.json')
MAINNET_RPC_URL = os.environ.get('MAINNET_RPC_URL', 'https://api.mainnet-beta.solana.com')
RATE_LIMIT_DELAY = 0.5
MAX_RETRIES = 3
MINIMUM_SLOT_PER_EPOCH = 32


def trailing_zeros(n: int) -> int:
    return (n & -n).bit_length() - 1


def next_power_of_two(n: int) -> int:
    return 1 << (n - 1).bit_length()


def get_epoch_for_slot(epoch_schedule, slot: int) -> int:
    if slot < epoch_schedule.first_normal_slot:
        power = next_power_of_two(slot + MINIMUM_SLOT_PER_EPOCH + 1)
        epoch = (trailing_zeros(power) -
                 trailing_zeros(MINIMUM_SLOT_PER_EPOCH) -
                 1)
        return epoch
    else:
        normal_slot_index = slot - epoch_schedule.first_normal_slot
        normal_epoch_index = normal_slot_index // epoch_schedule.slots_per_epoch
        return epoch_schedule.first_normal_epoch + normal_epoch_index


def get_features():
    with open(FEATURE_GATES_PATH, 'r') as f:
        return json.load(f)


async def main():
    features = get_features()

    async with AsyncClient(MAINNET_RPC_URL) as connection:
        epoch_schedule = (await connection.get_epoch_schedule()).value

        for feature in features:
            if not feature.get('mainnet_activation_epoch'):
                print(f"Fetching feature gate {feature['key']}")

                account = None
                for attempt in range(MAX_RETRIES):
                    try:
                        await asyncio.sleep(RATE_LIMIT_DELAY)
                        account = await connection.get_account_info(Pubkey.from_string(feature['key']))
                        break
                    except Exception as e:
                        if '429' in str(e) and attempt < MAX_RETRIES - 1:
                            wait = 2 ** (attempt + 1)
                            print(f"Rate limited on {feature['key']}, retrying in {wait}s...")
                            await asyncio.sleep(wait)
                        else:
                            print(f"Failed to fetch {feature['key']}: {e}")
                            break

                if account is None:
                    continue

                if account.value and account.value.data:
                    is_activated = account.value.data[0]

                    if is_activated:
                        activation_slot = int.from_bytes(account.value.data[1:9], 'little')
                        activation_epoch = get_epoch_for_slot(epoch_schedule, activation_slot)
                        print(f"  {feature['key']} activated at epoch {activation_epoch}")
                        feature['mainnet_activation_epoch'] = activation_epoch
                    else:
                        print(f"  {feature['key']} initialized but not activated")

    with open(FEATURE_GATES_PATH, 'w') as f:
        json.dump(features, f, indent=2)

    print(f"Updated {FEATURE_GATES_PATH}")


if __name__ == '__main__':
    asyncio.run(main())
