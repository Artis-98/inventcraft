"""OpenCascade geometry for the isometric InventCraft ribbon renders."""
from math import cos, dist, pi, sin, sqrt, tau

from OCP.BRep import BRep_Builder
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer, BRepFilletAPI_MakeFillet
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
from OCP.BRepPrimAPI import (BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCone,
                             BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakePrism,
                             BRepPrimAPI_MakeSphere)
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Compound
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Vec


def block(x, y, z, dx, dy, dz):
    return BRepPrimAPI_MakeBox(gp_Pnt(x, y, z), dx, dy, dz).Shape()


def cylinder(center, radius, height, direction=(0, 0, 1)):
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*center), gp_Dir(*direction)),
                                   radius, height).Shape()


def union(a, b):
    return BRepAlgoAPI_Fuse(a, b).Shape()


def cut(a, b):
    return BRepAlgoAPI_Cut(a, b).Shape()


def combine_parts(shapes):
    result = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(result)
    for shape in shapes:
        builder.Add(result, shape)
    return result


def groups(**items):
    return {name: combine_parts(value) if isinstance(value, (tuple, list)) else value
            for name, value in items.items() if value}


def wire(points):
    builder = BRepBuilderAPI_MakePolygon()
    for point in points:
        builder.Add(gp_Pnt(*point))
    builder.Close()
    return builder.Wire()


def prism(points, vector):
    return BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(wire(points)).Face(),
                               gp_Vec(*vector)).Shape()


def disk_wire(x, y, z, r, count=40):
    return wire([(x+r*cos(tau*j/count), y+r*sin(tau*j/count), z) for j in range(count)])


def tube(a, b, radius=.095):
    delta = tuple(y-x for x, y in zip(a, b))
    return cylinder(a, radius, dist(a, b), delta)


def chain(points, radius=.095):
    return [tube(a, b, radius) for a, b in zip(points, points[1:])]


def ball(p, radius):
    return BRepPrimAPI_MakeSphere(gp_Pnt(*p), radius).Shape()


def arrow(a, b, radius=.24, head=.59, length=1.22):
    span = dist(a, b)
    direction = tuple((q-p)/span for p, q in zip(a, b))
    base = tuple(q-d*length for q, d in zip(b, direction))
    axis = gp_Ax2(gp_Pnt(*base), gp_Dir(*direction))
    return union(tube(a, base, radius), BRepPrimAPI_MakeCone(axis, head, 0, length).Shape())


def orbit(center, radius, start, end, arrowhead=True, thickness=.15):
    x, y, z = center
    steps = max(12, round(abs(end-start)*12))
    points = [(x+radius*cos(start+(end-start)*j/steps),
               y+radius*sin(start+(end-start)*j/steps), z) for j in range(steps+1)]
    if not arrowhead:
        return chain(points, thickness)
    base = points[-1]
    tangent = (-sin(end), cos(end), 0)
    tip = tuple(p+d*.95 for p, d in zip(base, tangent))
    return chain(points[:-2], thickness)+[arrow(points[-3], tip, thickness, .48, .92)]


def segmented(a, b, pattern, radius=.10):
    span = dist(a, b)
    direction = [(q-p)/span for p, q in zip(a, b)]
    start = 0
    index = 0
    result = []
    while start < span-.03:
        end = min(span, start+pattern[index % len(pattern)])
        if index % 2 == 0:
            result.append(tube(tuple(p+d*start for p, d in zip(a, direction)),
                               tuple(p+d*end for p, d in zip(a, direction)), radius))
        index += 1
        start = end
    return result


def surfaces(shape):
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        f = TopoDS.Face_s(exp.Current())
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(f, props)
        p = props.CentreOfMass()
        yield f, (p.X(), p.Y(), p.Z()), BRepAdaptor_Surface(f).GetType()
        exp.Next()


def painted(shape, select, **extras):
    body, accent = [], []
    for face, p, kind in surfaces(shape):
        (accent if select(p, kind) else body).append(face)
    if extras.get("accent"):
        accent.extend(extras.pop("accent"))
    return groups(body=body, accent=accent, **extras)


def rounded_rectangle(x, y, z, half_x, half_y, radius):
    corners=((half_x-radius,half_y-radius,0),(-half_x+radius,half_y-radius,pi/2),
             (-half_x+radius,-half_y+radius,pi),(half_x-radius,-half_y+radius,3*pi/2))
    return [(x+cx+radius*cos(angle+pi*j/16),y+cy+radius*sin(angle+pi*j/16),z)
            for cx,cy,angle in corners for j in range(9)]


