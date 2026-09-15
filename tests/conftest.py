"""Fixtures de specs pour les tests offline."""

from __future__ import annotations

import pytest

V3_DOC = {
    "openapi": "3.0.3",
    "info": {"title": "Stock API", "version": "1.2.0", "description": "API de gestion de stock"},
    "servers": [
        {"url": "https://api.example.com/v1", "description": "production"},
        {"url": "https://{env}.api.example.com/v1", "description": "par environnement",
         "variables": {"env": {"default": "eu", "enum": ["eu", "us"]}}},
    ],
    "tags": [{"name": "customers"}, {"name": "articles"}],
    "paths": {
        "/customers": {
            "get": {
                "tags": ["customers"],
                "summary": "Liste les clients",
                "operationId": "listCustomers",
                "parameters": [
                    {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer", "default": 20}},
                    {"name": "X-Request-Id", "in": "header", "required": False, "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": {
                        "description": "OK",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CustomerList"}}},
                    }
                },
            },
            "post": {
                "tags": ["customers"],
                "summary": "Crée un client",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CustomerInput"}}},
                },
                "responses": {
                    "201": {
                        "description": "Créé",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Customer"}}},
                    },
                    "422": {"description": "Validation"},
                },
                "security": [{"bearerAuth": []}],
            },
        },
        "/customers/{id}": {
            "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
            "delete": {
                "tags": ["customers"],
                "summary": "Supprime un client",
                "servers": [{"url": "https://admin.example.com"}],
                "responses": {"204": {"description": "Supprimé"}},
            },
        },
    },
    "components": {
        "schemas": {
            "Customer": {
                "type": "object",
                "required": ["id", "name"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "address": {"$ref": "#/components/schemas/Address"},
                },
            },
            "Address": {
                "type": "object",
                "properties": {"city": {"type": "string"}, "zip": {"type": "string"}},
            },
            "CustomerList": {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": {"$ref": "#/components/schemas/Customer"}},
                },
            },
            "CustomerInput": {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}, "address": {"$ref": "#/components/schemas/Address"}},
            },
        },
        "securitySchemes": {
            "bearerAuth": {"type": "http", "scheme": "bearer"},
            "apiKey": {"type": "apiKey", "name": "X-Api-Key", "in": "header"},
        },
    },
    "security": [{"apiKey": []}],
}

V2_DOC = {
    "swagger": "2.0",
    "info": {"title": "Petstore", "version": "1.0.0"},
    "host": "petstore.example.com",
    "schemes": ["http", "https"],
    "basePath": "/v2",
    "securityDefinitions": {
        "petstore_auth": {"type": "oauth2", "flow": "implicit"},
        "api_key": {"type": "apiKey", "name": "api_key", "in": "header"},
    },
    "paths": {
        "/pets": {
            "get": {
                "tags": ["pets"],
                "summary": "Liste les animaux",
                "parameters": [{"name": "status", "in": "query", "type": "string", "enum": ["available", "sold"]}],
                "responses": {
                    "200": {"description": "OK", "schema": {"type": "array", "items": {"$ref": "#/definitions/Pet"}}}
                },
            },
            "post": {
                "tags": ["pets"],
                "summary": "Ajoute un animal",
                "parameters": [
                    {"name": "body", "in": "body", "required": True, "schema": {"$ref": "#/definitions/Pet"}}
                ],
                "responses": {"201": {"description": "Créé", "schema": {"$ref": "#/definitions/Pet"}}},
            },
        },
        "/pets/{petId}": {
            "get": {
                "tags": ["pets"],
                "summary": "Cherche un animal",
                "parameters": [{"name": "petId", "in": "path", "required": True, "type": "integer"}],
                "responses": {"200": {"description": "OK", "schema": {"$ref": "#/definitions/Pet"}}},
            },
        },
        "/pets/upload": {
            "post": {
                "tags": ["pets"],
                "summary": "Upload une photo",
                "consumes": ["multipart/form-data"],
                "parameters": [
                    {"name": "petId", "in": "formData", "required": True, "type": "integer"},
                    {"name": "file", "in": "formData", "required": True, "type": "file"},
                ],
                "responses": {"200": {"description": "OK"}},
            },
        },
    },
    "definitions": {
        "Pet": {
            "type": "object",
            "required": ["id", "name"],
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "tag": {"type": "string"},
            },
        }
    },
}

# Page swagger-ui façon Swashbuckle : config injectée via JSON.parse
SWASHBUCKLE_HTML = """<!DOCTYPE html>
<html>
<head><title>Swagger UI</title></head>
<body>
<div id="swagger-ui"></div>
<script>
window.onload = function() {
  var configObject = JSON.parse('{"urls":[{"name":"Agency Tanks","url":"/api-stock/swagger/AgencyTanks/swagger.json"},{"name":"Articles","url":"/api-stock/swagger/Articles/swagger.json"}],"dom_id":"#swagger-ui"}');
  const ui = SwaggerUIBundle(configObject);
}
</script>
</body>
</html>"""

AGENCY_TANKS_SPEC = {
    "swagger": "2.0",
    "info": {"title": "Agency Tanks", "version": "1.0"},
    "host": "vnext.sosoxygene.com",
    "schemes": ["https"],
    "basePath": "/api-stock",
    "paths": {
        "/api/tanks": {
            "get": {
                "tags": ["Tanks"],
                "summary": "Liste les cuves",
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
}

ARTICLES_SPEC = {
    "openapi": "3.0.1",
    "info": {"title": "Articles", "version": "1.0"},
    "servers": [{"url": "https://vnext.sosoxygene.com/api-stock"}],
    "paths": {
        "/api/articles": {
            "get": {
                "tags": ["Articles"],
                "summary": "Liste les articles",
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
}


@pytest.fixture
def v3_doc():
    return V3_DOC


@pytest.fixture
def v2_doc():
    return V2_DOC
