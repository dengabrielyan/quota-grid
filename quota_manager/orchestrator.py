from __future__ import annotations

import copy
import fcntl
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from typing import Any, Iterator

from . import __version__
from .model import SCHEMA_VERSION, empty_snapshot
from .notify import notify_resets
from .providers import ALL_PROVIDERS, Provider, ProviderError
from .util import (
    atomic_write_json,
    cache_path,
    ensure_private_dir,
    load_config,
    lock_path,
    now_ts,
    read_json,
    reset_state_path,
    safe_error,
    state_dir,
)

LOG = logging.getLogger(__name__)


@contextmanager
def _refresh_lock() -> Iterator[bool]:
    ensure_private_dir(state_dir())
    handle = open(lock_path(), "a+", encoding="utf-8")
    locked = False
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError:
            locked = False
        yield locked
    finally:
        if locked:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def _provider_instances() -> list[Provider]:
    instances: list[Provider] = []
    for provider_type in ALL_PROVIDERS:
        try:
            instance = provider_type()
            if instance.detected():
                instances.append(instance)
        except Exception:
            LOG.debug("provider detection failed for %s", provider_type.id, exc_info=True)
    return instances


def _load_previous() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    snapshot = read_json(cache_path(), {})
    if not isinstance(snapshot, dict):
        snapshot = {}
    previous: dict[str, dict[str, Any]] = {}
    for item in snapshot.get("providers") or []:
        if isinstance(item, dict) and item.get("id"):
            previous[str(item["id"])] = item
    return snapshot, previous


def _empty_provider(instance: Provider, now: int, error: str) -> dict[str, Any]:
    return {
        "id": instance.id,
        "name": instance.name,
        "icon": instance.icon,
        "account": "",
        "badge": "",
        "status": "error",
        "error": error,
        "retry_at": None,
        "note": None,
        "windows": [],
        "fetched_at": 0,
        "last_attempt_at": now,
    }


def _display_previous(previous: dict[str, Any], now: int, error: str, retry_at: int | None) -> dict[str, Any]:
    item = copy.deepcopy(previous)
    item["status"] = "error"
    item["error"] = error
    item["retry_at"] = retry_at
    item["last_attempt_at"] = now
    return item


def _refresh_provider(instance: Provider) -> dict[str, Any]:
    data = instance.fetch()
    data["status"] = "ok"
    data["error"] = None
    data["retry_at"] = None
    data["last_attempt_at"] = now_ts()
    return data