def extrude():
    blank = prism(rounded_rectangle(-.40,0,-3.55,3.45,2.75,.58),(0,0,.43))
    profile = rounded_rectangle(-.55,0,-3.12,2.23,1.72,.39)
    raised = prism(profile,(0,0,5.75))
    border = rounded_rectangle(-.55,0,-3.085,2.31,1.8,.43)
    return groups(body=[blank, raised], line=chain(border+[border[0]],.12),
                  accent=arrow((3.78,-.18,-3.12),(3.78,-.18,3.82),.29,.76,1.55))


def revolve():
    axis = segmented((-1.55,0,-4.40),(-1.55,0,4.55),(.83,.31,.20,.31),.12)
    prof = [(0.0,0,-3.3),(2.95,0,-3.3),(2.95,0,-.70),(1.85,0,-.70),
            (1.85,0,3.60),(0,0,3.60),(0,0,-3.3)]
    return groups(line=axis+chain(prof,.145),
                  accent=orbit((-1.0,0,-.75),3.57,.28,4.98,thickness=.19))


def sweep():
    def at(x, y, z):
        # Put the bent path across the camera's horizontal and vertical axes.
        return ((x-y)/sqrt(2),(x+y)/sqrt(2),z)
    x,z=-4.25,-3.15
    points=[at(x,0,z),at(-.83,0,z)]
    points += [at(-.83+3.6*sin(j*pi/48),0,z+3.6*(1-cos(j*pi/48))) for j in range(1,25)]
    points.append(at(2.77,0,3.95))
    ring=[at(x-.12,1.0*cos(tau*j/40),z+1.0*sin(tau*j/40)) for j in range(41)]
    return groups(body=tube(points[0],points[1],.79),
                  line=chain(ring,.13),
                  accent=chain(points[1:],.205)+[ball(points[-1],.47)])


def loft():
    bottom = [(-3.1,-2.65,-3),(3.1,-2.65,-3),(3.1,2.65,-3),(-3.1,2.65,-3)]
    top = [(1.45*cos(tau*i/40),1.45*sin(tau*i/40),3.05) for i in range(40)]
    loft = BRepOffsetAPI_ThruSections(True, False)
    loft.AddWire(wire(bottom))
    loft.AddWire(disk_wire(0,0,3.05,1.45))
    loft.Build()
    return groups(body=loft.Shape(),
                  accent=chain(bottom+[bottom[0]],.145)+chain(top+[top[0]],.145))


def cut_icon():
    stock = block(-3.65,-3.00,-3.45,7.30,6.0,4.42)
    stock = cut(stock, block(-2.05,-1.83,-.12,4.1,3.66,2))
    return painted(stock, lambda p,k: abs(p[2]+.12)<.04,
                   accent=[arrow((.05,-.16,3.62),(.05,-.16,.66),.26,.64,1.15)])


def cut_face():
    stock = block(-3.45,-2.85,-3.25,6.90,5.70,6.5)
    slicing = prism([(-4.3,-3.75,-1.05),(4.3,-3.75,1.03),
                     (4.3,3.75,1.03),(-4.3,3.75,-1.05)],(0,0,.13))
    return groups(body=cut(stock,slicing),accent=slicing)


def hole():
    solid=cut(block(-3.55,-3.18,-2.7,7.1,6.36,4.92),cylinder((0,0,-3.2),1.48,6))
    return painted(solid,lambda p,k: 'Cylinder' in str(k))


def rounded_edge(kind):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    stock=block(-3.52,-2.9,-3.05,7.04,5.8,5.45)
    operation=kind(stock)
    exp=TopExp_Explorer(stock,TopAbs_EDGE)
    while exp.More():
        e=TopoDS.Edge_s(exp.Current())
        curve=BRepAdaptor_Curve(e)
        ends=[curve.Value(t) for t in (curve.FirstParameter(),curve.LastParameter())]
        if all(abs(p.Y()+2.9)<.01 and abs(p.Z()-2.4)<.01 for p in ends):
            operation.Add(1.53,e)
            operation.Build()
            assert operation.IsDone()
            return painted(operation.Shape(),lambda p,k:-2.86<p[1]<-1.4 and 0.9<p[2]<2.37)
        exp.Next()
    raise ValueError('Could not locate the top edge')


def fillet():
    return rounded_edge(BRepFilletAPI_MakeFillet)


def chamfer():
    return rounded_edge(BRepFilletAPI_MakeChamfer)


