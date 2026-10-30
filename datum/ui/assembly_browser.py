"""The assembly browser: occurrences, with their relationships underneath.

Inventor nests each constraint under the components it holds, so a part shows
you what is pinning it down without hunting through a flat list.  Same here:
every occurrence carries its own relationships, and a constraint therefore
appears twice - once under each of the two parts it relates.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

from ..core.assembly import AssemblyDocument
from . import icons
from .theme import C

ROLE_ID = QtCore.Qt.UserRole + 1
ROLE_KIND = QtCore.Qt.UserRole + 2
# which component a feature row belongs to, so a click on one knows
# whether it is looking at the part that is currently being edited
ROLE_OWNER = QtCore.Qt.UserRole + 3

ORIGIN_PLANES = (("XY Plane", "XY"), ("XZ Plane", "XZ"), ("YZ Plane", "YZ"))

# the frame that is the assembly open itself, as frames_ui.SELF
SELF_FRAME = -1


class AssemblyBrowser(QtWidgets.QTreeWidget):
    """Tree of placed components and the relationships between them."""

    occurrence_selected = QtCore.Signal(int)
    occurrence_activated = QtCore.Signal(int)        # double-click -> open part
    feature_activated = QtCore.Signal(int)           # a feature of the live part
    occurrence_delete_requested = QtCore.Signal(int)
    occurrence_rename_requested = QtCore.Signal(int, str)
    ground_toggled = QtCore.Signal(int)
    visibility_toggled = QtCore.Signal(int)
    suppress_toggled = QtCore.Signal(int)
    isolate_requested = QtCore.Signal(int)
    replace_requested = QtCore.Signal(int)
    # 0 for the assembly itself, else the component's occurrence id
    properties_requested = QtCore.Signal(int)
    open_location_requested = QtCore.Signal(int)

    constraint_selected = QtCore.Signal(int)
    constraint_activated = QtCore.Signal(int)        # double-click -> edit
    constraint_delete_requested = QtCore.Signal(int)
    # everything selected at once, as one undo step: components, then
    # relationships
    delete_requested = QtCore.Signal(list, list)
    constraint_suppress_toggled = QtCore.Signal(int)

    plane_visibility_toggled = QtCore.Signal(str)
    place_requested = QtCore.Signal()
    # a Frame Generator command on members of a frame: (what, the frame's
    # occurrence, the members' ids); "change", "miter", "corner",
    # "trim_face", "notch", "lengthen", "remove"
    frame_action_requested = QtCore.Signal(str, int, list)
    # what the pointer is over: ("occurrence", its id, 0) or
    # ("frame_member", its id, its frame's occurrence); ("", 0, 0) for
    # nothing, so the view can light up what the row is
    hovered_changed = QtCore.Signal(str, int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setIndentation(14)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.setExpandsOnDoubleClick(False)
        self.setIconSize(QtCore.QSize(16, 16))
        self.setUniformRowHeights(True)

        self.customContextMenuRequested.connect(self._menu)
        self.itemDoubleClicked.connect(self._double_clicked)
        self.setMouseTracking(True)
        self.itemEntered.connect(self._entered)
        self._hovered: Tuple[str, int, int] = ("", 0, 0)
        # Assembly or Modeling: what a component expands into
        self.mode = "assembly"
        # the component being edited in place, bolded and the only one
        # whose features can be opened
        self.active = None
        self.active_path = ""
        # hands back the document behind a component path, so Modeling has
        # something to list.  The assembly only ever loaded the shapes.
        self.document_for = None
        self.itemSelectionChanged.connect(self._selection_changed)

        self._doc: Optional[AssemblyDocument] = None
        self._expanded: Dict[str, bool] = {}
        self.hidden_planes: set = {"XY", "XZ", "YZ"}

    # ------------------------------------------------------------- building

    def set_mode(self, mode: str) -> None:
        """Assembly or Modeling, which is what a component expands into.

        Inventor's two views of the same tree: in Assembly you see what
        holds a component in place, in Modeling you see what it is made
        of. Same components either way, which is the point - the tree
        does not change shape when you step into a part.
        """
        if mode == self.mode:
            return
        self.mode = mode
        self.refresh()

    def set_active(self, occurrence_id, path: str = "") -> None:
        """Mark the component being edited, the way Inventor bolds it."""
        if (occurrence_id, path) == (self.active, self.active_path):
            return
        self.active = occurrence_id
        self.active_path = path
        if occurrence_id is not None:
            self.mode = "modeling"
        self.refresh()

    def set_document(self, doc: AssemblyDocument) -> None:
        self._doc = doc
        self.refresh()

    def refresh(self) -> None:
        doc = self._doc
        if doc is None:
            return

        selected = self.selected_occurrence_ids()
        scroll = self.verticalScrollBar().value()
        self._remember_expansion()
        self.blockSignals(True)
        self.clear()

        root = QtWidgets.QTreeWidgetItem(self, [doc.title])
        root.setIcon(0, icons.icon("frame_assembly" if getattr(
            doc, "frame", None) is not None else "pattern", 16))
        root.setData(0, ROLE_KIND, "root")
        font = root.font(0)
        font.setBold(True)
        root.setFont(0, font)

        origin = QtWidgets.QTreeWidgetItem(root, ["Origin"])
        origin.setIcon(0, icons.icon("plane", 16))
        origin.setData(0, ROLE_KIND, "origin")
        origin.setForeground(0, QtGui.QBrush(QtGui.QColor(C.text_dim)))
        for label, key in ORIGIN_PLANES:
            item = QtWidgets.QTreeWidgetItem(origin, [label])
            item.setIcon(0, icons.icon("plane", 16))
            item.setData(0, ROLE_KIND, "plane")
            item.setData(0, ROLE_ID, key)
            if key in self.hidden_planes:
                item.setText(0, "%s   (hidden)" % label)
                item.setForeground(0, QtGui.QBrush(QtGui.QColor(C.tree_hidden)))

        if not doc.occurrences:
            empty = QtWidgets.QTreeWidgetItem(
                root, ["No components yet - use Place Component"])
            empty.setData(0, ROLE_KIND, "empty")
            empty.setForeground(0, QtGui.QBrush(QtGui.QColor(C.text_dim)))
            f = empty.font(0)
            f.setItalic(True)
            empty.setFont(0, f)

        for occurrence in doc.occurrences:
            item = QtWidgets.QTreeWidgetItem(root, [occurrence.label])
            item.setIcon(0, icons.icon(self._icon_of(occurrence), 16))
            item.setData(0, ROLE_ID, occurrence.id)
            item.setData(0, ROLE_KIND, "occurrence")
            item.setToolTip(0, occurrence.summary())

            tags = []
            if occurrence.grounded:
                tags.append("grounded")
            if occurrence.suppressed:
                tags.append("suppressed")
            if not occurrence.visible:
                tags.append("hidden")
            if tags:
                item.setText(0, "%s   (%s)" % (occurrence.label,
                                               ", ".join(tags)))

            if occurrence.error:
                item.setForeground(0, QtGui.QBrush(QtGui.QColor(C.error)))
                item.setText(0, occurrence.label + "   !")
                item.setToolTip(0, occurrence.error)
            elif occurrence.suppressed:
                f = item.font(0)
                f.setItalic(True)
                item.setFont(0, f)
                item.setForeground(0, QtGui.QBrush(QtGui.QColor(C.tree_faint)))
            elif occurrence.grounded:
                item.setForeground(0, QtGui.QBrush(QtGui.QColor(C.ok)))

            if occurrence.id == self.active:
                f = item.font(0)
                f.setBold(True)
                item.setFont(0, f)
                item.setForeground(0, QtGui.QBrush(QtGui.QColor(C.accent)))

            if self.mode == "modeling":
                self._add_features(item, occurrence)
                continue
            self._add_members(item, occurrence)

            for constraint in doc.constraints_on(occurrence.id):
                child = QtWidgets.QTreeWidgetItem(item, [constraint.name])
                child.setIcon(0, icons.icon(constraint.icon, 16))
                child.setData(0, ROLE_ID, constraint.id)
                child.setData(0, ROLE_KIND, "constraint")
                child.setToolTip(0, "%s\n%s" % (constraint.name,
                                                constraint.summary()))
                if constraint.error:
                    child.setForeground(0, QtGui.QBrush(QtGui.QColor(C.error)))
                    child.setText(0, constraint.name + "   !")
                elif constraint.suppressed:
                    f = child.font(0)
                    f.setItalic(True)
                    child.setFont(0, f)
                    child.setForeground(0,
                                        QtGui.QBrush(QtGui.QColor(C.tree_faint)))
                else:
                    child.setForeground(0,
                                        QtGui.QBrush(QtGui.QColor(C.text_dim)))

        self.expandItem(root)
        self._restore_expansion()
        self._focus_active()
        self.blockSignals(False)

        self.select_occurrences(selected)
        self.verticalScrollBar().setValue(scroll)

    def _icon_of(self, occurrence) -> str:
        """A frame and a frame's members have icons of their own, so they
        read apart from the parts and assemblies round them."""
        from ..core import frames
        path = self._doc.component_path(occurrence) if self._doc else None
        if path and path.lower().endswith(".icasm") and frames.is_frame(path):
            return "frame_assembly"
        if path and path.lower().endswith(".icpart") \
                and frames.is_member_part(path):
            return "frame_member"
        return occurrence.icon

    def _add_members(self, item, occurrence) -> None:
        """A frame's members hung under it, to pick for Change Frame and
        the end treatments, as Inventor lists them."""
        from ..core import frames
        path = self._doc.component_path(occurrence)
        if not path or not path.lower().endswith(".icasm"):
            return
        fd = frames.read_frame(path)
        if fd is None:
            return
        for member in fd.members:
            label = os.path.splitext(member.part)[0] if member.part \
                else "Member %d" % member.id
            child = QtWidgets.QTreeWidgetItem(item, [label])
            child.setIcon(0, icons.icon("frame_member", 16))
            child.setData(0, ROLE_ID, member.id)
            child.setData(0, ROLE_KIND, "frame_member")
            child.setData(0, ROLE_OWNER, occurrence.id)
            ends = [t.kind.replace("_", " ") for t in
                    frames.treatments_on(fd, member.id)]
            child.setToolTip(0, "%s %s%s" % (
                member.size, member.family,
                ("\nEnd treatments: " + ", ".join(ends)) if ends else ""))

    def selected_frame_members(self) -> Tuple[int, List[int]]:
        """The frame and the members of it picked in the tree: the first
        frame's, if members of several are picked."""
        owner, ids = 0, []
        fd = getattr(self._doc, "frame", None)
        if fd is not None:
            # the frame itself is open: its members are the parts in it
            by_occurrence = {m.occurrence: m.id for m in fd.members}
            ids = [by_occurrence[oid] for oid in self.selected_occurrence_ids()
                   if oid in by_occurrence]
            if ids:
                return SELF_FRAME, ids
        for item in self.selectedItems():
            if item.data(0, ROLE_KIND) != "frame_member":
                continue
            frame_oid = int(item.data(0, ROLE_OWNER))
            if owner and frame_oid != owner:
                continue
            owner = frame_oid
            mid = int(item.data(0, ROLE_ID))
            if mid not in ids:
                ids.append(mid)
        return owner, ids

    def _frame_menu(self, menu, frame_oid: int, member_ids: List[int]
                    ) -> None:
        """Inventor's Frame Generator commands on the picked members."""
        def ask(what):
            return lambda: self.frame_action_requested.emit(
                what, frame_oid, list(member_ids))
        n = len(member_ids)
        title = menu.addAction("%d frame member%s" % (n, "" if n == 1
                                                     else "s"))
        title.setEnabled(False)
        menu.addAction(icons.icon("frame_change", 16),
                       "Change Frame...").triggered.connect(ask("change"))
        if n == 1 and frame_oid != SELF_FRAME:
            # a member is a part like any other: open it, and drill holes
            menu.addAction(icons.icon("open", 16),
                           "Open Part").triggered.connect(ask("open"))
        menu.addSeparator()
        for what, label in (("miter", "Miter..."),
                            ("corner", "Corner Joint..."),
                            ("trim_face", "Trim - Extend To Face..."),
                            ("notch", "Notch..."),
                            ("lengthen", "Lengthen - Shorten...")):
            menu.addAction(label).triggered.connect(ask(what))
        menu.addSeparator()
        menu.addAction("Remove End Treatments").triggered.connect(
            ask("remove"))

    def _add_features(self, item, occurrence) -> None:
        """The component's own feature tree, hung under it.

        Read from the part's document, which somebody has to hand us: the
        assembly itself only ever loaded the shapes. A component whose
        document will not open simply has nothing under it rather than
        taking the tree down with it.
        """
        doc = self._doc
        if doc is None or self.document_for is None:
            return
        path = doc.component_path(occurrence)
        if not path:
            return
        part = self.document_for(path)
        features = list(getattr(part, "features", ()) or ())
        if not features:
            return

        live = occurrence.id == self.active
        for feature in features:
            child = QtWidgets.QTreeWidgetItem(item, [feature.name])
            child.setIcon(0, icons.icon(getattr(feature, "icon", "feature"),
                                        16))
            child.setData(0, ROLE_ID, feature.id)
            child.setData(0, ROLE_KIND, "feature")
            child.setData(0, ROLE_OWNER, occurrence.id)
            child.setToolTip(0, feature.summary())
            if getattr(feature, "suppressed", False):
                f = child.font(0)
                f.setItalic(True)
                child.setFont(0, f)
            if not live:
                # visible, but not yours to change until the part is
                # activated, which is the rule Inventor enforces too
                child.setForeground(0, QtGui.QBrush(QtGui.QColor(C.text_dim)))

    # -- expansion is remembered so a rebuild does not fold the tree up -----

    def _focus_active(self) -> None:
        """Open the component being edited, and fold the others away.

        A tree with every component's features open at once is a tree
        nobody can read. Only the part you stepped into is unfolded, which
        is where you are working and the only place you can change
        anything anyway.
        """
        if self.active is None:
            return
        target = None
        for item in self._iter_items():
            if item.data(0, ROLE_KIND) != "occurrence":
                continue
            if item.data(0, ROLE_ID) == self.active:
                target = item
                self.expandItem(item)
            else:
                self.collapseItem(item)
        if target is not None:
            self.scrollToItem(target,
                              QtWidgets.QAbstractItemView.PositionAtCenter)

    def _key(self, item: QtWidgets.QTreeWidgetItem) -> str:
        return "%s:%s" % (item.data(0, ROLE_KIND), item.data(0, ROLE_ID))

    def _remember_expansion(self) -> None:
        for item in self._iter_items():
            if item.childCount():
                self._expanded[self._key(item)] = item.isExpanded()

    def _restore_expansion(self) -> None:
        for item in self._iter_items():
            if item.childCount():
                item.setExpanded(self._expanded.get(self._key(item), True))

    def _iter_items(self):
        it = QtWidgets.QTreeWidgetItemIterator(self)
        while it.value():
            yield it.value()
            it += 1

    # ------------------------------------------------------------ selection

    def selected_occurrence_ids(self) -> List[int]:
        return self._selected("occurrence")

    def selected_constraint_ids(self) -> List[int]:
        return self._selected("constraint")

    def _selected(self, kind: str) -> List[int]:
        """The ids picked, once each: a relationship is listed under both
        of its components, and picking it in both places is one pick."""
        out: List[int] = []
        for item in self.selectedItems():
            if item.data(0, ROLE_KIND) == kind:
                found = int(item.data(0, ROLE_ID))
                if found not in out:
                    out.append(found)
        return out

    def select_occurrences(self, ids: List[int]) -> None:
        if not ids:
            return
        self.blockSignals(True)
        self.clearSelection()
        for item in self._iter_items():
            if (item.data(0, ROLE_KIND) == "occurrence"
                    and item.data(0, ROLE_ID) in ids):
                item.setSelected(True)
        self.blockSignals(False)

    def _selection_changed(self) -> None:
        occurrences = self.selected_occurrence_ids()
        if occurrences:
            self.occurrence_selected.emit(occurrences[0])
            return
        constraints = self.selected_constraint_ids()
        if constraints:
            self.constraint_selected.emit(constraints[0])

    def _entered(self, item: QtWidgets.QTreeWidgetItem, _col: int) -> None:
        kind = item.data(0, ROLE_KIND) if item is not None else None
        if kind == "occurrence":
            self._set_hovered(("occurrence", int(item.data(0, ROLE_ID)), 0))
        elif kind == "frame_member":
            self._set_hovered(("frame_member", int(item.data(0, ROLE_ID)),
                               int(item.data(0, ROLE_OWNER))))
        else:
            self._set_hovered(("", 0, 0))

    def _set_hovered(self, hovered: Tuple[str, int, int]) -> None:
        if hovered != self._hovered:
            self._hovered = hovered
            self.hovered_changed.emit(*hovered)

    def leaveEvent(self, event) -> None:
        self._set_hovered(("", 0, 0))
        super().leaveEvent(event)

    def _double_clicked(self, item: QtWidgets.QTreeWidgetItem,
                        _col: int) -> None:
        kind = item.data(0, ROLE_KIND)
        if kind == "feature":
            if item.data(0, ROLE_OWNER) == self.active:
                self.feature_activated.emit(int(item.data(0, ROLE_ID)))
            else:
                # the part has to be activated first, which is what
                # double-clicking the component itself does
                self.occurrence_activated.emit(
                    int(item.data(0, ROLE_OWNER)))
            return
        if kind == "occurrence":
            self.occurrence_activated.emit(int(item.data(0, ROLE_ID)))
        elif kind == "frame_member":
            # its part, opened to work on as a part
            self.frame_action_requested.emit(
                "open", int(item.data(0, ROLE_OWNER)),
                [int(item.data(0, ROLE_ID))])
        elif kind == "constraint":
            self.constraint_activated.emit(int(item.data(0, ROLE_ID)))
        elif kind == "plane":
            self.plane_visibility_toggled.emit(str(item.data(0, ROLE_ID)))
        elif kind == "empty":
            self.place_requested.emit()

    # ------------------------------------------------------------- commands

    def _menu(self, pos: QtCore.QPoint) -> None:
        item = self.itemAt(pos)
        if item is None or self._doc is None:
            return
        kind = item.data(0, ROLE_KIND)
        menu = QtWidgets.QMenu(self)

        if kind == "frame_member":
            if not item.isSelected():
                self.clearSelection()
                item.setSelected(True)
            frame_oid, member_ids = self.selected_frame_members()
            self._frame_menu(menu, frame_oid, member_ids)
            menu.exec(self.viewport().mapToGlobal(pos))
            return

        if kind == "occurrence":
            oid = int(item.data(0, ROLE_ID))
            occurrence = self._doc.occurrence(oid)
            if occurrence is None:
                return

            if getattr(self._doc, "frame", None) is not None:
                # in the frame itself its parts are its members
                if not item.isSelected():
                    self.clearSelection()
                    item.setSelected(True)
                frame_oid, member_ids = self.selected_frame_members()
                if member_ids:
                    self._frame_menu(menu, frame_oid, member_ids)
                    menu.addSeparator()

            open_part = menu.addAction(icons.icon("open", 16), "Open Part")
            open_part.setToolTip("Edit the file this component places")
            open_part.triggered.connect(
                lambda: self.occurrence_activated.emit(oid))

            replace = menu.addAction(icons.icon("import", 16), "Replace...")
            replace.triggered.connect(
                lambda: self.replace_requested.emit(oid))

            from ..core import frames
            path = self._doc.component_path(occurrence)
            fd = frames.read_frame(path) if path and \
                path.lower().endswith(".icasm") else None
            if fd is not None and fd.members:
                # the whole frame: every member of it
                menu.addSeparator()
                self._frame_menu(menu.addMenu(icons.icon("frame_assembly", 16),
                                              "Frame Generator"),
                                 oid, [m.id for m in fd.members])

            from .browser import add_file_actions

            class _Placed:
                path = self._doc.component_path(occurrence) or ""

            add_file_actions(
                menu, _Placed,
                lambda: self.properties_requested.emit(oid),
                lambda: self.open_location_requested.emit(oid))

            menu.addSeparator()
            ground = menu.addAction("Grounded")
            ground.setCheckable(True)
            ground.setChecked(occurrence.grounded)
            ground.setToolTip("A grounded component never moves when the "
                              "constraints are solved")
            ground.triggered.connect(lambda: self.ground_toggled.emit(oid))

            visible = menu.addAction("Visible")
            visible.setCheckable(True)
            visible.setChecked(occurrence.visible)
            visible.triggered.connect(
                lambda: self.visibility_toggled.emit(oid))

            isolate = menu.addAction("Isolate")
            isolate.setToolTip("Hide everything except this component")
            isolate.triggered.connect(lambda: self.isolate_requested.emit(oid))

            suppress = menu.addAction(
                icons.icon("suppress", 16),
                "Unsuppress" if occurrence.suppressed else "Suppress")
            suppress.triggered.connect(lambda: self.suppress_toggled.emit(oid))

            menu.addSeparator()
            rename = menu.addAction("Rename...")
            rename.triggered.connect(
                lambda: self._rename(oid, occurrence.label))
            delete = menu.addAction(icons.icon("delete", 16), "Delete")
            delete.triggered.connect(
                lambda: self._delete_from_menu("occurrence", oid))

        elif kind == "constraint":
            cid = int(item.data(0, ROLE_ID))
            constraint = self._doc.constraint(cid)
            if constraint is None:
                return
            edit = menu.addAction(icons.icon("edit", 16), "Edit")
            edit.triggered.connect(lambda: self.constraint_activated.emit(cid))
            menu.addSeparator()
            suppress = menu.addAction(
                icons.icon("suppress", 16),
                "Unsuppress" if constraint.suppressed else "Suppress")
            suppress.triggered.connect(
                lambda: self.constraint_suppress_toggled.emit(cid))
            delete = menu.addAction(icons.icon("delete", 16), "Delete")
            delete.triggered.connect(
                lambda: self._delete_from_menu("constraint", cid))

        elif kind == "plane":
            key = str(item.data(0, ROLE_ID))
            visible = menu.addAction("Visible")
            visible.setCheckable(True)
            visible.setChecked(key not in self.hidden_planes)
            visible.triggered.connect(
                lambda: self.plane_visibility_toggled.emit(key))

        else:
            if kind == "root":
                from .browser import add_file_actions

                add_file_actions(
                    menu, self._doc,
                    lambda: self.properties_requested.emit(0),
                    lambda: self.open_location_requested.emit(0))
                menu.addSeparator()
            place = menu.addAction(icons.icon("import", 16),
                                   "Place Component...")
            place.triggered.connect(self.place_requested.emit)

        menu.exec(self.viewport().mapToGlobal(pos))

    def _rename(self, occurrence_id: int, current: str) -> None:
        text, ok = QtWidgets.QInputDialog.getText(
            self, "Rename Component", "Name:", QtWidgets.QLineEdit.Normal,
            current)
        if ok and text.strip():
            self.occurrence_rename_requested.emit(occurrence_id, text.strip())

    def _delete_from_menu(self, kind: str, item_id: int) -> None:
        """Delete on a right click: the whole selection when the item is
        part of it, otherwise just the item that was clicked."""
        occurrences = self.selected_occurrence_ids()
        constraints = self.selected_constraint_ids()
        chosen = occurrences if kind == "occurrence" else constraints
        if item_id in chosen:
            self.delete_requested.emit(occurrences, constraints)
        elif kind == "occurrence":
            self.occurrence_delete_requested.emit(item_id)
        else:
            self.constraint_delete_requested.emit(item_id)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key_Delete:
            occurrences = self.selected_occurrence_ids()
            constraints = self.selected_constraint_ids()
            if occurrences or constraints:
                self.delete_requested.emit(occurrences, constraints)
                return
        elif event.key() == QtCore.Qt.Key_F2:
            ids = self.selected_occurrence_ids()
            if ids and self._doc:
                occurrence = self._doc.occurrence(ids[0])
                if occurrence:
                    self._rename(ids[0], occurrence.label)
            return
        super().keyPressEvent(event)


