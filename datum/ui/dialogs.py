"""Feature dialogs.

They are non-modal on purpose: the viewport must stay live so edges and faces
can be picked while the dialog is open, exactly as Inventor works.  Each
dialog edits a feature that is *already in the document*, rebuilding on every
keystroke so the preview is the real model, not an approximation.  Cancelling
restores the snapshot taken when the dialog opened.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import fileformat, kernel
from ..core import units as unitlib
from ..core.document import Document
from ..core.features import (
    CUT, INTERSECT, JOIN, NEW_BODY, OPERATION_HINTS, OPERATION_LABELS,
    OPERATIONS, ChamferFeature, ExtrudeFeature, Feature, FilletFeature,
    HoleFeature, ImportFeature, LoftFeature, MirrorFeature, MoveFeature,
    PatternFeature, PrimitiveFeature, RevolveFeature, ShellFeature,
    SketchFeature, SweepFeature, WorkPlaneFeature, CodeFeature,
    AXIS_PREFIX, WorkAxisFeature,
    SplitFeature,
)
from ..core.naming import RefSet
from . import icons
from .theme import C
from .widgets import ExpressionEdit, FormRows, SegmentedControl, SelectionField

OP_ICONS = {JOIN: "extrude", CUT: "hole", INTERSECT: "shell",
            NEW_BODY: "box"}

# the order is Inventor's, and it is the order of how often you want each:
# Join nearly always, New Solid only when you mean it
OP_OPTIONS = [(op, OP_ICONS[op],
               "%s - %s" % (OPERATION_LABELS[op], OPERATION_HINTS[op]))
              for op in OPERATIONS]

# feature types that put a solid into the part
SOLID_MAKERS = (ExtrudeFeature, RevolveFeature, SweepFeature, LoftFeature,
                PrimitiveFeature, ImportFeature, CodeFeature)


class FeatureDialog(QtWidgets.QDialog):
    """Base class: snapshot, live rebuild, OK/Cancel."""

    committed = QtCore.Signal(int)
    cancelled = QtCore.Signal()

    def __init__(self, host, feature: Feature, title: str, icon_name: str,
                 is_new: bool, snapshot: Optional[str] = None) -> None:
        super().__init__(host)
        self.host = host
        self.doc: Document = host.document
        self.feature = feature
        self.is_new = is_new
        # Taken before the feature was added for a new feature, so Cancel
        # removes it again rather than leaving an empty one behind.
        self._snapshot = snapshot or self.doc.snapshot()
        self._updating = False
        self._closed = False
        # guards against re-entry: handling a pick clears the viewport
        # selection, which fires selection_changed straight back at us
        self._in_selection = False

        self.setWindowTitle(title)
        self.setWindowIcon(icons.icon(icon_name, 24))
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint
                            | QtCore.Qt.WindowCloseButtonHint)
        self.setModal(False)
        self.setMinimumWidth(340)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(9)

        header = QtWidgets.QHBoxLayout()
        badge = QtWidgets.QLabel()
        badge.setPixmap(icons.pixmap(icon_name, 22, self.devicePixelRatioF()))
        header.addWidget(badge)
        caption = QtWidgets.QLabel(title)
        caption.setStyleSheet("font-size: 13px; font-weight: 600;")
        header.addWidget(caption)
        header.addStretch(1)
        root.addLayout(header)

        self.form = FormRows()
        # Inventor's strip of buttons down the right of a dialog: what kind
        # of thing it works on, which kind of pattern
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(10)
        body.addWidget(self.form, 1)
        self.side = QtWidgets.QVBoxLayout()
        self.side.setSpacing(6)
        body.addLayout(self.side)
        root.addLayout(body)
        self._pick_fields: List[SelectionField] = []

        self.status = QtWidgets.QLabel("")
        self.status.setProperty("hint", True)
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(16)
        root.addWidget(self.status)

        root.addStretch(1)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self.ok_button = QtWidgets.QPushButton("OK")
        self.ok_button.setProperty("primary", True)
        self.ok_button.setDefault(True)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        buttons.addWidget(self.ok_button)
        buttons.addWidget(self.cancel_button)
        root.addLayout(buttons)

        self.ok_button.clicked.connect(self.commit)
        self.cancel_button.clicked.connect(self.cancel)

        self.build()
        self._updating = True
        self.load()
        self._updating = False
        QtCore.QTimer.singleShot(0, self.preview)

    # -- subclass hooks -----------------------------------------------------

    def build(self) -> None:
        """Add rows to ``self.form``."""

    def load(self) -> None:
        """Copy feature state into the widgets."""

    def store(self) -> None:
        """Copy widget state into the feature."""

    def wants_selection(self) -> Optional[str]:
        """Viewport selection mode to use while this dialog is open."""
        field = self.armed_picker()
        return getattr(field, "pick_mode", None) if field else None

    # -- pick fields ----------------------------------------------------------
    #
    # Inventor picks what a feature works on in the view or the browser,
    # rather than off a list of everything there is: a field switched on,
    # a click on the thing, and the field counts what it has.  One field is
    # switched on at a time.

    def picker(self, label: str, noun: str, mode: str,
               on_view: Callable, on_tree: Optional[Callable] = None
               ) -> SelectionField:
        """A pick field: ``on_view(shapes)`` for picks in the view in
        ``mode``, ``on_tree(kind, key)`` for a click in the tree, which says
        whether it was taken."""
        field = SelectionField(label)
        field.pick_mode = mode
        field.noun = noun
        field.on_view = on_view
        field.on_tree = on_tree
        field.pick_toggled.connect(
            lambda on, f=field: self._picker_toggled(f, on))
        self._pick_fields.append(field)
        return field

    def armed_picker(self) -> Optional[SelectionField]:
        return next((f for f in self._pick_fields if f.picking), None)

    def _picker_toggled(self, field: SelectionField, on: bool) -> None:
        if on:
            for other in self._pick_fields:
                if other is not field and other.picking:
                    other.blockSignals(True)
                    other.set_picking(False)
                    other.blockSignals(False)
            profiles = getattr(self, "profiles", None)
            if profiles is not None and profiles.picking:
                profiles.set_picking(False)
            self.host.set_pick_mode(field.pick_mode)
        elif self.armed_picker() is None:
            self.host.set_pick_mode(None)

    def arm(self, field: Optional[SelectionField]) -> None:
        if field is None:
            armed = self.armed_picker()
            if armed is not None:
                armed.set_picking(False)
        else:
            field.set_picking(True)

    def on_selection(self) -> None:
        field = self.armed_picker()
        if field is None or self._in_selection:
            return
        shapes = self.host.viewport.selected_shapes()
        if not shapes:
            return
        self._in_selection = True
        try:
            field.on_view(shapes)
            self.host.viewport.clear_selection()
        finally:
            self._in_selection = False
        self.preview()

    def on_tree_pick(self, kind: str, key: str) -> bool:
        """A click in the design tree while a pick field is on."""
        field = self.armed_picker()
        if field is None or field.on_tree is None:
            return False
        if not field.on_tree(kind, key):
            return False
        self.preview()
        return True

    def feature_picker(self, kinds, selected: List[int]) -> SelectionField:
        """Features, picked in the tree or by a face they made in the view."""
        self._picked_features = [fid for fid in selected
                                 if self.doc.feature(fid) is not None]
        index = self.doc.index_of(self.feature.id)

        def usable(fid) -> bool:
            f = self.doc.feature(fid)
            return (f is not None and self.doc.index_of(fid) < index
                    and not isinstance(f, SketchFeature)
                    and (not kinds or isinstance(f, kinds)))

        def toggle(fid) -> bool:
            if not usable(fid):
                return False
            if fid in self._picked_features:
                self._picked_features.remove(fid)
            else:
                self._picked_features.append(fid)
            field.set_count(len(self._picked_features), "feature")
            return True

        def from_view(shapes):
            from OCP.TopAbs import TopAbs_FACE
            for shape in shapes:
                if shape.ShapeType() == TopAbs_FACE:
                    fid = self.doc.feature_of_face(shape, self.feature.id)
                    if fid is not None:
                        toggle(fid)

        def from_tree(kind, key):
            return kind == "feature" and toggle(int(key))

        field = self.picker("Select features", "feature", "face",
                            from_view, from_tree)
        field.toggle = toggle
        field.cleared.connect(lambda: (self._picked_features.clear(),
                                       field.set_count(0, "feature"),
                                       self.preview()))
        field.setToolTip("Pick the features in the tree, or click a face "
                         "one of them made")
        field.set_count(len(self._picked_features), "feature")
        return field

    def picked_features(self, _field=None) -> List[int]:
        return list(getattr(self, "_picked_features", []))

    def solids_picker(self, selected: List[str]) -> SelectionField:
        """Solids, picked by any face of theirs or their row in the tree."""
        self._picked_solids = list(selected)
        names = (self.doc.bodies_before(self.feature.id)
                 if hasattr(self.doc, "bodies_before") else [])

        def toggle(name) -> bool:
            if name not in names and name not in self._picked_solids:
                return False
            if name in self._picked_solids:
                self._picked_solids.remove(name)
            else:
                self._picked_solids.append(name)
            field.set_count(len(self._picked_solids), "solid")
            return True

        def from_view(shapes):
            for shape in shapes:
                name = self.doc.solid_of(shape, self.feature.id)
                if name is not None:
                    toggle(name)

        def from_tree(kind, key):
            return kind == "body" and toggle(str(key))

        field = self.picker("Select solids", "solid", "face", from_view,
                            from_tree)
        field.toggle = toggle
        field.names = names
        field.cleared.connect(lambda: (self._picked_solids.clear(),
                                       field.set_count(0, "solid"),
                                       self.preview()))
        field.setToolTip("Pick a solid by any of its faces, or by its row "
                         "under Solid Bodies in the tree")
        field.set_count(len(self._picked_solids), "solid")
        return field

    # -- plumbing -----------------------------------------------------------

    def bind(self, *widgets) -> None:
        for w in widgets:
            if isinstance(w, ExpressionEdit):
                w.changed.connect(self.preview)
            elif isinstance(w, SegmentedControl):
                w.changed.connect(lambda _=None: self.preview())
            elif isinstance(w, QtWidgets.QComboBox):
                w.currentIndexChanged.connect(lambda _=0: self.preview())
            elif isinstance(w, QtWidgets.QCheckBox):
                w.toggled.connect(lambda _=False: self.preview())
            elif isinstance(w, QtWidgets.QLineEdit):
                w.textChanged.connect(lambda _="": self.preview())

    def preview(self) -> None:
        if self._updating or self._closed:
            return
        self.store()
        report = self.host.rebuild(keep_camera=True)
        error = self.feature.error
        if error:
            self.status.setText(error)
            self.status.setStyleSheet("color: %s;" % C.error)
            self.ok_button.setEnabled(False)
        elif report.errors:
            self.status.setText(report.message)
            self.status.setStyleSheet("color: %s;" % C.warn)
            self.ok_button.setEnabled(True)
        else:
            self.status.setText(self.feature.summary())
            self.status.setStyleSheet("color: %s;" % C.ok)
            self.ok_button.setEnabled(True)

    def commit(self) -> None:
        self.store()
        self.host.rebuild(keep_camera=True)
        if self.feature.error:
            QtWidgets.QMessageBox.warning(self, "Feature failed",
                                          self.feature.error)
            return
        self._closed = True
        self.committed.emit(self.feature.id)
        self.close()

    def cancel(self) -> None:
        self._closed = True
        self.doc.load_dict(json.loads(self._snapshot))
        self.host.rebuild(keep_camera=True)
        self.cancelled.emit()
        self.close()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if not self._closed:
            self.cancel()
            return
        self.host.dialog_finished(self)
        super().closeEvent(event)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key_Escape:
            self.cancel()
            return
        if (event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter)
                and self.ok_button.isEnabled()):
            self.commit()
            return
        super().keyPressEvent(event)

    # -- helpers ------------------------------------------------------------

    def expression(self, value: str, unit: str = "mm") -> ExpressionEdit:
        # every parameter of the part, dimensions and feature values too
        view = (self.doc.parameter_view()
                if hasattr(self.doc, "parameter_view") else self.doc.params)
        w = ExpressionEdit(value, view, unit)
        self.bind(w)
        return w

    def profile_field(self) -> SelectionField:
        """The profile field, armed, with a likely profile already in it.

        Clicking regions in the view adds and drops them, any closed region
        of any sketch in sight.  A new feature starts with one already
        chosen, the biggest of the newest sketch's, which is the one wanted
        most of the time and saves a click; when it is not, a click on it
        drops it and a click on the right one takes that.
        """
        self.profiles = SelectionField("Select profiles")
        self.profiles.pick_toggled.connect(self._toggle_profile_pick)
        self.profiles.cleared.connect(self._clear_profiles)
        self.profiles.set_count(len(self.feature.profiles), "profile")
        # armed as soon as the dialog opens: picking profiles is the first
        # thing you do, so it should not need a click to switch on. It stays
        # a toggle because later extent options need the viewport for their
        # own picking.
        QtCore.QTimer.singleShot(0, self._arm_profiles)
        return self.profiles

    def _arm_profiles(self) -> None:
        if self._closed:
            return
        self.profiles.set_picking(True)
        self._propose_profile()

    def _propose_profile(self) -> None:
        """Start a new feature off on the profile it most likely wants."""
        if not self.is_new or len(self.feature.profiles):
            return
        finder = getattr(self.host, "available_regions", None)
        if finder is None:
            return
        try:
            regions = finder()
        except Exception:
            return
        if not regions:
            return
        wanted = getattr(self.feature, "sketch_id", 0)
        own = [r for r in regions if r["sketch_id"] == wanted]
        if not own:
            # otherwise the newest sketch there is a region of
            newest = max(regions,
                         key=lambda r: self.doc.index_of(r["sketch_id"]))
            own = [r for r in regions
                   if r["sketch_id"] == newest["sketch_id"]]
        best = max(own, key=lambda r: r.get("area", 0.0))
        self.on_profile_clicked(best["sketch_id"], best["centre"])

    def _toggle_profile_pick(self, on: bool) -> None:
        if on:
            for field in self._pick_fields:
                if field.picking:
                    field.blockSignals(True)
                    field.set_picking(False)
                    field.blockSignals(False)
        self.host.set_profile_pick(self if on else None)

    def _clear_profiles(self) -> None:
        from ..core.features import ProfileSelection

        self.feature.profiles = ProfileSelection()
        self.profiles.set_count(0, "profile")
        self.host.refresh_profile_overlay()
        self.preview()

    def on_profile_clicked(self, sketch_id: int, centre) -> None:
        """One region was clicked in the viewport - toggle it."""
        self.feature.profiles.toggle(sketch_id, centre)
        self.profiles.set_count(len(self.feature.profiles), "profile")
        self.host.refresh_profile_overlay()
        self.preview()

    def showEvent(self, event):
        super().showEvent(event)
        # keep the viewport ready for picks rather than stealing focus
        if getattr(self, "profiles", None) is not None:
            self.host.viewport.setFocus()

    def wants_profiles(self) -> bool:
        return getattr(self, "profiles", None) is not None \
            and self.profiles.picking

    # -- the Output row ----------------------------------------------------

    def makes_first_solid(self) -> bool:
        """True when this feature would put the part's first solid in it."""
        index = self.doc.index_of(self.feature.id)
        for i, other in enumerate(self.doc.features):
            if i >= index or other.suppressed:
                continue
            if isinstance(other, SOLID_MAKERS):
                return False
        return True

    def boolean_row(self) -> None:
        """Inventor's Output row: how this solid meets the ones already there.

        An empty part is not asked, because there is no question to answer -
        nothing to join to, cut from or intersect with.  It gets the body
        name instead, which is the only decision left.
        """
        if self.makes_first_solid():
            self.operation = None
            self.body_name = QtWidgets.QLineEdit(
                self.feature.body_name or "Solid1")
            self.body_name.setToolTip(
                "What to call this solid. A part can hold several.")
            self.bind(self.body_name)
            self.form.add("Body Name", self.body_name)
            return

        self.body_name = None
        self.operation = SegmentedControl(OP_OPTIONS)
        self.bind(self.operation)
        self.form.add("Boolean", self.operation)
        self.solids_row()
        self.operation.changed.connect(lambda _k: self._sync_solids())

    def solids_row(self) -> None:
        """Which solids it works on, when the part has more than one.

        Nothing ticked means the one its material meets, which is right
        nearly every time; tick the ones meant when it is not, a cut
        through two solids at once, or a join that fuses several.
        """
        names = (self.doc.bodies_before(self.feature.id)
                 if hasattr(self.doc, "bodies_before") else [])
        names += [n for n in self.feature.solids if n not in names]
        self.solids = None
        self._picked_solids = list(self.feature.solids)
        if len(names) < 2:
            return
        self.solids = self.solids_picker(self.feature.solids)
        self.solids.setToolTip(
            "The solids this works on, picked by a face or in the tree. "
            "None picked: the one it meets. A join fuses the new material "
            "and every picked solid into one.")
        self.form.add("Solids", self.solids)

    def _sync_solids(self) -> None:
        if getattr(self, "solids", None) is None:
            return
        operation = (self.operation.value()
                     if getattr(self, "operation", None) is not None
                     else NEW_BODY)
        self.form.set_visible(self.solids, operation != NEW_BODY)

    def picked_solids(self) -> List[str]:
        return list(getattr(self, "_picked_solids", self.feature.solids))

    def load_boolean(self) -> None:
        if getattr(self, "operation", None) is not None:
            self.operation.set_value(self.feature.operation)
        elif getattr(self, "body_name", None) is not None:
            self.body_name.setText(self.feature.body_name or "Solid1")
        self._sync_solids()

    def store_boolean(self) -> None:
        if getattr(self, "operation", None) is not None:
            self.feature.operation = self.operation.value()
        elif getattr(self, "body_name", None) is not None:
            self.feature.body_name = self.body_name.text().strip()
        self.feature.solids = (self.picked_solids()
                               if self.feature.operation != NEW_BODY else [])

    def sketch_combo(self, current: int) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        index = self.doc.index_of(self.feature.id)
        for f in self.doc.sketch_features():
            if self.doc.index_of(f.id) < index:
                combo.addItem(icons.icon("sketch", 15), f.name, f.id)
        pos = combo.findData(current)
        if pos >= 0:
            combo.setCurrentIndex(pos)
        self.bind(combo)
        return combo

    def earlier(self, cls) -> List[Feature]:
        """Features of a kind that come before this one in the tree."""
        index = self.doc.index_of(self.feature.id)
        return [f for f in self.doc.features
                if isinstance(f, cls) and self.doc.index_of(f.id) < index]

    def axis_combo(self) -> QtWidgets.QComboBox:
        """The origin axes, then every work axis made before this feature."""
        combo = QtWidgets.QComboBox()
        for name in ("X", "Y", "Z"):
            combo.addItem(icons.icon("axis", 15), "%s Axis" % name, name)
        for axis in self.earlier(WorkAxisFeature):
            combo.addItem(icons.icon("axis", 15), axis.name, axis.name)
        return combo

    def plane_combo(self, current: str) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        for name in ("XY", "XZ", "YZ"):
            combo.addItem(icons.icon("plane", 15), "%s Plane" % name, name)
        # and the work planes made before this feature, which it can use
        for plane in self.earlier(WorkPlaneFeature):
            combo.addItem(icons.icon("plane", 15), plane.name, plane.name)
        pos = combo.findData(current)
        if pos >= 0:
            combo.setCurrentIndex(pos)
        self.bind(combo)
        return combo

    @staticmethod
    def checked_features(widget: QtWidgets.QListWidget) -> List[int]:
        out = []
        for i in range(widget.count()):
            item = widget.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                out.append(int(item.data(QtCore.Qt.UserRole)))
        return out


