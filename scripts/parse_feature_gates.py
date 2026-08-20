"""
Read the machine-readable Agave Feature Gate Tracker Schedule from the wiki and
enrich it with on-chain activation data from mainnet, devnet and testnet.
Updates data/feature_gates.json.

Adapted from: https://github.com/solana-foundation/explorer/blob/master/scripts/parse_feature_gates.py
"""

from typing import Annotated, Optional
import asyncio
import requests
import json
import os
from pydantic import BaseModel, Field, BeforeValidator, ConfigDict, ValidationError

from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey

from fetch_mainnet_activations import get_epoch_for_slot

FEATURE_GATES_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'feature_gates.json')
WIKI_JSON_URL = "https://raw.githubusercontent.com/wiki/anza-xyz/agave/feature-gate-tracker-schedule.json"
MAINNET_RPC_URL = os.environ.get('MAINNET_RPC_URL', 'https://api.mainnet-beta.solana.com')
DEVNET_RPC_URL = os.environ.get('DEVNET_RPC_URL', 'https://api.devnet.solana.com')
TESTNET_RPC_URL = os.environ.get('TESTNET_RPC_URL', 'https://api.testnet.solana.com')

# Sections of the wiki JSON to ingest. "Fully Activated" is deliberately left
# out: it lists 200+ features that activated long before this tracker existed,
# and detect_changes would announce every one of them as a new feature.
WIKI_SECTIONS = [
    'Pending Mainnet Beta Activation',
    'Pending Devnet Activation',
    'Pending Testnet Activation',
]

IntOrBlank = Annotated[
    Optional[int],
    BeforeValidator(lambda v: None if v in {'', None} else int(v))
]


def _clean_str_list(v):
    """The wiki JSON pads empty list fields with a blank entry, e.g. SIMDs: [""]."""
    if not isinstance(v, list):
        return v
    return [item.strip() for item in v if isinstance(item, str) and item.strip()]


StrList = Annotated[list[str], BeforeValidator(_clean_str_list)]


class Feature(BaseModel):
    model_config = ConfigDict(populate_by_name=True, json_schema_extra={"type": "object"})

    key: str | None = Field(alias='Feature ID', default=None)
    title: str = Field(alias='Title', default="")
    # Positionally aligned with `simds`; a SIMD with no published proposal
    # keeps an empty slot, so this one is not run through _clean_str_list.
    simd_link: list[str] = Field(default_factory=list, alias='SIMD Links')
    simds: StrList = Field(default_factory=list, alias='SIMDs')
    owners: StrList = Field(default_factory=list, alias='Owners')
    min_agave_versions: StrList = Field(default_factory=list, alias='Min Agave Versions')
    min_fd_versions: StrList = Field(default_factory=list, alias='Min FD Versions')
    min_jito_versions: StrList = Field(default_factory=list, alias='Min Jito Versions')

    planned_testnet_order: IntOrBlank = Field(alias='Planned Testnet Order', default=None)
    testnet_activation_epoch: IntOrBlank = Field(alias='Testnet Epoch', default=None)
    devnet_activation_epoch: IntOrBlank = Field(alias='Devnet Epoch', default=None)
    comms_required: str | None = Field(alias='Comms Required', default=None)


class StoredFeature(Feature):
    model_config = ConfigDict(populate_by_name=True, json_schema_extra={"type": "object"})

    mainnet_activation_epoch: IntOrBlank = Field(alias='Mainnet Epoch', default=None)
    description: str | None = Field(alias='Description', default=None)


def fetch_wiki_features() -> list[StoredFeature]:
    """Read the wiki's machine-readable schedule and return the pending features."""
    response = requests.get(WIKI_JSON_URL)
    if response.status_code != 200:
        raise RuntimeError(f"Failed to fetch wiki JSON: {response.status_code}")

    sections = response.json()
    matched = [s for s in WIKI_SECTIONS if s in sections]
    for section in WIKI_SECTIONS:
        if section not in matched:
            print(f"Warning: section '{section}' not found in wiki JSON, skipping")

    # Every section missing means the wiki renamed them out from under us. Fail
    # loudly rather than quietly writing back the existing data and reporting
    # success, which would stop new features being tracked without anyone noticing.
    if not matched:
        raise RuntimeError(
            f"None of {WIKI_SECTIONS} found in wiki JSON. "
            f"Available sections: {sorted(sections)}"
        )

    features = []
    for section in matched:
        for entry in sections[section]:
            features.append(StoredFeature.model_validate(entry))
    return features


def get_proposals_data():
    proposals_url = "https://api.github.com/repos/solana-foundation/solana-improvement-documents/contents/proposals"
    response = requests.get(proposals_url)
    if response.status_code != 200:
        print(f"Failed to fetch proposals: {response.status_code}")
        return {}

    proposals = {}
    for item in response.json():
        if item['name'].endswith('.md') and item['name'][:4].isdigit():
            simd_number = item['name'][:4]
            proposals[simd_number] = item['html_url']

    return proposals


