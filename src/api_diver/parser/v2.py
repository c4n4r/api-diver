"""Normalisation Swagger 2.0 -> modèle canonique."""

from __future__ import annotations

from urllib.parse import urlsplit

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
    body_from_v2_param,
    build_parameter_v2,
    build_schema,
    clean_text,
    convert_security_scheme,
    merge_parameters,
)


def _domains_from_host(doc: dict, source_url: str) -> list[Domain]:
    host = doc.get("host")
    if not host:
        netloc = urlsplit(source_url).netloc if source_url else ""
        host = netloc or "localhost"
    schemes = doc.get("schemes") or ["https"]
    base_path = doc.get("basePath") or ""
    domains: list[Domain] = []
    seen: set[str] = set()
    for scheme in schemes:
        url = f"{scheme}://{host}{base_path}"
        if url not in seen:
            seen.add(url)
            domains.append(Domain(url=url))
    return domains


def _security_names(security) -> list[list[str]]:
    out: list[list[str]] = []
    if not isinstance(security, list):
        return out
    for req in security:
        if isinstance(req, dict) and req:
            out.append([str(k) for k in req.keys()])
    return out


def _build_responses(raw, consumes: str) -> list[Response]:
    responses: list[Response] = []
    if not isinstance(raw, dict):
        return responses
    for code, resp in sorted(raw.items(), key=lambda kv: str(kv[0])):
        if not isinstance(resp, dict):
            continue
        content_types = {}
        if "schema" in resp:
            schema = build_schema(resp["schema"])
            if schema is not None:
                content_types[consumes] = schema
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
    domains = _domains_from_host(resolved, source_url)
    global_consumes = (resolved.get("consumes") or ["application/json"])[0]
    root_security = _security_names(resolved.get("security"))

    security_schemes: list[SecurityScheme] = []
    for scheme_name, raw in (resolved.get("securityDefinitions") or {}).items():
        if isinstance(raw, dict):
            security_schemes.append(convert_security_scheme(str(scheme_name), raw))

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

            consumes = (operation.get("consumes") or [global_consumes])[0]
            parameters: list[Parameter] = []
            body: RequestBody | None = None
            for raw_param in merge_parameters(path_params, operation.get("parameters") or []):
                location = str(raw_param.get("in", "query"))
                if location == "body":
                    body = body_from_v2_param(raw_param, consumes) or body
                    continue
                param = build_parameter_v2(raw_param)
                if param is not None:
                    parameters.append(param)

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
                    responses=_build_responses(operation.get("responses"), consumes),
                    security=_security_names(operation.get("security")) or root_security,
                )
            )

    order = {m: i for i, m in enumerate(HTTP_METHODS)}
    routes.sort(key=lambda r: (r.path, order.get(r.method, 99)))

    return ApiSpec(
        name=name,
        title=str(info.get("title", "") or name),
        version=str(info.get("version", "") or ""),
        openapi_version=str(resolved.get("swagger", "2.0")),
        source_url=source_url,
        description=clean_text(info.get("description", ""), 800),
        domains=domains,
        security_schemes=security_schemes,
        routes=routes,
        groups=[group_label] if group_label else [],
        spec_urls=[{"url": source_url, "label": group_label}] if group_label else [],
    )