# ==========================================================================


def _length_value(mm: float) -> str:
    """A dragged length as the field stores it: millimetres, to the
    hundredth, without trailing zeros."""
    return ("%.2f" % mm).rstrip("0").rstrip(".")


class ExtrudeDialog(FeatureDialog):
    def __init__(self, host, feature, is_new, snapshot=None):
        self._handle_drawn = []
        self._handle_axis = None        # (centre, direction, factor)
        self._handle_dragging = False
        self._handle_pending = False
        super().__init__(host, feature, "Extrude", "extrude", is_new, snapshot)
        viewport = getattr(host, "viewport", None)
        if viewport is not None:
            viewport.drag_handle = self._handle_hit
            viewport.handle_drag_started.connect(self._handle_started)
            viewport.axis_drag_moved.connect(self._handle_moved)
            viewport.axis_drag_finished.connect(self._handle_finished)

    # -- the arrow in the view ------------------------------------------------
    #
    # Inventor puts an arrow on the end of the extrusion that drags the
    # distance up and down, rather than it always having to be typed.  It
    # stands on the middle of the profile, moved out along the direction by
    # the distance, and a press on it pulls it along that line; the
    # distance follows, written back into the field, and the preview
    # follows that.

    HANDLE_PICK = 12            # how near the arrow a press grabs it, pixels

    def _handle_geometry(self):
        """(centre, direction, factor) for the arrow, or None for none.

        ``factor`` turns a distance along the line into the extrude's
        distance: 1, or 2 for a symmetric one, whose end is half way out.
        """
        if (self.extent.currentData() != "distance"
                or self.direction.value() == "asymmetric"
                or self.from_end.is_set() or self.match.isChecked()):
            return None
        centres, normal = [], None
        for sketch_id, u, v in self.feature.profiles:
            owner = self.doc.feature(sketch_id)
            sketch = getattr(owner, "sketch", None)
            if sketch is None:
                continue
            centres.append(sketch.plane.to_3d(u, v))
            if normal is None:
                normal = sketch.plane.normal
        if not centres or normal is None:
            return None
        centre = tuple(sum(c[i] for c in centres) / len(centres)
                       for i in range(3))
        direction = self.direction.value()
        sign = -1.0 if direction == "flipped" else 1.0
        factor = 2.0 if direction == "symmetric" else 1.0
        return centre, tuple(sign * n for n in normal), factor

    def _handle_tip(self):
        axis = self._handle_geometry()
        if axis is None:
            return None, None
        centre, direction, factor = axis
        reach = self.distance.value() / factor
        return axis, tuple(centre[i] + direction[i] * reach for i in range(3))

    def _draw_handle(self) -> None:
        viewport = getattr(self.host, "viewport", None)
        if viewport is None:
            return
        viewport.remove_drawn(self._handle_drawn)
        self._handle_drawn = []
        if self._closed:
            return
        axis, tip = self._handle_tip()
        self._handle_axis = axis
        if axis is None:
            viewport.redraw()
            return
        with viewport.collecting() as drawn:
            viewport.draw_arrow(tip, axis[1], C.annotation, preview=False,
                                width=4.0)
            label = unitlib.length_text(self.distance.value(),
                                        self.distance.doc_unit)
            length = max(2.0, viewport.view_span() * 0.11)
            beside = tuple(tip[i] + axis[1][i] * length * 1.15
                           for i in range(3))
            viewport.draw_text(label, beside, C.annotation, 16.0)
        viewport.on_top(drawn)
        self._handle_drawn = drawn
        viewport.redraw()

    def _handle_hit(self, x: int, y: int):
        """Whether a press at (x, y) is on the arrow; its axis if so."""
        if self._closed or self._handle_axis is None:
            return None
        viewport = self.host.viewport
        axis, tip = self._handle_tip()
        if axis is None:
            return None
        length = max(2.0, viewport.view_span() * 0.11)
        end = tuple(tip[i] + axis[1][i] * length for i in range(3))
        ax, ay = viewport.project(tip)
        bx, by = viewport.project(end)
        dx, dy = bx - ax, by - ay
        span = dx * dx + dy * dy
        t = 0.0 if span == 0 else max(0.0, min(1.0, (
            (x - ax) * dx + (y - ay) * dy) / span))
        px, py = ax + t * dx, ay + t * dy
        if (x - px) ** 2 + (y - py) ** 2 > self.HANDLE_PICK ** 2:
            return None
        return axis[0], axis[1]

    def _handle_started(self, along: float) -> None:
        if self._closed or self._handle_axis is None:
            return
        # Measured along the line as it was when grabbed, all the way: the
        # arrow keeps the spot it was grabbed by under the cursor, rather
        # than its tip jumping there.
        factor = self._handle_axis[2]
        self._grab_offset = along - self.distance.value() / factor
        self._grab_direction = self.direction.value()
        self._handle_dragging = True

    def _handle_moved(self, along: float) -> None:
        if not self._handle_dragging or self._closed:
            return
        _centre, _direction, factor = self._handle_axis
        value = (along - self._grab_offset) * factor
        start = self._grab_direction
        if start != "symmetric":
            # pulled back through the sketch it goes the other way, as
            # Inventor's arrow does, and back again if pulled out again
            other = "default" if start == "flipped" else "flipped"
            wanted = start if value >= 0 else other
            if self.direction.value() != wanted:
                self.direction.blockSignals(True)
                self.direction.set_value(wanted)
                self.direction.blockSignals(False)
                self._sync_enabled()
        value = max(0.01, abs(value))
        # the field shows it at once; the rebuild is batched below
        self.distance.blockSignals(True)
        self.distance.set_text(_length_value(value))
        self.distance.blockSignals(False)
        # one rebuild for however many moves arrive before it can run
        if not self._handle_pending:
            self._handle_pending = True
            QtCore.QTimer.singleShot(0, self._handle_catch_up)

    def _handle_catch_up(self) -> None:
        self._handle_pending = False
        if not self._closed:
            self.preview()

    def _handle_finished(self, along: float) -> None:
        if not self._handle_dragging:
            return
        self._handle_moved(along)
        self._handle_dragging = False

    def _drop_handle(self) -> None:
        viewport = getattr(self.host, "viewport", None)
        if viewport is None:
            return
        viewport.remove_drawn(self._handle_drawn)
        self._handle_drawn = []
        if viewport.drag_handle == self._handle_hit:
            viewport.drag_handle = None
        for signal, slot in ((viewport.handle_drag_started,
                              self._handle_started),
                             (viewport.axis_drag_moved, self._handle_moved),
                             (viewport.axis_drag_finished,
                              self._handle_finished)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        viewport.redraw()

    def preview(self) -> None:
        super().preview()
        self._draw_handle()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._closed:
            self._drop_handle()
        super().closeEvent(event)

    # Direction is its own row of buttons, as in Inventor, rather than
    # Symmetric hiding among the extents and a Flip box at the bottom.
    DIRECTIONS = [
        ("default", "dir_default", "Default - away from the sketch, along "
                                   "its normal"),
        ("flipped", "dir_flipped", "Flipped - the other way, into the part"),
        ("symmetric", "dir_symmetric", "Symmetric - half the distance each "
                                       "side of the sketch"),
        ("asymmetric", "dir_asymmetric", "Asymmetric - a distance each way, "
                                         "each its own"),
    ]

    EXTENTS = [
        ("Distance", "distance",
         "A distance from the sketch, or from the face picked in From"),
        ("To Next", "to_next",
         "Up to the next face it meets: a join until it reaches the part, "
         "a cut through the material it starts in"),
        ("To", "to_plane",
         "Up to a face, a plane or a corner of the part. A tilted plane "
         "cuts the end on its slope."),
        ("Between", "from_to",
         "Between two faces or planes: From, and the one it runs to"),
        ("Through All", "through_all",
         "Right through everything, both ways"),
    ]

    def build(self):
        # Inventor's order: what to extrude, how, what it does, the rest
        self.form.add_section("Input Geometry")
        self.form.add("Profiles", self.profile_field())
        # From: where it starts, when not on the sketch itself
        self.from_end = EndField(self, self.feature.from_plane,
                                 blank="Sketch plane", curved=False)
        self.from_end.changed.connect(self.preview)
        self.from_end.setToolTip(
            "Where it starts: the sketch, or a flat face or a plane. "
            "Between runs from this to the one it runs to.")
        self.form.add("From", self.from_end)

        self.form.add_section("Behavior")
        self.direction = SegmentedControl(self.DIRECTIONS)
        self.bind(self.direction)
        self.form.add("Direction", self.direction)

        # the extent is picked beside the distance it qualifies, the way
        # Inventor's Distance A carries its own drop down
        self.extent = QtWidgets.QComboBox()
        for text, key, tip in self.EXTENTS:
            self.extent.addItem(text, key)
            self.extent.setItemData(self.extent.count() - 1, tip,
                                    QtCore.Qt.ToolTipRole)
        self.extent.setToolTip(
            "How far it goes: a distance, to the next face, up to a face, "
            "a plane or a point, between two, or right through everything")
        self.bind(self.extent)

        self.distance = self.expression(self.feature.distance)

        self.to_end = EndField(self, self.feature.to_plane, points=True)
        self.to_end.changed.connect(self.preview)
        # the list of planes, as it always was
        self.to_plane = self.to_end.combo
        self.to_plane.setToolTip(
            "The datum or work plane the extrude runs up to. A tilted one "
            "cuts the end on its slope.")

        extents = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(extents)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.extent)
        row.addWidget(self.distance, 1)
        row.addWidget(self.to_end, 1)
        self.form.add("Extents", extents)

        self.distance2 = self.expression(self.feature.distance2)
        self.distance2.setToolTip("How far it goes the other way")
        self.form.add("Distance B", self.distance2)

        self.extend_face = QtWidgets.QCheckBox("Extend Face")
        self.extend_face.setToolTip(
            "A picked face that stops short of the profile runs on past its "
            "edges, the whole of its surface")
        self.bind(self.extend_face)
        self.form.add("", self.extend_face)

        self.form.add_section("Output")
        self.boolean_row()
        self._open_sketch = self._find_open_sketch()
        self._sketch_id = self.feature.sketch_id
        self.match = QtWidgets.QCheckBox("Match Shape")
        self.match.setToolTip(
            "The sketch's open profile, its ends run on to the part: a cut "
            "takes everything on its side, a join fills what it closes in")
        self.match_side = QtWidgets.QToolButton()
        self.match_side.setIcon(icons.icon("dir_flipped", 18))
        self.match_side.setCheckable(True)
        self.match_side.setFixedSize(30, 26)
        self.match_side.setToolTip("The other side of the profile")
        match = QtWidgets.QWidget()
        line = QtWidgets.QHBoxLayout(match)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        line.addWidget(self.match)
        line.addWidget(self.match_side)
        line.addStretch(1)
        self.match_row = match
        self.form.add("", match)
        self.match.toggled.connect(lambda _on: (self._sync_enabled(),
                                                self.preview()))
        self.match_side.toggled.connect(lambda _on: self.preview())

        self.form.add_section("Advanced")
        self.taper = self.expression(self.feature.taper, "deg")
        self.form.add("Taper", self.taper)
        self.taper2 = self.expression(self.feature.taper2, "deg")
        self.taper2.setToolTip("The other way's own taper")
        self.form.add("Taper B", self.taper2)

        self.extent.currentIndexChanged.connect(
            lambda _=0: self._sync_enabled())
        self.direction.changed.connect(lambda _k: self._sync_enabled())

    def _find_open_sketch(self) -> int:
        """The sketch Match Shape would use: the picked profiles' own, if
        it has an open profile, else the newest before this one that has;
        0 for none."""
        index = self.doc.index_of(self.feature.id)
        sketches = [f for f in self.doc.sketch_features()
                    if self.doc.index_of(f.id) < index]
        own = set(self.feature.profiles.sketch_ids())
        if self.feature.match_shape and self.feature.sketch_id:
            own.add(self.feature.sketch_id)
        ordered = ([f for f in sketches if f.id in own]
                   + sorted((f for f in sketches if f.id not in own),
                            key=lambda f: -self.doc.index_of(f.id)))
        for owner in ordered:
            sketch = getattr(owner, "sketch", None)
            try:
                if sketch is not None and kernel.open_chain_wire(sketch):
                    return owner.id
            except Exception:
                continue
        return 0

    def _sync_enabled(self):
        mode = self.extent.currentData()
        direction = self.direction.value()
        ending = mode in ("to_plane", "from_to")
        self.distance.setVisible(not ending)
        self.distance.setEnabled(mode == "distance")
        self.to_end.setVisible(ending)
        self.form.set_visible(self.extend_face, ending)
        # Distance and To Next go one way or the other; Distance can go
        # both, the same or each its own.  Through All already runs both
        # ways, and a face or a plane decides the way for itself.
        steerable = mode in ("distance", "to_next")
        self.direction.setEnabled(steerable)
        for key in ("symmetric", "asymmetric"):
            self.direction._buttons[key].setEnabled(mode == "distance")
        if mode == "to_next" and direction in ("symmetric", "asymmetric"):
            self.direction.set_value("default")
            direction = "default"
        self.direction.setToolTip(
            "" if steerable else
            "Through All runs both ways, so there is no direction to pick"
            if mode == "through_all" else
            "The face or plane decides which way it runs")
        asymmetric = mode == "distance" and direction == "asymmetric"
        self.form.set_visible(self.distance2, asymmetric)
        self.form.set_visible(self.taper2, asymmetric)
        # From is where a plain distance starts, or the first of the two
        # it runs between
        self.form.set_visible(self.from_end, mode == "from_to" or (
            mode == "distance" and direction in ("default", "flipped")))
        self.form.set_label(self.from_end, "From" if mode != "from_to"
                            else "Between")
        # a taper grows from the sketch, so it only makes sense one way
        self.taper.setEnabled(
            mode == "distance" and direction != "symmetric")
        self.form.set_visible(self.match_row, bool(self._open_sketch))
        self.match_side.setEnabled(self.match.isChecked())
        if getattr(self, "profiles", None) is not None:
            self.profiles.setEnabled(not self.match.isChecked())

    def load(self):
        self.load_boolean()
        extent = self.feature.extent
        if extent in ("symmetric", "asymmetric"):
            # files keep these as extents; here they are directions
            self.direction.set_value(extent)
            extent = "distance"
        else:
            self.direction.set_value(
                "flipped" if self.feature.reversed else "default")
        pos = self.extent.findData(extent)
        self.extent.setCurrentIndex(max(0, pos))
        self.distance.set_text(self.feature.distance)
        self.distance2.set_text(self.feature.distance2)
        self.taper.set_text(self.feature.taper)
        self.taper2.set_text(self.feature.taper2)
        self.to_end.set_value(self.feature.to_plane, self.feature.to_ref)
        self.from_end.set_value(self.feature.from_plane,
                                self.feature.from_ref)
        self.extend_face.setChecked(self.feature.extend_face)
        self.match.setChecked(self.feature.match_shape
                              and bool(self._open_sketch))
        self.match_side.setChecked(self.feature.match_flip)
        self._sync_enabled()

    def store(self):
        self.store_boolean()
        mode = self.extent.currentData()
        direction = self.direction.value()
        # Symmetric and Asymmetric are stored as extents and Flipped as
        # reversed, as files always had them
        if mode == "distance" and direction in ("symmetric", "asymmetric"):
            self.feature.extent = direction
            self.feature.reversed = False
        else:
            self.feature.extent = mode
            self.feature.reversed = direction == "flipped"
        self.feature.distance = self.distance.text()
        self.feature.distance2 = self.distance2.text()
        self.feature.to_plane = self.to_end.name
        self.feature.to_ref = self.to_end.ref
        self.feature.from_plane = self.from_end.name
        self.feature.from_ref = self.from_end.ref
        self.feature.extend_face = self.extend_face.isChecked()
        self.feature.taper = self.taper.text()
        self.feature.taper2 = self.taper2.text()
        matching = self.match.isChecked() and bool(self._open_sketch)
        self.feature.match_shape = matching
        self.feature.match_flip = self.match_side.isChecked()
        self.feature.sketch_id = (self._open_sketch if matching
                                  else self._sketch_id)


