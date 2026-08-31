"""The CLI, exercised end to end."""

from datetime import date

from structura.cli import main
from structura.index import index_path


def test_lint_exits_zero_on_a_clean_workspace(workspace, capsys):
    assert main(["lint", str(workspace)]) == 0
    assert "schema clean" in capsys.readouterr().out


def test_lint_exits_one_and_reports_each_violation(workspace, capsys, write_note):
    write_note(workspace, "2-Notes/Bad.md", dtype="sandwich")
    assert main(["lint", str(workspace)]) == 1
    assert "unknown type `sandwich`" in capsys.readouterr().err


def test_scan_summarises_without_validating(workspace, capsys):
    assert main(["scan", str(workspace)]) == 0
    out = capsys.readouterr().out
    assert "5 documents · 2 tasks (1 open)" in out
    assert "5 without a uid" in out


def test_uid_is_a_dry_run_until_applied(workspace, capsys):
    assert main(["uid", str(workspace)]) == 0
    assert "Re-run with --apply" in capsys.readouterr().out

    assert main(["uid", "--apply", str(workspace)]) == 0
    assert "stamped 5" in capsys.readouterr().out

    assert main(["uid", str(workspace)]) == 0
    assert "already has a uid" in capsys.readouterr().out


def test_reindex_creates_the_index_and_reports(workspace, capsys):
    assert main(["reindex", str(workspace)]) == 0
    assert "5 added" in capsys.readouterr().out
    assert index_path(workspace).exists()


def test_reindex_is_idempotent(workspace, capsys):
    main(["reindex", str(workspace)])
    capsys.readouterr()
    assert main(["reindex", str(workspace)]) == 0
    assert "0 added · 0 updated · 0 removed · 5 unchanged" in capsys.readouterr().out


def test_rebuild_starts_from_nothing(workspace, capsys):
    main(["reindex", str(workspace)])
    capsys.readouterr()
    assert main(["reindex", "--rebuild", str(workspace)]) == 0
    assert "5 added" in capsys.readouterr().out


def test_export_writes_the_four_registers(workspace, tmp_path, capsys):
    out = tmp_path / "registers"
    assert main(["export", str(workspace), "--out", str(out), "--today", "2026-08-31"]) == 0
    written = sorted(p.name for p in out.iterdir())
    assert written == ["Assets.md", "Contacts.md", "Open Items.md", "Placeholders.md"]
    assert "date: 2026-08-31" in (out / "Assets.md").read_text()


def test_export_defaults_to_the_index_folder(workspace):
    assert main(["export", str(workspace)]) == 0
    assert (workspace / "0-Index" / "Open Items.md").exists()


def test_exported_registers_are_not_re_indexed(workspace):
    """`0-Index/` is generated output; reading it back would double-count every
    task in it."""
    main(["export", str(workspace)])
    from structura.stores.markdown import MarkdownStore

    assert all("0-Index" not in p.parts for p in MarkdownStore(workspace).paths())


def test_a_broken_schema_fails_loudly_rather_than_checking_nothing(workspace, capsys):
    (workspace / "structura.toml").write_text('[schema]\ntypes = ["note"]\nenums = 3\n')
    assert main(["lint", str(workspace)]) == 2
    assert "schema error" in capsys.readouterr().err


def test_export_uses_todays_date_by_default(workspace):
    main(["export", str(workspace)])
    assert f"date: {date.today().isoformat()}" in (workspace / "0-Index" / "Assets.md").read_text()
