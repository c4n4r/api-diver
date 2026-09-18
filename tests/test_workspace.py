from __future__ import annotations

import json

import pytest

from api_diver.crawler import crawl_source
from api_diver.errors import WorkspaceError
from api_diver.fetcher import FetchedContent
from api_diver.model import ApiSpec, Route, diff_routes
from api_diver.workspace import Workspace

from conftest import AGENCY_TANKS_SPEC, ARTICLES_SPEC, SWASHBUCKLE_HTML, V2_DOC, V3_DOC

PAGE = "https://vnext.sosoxygene.com/api-stock/swagger/index.html"


def _spec(name="stock", routes=None):
    return ApiSpec(
        name=name,
        title=name,
        version="1.0",
        openapi_version="3.0.0",
        source_url="https://x/" + name,
        routes=routes or [],
    )


def _route(path, method="get", tags=None):
    from api_diver.model import Parameter

    return Route(
        path=path,
        method=method,
        tags=tags or [],
        parameters=[Parameter(name="id", location="path", required=True)],
    )


def test_init_and_store(tmp_path):
    ws = Workspace.create(tmp_path / "kb")
    assert ws.skill_name == "api-diver"
    diff = ws.store_api(
        _spec(routes=[_route("/a"), _route("/b")]),
        spec_urls=[{"url": "https://x/stock", "label": ""}],
        auth_headers={"Authorization": "env:MY_TOKEN"},
        inline_headers=[],
        raw_docs=[("https://x/stock", V3_DOC)],
    )
    assert diff.added == ["GET /a", "GET /b"]
    assert ws.has("stock")
    assert ws.sources["stock"]["auth_headers"] == {"Authorization": "env:MY_TOKEN"}
    assert (tmp_path / "kb" / "specs" / "stock" / "normalized.json").is_file()
    # le doc brut est caché
    raw_dir = tmp_path / "kb" / "specs" / "stock" / "raw"
    assert list(raw_dir.glob("*.json"))

    loaded = ws.load_api("stock")
    assert [r.id for r in loaded.routes] == ["GET /a", "GET /b"]


def test_update_rotates_prev_and_diffs(tmp_path):
    ws = Workspace.create(tmp_path / "kb")
    ws.store_api(
        _spec(routes=[_route("/a"), _route("/b")]),
        spec_urls=[], auth_headers={}, inline_headers=[], raw_docs=[],
    )
    diff = ws.store_api(
        _spec(routes=[_route("/a"), _route("/c"), _route("/d", "post")]),
        spec_urls=[], auth_headers={}, inline_headers=[], raw_docs=[],
    )
    assert diff.added == ["GET /c", "POST /d"]
    assert diff.removed == ["GET /b"]
    assert diff.modified == []  # /a inchangée
    assert ws.load_api_prev("stock") is not None
    assert ws.sources["stock"]["route_count"] == 3


def test_diff_routes_modified():
    old = [_route("/a")]
    new = [Route(path="/a", method="get", tags=[], parameters=[])]
    diff = diff_routes(old, new)
    assert diff.modified == ["GET /a"]


def test_remove(tmp_path):
    ws = Workspace.create(tmp_path / "kb")
    ws.store_api(_spec(), spec_urls=[], auth_headers={}, inline_headers=[], raw_docs=[])
    ws.remove("stock")
    assert not ws.has("stock")
    assert not (tmp_path / "kb" / "specs" / "stock").exists()
    with pytest.raises(WorkspaceError):
        ws.require("stock")


def test_find_walks_up(tmp_path):
    Workspace.create(tmp_path / "kb")
    nested = tmp_path / "kb" / "a" / "b" / "c"
    nested.mkdir(parents=True)
    found = Workspace.find(start=nested)
    assert found.root == (tmp_path / "kb").resolve()


def test_duplicate_init_refused(tmp_path):
    Workspace.create(tmp_path / "kb")
    with pytest.raises(WorkspaceError):
        Workspace.create(tmp_path / "kb")


def test_legacy_skill_name_migrated(tmp_path):
    """Un ancien workspace (nom de skill = nom du dossier) repasse à « api-diver »."""
    ws = Workspace.create(tmp_path / "kb")
    ws.registry["skill_name"] = "kb"  # ancien défaut dérivé du dossier projet
    ws._dump()

    reloaded = Workspace(tmp_path / "kb")
    assert reloaded.skill_name == "api-diver"
    # migré aussi sur disque
    on_disk = json.loads((tmp_path / "kb" / "apidiver.json").read_text())
    assert on_disk["skill_name"] == "api-diver"


def test_custom_skill_name_preserved(tmp_path):
    """Un nom choisi explicitement n'est pas touché par la migration."""
    ws = Workspace.create(tmp_path / "kb")
    ws.set_skill_name("mon-skill")
    assert Workspace(tmp_path / "kb").skill_name == "mon-skill"


def test_crawl_to_workspace_end_to_end(tmp_path):
    """Le parcours complet : page multi-specs -> workspace -> registre complet."""

    def fetch(url):
        if url == PAGE:
            return FetchedContent(url=url, kind="html", data=SWASHBUCKLE_HTML)
        data = {
            "https://vnext.sosoxygene.com/api-stock/swagger/AgencyTanks/swagger.json": AGENCY_TANKS_SPEC,
            "https://vnext.sosoxygene.com/api-stock/swagger/Articles/swagger.json": ARTICLES_SPEC,
        }.get(url)
        if data is not None:
            return FetchedContent(url=url, kind="spec", data=data)
        raise AssertionError(f"fetch inattendu : {url}")

    ws = Workspace.create(tmp_path / "kb")
    result = crawl_source(PAGE, fetch_fn=fetch)
    ws.store_api(
        result.spec, result.spec_urls, {}, [], result.raw_docs
    )
    entry = ws.sources["vnext-api-stock"]
    assert entry["route_count"] == 2
    assert entry["groups"] == ["Agency Tanks", "Articles"]
    normalized = json.loads((tmp_path / "kb" / "specs" / "vnext-api-stock" / "normalized.json").read_text())
    assert sorted(g for g in normalized["groups"]) == ["Agency Tanks", "Articles"]


def test_v2_spec_store(tmp_path):
    ws = Workspace.create(tmp_path / "kb")
    result = crawl_source(
        "https://petstore.example.com/v2/swagger.json",
        name="petstore",
        fetch_fn=lambda url: FetchedContent(url=url, kind="spec", data=V2_DOC),
    )
    ws.store_api(result.spec, result.spec_urls, {}, [], result.raw_docs)
    entry = ws.sources["petstore"]
    assert entry["route_count"] == 4
    assert entry["domains"] == [
        "http://petstore.example.com/v2",
        "https://petstore.example.com/v2",
    ]