class RevolveDialog(FeatureDialog):
    def __init__(self, host, feature, is_new, snapshot=None):
        super().__init__(host, feature, "Revolve", "revolve", is_new, snapshot)

    def build(self):
        self.form.add("Profiles", self.profile_field())

        self.boolean_row()

        self.form.add_separator()

        self.axis = QtWidgets.QComboBox()
        self.axis.addItem("Sketch X axis", "X")
        self.axis.addItem("Sketch Y axis", "Y")
        # the part's own axes and every work axis made before this feature
        for name in ("X", "Y", "Z"):
            self.axis.addItem(icons.icon("axis", 15), "%s Axis" % name,
                              AXIS_PREFIX + name)
        for axis in self.earlier(WorkAxisFeature):
            self.axis.addItem(icons.icon("axis", 15), axis.name,
                              AXIS_PREFIX + axis.name)
        self.bind(self.axis)
        self.form.add("Axis", self.axis)

        self.angle = self.expression(self.feature.angle, "deg")
        self.form.add("Angle", self.angle)

        self.flip = QtWidgets.QCheckBox("Reverse direction")
        self.bind(self.flip)
        self.form.add("", self.flip)

    def load(self):
        self.load_boolean()
        pos = self.axis.findData(self.feature.axis)
        self.axis.setCurrentIndex(max(0, pos))
        self.angle.set_text(self.feature.angle)
        self.flip.setChecked(self.feature.reversed)

    def store(self):
        self.store_boolean()
        self.feature.axis = self.axis.currentData()
        self.feature.angle = self.angle.text()
        self.feature.reversed = self.flip.isChecked()


