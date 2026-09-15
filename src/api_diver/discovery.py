"""Découverte des specs derrière une page swagger-ui HTML.

L'utilisateur ne donne que l'URL de la page (ex: .../swagger/index.html) ;
ce module retrouve les URLs des swagger.json/openapi.json qu'elle référence.

Patterns couverts (Swashbuckle, swagger-ui dist, etc.) :
1. Blobs `JSON.parse('{"urls":[{name,url},...]}')` embarqués dans la page
2. Tableaux `urls` en JSON (clés quotées) ou en JS (clés non quotées)
3. Mêmes patterns dans les <script src> externes (index.js du dist swagger-ui)
4. `configUrl` -> fetch du JSON de config -> ses `urls`/`url`
5. `url: "..."` unique, `data-spec-url`, `spec-url`
6. Fallbacks : fichiers frères courants (swagger.json, v1/swagger.json, ...)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from .errors import FetchError
from .fetcher import FetchedContent, FetchFn

# objets JS/JSON courts contenant au moins un champ url
_OBJ_BLOCK_RE = re.compile(r"\{[^{}]{0,600}?\}")
_URL_KEY_RE = re.compile(r"['\"]?url['\"]?\s*:\s*['\"]([^'\"]+)['\"]")
_NAME_KEY_RE = re.compile(r"['\"]?name['\"]?\s*:\s*['\"]([^'\"]+)['\"]")
_JSON_PARSE_RE = re.compile(r"JSON\.parse\(\s*(['\"])(.*?)\1\s*[\),]", re.S)
_CONFIG_URL_RE = re.compile(r"['\"]?configUrl['\"]?\s*:\s*['\"]([^'\"]+)['\"]")
_DATA_SPEC_RE = re.compile(r"(?:data-spec-url|spec-url)\s*=\s*['\"]([^'\"]+)['\"]")
_URLS_ARRAY_RE = re.compile(r"['\"]?urls['\"]?\s*:\s*\[(.*?)\]", re.S)
_SCRIPT_SRC_RE = re.compile(r"<script[^>]*\ssrc\s*=\s*[\"']([^\"']+)[\"']", re.I)
# bundles du dist swagger-ui : la config n'y vit jamais, on évite de les charger
_SKIP_SCRIPT_RE = re.compile(r"swagger-ui|jquery|highlight|modernizr|es5-shim|\.min\.js", re.I)

_SPEC_HINTS = ("swagger", "openapi", "api-docs", "api-doc", "spec", ".json", ".yaml", ".yml")

FALLBACK_CANDIDATES = (
    "swagger.json",
    "openapi.json",
    "v1/swagger.json",
    "v1/openapi.json",
    "swagger/v1/swagger.json",
    "swagger-config.json",
    "index.js",
)


@dataclass
class DiscoveredSpec:
    url: str
    label: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"url": self.url, "label": self.label}


@dataclass
class DiscoveryResult:
    specs: list[DiscoveredSpec] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _looks_like_spec_url(url: str) -> bool:
    lowered = url.lower()
    return any(hint in lowered for hint in _SPEC_HINTS)


def _pairs_in_block(block: str) -> list[tuple[str, str]]:
    """Extrait (url, label) d'un bloc objet `{...}`."""
    out: list[tuple[str, str]] = []
    for url_match in _URL_KEY_RE.finditer(block):
        label = ""
        name_match = _NAME_KEY_RE.search(block)
        if name_match:
            label = name_match.group(1)
        out.append((url_match.group(1), label))
    return out


def _urls_from_config_json(data: object) -> list[tuple[str, str]]:
    if not isinstance(data, dict):
        return []
    pairs: list[tuple[str, str]] = []
    if isinstance(data.get("urls"), list):
        for item in data["urls"]:
            if isinstance(item, dict) and item.get("url"):
                pairs.append((str(item["url"]), str(item.get("name", "") or "")))
    elif data.get("url"):
        pairs.append((str(data["url"]), str(data.get("name", "") or "")))
    return pairs


