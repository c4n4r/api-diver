"""Normalisation OpenAPI 3.x -> modèle canonique."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from ..model import (
    ApiSpec,
    Domain,
    HTTP_METHODS,
    Parameter,
    RequestBody,
    Response,
    Route,
    SecurityScheme,
)
from .resolver import resolve_document
from .schemas import (
    build_parameter_v3,
    build_schema,
    clean_text,
    convert_security_scheme,
    merge_parameters,
)

_VAR_RE = re.compile(r"\{([^}/]+)\}")


def _resolve_server_url(server: dict) -> str:
    url = str(server.get("url", ""))
    variables = server.get("variables") or {}

    def replace(match: re.Match) -> str:
        name = match.group(1)
        var = variables.get(name)
        if isinstance(var, dict) and var.get("default") is not None:
            return str(var["default"])
        return match.group(0)

    return _VAR_RE.sub(replace, url)


def servers_to_domains(servers: list, source_url: str = "") -> list[Domain]:
    """Convertit `servers[]` en domaines ; les URLs relatives sont résolues
    contre l'origine de la source."""
    domains: list[Domain] = []
    seen: set[str] = set()
    for server in servers or []:
        if not isinstance(server, dict):
            continue
        url = _resolve_server_url(server)
        if not url:
            continue
        if url.startswith("/") and source_url:
            url = urljoin(source_url, url)
        if url not in seen:
            seen.add(url)
            domains.append(Domain(url=url, description=clean_text(server.get("description", ""), 200)))
    return domains


def _effective_servers(operation: dict, path_item: dict, root_servers: list) -> list | None:
    for holder in (operation, path_item):
        if isinstance(holder.get("servers"), list) and holder["servers"]:
            return holder["servers"]
    return root_servers


def _security_names(security: Any) -> list[list[str]]:
    out: list[list[str]] = []
    if not isinstance(security, list):
        return out
    for req in security:
        if isinstance(req, dict):
            names = [str(k) for k in req.keys()]
            out.append(names if names else [])
    return [x for x in out if x]


def _build_request_body(raw: Any) -> RequestBody | None:
    if not isinstance(raw, dict):
        return None
    content_types: dict[str, object] = {}
    content = raw.get("content")
    if isinstance(content, dict):
        for ct, media in content.items():
            if not isinstance(media, dict):
                continue
            if "schema" in media:
                schema = build_schema(media["schema"])
                if schema is not None:
                    if schema.example is None and isinstance(media.get("example"), (str, int, float, bool)):
                        schema.example = media["example"]
                    content_types[str(ct)] = schema
    if not content_types:
        return None
    return RequestBody(
        required=bool(raw.get("required", False)),
        description=clean_text(raw.get("description", "")),
        content_types=content_types,
    )


def _build_responses(raw: Any) -> list[Response]:
    responses: list[Response] = []
    if not isinstance(raw, dict):
        return responses
    for code, resp in sorted(raw.items(), key=lambda kv: str(kv[0])):
        if not isinstance(resp, dict):
            continue
        content_types: dict[str, object] = {}
        content = resp.get("content")
        if isinstance(content, dict):
            for ct, media in content.items():
                if isinstance(media, dict) and "schema" in media:
                    schema = build_schema(media["schema"])
                    if schema is not None:
                        content_types[str(ct)] = schema
        responses.append(
            Response(
                status=str(code),
                description=clean_text(resp.get("description", "")),
                content_types=content_types,
            )
        )
    return responses


def parse(
    doc: dict,
    name: str,
    source_url: str,
    group_label: str = "",
    collect_warnings: list | None = None,
) -> ApiSpec:
    resolved, warnings = resolve_document(doc)
    if collect_warnings is not None:
        collect_warnings.extend(warnings)

    info = resolved.get("info") or {}
    root_servers = resolved.get("servers") or []
    domains = servers_to_domains(root_servers, source_url)
    root_domain_urls = [d.url for d in domains]

    security_schemes: list[SecurityScheme] = []
    components = resolved.get("components") or {}
    for scheme_name, raw in (components.get("securitySchemes") or {}).items():
        if isinstance(raw, dict):
            security_schemes.append(convert_security_scheme(str(scheme_name), raw))
    root_security = _security_names(resolved.get("security"))

    routes: list[Route] = []
    paths = resolved.get("paths") or {}
    if not isinstance(paths, dict):
        paths = {}
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        path_params = path_item.get("parameters") or []
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            tags = list(operation.get("tags") or [])
            if group_label:
                tags = [group_label] + [t for t in tags if t != group_label]

            parameters: list[Parameter] = []
            body: RequestBody | None = None
            for raw_param in merge_parameters(path_params, operation.get("parameters") or []):
                location = str(raw_param.get("in", "query"))
                if location == "body":  # toléré dans certains specs 3.x dérivés de v2
                    body = _build_request_body({"schema": raw_param.get("schema")}) or body
                    continue
                param = build_parameter_v3(raw_param)
                if param is not None:
                    parameters.append(param)
            if body is None:
                body = _build_request_body(operation.get("requestBody"))

            route_domains = _effective_servers(operation, path_item, root_servers)
            specific = [d.url for d in servers_to_domains(route_domains or [], source_url)]
            domain_urls = specific if specific and specific != root_domain_urls else []

            routes.append(
                Route(
                    path=str(path),
                    method=method,
                    operation_id=str(operation.get("operationId", "") or ""),
                    summary=clean_text(operation.get("summary", "")),
                    description=clean_text(operation.get("description", ""), 800),
                    tags=tags,
                    deprecated=bool(operation.get("deprecated", False)),
                    parameters=parameters,
                    request_body=body,
                    responses=_build_responses(operation.get("responses")),
                    security=_security_names(operation.get("security")) or root_security,
                    domain_urls=domain_urls,
                )
            )

    order = {m: i for i, m in enumerate(HTTP_METHODS)}
    routes.sort(key=lambda r: (r.path, order.get(r.method, 99)))

    return ApiSpec(
        name=name,
        title=str(info.get("title", "") or name),
        version=str(info.get("version", "") or ""),
        openapi_version=str(resolved.get("openapi", "3.x")),
        source_url=source_url,
        description=clean_text(info.get("description", ""), 800),
        domains=domains,
        security_schemes=security_schemes,
        routes=routes,
        groups=[group_label] if group_label else [],
        spec_urls=[{"url": source_url, "label": group_label}] if group_label else [],
    )