def _fetch_all(
    instances: list[Provider],
    previous: dict[str, dict[str, Any]],
    *,
    now: int,
    ignore_cooldown: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    results: dict[str, dict[str, Any]] = {}
    fresh: list[dict[str, Any]] = []
    pending: list[Provider] = []

    for instance in instances:
        prior = previous.get(instance.id)
        if (
            not ignore_cooldown
            and isinstance(prior, dict)
            and isinstance(prior.get("retry_at"), (int, float))
            and prior["retry_at"] > now
        ):
            item = copy.deepcopy(prior)
            item["status"] = "error"
            item["last_attempt_at"] = now
            results[instance.id] = item
        else:
            pending.append(instance)

    errors: dict[str, ProviderError] = {}
    if pending:
        executor = ThreadPoolExecutor(max_workers=min(4, len(pending)), thread_name_prefix="quota")
        futures = {executor.submit(_refresh_provider, instance): instance for instance in pending}
        try:
            for future in as_completed(futures, timeout=55):
                instance = futures[future]
                try:
                    item = future.result()
                except ProviderError as exc:
                    errors[instance.id] = exc
                except Exception as exc:
                    LOG.warning("provider %s failed: %s", instance.id, type(exc).__name__)
                    errors[instance.id] = ProviderError("Не удалось получить квоту.")
                else:
                    results[instance.id] = item
                    fresh.append(item)
        except TimeoutError:
            LOG.warning("provider refresh exceeded overall timeout")
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    for instance in pending:
        if instance.id in results:
            continue
        error = errors.get(instance.id, ProviderError("Источник не ответил вовремя."))
        retry_after = error.retry_after if isinstance(error.retry_after, int) else None
        retry_at = now + retry_after if retry_after else None
        message = safe_error(error.message)
        prior = previous.get(instance.id)
        if isinstance(prior, dict) and prior.get("windows"):
            item = _display_previous(prior, now, message, retry_at)
        else:
            item = _empty_provider(instance, now, message)
            item["retry_at"] = retry_at
        results[instance.id] = item

    ordered = [results[instance.id] for instance in instances if instance.id in results]
    return ordered, fresh


def _load_reset_state() -> dict[str, Any]:
    raw = read_json(reset_state_path(), {})
    if not isinstance(raw, dict):
        raw = {}
    windows = raw.get("windows")
    events = raw.get("events")
    if not isinstance(windows, dict):
        windows = {}
    if not isinstance(events, list):
        events = []
    return {
        "version": 1,
        "seeded_at": raw.get("seeded_at"),
        "windows": windows,
        "events": events,
    }


def _save_reset_state(state: dict[str, Any]) -> None:
    cutoff = now_ts() - 30 * 86400
    events = [
        event
        for event in state.get("events", [])
        if isinstance(event, dict) and isinstance(event.get("at"), (int, float)) and event["at"] >= cutoff
    ][-100:]
    state["events"] = events
    atomic_write_json(reset_state_path(), state)


def _record_resets(
    state: dict[str, Any],
    fresh_providers: list[dict[str, Any]],
    now: int,
    *,
    should_notify: bool,
) -> list[dict[str, Any]]:
    markers = state["windows"]
    first_seed = not bool(state.get("seeded_at"))
    reset_groups: dict[str, list[dict[str, Any]]] = {}
    fresh_any = False

    for provider in fresh_providers:
        for window in provider.get("windows") or []:
            fresh_any = True
            resets_at = window.get("resets_at")
            if not isinstance(resets_at, (int, float)) or resets_at <= 0:
                continue
            key = f"{provider['id']}:{window.get('id')}"
            previous = markers.get(key)
            if not first_seed and isinstance(previous, dict):
                old = previous.get("resets_at")
                if (
                    isinstance(old, (int, float))
                    and resets_at > old + 30
                    and old <= now + 10
                ):
                    reset_groups.setdefault(provider["id"], []).append(
                        {
                            "title": window.get("title") or "Лимит",
                            "period": window.get("period"),
                            "resets_at": int(resets_at),
                        }
                    )
            markers[key] = {
                "resets_at": int(resets_at),
                "title": window.get("title") or "Лимит",
                "provider_name": provider.get("name") or provider.get("id"),
                "updated_at": now,
            }

    if first_seed and fresh_any:
        state["seeded_at"] = now
        return []

    created_events: list[dict[str, Any]] = []
    for provider in fresh_providers:
        windows = reset_groups.get(provider["id"])
        if not windows:
            continue
        labels: list[str] = []
        for window in windows:
            if window["title"] not in labels:
                labels.append(str(window["title"]))
        event = {
            "provider_id": provider["id"],
            "provider_name": provider.get("name") or provider["id"],
            "labels": labels,
            "at": now,
        }
        created_events.append(event)
        state["events"].append(event)
        if should_notify:
            notify_resets(str(event["provider_name"]), windows)

    return created_events


def _provider_summary(providers: list[dict[str, Any]]) -> str:
    if not providers:
        return "empty"
    ok = sum(1 for provider in providers if provider.get("status") == "ok")
    if ok == len(providers):
        return "ok"
    if ok == 0:
        return "error"
    return "degraded"


def refresh(*, notify: bool = False, ignore_cooldown: bool = False) -> dict[str, Any]:
    config = load_config()
    interval = int(config["refresh_interval_seconds"])
    with _refresh_lock() as locked:
        if not locked:
            snapshot = read_json(cache_path(), None)
            if isinstance(snapshot, dict):
                snapshot = copy.deepcopy(snapshot)
                snapshot["refreshing"] = True
                return snapshot
            snapshot = empty_snapshot(interval)
            snapshot["refreshing"] = True
            return snapshot

        now = now_ts()
        previous_snapshot, previous_providers = _load_previous()
        instances = _provider_instances()
        providers, fresh = _fetch_all(
            instances,
            previous_providers,
            now=now,
            ignore_cooldown=ignore_cooldown,
        )

        reset_state = _load_reset_state()
        should_notify = bool(config.get("notifications", True)) and notify
        _record_resets(reset_state, fresh, now, should_notify=should_notify)
        _save_reset_state(reset_state)

        recent_resets = [
            {
                "provider_id": event.get("provider_id"),
                "provider_name": event.get("provider_name"),
                "labels": event.get("labels") or [],
                "at": int(event.get("at") or 0),
            }
            for event in reset_state.get("events", [])
            if isinstance(event, dict) and int(event.get("at") or 0) >= now - 86400
        ][-5:]

        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "app_version": __version__,
            "generated_at": now,
            "next_refresh_at": now + interval,
            "interval_seconds": interval,
            "status": _provider_summary(providers),
            "providers": providers,
            "recent_resets": recent_resets,
        }
        if previous_snapshot.get("schema_version") not in (None, SCHEMA_VERSION):
            LOG.info("upgraded cache schema from %s", previous_snapshot.get("schema_version"))
        atomic_write_json(cache_path(), snapshot)
        LOG.info(
            "refresh complete: %s",
            ", ".join(f"{item.get('id')}={item.get('status')}" for item in providers) or "no providers",
        )
        return snapshot


def status() -> dict[str, Any]:
    snapshot = read_json(cache_path(), None)
    if not isinstance(snapshot, dict):
        return empty_snapshot(int(load_config()["refresh_interval_seconds"]))
    return snapshot
