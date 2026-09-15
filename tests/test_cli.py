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

    installed = kb / ".agents" / "skills" / "kb"
    assert (installed / "SKILL.md").is_file()
    assert (installed / "apis" / "vnext-api-stock" / "routes" / "_index.md").is_file()
    # le nom du dossier = frontmatter name
    front = (installed / "SKILL.md").read_text().split("---")[1]
    assert "name: kb" in front


@pytest.mark.parametrize("target", sorted(_TARGETS))
def test_build_install_per_target(kb, monkeypatch, target):
    monkeypatch.chdir(kb)
    runner.invoke(app, ["add", PAGE])
    result = runner.invoke(app, ["build", "--target", target, "--install"])
    assert result.exit_code == 0, result.output

    installed = kb / _TARGETS[target][0] / "kb"
    assert (installed / "SKILL.md").is_file()


def test_remove(kb):
    runner.invoke(app, ["add", PAGE, "--workspace", str(kb)])
    result = runner.invoke(app, ["remove", "vnext-api-stock", "--force", "--workspace", str(kb)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["list", "--workspace", str(kb)])
    assert "vnext-api-stock" not in result.output
