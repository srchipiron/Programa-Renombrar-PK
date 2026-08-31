"""Per-project settings: one corridor, one set of rules.

AEROSCAN flies several corridors for different clients, and each one carries
its own logic: chainage origin (Torre Pacheco runs PK-18+653→36+400, Lorca-Pulpí
400+500→431+834, Pulpí-Vera 500+000→525+700), its own trace KML, its own
landfills (five in Torre Pacheco, none in the other two), its own viaduct PK
list, threshold and filename suffix.

All of that used to live in a single global ``config.json``, so switching
corridor meant editing seven fields by hand — including a 29-entry list. Worse,
forgetting to do it failed *silently*: landfills 200 km away never capture a
photo and viaduct PKs of a different chainage never match, so the run looked
clean while ``ensure_work_folders`` created one client's landfill folders
inside another client's delivery.

A :class:`Project` bundles those rules. Definitions live in local JSON files —
never inside the client folders on the share, which the app must not write to,
and which would make the project list depend on the network being up. ``root``
is used only to *recognise* which corridor a chosen folder belongs to.
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Written by :meth:`ProjectStore.save`; the suffix identifies project files.
PROJECT_SUFFIX = ".json"


def slugify(name: str) -> str:
    """Filesystem-safe stem for a project name (``Lorca-Pulpí`` → ``lorca-pulpi``)."""
    normalised = unicodedata.normalize("NFKD", name or "")
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug or "proyecto"


@dataclass
class Project:
    """Everything that changes when the operator switches corridor."""

    name: str
    #: Client folder on the share. Only ever read/compared, never written to.
    root: str = ""
    kml: str = ""
    #: Extra landmark files (``Vertederos.kml``); merged on top of the trace.
    landmark_kmls: List[str] = field(default_factory=list)
    extra_landmarks: List[Dict[str, Any]] = field(default_factory=list)
    landmark_groups: List[Dict[str, Any]] = field(default_factory=list)
    landmark_capture_radius: float = 450.0
    landmark_threshold: float = 450.0
    landmark_cluster_radius: float = 500.0
    landmark_split_ratio: float = 0.45
    viaduct_pks: List[str] = field(default_factory=list)
    threshold: float = 30.0
    #: Filename suffix/template, e.g. ``[PK]-AGO26``.
    suffix: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Project":
        """Build a project from JSON, ignoring keys this version doesn't know."""
        fields = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in (data or {}).items() if k in fields}
        clean["name"] = str(clean.get("name") or "").strip() or "Proyecto"
        for key in ("landmark_kmls", "viaduct_pks"):
            clean[key] = [str(v).strip() for v in (clean.get(key) or []) if str(v).strip()]
        for key in ("extra_landmarks", "landmark_groups"):
            clean[key] = [v for v in (clean.get(key) or []) if isinstance(v, dict)]
        for key in (
            "landmark_capture_radius",
            "landmark_threshold",
            "landmark_cluster_radius",
            "landmark_split_ratio",
            "threshold",
        ):
            if key in clean:
                try:
                    clean[key] = float(clean[key])
                except (TypeError, ValueError):
                    clean.pop(key)
        return cls(**clean)

    def contains(self, path: str) -> bool:
        """True when ``path`` lives under this project's root."""
        return _is_within(path, self.root)


