import pytest

from app import cli


@pytest.mark.parametrize(
    ("entrypoint_name", "command_name"),
    [
        ("import_open_beauty_facts_entry", "import-open-beauty-facts"),
        ("import_ewg_wayback_entry", "import-ewg-wayback"),
        ("backfill_ewg_wayback_images_entry", "backfill-ewg-wayback-images"),
        ("sync_local_to_prod_entry", "sync-local-to-prod"),
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
