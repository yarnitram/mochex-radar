import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest

from cluster_radar.providers.dexscreener import BudgetExceeded, ProviderUnavailable
from cluster_radar.providers.solana_authorities import (
    TOKEN_2022,
    SolanaAuthorities,
    decode_pubkey,
    encode_pubkey,
)

MINT = "So11111111111111111111111111111111111111112"
FIXTURE = (Path(__file__).parent / "fixtures/solana-mint-authorities.json").read_text()


def test_finalized_read_contract_and_partial_security():
    async def run():
        def handle(request):
            body = json.loads(request.content)
            assert request.url.host == "api.mainnet.solana.com"
            assert body == {"jsonrpc":"2.0", "id":1, "method":"getAccountInfo",
                "params":[MINT,{"encoding":"base64", "commitment":"finalized"}]}
            return httpx.Response(200, text=FIXTURE)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = SolanaAuthorities(client, max_requests=1)
            evidence = await provider.check(MINT)
            assert evidence.slot == 123456
            assert evidence.mint_authority_status == "PRESENT"
            assert evidence.mint_authority == "1" * 32
            assert evidence.freeze_authority_status == "DISABLED"
            assert evidence.security_status == "UNKNOWN"
            assert evidence.approved_pump_watch is False
            with pytest.raises(BudgetExceeded):
                await provider.check(MINT)

    asyncio.run(run())


@pytest.mark.parametrize("condition", ["absent", "token2022", "owner", "executable", "token_account", "uninitialized", "option_tag", "both_disabled", "freeze_present"])
def test_missing_unsupported_and_disabled_authorities_never_approve(condition):
    payload = json.loads(FIXTURE)
    value = payload["result"]["value"]
    if condition == "absent":
        payload["result"]["value"] = None
    elif condition == "token2022":
        value["owner"] = TOKEN_2022
    elif condition == "owner":
        value["owner"] = "1" * 32
    elif condition == "executable":
        value["executable"] = True
    else:
        data = bytearray(base64.b64decode(value["data"][0]))
        if condition == "token_account":
            data += bytes(83)
        elif condition == "uninitialized":
            data[45] = 0
        elif condition == "option_tag":
            data[0] = 2
        elif condition == "freeze_present":
            data[46] = 1
            data[81] = 1
        else:
            data[0] = 0
        value["data"][0] = base64.b64encode(data).decode()

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200,json=payload))) as client:
            evidence = await SolanaAuthorities(client).check(MINT)
            assert evidence.security_status == "UNKNOWN"
            assert evidence.approved_pump_watch is False
            if condition == "both_disabled":
                assert evidence.mint_authority_status == "DISABLED"
                assert evidence.freeze_authority_status == "DISABLED"
            elif condition == "freeze_present":
                assert evidence.freeze_authority_status == "PRESENT"
                assert evidence.freeze_authority == "1" * 31 + "2"
            else:
                assert evidence.mint_authority_status == "UNKNOWN"

    asyncio.run(run())


@pytest.mark.parametrize(("status", "body"), [(429,FIXTURE),(403,FIXTURE),(500,FIXTURE),
    (200,'{"jsonrpc":"2.0","id":1,"error":{"code":-32602}}'),(200,'not-json'),
    (200,FIXTURE.replace('"slot": 123456','"slot": true')),
    (200,FIXTURE.replace('"id": 1','"id": 2')),
    (200,FIXTURE.replace('"base64"','"base64+zstd"'))])
def test_rpc_failures_do_not_fabricate_authority_evidence(status, body):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status,text=body))) as client:
            with pytest.raises(ProviderUnavailable):
                await SolanaAuthorities(client).check(MINT)

    asyncio.run(run())


def test_public_key_validation_precedes_transport_and_preserves_leading_zeroes():
    assert decode_pubkey("1" * 32) == bytes(32)
    assert decode_pubkey("1" * 31 + "2") == bytes(31) + b"\x01"
    assert encode_pubkey(bytes(31) + b"\x01") == "1" * 31 + "2"
    assert encode_pubkey(decode_pubkey(MINT)) == MINT

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail("no HTTP"))) as client:
            provider = SolanaAuthorities(client)
            for invalid in ("1" * 31, "z" * 44, "0" * 32):
                with pytest.raises(ValueError):
                    await provider.check(invalid)
            assert provider.requests == 0

    asyncio.run(run())

def test_custom_rpc_url_routing_and_validation():
    async def run():
        def handle(request):
            assert str(request.url).rstrip("/") == "https://dedicated-rpc.internal:8899"
            return httpx.Response(200, text=FIXTURE)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            with pytest.raises(ValueError, match="valid http or https rpc_url"):
                SolanaAuthorities(client, rpc_url="ftp://invalid")
            provider = SolanaAuthorities(client, rpc_url="https://dedicated-rpc.internal:8899")
            obs = await provider.check(MINT)
            assert obs.mint == MINT
            assert obs.slot == 123456

    asyncio.run(run())
