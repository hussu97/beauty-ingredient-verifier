from app import cli


def test_single_command_entrypoints_prepend_typer_command(monkeypatch):
    captured = {}

    def fake_app(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli, "app", fake_app)
    monkeypatch.setattr(cli.sys, "argv", ["import-open-beauty-facts", "--limit", "1"])

    cli.import_open_beauty_facts_entry()

    assert captured["args"] == ["import-open-beauty-facts", "--limit", "1"]
    assert captured["prog_name"] == "import-open-beauty-facts"
