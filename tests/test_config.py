from datetime import time
from pathlib import Path

import pytest

from src.config import ConfigError, load_settings

REQUIRED = {"TELEGRAM_BOT_TOKEN": "123:abc", "GOOGLE_API_KEY": "key", "ADMIN_IDS": "11"}


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    monkeypatch.chdir(tmp_path)  # no .env file here
    for name in (*REQUIRED, "USER_IDS", "TIMEZONE", "REMINDER_TIMES", "LANGUAGE"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _set(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    for name, value in {**REQUIRED, **values}.items():
        monkeypatch.setenv(name, value)


def test_load_settings_parses_comma_separated_values(isolated_env: pytest.MonkeyPatch) -> None:
    _set(isolated_env, ADMIN_IDS="11, 22", USER_IDS="22,33", REMINDER_TIMES="09:30,20:00")

    settings = load_settings()

    assert settings.admin_ids == (11, 22)
    assert settings.member_ids == (11, 22, 33)
    assert settings.reminder_times == (time(9, 30), time(20, 0))
    assert settings.language == "en"
    assert settings.timezone == "Europe/Madrid"


def test_load_settings_allows_empty_user_ids(isolated_env: pytest.MonkeyPatch) -> None:
    _set(isolated_env, USER_IDS="")
    assert load_settings().user_ids == ()


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"ADMIN_IDS": ""}, "ADMIN_IDS"),
        ({"ADMIN_IDS": "abc"}, "ADMIN_IDS"),
        ({"USER_IDS": "-5"}, "USER_IDS"),
        ({"TIMEZONE": "Mars/Base"}, "TIMEZONE"),
        ({"LANGUAGE": "de"}, "LANGUAGE"),
    ],
)
def test_load_settings_with_bad_values_names_the_variable(
    isolated_env: pytest.MonkeyPatch, overrides: dict[str, str], expected: str
) -> None:
    _set(isolated_env, **overrides)

    with pytest.raises(ConfigError, match=expected):
        load_settings()


def test_load_settings_without_token_lists_missing_variables(isolated_env: pytest.MonkeyPatch) -> None:
    isolated_env.setenv("ADMIN_IDS", "1")

    with pytest.raises(ConfigError) as exc:
        load_settings()

    assert "TELEGRAM_BOT_TOKEN" in str(exc.value)
    assert "GOOGLE_API_KEY" in str(exc.value)
    assert "123:abc" not in str(exc.value)