def shell():
    stock=cut(block(-3.50,-2.90,-3.15,7,5.8,5.15),block(-2.92,-2.32,-2.52,5.84,4.64,5))
    return painted(stock,lambda p,k:abs(abs(p[0])-2.92)<.045
                   or abs(abs(p[1])-2.32)<.045 or abs(p[2]+2.52)<.045)


def split():
    return groups(body=[block(-3.32,-2.72,-3.7,6.64,5.44,2.08),
                        block(-3.32,-2.72,1.0,6.64,5.44,2.0)],
                  accent=block(-4.18,-3.55,-.5,8.36,7.10,.19))


def split_faces():
    p=[(-3.51,-2.91,0),(3.51,-2.91,0),(3.51,2.91,0)]
    return groups(body=block(-3.5,-2.9,-2.75,7,5.8,5.5),accent=chain(p,.145))


def split_solid():
    return groups(body=[block(-4.04,-2.55,-2.58,2.60,5.10,5.16),
                        block(1.44,-2.55,-2.58,2.60,5.10,5.16)],
                  accent=block(-.10,-3.15,-3.14,.20,6.30,6.28))


def combine():
    a=block(-3.85,-1.65,-2.5,6.4,3.3,3.75)
    b=block(-1.25,-3.1,-2.05,3.15,6.2,5.15)
    return groups(body=[cut(a,b),cut(b,a)],accent=BRepAlgoAPI_Common(a,b).Shape())


def emboss():
    plate=block(-3.70,-2.92,-1.2,7.4,5.84,1)
    active=union(cylinder((-1.1,0,-.20),1.1,1.4),block(-1.1,-1.1,-.20,3.5,2.2,1.4))
    return groups(body=plate,accent=active)


def engrave():
    plate=block(-3.7,-2.92,-1.3,7.4,5.84,1.54)
    active=union(cylinder((-1.1,0,-.78),1.15,1.55),block(-1.1,-1.15,-.78,3.57,2.3,1.55))
    return painted(cut(plate,active),lambda p,k: abs(p[2]+.78)<.04)


def cube(size=6.4):
    return block(-size/2,-size/2,-size/2,size,size,size)


def cube_sticks(size, hidden=False):
    h=size/2
    points=[(-h,-h,-h),(h,-h,-h),(h,h,-h),(-h,h,-h),
            (-h,-h,h),(h,-h,h),(h,h,h),(-h,h,h)]
    pairs=[(0,1),(1,2),(0,4),(1,5),(2,6),(4,5),(5,6),(6,7),(7,4)]
    if hidden:
        pairs.extend(((0,3),(2,3),(3,7)))
    return [tube(points[i],points[j],.13) for i,j in pairs]


def box():
    return groups(line=cube_sticks(7.15))


def cylinder_icon():
    return painted(cylinder((0,0,-3.35),3.05,6.7),lambda p,k:p[2]>3.3)


def sphere():
    return groups(body=ball((0,0,0),3.67),accent=orbit((0,0,0),3.69,0,tau,False,.125))


def shaded():
    return groups(body=cube(7.05))


def shaded_edges():
    return shaded()


def wireframe():
    return groups(line=cube_sticks(7.15,True))


def xray():
    return groups(body=cube(7.18),accent=ball((.1,-.1,.1),1.68))


def axis_arrows(origin, length=2.65):
    return [arrow(origin,tuple(v+(length if j==i else 0) for j,v in enumerate(origin)),
                  .14,.39,.83) for i in range(3)]


def iso():
    origin=(2.58,-2.55,-1.65)
    return groups(body=block(-2.9,-2.55,-2.65,5.48,5.24,5.10),
                  accent=[arrow(origin,(4.7,-2.55,-1.65),.16,.45,.83),
                          arrow(origin,(2.58,-4.7,-1.65),.16,.45,.83),
                          arrow(origin,(2.58,-2.55,.63),.16,.45,.83)])


def direction_view(which):
    if which=='top':
        stock=block(-2.85,-2.85,-3.62,5.7,5.7,4.92)
        test=lambda p,k:p[2]>1.25
        marker=arrow((0,0,4.65),(0,0,1.61),.19,.62,1.1)
    elif which=='front':
        stock=block(-2.90,-1.68,-2.82,5.8,4.85,5.64)
        test=lambda p,k:p[1]<-1.65
        marker=arrow((-.18,-4.8,.13),(-.18,-1.94,.13),.19,.63,1.1)
    else:
        stock=block(-3.15,-2.82,-2.82,4.8,5.64,5.64)
        test=lambda p,k:p[0]>1.62
        marker=arrow((4.8,0,.12),(1.91,0,.12),.19,.63,1.1)
    return painted(stock,test,accent=[marker])


