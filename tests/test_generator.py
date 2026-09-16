from __future__ import annotations

import re

import pytest

from api_diver.crawler import crawl_source
from api_diver.errors import GeneratorError
from api_diver.fetcher import FetchedContent
from api_diver.generator.curl import curl_for_route
from api_diver.generator.skill import generate_skill
from api_diver.generator.util import example_from_schema, flatten_schema

from conftest import AGENCY_TANKS_SPEC, ARTICLES_SPEC, SWASHBUCKLE_HTML, V2_DOC, V3_DOC

PAGE = "https://vnext.sosoxygene.com/api-stock/swagger/index.html"
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _crawl_v3():
    return crawl_source(
        "https://api.example.com/openapi.json",
        name="stock",
        fetch_fn=lambda url: FetchedContent(url=url, kind="spec", data=V3_DOC),
    ).spec


def _crawl_v2():
    return crawl_source(
        "https://petstore.example.com/v2/swagger.json",
        name="petstore",
        fetch_fn=lambda url: FetchedContent(url=url, kind="spec", data=V2_DOC),
    ).spec


def _crawl_merged():
    def fetch(url):
        if url == PAGE:
            return FetchedContent(url=url, kind="html", data=SWASHBUCKLE_HTML)
        data = {
            "https://vnext.sosoxygene.com/api-stock/swagger/AgencyTanks/swagger.json": AGENCY_TANKS_SPEC,
            "https://vnext.sosoxygene.com/api-stock/swagger/Articles/swagger.json": ARTICLES_SPEC,
        }.get(url)
        return FetchedContent(url=url, kind="spec", data=data)

    return crawl_source(PAGE, fetch_fn=fetch).spec


def test_flatten_and_example():
    spec = _crawl_v3()
    post = next(r for r in spec.routes if r.method == "post")
    schema = post.request_body.content_types["application/json"]
    rows = flatten_schema(schema)
    paths = [p for p, _, _ in rows]
    assert "name" in paths
    assert "address.city" in paths
    assert "address.zip" in paths
    example = example_from_schema(schema)
    assert example["name"] == "string"
    assert example["address"]["city"] == "string"


def test_required_flags_rendered(tmp_path):
    out = tmp_path / "mon-skill"
    generate_skill([_crawl_v3()], "mon-skill", out)
    customers = (out / "apis" / "stock" / "routes" / "customers.md").read_text()
    post_section = customers.partition("### POST `/customers`")[2].partition("###")[0]
    # CustomerInput déclare `name` comme requis
    assert "| `name` | string | oui |" in post_section
    assert "| `address` | Address | non |" in post_section


def test_response_schema_rendered(tmp_path):
    out = tmp_path / "mon-skill"
    generate_skill([_crawl_v3()], "mon-skill", out)
    customers = (out / "apis" / "stock" / "routes" / "customers.md").read_text()
    get_section = customers.partition("### GET `/customers`")[2].partition("###")[0]
    assert "**Réponse 200** (application/json) — schéma : `CustomerList`" in get_section
    assert "| `items` | array<Customer> | non |" in get_section
    assert "| `items[].id` | string | oui |" in get_section
    assert "| `items[].name` | string | oui |" in get_section
    assert "Exemple de réponse :" in get_section
    assert '"items"' in get_section
    # le tableau résumé reste, avec le nom de schéma
    assert "| 200 | OK | application/json : `CustomerList` |" in get_section


def test_response_schema_v2_top_level_array(tmp_path):
    out = tmp_path / "mon-skill"
    generate_skill([_crawl_v2()], "mon-skill", out)
    pets = (out / "apis" / "petstore" / "routes" / "pets.md").read_text()
    get_section = pets.partition("### GET `/pets`")[2].partition("###")[0]
    assert "**Réponse 200** (application/json) — schéma : `array<Pet>`" in get_section
    assert "| `[].id` | integer | oui |" in get_section
    assert "| `[].name` | string | oui |" in get_section
    assert "application/json : `array<Pet>`" in get_section
    assert "Exemple de réponse :" in get_section


