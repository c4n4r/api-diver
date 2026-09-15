"""CLI api-diver : init, add, list, info, update, remove, diff, build."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, List, Optional

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Column, Table

from . import __version__
from .crawler import CrawlProgress, CrawlResult, crawl_source
from .errors import ApiDiverError
from .fetcher import FetchedContent, build_headers, make_fetcher, split_header_arg
from .generator.skill import generate_skill
from .util import slugify
from .workspace import Workspace

app = typer.Typer(
    name="api-diver",
    help="Cartographie des swaggers/OpenAPI (multi-domaines, multi-APIs) en skills agents.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

WorkspaceOpt = Annotated[
    Optional[Path],
    typer.Option(
        "--workspace",
        "-w",
        help="Chemin du workspace (sinon recherché en remontant depuis le dossier courant).",
    ),
]
HeaderOpt = Annotated[
    Optional[List[str]],
    typer.Option(
        "--header",
        "-H",
        help="Header d'auth pour le fetch, ex: « Authorization: {$MON_TOKEN} ». Répéable.",
    ),
]


def _fail(exc: ApiDiverError) -> None:
    err_console.print(f"[red]Erreur :[/red] {exc}")
    raise typer.Exit(code=1)


def _workspace(explicit: Optional[Path]) -> Workspace:
    try:
        return Workspace.find(explicit=explicit)
    except ApiDiverError as exc:
        _fail(exc)
        raise  # inatteignable


def _crawl_with_progress(url: str, headers: dict[str, str] | None, name: str | None) -> CrawlResult:
    """Crawl une source en affichant une ligne de progression (réseau puis analyse).

    La progression part sur stderr et se désactive hors terminal (tests, CI, pipe) ;
    elle disparaît une fois terminée pour laisser la place au résumé.
    """
    progress = Progress(
        SpinnerColumn(),
        TextColumn(
            "[progress.description]{task.description}",
            table_column=Column(overflow="ellipsis", no_wrap=True),
        ),
        BarColumn(bar_width=None),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=err_console,
        transient=True,
        disable=not err_console.is_terminal,
    )
    fetch = make_fetcher(headers)
    with progress:
        task = progress.add_task(f"Récupération : {url}", total=None)
        bar_started = False

        def wrapped_fetch(target: str) -> FetchedContent:
            # tant qu'aucune barre n'a démarré, montrer l'URL en cours (page source, sondes de découverte)
            if not bar_started:
                progress.update(task, description=f"Récupération : {target}")
            return fetch(target)

        def on_progress(event: CrawlProgress) -> None:
            nonlocal bar_started
            bar_started = True
            label = "Téléchargement des specs" if event.phase == "download" else "Analyse des specs"
            progress.update(
                task,
                description=f"{label} — {event.label}",
                total=event.total,
                completed=event.done,
            )

        return crawl_source(
            url, headers=headers, name=name, fetch_fn=wrapped_fetch, on_progress=on_progress
        )


def _store(ws: Workspace, url: str, name: Optional[str], header_args: Optional[List[str]]) -> None:
    """Crawl une source puis l'enregistre (utilisé par add et update)."""
    stored, inline = {}, []
    if name and ws.has(name):
        entry = ws.require(name)
        stored = dict(entry.get("auth_headers") or {})
        inline = list(entry.get("inline_headers") or [])
        url = entry["source_url"]
        missing = [
            key
            for key in entry.get("inline_headers") or []
            if key not in {split_header_arg(raw)[0] for raw in header_args or []}
        ]
        if missing:
            listed = ", ".join(sorted(set(missing)))
            console.print(
                f"[yellow]⚠[/yellow] headers « {listed} » avaient été fournis en valeur brute : "
                "repasse-les via --header ou exporte API_DIVER_HEADERS si le fetch échoue."
            )
    for raw in header_args or []:
        key, value = split_header_arg(raw)
        if value.strip().startswith("{$"):
            stored[key] = "env:" + value.strip()[2:-1]
        else:
            inline.append(key)
    try:
        headers = build_headers(stored=stored, header_args=header_args)
        result = _crawl_with_progress(url, headers=headers, name=name)
    except ApiDiverError as exc:
        _fail(exc)
        raise

    api = result.spec
    if ws.has(api.name) and name != api.name:
        err_console.print(
            f"[red]Erreur :[/red] une API « {api.name} » existe déjà ; "
            "utilise `api-diver update " + api.name + "` ou passe --name différent."
        )
        raise typer.Exit(code=1)

    diff = ws.store_api(
        spec=api,
        spec_urls=result.spec_urls,
        auth_headers=stored,
        inline_headers=inline,
        raw_docs=result.raw_docs,
    )

    specs_count = len(result.spec_urls)
    groups = ", ".join(g for g in api.groups) if api.groups else f"{specs_count} spec(s)"
    console.print(
        f"[green]✔[/green] [bold]{api.name}[/bold] — {api.title} "
        f"({len(api.routes)} routes, {len(api.domains)} domaine(s), {groups})"
    )
    for note in result.notes:
        console.print(f"  [dim]ℹ {note}[/dim]")
    for warning in result.warnings:
        console.print(f"  [yellow]⚠[/yellow] {warning}")
    if not diff.is_empty:
        console.print(f"  changements : {diff.summary()}")
    if inline:
        listed = ", ".join(sorted(set(inline)))
        console.print(
            f"  [dim]headers « {listed} » fournis en valeur brute : non stockés, "
            "repasse-les à `update` ou utilise la forme {$VAR}.[/dim]"
        )