class SweepDialog(FeatureDialog):
    def __init__(self, host, feature, is_new, snapshot=None):
        super().__init__(host, feature, "Sweep", "sweep", is_new, snapshot)

    def build(self):
        self.form.add("Profiles", self.profile_field())

        self.path = self.sketch_combo(self.feature.path_id)
        self.form.add("Path", self.path)

        hint = QtWidgets.QLabel("The path sketch supplies an open chain of "
                                "curves for the profile to follow.")
        hint.setProperty("hint", True)
        hint.setWordWrap(True)
        self.form.add("", hint)

        self.boolean_row()

    def load(self):
        pos = self.path.findData(self.feature.path_id)
        if pos >= 0:
            self.path.setCurrentIndex(pos)
        elif self.path.count() > 1:
            self.path.setCurrentIndex(self.path.count() - 1)
        self.load_boolean()

    def store(self):
        self.feature.path_id = int(self.path.currentData() or 0)
        self.store_boolean()


class LoftDialog(FeatureDialog):
    def __init__(self, host, feature, is_new, snapshot=None):
        super().__init__(host, feature, "Loft", "loft", is_new, snapshot)

    def build(self):
        self.sections = QtWidgets.QListWidget()
        self.sections.setMaximumHeight(130)
        index = self.doc.index_of(self.feature.id)
        for f in self.doc.sketch_features():
            if self.doc.index_of(f.id) >= index:
                continue
            item = QtWidgets.QListWidgetItem(icons.icon("sketch", 15), f.name)
            item.setData(QtCore.Qt.UserRole, f.id)
            item.setCheckState(QtCore.Qt.Checked
                               if f.id in self.feature.sections
                               else QtCore.Qt.Unchecked)
            self.sections.addItem(item)
        self.sections.itemChanged.connect(lambda _i: self.preview())
        self.form.add("Sections", self.sections)

        hint = QtWidgets.QLabel("Blended in list order. Put each section on "
                                "its own plane.")
        hint.setProperty("hint", True)
        hint.setWordWrap(True)
        self.form.add("", hint)

        self.ruled = QtWidgets.QCheckBox("Ruled (straight between sections)")
        self.bind(self.ruled)
        self.form.add("", self.ruled)

        self.boolean_row()

    def load(self):
        self.ruled.setChecked(self.feature.ruled)
        self.load_boolean()

    def store(self):
        self.feature.sections = self.checked_features(self.sections)
        self.feature.ruled = self.ruled.isChecked()
        self.feature.closed = True
        self.store_boolean()


