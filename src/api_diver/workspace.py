"""Workspace : la base de connaissance (sources, specs, cache, historique)."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import WorkspaceError
from .model import ApiSpec, RouteDiff, diff_routes
from .util import slugify

REGISTRY_NAME = "apidiver.json"
REGISTRY_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.registry: dict[str, Any] = {}
        self._load()

    # -- cycle de vie -------------------------------------------------------

    @classmethod
    def create(cls, path: Path) -> "Workspace":
        root = Path(path).resolve()
        registry_file = root / REGISTRY_NAME
        if registry_file.exists():
            raise WorkspaceError(f"un workspace existe déjà ici : {registry_file}")
        root.mkdir(parents=True, exist_ok=True)
        (root / "specs").mkdir(exist_ok=True)
        default_skill = slugify(root.name, fallback="mes-apis")
        registry = {
            "version": REGISTRY_VERSION,
            "skill_name": default_skill,
            "created_at": _now(),
            "sources": {},
        }
        ws = cls.__new__(cls)
        ws.root = root
        ws.registry = registry
        ws._dump()
        return ws

    @classmethod
    def find(cls, start: Path | None = None, explicit: Path | None = None) -> "Workspace":
        """Cherche apidiver.json en remontant depuis `start` (comme git)."""
        if explicit is not None:
            candidate = Path(explicit).resolve()
            if (candidate / REGISTRY_NAME).is_file():
                return cls(candidate)
            raise WorkspaceError(f"pas de workspace dans {candidate} (apidiver.json absent)")
        current = Path(start or Path.cwd()).resolve()
        for folder in [current, *current.parents]:
            if (folder / REGISTRY_NAME).is_file():
                return cls(folder)
        raise WorkspaceError(
            "aucun workspace trouvé : place-toi dans le projet ou crée-le avec `api-diver init`"
        )

    def _load(self) -> None:
        registry_file = self.root / REGISTRY_NAME
        if not registry_file.is_file():
            raise WorkspaceError(f"workspace invalide (pas de {REGISTRY_NAME}) : {self.root}")
        try:
            self.registry = json.loads(registry_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise WorkspaceError(f"registry illisible : {registry_file} ({exc})") from exc
        self.registry.setdefault("sources", {})

    def _dump(self) -> None:
        registry_file = self.root / REGISTRY_NAME
        registry_file.write_text(
            json.dumps(self.registry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    # -- entrées ------------------------------------------------------------

    @property
    def skill_name(self) -> str:
        return str(self.registry.get("skill_name") or "mes-apis")

    def set_skill_name(self, name: str) -> None:
        self.registry["skill_name"] = slugify(name, fallback=self.skill_name)
        self._dump()

    @property
    def sources(self) -> dict[str, dict]:
        return self.registry["sources"]

    def has(self, name: str) -> bool:
        return name in self.sources

    def require(self, name: str) -> dict:
        entry = self.sources.get(name)
        if entry is None:
            known = ", ".join(sorted(self.sources)) or "(vide)"
            raise WorkspaceError(f"API inconnue « {name} ». APIs connues : {known}")
        return entry

    def api_dir(self, name: str) -> Path:
        return self.root / "specs" / name

    def normalized_path(self, name: str) -> Path:
        return self.api_dir(name) / "normalized.json"

    def load_api(self, name: str) -> ApiSpec:
        path = self.normalized_path(name)
        if not path.is_file():
            raise WorkspaceError(f"spec normalisée absente : {path}")
        return ApiSpec.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def load_api_prev(self, name: str) -> ApiSpec | None:
        path = self.api_dir(name) / "normalized.prev.json"
        if not path.is_file():
            return None
        return ApiSpec.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def store_api(
        self,
        spec: ApiSpec,
        spec_urls: list[dict[str, str]],
        auth_headers: dict[str, str],
        inline_headers: list[str],
        raw_docs: list[tuple[str, dict]],
    ) -> RouteDiff:
        """Écrit une API (nouvelle ou mise à jour) et renvoie le diff routes."""
        name = spec.name
        if not name or not slugify(name, fallback="") == name:
            raise WorkspaceError(f"nom d'API invalide : {name!r} (slug attendu, ex: mon-api)")
        api_dir = self.api_dir(name)
        api_dir.mkdir(parents=True, exist_ok=True)
        (api_dir / "raw").mkdir(exist_ok=True)

        previous = None
        normalized_path = self.normalized_path(name)
        if normalized_path.is_file():
            previous = ApiSpec.from_dict(json.loads(normalized_path.read_text(encoding="utf-8")))
            shutil.copy2(normalized_path, api_dir / "normalized.prev.json")
            old_raw = api_dir / "raw.json"
            if old_raw.is_file():
                shutil.move(str(old_raw), api_dir / "raw.prev.json")

        diff = diff_routes(previous.routes if previous else [], spec.routes)

        normalized_path.write_text(
            json.dumps(spec.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        # cache brut par spec découverte (une par fichier, slug du label ou de l'URL)
        used: set[str] = set()
        for url, doc in raw_docs:
            label = ""
            for su in spec_urls:
                if su["url"] == url:
                    label = su.get("label", "")
            stem = slugify(label, fallback="") or slugify(
                url.rsplit("/", 1)[-1].split(".")[0] or "spec", fallback="spec"
            )
            unique = stem
            i = 2
            while unique in used:
                unique = f"{stem}-{i}"
                i += 1
            used.add(unique)
            (api_dir / "raw" / f"{unique}.json").write_text(
                json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

        entry = self.sources.get(name) or {"added_at": _now()}
        entry.update(
            {
                "source_url": spec.source_url,
                "spec_urls": spec_urls,
                "auth_headers": auth_headers,
                "inline_headers": inline_headers,
                "title": spec.title,
                "version": spec.version,
                "openapi_version": spec.openapi_version,
                "domains": [d.url for d in spec.domains],
                "groups": spec.groups,
                "route_count": len(spec.routes),
                "updated_at": _now(),
            }
        )
        self.sources[name] = entry
        self._dump()
        return diff

    def remove(self, name: str) -> None:
        self.require(name)
        del self.sources[name]
        api_dir = self.api_dir(name)
        if api_dir.exists():
            shutil.rmtree(api_dir)
        self._dump()
