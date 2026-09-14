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
    def __init__(self, payload=PAYLOAD):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


@pytest.fixture(autouse=True)
def reset_weather_cache(monkeypatch):
    main._weather_cache.update({
        "data": None,
        "expires_at": None,
        "stale_until": None,
        "last_success_at": None,
        "retry_after": None,
    })
    monkeypatch.setattr(main, "utc_now", lambda: NOW)


def successful_weather(monkeypatch, payload=PAYLOAD):
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *args, **kwargs: Response(payload))
    return main.get_cabalango_weather()


def fail_requests(monkeypatch, attempts=None):
    def fail(*args, **kwargs):
        if attempts is not None:
            attempts.append(kwargs)
        raise TimeoutError("temporary timeout")

    monkeypatch.setattr(main.urllib.request, "urlopen", fail)


def seed_real_weather(*, age=timedelta(minutes=30), temperature=18):
    obtained_at = NOW - age
    forecast = [{"label": "Mañana", "min": 7, "max": 19, "rain_probability": 37, "condition": "Nublado"}]
    data = {
        "available": True,
        "temperature": temperature,
        "apparent_temperature": 16,
        "condition": "Nublado",
        "min": 7,
        "max": 19,
        "rain_probability": 37,
        "wind": 11,
        "advice": "Ideal para recorrer.",
        "forecast": forecast,
    }
    main._weather_cache.update({
        "data": data,
        "expires_at": obtained_at + main.WEATHER_FRESH_TTL,
        "stale_until": obtained_at + main.WEATHER_STALE_TTL,
        "last_success_at": obtained_at,
        "retry_after": None,
    })
    return data


def test_success_sets_fresh_and_stale_cache_metadata(monkeypatch):
    calls = []
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *args, **kwargs: calls.append(kwargs) or Response())

    weather = main.get_cabalango_weather()

    assert weather["temperature"] == 22
    assert weather["is_stale"] is False
    assert weather["last_updated_at"] == NOW
    assert weather["last_updated_label"] == "09:00"
    assert calls == [{"timeout": 5}]
    assert main._weather_cache["data"]["temperature"] == 22
    assert main._weather_cache["expires_at"] == NOW + timedelta(minutes=25)
    assert main._weather_cache["stale_until"] == NOW + timedelta(hours=6)
    assert main._weather_cache["last_success_at"] == NOW
    assert main._weather_cache["retry_after"] is None


def test_fresh_cache_does_not_request_open_meteo(monkeypatch):
    successful_weather(monkeypatch)
    calls = []
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *args, **kwargs: calls.append(1))

    weather = main.get_cabalango_weather()

    assert weather["temperature"] == 22
    assert weather["is_stale"] is False
    assert calls == []


def test_second_attempt_can_recover_from_first_failure(monkeypatch, caplog):
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
    assert "attempt 1/2 failed (TimeoutError)" in caplog.text


def test_expired_cache_failure_returns_exact_real_weather_as_stale(monkeypatch):
    cached = seed_real_weather()
    original_forecast = cached["forecast"]
    fail_requests(monkeypatch)

    weather = main.get_cabalango_weather()

    assert weather["available"] is True
    assert weather["is_stale"] is True
    assert weather["temperature"] == 18
    assert weather["forecast"] == original_forecast
    assert weather["forecast"] is original_forecast
    assert set(main._weather_cache["data"]) == set(cached)
    assert main._weather_cache["retry_after"] == NOW + timedelta(minutes=1)


def test_retry_window_returns_stale_without_new_request(monkeypatch):
    seed_real_weather()
    main._weather_cache["retry_after"] = NOW + timedelta(seconds=30)
    calls = []
    fail_requests(monkeypatch, calls)

    assert main.get_cabalango_weather()["is_stale"] is True
    assert calls == []


def test_after_retry_window_requests_again(monkeypatch):
    seed_real_weather()
    main._weather_cache["retry_after"] = NOW - timedelta(seconds=1)
    calls = []
    fail_requests(monkeypatch, calls)

    assert main.get_cabalango_weather()["is_stale"] is True
    assert len(calls) == 2


