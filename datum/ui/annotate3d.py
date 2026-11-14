"""The part's Annotate tab: dimensions and hole notes on the 3D model.

Dimension takes what is clicked: a round edge or face gives its diameter
at once; a straight edge waits for a second pick, a distance to it, or
Enter for its own length; anything else waits for a second pick.  Hole
Note takes the bore of a hole and writes the note a drawing would.  Both
are drawn on the model after every rebuild and listed under Annotations in
the tree, where they are edited, hidden and deleted.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6 import QtWidgets

from ..core import annotations as core
from .theme import C

DIM = "dim"
HOLE_TOOL = "hole"


class ModelAnnotateTool:
    """Picks for a new model annotation, and drawing the ones there are."""

    def __init__(self, host) -> None:
        self.host = host
        self.mode: Optional[str] = None
        self.picks: List[object] = []

    @property
    def active(self) -> bool:
        return self.mode is not None

    # -- making one ----------------------------------------------------------

    def start(self, mode: str) -> None:
        host = self.host
        if not host.in_part or host.document.shape is None:
            host.status_message.setText(
                "Annotations go on a body: model something first.")
            return
        if host.editor.active:
            host.finish_sketch()
        host.close_dialogs()
        self.mode = mode
        self.picks = []
        host.set_pick_mode("face" if mode == HOLE_TOOL else "annotate")
        host.viewport.clear_selection()
        host.status_message.setStyleSheet("")
        host.status_message.setText(
            "Hole Note: click the bore of a hole. Esc when done."
            if mode == HOLE_TOOL else
            "Dimension: click a round edge or face for its diameter, a "
            "straight edge and Enter for its length, or two faces, edges or "
            "corners for the distance between them. Esc when done.")

    def cancel(self) -> None:
        if self.mode is None:
            return
        self.mode = None
        self.picks = []
        self.host.set_pick_mode(None)
        self.host.viewport.clear_selection()
        self.host.viewport.clear_preview()
        self.host.status_message.setText("Cancelled.")

    def on_selection(self) -> bool:
        """A click in the view while the tool is on.  True when taken."""
        if self.mode is None:
            return False
        picked = list(self.host.viewport.selected_shapes() or [])
        if not picked:
            return True
        self.host.viewport.clear_selection()
        pick = picked[-1]
        if self.mode == HOLE_TOOL:
            from OCP.TopAbs import TopAbs_FACE

            if pick.ShapeType() != TopAbs_FACE \
                    or core.kind_for([pick]) != core.DIAMETER:
                self.host.status_message.setText(
                    "That is not the bore of a hole. Click its round face.")
                return True
            self._make(core.HOLE, [pick])
            return True
        self.picks.append(pick)
        if len(self.picks) == 1:
            kind = core.kind_for(self.picks)
            if kind == core.DIAMETER:
                self._make(core.DIAMETER, self.picks)
                return True
            self.host.status_message.setText(
                "Now the second face, edge or corner, or Enter for this "
                "edge's own length.")
            return True
        self._make(core.LINEAR, self.picks[:2])
        return True

    def accept_single(self) -> bool:
        """Enter: a straight edge picked on its own is dimensioned by its
        length."""
        from OCP.TopAbs import TopAbs_EDGE

        if self.mode != DIM or len(self.picks) != 1 \
                or self.picks[0].ShapeType() != TopAbs_EDGE:
            return False
        self._make(core.LINEAR, self.picks)
        return True

    def _make(self, kind: str, picks) -> None:
        host = self.host
        document = host.document
        refs, kinds = core.capture(document.shape, picks)
        self.picks = []
        if len(refs) != len(picks):
            host.status_message.setText("That cannot be dimensioned.")
            return
        annotation = core.ModelAnnotation(kind=kind, refs=refs,
                                          ref_kinds=kinds)
        core.evaluate(annotation, document.shape)
        if annotation.lost:
            host.status_message.setText(
                "Those cannot be measured against each other.")
            return
        document.push_undo()
        annotation.id = document.new_id()
        annotation.offset = core.default_offset(
            annotation, document.shape, self._view_direction())
        document.annotations.append(annotation)
        document.annotations_visible = True
        document.modified = True
        self.draw()
        host._refresh_trees()
        host._update_title()
        host.status_message.setText(
            "%s: %s. Keep clicking for more, or Esc when done."
            % (annotation.label(), annotation.display))

    def _view_direction(self):
        try:
            return self.host.viewport.view_direction()
        except Exception:
            return None

    # -- after a rebuild -----------------------------------------------------

    def draw(self) -> None:
        """Every shown annotation, measured again and drawn on the model.

        Drawn on the overlay the sketches use, which the window clears and
        redraws after each rebuild."""
        host = self.host
        document = host.document
        notes = getattr(document, "annotations", None) or []
        if not notes or not document.annotations_visible:
            return
        vp = host.viewport
        core.evaluate_all(document)
        for note in notes:
            if note.hidden:
                continue
            # the theme's strongest text colour: black on a light view, near
            # white on a dark one, and never mistaken for a hidden model edge
            colour = C.error if note.lost else C.text_bright
            off = note.offset
            if note.kind == core.LINEAR and len(note.points) == 2:
                p, q = note.points
                p2 = tuple(p[i] + off[i] for i in range(3))
                q2 = tuple(q[i] + off[i] for i in range(3))
                vp.draw_edge(p, p2, colour, 1.0)
                vp.draw_edge(q, q2, colour, 1.0)
                vp.draw_edge(p2, q2, colour, 1.6)
                for end, other in ((p2, q2), (q2, p2)):
                    self._tick(end, other, colour)
                at = tuple((p2[i] + q2[i]) / 2 for i in range(3))
            elif len(note.points) == 2:
                centre, rim = note.points
                at = tuple(rim[i] + off[i] for i in range(3))
                vp.draw_edge(rim, at, colour, 1.4)
                vp.draw_point(rim, colour, 4.0)
            else:
                at = tuple(note.anchor[i] + off[i] for i in range(3))
            text = note.display + ("  (lost)" if note.lost else "")
            vp.draw_text(text, at, colour, 15.0)

    def _tick(self, end, other, colour: str) -> None:
        """A short arrowhead stroke at one end of a dimension line."""
        span = [other[i] - end[i] for i in range(3)]
        n = sum(c * c for c in span) ** 0.5
        if n < 1e-9:
            return
        size = min(2.5, n * 0.2)
        tip = tuple(end[i] + span[i] / n * size for i in range(3))
        self.host.viewport.draw_edge(end, tip, colour, 3.2)

    # -- from the tree ---------------------------------------------------

    def action(self, what: str, annotation_id: int) -> None:
        host = self.host
        document = host.document
        note = next((a for a in getattr(document, "annotations", [])
                     if a.id == annotation_id), None)
        if note is None:
            return
        if what == "delete":
            document.push_undo()
            document.annotations.remove(note)
        elif what == "toggle":
            document.push_undo()
            note.hidden = not note.hidden
        elif what == "text":
            text, ok = QtWidgets.QInputDialog.getText(
                host, "Edit Text",
                "Text for %s. <> stands for the measured value; leave it "
                "empty to show just the value." % note.label(),
                text=note.text or "<>")
            if not ok:
                return
            document.push_undo()
            note.text = "" if text.strip() == "<>" else text.strip()
        elif what == "tolerance":
            text, ok = QtWidgets.QInputDialog.getText(
                host, "Tolerance",
                "Tolerance for %s, as it should read: +0.1/-0, ±0.05, "
                "H7" % note.label(), text=note.tolerance)
            if not ok:
                return
            document.push_undo()
            note.tolerance = text.strip()
        else:
            return
        document.modified = True
        host._draw_visible_sketches()
        host.viewport.redraw()
        host._refresh_trees()
        host._update_title()

    def toggle_all(self) -> None:
        document = self.host.document
        if not getattr(document, "annotations", None):
            self.host.status_message.setText("This part has no annotations.")
            return
        document.annotations_visible = not document.annotations_visible
        document.modified = True
        self.host._draw_visible_sketches()
        self.host.viewport.redraw()
        self.host._update_title()