def _extract_explicit_pairs(text: str) -> list[tuple[str, str]]:
    """Tous les patterns explicites (1, 2 et 4) sur un texte HTML ou JS."""
    pairs: list[tuple[str, str]] = []

    # 1. blobs JSON.parse('...') : Swashbuckle et le dist swagger-ui (index.js)
    for match in _JSON_PARSE_RE.finditer(text):
        blob = match.group(2)
        try:
            data = json.loads(blob)
        except (json.JSONDecodeError, ValueError):
            continue
        pairs.extend(_urls_from_config_json(data))

    # 2. tableaux urls (JSON ou JS), analysés bloc objet par bloc objet
    if not pairs:
        for array_match in _URLS_ARRAY_RE.finditer(text):
            for block in _OBJ_BLOCK_RE.finditer(array_match.group(1)):
                pairs.extend(_pairs_in_block(block.group(0)))

    # 4. url unique (uniquement si le texte semble pertinent)
    if not pairs:
        for match in _URL_KEY_RE.finditer(text):
            candidate = match.group(1)
            if _looks_like_spec_url(candidate):
                pairs.append((candidate, ""))
    return pairs


def _dedupe(pairs: list[tuple[str, str]], page_url: str) -> list[DiscoveredSpec]:
    specs: list[DiscoveredSpec] = []
    seen: set[str] = set()
    for raw_url, label in pairs:
        if not raw_url or raw_url.startswith("#"):
            continue
        url = urljoin(page_url, raw_url)
        if url in seen:
            continue
        seen.add(url)
        specs.append(DiscoveredSpec(url=url, label=label.strip()))
    return specs


def discover_specs(html: str, page_url: str, fetch_fn: FetchFn | None = None) -> DiscoveryResult:
    result = DiscoveryResult()
    pairs: list[tuple[str, str]] = []

    # 1-2-4 : patterns explicites dans la page elle-même
    pairs = _extract_explicit_pairs(html)
    if pairs:
        result.notes.append("config trouvée dans la page")

    # 3. patterns dans les <script src> externes (ex: index.js du dist swagger-ui)
    if not pairs and fetch_fn is not None:
        srcs: list[str] = []
        for match in _SCRIPT_SRC_RE.finditer(html):
            src = urljoin(page_url, match.group(1))
            if _SKIP_SCRIPT_RE.search(src):
                continue
            if src not in srcs:
                srcs.append(src)
        for src in srcs[:6]:
            try:
                fetched: FetchedContent = fetch_fn(src)
            except FetchError as exc:
                result.notes.append(f"script {src} inaccessible : {exc}")
                continue
            if fetched.kind in ("text", "html"):
                script_pairs = _extract_explicit_pairs(str(fetched.data))
                if script_pairs:
                    pairs = script_pairs
                    result.notes.append(f"config trouvée dans le script externe {src}")
                    break

    # 5. configUrl -> fetch du JSON de configuration
    if not pairs:
        config_match = _CONFIG_URL_RE.search(html)
        if config_match and fetch_fn is not None:
            config_url = urljoin(page_url, config_match.group(1))
            try:
                fetched = fetch_fn(config_url)
                pairs = _urls_from_config_json(fetched.data if fetched.kind == "spec" else {})
                if pairs:
                    result.notes.append(f"config chargée depuis {config_url}")
            except FetchError as exc:
                result.notes.append(f"configUrl {config_url} inaccessible : {exc}")

    # 5bis. attributs data-spec-url
    if not pairs:
        for match in _DATA_SPEC_RE.finditer(html):
            pairs.append((match.group(1), ""))
        if pairs:
            result.notes.append("URL de spec trouvée via data-spec-url")

    specs = _dedupe(pairs, page_url)

    # 6. fallbacks : fichiers frères courants
    if not specs:
        result.notes.append(
            "aucun pattern explicite trouvé dans la page "
            "(JSON.parse embarqué, tableau « urls », scripts externes, configUrl, url unique)"
        )
        if fetch_fn is not None:
            for candidate in FALLBACK_CANDIDATES:
                url = urljoin(page_url, candidate)
                try:
                    fetched = fetch_fn(url)
                except FetchError:
                    continue
                if fetched.looks_like_spec() and (
                    "openapi" in fetched.data or "swagger" in fetched.data
                ):
                    specs = [DiscoveredSpec(url=url, label="")]
                    result.notes.append(f"spec trouvée par fallback : {url}")
                    break

    result.specs = specs
    return result