class HoleDialog(FeatureDialog):
    def __init__(self, host, feature, is_new, snapshot=None):
        super().__init__(host, feature, "Hole", "hole", is_new, snapshot)

    def build(self):
        self.sketch = self.sketch_combo(self.feature.sketch_id)
        self.form.add("Centres", self.sketch)

        hint = QtWidgets.QLabel("Each circle in the sketch places one hole.")
        hint.setProperty("hint", True)
        self.form.add("", hint)

        self.form.add_separator()

        self.kind = QtWidgets.QComboBox()
        self.kind.addItem("Simple", "simple")
        self.kind.addItem("Counterbore", "counterbore")
        self.kind.addItem("Countersink", "countersink")
        self.bind(self.kind)
        self.form.add("Type", self.kind)

        self.diameter = self.expression(self.feature.diameter)
        self.form.add("Diameter", self.diameter)

        self.through = QtWidgets.QCheckBox("Through all")
        self.bind(self.through)
        self.form.add("", self.through)

        self.depth = self.expression(self.feature.depth)
        self.form.add("Depth", self.depth)

        self.form.add_separator()

        self.cb_diameter = self.expression(self.feature.cb_diameter)
        self.form.add("C'bore dia", self.cb_diameter)
        self.cb_depth = self.expression(self.feature.cb_depth)
        self.form.add("C'bore depth", self.cb_depth)
        self.cs_angle = self.expression(self.feature.cs_angle, "deg")
        self.form.add("C'sink angle", self.cs_angle)

        self.flip = QtWidgets.QCheckBox("Flip drill direction")
        self.bind(self.flip)
        self.form.add("", self.flip)

        self.kind.currentIndexChanged.connect(self._sync_enabled)
        self.through.toggled.connect(self._sync_enabled)

    def _sync_enabled(self):
        kind = self.kind.currentData()
        self.depth.setEnabled(not self.through.isChecked())
        self.cb_diameter.setEnabled(kind != "simple")
        self.cb_depth.setEnabled(kind == "counterbore")
        self.cs_angle.setEnabled(kind == "countersink")

    def load(self):
        pos = self.kind.findData(self.feature.hole_type)
        self.kind.setCurrentIndex(max(0, pos))
        self.diameter.set_text(self.feature.diameter)
        self.depth.set_text(self.feature.depth)
        self.through.setChecked(self.feature.through)
        self.cb_diameter.set_text(self.feature.cb_diameter)
        self.cb_depth.set_text(self.feature.cb_depth)
        self.cs_angle.set_text(self.feature.cs_angle)
        self.flip.setChecked(self.feature.flip)
        self._sync_enabled()

    def store(self):
        self.feature.sketch_id = int(self.sketch.currentData() or 0)
        self.feature.hole_type = self.kind.currentData()
        self.feature.diameter = self.diameter.text()
        self.feature.depth = self.depth.text()
        self.feature.through = self.through.isChecked()
        self.feature.cb_diameter = self.cb_diameter.text()
        self.feature.cb_depth = self.cb_depth.text()
        self.feature.cs_angle = self.cs_angle.text()
        self.feature.flip = self.flip.isChecked()


class EdgeOpDialog(FeatureDialog):
    """Shared base for fillet and chamfer."""

    noun = "edge"
    size_label = "Radius"

    def build(self):
        self.picker = SelectionField("Select edges")
        self.picker.pick_toggled.connect(self._toggle_pick)
        self.picker.cleared.connect(self._clear)
        self.form.add("Edges", self.picker)

        self.all_edges = QtWidgets.QCheckBox("All edges of the body")
        self.bind(self.all_edges)
        self.form.add("", self.all_edges)

        self.size = self.expression(self._size_value())
        self.form.add(self.size_label, self.size)

        self.all_edges.toggled.connect(self._sync_enabled)
        QtCore.QTimer.singleShot(0, lambda: self.picker.set_picking(True))

    def _size_value(self) -> str:
        return "2"

    def _sync_enabled(self):
        on = not self.all_edges.isChecked()
        self.picker.setEnabled(on)
        if not on:
            self.picker.set_picking(False)

    def wants_selection(self):
        return "edge" if self.picker.picking else None

    def _toggle_pick(self, on: bool):
        self.host.set_pick_mode("edge" if on else None)

    def _clear(self):
        self.feature.refs = RefSet()
        self.picker.set_count(0, self.noun)
        self.host.viewport.clear_selection()
        self.preview()

    def on_selection(self):
        """Each pick *adds* to the set, the way Inventor's fillet dialog works.

        Accumulating here rather than reading the viewport's selection is what
        makes multi-edge picking possible at all: the live preview rebuilds the
        body after every pick, which necessarily clears the OCCT selection.
        """
        if not self.picker.picking or self._in_selection:
            return
        picked = self.host.viewport.selected_edges()
        if not picked:
            return
        base = self.host.pick_shape()
        if base is None:
            return

        self._in_selection = True
        try:
            fresh = RefSet()
            fresh.capture_from(base, "edge", picked)
            for ref in fresh:
                existing = self._matching_ref(ref)
                if existing is not None:
                    self.feature.refs.refs.remove(existing)  # click again to drop
                else:
                    self.feature.refs.add(ref)

            self.picker.set_count(len(self.feature.refs), self.noun)
            self.host.viewport.clear_selection()
        finally:
            self._in_selection = False
        self.preview()

    def _matching_ref(self, ref):
        import math
        for existing in self.feature.refs:
            if existing.same_as(ref):
                return existing
        return None

    def load(self):
        self.picker.set_count(len(self.feature.refs), self.noun)
        self.all_edges.setChecked(self.feature.all_edges)
        self._sync_enabled()


class FilletDialog(EdgeOpDialog):
    size_label = "Radius"

    def __init__(self, host, feature, is_new, snapshot=None):
        super().__init__(host, feature, "Fillet", "fillet", is_new, snapshot)

    def _size_value(self):
        return self.feature.radius

    def load(self):
        super().load()
        self.size.set_text(self.feature.radius)

    def store(self):
        self.feature.radius = self.size.text()
        self.feature.all_edges = self.all_edges.isChecked()


class ChamferDialog(EdgeOpDialog):
    size_label = "Distance"

    def __init__(self, host, feature, is_new, snapshot=None):
        super().__init__(host, feature, "Chamfer", "chamfer", is_new, snapshot)

    def _size_value(self):
        return self.feature.distance

    def load(self):
        super().load()
        self.size.set_text(self.feature.distance)

    def store(self):
        self.feature.distance = self.size.text()
        self.feature.all_edges = self.all_edges.isChecked()


class ShellDialog(FeatureDialog):
    def __init__(self, host, feature, is_new, snapshot=None):
        super().__init__(host, feature, "Shell", "shell", is_new, snapshot)

    def build(self):
        self.picker = SelectionField("Select faces")
        self.picker.pick_toggled.connect(
            lambda on: self.host.set_pick_mode("face" if on else None))
        self.picker.cleared.connect(self._clear)
        self.form.add("Open faces", self.picker)

        hint = QtWidgets.QLabel("Faces picked here are removed, leaving the "
                                "body open.")
        hint.setProperty("hint", True)
        hint.setWordWrap(True)
        self.form.add("", hint)

        self.thickness = self.expression(self.feature.thickness)
        self.form.add("Wall", self.thickness)

        QtCore.QTimer.singleShot(0, lambda: self.picker.set_picking(True))

    def wants_selection(self):
        return "face" if self.picker.picking else None

    def _clear(self):
        self.feature.refs = RefSet()
        self.picker.set_count(0, "face")
        self.host.viewport.clear_selection()
        self.preview()

    def on_selection(self):
        # additive, for the same reason as the fillet/chamfer picker
        if not self.picker.picking or self._in_selection:
            return
        picked = self.host.viewport.selected_faces()
        if not picked:
            return
        base = self.host.pick_shape()
        if base is None:
            return

        import math
        self._in_selection = True
        try:
            fresh = RefSet()
            fresh.capture_from(base, "face", picked)
            for ref in fresh:
                match = next((e for e in self.feature.refs
                              if e.same_as(ref)), None)
                if match is not None:
                    self.feature.refs.refs.remove(match)
                else:
                    self.feature.refs.add(ref)

            self.picker.set_count(len(self.feature.refs), "face")
            self.host.viewport.clear_selection()
        finally:
            self._in_selection = False
        self.preview()

    def load(self):
        self.picker.set_count(len(self.feature.refs), "face")
        self.thickness.set_text(self.feature.thickness)

    def store(self):
        self.feature.thickness = self.thickness.text()


class AxisField(QtWidgets.QWidget):
    """Inventor's direction pick: quick buttons for the origin's own, or
    something picked in the view or the tree, and a flip.

    For a direction or an axis the buttons are X, Y and Z and a pick is a
    straight edge, a round edge or face, a flat face or a work axis; for a
    mirror plane they are XY, XZ and YZ and a pick is a flat face or a
    work plane.  A pick wins over a name, the way the feature reads it.
    """

    changed = QtCore.Signal()

    def __init__(self, dialog: "FeatureDialog", names, noun: str,
                 tree_kind: str, flip: bool = True) -> None:
        super().__init__()
        self.dialog = dialog
        self.noun = noun
        self.tree_kind = tree_kind
        self.name = names[0]
        self.ref = RefSet()
        self.flipped = False
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        self.buttons: Dict[str, QtWidgets.QToolButton] = {}
        for name in names:
            button = QtWidgets.QToolButton()
            button.setText(name)
            button.setCheckable(True)
            button.setFixedSize(30, 26)
            button.setToolTip("The origin's %s %s" % (name, noun))
            button.clicked.connect(lambda _=False, n=name: self.set_name(n))
            row.addWidget(button)
            self.buttons[name] = button
        mode = "project" if noun != "plane" else "face"
        self.pick = dialog.picker("Select", noun, mode, self._from_view,
                                  self._from_tree)
        self.pick.button.setMinimumWidth(72)
        self.pick.cleared.connect(lambda: self.set_name(names[0]))
        self.pick.setToolTip(
            "Pick %s in the view or the tree" % (
                "a flat face or a work plane" if noun == "plane" else
                "a straight edge, a round edge or face, a flat face or a "
                "work axis"))
        row.addWidget(self.pick, 1)
        self.flip_button = None
        if flip:
            self.flip_button = QtWidgets.QToolButton()
            self.flip_button.setIcon(icons.icon("dir_flipped", 18))
            self.flip_button.setCheckable(True)
            self.flip_button.setFixedSize(30, 26)
            self.flip_button.setToolTip("Flip: the other way")
            self.flip_button.toggled.connect(self._flip)
            row.addWidget(self.flip_button)
        self._show()

    def set_name(self, name: str) -> None:
        self.name = name
        self.ref = RefSet()
        self._show()
        self.changed.emit()

    def set_value(self, name: str, ref: RefSet, flipped: bool = False) -> None:
        self.name = name or self.name
        self.ref = ref if ref is not None else RefSet()
        self.flipped = flipped
        if self.flip_button is not None:
            self.flip_button.blockSignals(True)
            self.flip_button.setChecked(flipped)
            self.flip_button.blockSignals(False)
        self._show()

    def _flip(self, on: bool) -> None:
        self.flipped = on
        self.changed.emit()

    def _show(self) -> None:
        picked = bool(len(self.ref))
        for name, button in self.buttons.items():
            button.setChecked(not picked and name == self.name)
        if picked:
            text = "a picked %s" % ("face" if self.noun == "plane"
                                    else "edge or face")
        elif self.name in self.buttons:
            text = "%s %s" % (self.name, self.noun)
        else:
            text = self.name
        self.pick.count.setText(text)
        self.pick.count.setStyleSheet("color: %s;" % C.ok)

    def _from_view(self, shapes) -> None:
        from ..core.features import axis_from_shape, plane_from_face
        from OCP.TopAbs import TopAbs_FACE
        base = self.dialog.host.pick_shape()
        if base is None:
            return
        for shape in shapes:
            if self.noun == "plane":
                if (shape.ShapeType() != TopAbs_FACE
                        or plane_from_face(shape) is None):
                    continue
                kind = "face"
            else:
                if axis_from_shape(shape) is None:
                    continue
                kind = ("face" if shape.ShapeType() == TopAbs_FACE
                        else "edge")
            ref = RefSet()
            ref.capture_from(base, kind, [shape])
            if len(ref):
                self.ref = ref
                self._show()
                self.pick.set_picking(False)
                self.changed.emit()
                return

    def _from_tree(self, kind: str, key: str) -> bool:
        from ..core.features import WorkAxisFeature, WorkPlaneFeature
        if kind == "feature":
            # a work axis or work plane is a feature row of its own
            try:
                made = self.dialog.doc.feature(int(key))
            except (TypeError, ValueError):
                made = None
            wanted = (WorkPlaneFeature if self.noun == "plane"
                      else WorkAxisFeature)
            if not isinstance(made, wanted):
                return False
            key = made.name
        elif kind != self.tree_kind:
            return False
        self.set_name(str(key))
        self.pick.set_picking(False)
        return True