def top():
    return direction_view('top')


def front():
    return direction_view('front')


def right():
    return direction_view('right')


def stepped_block():
    return cut(block(-3.5,-2.8,-2.9,7,5.6,5.8),block(-3.6,.20,.3,3.55,3,3))


def view_hidden():
    edges=[
        ((-3.5,-2.8,-2.9),(-3.5,2.8,-2.9)),
        ((-3.5,2.8,-2.9),(3.5,2.8,-2.9)),
        ((-3.5,2.8,-2.9),(-3.5,2.8,.3)),
        ((-3.5,.20,.3),(-.05,.20,.3))]
    return groups(body=stepped_block(),accent=[dash for a,b in edges
                      for dash in segmented(a,b,(.63,.41),.14)])


def view_visible():
    return groups(body=stepped_block())


def section():
    stock=cut(block(-3.3,-3.26,-3.04,4.42,6.52,6.08),cylinder((1.12,0,-3.35),1.48,6.8))
    return painted(stock,lambda p,k:abs(p[0]-1.12)<.04)

def place():
    return groups(body=[block(-3.7,-2.95,-3.45,7.4,5.90,.7),
                        block(-1.72,-1.48,1.9,3.44,2.96,1.72)],
                  accent=arrow((.25,-1.96,1.91),(.25,-1.96,-2.35),.23,.61,1.17))


def replace():
    return groups(body=[block(-4.15,-1.55,-2.0,2.8,2.85,3.10),
                        cylinder((2.55,.25,-2.0),1.46,3.1)],
                  accent=[arrow((-2.75,0,2.78),(3.74,0,2.78)),
                          arrow((3.48,-1.85,-3.03),(-3.74,-1.85,-3.03))])


def adaptive():
    marks=[]
    for cx,cz in ((-1.05,.45),(1.05,1.66)):
        points=[(cx+1.23*cos(tau*j/30),-2.22,cz+.66*sin(tau*j/30))
                for j in range(31)]
        marks.extend(chain(points,.16))
    return groups(body=[block(-4,-1.5,-2.5,2.8,3,3.7),block(1.2,-1.5,-1.9,2.8,3,3.7)],
                  accent=marks)


def edit_in_place():
    pencil=cylinder((.47,-2.42,-.36),.36,4.75,(.55,0,.835))
    tip=BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(.02,-2.42,-1.04),gp_Dir(.55,0,.835)),
                             0,.36,.82).Shape()
    return groups(body=[block(-3.75,-1.75,-2.7,3.55,3.5,4.15),
                        block(.62,0,-2.7,2.96,2.7,2.78)],
                  accent=[pencil,tip])


def free_move():
    z=-1.75
    return groups(body=cube(2.65),
                  accent=[arrow((1.4,0,z),(4.48,0,z)),
                          arrow((-1.4,0,z),(-4.48,0,z)),
                          arrow((0,1.4,z),(0,4.48,z)),
                          arrow((0,-1.4,z),(0,-4.48,z))])


def free_rotate():
    return groups(body=cube(4.65),accent=orbit((0,0,-1.15),3.82,.25,5.5,thickness=.18))


def move():
    p=(1.55,-1.55,1.55)
    return groups(body=cube(3.1),accent=[arrow(p,(4.5,p[1],p[2]),.17,.51,1.0),
                  arrow(p,(p[0],-4.5,p[2]),.17,.51,1.0),
                  arrow(p,(p[0],p[1],4.65),.17,.51,1.0)])


def bodies():
    return groups(body=[block(-1.13,-1.22,-1.6,2.26,2.44,3.2),
                         block(1.71,-1.22,-1.6,2.26,2.44,3.2)],
                  accent=block(-3.97,-1.22,-1.6,2.26,2.44,3.2))


def features():
    rows=[block(-2.9,-1.45,z,2.2,2.05,1.8) for z in (-3.8,-.86,2.08)]
    bars=[tube((.27,-1.45,z),(3.9,-1.45,z),.17) for z in (-2.9,.04,2.98)]
    return groups(body=rows[:2],accent=rows[2],line=bars)


def create_part():
    p=(2.45,-2.0,2.40)
    return groups(body=block(-3.46,-2.15,-2.7,5.2,4.4,4.5),
                  accent=[tube((1.20,p[1],p[2]),(3.92,p[1],p[2]),.22),
                          tube((p[0],p[1],1.13),(p[0],p[1],3.65),.22)])


