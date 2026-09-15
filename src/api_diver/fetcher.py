"""Téléchargement des contenus (specs et pages swagger-ui) + auth en refs env.

Les headers d'auth peuvent être passés sous la forme `{$NOM_VAR}` : la valeur
est lue dans l'environnement au moment du fetch et n'est jamais persistée.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import httpx
import yaml

from .errors import FetchError

ENV_REF_RE = re.compile(r"^\{\$([A-Za-z_][A-Za-z0-9_]*)\}$")
USER_AGENT = "api-diver (cartographie de swaggers en skills agents)"


def resolve_header_value(value: str) -> str:
    """`{$VAR}` -> valeur de l'environnement ; toute autre forme est renvoyée telle quelle."""
    match = ENV_REF_RE.match(value.strip())
    if match:
        var = match.group(1)
        resolved = os.environ.get(var)
        if resolved is None:
            raise FetchError(f"variable d'environnement ${var} absente pour l'authentification")
        return resolved
    return value


def split_header_arg(raw: str) -> tuple[str, str]:
    if ":" not in raw:
        raise FetchError(f"header invalide « {raw} » (format attendu : « Nom: valeur »)")
    key, value = raw.split(":", 1)
    key, value = key.strip(), value.strip()
    if not key:
        raise FetchError(f"header invalide « {raw} » (nom vide)")
    return key, value


def build_headers(
    stored: Optional[dict[str, str]] = None,
    header_args: Optional[list[str]] = None,
) -> dict[str, str]:
    """Assemble les headers : refs env persistées + API_DIVER_HEADERS + flags du moment."""
    headers: dict[str, str] = {}
    for key, ref in (stored or {}).items():
        if ref.startswith("env:"):
            var = ref[4:]
            value = os.environ.get(var)
            if value is None:
                raise FetchError(
                    f"header « {key} » référencé par env:${var} mais la variable est absente"
                )
            headers[key] = value
        else:
            headers[key] = resolve_header_value(ref)
    env_blob = os.environ.get("API_DIVER_HEADERS")
    if env_blob:
        try:
            extra = json.loads(env_blob)
            if not isinstance(extra, dict):
                raise ValueError("pas un objet")
            for key, value in extra.items():
                headers[str(key)] = resolve_header_value(str(value))
        except ValueError as exc:
            raise FetchError(f"API_DIVER_HEADERS invalide (JSON attendu) : {exc}") from exc
    for raw in header_args or []:
        key, value = split_header_arg(raw)
        headers[key] = resolve_header_value(value)
    return headers


@dataclass
class FetchedContent:
    url: str  # URL finale après redirections
    kind: str  # "spec" | "html" | "text"
    data: Any  # dict si spec, texte brut sinon
    content_type: str = ""
    warnings: list[str] = field(default_factory=list)

    def looks_like_spec(self) -> bool:
        return self.kind == "spec" and isinstance(self.data, dict)


def _parse_payload(text: str, content_type: str) -> tuple[str, Any]:
    ct = content_type.lower()
    is_js = "javascript" in ct or "ecmascript" in ct or ct.endswith("/js")
    lowered = text[:3000].lstrip().lower()
    is_html_ct = "html" in ct
    looks_html = is_html_ct or lowered.startswith("<!doctype html") or lowered.startswith("<html")

    if not is_js and not looks_html:
        try:
            return "spec", json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass
        if not is_js:
            try:
                parsed = yaml.safe_load(text)
            except yaml.YAMLError:
                parsed = None
            if isinstance(parsed, (dict, list)):
                return "spec", parsed
    if looks_html:
        # page HTML : on tente quand même un JSON/YAML au cas où le content-type mente
        stripped = text.lstrip()
        if stripped.startswith(("{", "[")):
            try:
                return "spec", json.loads(text)
            except (json.JSONDecodeError, ValueError):
                pass
        return "html", text
    # JS, CSS ou autre texte : renvoyé brut (utile pour scanner les configs embarquées)
    return "text", text


def fetch_content(
    url: str,
    headers: Optional[dict[str, str]] = None,
    timeout: float = 30.0,
    transport: Optional[httpx.BaseTransport] = None,
) -> FetchedContent:
    """GET l'URL et renvoie une specs parsée ou la page HTML brute."""
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json, application/yaml, text/html, */*"}
    request_headers.update(headers or {})
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, transport=transport) as client:
            response = client.get(url, headers=request_headers)
    except httpx.HTTPError as exc:
        raise FetchError(f"impossible de récupérer {url} : {exc}") from exc
    if response.status_code >= 400:
        raise FetchError(f"HTTP {response.status_code} sur {url}")
    kind, data = _parse_payload(response.text, response.headers.get("content-type", ""))
    return FetchedContent(
        url=str(response.url),
        kind=kind,
        data=data,
        content_type=response.headers.get("content-type", ""),
    )


FetchFn = Callable[[str], FetchedContent]


def make_fetcher(headers: Optional[dict[str, str]] = None) -> FetchFn:
    """Fabrique un callable `(url) -> FetchedContent` avec les headers d'auth."""

    def _fetch(url: str) -> FetchedContent:
        return fetch_content(url, headers=headers)

    return _fetch
