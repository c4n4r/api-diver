from __future__ import annotations

import pytest
from typer.testing import CliRunner

from api_diver.cli import app, _TARGETS
from api_diver.crawler import CrawlResult
from api_diver.fetcher import FetchedContent
from api_diver import crawler as crawler_module

from conftest import AGENCY_TANKS_SPEC, ARTICLES_SPEC, SWASHBUCKLE_HTML, V2_DOC, V3_DOC

runner = CliRunner()
PAGE = "https://vnext.sosoxygene.com/api-stock/swagger/index.html"


@pytest.fixture
def kb(tmp_path, monkeypatch):
    """Workspace initialisé + crawl factice (sans réseau)."""

    def fake_crawl(source_url, headers=None, name=None, fetch_fn=None, on_progress=None):
        def fetch(url):
            if url == PAGE:
                return FetchedContent(url=url, kind="html", data=SWASHBUCKLE_HTML)
            data = {
                "https://vnext.sosoxygene.com/api-stock/swagger/AgencyTanks/swagger.json": AGENCY_TANKS_SPEC,
                "https://vnext.sosoxygene.com/api-stock/swagger/Articles/swagger.json": ARTICLES_SPEC,
            }.get(url)
            if data is None:
                raise AssertionError(f"fetch inattendu : {url}")
            return FetchedContent(url=url, kind="spec", data=data)

        return crawler_module.crawl_source(source_url, headers=headers, name=name, fetch_fn=fetch)

    monkeypatch.setattr("api_diver.cli.crawl_source", fake_crawl)
    result = runner.invoke(app, ["init", str(tmp_path / "kb")])
    assert result.exit_code == 0, result.output
    return tmp_path / "kb"


def test_init_creates_workspace(tmp_path):
    result = runner.invoke(app, ["init", str(tmp_path / "ws")])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "ws" / "apidiver.json").is_file()


def test_add_and_list(kb):
    result = runner.invoke(app, ["add", PAGE, "--workspace", str(kb)])
    assert result.exit_code == 0, result.output
    assert "Agency Tanks" in result.output

    result = runner.invoke(app, ["list", "--workspace", str(kb)])
    assert result.exit_code == 0, result.output
    assert "vnext-api-stock" in result.output


def test_add_duplicate_refused(kb):
    runner.invoke(app, ["add", PAGE, "--workspace", str(kb)])
    result = runner.invoke(app, ["add", PAGE, "--workspace", str(kb)])
    assert result.exit_code != 0


def test_update_diff(kb):
    runner.invoke(app, ["add", PAGE, "--workspace", str(kb)])
    result = runner.invoke(app, ["update", "vnext-api-stock", "--workspace", str(kb)])
    assert result.exit_code == 0, result.output
    # rien n'a changé côté fixtures -> aucun changement signalé ou aucune ligne diff
    result = runner.invoke(app, ["diff", "vnext-api-stock", "--workspace", str(kb)])
    assert result.exit_code == 0, result.output


def test_update_skill_installs_to_detected_agents(kb, monkeypatch):
    monkeypatch.chdir(kb)
    runner.invoke(app, ["add", PAGE])
    (kb / ".claude").mkdir()
    (kb / ".agents").mkdir()
    result = runner.invoke(app, ["update", "--skill"])
    assert result.exit_code == 0, result.output
    assert "installé" in result.output
    assert (kb / ".claude" / "skills" / "api-diver" / "SKILL.md").is_file()
    assert (kb / ".agents" / "skills" / "api-diver" / "SKILL.md").is_file()
    # .agents et .claude détectés, mais pas .opencode (absent du projet)
    assert not (kb / ".opencode").exists()


def test_update_skill_without_agents_warns(kb, monkeypatch):
    monkeypatch.chdir(kb)
    runner.invoke(app, ["add", PAGE])
    result = runner.invoke(app, ["update", "--skill"])
    assert result.exit_code == 0, result.output
    assert "aucun agent détecté" in result.output
    # rien n'est généré ni installé sans cible
    assert not (kb / "api-diver").exists()


def test_update_skill_copilot_marker_anchored_to_workspace(kb, monkeypatch):
    runner.invoke(app, ["add", PAGE, "--workspace", str(kb)])
    gh = kb / ".github"
    gh.mkdir()
    (gh / "copilot-instructions.md").write_text("instructions")
    # lancé depuis un sous-dossier : détection et installation restent ancrées au workspace
    sub = kb / "sous-dossier"
    sub.mkdir()
    monkeypatch.chdir(sub)
    result = runner.invoke(app, ["update", "--skill"])
    assert result.exit_code == 0, result.output
    assert (gh / "skills" / "api-diver" / "SKILL.md").is_file()
    assert (kb / "api-diver" / "SKILL.md").is_file()
    assert not (sub / ".github").exists()
    assert not (sub / "api-diver").exists()