def dof():
    straight=move()['accent']
    curves=[]
    for axis in range(3):
        remaining=[i for i in range(3) if i!=axis]
        points=[]
        for j in range(16):
            angle=.40+j*.22
            point=[0.,0.,0.]
            point[axis]=-1.75
            point[remaining[0]]=2.45*cos(angle)
            point[remaining[1]]=2.45*sin(angle)
            points.append(tuple(point))
        curves.extend(chain(points[:-2],.105))
        curves.append(arrow(points[-3],points[-1],.105,.31,.36))
    return groups(body=cube(2.65),accent=straight,line=curves)


def c3d_mate():
    return groups(body=[block(-2.85,-2.52,-3.35,5.7,5.04,1.45),
                        block(-2.85,-2.52,1.9,5.7,5.04,1.45)],
                  accent=[block(-2.85,-2.52,-1.9,5.7,5.04,.13),
                          block(-2.85,-2.52,1.77,5.7,5.04,.13),
                          arrow((3.7,-.10,2.41),(3.7,-.10,.29),.18,.53,.93),
                          arrow((3.7,-.10,-2.41),(3.7,-.10,-.29),.18,.53,.93)])


def c3d_flush():
    a=block(-3.95,-2.2,-2.7,3.12,4.4,4.0)
    b=block(.33,-2.2,-1.25,3.65,4.4,2.55)
    return groups(body=[a,b],accent=[block(-3.95,-2.2,1.3,3.12,4.4,.13),
                     block(.33,-2.2,1.3,3.65,4.4,.13)],
                  line=segmented((-4.4,-2.35,1.42),(4.45,-2.35,1.42),(.55,.32)))


def c3d_angle():
    low=block(-3.44,-3.65,-1.87,6.88,4.16,.34)
    high=prism([(-3.44,.5,-1.5),(3.44,.5,-1.5),
                (3.44,2.95,2.60),(-3.44,2.95,2.60)],(0,0,.32))
    under=block(-3.44,-3.65,-1.53,6.88,4.16,.065)
    return groups(body=[low,high],accent=[under, tube((-3.41,.53,-1.2),(3.41,.53,-1.2),.16)])


def c3d_insert():
    lower=cut(block(-3.45,-3.03,-3.18,6.9,6.06,1.62),cylinder((0,0,-3.4),1.27,2.22))
    pin=cylinder((0,0,.38),1.13,3.1)
    body, active=[],[]
    for face,p,k in surfaces(lower):
        (active if 'Cylinder' in str(k) else body).append(face)
    return groups(body=body+[pin],accent=active+[arrow((2.85,0,2.9),(2.85,0,-.72),.18,.53,1.06)])


def c3d_parallel():
    a=block(-2.50,-3.95,-1.90,5,3.51,1.41)
    b=block(-2.50,.44,-1.90,5,3.51,1.41)
    return groups(body=[a,b],accent=[arrow((0,y,-.47),(0,y,2.69),.18,.54,1.1)
                                    for y in (-2.195,2.195)])


def c3d_symmetry():
    a=union(block(-4.,-1.7,-2.1,2.8,3.4,1.15),block(-4,-1.7,-.95,.9,3.4,2.03))
    b=union(block(1.2,-1.7,-2.1,2.8,3.4,1.15),block(3.1,-1.7,-.95,.9,3.4,2.03))
    return groups(body=[a,b],accent=block(-.065,-2.65,-2.25,.13,5.3,4.55))


def c3d_tangent():
    return groups(body=[block(-3.45,-2.9,-2.65,6.9,5.8,.72),ball((0,0,.47),2.4)],
                  accent=ball((.02,-.05,-1.79),.43))


def sheet_profile(profile, span=6.9):
    return prism([(-span/2,y,z) for y,z in profile],(span,0,0))


def sheet_fold(angle=pi/2, side=-1):
    run, rad, leg, thick=3.65,.55,2.85,.28
    points=lambda r:[(r*sin(t),-1.7+rad-r*cos(t)) for t in [angle*j/15 for j in range(16)]]
    outer,inner=points(rad),points(rad-thick)
    extend=lambda q:(q[0]+leg*cos(angle),q[1]+leg*sin(angle))
    contour=[(-run,-1.7),*outer,extend(outer[-1]),extend(inner[-1]),*reversed(inner),(-run,-1.7+thick)]
    if side>0:
        contour=[(-y,z) for y,z in contour]
    return painted(sheet_profile(contour),lambda p,k:p[1]*(-side)>-.17 and p[2]>-1.52)


