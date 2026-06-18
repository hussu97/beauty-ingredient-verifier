import pytest

from app import cli


@pytest.mark.parametrize(
    ("entrypoint_name", "command_name"),
    [
        ("import_open_beauty_facts_entry", "import-open-beauty-facts"),
        ("import_ewg_skin_deep_entry", "import-ewg-skin-deep"),
        ("scrape_ewg_skin_deep_entry", "scrape-ewg-skin-deep"),
    ],
)
def test_single_command_entrypoints_prepend_typer_command(monkeypatch, entrypoint_name, command_name):
    captured = {}

    def fake_app(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli, "app", fake_app)
    monkeypatch.setattr(cli.sys, "argv", [command_name, "--limit", "1"])

    getattr(cli, entrypoint_name)()

    assert captured["args"] == [command_name, "--limit", "1"]
    assert captured["prog_name"] == command_name
