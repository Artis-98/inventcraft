"""The part's Annotate tab: dimensions and hole notes on the 3D model.

Dimension takes what is clicked: a round edge or face gives its diameter
at once; a straight edge shows its length, placed where the next click on
empty space is (or Enter), unless that click picks something else, which
makes it the distance between the two; anything else waits for a second
pick.  A dimension's legs stand square to what it measures, and any
annotation's text can be picked up and dragged.  Hole
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
        # an edge picked on its own, shown with its length until placed
        self.pending: Optional[core.ModelAnnotation] = None
        # where each annotation's text was drawn, for picking it up
        self._spots: List[tuple] = []
        try:
            host.viewport.grabber = self.grab_at
        except Exception:
            pass

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
        self.pending = None
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
            if self.pending is not None and len(self.picks) == 1:
                # a click off the part: the edge's length, put there
                self._make(core.LINEAR, self.picks, at=self._click_point())
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
            if self._show_length(pick):
                self.host.status_message.setText(
                    "%s long. Click off the part where it goes, or Enter; "
                    "or click a second face, edge or corner for the "
                    "distance to it." % self.pending.display)
                return True
            self.host.status_message.setText(
                "Now the second face, edge or corner.")
            return True
        self.pending = None
        self._make(core.LINEAR, self.picks[:2])
        return True

    def _show_length(self, pick) -> bool:
        """A straight edge picked on its own: its length, drawn at once."""
        from OCP.TopAbs import TopAbs_EDGE

        self.pending = None
        if pick.ShapeType() != TopAbs_EDGE:
            return False
        document = self.host.document
        refs, kinds = core.capture(document.shape, [pick])
        if not refs:
            return False
        note = core.ModelAnnotation(kind=core.LINEAR, refs=refs,
                                    ref_kinds=kinds)
        core.evaluate(note, document.shape)
        if note.lost:
            return False
        note.offset = core.default_offset(note, document.shape,
                                          self._view_direction())
        self.pending = note
        self._redraw()
        return True

    def _click_point(self):
        """Where the last click was, on the plane square to the view through
        the pending dimension's middle; None when that cannot be told."""
        vp = self.host.viewport
        at = getattr(vp, "_press_pos", None)
        direction = self._view_direction()
        if at is None or direction is None or self.pending is None:
            return None
        return vp.plane_hit(at.x(), at.y(), self.pending.anchor, direction)

    def accept_single(self) -> bool:
        """Enter: a straight edge picked on its own is dimensioned by its
        length."""
        from OCP.TopAbs import TopAbs_EDGE

        if self.mode != DIM or len(self.picks) != 1 \
                or self.picks[0].ShapeType() != TopAbs_EDGE:
            return False
        self._make(core.LINEAR, self.picks)
        return True

    def _make(self, kind: str, picks, at=None) -> None:
        host = self.host
        document = host.document
        refs, kinds = core.capture(document.shape, picks)
        self.picks = []
        self.pending = None
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
        if at is not None:
            annotation.offset = [at[i] - annotation.anchor[i]
                                 for i in range(3)]
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
        self._spots = []
        if self.pending is not None and self.mode == DIM:
            self._draw_note(self.pending, C.accent)
        notes = getattr(document, "annotations", None) or []
        if not notes or not document.annotations_visible:
            return
        core.evaluate_all(document)
        for note in notes:
            if note.hidden:
                continue
            # the theme's strongest text colour: black on a light view, near
            # white on a dark one, and never mistaken for a hidden model edge
            colour = C.error if note.lost else C.text_bright
            at = self._draw_note(note, colour)
            self._spots.append((note, at))

    def _draw_note(self, note, colour: str):
        """One annotation on the model; returns where its text is."""
        vp = self.host.viewport
        off = list(note.offset)
        if note.kind == core.LINEAR and len(note.points) == 2:
            p, q = note.points
            span = [q[i] - p[i] for i in range(3)]
            length = sum(c * c for c in span) ** 0.5
            u = [c / length for c in span] if length > 1e-9 else [0.0] * 3
            along = sum(off[i] * u[i] for i in range(3))
            # the legs stand square to what is measured, whichever way the
            # text has been dragged; the text may slide along the line
            leg = [off[i] - along * u[i] for i in range(3)]
            p2 = tuple(p[i] + leg[i] for i in range(3))
            q2 = tuple(q[i] + leg[i] for i in range(3))
            vp.draw_edge(p, p2, colour, 1.0)
            vp.draw_edge(q, q2, colour, 1.0)
            vp.draw_edge(p2, q2, colour, 1.6)
            for end, other in ((p2, q2), (q2, p2)):
                self._tick(end, other, colour)
            mid = tuple((p2[i] + q2[i]) / 2 for i in range(3))
            at = tuple(mid[i] + along * u[i] for i in range(3))
            if abs(along) > length / 2.0:
                # out past an end: the line runs on to the text
                end = q2 if along > 0 else p2
                vp.draw_edge(end, at, colour, 1.0)
        elif len(note.points) == 2:
            centre, rim = note.points
            at = tuple(rim[i] + off[i] for i in range(3))
            vp.draw_edge(rim, at, colour, 1.4)
            vp.draw_point(rim, colour, 4.0)
        else:
            at = tuple(note.anchor[i] + off[i] for i in range(3))
        text = note.display + ("  (lost)" if note.lost else "")
        vp.draw_text(text, at, colour, 15.0)
        return at

    def _redraw(self) -> None:
        self.host._draw_visible_sketches()
        self.host.viewport.redraw()

    # -- dragging the text -------------------------------------------------

    GRAB_PIXELS = (40, 12)

    def grab_at(self, x: int, y: int):
        """A press on an annotation's text picks it up to drag."""
        host = self.host
        if not getattr(host, "in_part", False) or host.editor.active:
            return None
        document = host.document
        if not getattr(document, "annotations_visible", True):
            return None
        vp = host.viewport
        best, best_gap = None, None
        for note, at in self._spots:
            sx, sy = vp.project(at)
            if abs(sx - x) > self.GRAB_PIXELS[0] \
                    or abs(sy - y) > self.GRAB_PIXELS[1]:
                continue
            gap = abs(sx - x) + abs(sy - y)
            if best_gap is None or gap < best_gap:
                best, best_gap = (note, at), gap
        if best is None:
            return None
        direction = self._view_direction()
        if direction is None:
            return None
        return _TextDrag(self, best[0], best[1], direction)

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


class _TextDrag:
    """An annotation's text being dragged, on the plane square to the view
    through where it was picked up."""

    def __init__(self, tool, note, at, direction) -> None:
        self.tool = tool
        self.note = note
        self.start = tuple(at)
        self.offset = list(note.offset)
        self.direction = direction
        self.moved = False

    def move(self, x: int, y: int) -> None:
        vp = self.tool.host.viewport
        hit = vp.plane_hit(x, y, self.start, self.direction)
        if hit is None:
            return
        if not self.moved:
            self.tool.host.document.push_undo()
            self.moved = True
        self.note.offset = [self.offset[i] + hit[i] - self.start[i]
                            for i in range(3)]
        self.tool._redraw()

    def finish(self) -> None:
        if not self.moved:
            return
        host = self.tool.host
        host.document.modified = True
        host._update_title()