def sm_flange():
    return sheet_fold()


def sm_fold():
    return sheet_fold(pi*.30)


def sm_folded():
    return sheet_fold(pi*.63,1)


def sm_contour():
    shape=sheet_profile([(-3.4,1.55),(-3.4,-1.15),(-2.85,-1.7),(2.85,-1.7),
                        (3.4,-1.15),(3.4,1.55),(3.15,1.55),(3.15,-1.05),
                        (2.73,-1.45),(-2.73,-1.45),(-3.15,-1.05),(-3.15,1.55)])
    return painted(shape,lambda p,k:p[1]<-3.10 and p[2]>-.6)


def sm_corner():
    return groups(body=[block(-3.55,-2.8,-1.75,7.1,5.6,.25),
                        block(-3.55,2.55,-1.5,7.1,.25,3.25)],
                  accent=block(3.3,-2.8,-1.5,.25,5.34,3.25))


def sm_face():
    return painted(block(-3.6,-3.1,-.16,7.2,6.2,.32),lambda p,k:p[2]>.15)


def sm_flat():
    bars=[dash for y in (-1.25,1.25) for dash in
          segmented((-3.55,y,.115),(3.55,y,.115),(.69,.47),.15)]
    return groups(body=block(-3.72,-3,-.21,7.44,6,.30),accent=bars)


def gear(center, r=1.15):
    x,y,z=center
    outline=[(x+(r if i%4 in (0,1) else r*.73)*cos(tau*i/32),
              y+(r if i%4 in (0,1) else r*.73)*sin(tau*i/32),z) for i in range(32)]
    return cut(prism(outline,(0,0,.28)),cylinder((x,y,z-.08),r*.31,.6))


def sm_defaults():
    return groups(body=sheet_profile([(-3.3,-1.3),(.74,-1.3),(.74,2.45),(.47,2.45),
                                       (.47,-1.03),(-3.3,-1.03)],4.55),
                  accent=gear((2.75,-1.85,.25),1.24))


def sm_convert():
    bent=sheet_profile([(-2.5,-1.25),(.95,-1.25),(.95,1.67),(.70,1.67),
                        (.70,-1),(-2.5,-1)],2.6)
    return groups(body=[bent,block(1.67,.55,-1.25,2.2,2.75,2.25)],
                  accent=arrow((-.13,-.14,2.05),(3.23,-.14,2.05),.18,.45,.95))


def sm_to_standard():
    shape=sheet_profile([(-3.05,-1.65),(1.04,-1.65),(1.04,1.55),(.77,1.55),
                         (.77,-1.38),(-3.05,-1.38)],3.70)
    return groups(body=[shape,block(2.17,-1.05,-1.48,2.18,2.15,2.55)],
                  accent=arrow((-.18,-.16,2.32),(3.75,-.16,2.32),.18,.48,1.06))


def sm_corner_round():
    plate=block(-3.55,-3,-.2,7.10,6,.35)
    tool=cut(block(1.5,-3.55,-.4,2.55,2.6,.8),cylinder((1.5,-.95,-.52),2.06,1.0))
    return painted(cut(plate,tool),lambda p,k:'Cylinder' in str(k))


def sm_adjacent():
    variant=sheet_fold(pi/2)
    notch=segmented((-3.47,-.58,-1.38),(3.47,-.58,-1.38),(.65,.38),.12)
    return groups(body=combine_parts([variant['body'],variant['accent']]),accent=notch)


def sm_inside():
    variant=sheet_fold(pi/2)
    notch=segmented((-3.47,.62,.27),(3.47,.62,.27),(.65,.38),.12)
    return groups(body=combine_parts([variant['body'],variant['accent']]),accent=notch)


def hemmed(turn):
    r=.57 if turn!=1 else .72
    sweep_angle={0:pi,1:pi*1.75,2:pi*1.32,3:pi}[turn]
    outer=[(r*sin(a),-1.13+r-r*cos(a)) for a in [sweep_angle*j/32 for j in range(33)]]
    inner=[((r-.21)*sin(a),-1.13+r-(r-.21)*cos(a)) for a in [sweep_angle*j/32 for j in range(33)]]
    if turn==3:
        lip=[(-1.65,-1.13+2*r),(-1.65,-.28),(-1.44,-.28),(-1.44,-1.13+2*r-.21)]
    elif turn==2:
        lip=[(-1.52,-.48),(-1.44,-.66)]
    elif turn==0:
        lip=[(-1.98,-1.13+2*r),(-1.98,-1.13+2*r-.21)]
    else:
        lip=[]
    shape=sheet_profile([(-3.95,-1.13),*outer,*lip,*reversed(inner),(-3.95,-.92)])
    return painted(shape,lambda p,k:p[1]>-.13 and p[2]>-1.10)


