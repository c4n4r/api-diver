"""Modèle canonique interne d'api-diver.

Toutes les specs (Swagger 2.0 comme OpenAPI 3.x) sont converties vers ces
dataclasses avant stockage dans le workspace et génération du skill.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


@dataclass
class Domain:
    """Un domaine (= base URL effective) d'une API."""

    url: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "description": self.description}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Domain":
        return cls(url=data.get("url", ""), description=data.get("description", ""))


@dataclass
class SecurityScheme:
    """Schéma d'authentification (apiKey / http bearer / basic / oauth2...)."""

    name: str  # clé du schéma dans la spec (référencée par `security`)
    type: str  # apiKey | http | oauth2 | openIdConnect
    location: str = ""  # header | query | cookie (apiKey)
    scheme: str = ""  # bearer | basic (http)
    param_name: str = ""  # nom réel du header/query pour apiKey (ex: X-Api-Key)
    description: str = ""

    def resolved_param_name(self) -> str:
        return self.param_name or self.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "location": self.location,
            "scheme": self.scheme,
            "param_name": self.param_name,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SecurityScheme":
        return cls(
            name=data.get("name", ""),
            type=data.get("type", ""),
            location=data.get("location", ""),
            scheme=data.get("scheme", ""),
            param_name=data.get("param_name", ""),
            description=data.get("description", ""),
        )


@dataclass
class SchemaNode:
    """Schéma JSON résolu et simplifié (les $ref locaux sont déjà inlinés)."""

    type: str = "string"  # object|array|string|integer|number|boolean|any|ref
    format: str = ""
    description: str = ""
    required: list[str] = field(default_factory=list)
    properties: dict[str, SchemaNode] = field(default_factory=dict)
    items: Optional[SchemaNode] = None
    enum: list[Any] = field(default_factory=list)
    default: Any = None
    example: Any = None
    ref_name: str = ""  # nom du $ref d'origine, pour titrer le schéma
    additional_properties: Optional[SchemaNode] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type}
        if self.format:
            d["format"] = self.format
        if self.description:
            d["description"] = self.description
        if self.required:
            d["required"] = list(self.required)
        if self.properties:
            d["properties"] = {k: v.to_dict() for k, v in self.properties.items()}
        if self.items is not None:
            d["items"] = self.items.to_dict()
        if self.enum:
            d["enum"] = list(self.enum)
        if self.default is not None:
            d["default"] = self.default
        if self.example is not None:
            d["example"] = self.example
        if self.ref_name:
            d["ref_name"] = self.ref_name
        if self.additional_properties is not None:
            d["additional_properties"] = self.additional_properties.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SchemaNode":
        return cls(
            type=data.get("type", "string"),
            format=data.get("format", ""),
            description=data.get("description", ""),
            required=list(data.get("required", [])),
            properties={
                k: cls.from_dict(v) for k, v in data.get("properties", {}).items()
            },
            items=cls.from_dict(data["items"]) if data.get("items") else None,
            enum=list(data.get("enum", [])),
            default=data.get("default"),
            example=data.get("example"),
            ref_name=data.get("ref_name", ""),
            additional_properties=(
                cls.from_dict(data["additional_properties"])
                if data.get("additional_properties")
                else None
            ),
        )


@dataclass
class Parameter:
    name: str
    location: str  # path | query | header | cookie | formData
    required: bool = False
    description: str = ""
    type: str = "string"
    format: str = ""
    enum: list[Any] = field(default_factory=list)
    default: Any = None
    example: Any = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "location": self.location,
            "required": self.required,
            "type": self.type,
        }
        for attr in ("description", "format", "default", "example"):
            value = getattr(self, attr)
            if value not in ("", None):
                d[attr] = value
        if self.enum:
            d["enum"] = list(self.enum)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Parameter":
        return cls(
            name=data.get("name", ""),
            location=data.get("location", "query"),
            required=bool(data.get("required", False)),
            description=data.get("description", ""),
            type=data.get("type", "string"),
            format=data.get("format", ""),
            enum=list(data.get("enum", [])),
            default=data.get("default"),
            example=data.get("example"),
        )


