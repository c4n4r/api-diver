from __future__ import annotations

import json

from api_diver.crawler import crawl_source, derive_name_from_url
from api_diver.fetcher import FetchedContent

from conftest import AGENCY_TANKS_SPEC, ARTICLES_SPEC, SWASHBUCKLE_HTML, V3_DOC

PAGE = "https://vnext.sosoxygene.com/api-stock/swagger/index.html"


def make_fetcher(pages: dict, specs: dict):
    def fetch(url):
        if url in pages:
            return FetchedContent(url=url, kind="html", data=pages[url])
        if url in specs:
            return FetchedContent(url=url, kind="spec", data=specs[url])
        raise AssertionError(f"fetch inattendu : {url}")

    return fetch


def test_crawl_direct_spec():
    fetch = make_fetcher({}, {"https://x.io/openapi.json": V3_DOC})
    result = crawl_source("https://x.io/openapi.json", name="stock", fetch_fn=fetch)
    assert result.spec.name == "stock"
    assert len(result.spec.routes) == 3
    assert len(result.spec.groups) == 0


def test_crawl_swashbuckle_multi_specs_merge():
    fetch = make_fetcher(
        {PAGE: SWASHBUCKLE_HTML},
        {
            "https://vnext.sosoxygene.com/api-stock/swagger/AgencyTanks/swagger.json": AGENCY_TANKS_SPEC,
            "https://vnext.sosoxygene.com/api-stock/swagger/Articles/swagger.json": ARTICLES_SPEC,
        },
    )
    result = crawl_source(PAGE, fetch_fn=fetch)

    spec = result.spec
    assert spec.groups == ["Agency Tanks", "Articles"]
    assert sorted(r.id for r in spec.routes) == ["GET /api/articles", "GET /api/tanks"]
    # chaque route porte son groupe en premier tag
    by_id = {r.id: r for r in spec.routes}
    assert by_id["GET /api/tanks"].tags[0] == "Agency Tanks"
    assert by_id["GET /api/articles"].tags[0] == "Articles"
    # domaines unionnés et dédupliqués (même base URL via 2 formes différentes)
    assert [d.url for d in spec.domains] == ["https://vnext.sosoxygene.com/api-stock"]
    assert len(result.spec_urls) == 2
    assert len(result.raw_docs) == 2


def test_derive_name_from_url():
    assert derive_name_from_url(PAGE) == "vnext-api-stock"
    assert derive_name_from_url("https://petstore.io/v2/swagger.json") == "petstore"


def test_roundtrip_normalized(tmp_path):
    fetch = make_fetcher({}, {"https://x.io/openapi.json": V3_DOC})
    result = crawl_source("https://x.io/openapi.json", name="stock", fetch_fn=fetch)
    dumped = json.dumps(result.spec.to_dict(), ensure_ascii=False)
    from api_diver.model import ApiSpec

    restored = ApiSpec.from_dict(json.loads(dumped))
    assert restored.name == "stock"
    assert [r.id for r in restored.routes] == [r.id for r in result.spec.routes]
    assert restored.domains[1].url == "https://eu.api.example.com/v1"
