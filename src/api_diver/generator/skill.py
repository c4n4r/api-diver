"""Assemblage du dossier skill : SKILL.md + arborescence par API."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..errors import GeneratorError
from ..model import ApiSpec
from ..util import slugify
from .routes_md import group_routes, render_index, render_tag_file
from .util import md_cell

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def build_frontmatter(skill_name: str, apis: list[ApiSpec]) -> str:
    if not NAME_RE.fullmatch(skill_name) or len(skill_name) > 64:
        raise GeneratorError(
            f"nom de skill invalide : {skill_name!r} "
            "(attendu : minuscules/chiffres/tirets, max 64, ex: api-diver)"
        )
    names = ", ".join(a.name for a in apis)
    description = (
        f"Cartographie de {len(apis)} API(s) : {names}. Pour chaque API : domaines "
        "(base URLs), groupes de routes, paramètres, payloads, réponses et exemples "
        "curl. Consulte ce skill pour connaître la façon exacte d'appeler une route "
        "de ces APIs avant de faire une requête."
    )
    if len(description) > 1024:
        description = description[:1021] + "..."
    return f"""---
name: {skill_name}
description: >
  {description}
---"""


def render_overview(api: ApiSpec) -> str:
    lines = [f"# {api.title}", ""]
    lines.append(f"- **API** : `{api.name}`")
    lines.append(f"- **Source** : {api.source_url}")
    lines.append(f"- **Version spec** : {api.openapi_version} · version API : {api.version or '?'}")
    routes_word = "route" if len(api.routes) == 1 else "routes"
    lines.append(f"- **{len(api.routes)} {routes_word}** réparties dans `routes/` (index : `routes/_index.md`)")

    if api.description:
        lines.append("")
        lines.append(f"> {md_cell(api.description, 500)}")

    lines.append("")
    lines.append("## Domaines (base URLs)")
    lines.append("")
    if api.domains:
        lines.append("| URL | Description |")
        lines.append("| --- | --- |")
        for i, domain in enumerate(api.domains):
            marker = " *(par défaut)*" if i == 0 else ""
            lines.append(f"| `{domain.url}`{marker} | {md_cell(domain.description, 120)} |")
    else:
        lines.append("Aucun domaine explicite : l'URL de base est relative, à compléter selon l'hébergement.")
    if len(api.domains) > 1:
        lines.append("")
        lines.append(
            "Plusieurs domaines disponibles : les exemples curl utilisent le domaine par défaut, "
            "remplace la base URL par celle voulue si besoin."
        )

    if api.groups:
        lines.append("")
        lines.append("## Groupes (specs découvertes derrière la source)")
        lines.append("")
        for group in api.groups:
            count = sum(1 for r in api.routes if group in r.tags)
            routes_word = "route" if count == 1 else "routes"
            lines.append(f"- **{group}** : {count} {routes_word}")
        spec_urls = "; ".join(
            f"{s.get('label') or s.get('url')} → {s.get('url')}" for s in api.spec_urls
        )
        if spec_urls:
            lines.append("")
            lines.append(f"Provenance : {spec_urls}")

    tag_counts = api.tag_counts()
    real_tags = {t: c for t, c in tag_counts.items() if t}
    if real_tags:
        lines.append("")
        lines.append("## Tags")
        lines.append("")
        lines.append(", ".join(f"`{t}` ({c})" for t, c in list(real_tags.items())[:25]))

    if api.security_schemes:
        lines.append("")
        lines.append("## Authentification")
        lines.append("")
        lines.append("| Schéma | Type | Où | Secrets (placeholder curl) |")
        lines.append("| --- | --- | --- | --- |")
        from ..util import env_name

        for scheme in api.security_schemes:
            if scheme.type == "apiKey":
                where = f"{scheme.location} « {scheme.resolved_param_name()} »"
            else:
                where = scheme.location or scheme.scheme or "—"
            if scheme.type == "http" and scheme.scheme == "bearer":
                secret = f"`${env_name(api.name, 'TOKEN')}`"
            elif scheme.type == "http" and scheme.scheme == "basic":
                secret = f"`${env_name(api.name, 'USER')}` / `${env_name(api.name, 'PASSWORD')}`"
            elif scheme.type == "apiKey":
                secret = f"`${env_name(api.name, 'API_KEY')}`"
            else:
                secret = "—"
            lines.append(
                f"| `{scheme.name}` | {scheme.type} | {where} | {secret} |"
            )
        lines.append("")
        lines.append(
            "Les exemples curl utilisent des placeholders `$NOM_API_…` : "
            "substitue les vraies valeurs (jamais de secret en dur)."
        )

    return "\n".join(lines) + "\n"


def render_skill_md(skill_name: str, apis: list[ApiSpec]) -> str:
    front = build_frontmatter(skill_name, apis)
    lines = [front, ""]
    lines.append("# Cartographie d'APIs")
    lines.append("")
    lines.append(
        "Ce skill référence toutes les routes des APIs ci-dessous. "
        "**Ne lis pas tous les fichiers** : procède par étapes."
    )
    lines.append("")
    lines.append("## Comment utiliser ce skill")
    lines.append("")
    lines.append("1. Repère l'API visée dans le tableau ci-dessous.")
    lines.append("2. Ouvre `apis/<api>/routes/_index.md` pour chercher la route (METHOD + chemin).")
    lines.append("3. Ouvre le fichier de tag indiqué en fin de ligne pour la fiche complète :")
    lines.append("   paramètres, payload, réponses attendues et exemple curl.")
    lines.append("4. Ouvre `apis/<api>/overview.md` pour les domaines (base URLs), l'authentification")
    lines.append("   et les conventions de l'API.")
    lines.append("")
    lines.append("## APIs")
    lines.append("")
    lines.append("| API | Titre | Domaines | Groupes | Routes |")
    lines.append("| --- | --- | --- | --- | --- |")
    for api in apis:
        domains = "<br>".join(md_cell(d.url, 70) for d in api.domains[:3]) or "—"
        if len(api.domains) > 3:
            domains += f"<br>… (+{len(api.domains) - 3})"
        groups = md_cell(", ".join(api.groups[:6]), 60) or "—"
        lines.append(f"| `{api.name}` | {md_cell(api.title, 60)} | {domains} | {groups} | {len(api.routes)} |")
    lines.append("")
    lines.append("## Conventions")
    lines.append("")
    lines.append(
        "- Les exemples curl utilisent des placeholders `$NOM_API_…` pour les secrets et les "
        "identifiants : substitue leurs valeurs au moment de l'appel."
    )
    lines.append(
        "- Certaines APIs exposent plusieurs domaines : la base URL par défaut figure en premier "
        "dans `overview.md`, les alternatives sont notées en commentaire des curls."
    )
    lines.append("- Les paramètres obligatoires sont marqués « requis : oui » ; le reste est optionnel.")
    return "\n".join(lines) + "\n"


def generate_skill(apis: list[ApiSpec], skill_name: str, out_dir: Path) -> list[Path]:
    """Écrit l'arborescence complète du skill dans out_dir (doit être vide ou nôtre)."""
    if not apis:
        raise GeneratorError("aucune API à générer : ajoute des sources avec `api-diver add`")
    out_dir = Path(out_dir)
    if out_dir.exists():
        if not (out_dir / "SKILL.md").is_file():
            raise GeneratorError(
                f"le dossier cible {out_dir} existe et ne semble pas être un skill api-diver "
                "(pas de SKILL.md) — choisis un autre chemin ou supprime-le"
            )
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    created: list[Path] = []

    skill_md = out_dir / "SKILL.md"
    skill_md.write_text(render_skill_md(skill_name, apis), encoding="utf-8")
    created.append(skill_md)

    for api in apis:
        api_dir = out_dir / "apis" / api.name
        routes_dir = api_dir / "routes"
        routes_dir.mkdir(parents=True)

        overview = api_dir / "overview.md"
        overview.write_text(render_overview(api), encoding="utf-8")
        created.append(overview)

        tag_files: dict[str, str] = {}
        groups = group_routes(api)
        used_names: set[str] = set()
        for tag in groups:
            base = slugify(tag, fallback="autres")
            file_name = base
            i = 2
            while file_name in used_names:
                file_name = f"{base}-{i}"
                i += 1
            used_names.add(file_name)
            tag_files[tag] = f"{file_name}.md"

        index = routes_dir / "_index.md"
        index.write_text(render_index(api, tag_files), encoding="utf-8")
        created.append(index)

        for tag, routes in groups.items():
            path = routes_dir / tag_files[tag]
            path.write_text(render_tag_file(api, tag, routes), encoding="utf-8")
            created.append(path)

    return created