def test_successful_retry_replaces_stale_and_resets_metadata(monkeypatch):
    seed_real_weather()
    old_success = main._weather_cache["last_success_at"]

    weather = successful_weather(monkeypatch)

    assert weather["temperature"] == 22
    assert weather["is_stale"] is False
    assert main._weather_cache["last_success_at"] == NOW > old_success
    assert main._weather_cache["stale_until"] == NOW + timedelta(hours=6)
    assert main._weather_cache["retry_after"] is None


def test_weather_at_five_hours_fifty_nine_minutes_can_be_stale(monkeypatch):
    seed_real_weather(age=timedelta(hours=5, minutes=59))
    fail_requests(monkeypatch)

    assert main.get_cabalango_weather()["temperature"] == 18
    assert main.get_cabalango_weather()["is_stale"] is True


def test_weather_older_than_six_hours_is_not_returned(monkeypatch):
    seed_real_weather(age=timedelta(hours=6, seconds=1))
    fail_requests(monkeypatch)

    assert main.get_cabalango_weather() == FALLBACK
    assert main._weather_cache["data"] == FALLBACK
    assert main._weather_cache["last_success_at"] is None


def test_failure_without_history_returns_fallback(monkeypatch):
    fail_requests(monkeypatch)
    assert main.get_cabalango_weather() == FALLBACK


def test_fallback_is_cached_for_one_minute(monkeypatch):
    attempts = []
    fail_requests(monkeypatch, attempts)
    assert main.get_cabalango_weather() == FALLBACK
    assert main._weather_cache["expires_at"] == NOW + timedelta(minutes=1)
    assert main.get_cabalango_weather() == FALLBACK
    assert len(attempts) == 2

    monkeypatch.setattr(main, "utc_now", lambda: NOW + timedelta(minutes=2))
    assert main.get_cabalango_weather() == FALLBACK
    assert len(attempts) == 4


def test_force_refresh_success_replaces_fresh_cache(monkeypatch):
    seed_real_weather(age=timedelta(minutes=5))
    weather = successful_weather(monkeypatch)

    # The helper above is a normal call, so explicitly verify forced refresh separately.
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    weather = main.get_cabalango_weather(force_refresh=True)
    assert weather["temperature"] == 22
    assert weather["is_stale"] is False


def test_failed_force_refresh_preserves_fresh_real_weather(monkeypatch):
    cached = seed_real_weather(age=timedelta(minutes=5))
    fail_requests(monkeypatch)

    weather = main.get_cabalango_weather(force_refresh=True)

    assert weather["temperature"] == cached["temperature"]
    assert weather["is_stale"] is False
    assert main._weather_cache["data"] is cached
    assert main._weather_cache["retry_after"] == NOW + timedelta(minutes=1)


def test_failed_force_refresh_preserves_valid_stale_weather(monkeypatch):
    cached = seed_real_weather(age=timedelta(minutes=30))
    fail_requests(monkeypatch)

    weather = main.get_cabalango_weather(force_refresh=True)

    assert weather["available"] is True
    assert weather["temperature"] == cached["temperature"]
    assert weather["is_stale"] is True
    assert main._weather_cache["data"] is cached


def test_failed_force_refresh_rejects_weather_older_than_six_hours(monkeypatch):
    seed_real_weather(age=timedelta(hours=7))
    fail_requests(monkeypatch)

    assert main.get_cabalango_weather(force_refresh=True) == FALLBACK


def test_force_refresh_ignores_cached_fallback(monkeypatch):
    main._weather_cache.update({"data": FALLBACK, "expires_at": NOW + timedelta(seconds=30)})
    calls = []
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda *args, **kwargs: calls.append(kwargs) or Response())

    assert main.get_cabalango_weather(force_refresh=True)["temperature"] == 22
    assert calls == [{"timeout": 5}]