def test_curl_v3_post():
    spec = _crawl_v3()
    post = next(r for r in spec.routes if r.method == "post")
    curl = curl_for_route(post, spec)
    assert 'curl -X POST "https://api.example.com/v1/customers"' in curl
    assert "-H \"Authorization: Bearer $STOCK_TOKEN\"" in curl
    assert "-H \"Content-Type: application/json\"" in curl
    assert "-d " in curl
    # autres domaines notées en commentaire
    assert "# autres domaines possibles : https://eu.api.example.com/v1" in curl


def test_curl_v3_get_with_query():
    spec = _crawl_v3()
    get = spec.routes[0]
    curl = curl_for_route(get, spec)
    assert "-H \"X-Api-Key: $STOCK_API_KEY\"" in curl


def test_curl_path_params():
    spec = _crawl_v3()
    delete = next(r for r in spec.routes if r.method == "delete")
    curl = curl_for_route(delete, spec)
    assert '"https://admin.example.com/customers/$STOCK_ID"' in curl


def test_curl_v2_form():
    spec = _crawl_v2()
    upload = next(r for r in spec.routes if "upload" in r.path)
    curl = curl_for_route(upload, spec)
    assert "-d" in curl and "petId=$PETSTORE_PETID" in curl


def test_skill_structure(tmp_path):
    spec = _crawl_merged()
    out = tmp_path / "mon-skill"
    created = generate_skill([spec], "mon-skill", out)

    skill_md = out / "SKILL.md"
    assert skill_md.is_file()
    content = skill_md.read_text()
    front = content.split("---")[1]
    assert "name: mon-skill" in front
    assert "description:" in front
    assert "Cartographie de 1 API(s) : vnext-api-stock" in content
    assert "vnext-api-stock" in content

    api_dir = out / "apis" / "vnext-api-stock"
    assert (api_dir / "overview.md").is_file()
    routes_dir = api_dir / "routes"
    assert (routes_dir / "_index.md").is_file()
    # un fichier par groupe découvert
    assert (routes_dir / "agency-tanks.md").is_file()
    assert (routes_dir / "articles.md").is_file()

    index = (routes_dir / "_index.md").read_text()
    assert "GET" in index and "/api/tanks" in index and "/api/articles" in index

    overview = (api_dir / "overview.md").read_text()
    assert "Agency Tanks" in overview
    assert "https://vnext.sosoxygene.com/api-stock" in overview

    assert all(NAME_RE.fullmatch(p.name) or "." in p.name for p in created)


def test_skill_frontmatter_constraints(tmp_path):
    spec = _crawl_v3()
    with pytest.raises(GeneratorError):
        generate_skill([spec], "Nom Invalide!", tmp_path / "x")


def test_skill_refuses_foreign_dir(tmp_path):
    target = tmp_path / "existant"
    target.mkdir()
    (target / "mes-fichiers.txt").write_text("données perso")
    spec = _crawl_v3()
    with pytest.raises(GeneratorError):
        generate_skill([spec], "mon-skill", target)


def test_skill_rebuild_replaces(tmp_path):
    spec = _crawl_v3()
    out = tmp_path / "mon-skill"
    generate_skill([spec], "mon-skill", out)
    (out / "apis" / "stock" / "routes" / "anciennetag.md").write_text("vieux")
    generate_skill([spec], "mon-skill", out)
    assert not (out / "apis" / "stock" / "routes" / "anciennetag.md").exists()
    assert (out / "SKILL.md").is_file()


def test_multi_api_skill(tmp_path):
    out = tmp_path / "kb"
    generate_skill([_crawl_v3(), _crawl_v2()], "kb", out)
    assert (out / "apis" / "stock" / "overview.md").is_file()
    assert (out / "apis" / "petstore" / "overview.md").is_file()
    content = (out / "SKILL.md").read_text()
    assert "petstore" in content and "stock" in content
