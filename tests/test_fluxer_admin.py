"""Tests for common/fluxer_admin.py (the Fluxer Admin API gateway-stats
client) and the owner-only GET /api/fluxer-stats endpoint it backs.

FLUXER_ADMIN_API_KEY is optional per-deployment (generating one needs
Fluxer instance-staff access), so these pin down the three states a
caller actually needs to tell apart: not configured (None, and a 400
from the endpoint), configured and reachable (real data, cached), and
configured but currently unreachable ({"status": "unknown"}, never
raises).

Verified against a real self-hosted instance's admin API while writing
this: the Node Statistics Object's memory.total/processes/system come
back as JSON strings (e.g. "73891656"), not numbers, which the Fluxer
Status page's formatBytes() specifically accounts for.

config is a frozen dataclass (common/config.py), so tests here swap the
module-level `config` name in whichever module reads it
(dataclasses.replace() for a patched copy) rather than mutating fields
on the shared singleton directly, which would raise FrozenInstanceError.
"""
from __future__ import annotations

import dataclasses

import dashboard.app as app_mod
from common import fluxer_admin
from common.config import config


def _reset_cache():
    fluxer_admin._cache["data"] = None
    fluxer_admin._cache["fetched_at"] = 0.0


def _patch_fluxer_admin_config(monkeypatch, **overrides):
    monkeypatch.setattr(fluxer_admin, "config", dataclasses.replace(config, **overrides))


def _patch_app_config(monkeypatch, **overrides):
    monkeypatch.setattr(app_mod, "config", dataclasses.replace(config, **overrides))


async def test_returns_none_when_unconfigured(monkeypatch):
    _reset_cache()
    _patch_fluxer_admin_config(monkeypatch, fluxer_admin_api_key="")
    assert await fluxer_admin.get_gateway_stats() is None


async def test_returns_fetched_data_when_configured(monkeypatch):
    _reset_cache()
    _patch_fluxer_admin_config(monkeypatch, fluxer_admin_api_key="test-key")

    async def fake_fetch():
        return {"status": "healthy", "sessions": 42}

    monkeypatch.setattr(fluxer_admin, "_fetch", fake_fetch)
    assert await fluxer_admin.get_gateway_stats() == {"status": "healthy", "sessions": 42}


async def test_caches_within_ttl_without_refetching(monkeypatch):
    _reset_cache()
    _patch_fluxer_admin_config(monkeypatch, fluxer_admin_api_key="test-key")
    calls = []

    async def fake_fetch():
        calls.append(1)
        return {"status": "healthy"}

    monkeypatch.setattr(fluxer_admin, "_fetch", fake_fetch)
    await fluxer_admin.get_gateway_stats()
    await fluxer_admin.get_gateway_stats()
    assert len(calls) == 1


async def test_refetches_once_the_ttl_has_elapsed(monkeypatch):
    _reset_cache()
    _patch_fluxer_admin_config(monkeypatch, fluxer_admin_api_key="test-key")
    monkeypatch.setattr(fluxer_admin, "_CACHE_TTL_SECONDS", 0)
    calls = []

    async def fake_fetch():
        calls.append(1)
        return {"status": "healthy"}

    monkeypatch.setattr(fluxer_admin, "_fetch", fake_fetch)
    await fluxer_admin.get_gateway_stats()
    await fluxer_admin.get_gateway_stats()
    assert len(calls) == 2


async def test_a_failed_request_reports_unknown_status_without_raising(monkeypatch):
    _reset_cache()
    _patch_fluxer_admin_config(monkeypatch, fluxer_admin_api_key="test-key")

    async def failing_fetch():
        raise RuntimeError("boom")

    monkeypatch.setattr(fluxer_admin, "_fetch", failing_fetch)
    assert await fluxer_admin.get_gateway_stats() == {"status": "unknown"}


class _FakeRequest:
    def __init__(self, session):
        self.session = session


async def test_fluxer_stats_endpoint_requires_the_bot_owner(monkeypatch):
    _patch_app_config(monkeypatch, owner_id="owner1")

    not_owner = _FakeRequest({"user": {"id": "someone-else"}})
    try:
        await app_mod.api_fluxer_stats(not_owner)
        assert False, "should have required the bot owner"
    except app_mod._ApiError as e:
        assert e.status_code == 403


async def test_fluxer_stats_endpoint_reports_not_configured_clearly(monkeypatch):
    _patch_app_config(monkeypatch, owner_id="owner1")
    _reset_cache()
    _patch_fluxer_admin_config(monkeypatch, fluxer_admin_api_key="")

    owner_req = _FakeRequest({"user": {"id": "owner1"}})
    try:
        await app_mod.api_fluxer_stats(owner_req)
        assert False, "should have reported FLUXER_ADMIN_API_KEY as unset"
    except app_mod._ApiError as e:
        assert e.status_code == 400
        assert "FLUXER_ADMIN_API_KEY" in e.detail


async def test_fluxer_stats_endpoint_returns_real_data_for_the_owner(monkeypatch):
    _patch_app_config(monkeypatch, owner_id="owner1")
    _reset_cache()
    _patch_fluxer_admin_config(monkeypatch, fluxer_admin_api_key="test-key")

    async def fake_fetch():
        return {"status": "healthy", "sessions": 7, "memory": {"total": "73891656"}}

    monkeypatch.setattr(fluxer_admin, "_fetch", fake_fetch)

    owner_req = _FakeRequest({"user": {"id": "owner1"}})
    result = await app_mod.api_fluxer_stats(owner_req)
    assert result == {"status": "healthy", "sessions": 7, "memory": {"total": "73891656"}}