def _normcase(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _is_within(path: str, root: str) -> bool:
    """Whether ``path`` is ``root`` or sits below it.

    Compares normalised absolute paths instead of prefixes so that
    ``…/TRAZA PULPI-VERA-2`` is not read as being inside ``…/TRAZA PULPI-VERA``.
    UNC paths (``//server/share/…``) work because ``os.path`` handles them.
    """
    if not path or not root:
        return False
    try:
        target = Path(_normcase(path))
        base = Path(_normcase(root))
    except (OSError, ValueError):
        return False
    return target == base or base in target.parents


class ProjectStore:
    """Reads and writes one JSON per project in a local directory."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    # -- reading -------------------------------------------------------
    def load_all(self) -> List[Project]:
        """Every readable project, sorted by name. Never raises."""
        projects: List[Project] = []
        try:
            entries = sorted(self.directory.glob(f"*{PROJECT_SUFFIX}"))
        except OSError as exc:
            logger.warning("No se pudo listar %s: %s", self.directory, exc)
            return projects
        for path in entries:
            project = self._load_one(path)
            if project is not None:
                projects.append(project)
        projects.sort(key=lambda p: p.name.casefold())
        return projects

    def _load_one(self, path: Path) -> Optional[Project]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Proyecto ilegible %s: %s", path.name, exc)
            return None
        if not isinstance(data, dict):
            logger.warning("Proyecto ignorado (no es un objeto): %s", path.name)
            return None
        try:
            return Project.from_dict(data)
        except TypeError as exc:  # pragma: no cover - defensive
            logger.warning("Proyecto ignorado %s: %s", path.name, exc)
            return None

    def find(self, name: str) -> Optional[Project]:
        key = (name or "").strip().casefold()
        if not key:
            return None
        for project in self.load_all():
            if project.name.casefold() == key:
                return project
        return None

    def match_for_path(self, path: str) -> Optional[Project]:
        """Project whose root contains ``path``.

        The delivery tree already encodes the corridor
        (``…/CLIENTES/<obra>/<año>/<mes>/``), so choosing a folder is enough to
        know which rules apply. The deepest root wins, so a project nested
        inside another one is preferred.
        """
        if not path:
            return None
        matches = [p for p in self.load_all() if p.contains(path)]
        if not matches:
            return None
        return max(matches, key=lambda p: len(_normcase(p.root)))

    # -- writing -------------------------------------------------------
    def path_for(self, project: Project) -> Path:
        return self.directory / f"{slugify(project.name)}{PROJECT_SUFFIX}"

    def save(self, project: Project) -> Path:
        """Persist ``project``; the file name derives from its name."""
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(project)
        payload = json.dumps(project.to_dict(), indent=2, ensure_ascii=False)
        tmp = path.with_suffix(path.suffix + ".__tmp__")
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise
        logger.info("Proyecto guardado en %s", path)
        return path

    def delete(self, name: str) -> bool:
        project = self.find(name)
        if project is None:
            return False
        try:
            self.path_for(project).unlink()
        except OSError as exc:
            logger.warning("No se pudo borrar el proyecto %s: %s", name, exc)
            return False
        return True


#: Folder that groups one directory per client in the production share. When a
#: chosen path walks through it, the next segment names the corridor.
_CLIENT_ROOT_SEGMENT = "clientes"


def guess_project_root(*paths: str) -> Optional[tuple]:
    """Infer ``(root, name)`` for a corridor from any known path.

    The delivery tree is ``…/CLIENTES/<obra>/<año>/<mes>/…``, so the segment
    right after ``CLIENTES`` both names the corridor and bounds it. Falls back
    to the parent folder of the first usable path, which keeps this working for
    trees that are laid out differently.
    """
    for path in paths:
        if not path:
            continue
        parts = Path(os.path.normpath(str(path))).parts
        for index, part in enumerate(parts[:-1]):
            if part.casefold() == _CLIENT_ROOT_SEGMENT:
                name = parts[index + 1]
                return str(Path(*parts[: index + 2])), name
    for path in paths:
        if not path:
            continue
        parent = Path(os.path.normpath(str(path)))
        parent = parent if parent.is_dir() else parent.parent
        if parent.name:
            return str(parent), parent.name
    return None


def project_from_config(config: Any, *, name: str = "") -> Project:
    """Snapshot the current global settings as a project definition."""
    guessed = guess_project_root(
        getattr(config, "last_folder", ""), getattr(config, "last_kml", "")
    )
    root, guessed_name = guessed if guessed else ("", "")
    return Project(
        name=(name or guessed_name or "Proyecto"),
        root=root,
        kml=getattr(config, "last_kml", "") or "",
        landmark_kmls=list(getattr(config, "landmark_kmls", []) or []),
        extra_landmarks=list(getattr(config, "extra_landmarks", []) or []),
        landmark_groups=list(getattr(config, "landmark_groups", []) or []),
        landmark_capture_radius=float(getattr(config, "landmark_capture_radius", 450.0)),
        landmark_threshold=float(getattr(config, "landmark_threshold", 450.0)),
        landmark_cluster_radius=float(getattr(config, "landmark_cluster_radius", 500.0)),
        landmark_split_ratio=float(getattr(config, "landmark_split_ratio", 0.45)),
        viaduct_pks=list(getattr(config, "viaduct_pks", []) or []),
        threshold=float(getattr(config, "threshold", 30.0)),
        suffix=getattr(config, "last_suffix", "") or "",
    )


def bootstrap_from_config(store: ProjectStore, config: Any) -> Optional[Project]:
    """Seed the first project from the settings already in use.

    Operators upgrading from a single global config would otherwise open the
    selector and find it empty, with their corridor's rules stranded in
    ``config.json``. Only runs when no project exists and there is something
    worth keeping (a trace).
    """
    if store.load_all():
        return None
    if not getattr(config, "last_kml", ""):
        return None
    project = project_from_config(config)
    try:
        store.save(project)
    except OSError as exc:
        logger.warning("No se pudo crear el proyecto inicial: %s", exc)
        return None
    logger.info("Proyecto inicial creado desde la configuración: %s", project.name)
    return project
