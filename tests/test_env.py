import pytest

from app.env import get_env, require_env


def test_get_env_strips_leading_and_trailing_whitespace(monkeypatch):
    monkeypatch.setenv("BEISPIEL", "  wert  ")
    assert get_env("BEISPIEL") == "wert"


def test_get_env_strips_trailing_newline(monkeypatch):
    monkeypatch.setenv("BEISPIEL", "geheimer-schluessel\n")
    assert get_env("BEISPIEL") == "geheimer-schluessel"


def test_get_env_preserves_internal_whitespace(monkeypatch):
    monkeypatch.setenv("BEISPIEL", " 030 1234567 ")
    assert get_env("BEISPIEL") == "030 1234567"


def test_get_env_returns_default_when_unset(monkeypatch):
    monkeypatch.delenv("NICHT_GESETZT", raising=False)
    assert get_env("NICHT_GESETZT", "default") == "default"
    assert get_env("NICHT_GESETZT") is None


def test_require_env_returns_stripped_value(monkeypatch):
    monkeypatch.setenv("BEISPIEL", " wert \n")
    assert require_env("BEISPIEL") == "wert"


def test_require_env_raises_when_unset(monkeypatch):
    monkeypatch.delenv("NICHT_GESETZT", raising=False)
    with pytest.raises(RuntimeError, match="NICHT_GESETZT ist nicht gesetzt."):
        require_env("NICHT_GESETZT")


def test_require_env_raises_when_only_whitespace(monkeypatch):
    monkeypatch.setenv("NUR_LEERZEICHEN", "   \n")
    with pytest.raises(RuntimeError, match="NUR_LEERZEICHEN ist nicht gesetzt."):
        require_env("NUR_LEERZEICHEN")
