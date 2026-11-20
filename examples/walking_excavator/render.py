"""Render the native walking-excavator assembly in InventCraft.

Run from the repository with:
    .venv/Scripts/python.exe -m examples.walking_excavator.render
The normal output is a native OpenCascade ray trace at 3840x2160.
A graphics-driver failure is recorded and falls back to a native viewport
capture at its actual dimensions. No external renderer is involved.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[2]
QA=ROOT/'build/walking-qa'
os.environ['DATUM_CONFIG_DIR']=str(QA/'render-settings')
os.environ['DATUM_DOCUMENTS']=str(QA/'documents')
os.environ['DATUM_SETTINGS_ORG']='InventCraftWalkingExcavatorRender'
QA.mkdir(parents=True,exist_ok=True)
Path(os.environ['DATUM_CONFIG_DIR']).mkdir(parents=True,exist_ok=True)
Path(os.environ['DATUM_DOCUMENTS']).mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT))

from PySide6 import QtCore, QtGui, QtWidgets
from datum.core import kernel
from datum.ui import icons, theme
from datum.ui.main_window import MainWindow


def pump(app,seconds=.25):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents,25)


def image_info(path):
    image=QtGui.QImage(str(path))
    if image.isNull():
        return {'ok':False,'reason':'image could not be decoded'}
    # Sample the image for non-background pixels. This catches successful
    # PNG writes from a graphics context that rendered an empty scene.
    step=max(1,min(image.width(),image.height())//120)
    nonwhite=0
    samples=0
    for y in range(0,image.height(),step):
        for x in range(0,image.width(),step):
            color=image.pixelColor(x,y)
            samples+=1
            nonwhite+=int(color.alpha()>30 and min(color.red(),color.green(),color.blue())<240)
    return {'ok':nonwhite/max(samples,1)>.001,
            'width':image.width(),'height':image.height(),
            'nonwhite_fraction':nonwhite/max(samples,1)}


def frame(viewport,center,span,direction=(.68,.90,.52)):
    length=math.sqrt(sum(v*v for v in direction))
    direction=[v/length for v in direction]
    eye=[center[i]+direction[i]*16000 for i in range(3)]
    viewport.set_projection(True)
    viewport._set_camera(eye,center,(0,0,1),span)
    # _set_camera takes the vertical camera scale in model units.
    viewport.view.ZFitAll()
    viewport.redraw()


def bbox(assembly,words=None):
    bounds=[]
    for occurrence in assembly.active():
        if words and not any(w.lower() in occurrence.name.lower()
                             or w.lower() in occurrence.ref.path.lower() for w in words):
            continue
        shape=occurrence.placed()
        if shape is not None and not shape.IsNull():
            bounds.append(kernel.bounding_box(shape))
    if not bounds:
        return None
    return [min(b[i] for b in bounds) for i in range(3)]+[
            max(b[i+3] for b in bounds) for i in range(3)]


def centered(bounds):
    return [(bounds[i]+bounds[i+3])/2 for i in range(3)]


def extent(bounds):
    return max(bounds[i+3]-bounds[i] for i in range(3))


def chrome_capture(window,path,viewport_path,app):
    window.viewport.grab_image(str(viewport_path))
    pump(app,.1)
    image=window.grab().toImage()
    native=QtGui.QImage(str(viewport_path))
    if not native.isNull():
        origin=window.viewport.mapTo(window,QtCore.QPoint(0,0))
        painter=QtGui.QPainter(image)
        painter.drawImage(QtCore.QRect(origin.x(),origin.y(),
                          window.viewport.width(),window.viewport.height()),native)
        painter.end()
    if not image.save(str(path)):
        raise RuntimeError('Could not save native application capture')
    return image_info(path)


def run(args):
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setApplicationName('InventCraft Walking Excavator Render')
    app.setOrganizationName('InventCraftWalkingExcavatorRender')
    app.setStyle('Fusion')
    theme.set_theme('midnight_light')
    icons.use_theme('midnight_light')
    theme.apply_colours()
    app.setStyleSheet(theme.stylesheet())
    window=MainWindow()
    window.resize(1800,1100)
    window.show()
    pump(app,1.0)
    if not window.open_path(str(args.assembly)):
        raise RuntimeError('InventCraft could not open '+str(args.assembly))
    pump(app,1.0)
    if window.assembly is None:
        raise RuntimeError('Opened document is not an InventCraft assembly')
    window.assembly_ui.browser.expandToDepth(0)
    viewport=window.viewport
    if not viewport._ready:
        raise RuntimeError('Native OpenCascade viewport did not initialize')
    viewport.set_show_origin(False)
    viewport.set_display_mode('shaded')
    viewport.set_view('iso')
    pump(app,.35)
    viewport.fit_all()
    pump(app,.35)

    args.output.mkdir(parents=True,exist_ok=True)
    all_bounds=bbox(window.assembly)
    if all_bounds is None:
        raise RuntimeError('Assembly contains no renderable shapes')
    center=centered(all_bounds)
    width=args.width
    height=round(width*9/16)
    report={'assembly':str(args.assembly),'renderer':'InventCraft / OpenCascade',
            'requested_width':width,'requested_height':height,
            'bounds_mm':all_bounds,'images':[]}
    report_file=args.output/'render-report.json'
    # whole-machine views, then close-ups framed in a component's own
    # frame: (name, occurrence label or None, local box, view direction)
    # whole-machine views, then close-ups framed on the parts they show
    details=[
        ('hero',None,tuple(getattr(args,'hero_camera',(.95,.75,.45)))),
        ('overview',None,(-.85,.95,.6)),
        ('side',None,(0.0,1.0,0.12)),
        ('cab-frame-glass',('Upper/Cab','Upper/Frame0001','Upper/Seat','Upper/Console','Upper/Wiper'),(.85,.95,.4)),
        ('leg-and-wheel',('FL hip','FL leg','FL wheel','FL steering','leg_FL ram'),(.35,1.0,.35)),
        ('boom-hydraulics',('Boom/','boom ram','dipper ram'),(.25,-1.0,.55)),
        ('tiltrotator-bucket',('Bucket/','Tiltrotator','Idler link','Bucket link'),(.55,-1.0,.25)),
        ('chassis-hips',('Chassis/','FL hip','FR hip','RL hip','RR hip','spread_'),(.6,.75,.9)),
    ]
    if args.quick:
        details=details[:1]
    from examples.walking_excavator import interference
    pose={n:window.assembly.params[n].value for n in window.assembly.params.names()}
    placed=interference.world(interference.recipes(),pose) if 'ride_height' in pose else []
    for name,words,direction in details:
        if words is None:
            selected=all_bounds
        else:
            boxes=[interference.box(interference.located(path,pl)) for label,group,path,pl in placed
                   if label.startswith(words) and interference.part_shape(path) is not None]
            selected=[min(b[i] for b in boxes) for i in range(3)]+[max(b[i+3] for b in boxes) for i in range(3)]
        label=words
        max_span=extent(selected)
        span=max_span*(getattr(args,'hero_scale',.72) if label is None else 1.7)
        frame(viewport,centered(selected),span,direction)
        pump(app,.35)
        destination=args.output/(name+'.png')
        item={'name':name,'file':str(destination),'camera':viewport.camera_state(),
              'mode':'native ray trace','shadows':True,'reflections':False,'white':True}
        try:
            ok=viewport.render_image(str(destination),width,height,
                                     shadows=True,reflections=False,edges=False,white=True)
            item.update(image_info(destination))
            if not ok or not item['ok']:
                raise RuntimeError('Native ray-trace image was unavailable or empty')
        except Exception as error:
            item['raytrace_error']=str(error)
            item['mode']='native viewport capture'
            viewport.grab_image(str(destination))
            item.update(image_info(destination))
        report['images'].append(item)
        report_file.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(name,item['mode'],item.get('width'),item.get('height'),
              'ok='+str(item['ok']),flush=True)
        if name=='hero':
            chrome_capture(window,args.output/'application-tree.png',
                           QA/'chrome-viewport.png',app)
    report['completed']=all(item['ok'] for item in report['images']) and len(report['images'])==len(details)
    report_file.write_text(json.dumps(report,indent=2),encoding='utf-8')
    window.hide()
    viewport.shutdown()
    return 0 if report['completed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    base=ROOT/'examples/walking-excavator'
    parser.add_argument('--assembly',type=Path,default=base/'Walking Excavator.icasm')
    parser.add_argument('--output',type=Path,default=base/'renders')
    parser.add_argument('--width',type=int,default=3840)
    parser.add_argument('--quick',action='store_true')
    parser.add_argument('--hero-camera',type=float,nargs=3,default=(.95,.75,.45))
    parser.add_argument('--hero-scale',type=float,default=.72)
    args=parser.parse_args()
    args.assembly=args.assembly.resolve()
    args.output=args.output.resolve()
    if not args.assembly.is_file():
        parser.error('Native assembly does not exist yet: '+str(args.assembly))
    try:
        result=run(args)
    except Exception:
        traceback.print_exc()
        result=1
    # OCCT graphics teardown can outlive Qt's native window. Shutdown above
    # releases the viewport before the process ends.
    sys.stdout.flush()
    sys.stderr.flush()
    return result


if __name__=='__main__':
    raise SystemExit(main())
