"""Rendu markdown des routes : fiche par route, fichier par tag, index par API."""

from __future__ import annotations

from ..model import ApiSpec, Route
from ..util import env_prefix
from .curl import curl_for_route
from .util import (
    code_span,
    flatten_schema,
    json_example,
    md_cell,
    param_type_label,
    pick_body,
    pick_response,
    schema_type_label,
)

_REQUIRED_FLAG = {"path", "body"}


def _auth_text(route: Route, api: ApiSpec) -> str:
    schemes = {s.name: s for s in api.security_schemes}
    labels = []
    for requirement in route.security:
        for name in requirement:
            scheme = schemes.get(name)
            if scheme is None:
                continue
            if scheme.type == "http" and scheme.scheme:
                where = f"header {scheme.scheme}" if scheme.scheme == "bearer" else scheme.scheme
                labels.append(f"{scheme.type} {where} ({scheme.name})")
            elif scheme.type == "apiKey":
                labels.append(f"apiKey {scheme.location} « {scheme.resolved_param_name()} »")
            else:
                labels.append(f"{scheme.type} ({scheme.name})")
    if not labels:
        return "aucune authentification requise" if api.security_schemes else "publique"
    seen: list[str] = []
    for label in labels:
        if label not in seen:
            seen.append(label)
    return "ou ".join(seen)


def render_route(route: Route, api: ApiSpec) -> str:
    lines: list[str] = []
    method = route.method.upper()
    title = route.summary or route.operation_id or route.path
    badge = " ⚠️ *dépréciée*" if route.deprecated else ""
    lines.append(f"### {method} `{route.path}` — {md_cell(title, 120)}{badge}")
    lines.append("")

    meta: list[str] = []
    if route.operation_id:
        meta.append(f"operationId : {code_span(route.operation_id)}")
    if route.domain_urls:
        meta.append("domaines spécifiques : " + ", ".join(code_span(u) for u in route.domain_urls))
    if meta:
        lines.append("> " + " · ".join(meta))
        lines.append("")

    lines.append(f"**Auth** : {_auth_text(route, api)}")
    lines.append("")

    if route.description:
        lines.append(route.description)
        lines.append("")

    path_query = [p for p in route.parameters if p.location in ("path", "query", "header", "cookie")]
    if path_query:
        lines.append("**Paramètres**")
        lines.append("")
        lines.append("| Nom | Dans | Requis | Type | Description |")
        lines.append("| --- | --- | --- | --- | --- |")
        for param in path_query:
            required = "oui" if param.required or param.location in _REQUIRED_FLAG else "non"
            default = ""
            if param.default is not None:
                default = f" — défaut : {md_cell(param.default, 60)}"
            description = md_cell(param.description, 200) + default
            lines.append(
                f"| {code_span(param.name)} | {param.location} | {required} "
                f"| {md_cell(param_type_label(param), 60)} | {description} |"
            )
        lines.append("")

    body = pick_body(route)
    if body is not None:
        content_type, schema = body
        name = schema.ref_name or ""
        label = f" — schéma : {code_span(name)}" if name else ""
        lines.append(f"**Body** ({content_type}){label}")
        lines.append("")
        rows = flatten_schema(schema)
        if rows:
            lines.append("| Propriété | Type | Requis | Description |")
            lines.append("| --- | --- | --- | --- |")
            for prop_path, prop_schema, required in rows:
                lines.append(
                    f"| {code_span(prop_path)} | {md_cell(schema_type_label(prop_schema), 60)} "
                    f"| {'oui' if required else 'non'} | {md_cell(prop_schema.description, 200)} |"
                )
            lines.append("")
        lines.append("Exemple de payload :")
        lines.append("```json")
        lines.append(json_example(schema))
        lines.append("```")
        lines.append("")

    form_params = [p for p in route.parameters if p.location == "formData"]
    if form_params:
        lines.append("**Champs de formulaire**")
        lines.append("")
        lines.append("| Nom | Requis | Type | Description |")
        lines.append("| --- | --- | --- | --- |")
        for param in form_params:
            lines.append(
                f"| {code_span(param.name)} | {'oui' if param.required else 'non'} "
                f"| {md_cell(param_type_label(param), 60)} | {md_cell(param.description, 200)} |"
            )
        lines.append("")

    if route.responses:
        lines.append("**Réponses**")
        lines.append("")
        lines.append("| Code | Description | Corps retourné |")
        lines.append("| --- | --- | --- |")
        for response in route.responses:
            bodies = []
            for content_type, schema in response.content_types.items():
                short = content_type.split(";")[0]
                name = schema.ref_name or schema_type_label(schema)
                bodies.append(f"{short} : {code_span(name)}")
            corpus = "<br>".join(bodies) if bodies else "—"
            lines.append(
                f"| {md_cell(response.status, 12)} | {md_cell(response.description, 150)} | {corpus} |"
            )
        lines.append("")

    detail = pick_response(route)
    if detail is not None:
        response, content_type, schema = detail
        name = schema.ref_name or (schema_type_label(schema) if schema.type == "array" else "")
        label = f" — schéma : {code_span(name)}" if name else ""
        lines.append(f"**Réponse {response.status}** ({content_type}){label}")
        lines.append("")
        rows = flatten_schema(schema)
        if rows:
            lines.append("| Propriété | Type | Requis | Description |")
            lines.append("| --- | --- | --- | --- |")
            for prop_path, prop_schema, required in rows:
                lines.append(
                    f"| {code_span(prop_path)} | {md_cell(schema_type_label(prop_schema), 60)} "
                    f"| {'oui' if required else 'non'} | {md_cell(prop_schema.description, 200)} |"
                )
            lines.append("")
        lines.append("Exemple de réponse :")
        lines.append("```json")
        lines.append(json_example(schema))
        lines.append("```")
        lines.append("")

    lines.append("**Exemple curl**")
    lines.append("")
    lines.append("```bash")
    lines.append(curl_for_route(route, api))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def group_routes(api: ApiSpec) -> dict[str, list[Route]]:
    """Regroupe les routes par tag (les groupes de specs sont des tags)."""
    groups: dict[str, list[Route]] = {}
    for route in api.routes:
        tags = route.tags or [""]
        for tag in tags:
            groups.setdefault(tag, []).append(route)
    return dict(sorted(groups.items(), key=lambda kv: (kv[0] == "", kv[0])))


