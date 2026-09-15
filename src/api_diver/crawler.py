"""Crawler : d'une seule URL (page swagger-ui ou spec directe) vers une API fusionnée.

Une source peut cacher plusieurs specs (ex: Swashbuckle multi-docs —
« Agency Tanks », « Articles »...) : chacune est crawlée puis fusionnée en une
seule ApiSpec, les routes étant étiquetées par le nom de leur spec d'origine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .discovery import DiscoveredSpec, discover_specs
from .errors import FetchError, SpecError
from .fetcher import FetchedContent, FetchFn, make_fetcher
from .model import ApiSpec, Domain
from .parser import parse_document
from .util import slugify


def derive_name_from_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.netloc.split(":")[0].split(".")[0] if parts.netloc else ""
    path_bits = [b for b in parts.path.split("/") if b and b.endswith((".html", ".json", ".yaml")) is False]
    path_bits = [re.sub(r"\.(html?|json|ya?ml)$", "", b) for b in path_bits]
    path_bits = [b for b in path_bits if b.lower() not in ("swagger", "index", "api-docs", "docs", "v1", "v2", "v3")]
    candidate = "-".join([host] + path_bits[:3])
    return slugify(candidate, fallback="api")


@dataclass
class CrawlResult:
    spec: ApiSpec
    spec_urls: list[dict[str, str]]  # [{"url", "label"}]
    raw_docs: list[tuple[str, dict]] = field(default_factory=list)  # (url, doc brut)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # informations de découverte


def _fetch_spec_or_die(fetch_fn: FetchFn, url: str, label: str, warnings: list[str]) -> dict | None:
    try:
        fetched: FetchedContent = fetch_fn(url)
    except FetchError as exc:
        warnings.append(f"spec « {label or url} » inaccessible : {exc}")
        return None
    if not fetched.looks_like_spec():
        warnings.append(f"« {url} » n'est pas une spec exploitable ({fetched.kind})")
        return None
    if "openapi" not in fetched.data and "swagger" not in fetched.data:
        warnings.append(f"« {url} » ne contient ni clé « openapi » ni « swagger », ignoré")
        return None
    return fetched.data


def crawl_source(
    source_url: str,
    headers: dict[str, str] | None = None,
    name: str | None = None,
    fetch_fn: FetchFn | None = None,
) -> CrawlResult:
    fetch = fetch_fn or make_fetcher(headers)

    try:
        page: FetchedContent = fetch(source_url)
    except FetchError as exc:
        raise FetchError(f"source inaccessible : {exc}") from exc

    warnings: list[str] = []
    discovery_notes: list[str] = []
    discovered: list[DiscoveredSpec] = []

    if page.looks_like_spec() and ("openapi" in page.data or "swagger" in page.data):
        discovered.append(DiscoveredSpec(url=page.url, label=""))
    elif page.kind == "html":
        result = discover_specs(page.data, page.url, fetch_fn=fetch)
        discovery_notes = result.notes
        discovered = result.specs
        if not discovered:
            raise FetchError(
                f"aucune spec trouvée derrière {page.url}\n"
                + "\n".join(f"  - {n}" for n in result.notes)
                + "\nVérifie l'URL ou fournis directement l'URL du swagger.json."
            )
    else:
        raise SpecError(
            f"le contenu de {page.url} n'est ni une spec OpenAPI/Swagger ni une page swagger-ui"
        )

    api_name = slugify(name) if name else ""
    if not api_name:
        if len(discovered) == 1 and not discovered[0].label:
            api_name = ""  # dérivé plus bas depuis le titre / l'URL
        else:
            api_name = derive_name_from_url(page.url)

    parsed_specs: list[tuple[DiscoveredSpec, dict]] = []
    raw_docs: list[tuple[str, dict]] = []
    for ds in discovered:
        raw = _fetch_spec_or_die(fetch, ds.url, ds.label, warnings)
        if raw is not None:
            parsed_specs.append((ds, raw))
            raw_docs.append((ds.url, raw))

    if not parsed_specs:
        raise FetchError(
            "aucune spec n'a pu être téléchargée :\n"
            + "\n".join(f"  - {w}" for w in warnings)
        )

    parse_warnings: list[str] = []
    parsed_apis: list[tuple[DiscoveredSpec, ApiSpec]] = []
    for ds, raw in parsed_specs:
        try:
            spec = parse_document(
                raw,
                name=api_name or "temp",
                source_url=source_url,
                group_label=ds.label,
                collect_warnings=parse_warnings,
            )
        except SpecError as exc:
            warnings.append(f"spec « {ds.label or ds.url} » illisible : {exc}")
            continue
        parsed_apis.append((ds, spec))
    warnings.extend(parse_warnings)

    if not parsed_apis:
        raise SpecError("aucune spec valide n'a pu être normalisée :\n" + "\n".join(warnings))

    merged = _merge(parsed_apis, source_url=source_url, name=api_name)

    spec_urls = [{"url": ds.url, "label": ds.label} for ds, _ in parsed_apis]

    return CrawlResult(
        spec=merged, spec_urls=spec_urls, raw_docs=raw_docs, warnings=warnings, notes=discovery_notes
    )


def _merge(parsed: list[tuple[DiscoveredSpec, ApiSpec]], source_url: str, name: str) -> ApiSpec:
    first_spec = parsed[0][1]

    if len(parsed) == 1 and not parsed[0][0].label:
        merged = first_spec
        if name:
            merged.name = name
        merged.source_url = source_url
        merged.spec_urls = [{"url": parsed[0][0].url, "label": ""}]
        return merged

    domains: list[Domain] = []
    seen_domains: set[str] = set()
    schemes_by_name: dict[str, object] = {}
    routes = []
    groups: list[str] = []
    openapi_versions: set[str] = set()

    for ds, spec in parsed:
        openapi_versions.add(spec.openapi_version)
        for domain in spec.domains:
            if domain.url not in seen_domains:
                seen_domains.add(domain.url)
                domains.append(domain)
        for scheme in spec.security_schemes:
            schemes_by_name.setdefault(scheme.name, scheme)
        if ds.label and ds.label not in groups:
            groups.append(ds.label)
        routes.extend(spec.routes)

    host = urlsplit(source_url).netloc
    merged = ApiSpec(
        name=name or first_spec.name,
        title=host or first_spec.title,
        version=first_spec.version,
        openapi_version=", ".join(sorted(openapi_versions)),
        source_url=source_url,
        description=first_spec.description,
        domains=domains,
        security_schemes=list(schemes_by_name.values()),
        routes=routes,
        groups=groups,
        spec_urls=[{"url": ds.url, "label": ds.label} for ds, _ in parsed],
    )
    return merged