def safe_model_validate(model, data):
    try:
        return model.model_validate(data)
    except ValidationError:
        return None


RATE_LIMIT_DELAY = 0.5
MAX_RETRIES = 3


async def fetch_activation_epoch(connection: AsyncClient, epoch_schedule, key: str, backup_epoch: int | None) -> int | None:
    account = None
    for attempt in range(MAX_RETRIES):
        try:
            await asyncio.sleep(RATE_LIMIT_DELAY)
            account = await connection.get_account_info(Pubkey.from_string(key))
            break
        except Exception as e:
            if '429' in str(e) and attempt < MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                print(f"Rate limited on {key}, retrying in {wait}s...")
                await asyncio.sleep(wait)
            else:
                print(f"Failed to fetch {key}: {e}")
                return backup_epoch

    if account is None:
        return backup_epoch

    if account.value and account.value.data:
        is_activated = account.value.data[0]
        if is_activated:
            activation_slot = int.from_bytes(account.value.data[1:9], 'little')
            return get_epoch_for_slot(epoch_schedule, activation_slot)
        else:
            return backup_epoch
    else:
        return backup_epoch


async def fetch_cluster_activations(cluster_url: str, features_to_check: list[tuple[StoredFeature, StoredFeature]]) -> None:
    if not features_to_check:
        return

    if "devnet" in cluster_url:
        cluster_name = "devnet"
    elif "testnet" in cluster_url:
        cluster_name = "testnet"
    else:
        cluster_name = "mainnet"

    async with AsyncClient(cluster_url) as connection:
        epoch_schedule = (await connection.get_epoch_schedule()).value
        if epoch_schedule is None:
            print(f"[{cluster_name}] Failed to fetch epoch schedule, skipping cluster.")
            return

        for existing, new_feature in features_to_check:
            if cluster_name == 'devnet':
                existing.devnet_activation_epoch = await fetch_activation_epoch(
                    connection, epoch_schedule, existing.key, existing.devnet_activation_epoch
                )
            elif cluster_name == 'testnet':
                existing.testnet_activation_epoch = await fetch_activation_epoch(
                    connection, epoch_schedule, existing.key, existing.testnet_activation_epoch
                )
            elif cluster_name == 'mainnet':
                existing.mainnet_activation_epoch = await fetch_activation_epoch(
                    connection, epoch_schedule, existing.key, existing.mainnet_activation_epoch
                )
            print(f"  [{cluster_name}] Checked {existing.key}")


async def parse_wiki():
    features = fetch_wiki_features()
    print(f"Read {len(features)} pending features from the wiki schedule")

    proposals = get_proposals_data()
    for feature in features:
        feature.simd_link = [
            proposals.get(simd.zfill(4), "") if simd.isdigit() else ""
            for simd in feature.simds
        ]

    existing_features: list[StoredFeature] = []
    if os.path.exists(FEATURE_GATES_PATH):
        with open(FEATURE_GATES_PATH, 'r') as f:
            current = json.load(f)

        for feature in current:
            if safe_model_validate(StoredFeature, feature):
                existing_features.append(StoredFeature.model_validate(feature))
            else:
                raise ValueError(f"Unknown feature: {feature}")

    features_by_key: dict[str, StoredFeature] = {f.key: f for f in features if f.key is not None}
    features_to_check: list[tuple[StoredFeature, StoredFeature]] = []
    for existing in existing_features:
        if existing.key in features_by_key:
            features_to_check.append((existing, features_by_key[existing.key]))
            del features_by_key[existing.key]

    stale_features = [
        (existing, existing)
        for existing in existing_features
        if existing.key not in {e.key for e, _ in features_to_check}
        and (not existing.mainnet_activation_epoch
             or not existing.devnet_activation_epoch
             or not existing.testnet_activation_epoch)
    ]
    all_to_check = features_to_check + stale_features

    print(f"Checking {len(all_to_check)} features ({len(features_to_check)} from wiki, "
          f"{len(stale_features)} stale) against mainnet, devnet and testnet...")
    await fetch_cluster_activations(MAINNET_RPC_URL, all_to_check)
    await fetch_cluster_activations(DEVNET_RPC_URL, all_to_check)
    await fetch_cluster_activations(TESTNET_RPC_URL, all_to_check)

    new_features = list(features_by_key.values())
    if new_features:
        print("New features:")
        for f in new_features:
            print(f"  {f.key} - {f.title}")

    all_features = existing_features + new_features

    with open(FEATURE_GATES_PATH, 'w') as f:
        json.dump([feat.model_dump() for feat in all_features], f, indent=2)

    print(f"Wrote {len(all_features)} features to {FEATURE_GATES_PATH}")


if __name__ == "__main__":
    asyncio.run(parse_wiki())
