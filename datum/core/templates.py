"""Drawing templates.

A template is not a special kind of file.  It is an ordinary ``.ddat``
sitting in a folder called Templates, and starting a drawing from one
copies it and forgets where it came from.  That is the whole mechanism, and
it means anything you can draw you can make a template of - no separate
editor, no second file format, and a template you can open and check.

Templates live in the active project's folder, so a project can carry its
own title block; the ones shipped with the application are the fallback
when a project has none of its own.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import List, Optional

from . import drawing as dwg
from . import fileformat

FOLDER = "Templates"


@dataclass
class Template:
    """One template file, and where it came from."""

    name: str
    path: str
    builtin: bool = False

    @property
    def label(self) -> str:
        return "%s%s" % (self.name, "   (shipped)" if self.builtin else "")


def builtin_folder() -> str:
    """Where the templates that ship with the application live."""
    return os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "templates")


def project_folder(project_dir: str) -> str:
    return os.path.join(project_dir, FOLDER) if project_dir else ""


def default_folder() -> str:
    """Where templates are kept when Application Options names no folder:
    the user's Documents, as Inventor keeps its own.  DATUM_TEMPLATES_DIR
    moves it, so tests never write into somebody's Documents."""
    forced = os.environ.get("DATUM_TEMPLATES_DIR")
    if forced:
        return forced
    return os.path.join(os.path.expanduser("~"), "Documents", "InventCraft",
                        "Templates")


def shared_folder() -> str:
    """The Templates folder: the one set in Application Options, Inventor's
    way, or the default one, filled with the standard templates the
    first time it is asked for."""
    try:
        from . import prefs
        folder = prefs.prefs().templates_folder
    except Exception:
        folder = ""
    if folder and os.path.isdir(folder):
        return folder
    folder = default_folder()
    try:
        seed(folder)
    except Exception:
        return folder if os.path.isdir(folder) else ""
    return folder


# The standard templates: a part and an assembly in millimetres and in
# inches, as Inventor ships Standard (mm) and Standard (in), and a drawing
# for each: ISO on A3, and ANSI on B, the inch sheet nearest A3.
STANDARD_PARTS = (("Standard (mm)", "mm"), ("Standard (in)", "in"))
STANDARD_DRAWINGS = (("ISO (mm)", "A3", "ISO", "mm"),
                     ("ANSI (in)", "Tabloid", "ANSI", "in"))


def seed(folder: str) -> List[str]:
    """Write the standard templates into a folder that lacks them.  One
    already there is never touched: it may be somebody's own."""
    from .assembly import AssemblyDocument
    from .document import Document

    os.makedirs(folder, exist_ok=True)
    written: List[str] = []
    for name, unit in STANDARD_PARTS:
        for kind, cls in ((fileformat.PART, Document),
                          (fileformat.ASSEMBLY, AssemblyDocument)):
            path = os.path.join(folder, name + fileformat.EXTENSIONS[kind])
            if os.path.exists(path):
                continue
            document = cls()
            document.units = unit
            document.view.style = "shaded_edges"
            document.view.orthographic = True
            document.save(path)
            written.append(path)
    for name, size, standard, unit in STANDARD_DRAWINGS:
        path = os.path.join(folder, name + fileformat.EXTENSIONS[
            fileformat.DRAWING])
        if os.path.exists(path):
            continue
        document = dwg.DrawingDocument()
        document.standard = standard
        document.units = unit
        sheet = document.add_sheet(size)
        sheet.name = "Sheet1"
        document.path = path
        document.save(path)
        written.append(path)
    return written


def default_for(kind: str, units: str = "mm",
                project_dir: str = "") -> Optional[Template]:
    """The template a New Part, New Assembly or New Drawing button starts
    from: the standard one in these units, else the first there is."""
    found = by_kind(project_dir).get(kind) or []
    inch = units in ("in", "ft")
    wanted = ("(in)" if inch else "(mm)")
    for template in found:
        if wanted in template.name:
            return template
    return found[0] if found else None


def by_kind(project_dir: str = "") -> "dict":
    """Every template on offer, by document kind, for the New dialog: the
    Templates folder's, then a project's own drawing templates, then the
    shipped drawing templates no other has the name of."""
    out = {fileformat.PART: of_type(fileformat.PART),
           fileformat.ASSEMBLY: of_type(fileformat.ASSEMBLY),
           fileformat.DRAWING: available(project_dir),
           fileformat.CAM: of_type(fileformat.CAM)}
    return out


def of_type(kind: str) -> List[Template]:
    """Part or assembly templates in the shared Templates folder: any
    InventCraft file of that kind there, as Inventor offers its .ipt and
    .iam templates."""
    folder = shared_folder()
    out: List[Template] = []
    if not folder:
        return out
    for entry in sorted(os.listdir(folder)):
        if fileformat.is_type(entry, kind):
            out.append(Template(name=os.path.splitext(entry)[0],
                                path=os.path.join(folder, entry)))
    return out


