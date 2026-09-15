from __future__ import annotations

from api_diver.errors import SpecError
from api_diver.parser import parse_document
from api_diver.parser.resolver import resolve_document


def test_resolver_inlines_local_refs(v3_doc):
    resolved, warnings = resolve_document(v3_doc)
    schema = resolved["components"]["schemas"]["Customer"]
    # Address est inlinée (plus de $ref local)
    assert "$ref" not in schema["properties"]["address"]
    assert schema["properties"]["address"]["properties"]["city"]["type"] == "string"
    # x-ref-name est posé aux sites d'usage des références
    usage = resolved["paths"]["/customers"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert usage["x-ref-name"] == "CustomerInput"
    assert usage["properties"]["address"]["x-ref-name"] == "Address"
    assert warnings == []


def test_resolver_cycle():
    doc = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {},
        "components": {
            "schemas": {
                "Node": {
                    "type": "object",
                    "properties": {"child": {"$ref": "#/components/schemas/Node"}},
                }
            }
        },
    }
    resolved, _ = resolve_document(doc)
    inner = resolved["components"]["schemas"]["Node"]["properties"]["child"]
    assert inner["properties"]["child"] == {"x-cycle": "Node"}


def test_resolver_external_ref_warns():
    doc = {
        "paths": {
            "/a": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {"application/json": {"schema": {"$ref": "https://ailleurs.io/x.json"}}},
                        }
                    }
                }
            }
        }
    }
    resolved, warnings = resolve_document(doc)
    assert any("externe" in w for w in warnings)


def test_parse_v3_domains_and_variables(v3_doc):
    spec = parse_document(v3_doc, name="stock", source_url="https://api.example.com/openapi.json")
    urls = [d.url for d in spec.domains]
    assert urls == ["https://api.example.com/v1", "https://eu.api.example.com/v1"]
    assert spec.openapi_version == "3.0.3"
    assert spec.title == "Stock API"


def test_parse_v3_routes(v3_doc):
    spec = parse_document(v3_doc, name="stock", source_url="https://api.example.com/openapi.json")
    ids = [r.id for r in spec.routes]
    assert ids == ["GET /customers", "POST /customers", "DELETE /customers/{id}"]

    post = spec.routes[1]
    assert post.tags == ["customers"]
    assert post.request_body is not None
    json_schema = post.request_body.content_types["application/json"]
    # $ref CustomerInput résolu et inliné
    assert json_schema.properties["name"].type == "string"
    assert json_schema.properties["address"].properties["city"].type == "string"
    assert [r.status for r in post.responses] == ["201", "422"]
    assert post.security == [["bearerAuth"]]

    get = spec.routes[0]
    params = {p.name: p for p in get.parameters}
    assert params["limit"].type == "integer"
    assert params["limit"].default == 20
    assert params["X-Request-Id"].location == "header"
    assert get.security == [["apiKey"]]  # security root héritée

    delete = spec.routes[2]
    assert delete.domain_urls == ["https://admin.example.com"]
    path_param = next(p for p in delete.parameters if p.location == "path")
    assert path_param.name == "id" and path_param.required


def test_parse_v3_group_label(v3_doc):
    spec = parse_document(v3_doc, name="stock", source_url="https://x", group_label="Articles")
    assert spec.routes[0].tags[0] == "Articles"
    assert spec.groups == ["Articles"]


def test_parse_v2(v2_doc):
    spec = parse_document(v2_doc, name="petstore", source_url="https://petstore.example.com/v2/swagger.json")
    assert [d.url for d in spec.domains] == [
        "http://petstore.example.com/v2",
        "https://petstore.example.com/v2",
    ]
    ids = [r.id for r in spec.routes]
    # tri lexicographique des chemins : "/pets/upload" < "/pets/{petId}"
    assert ids == ["GET /pets", "POST /pets", "POST /pets/upload", "GET /pets/{petId}"]

    post = spec.routes[1]
    body_param_only = [p for p in post.parameters if p.location == "body"]
    assert body_param_only == []
    assert post.request_body is not None
    schema = post.request_body.content_types["application/json"]
    assert schema.ref_name == "Pet"
    assert schema.properties["name"].type == "string"

    upload = next(r for r in spec.routes if "upload" in r.path)
    form = {p.name: p for p in upload.parameters if p.location == "formData"}
    assert set(form) == {"petId", "file"}

    scheme_names = {s.name: s for s in spec.security_schemes}
    assert scheme_names["api_key"].type == "apiKey"
    assert scheme_names["petstore_auth"].type == "oauth2"


def test_parse_rejects_unknown():
    try:
        parse_document({"hello": "world"}, name="x", source_url="https://x")
    except SpecError as exc:
        assert "OpenAPI" in str(exc)
    else:
        raise AssertionError("SpecError attendue")