def test_update_skill_renames_legacy_folders(kb, monkeypatch):
    monkeypatch.chdir(kb)
    runner.invoke(app, ["add", PAGE])
    (kb / ".claude").mkdir()
    # vieux nommage : skill généré et installé sous le nom du dossier projet (« kb »)
    legacy = kb / "kb"
    legacy.mkdir()
    (legacy / "SKILL.md").write_text("---\nname: kb\n---\n# Cartographie d'APIs\n")
    old_install = kb / ".claude" / "skills" / "kb"
    old_install.mkdir(parents=True)
    (old_install / "SKILL.md").write_text("---\nname: kb\n---\n# Cartographie d'APIs\n")

    result = runner.invoke(app, ["update", "--skill"])
    assert result.exit_code == 0, result.output
    assert "renommé" in result.output
    # l'ancien dossier est renommé (puis régénéré), l'ancienne installation supprimée
    assert not legacy.exists()
    assert not old_install.exists()
    assert (kb / "api-diver" / "SKILL.md").is_file()
    assert (kb / ".claude" / "skills" / "api-diver" / "SKILL.md").is_file()


def test_update_skill_removes_legacy_duplicate(kb, monkeypatch):
    monkeypatch.chdir(kb)
    runner.invoke(app, ["add", PAGE])
    (kb / ".agents").mkdir()
    legacy = kb / "kb"
    legacy.mkdir()
    (legacy / "SKILL.md").write_text("# Cartographie d'APIs\n")
    fresh = kb / "api-diver"  # déjà généré au nouveau nom par le passé
    fresh.mkdir()
    (fresh / "SKILL.md").write_text("# Cartographie d'APIs\n")

    result = runner.invoke(app, ["update", "--skill"])
    assert result.exit_code == 0, result.output
    # le nouveau dossier existe déjà : l'ancien n'est plus qu'un doublon à supprimer
    assert not legacy.exists()
    assert (kb / "api-diver" / "SKILL.md").is_file()


def test_update_skill_leaves_foreign_folder_alone(kb, monkeypatch):
    monkeypatch.chdir(kb)
    runner.invoke(app, ["add", PAGE])
    (kb / ".agents").mkdir()
    # un dossier homonyme qui n'est pas un skill api-diver ne doit pas être touché
    foreign = kb / "kb"
    foreign.mkdir()
    (foreign / "SKILL.md").write_text("# Un skill d'un autre outil\n")

    result = runner.invoke(app, ["update", "--skill"])
    assert result.exit_code == 0, result.output
    assert (foreign / "SKILL.md").is_file()
    assert (kb / "api-diver" / "SKILL.md").is_file()


def test_info(kb):
    runner.invoke(app, ["add", PAGE, "--workspace", str(kb)])
    result = runner.invoke(app, ["info", "vnext-api-stock", "--workspace", str(kb)])
    assert result.exit_code == 0, result.output
    assert PAGE in result.output


def test_build_and_install(kb, tmp_path, monkeypatch):
    monkeypatch.chdir(kb)
    runner.invoke(app, ["add", PAGE])
    result = runner.invoke(app, ["build", "--install"])
    assert result.exit_code == 0, result.output

    # généré dans ./api-diver (nom fixe, indépendant du dossier projet)
    assert (kb / "api-diver" / "SKILL.md").is_file()
    installed = kb / ".agents" / "skills" / "api-diver"
    assert (installed / "SKILL.md").is_file()
    assert (installed / "apis" / "vnext-api-stock" / "routes" / "_index.md").is_file()
    # le nom du dossier = frontmatter name
    front = (installed / "SKILL.md").read_text().split("---")[1]
    assert "name: api-diver" in front


@pytest.mark.parametrize("target", sorted(_TARGETS))
def test_build_install_per_target(kb, monkeypatch, target):
    monkeypatch.chdir(kb)
    runner.invoke(app, ["add", PAGE])
    result = runner.invoke(app, ["build", "--target", target, "--install"])
    assert result.exit_code == 0, result.output

    installed = kb / _TARGETS[target][0] / "api-diver"
    assert (installed / "SKILL.md").is_file()


def test_build_install_cleans_legacy_folders(kb, monkeypatch):
    monkeypatch.chdir(kb)
    runner.invoke(app, ["add", PAGE])
    legacy = kb / "kb"
    legacy.mkdir()
    (legacy / "SKILL.md").write_text("---\nname: kb\n---\n# Cartographie d'APIs\n")
    old_install = kb / ".agents" / "skills" / "kb"
    old_install.mkdir(parents=True)
    (old_install / "SKILL.md").write_text("---\nname: kb\n---\n# Cartographie d'APIs\n")

    result = runner.invoke(app, ["build", "--install"])
    assert result.exit_code == 0, result.output
    # l'ancien dossier est renommé puis régénéré, l'ancienne installation supprimée
    assert not legacy.exists()
    assert not old_install.exists()
    assert (kb / "api-diver" / "SKILL.md").is_file()
    assert (kb / ".agents" / "skills" / "api-diver" / "SKILL.md").is_file()


def test_build_install_global_cleans_legacy(kb, monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    old_global = home / ".agents" / "skills" / "kb"
    old_global.mkdir(parents=True)
    (old_global / "SKILL.md").write_text("---\nname: kb\n---\n# Cartographie d'APIs\n")
    monkeypatch.chdir(kb)
    runner.invoke(app, ["add", PAGE])

    result = runner.invoke(app, ["build", "--install", "--global"])
    assert result.exit_code == 0, result.output
    assert not old_global.exists()
    assert (home / ".agents" / "skills" / "api-diver" / "SKILL.md").is_file()


def test_remove(kb):
    runner.invoke(app, ["add", PAGE, "--workspace", str(kb)])
    result = runner.invoke(app, ["remove", "vnext-api-stock", "--force", "--workspace", str(kb)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["list", "--workspace", str(kb)])
    assert "vnext-api-stock" not in result.output