class AssemblyBrowserPanel(QtWidgets.QWidget):
    """The assembly tree, with Inventor's two ways of looking at it.

    Assembly and Modeling are not two trees. They are the same components
    in the same order, and only what a component expands into changes: the
    relationships that hold it, or the features it is made of. That is why
    stepping into a part does not make the rest of the assembly vanish -
    the tree never went anywhere.
    """

    MODES = (("assembly", "Assembly"), ("modeling", "Modeling"))

    def __init__(self, tree, parent=None) -> None:
        super().__init__(parent)
        self.tree = tree
        tree.setParent(self)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QtWidgets.QWidget(self)
        bar.setObjectName("BrowserModeBar")
        bar.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(6, 2, 6, 0)
        row.setSpacing(2)

        self.buttons = {}
        for key, label in self.MODES:
            button = QtWidgets.QToolButton(bar)
            button.setObjectName("BrowserModeTab")
            button.setText(label)
            button.setCheckable(True)
            button.setCursor(QtCore.Qt.PointingHandCursor)
            button.clicked.connect(
                lambda _=False, k=key: self.set_mode(k))
            row.addWidget(button)
            self.buttons[key] = button
        row.addStretch(1)

        layout.addWidget(bar)
        layout.addWidget(tree, 1)
        self.set_mode(tree.mode)

    def set_mode(self, key: str) -> None:
        for name, button in self.buttons.items():
            button.setChecked(name == key)
        self.tree.set_mode(key)

    def sync(self) -> None:
        """Follow the tree, which the application may have switched."""
        for name, button in self.buttons.items():
            button.setChecked(name == self.tree.mode)