@dataclass
class RequestBody:
    required: bool = False
    description: str = ""
    # "application/json" -> schéma
    content_types: dict[str, SchemaNode] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "description": self.description,
            "content_types": {k: v.to_dict() for k, v in self.content_types.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RequestBody":
        return cls(
            required=bool(data.get("required", False)),
            description=data.get("description", ""),
            content_types={
                k: SchemaNode.from_dict(v)
                for k, v in data.get("content_types", {}).items()
            },
        )


@dataclass
class Response:
    status: str
    description: str = ""
    content_types: dict[str, SchemaNode] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "description": self.description,
            "content_types": {k: v.to_dict() for k, v in self.content_types.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Response":
        return cls(
            status=data.get("status", ""),
            description=data.get("description", ""),
            content_types={
                k: SchemaNode.from_dict(v)
                for k, v in data.get("content_types", {}).items()
            },
        )


@dataclass
class Route:
    path: str
    method: str
    operation_id: str = ""
    summary: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    deprecated: bool = False
    parameters: list[Parameter] = field(default_factory=list)
    request_body: Optional[RequestBody] = None
    responses: list[Response] = field(default_factory=list)
    # noms de schemes requis : liste de listes (OR de AND), ex [["apiKeyA"], ["oauth", "pkce"]]
    security: list[list[str]] = field(default_factory=list)
    # serveurs spécifiques à l'opération (operation-level servers), si différents du root
    domain_urls: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.method.upper()} {self.path}"

    def signature(self) -> str:
        """Empreinte stable des éléments structurants, pour les diffs d'update."""
        payload = {
            "tags": self.tags,
            "deprecated": self.deprecated,
            "parameters": [p.to_dict() for p in self.parameters],
            "request_body": self.request_body.to_dict() if self.request_body else None,
            "responses": [r.to_dict() for r in self.responses],
            "security": self.security,
            "domain_urls": self.domain_urls,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.md5(blob.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "path": self.path,
            "method": self.method,
            "tags": self.tags,
            "deprecated": self.deprecated,
            "parameters": [p.to_dict() for p in self.parameters],
            "responses": [r.to_dict() for r in self.responses],
        }
        for attr in ("operation_id", "summary", "description"):
            value = getattr(self, attr)
            if value:
                d[attr] = value
        if self.request_body is not None:
            d["request_body"] = self.request_body.to_dict()
        if self.security:
            d["security"] = self.security
        if self.domain_urls:
            d["domain_urls"] = self.domain_urls
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Route":
        return cls(
            path=data.get("path", ""),
            method=data.get("method", ""),
            operation_id=data.get("operation_id", ""),
            summary=data.get("summary", ""),
            description=data.get("description", ""),
            tags=list(data.get("tags", [])),
            deprecated=bool(data.get("deprecated", False)),
            parameters=[Parameter.from_dict(p) for p in data.get("parameters", [])],
            request_body=(
                RequestBody.from_dict(data["request_body"])
                if data.get("request_body")
                else None
            ),
            responses=[Response.from_dict(r) for r in data.get("responses", [])],
            security=[list(s) for s in data.get("security", [])],
            domain_urls=list(data.get("domain_urls", [])),
        )


@dataclass
class ApiSpec:
    name: str
    title: str
    version: str
    openapi_version: str  # "2.0" | "3.0.x" | "3.1.x"
    source_url: str
    description: str = ""
    domains: list[Domain] = field(default_factory=list)
    security_schemes: list[SecurityScheme] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    # labels des specs découvertes derrière la source (ex: "Agency Tanks", "Articles")
    groups: list[str] = field(default_factory=list)
    # provenance : [{"url": "...", "label": "..."}]
    spec_urls: list[dict[str, str]] = field(default_factory=list)

    def tag_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for route in self.routes:
            for tag in route.tags or [""]:
                counts[tag] = counts.get(tag, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    def to_dict(self) -> dict[str, Any]:
        d = {
            "name": self.name,
            "title": self.title,
            "version": self.version,
            "openapi_version": self.openapi_version,
            "source_url": self.source_url,
            "domains": [dom.to_dict() for dom in self.domains],
            "security_schemes": [s.to_dict() for s in self.security_schemes],
            "routes": [r.to_dict() for r in self.routes],
            "groups": self.groups,
            "spec_urls": self.spec_urls,
        }
        if self.description:
            d["description"] = self.description
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApiSpec":
        return cls(
            name=data.get("name", ""),
            title=data.get("title", ""),
            version=data.get("version", ""),
            openapi_version=data.get("openapi_version", ""),
            source_url=data.get("source_url", ""),
            description=data.get("description", ""),
            domains=[Domain.from_dict(x) for x in data.get("domains", [])],
            security_schemes=[
                SecurityScheme.from_dict(x) for x in data.get("security_schemes", [])
            ],
            routes=[Route.from_dict(x) for x in data.get("routes", [])],
            groups=list(data.get("groups", [])),
            spec_urls=[dict(x) for x in data.get("spec_urls", [])],
        )


@dataclass
class RouteDiff:
    added: list[str]
    removed: list[str]
    modified: list[str]

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.modified)

    def summary(self) -> str:
        parts = []
        if self.added:
            parts.append(f"+{len(self.added)}")
        if self.removed:
            parts.append(f"-{len(self.removed)}")
        if self.modified:
            parts.append(f"~{len(self.modified)}")
        return " ".join(parts) if parts else "aucun changement"


def diff_routes(old: list[Route], new: list[Route]) -> RouteDiff:
    """Compare deux versions des routes d'une API (par METHOD+chemin)."""
    old_map = {r.id: r.signature() for r in old}
    new_map = {r.id: r.signature() for r in new}
    added = sorted(set(new_map) - set(old_map))
    removed = sorted(set(old_map) - set(new_map))
    modified = sorted(
        rid for rid in set(old_map) & set(new_map) if old_map[rid] != new_map[rid]
    )
    return RouteDiff(added=added, removed=removed, modified=modified)
