"""Parts for the quick look tests: plates side by side, each a solid of
its own, drilled with a grid of holes, the rims filleted if asked."""
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GeomAbs import GeomAbs_Circle
from OCP.TopoDS import TopoDS

from datum.core import kernel
from datum.core.document import Document
from datum.core.features import (CUT, JOIN, NEW_BODY, FilletFeature,
                                 PatternFeature, PrimitiveFeature)


def plates(count, holes=3, fillets=False):
    doc = Document()
    doc.params.add("d", "5")
    for i in range(count):
        x = i * 200.0
        doc.add_feature(PrimitiveFeature(
            name="Plate%d" % i, kind="box", a="150", b="100", c="10",
            origin=(str(x), "0", "0"), operation=NEW_BODY if i else JOIN))
        hole = PrimitiveFeature(name="Hole%d" % i, kind="cylinder", a="d",
                                b="10", operation=CUT,
                                origin=(str(x + 15), "15", "0"))
        doc.add_feature(hole)
        doc.add_feature(PatternFeature(parents=[hole.id], count1=str(holes),
                                       spacing1="20", dir1="X",
                                       count2=str(holes), spacing2="20",
                                       dir2="Y"))
        if fillets:
            doc.rebuild()
            body = doc.bodies[-1].shape
            rims = [e for e in kernel.edges(body)
                    if BRepAdaptor_Curve(TopoDS.Edge_s(e)).GetType()
                    == GeomAbs_Circle]
            fillet = FilletFeature(name="Round%d" % i, radius="0.8")
            fillet.refs.capture_from(doc.shape, "edge", rims)
            doc.add_feature(fillet)
    doc.rebuild()
    return doc
