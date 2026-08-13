from __future__ import annotations

import pytest

from entity_map import cli


def test_parser_defaults_and_flags() -> None:
    args = cli.build_parser().parse_args(["serve"])
    assert args.port == 8501
    assert args.no_browser is False
    args = cli.build_parser().parse_args(["serve", "--port", "9000", "--no-browser"])
    assert args.port == 9000
    assert args.no_browser is True


def test_cli_starts_local_only_fastapi_server(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app: str, **options: object) -> None:
        captured["app"] = app
        captured.update(options)

    monkeypatch.setattr("uvicorn.run", fake_run)
    assert cli.main(["serve", "--port", "8765", "--no-browser"]) == 0
    assert captured == {
        "app": "entity_map.app:app",
        "host": "127.0.0.1",
        "port": 8765,
        "log_level": "info",
    }


def test_cli_rejects_invalid_port() -> None:
    with pytest.raises(SystemExit, match="between 1 and 65535"):
        cli.main(["serve", "--port", "70000"])
