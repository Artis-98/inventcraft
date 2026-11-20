"""Drive the assembly's icLogic forms in InventCraft, as a user would.

    .venv/Scripts/python.exe -m examples.walking_excavator.verify_controls

Each form is opened from its rule; every slider is moved, the model is
checked against the skeleton while the form is still open, and Cancel must
put everything back.  One form is accepted to show OK keeps the pose.  The
time a slider move takes, rule and redraw, is measured.  Every joint is
checked to stay on its pin across every slider's range.
"""
import json
import time

from . import render, motion as M
from .common import OUT
from .controls import control_sets
from datum.core import rules
from datum.ui.rules_ui import FormDialog
from PySide6 import QtCore, QtWidgets


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setStyle('Fusion')
    window = render.MainWindow()
    window.resize(1800, 1100)
    window.show()
    render.pump(app, .3)
    assert window.open_path(str(OUT / 'Walking Excavator.icasm'))
    render.pump(app, .5)
    ass = window.assembly
    rules.trust_document(ass)
    results = {'forms': [], 'joints': {}, 'errors': []}
    baseline = {n: ass.params[n].expression for n in ass.params.names()}
    recipes = json.loads((OUT / 'assembly-recipes.json').read_text())
    families = json.loads((OUT / 'ram-families.json').read_text())

    def pose_error():
        p = {n: ass.params[n].value for n in ass.params.names()}
        f = M.skeleton(p)
        expected = {r['label']: M.recipe_frame(r, f) for r in recipes}
        return max(M.norm(M.sub(o.placement.position, expected[o.ref.label][0]))
                   for o in ass.occurrences)

    before = {o.ref.label: list(o.placement.position) for o in ass.occurrences}
    shown = rules.show_form
    for title, controls in control_sets().items():
        timings = []

        def show(document, caption, rows):
            dialog = FormDialog(window, document, caption, rows)
            errors = []

            def move():
                try:
                    for fraction in (0.15, 0.85):
                        for _, param, low, high, step, label in controls:
                            dialog.widgets[param].setValue(round(fraction * (high - low) / step))
                            t = time.perf_counter()
                            dialog._pending.stop()
                            dialog._rebuild()
                            render.pump(app, 0.0)
                            timings.append(time.perf_counter() - t)
                        err = pose_error()
                        assert err < 1e-6, 'model left the skeleton by %.3g mm' % err
                    moved = max(M.norm(M.sub(o.placement.position, before[o.ref.label]))
                                for o in ass.occurrences)
                    assert moved > 1, 'nothing moved'
                    if title == 'Leg controls FL':
                        window.viewport.fit_all()
                        render.pump(app, .3)
                        destination = OUT / 'renders'
                        destination.mkdir(exist_ok=True)
                        render.chrome_capture(window, destination / 'icLogic-leg-form.png',
                                              render.QA / 'controls-viewport.png', app)
                        dialog.grab().save(str(destination / 'icLogic-leg-sliders.png'))
                except Exception as exc:
                    errors.append(repr(exc))
                finally:
                    dialog.reject()
            QtCore.QTimer.singleShot(150, move)
            accepted = dialog.exec() == QtWidgets.QDialog.Accepted
            if errors:
                raise AssertionError(errors)
            return accepted
        rules.show_form = show
        rule = next(r for r in ass.rules.rules if r.name == title)
        result = rules.run(rule, ass)
        assert result.ok, (title, result.error)
        restored = all(ass.params[n].expression == v for n, v in baseline.items())
        back = pose_error() < 1e-6 and max(
            M.norm(M.sub(o.placement.position, before[o.ref.label])) for o in ass.occurrences) < 1e-6
        results['forms'].append(dict(form=title, sliders=len(controls), moves=len(timings),
                                     slowest_move_s=round(max(timings), 3),
                                     average_move_s=round(sum(timings) / len(timings), 3),
                                     cancel_restores=restored and back))
        print('%-28s %2d sliders  %.2f s a move (slowest %.2f)  cancel restores: %s'
              % (title, len(controls), sum(timings) / len(timings), max(timings), restored and back),
              flush=True)
        if not (restored and back):
            results['errors'].append(title + ': Cancel did not restore the pose')
    # OK keeps what the form set
    def accept(document, caption, rows):
        dialog = FormDialog(window, document, caption, rows)

        def go():
            ranges = {k: lo for _, k, lo, hi, st, lb in control_sets()['Leg controls FL']}
            dialog.widgets['steer_FL'].setValue(round(10 - ranges['steer_FL']))   # +10 degrees
            dialog.widgets['lift_FL'].setValue(round(20 - ranges['lift_FL']))     # +20 degrees
            dialog._pending.stop()
            dialog._rebuild()
            dialog.accept()
        QtCore.QTimer.singleShot(150, go)
        return dialog.exec() == QtWidgets.QDialog.Accepted
    rules.show_form = accept
    result = rules.run(next(r for r in ass.rules.rules if r.name == 'Leg controls FL'), ass)
    assert result.ok, result.error
    kept = ass.params['steer_FL'].value == 10 and ass.params['lift_FL'].value == 20 and pose_error() < 1e-6
    results['ok_keeps_pose'] = kept
    print('OK keeps the pose:', kept, flush=True)
    rules.show_form = shown
    for name, value in baseline.items():
        ass.params.set_expression(name, value)
    assert rules.run(ass.rules.rules[0], ass).ok
    # every joint stays on its pin, every cylinder inside its stroke
    p = {n: ass.params[n].value for n in ass.params.names()}
    worst, samples = 0.0, 0
    for controls in control_sets().values():
        for _, param, low, high, step, label in controls:
            for k in range(9):
                f = M.skeleton(dict(p, **{param: low + (high - low) * k / 8}))
                for s in M.SIDES:
                    ws = M.wheel_side(s)
                    pairs = [('leg_' + s, 'carrier_' + s, (M.LEG_LENGTH, 0, 0)),
                             ('carrier_' + s, 'steer_' + s, (M.LEG_LENGTH, ws * (M.WHEEL_Y - M.SCRUB), -150)),
                             ('steer_' + s, 'wheel_' + s, (M.LEG_LENGTH, ws * M.WHEEL_Y, 0)),
                             ('hip_' + s, 'leg_' + s, (M.HIP_REACH, 0, 0))]
                    tip = (M.LEG_LENGTH + M.LINK_OFFSET[0], 0, M.LINK_OFFSET[2])
                    worst = max(worst, M.norm(M.sub(M.point(f['link_' + s], (M.LEG_LENGTH, 0, 0)),
                                                    M.point(f['carrier_' + s], tip))))
                    for a, b, q in pairs:
                        if a.startswith('hip'):
                            d = M.norm(M.sub(M.point(f[a], q), M.point(f[b], (0, 0, 0))))
                        else:
                            d = M.norm(M.sub(M.point(f[a], q), M.point(f[b], q)))
                        worst = max(worst, d)
                for key, fam in (('boom', 'boom'), ('dipper', 'dipper'), ('bucket', 'bucket')):
                    span = M.norm(M.sub(f[key + '_a'], f[key + '_b']))
                    if not families[fam]['min_span'] <= span <= families[fam]['max_span']:
                        results['errors'].append('%s=%g: %s cylinder out of stroke (%.0f)' % (param, f and low, key, span))
                for s in M.SIDES:
                    for key, fam in (('leg_' + s, 'leg'), ('spread_' + s, 'spread')):
                        span = M.norm(M.sub(f[key + '_a'], f[key + '_b']))
                        if not families[fam]['min_span'] <= span <= families[fam]['max_span']:
                            results['errors'].append('%s: %s cylinder out of stroke (%.0f)' % (param, key, span))
                samples += 1
    results['joints'] = {'samples': samples, 'worst_separation_mm': worst}
    print('Joints: %d samples, worst separation %.2g mm; stroke errors: %d'
          % (samples, worst, len(results['errors'])), flush=True)
    (OUT / 'controls-validation.json').write_text(json.dumps(results, indent=1), encoding='utf-8')
    window.hide()
    window.viewport.shutdown()
    return 1 if results['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