def sm_hem():
    return hemmed(0)


def sm_hem_rolled():
    return hemmed(1)


def sm_hem_teardrop():
    return hemmed(2)


def sm_hem_double():
    return hemmed(3)


def perforations(style):
    plate=block(-3.7,-2.55,-.25,7.4,5.1,.4)
    marks=[]
    for x in (-2.4,0,2.4):
        if style==0:
            pts=[(x-.41,-1.4,.19),(x+.38,-.28,.19),(x-.4,.9,.19)]
        elif style==1:
            pts=[(x,-1.35,.19),(x,1.35,.19)]
        else:
            pts=[(x-.68,-.8,.19),(x-.33,.73,.19),(x+.33,.73,.19),(x+.68,-.8,.19)]
        marks.extend(chain(pts,.16))
    return groups(body=plate,accent=marks)


def sm_perforation():
    return perforations(0)


def sm_perforation_straight():
    return perforations(1)


def sm_perforation_trapezoid():
    return perforations(2)


def beam(x,y,z,length,w=1.55,h=1.55):
    cross=[(x,y,z),(x,y+w,z),(x,y+w,z+.31),(x,y+.98,z+.31),
           (x,y+.98,z+h-.31),(x,y+w,z+h-.31),(x,y+w,z+h),
           (x,y,z+h),(x,y,z+h-.31),(x,y+.57,z+h-.31),
           (x,y+.57,z+.31),(x,y,z+.31)]
    return prism(cross,(length,0,0))


def hollow(x,y,z,dx,dy,dz,axis=0):
    dimensions=[dx,dy,dz]
    start=[x+.23,y+.23,z+.23]
    inside=[d-.46 for d in dimensions]
    start[axis]-=.34
    inside[axis]=dimensions[axis]+.22
    return cut(block(x,y,z,dx,dy,dz),block(*start,*inside))


def joint(left_miter=False):
    if left_miter:
        a=prism([(-3.75,-.72,-.76),(.66,-.72,-.76),(2.18,.78,-.76),(-3.75,.78,-.76)],(0,0,1.5))
        b=prism([(.78,-3.63,-.76),(2.30,-3.63,-.76),(2.30,.74,-.76),(.78,-.76,-.76)],(0,0,1.5))
        return groups(body=a,accent=b)
    return groups(body=hollow(-3.85,.10,-.85,5.12,1.55,1.7),
                  accent=hollow(1.30,-3.5,-.85,1.55,5.15,1.7,1))


def frame_assembly():
    return groups(body=[hollow(-3.49,-.72,-3.52,1.41,1.44,5.3,2),
                       hollow(2.08,-.72,-3.52,1.41,1.44,5.3,2)],
                  accent=beam(-3.49,-.78,1.80,6.98))


def frame_insert():
    return groups(body=[hollow(-3.42,-.65,-3.7,1.3,1.3,4.2,2),
                         hollow(2.12,-.65,-3.7,1.3,1.3,4.2,2),
                         beam(-3.42,-.78,1.45,6.84)],
                  accent=arrow((0,-1.65,3.85),(0,-1.65,.57),.19,.58,1))


def frame_change():
    return groups(body=beam(-2.83,-.78,-1.34,5.66),
                  accent=orbit((0,0,-.30),3.62,.25,5.45,thickness=.17))


def frame_corner():
    return joint()


def frame_miter():
    return joint(True)


def frame_lengthen():
    return groups(body=beam(-2.78,-.78,-1.3,5.56),
                  accent=[arrow((-1.0,0,1.48),(-4.55,0,1.48)),
                          arrow((1.0,0,1.48),(4.55,0,1.48))])


def frame_library():
    angle=union(block(-3.25,-3.0,-1.0,6.5,1.28,.30),block(-3.25,-3.0,-.70,6.5,.30,1.08))
    return groups(body=[angle,hollow(-3.25,1.40,-1.,6.5,1.48,1.45)],
                  accent=beam(-3.25,-.76,-1.,6.5))


def frame_member():
    c=beam(-3.6,-1.05,-1.25,7.2,2.1,2.5)
    return painted(c,lambda p,k:p[0]>3.55)