@app.command()
def init(
    path: Annotated[Path, typer.Argument(help="Dossier du workspace (défaut : courant).")] = Path("."),
    skill_name: Annotated[Optional[str], typer.Option("--skill-name", help="Nom du skill généré.")] = None,
) -> None:
    """Crée un workspace (base de connaissance) dans le dossier donné."""
    try:
        ws = Workspace.create(path)
        if skill_name:
            ws.set_skill_name(skill_name)
    except ApiDiverError as exc:
        _fail(exc)
        raise
    console.print(f"[green]✔[/green] workspace créé : {ws.root}")
    console.print(f"  skill généré sous le nom : [bold]{ws.skill_name}[/bold]")
    console.print("  ajoute une API : [bold]api-diver add <url-swagger>[/bold]")


@app.command()
def add(
    url: Annotated[str, typer.Argument(help="URL de la spec ou de la page swagger-ui.")],
    name: Annotated[Optional[str], typer.Option("--name", "-n", help="Nom (slug) de l'API.")] = None,
    header: HeaderOpt = None,
    workspace: WorkspaceOpt = None,
) -> None:
    """Crawl une source (découverte automatique des specs) et l'ajoute au workspace."""
    ws = _workspace(workspace)
    if name:
        name = slugify(name, fallback="")
        if not name:
            _fail(ApiDiverError("nom invalide après nettoyage (slug attendu)"))
            raise
        if ws.has(name):
            _fail(ApiDiverError(f"« {name} » existe déjà : utilise `api-diver update {name}`"))
            raise
    _store(ws, url, name, header)


@app.command()
def update(
    name: Annotated[Optional[str], typer.Argument(help="API à mettre à jour (défaut : toutes).")] = None,
    header: HeaderOpt = None,
    workspace: WorkspaceOpt = None,
) -> None:
    """Re-crawl les sources : rediscovery + refresh des routes, avec résumé du diff."""
    ws = _workspace(workspace)
    targets = [name] if name else sorted(ws.sources)
    if not targets:
        console.print("Aucune API dans le workspace : commence par `api-diver add <url>`.")
        return
    for index, api_name in enumerate(targets, start=1):
        entry = ws.require(api_name)
        if len(targets) > 1:
            console.print(f"[dim]Mise à jour {index}/{len(targets)} : {api_name}…[/dim]")
        _store(ws, entry["source_url"], api_name, header)


