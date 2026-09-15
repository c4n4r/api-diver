"""Génération d'un exemple curl par route (placeholders $ENV pour les secrets)."""

from __future__ import annotations

import json
import re

from ..model import ApiSpec, Route
from ..util import env_name
from .util import example_from_schema

_PATH_PARAM_RE = re.compile(r"\{([^}/]+)\}")


def _placeholder(api_name: str, suffix: str) -> str:
    return "$" + env_name(api_name, suffix)


def _auth_args(route: Route, api: ApiSpec, prefix_placeholders: str) -> list[str]:
    """Args curl pour l'auth ; les commentaires (ex: oauth2) sont retournés à part."""
    schemes = {s.name: s for s in api.security_schemes}
    for requirement in route.security:
        for name in requirement:
            scheme = schemes.get(name)
            if scheme is None:
                continue
            if scheme.type == "apiKey" and scheme.location == "header":
                return [f'-H "{scheme.resolved_param_name()}: {_placeholder(api.name, "API_KEY")}"']
            if scheme.type == "http" and scheme.scheme == "bearer":
                return [f'-H "Authorization: Bearer {_placeholder(api.name, "TOKEN")}"']
            if scheme.type == "http" and scheme.scheme == "basic":
                return [
                    f'-u "{_placeholder(api.name, "USER")}:{_placeholder(api.name, "PASSWORD")}"'
                ]
            if scheme.type == "oauth2":
                return [f"# auth oauth2 « {scheme.name} » : fournis un token valide"]
            return []
    return []


def curl_for_route(route: Route, api: ApiSpec) -> str:
    base = ""
    if route.domain_urls:
        base = route.domain_urls[0]
    elif api.domains:
        base = api.domains[0].url

    path = _PATH_PARAM_RE.sub(
        lambda m: _placeholder(api.name, m.group(1)), route.path
    )
    url = (base.rstrip("/") + path) if base else path

    alternatives: list[str] = []
    if api.domains and base == api.domains[0].url:
        alternatives = [d.url for d in api.domains[1:]]
    if route.domain_urls and len(route.domain_urls) > 1:
        alternatives = route.domain_urls[1:]

    parts = [f'curl -X {route.method.upper()} "{url}"']
    auth_args = _auth_args(route, api, "")
    # les commentaires d'auth ne doivent pas couper la continuation « \ » du curl
    auth_comments = [arg for arg in auth_args if arg.startswith("#")]
    parts.extend(arg for arg in auth_args if not arg.startswith("#"))

    body_arg: str | None = None
    if route.request_body is not None:
        ordered = sorted(
            route.request_body.content_types.items(),
            key=lambda kv: 0 if "json" in kv[0] else 1,
        )
        for content_type, schema in ordered:
            if "json" in content_type:
                payload = json.dumps(
                    example_from_schema(schema), ensure_ascii=False, separators=(", ", ": ")
                )
                parts.append(f'-H "Content-Type: {content_type}"')
                body_arg = f"-d '{payload}'"
                break
            if "x-www-form-urlencoded" in content_type and schema.properties:
                fields = "&".join(
                    f"{name}={_placeholder(api.name, name)}"
                    for name in list(schema.properties)[:6]
                )
                parts.append(f'-H "Content-Type: {content_type}"')
                body_arg = f'-d "{fields}"'
                break

    form_params = [p for p in route.parameters if p.location == "formData"]
    if body_arg is None and form_params:
        fields = "&".join(
            f"{p.name}={_placeholder(api.name, p.name)}" for p in form_params[:6]
        )
        body_arg = f'-d "{fields}"'
    if body_arg is not None:
        parts.append(body_arg)

    required_query = [p for p in route.parameters if p.location == "query" and p.required]
    if required_query:
        parts.insert(1, "-G")
        for param in required_query:
            parts.append(
                f'--data-urlencode "{param.name}={_placeholder(api.name, param.name)}"'
            )

    lines = " \\\n  ".join(parts)
    if auth_comments:
        lines += "\n" + "\n".join(auth_comments)
    header = ""
    if alternatives:
        header = f"# autres domaines possibles : {', '.join(alternatives)}\n"
    return header + lines
