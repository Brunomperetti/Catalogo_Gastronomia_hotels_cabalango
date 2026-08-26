import json
from datetime import datetime, timedelta, timezone

import pytest

import app.main as main


NOW = datetime(2026, 8, 26, 12, tzinfo=timezone.utc)
FALLBACK = {"available": False, "message": "Clima no disponible por el momento."}
PAYLOAD = {
    "current": {
        "temperature_2m": 22,
        "apparent_temperature": 21,
        "weather_code": 1,
        "wind_speed_10m": 8,
    },
    "daily": {
        "time": [f"2026-08-{day:02d}" for day in range(26, 33)],
        "weather_code": [1] * 7,
        "temperature_2m_max": [25] * 7,
        "temperature_2m_min": [12] * 7,
        "precipitation_probability_max": [10] * 7,
    },
}


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps(PAYLOAD).encode()


@pytest.fixture(autouse=True)
def reset_weather_cache(monkeypatch):
    main._weather_cache.update({"expires_at": None, "data": None})
    monkeypatch.setattr(main, "utc_now", lambda: NOW)


def test_success_is_cached_for_25_minutes(monkeypatch):
    calls = []
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *args, **kwargs: calls.append(kwargs) or Response())

    weather = main.get_cabalango_weather()

    assert weather["temperature"] == 22
    assert calls == [{"timeout": 5}]
    assert main._weather_cache["data"] == weather
    assert main._weather_cache["expires_at"] == NOW + timedelta(minutes=25)


def test_second_attempt_can_recover_from_first_failure(monkeypatch):
    attempts = 0

    def flaky_request(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("temporary timeout")
        return Response()

    monkeypatch.setattr(main.urllib.request, "urlopen", flaky_request)

    assert main.get_cabalango_weather()["temperature"] == 22
    assert attempts == 2


def test_failure_does_not_return_expired_last_valid_weather(monkeypatch):
    stale = {"available": True, "temperature": 18}
    main._weather_cache.update({"data": stale, "expires_at": NOW - timedelta(seconds=1)})
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()))

    assert main.get_cabalango_weather() == FALLBACK


def test_failure_without_last_valid_weather_returns_fallback(monkeypatch):
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()))

    assert main.get_cabalango_weather() == FALLBACK


def test_fallback_is_only_cached_for_one_minute(monkeypatch):
    attempts = 0

    def failed_request(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise TimeoutError()

    monkeypatch.setattr(main.urllib.request, "urlopen", failed_request)
    assert main.get_cabalango_weather() == FALLBACK
    assert main._weather_cache["data"] == FALLBACK
    assert main._weather_cache["expires_at"] == NOW + timedelta(minutes=1)

    monkeypatch.setattr(main, "utc_now", lambda: NOW + timedelta(minutes=2))
    assert main.get_cabalango_weather() == FALLBACK
    assert attempts == 4


def test_force_refresh_ignores_valid_weather_cache(monkeypatch):
    cached = {"available": True, "temperature": 18}
    main._weather_cache.update({"data": cached, "expires_at": NOW + timedelta(minutes=20)})
    calls = []
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *args, **kwargs: calls.append(kwargs) or Response())

    weather = main.get_cabalango_weather(force_refresh=True)

    assert weather["temperature"] == 22
    assert calls == [{"timeout": 5}]
    assert main._weather_cache["data"] == weather


def test_force_refresh_ignores_cached_fallback(monkeypatch):
    main._weather_cache.update({"data": FALLBACK, "expires_at": NOW + timedelta(seconds=30)})
    calls = []
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *args, **kwargs: calls.append(kwargs) or Response())

    assert main.get_cabalango_weather(force_refresh=True)["temperature"] == 22
    assert calls == [{"timeout": 5}]


def test_failed_force_refresh_replaces_old_weather_with_fallback(monkeypatch):
    cached = {"available": True, "temperature": 18}
    main._weather_cache.update({"data": cached, "expires_at": NOW + timedelta(minutes=20)})
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()))

    assert main.get_cabalango_weather(force_refresh=True) == FALLBACK
    assert main._weather_cache["data"] == FALLBACK