def render_tag_file(api: ApiSpec, tag: str, routes: list[Route]) -> str:
    title = tag if tag else "Autres routes"
    lines = [f"# {title}", ""]
    if tag in api.groups:
        lines.append(f"*Groupe de la spec « {tag} » — source : {api.source_url}*")
        lines.append("")
    for i, route in enumerate(routes):
        if i:
            lines.append("---")
            lines.append("")
        lines.append(render_route(route, api))
    return "\n".join(lines).rstrip() + "\n"


def render_index(api: ApiSpec, tag_files: dict[str, str]) -> str:
    lines = [f"# Index des routes — {api.title}", ""]
    lines.append(
        f"API `{api.name}` · {len(api.routes)} routes · préfixe des secrets : "
        f"`${env_prefix(api.name)}_…`"
    )
    lines.append("")
    lines.append("| Méthode | Chemin | Résumé | Tags | Fichier |")
    lines.append("| --- | --- | --- | --- | --- |")
    order = {"get": 0, "post": 1, "put": 2, "patch": 3, "delete": 4}
    for route in sorted(api.routes, key=lambda r: (r.path, order.get(r.method, 9))):
        tag = (route.tags or [""])[0]
        file_name = tag_files.get(tag, tag_files.get("", "autres.md"))
        summary = route.summary or route.operation_id or ""
        if route.deprecated:
            summary = "⚠️ " + summary
        lines.append(
            f"| **{route.method.upper()}** | `{route.path}` | {md_cell(summary, 90)} "
            f"| {md_cell(', '.join(route.tags), 50)} | {file_name} |"
        )
    lines.append("")
    return "\n".join(lines)