@app.command("list")
def list_(workspace: WorkspaceOpt = None) -> None:
    """Liste les APIs du workspace (domaines, groupes, routes)."""
    ws = _workspace(workspace)
    if not ws.sources:
        console.print("Workspace vide : ajoute une source avec `api-diver add <url>`.")
        return
    table = Table(title=f"APIs du workspace ({ws.root})")
    table.add_column("API", style="bold cyan", overflow="fold")
    table.add_column("Spec", justify="center")
    table.add_column("Routes", justify="right")
    table.add_column("Domaines", overflow="fold")
    table.add_column("Groupes", overflow="fold")
    for api_name, entry in sorted(ws.sources.items()):
        domains = entry.get("domains", [])
        domain_cell = domains[0] if domains else "—"
        if len(domains) > 1:
            domain_cell += f" (+{len(domains) - 1})"
        groups = entry.get("groups", [])
        group_cell = ", ".join(groups[:3]) if groups else "—"
        if len(groups) > 3:
            group_cell += f" (+{len(groups) - 3})"
        table.add_row(
            api_name,
            entry.get("openapi_version", ""),
            str(entry.get("route_count", 0)),
            domain_cell,
            group_cell,
        )
    console.print(table)


@app.command()
def info(
    name: Annotated[str, typer.Argument(help="Nom de l'API.")],
    workspace: WorkspaceOpt = None,
) -> None:
    """Détail d'une API : source, specs découvertes, domaines, auth."""
    ws = _workspace(workspace)
    entry = ws.require(name)
    console.print(f"[bold cyan]{name}[/bold cyan] — {entry.get('title', '')}")
    console.print(f"  source   : {entry.get('source_url')}")
    console.print(f"  spec     : {entry.get('openapi_version')} · routes : {entry.get('route_count')}")
    console.print(f"  ajoutée  : {entry.get('added_at')} · MAJ : {entry.get('updated_at')}")
    for domain in entry.get("domains", []):
        console.print(f"  domaine  : {domain}")
    for spec in entry.get("spec_urls", []):
        label = f" ({spec['label']})" if spec.get("label") else ""
        console.print(f"  spec     : {spec['url']}{label}")
    auth = entry.get("auth_headers") or {}
    for key, ref in auth.items():
        console.print(f"  auth     : {key} = {ref}")
    if entry.get("inline_headers"):
        console.print(f"  auth     : {', '.join(entry['inline_headers'])} (valeurs brutes, non stockées)")


