import json
from datetime import datetime, timedelta, timezone

import pytest

import app.main as main
from tests.test_weather_resilience import FALLBACK, NOW, Response, fail_requests, PAYLOAD


REAL_WEATHER = {
    "available": True,
    "temperature": 19,
    "apparent_temperature": 18,
    "condition": "Nublado",
    "min": 10,
    "max": 22,
    "rain_probability": 20,
    "wind": 8,
    "advice": "Ideal para recorrer.",
    "forecast": [],
}


@pytest.fixture(autouse=True)
def isolated_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "WEATHER_SNAPSHOT_PATH", tmp_path / "system" / "weather_snapshot.json")
    monkeypatch.setattr(main, "utc_now", lambda: NOW)
    monkeypatch.setattr(main, "_weather_persisted_snapshot_loaded", False)
    monkeypatch.setattr(main, "_weather_persisted_snapshot_valid", False)
    main._weather_cache.update({
        "data": None, "expires_at": None, "stale_until": None,
        "last_success_at": None, "retry_after": None,
    })


def write_snapshot(timestamp, data=REAL_WEATHER):
    main.WEATHER_SNAPSHOT_PATH.parent.mkdir(parents=True)
    main.WEATHER_SNAPSHOT_PATH.write_text(json.dumps({
        "saved_at": timestamp.isoformat(),
        "last_success_at": timestamp.isoformat(),
        "data": data,
    }))


def reset_process():
    main._weather_cache.update({
        "data": None, "expires_at": None, "stale_until": None,
        "last_success_at": None, "retry_after": None,
    })
    main._weather_persisted_snapshot_loaded = False
    main._weather_persisted_snapshot_valid = False


def test_success_persists_only_snapshot_and_timestamps(monkeypatch):
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *a, **k: Response(PAYLOAD))
    result = main.get_cabalango_weather()
    saved = json.loads(main.WEATHER_SNAPSHOT_PATH.read_text())
    assert saved.keys() == {"saved_at", "last_success_at", "data"}
    assert saved["data"] == main._weather_cache["data"]
    assert saved["data"]["temperature"] == result["temperature"] == 22
    assert "is_stale" not in saved["data"]


def test_failed_fetch_never_overwrites_previous_snapshot(monkeypatch):
    write_snapshot(NOW - timedelta(hours=7))
    before = main.WEATHER_SNAPSHOT_PATH.read_bytes()
    fail_requests(monkeypatch)
    assert main.get_cabalango_weather() == FALLBACK
    assert main.WEATHER_SNAPSHOT_PATH.read_bytes() == before


def test_new_process_loads_fresh_snapshot_without_request(monkeypatch):
    write_snapshot(NOW - timedelta(minutes=10))
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *a, **k: pytest.fail("must not fetch"))
    result = main.get_cabalango_weather()
    assert result["available"] is True
    assert result["is_stale"] is False
    assert main._weather_cache["expires_at"] == NOW + timedelta(minutes=15)


@pytest.mark.parametrize("age", [timedelta(minutes=30), timedelta(hours=5, minutes=59)])
def test_recent_expired_snapshot_is_stale_on_fetch_failure(monkeypatch, age):
    timestamp = NOW - age
    write_snapshot(timestamp)
    fail_requests(monkeypatch)
    result = main.get_cabalango_weather()
    assert result["available"] is True
    assert result["is_stale"] is True
    assert main._weather_cache["stale_until"] == timestamp + timedelta(hours=6)


def test_snapshot_older_than_six_hours_is_ignored(monkeypatch):
    write_snapshot(NOW - timedelta(hours=6, seconds=1))
    fail_requests(monkeypatch)
    assert main.get_cabalango_weather() == FALLBACK


@pytest.mark.parametrize("contents", ["{broken", "", json.dumps({"last_success_at": "not-a-date", "data": REAL_WEATHER}), json.dumps({"last_success_at": NOW.isoformat(), "data": {"available": False}})])
def test_invalid_snapshot_does_not_break_request(monkeypatch, contents):
    main.WEATHER_SNAPSHOT_PATH.parent.mkdir(parents=True)
    main.WEATHER_SNAPSHOT_PATH.write_text(contents)
    fail_requests(monkeypatch)
    assert main.get_cabalango_weather() == FALLBACK


def test_failed_force_refresh_preserves_disk_and_loaded_weather(monkeypatch):
    write_snapshot(NOW - timedelta(minutes=10))
    before = main.WEATHER_SNAPSHOT_PATH.read_bytes()
    fail_requests(monkeypatch)
    result = main.get_cabalango_weather(force_refresh=True)
    assert result["temperature"] == 19
    assert result["is_stale"] is False
    assert main.WEATHER_SNAPSHOT_PATH.read_bytes() == before


def test_new_success_atomically_replaces_old_snapshot(monkeypatch):
    write_snapshot(NOW - timedelta(hours=1))
    replacements = []
    real_replace = main.os.replace
    monkeypatch.setattr(main.os, "replace", lambda source, target: (replacements.append((source, target)), real_replace(source, target))[1])
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *a, **k: Response(PAYLOAD))
    main.get_cabalango_weather(force_refresh=True)
    saved = json.loads(main.WEATHER_SNAPSHOT_PATH.read_text())
    assert saved["data"]["temperature"] == 22
    assert len(replacements) == 1
    source, target = replacements[0]
    assert str(source).endswith(".tmp")
    assert target == main.WEATHER_SNAPSHOT_PATH


def test_snapshot_load_is_attempted_only_once(monkeypatch):
    calls = 0
    original = main.Path.read_text
    def counted(path, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(path, *args, **kwargs)
    write_snapshot(NOW - timedelta(minutes=5))
    monkeypatch.setattr(main.Path, "read_text", counted)
    main.get_cabalango_weather()
    main.get_cabalango_weather()
    assert calls == 1