class EndField(QtWidgets.QWidget):
    """Where an extrusion starts or stops: a plane off the list, or picked
    in the tree, or a face, or a corner of the part, picked in the view.

    A pick wins over the list, which stands aside until it is cleared, the
    way the feature reads it.  ``blank`` is what the list says for nothing
    chosen, the sketch's own plane for From; without it a plane is always
    chosen.
    """

    changed = QtCore.Signal()

    def __init__(self, dialog: "FeatureDialog", current: str,
                 blank: Optional[str] = None, points: bool = False,
                 curved: bool = True) -> None:
        super().__init__()
        self.dialog = dialog
        self.points = points
        self.curved = curved
        self.ref = RefSet()
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        # the list previews by itself when it changes, as every combo does
        self.combo = dialog.plane_combo(current)
        if blank is not None:
            self.combo.blockSignals(True)
            self.combo.insertItem(0, icons.icon("sketch", 15), blank, "")
            if not current:
                self.combo.setCurrentIndex(0)
            self.combo.blockSignals(False)
        row.addWidget(self.combo, 1)
        mode = "face_vertex" if points else "face"
        self.pick = dialog.picker("Select", "face", mode, self._from_view,
                                  self._from_tree)
        self.pick.button.setMinimumWidth(72)
        self.pick.cleared.connect(self._clear)
        self.pick.setToolTip(
            "Pick %s in the view, or a plane in the tree" % (
                "a face or a corner of the part" if points else
                "a face of the part" if curved else
                "a flat face of the part"))
        row.addWidget(self.pick)
        self._show()

    @property
    def name(self) -> str:
        return "" if len(self.ref) else (self.combo.currentData() or "")

    def is_set(self) -> bool:
        return bool(len(self.ref) or self.combo.currentData())

    def set_value(self, name: str, ref: Optional[RefSet]) -> None:
        self.ref = ref if ref is not None else RefSet()
        pos = self.combo.findData(name or "")
        if pos >= 0:
            self.combo.blockSignals(True)
            self.combo.setCurrentIndex(pos)
            self.combo.blockSignals(False)
        self._show()

    def _show(self) -> None:
        picked = bool(len(self.ref))
        self.combo.setEnabled(not picked)
        if picked:
            kind = self.ref.refs[0].kind
            self.pick.count.setText("a picked %s" % (
                "point" if kind == "vertex" else kind))
            self.pick.count.setStyleSheet("color: %s;" % C.ok)
        else:
            self.pick.count.setText("")

    def _clear(self) -> None:
        self.ref = RefSet()
        self._show()
        self.changed.emit()

    def _from_view(self, shapes) -> None:
        from ..core.features import plane_from_face
        from OCP.TopAbs import TopAbs_FACE, TopAbs_VERTEX
        base = self.dialog.host.pick_shape()
        if base is None:
            return
        for shape in shapes:
            if shape.ShapeType() == TopAbs_VERTEX and self.points:
                kind = "vertex"
            elif shape.ShapeType() == TopAbs_FACE and (
                    self.curved or plane_from_face(shape) is not None):
                kind = "face"
            else:
                continue
            ref = RefSet()
            ref.capture_from(base, kind, [shape])
            if len(ref):
                self.ref = ref
                self._show()
                self.pick.set_picking(False)
                self.changed.emit()
                return

    def _from_tree(self, kind: str, key: str) -> bool:
        from ..core.features import WorkPlaneFeature
        if kind == "feature":
            try:
                made = self.dialog.doc.feature(int(key))
            except (TypeError, ValueError):
                made = None
            if not isinstance(made, WorkPlaneFeature):
                return False
            key = made.name
        elif kind != "plane":
            return False
        pos = self.combo.findData(str(key))
        if pos < 0:
            return False
        self.ref = RefSet()
        self.combo.setCurrentIndex(pos)
        self._show()
        self.pick.set_picking(False)
        self.changed.emit()
        return True


class PatternDialog(FeatureDialog):
    """Inventor's Rectangular and Circular Pattern, in one dialog.

    The strip down the right says what is patterned, features or solids,
    and which kind of pattern; the features or solids are picked, and so
    are the directions and the axis, with X, Y and Z a click away.
    """

    KINDS = [("rectangular", "pattern", "Rectangular Pattern"),
             ("circular", "pattern_circ", "Circular Pattern")]
    WHAT = [("features", "extrude", "Pattern features"),
            ("bodies", "box", "Pattern solids")]

    def __init__(self, host, feature, is_new, snapshot=None):
        super().__init__(host, feature, "Pattern", "pattern", is_new, snapshot)

    def build(self):
        self.of = SegmentedControl(self.WHAT, vertical=True)
        self.side.addWidget(self.of)
        self.side.addSpacing(10)
        self.kind = SegmentedControl(self.KINDS, vertical=True)
        self.side.addWidget(self.kind)
        self.side.addStretch(1)
        self.of.changed.connect(lambda _k: (self._sync_of(), self.preview()))
        self.kind.changed.connect(lambda _k: (self._sync_enabled(),
                                              self.preview()))

        self.parents = self.feature_picker(None, self.feature.parents)
        self.form.add("Features", self.parents)
        self.bodies = self.solids_picker(self.feature.bodies)
        self.form.add("Solids", self.bodies)

        self.copies = QtWidgets.QComboBox()
        self.copies.addItem("Join to the solid", JOIN)
        self.copies.addItem("A new solid each", NEW_BODY)
        self.bind(self.copies)
        self.form.add("Copies", self.copies)

        self.form.add_section("Direction 1")
        self.dir1 = AxisField(self, ("X", "Y", "Z"), "axis", "axis")
        self.dir1.changed.connect(self.preview)
        self.form.add("Direction", self.dir1)
        self.count1 = self.expression(self.feature.count1, "")
        self.form.add("Count", self.count1)
        self.spacing1 = self.expression(self.feature.spacing1)
        self.form.add("Spacing", self.spacing1)

        self.form.add_section("Direction 2")
        self.dir2 = AxisField(self, ("X", "Y", "Z"), "axis", "axis")
        self.dir2.changed.connect(self.preview)
        self.form.add("Direction", self.dir2)
        self.count2 = self.expression(self.feature.count2, "")
        self.form.add("Count", self.count2)
        self.spacing2 = self.expression(self.feature.spacing2)
        self.form.add("Spacing", self.spacing2)

        self.form.add_section("Rotation")
        self.axis = AxisField(self, ("X", "Y", "Z"), "axis", "axis")
        self.axis.changed.connect(self.preview)
        self.form.add("Axis", self.axis)
        self.full = QtWidgets.QCheckBox("Full circle")
        self.bind(self.full)
        self.form.add("", self.full)
        self.angle = self.expression(self.feature.angle, "deg")
        self.form.add("Angle", self.angle)
        self.full.toggled.connect(lambda _on: self._sync_enabled())

    def _sync_enabled(self):
        rect = self.kind.value() == "rectangular"
        for w in (self.dir1, self.count1, self.spacing1, self.dir2,
                  self.count2, self.spacing2):
            self.form.set_visible(w, rect)
        for w in (self.axis, self.full, self.angle):
            self.form.set_visible(w, not rect)
        self.form.set_section_visible("Direction 1", rect)
        self.form.set_section_visible("Direction 2", rect)
        self.form.set_section_visible("Rotation", not rect)
        self.angle.setEnabled(not self.full.isChecked())
        # the count of a circular pattern is its only count
        if not rect:
            self.form.set_visible(self.count1, True)

    def _sync_of(self):
        bodies = self.of.value() == "bodies"
        self.form.set_visible(self.parents, not bodies)
        self.form.set_visible(self.bodies, bodies)
        self.form.set_visible(self.copies, bodies)

    def load(self):
        self.kind.set_value(self.feature.mode)
        self.of.set_value(self.feature.of)
        self.copies.setCurrentIndex(
            max(0, self.copies.findData(self.feature.copies)))
        self.count1.set_text(self.feature.count1)
        self.spacing1.set_text(self.feature.spacing1)
        self.count2.set_text(self.feature.count2)
        self.spacing2.set_text(self.feature.spacing2)
        self.angle.set_text(self.feature.angle)
        self.full.setChecked(self.feature.full_circle)
        self.dir1.set_value(self.feature.dir1, self.feature.dir1_ref,
                            self.feature.flip1)
        self.dir2.set_value(self.feature.dir2, self.feature.dir2_ref,
                            self.feature.flip2)
        self.axis.set_value(self.feature.axis, self.feature.axis_ref,
                            self.feature.flip1)
        self._sync_of()
        self._sync_enabled()

    def store(self):
        self.feature.mode = self.kind.value()
        self.feature.of = self.of.value() or "features"
        self.feature.copies = self.copies.currentData() or JOIN
        self.feature.bodies = self.picked_solids()
        self.feature.parents = self.picked_features()
        self.feature.count1 = self.count1.text()
        self.feature.spacing1 = self.spacing1.text()
        self.feature.count2 = self.count2.text()
        self.feature.spacing2 = self.spacing2.text()
        self.feature.angle = self.angle.text()
        self.feature.full_circle = self.full.isChecked()
        rect = self.feature.mode == "rectangular"
        self.feature.dir1, self.feature.dir1_ref = self.dir1.name, self.dir1.ref
        self.feature.dir2, self.feature.dir2_ref = self.dir2.name, self.dir2.ref
        self.feature.axis, self.feature.axis_ref = self.axis.name, self.axis.ref
        self.feature.flip1 = (self.dir1.flipped if rect
                              else self.axis.flipped)
        self.feature.flip2 = self.dir2.flipped


