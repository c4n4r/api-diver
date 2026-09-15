from __future__ import annotations

from api_diver.discovery import discover_specs
from api_diver.fetcher import FetchedContent

from conftest import (
    AGENCY_TANKS_SPEC,
    ARTICLES_SPEC,
    SWASHBUCKLE_HTML,
)

PAGE = "https://vnext.sosoxygene.com/api-stock/swagger/index.html"


def test_swashbuckle_json_parse_blob():
    result = discover_specs(SWASHBUCKLE_HTML, PAGE)
    assert [s.label for s in result.specs] == ["Agency Tanks", "Articles"]
    assert result.specs[0].url == "https://vnext.sosoxygene.com/api-stock/swagger/AgencyTanks/swagger.json"


def test_unquoted_js_urls():
    html = "<script>SwaggerUIBundle({urls: [{url: '/docs/a.json', name: 'A'}, {url: '/docs/b.json', name: 'B'}]})</script>"
    result = discover_specs(html, "https://x.io/ui/")
    assert len(result.specs) == 2
    assert result.specs[0].url == "https://x.io/docs/a.json"
    assert result.specs[0].label == "A"


def test_single_url_quoted():
    html = '<script>SwaggerUIBundle({url: "/swagger/v1/swagger.json", dom_id: "#ui"})</script>'
    result = discover_specs(html, "https://x.io/swagger/")
    assert len(result.specs) == 1
    assert result.specs[0].url == "https://x.io/swagger/v1/swagger.json"


def test_data_spec_url():
    html = '<div data-spec-url="../openapi.json"></div>'
    result = discover_specs(html, "https://x.io/docs/")
    assert len(result.specs) == 1
    assert result.specs[0].url == "https://x.io/openapi.json"


def test_config_url_fetch():
    html = '<script>SwaggerUIBundle({configUrl: "/swagger/swagger-config.json"})</script>'
    config = {"urls": [{"url": "/specs/one.json", "name": "One"}]}

    def fetch(url):
        return FetchedContent(url=url, kind="spec", data=config)

    result = discover_specs(html, "https://x.io/", fetch_fn=fetch)
    assert len(result.specs) == 1
    assert result.specs[0].url == "https://x.io/specs/one.json"
    assert result.specs[0].label == "One"


def test_fallback_sibling_swagger_json():
    def fetch(url):
        if url.endswith("swagger.json"):
            return FetchedContent(url=url, kind="spec", data=AGENCY_TANKS_SPEC)
        raise AssertionError(f"fetch inattendu : {url}")

    # page vierge sans config -> fallback sur les chemins courants
    result = discover_specs("<html><body>rien</body></html>", "https://x.io/swagger/", fetch_fn=fetch)
    assert len(result.specs) == 1
    assert result.specs[0].url == "https://x.io/swagger/swagger.json"


def test_no_discovery_reports_notes():
    result = discover_specs("<html><body>rien</body></html>", "https://x.io/", fetch_fn=None)
    assert result.specs == []
    assert result.notes


def test_external_script_config():
    """Pattern du dist swagger-ui : config JSON.parse dans un index.js externe."""
    html = """<html><head><title>Swagger UI</title>
<link rel="stylesheet" href="./swagger-ui.css"></head>
<body><div id="swagger-ui"></div>
<script src="./swagger-ui-bundle.js"></script>
<script src="./swagger-ui-standalone-preset.js"></script>
<script src="index.js"></script>
</body></html>"""
    index_js = (
        "window.onload = function () {\n"
        "  var configObject = JSON.parse('{\"urls\":[{\"url\":\"AgencyTanks/swagger.json\","
        "\"name\":\"Agency Tanks Domain\"},{\"url\":\"Articles/swagger.json\",\"name\":\"Articles Domain\"}],"
        "\"dom_id\":\"#swagger-ui\"}');\n"
        "  const ui = SwaggerUIBundle(configObject);\n}"
    )

    def fetch(url):
        assert url == "https://x.io/swagger/index.js", f"fetch inattendu : {url}"
        return FetchedContent(url=url, kind="text", data=index_js)

    result = discover_specs(html, "https://x.io/swagger/index.html", fetch_fn=fetch)
    assert [s.label for s in result.specs] == ["Agency Tanks Domain", "Articles Domain"]
    assert result.specs[0].url == "https://x.io/swagger/AgencyTanks/swagger.json"
    assert any("script externe" in n for n in result.notes)


def test_fetch_specs_are_valid_documents():
    # sanity : les specs fixtures ressemblent bien à des swaggers
    assert "swagger" in AGENCY_TANKS_SPEC
    assert "openapi" in ARTICLES_SPEC