def frame_notch():
    s=cut(hollow(-3.54,-1.21,-1.13,7.08,2.42,2.25),block(-1.0,-1.45,-.28,2,1.9,1.9))
    return painted(s,lambda p,k:abs(abs(p[0])-1.0)<.035 or abs(p[1]-.45)<.035)


def frame_trim():
    a=hollow(-3.88,-.65,-.89,4.56,1.65,1.8)
    b=hollow(.82,-3.41,-.89,1.66,6.10,1.8,1)
    return painted(combine_parts([a,b]),lambda p,k:abs(p[0]-.68)<.035 or abs(p[0]-.82)<.035)


def frame_refresh():
    return groups(body=beam(-2.78,-.78,-1.30,5.56),
                  accent=orbit((0,0,-.32),3.63,1.15,6.05,thickness=.17))


def frame_analysis():
    model=frame_assembly()
    return groups(body=combine_parts([model['body'],model['accent']]),
                  accent=arrow((0,-.82,4.63),(0,-.82,2.43),.18,.56,.95),
                  line=chain([(-2.8+.28*j,-1.02,1.1-.84*sin(pi*j/20)) for j in range(21)],.12))


def frame_untreat():
    model=frame_miter()
    x=[tube((1.25,-2.94,1.9),(3.45,-2.94,4.1),.20),tube((3.45,-2.94,1.9),(1.25,-2.94,4.1),.20)]
    return groups(body=combine_parts([model['body'],model['accent']]),accent=x)


def frame_time():
    stock=beam(-3.6,-1.04,-2.32,6.62)
    dial=cylinder((.4,-1.94,1.32),1.35,.53,(0,1,0))
    return groups(body=[stock,dial],line=[tube((.4,-2,1.32),(.4,-2,2.23),.11),
                  tube((.4,-2,1.32),(1.02,-2,.98),.11)],
                  accent=block(.08,-1.83,2.6,.64,.45,.48))


MODELS = {
    'extrude':extrude,'revolve':revolve,'sweep':sweep,'loft':loft,'cut':cut_icon,
    'cut_face':cut_face,'hole':hole,'fillet':fillet,'chamfer':chamfer,'shell':shell,
    'split':split,'split_faces':split_faces,'split_solid':split_solid,'combine':combine,
    'emboss':emboss,'engrave':engrave,'box':box,'cylinder':cylinder_icon,'sphere':sphere,
    'shaded':shaded,'shaded_edges':shaded_edges,'wireframe':wireframe,'xray':xray,
    'iso':iso,'top':top,'front':front,'right':right,'view_hidden':view_hidden,
    'view_visible':view_visible,'section':section,'place':place,'replace':replace,
    'adaptive':adaptive,'edit_in_place':edit_in_place,'free_move':free_move,'free_rotate':free_rotate,
    'move':move,'bodies':bodies,'features':features,'create_part':create_part,'dof':dof,
    'c3d_mate':c3d_mate,'c3d_flush':c3d_flush,'c3d_angle':c3d_angle,'c3d_insert':c3d_insert,
    'c3d_parallel':c3d_parallel,'c3d_symmetry':c3d_symmetry,'c3d_tangent':c3d_tangent,
    'sm_flange':sm_flange,'sm_fold':sm_fold,'sm_folded':sm_folded,'sm_contour':sm_contour,
    'sm_corner':sm_corner,'sm_face':sm_face,'sm_flat':sm_flat,'sm_defaults':sm_defaults,
    'sm_convert':sm_convert,'sm_to_standard':sm_to_standard,'sm_corner_round':sm_corner_round,
    'sm_adjacent':sm_adjacent,'sm_inside':sm_inside,'sm_hem':sm_hem,'sm_hem_rolled':sm_hem_rolled,
    'sm_hem_teardrop':sm_hem_teardrop,'sm_hem_double':sm_hem_double,'sm_perforation':sm_perforation,
    'sm_perforation_straight':sm_perforation_straight,'sm_perforation_trapezoid':sm_perforation_trapezoid,
    'frame_assembly':frame_assembly,'frame_insert':frame_insert,'frame_change':frame_change,
    'frame_corner':frame_corner,'frame_miter':frame_miter,'frame_lengthen':frame_lengthen,
    'frame_library':frame_library,'frame_member':frame_member,'frame_notch':frame_notch,
    'frame_trim':frame_trim,'frame_refresh':frame_refresh,'frame_analysis':frame_analysis,
    'frame_untreat':frame_untreat,'frame_time':frame_time,
}