class MirrorDialog(FeatureDialog):
    """Inventor's Mirror: features or solids down the side, both picked,
    and the plane picked or one of the origin's three."""

    WHAT = [("features", "extrude", "Mirror features"),
            ("body", "box", "Mirror solids")]

    def __init__(self, host, feature, is_new, snapshot=None):
        super().__init__(host, feature, "Mirror", "mirror", is_new, snapshot)

    def build(self):
        self.scope = SegmentedControl(self.WHAT, vertical=True)
        self.side.addWidget(self.scope)
        self.side.addStretch(1)
        self.scope.changed.connect(lambda _k: (self._sync_enabled(),
                                               self.preview()))

        self.parents = self.feature_picker(None, self.feature.parents)
        self.form.add("Features", self.parents)
        self.solids = self.solids_picker(self.feature.solids)
        self.solids.setToolTip(
            "The solids to mirror, picked by a face or in the tree. None "
            "picked: the whole part.")
        self.form.add("Solids", self.solids)

        self.plane = AxisField(self, ("XY", "XZ", "YZ"), "plane", "plane",
                               flip=False)
        self.plane.changed.connect(self.preview)
        self.form.add("Mirror Plane", self.plane)

    def _sync_enabled(self):
        features = self.scope.value() == "features"
        self.form.set_visible(self.parents, features)
        self.form.set_visible(self.solids, not features)

    def load(self):
        self.scope.set_value(self.feature.scope)
        self.plane.set_value(self.feature.plane, self.feature.plane_ref)
        self._sync_enabled()

    def store(self):
        self.feature.scope = self.scope.value() or "body"
        self.feature.parents = self.picked_features()
        self.feature.solids = (self.picked_solids()
                               if self.feature.scope == "body" else [])
        self.feature.plane = self.plane.name
        self.feature.plane_ref = self.plane.ref


class SplitDialog(FeatureDialog):
    """Inventor's Split: the tool, the method, and what it splits."""

    METHODS = [
        ("faces", "split_faces",
         "Split Faces - divide faces where the tool crosses them; the solid "
         "stays whole"),
        ("solid", "split_solid",
         "Split Solid - cut a solid in two along the tool, each half a "
         "solid of its own"),
    ]

    def __init__(self, host, feature, is_new, snapshot=None):
        super().__init__(host, feature, "Split", "split", is_new, snapshot)

    def build(self):
        self.form.add_section("Input Geometry")
        self.plane = self.plane_combo(self.feature.plane)
        self.plane.setToolTip(
            "An origin plane or a work plane to split along, or pick a flat "
            "face of the part with the button beside it")
        self.tool_pick = SelectionField("Select face")
        self.tool_pick.pick_toggled.connect(
            lambda on: self._arm(self.tool_pick if on else None))
        self.tool_pick.cleared.connect(self._clear_tool)
        tool = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(tool)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.plane, 1)
        row.addWidget(self.tool_pick)
        self.form.add("Split Tool", tool)

        self.form.add_section("Method")
        self.method = SegmentedControl(self.METHODS)
        self.bind(self.method)
        self.form.add("Method", self.method)

        self.faces_pick = SelectionField("Select faces")
        self.faces_pick.pick_toggled.connect(
            lambda on: self._arm(self.faces_pick if on else None))
        self.faces_pick.cleared.connect(self._clear_faces)
        self.form.add("Faces", self.faces_pick)
        self.all_faces = QtWidgets.QCheckBox("All Faces")
        self.all_faces.setToolTip("Split every face the tool crosses")
        self.bind(self.all_faces)
        self.form.add("", self.all_faces)

        self.solids_row()
        self.method.changed.connect(lambda _k: self._sync_enabled())
        self.all_faces.toggled.connect(lambda _on: self._sync_enabled())

    # -- which field is picking --------------------------------------------

    def _arm(self, field) -> None:
        for candidate in (self.tool_pick, self.faces_pick):
            if candidate is not field and candidate.picking:
                candidate.blockSignals(True)
                candidate.set_picking(False)
                candidate.blockSignals(False)
        self.host.set_pick_mode("face" if field is not None else None)

    def wants_selection(self):
        return ("face" if self.tool_pick.picking or self.faces_pick.picking
                else None)

    def on_selection(self):
        if self._in_selection:
            return
        picked = self.host.viewport.selected_faces()
        base = self.host.pick_shape()
        if not picked or base is None:
            return
        self._in_selection = True
        try:
            if self.tool_pick.picking:
                from ..core.features import plane_from_face
                flat = [f for f in picked if plane_from_face(f) is not None]
                if flat:
                    self.feature.tool = RefSet()
                    self.feature.tool.capture_from(base, "face", flat[:1])
                    self.tool_pick.set_count(1, "face")
                    self.tool_pick.set_picking(False)
                    if (self.method.value() == "faces"
                            and not self.all_faces.isChecked()):
                        self.faces_pick.set_picking(True)
                    else:
                        self._arm(None)
            elif self.faces_pick.picking:
                fresh = RefSet()
                fresh.capture_from(base, "face", picked)
                for ref in fresh:
                    match = next((e for e in self.feature.faces
                                  if e.same_as(ref)), None)
                    if match is not None:
                        self.feature.faces.refs.remove(match)
                    else:
                        self.feature.faces.add(ref)
                self.faces_pick.set_count(len(self.feature.faces), "face")
            self.host.viewport.clear_selection()
        finally:
            self._in_selection = False
        self._sync_enabled()
        self.preview()

    def _clear_tool(self):
        self.feature.tool = RefSet()
        self.tool_pick.set_count(0, "face")
        self._sync_enabled()
        self.preview()

    def _clear_faces(self):
        self.feature.faces = RefSet()
        self.faces_pick.set_count(0, "face")
        self.host.viewport.clear_selection()
        self.preview()

    def _sync_enabled(self):
        faces = self.method.value() == "faces"
        self.form.set_visible(self.faces_pick, faces)
        self.form.set_visible(self.all_faces, faces)
        self.faces_pick.setEnabled(not self.all_faces.isChecked())
        if getattr(self, "solids", None) is not None:
            self.form.set_visible(self.solids, not faces)
        # a picked face is the tool; the plane list stands aside for it
        self.plane.setEnabled(not len(self.feature.tool))

    def load(self):
        self.method.set_value(self.feature.mode)
        self.all_faces.setChecked(self.feature.all_faces)
        self.tool_pick.set_count(len(self.feature.tool), "face")
        self.faces_pick.set_count(len(self.feature.faces), "face")
        self._sync_enabled()

    def store(self):
        self.feature.mode = self.method.value()
        self.feature.plane = self.plane.currentData() or "XY"
        self.feature.all_faces = self.all_faces.isChecked()
        self.feature.solids = (self.picked_solids()
                               if self.feature.mode == "solid" else [])


class PrimitiveDialog(FeatureDialog):
    LABELS = {
        "box": ("Length X", "Length Y", "Length Z"),
        "cylinder": ("Radius", "Height", None),
        "sphere": ("Radius", None, None),
        "cone": ("Bottom radius", "Top radius", "Height"),
        "torus": ("Ring radius", "Tube radius", None),
    }

    def __init__(self, host, feature, is_new, snapshot=None):
        super().__init__(host, feature, "Primitive", "box", is_new, snapshot)

    def build(self):
        self.kind = QtWidgets.QComboBox()
        for key, label, icon in (("box", "Box", "box"),
                                 ("cylinder", "Cylinder", "cylinder"),
                                 ("sphere", "Sphere", "sphere"),
                                 ("cone", "Cone", "cylinder"),
                                 ("torus", "Torus", "sphere")):
            self.kind.addItem(icons.icon(icon, 15), label, key)
        self.bind(self.kind)
        self.form.add("Shape", self.kind)

        self.boolean_row()

        self.form.add_separator()

        self.a = self.expression(self.feature.a)
        self.form.add("A", self.a)
        self.b = self.expression(self.feature.b)
        self.form.add("B", self.b)
        self.c = self.expression(self.feature.c)
        self.form.add("C", self.c)

        self.form.add_separator()
        self.ox = self.expression(self.feature.origin[0])
        self.form.add("Origin X", self.ox)
        self.oy = self.expression(self.feature.origin[1])
        self.form.add("Origin Y", self.oy)
        self.oz = self.expression(self.feature.origin[2])
        self.form.add("Origin Z", self.oz)

        self.centred = QtWidgets.QCheckBox("Centre on the origin")
        self.bind(self.centred)
        self.form.add("", self.centred)

        self.kind.currentIndexChanged.connect(self._sync_labels)

    def _sync_labels(self):
        labels = self.LABELS.get(self.kind.currentData(),
                                 ("A", "B", "C"))
        for widget, text in zip((self.a, self.b, self.c), labels):
            widget.setEnabled(text is not None)
        # relabel the rows in place
        row_of = {id(self.a): None, id(self.b): None, id(self.c): None}
        grid = self.form.grid
        for row in range(grid.rowCount()):
            item = grid.itemAtPosition(row, 1)
            if item is None:
                continue
            w = item.widget()
            if id(w) in row_of:
                label_item = grid.itemAtPosition(row, 0)
                if label_item and label_item.widget():
                    idx = [self.a, self.b, self.c].index(w)
                    label_item.widget().setText(labels[idx] or "-")

    def load(self):
        pos = self.kind.findData(self.feature.kind)
        self.kind.setCurrentIndex(max(0, pos))
        self.load_boolean()
        self.a.set_text(self.feature.a)
        self.b.set_text(self.feature.b)
        self.c.set_text(self.feature.c)
        self.ox.set_text(self.feature.origin[0])
        self.oy.set_text(self.feature.origin[1])
        self.oz.set_text(self.feature.origin[2])
        self.centred.setChecked(self.feature.centred)
        self._sync_labels()

    def store(self):
        self.feature.kind = self.kind.currentData()
        self.store_boolean()
        self.feature.a = self.a.text()
        self.feature.b = self.b.text()
        self.feature.c = self.c.text()
        self.feature.origin = (self.ox.text(), self.oy.text(), self.oz.text())
        self.feature.centred = self.centred.isChecked()
        self.feature.name = self.feature.name