def available(project_dir: str = "") -> List[Template]:
    """Every template on offer: the project's own first, then the shipped.

    A project template with the same name as a shipped one wins, so a
    company title block can quietly replace the default without anyone
    having to delete anything.
    """
    out: List[Template] = []
    seen = set()
    try:
        from . import prefs
        chosen = prefs.prefs().templates_folder
    except Exception:
        chosen = ""
    chosen = chosen if chosen and os.path.isdir(chosen) else ""
    # a folder set on purpose first, then the project's own, then the
    # standard ones in the default folder, then the shipped
    order = ((chosen, False), (project_folder(project_dir), False),
             ("" if chosen else shared_folder(), False),
             (builtin_folder(), True))
    for folder, builtin in order:
        if not folder or not os.path.isdir(folder):
            continue
        for entry in sorted(os.listdir(folder)):
            # a template saved by DATUM, .ddat, is as good as a new one
            if not fileformat.is_type(entry, fileformat.DRAWING):
                continue
            name = os.path.splitext(entry)[0]
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append(Template(name=name,
                                path=os.path.join(folder, entry),
                                builtin=builtin))
    return out


def find(name: str, project_dir: str = "") -> Optional[Template]:
    for template in available(project_dir):
        if template.name.lower() == (name or "").lower():
            return template
    return None


def new_from(template: Optional[Template]) -> "dwg.DrawingDocument":
    """A fresh untitled drawing with the template's sheets and styles.

    Loaded and then cut loose: the new document keeps no link back, because
    a template is a starting point and not a thing to stay attached to.
    """
    if template is None or not os.path.isfile(template.path):
        document = dwg.DrawingDocument()
        document.add_sheet("A3")
        return document

    document = dwg.DrawingDocument.load(template.path)
    document.path = ""
    document.created = fileformat.now()
    document.modified = False
    document.thumbnail = None
    # a template may have been saved with views on it as an example; the
    # drawing made from it starts empty, keeping the sheets and their
    # furniture but none of somebody else's geometry
    for sheet in document.sheets:
        sheet.views = []
        sheet.annotations = []
    document.hashes = {}
    return document


def save_as_template(document: "dwg.DrawingDocument", name: str,
                     project_dir: str) -> str:
    """Write the drawing into the project's Templates folder."""
    name = (name or "").strip()
    if not name:
        raise ValueError("a template needs a name")
    if any(ch in name for ch in '\\/:*?"<>|'):
        raise ValueError('a template name cannot contain \\ / : * ? " < > |')
    # into the shared Templates folder when one is set, so the whole
    # company gets it; the project's own otherwise
    try:
        from . import prefs
        chosen = prefs.prefs().templates_folder
    except Exception:
        chosen = ""
    chosen = chosen if chosen and os.path.isdir(chosen) else ""
    folder = chosen or project_folder(project_dir) or shared_folder()
    if not folder:
        raise ValueError("there is no project to save the template into")
    os.makedirs(folder, exist_ok=True)

    target = os.path.join(folder, name + fileformat.EXTENSIONS[
        fileformat.DRAWING])
    # saved through the document rather than copied, so a template written
    # from an open drawing carries whatever is on screen right now
    keep_path = document.path
    try:
        document.path = target
        written = document.save(target)
    finally:
        document.path = keep_path
    return written


def ensure_builtins() -> List[str]:
    """Write the shipped templates if they are not there yet.

    They are generated rather than stored as files because they are only a
    sheet size and a title block, and code that builds them cannot fall out
    of step with the code that reads them.
    """
    folder = builtin_folder()
    os.makedirs(folder, exist_ok=True)
    written: List[str] = []
    for name, size, standard in (("ISO A3", "A3", "ISO"),
                                 ("ISO A4", "A4", "ISO"),
                                 ("ISO A2", "A2", "ISO"),
                                 ("ANSI B", "Tabloid", "ANSI"),
                                 ("ANSI A", "Letter", "ANSI")):
        path = os.path.join(folder, name + fileformat.EXTENSIONS[
            fileformat.DRAWING])
        if os.path.isfile(path):
            continue
        document = dwg.DrawingDocument()
        document.standard = standard
        document.properties["Company"] = ""
        sheet = document.add_sheet(size)
        sheet.name = "Sheet1"
        document.path = path
        document.save(path)
        written.append(path)
    return written


def save_copy_as_template(document, name: str) -> str:
    """A part or assembly written into the Templates folder as a template,
    the open document staying the file it was."""
    name = (name or "").strip()
    if not name:
        raise ValueError("a template needs a name")
    if any(ch in name for ch in '\\/:*?"<>|'):
        raise ValueError('a template name cannot contain \\ / : * ? " < > |')
    folder = shared_folder()
    if not folder:
        raise ValueError("there is no Templates folder")
    kind = fileformat.ASSEMBLY if hasattr(document, "occurrences") \
        else fileformat.PART
    target = os.path.join(folder, name + fileformat.EXTENSIONS[kind])
    keep = (document.path, document.modified)
    try:
        written = document.save(target)
    finally:
        document.path, document.modified = keep
    return written