@app.command()
def remove(
    name: Annotated[str, typer.Argument(help="Nom de l'API à supprimer.")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Sans confirmation.")] = False,
    workspace: WorkspaceOpt = None,
) -> None:
    """Supprime une API du workspace (registry + cache specs)."""
    ws = _workspace(workspace)
    ws.require(name)
    if not force:
        confirm = typer.confirm(f"Supprimer « {name} » (specs et cache inclus) ?")
        if not confirm:
            console.print("Annulé.")
            return
    ws.remove(name)
    console.print(f"[green]✔[/green] « {name} » supprimée.")


@app.command()
def diff(
    name: Annotated[str, typer.Argument(help="Nom de l'API.")],
    workspace: WorkspaceOpt = None,
) -> None:
    """Affiche les changements de routes depuis la version précédente."""
    from .model import diff_routes

    ws = _workspace(workspace)
    current = ws.load_api(name)
    previous = ws.load_api_prev(name)
    if previous is None:
        console.print("Pas de version précédente (jamais mise à jour depuis l'ajout).")
        return
    changes = diff_routes(previous.routes, current.routes)
    if changes.is_empty:
        console.print("Aucun changement de routes depuis la version précédente.")
        return
    table = Table(title=f"Diff {name} — {changes.summary()}")
    table.add_column("Changement", style="bold")
    table.add_column("Routes")
    for label, items in (("ajoutées", changes.added), ("supprimées", changes.removed), ("modifiées", changes.modified)):
        if items:
            shown = "\n".join(items[:20]) + (f"\n… (+{len(items) - 20})" if len(items) > 20 else "")
            table.add_row(label, shown)
    console.print(table)


_TARGETS = {
    "agents": (Path(".agents/skills"), Path.home() / ".agents/skills"),
    "opencode": (Path(".opencode/skills"), Path.home() / ".config/opencode/skills"),
    "vibe": (Path(".vibe/skills"), Path.home() / ".vibe/skills"),
    "claude": (Path(".claude/skills"), Path.home() / ".claude/skills"),
    "codex": (Path(".agents/skills"), Path.home() / ".agents/skills"),  # dossier standard .agents, lu nativement par Codex >= 0.95
    "copilot": (Path(".github/skills"), Path.home() / ".copilot/skills"),
}


@app.command()
def build(
    name: Annotated[Optional[str], typer.Option("--name", "-n", help="Nom du skill (défaut : celui du workspace).")] = None,
    api: Annotated[Optional[str], typer.Option("--api", help="Limiter à une seule API du workspace.")] = None,
    target: Annotated[str, typer.Option("--target", help=" | ".join(_TARGETS))] = "agents",
    out: Annotated[Optional[Path], typer.Option("--out", "-o", help="Dossier de sortie (défaut : ./<skill>).")] = None,
    install: Annotated[bool, typer.Option("--install", help="Copier le skill vers la cible choisie.")] = False,
    global_: Annotated[bool, typer.Option("--global", help="Installation niveau utilisateur, pas projet.")] = False,
    workspace: WorkspaceOpt = None,
) -> None:
    """Génère le dossier skill (SKILL.md + références) depuis le workspace."""
    if target not in _TARGETS:
        expected = ", ".join(list(_TARGETS)[:-1]) + " ou " + list(_TARGETS)[-1]
        _fail(ApiDiverError(f"cible inconnue « {target} » : attends {expected}"))
        raise
    ws = _workspace(workspace)
    if api:
        specs = [ws.load_api(api)]
        default_skill = slugify(api, fallback="api")
    else:
        specs = [ws.load_api(n) for n in sorted(ws.sources)]
        default_skill = ws.skill_name
    skill_name = slugify(name, fallback=default_skill) if name else default_skill

    out_dir = Path(out) if out else Path.cwd() / skill_name
    try:
        created = generate_skill(specs, skill_name, out_dir)
    except ApiDiverError as exc:
        _fail(exc)
        raise

    console.print(f"[green]✔[/green] skill [bold]{skill_name}[/bold] généré : {out_dir}")
    console.print(f"  {len(created)} fichiers · {len(specs)} API(s) · {sum(len(s.routes) for s in specs)} routes")

    if install:
        import shutil

        base = _TARGETS[target][1 if global_ else 0]
        destination = base / skill_name
        if destination.exists():
            if not (destination / "SKILL.md").is_file():
                _fail(ApiDiverError(f"refus d'écraser {destination} (pas un skill)"))
                raise
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(out_dir, destination)
        console.print(f"[green]✔[/green] installé : {destination}")
        hints = {
            "agents": "visible par OpenCode et Mistral Vibe (dossier .agents partagé)",
            "opencode": "visible par OpenCode",
            "vibe": "visible par Mistral Vibe",
            "claude": "visible par Claude Code",
            "codex": "visible par Codex (dossier .agents partagé)",
            "copilot": "visible par GitHub Copilot (VS Code, CLI, coding agent)",
        }
        console.print(f"  [dim]{hints[target]}[/dim]")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"api-diver {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option("--version", "-V", is_eager=True, callback=_version_callback, help="Version d'api-diver."),
    ] = False,
) -> None:
    """Cartographie des swaggers/OpenAPI en skills agents."""


def main() -> None:
    app()


if __name__ == "__main__":
    main()