class WorkPlaneDialog(FeatureDialog):
    def __init__(self, host, feature, is_new, snapshot=None):
        super().__init__(host, feature, "Work Plane", "plane", is_new, snapshot)

    def build(self):
        row = QtWidgets.QWidget()
        line = QtWidgets.QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        self.base_label = QtWidgets.QLabel()
        line.addWidget(self.base_label, 1)
        repick = QtWidgets.QPushButton("Pick again")
        repick.setIcon(icons.icon("select", 15))
        repick.clicked.connect(self._repick)
        line.addWidget(repick)
        self.form.add("Base", row)

        # a datum plane can still be chosen from the list, for face-free models
        self.base = self.plane_combo(self.feature.base)
        self.form.add("Datum", self.base)

        self.form.add_separator()

        self.offset = self.expression(self.feature.offset)
        self.form.add("Offset", self.offset)
        self.angle = self.expression(self.feature.angle, "deg")
        self.form.add("Tilt", self.angle)

        self.flip = QtWidgets.QCheckBox("Offset the other way")
        self.bind(self.flip)
        self.form.add("", self.flip)

    def _repick(self):
        """Drop this plane and restart the pick-and-drag gesture."""
        self.cancel()
        QtCore.QTimer.singleShot(0, self.host.start_work_plane)

    def _sync_base(self):
        on_face = self.feature.face_ref is not None
        self.base_label.setText("Model face" if on_face
                                else "%s Plane" % self.feature.base)
        self.base_label.setStyleSheet("color: %s;" % (C.ok if on_face
                                                      else C.text))
        self.base.setEnabled(not on_face)

    def load(self):
        self.offset.set_text(self.feature.offset)
        self.angle.set_text(self.feature.angle)
        self.flip.setChecked(self.feature.flip)
        self._sync_base()

    def store(self):
        if self.feature.face_ref is None:
            self.feature.base = self.base.currentData()
        self.feature.offset = self.offset.text()
        self.feature.angle = self.angle.text()
        self.feature.flip = self.flip.isChecked()


class WorkAxisDialog(FeatureDialog):
    """Where a work axis comes from: an origin axis, two planes, or a pick.

    A straight edge or a round face selected before pressing Axis is taken
    straight away; the planes and origin choices need nothing picked.
    """

    MODES = (("planes", "Where two planes meet"),
             ("origin", "Origin axis"),
             ("edge", "Straight edge or round face"))

    def __init__(self, host, feature, is_new, snapshot=None):
        super().__init__(host, feature, "Work Axis", "axis", is_new, snapshot)

    def build(self):
        self.mode = QtWidgets.QComboBox()
        for key, label in self.MODES:
            self.mode.addItem(label, key)
        self.bind(self.mode)
        self.form.add("Axis", self.mode)

        self.origin_axis = QtWidgets.QComboBox()
        for name in ("X", "Y", "Z"):
            self.origin_axis.addItem(icons.icon("axis", 15),
                                     "%s Axis" % name, name)
        self.bind(self.origin_axis)
        self.form.add("Origin", self.origin_axis)

        self.plane_a = self.plane_combo(self.feature.plane_a)
        self.form.add("First plane", self.plane_a)
        self.plane_b = self.plane_combo(self.feature.plane_b)
        self.form.add("Second plane", self.plane_b)

        self.picked = QtWidgets.QLabel()
        self.picked.setWordWrap(True)
        self.form.add("Picked", self.picked)

        self.flip = QtWidgets.QCheckBox("Reverse direction")
        self.flip.setToolTip("Which way a pattern along this axis runs")
        self.bind(self.flip)
        self.form.add("", self.flip)

        self.mode.currentIndexChanged.connect(lambda _i: self._sync())

    def _sync(self):
        mode = self.mode.currentData()
        self.form.set_visible(self.origin_axis, mode == "origin")
        self.form.set_visible(self.plane_a, mode == "planes")
        self.form.set_visible(self.plane_b, mode == "planes")
        self.form.set_visible(self.picked, mode == "edge")
        if self.feature.ref is not None:
            self.picked.setText("Model %s" % self.feature.ref.kind)
            self.picked.setStyleSheet("color: %s;" % C.ok)
        else:
            self.picked.setText("Select a straight edge or a round face "
                                "first, then press Axis.")
            self.picked.setStyleSheet("color: %s;" % C.warn)

    def load(self):
        self.mode.setCurrentIndex(max(0, self.mode.findData(self.feature.mode)))
        self.origin_axis.setCurrentIndex(
            max(0, self.origin_axis.findData(self.feature.origin_axis)))
        self.flip.setChecked(self.feature.flip)
        self._sync()

    def store(self):
        self.feature.mode = self.mode.currentData()
        self.feature.origin_axis = self.origin_axis.currentData()
        self.feature.plane_a = self.plane_a.currentData()
        self.feature.plane_b = self.plane_b.currentData()
        self.feature.flip = self.flip.isChecked()


class MoveDialog(FeatureDialog):
    def __init__(self, host, feature, is_new, snapshot=None):
        super().__init__(host, feature, "Move Body", "move", is_new, snapshot)

    def build(self):
        self.dx = self.expression(self.feature.dx)
        self.form.add("Move X", self.dx)
        self.dy = self.expression(self.feature.dy)
        self.form.add("Move Y", self.dy)
        self.dz = self.expression(self.feature.dz)
        self.form.add("Move Z", self.dz)
        self.form.add_separator()
        self.rx = self.expression(self.feature.rx, "deg")
        self.form.add("Rotate X", self.rx)
        self.ry = self.expression(self.feature.ry, "deg")
        self.form.add("Rotate Y", self.ry)
        self.rz = self.expression(self.feature.rz, "deg")
        self.form.add("Rotate Z", self.rz)

    def load(self):
        for widget, name in ((self.dx, "dx"), (self.dy, "dy"), (self.dz, "dz"),
                             (self.rx, "rx"), (self.ry, "ry"), (self.rz, "rz")):
            widget.set_text(getattr(self.feature, name))

    def store(self):
        for widget, name in ((self.dx, "dx"), (self.dy, "dy"), (self.dz, "dz"),
                             (self.rx, "rx"), (self.ry, "ry"), (self.rz, "rz")):
            setattr(self.feature, name, widget.text())


DIALOGS = {
    ExtrudeFeature: ExtrudeDialog,
    RevolveFeature: RevolveDialog,
    SweepFeature: SweepDialog,
    LoftFeature: LoftDialog,
    HoleFeature: HoleDialog,
    FilletFeature: FilletDialog,
    ChamferFeature: ChamferDialog,
    ShellFeature: ShellDialog,
    PatternFeature: PatternDialog,
    MirrorFeature: MirrorDialog,
    PrimitiveFeature: PrimitiveDialog,
    WorkPlaneFeature: WorkPlaneDialog,
    WorkAxisFeature: WorkAxisDialog,
    MoveFeature: MoveDialog,
    SplitFeature: SplitDialog,
}


def dialog_for(host, feature: Feature, is_new: bool,
               snapshot: Optional[str] = None) -> Optional[FeatureDialog]:
    cls = DIALOGS.get(type(feature))
    return cls(host, feature, is_new, snapshot) if cls else None



class NewDocumentDialog(QtWidgets.QDialog):
    """What kind of document New should make.

    New used to make a part whatever you were doing, which is wrong the
    moment there is more than one kind: somebody in an assembly pressing
    New usually wants another assembly, or a drawing of the one they are
    already in.
    """

    KINDS = (
        (fileformat.PART, "box", "Part",
         "A solid, built on a feature tree"),
        (fileformat.ASSEMBLY, "import", "Assembly",
         "Parts and sub-assemblies, placed and constrained"),
        (fileformat.DRAWING, "dimension", "Drawing",
         "Views, dimensions and a title block"),
        (fileformat.CAM, "section", "CAM Sheet",
         "Flat parts nested on stock, and the toolpaths for them"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New")
        self.setWindowIcon(icons.icon("new", 24))
        self.setMinimumWidth(420)
        self.chosen: Optional[str] = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        self.list = QtWidgets.QListWidget()
        self.list.setIconSize(QtCore.QSize(28, 28))
        self.list.setSpacing(1)
        for kind, icon_name, title, hint in self.KINDS:
            item = QtWidgets.QListWidgetItem(
                icons.icon(icon_name, 28), "%s\n%s" % (title, hint))
            item.setData(QtCore.Qt.UserRole, kind)
            self.list.addItem(item)
        self.list.setCurrentRow(0)
        self.list.itemActivated.connect(lambda _i: self.accept())
        layout.addWidget(self.list, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self.chosen = str(item.data(QtCore.Qt.UserRole))
        super().accept()

    @classmethod
    def ask(cls, parent=None) -> Optional[str]:
        dialog = cls(parent)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return None
        return dialog.chosen
