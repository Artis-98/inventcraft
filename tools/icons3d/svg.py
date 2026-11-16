"""Redraw the specified flat icons and reduce stroke weights to 1.1 units."""
from pathlib import Path
import math
import xml.etree.ElementTree as ET

NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
PALETTE = dict(i='#2b3540', a='#b9820f', s='#7a8693', r='#d9534f',
               g='#69c26b', w='#e0a355', n='none')
APPROVED = {'doc_part', 'doc_assembly', 'doc_drawing', 'doc_cam'}


def path(d, fill='n', stroke='n', opacity=1, dash=None):
    attrs = {'d': d, 'fill': PALETTE[fill]}
    if opacity != 1:
        attrs['fill-opacity'] = str(opacity)
    if stroke != 'n':
        attrs.update({'stroke': PALETTE[stroke], 'stroke-width': '1.1',
                      'stroke-linecap': 'round', 'stroke-linejoin': 'round'})
    if dash:
        attrs['stroke-dasharray'] = dash
    return ET.Element(f'{{{NS}}}path', attrs)


def line(d, color='i', dash=None):
    return path(d, stroke=color, dash=dash)


def dot(x,y,r,color='a'):
    return ET.Element(f'{{{NS}}}circle', {'cx': str(x),'cy': str(y),
                                           'r': str(r),'fill': PALETTE[color]})


def arrow(x,y,u,v, size=3.05):
    theta=math.atan2(v-y,u-x)
    base=(u-size*math.cos(theta),v-size*math.sin(theta))
    left=(base[0]+size*.42*math.sin(theta),base[1]-size*.42*math.cos(theta))
    right=(base[0]-size*.42*math.sin(theta),base[1]+size*.42*math.cos(theta))
    return [line(f'M{x} {y}L{base[0]:.2f} {base[1]:.2f}','a'),
            path(f'M{u} {v}L{left[0]:.2f} {left[1]:.2f} {right[0]:.2f} {right[1]:.2f}Z','a')]


def part():
    return [path('M5 9L12 5.25 19 9V16.2L12 20 5 16.2Z','s','i',.78),
            path('M5 9L12 5.25 19 9 12 12.75Z','s','i',.64),
            line('M12 12.75V20')]


def folder():
    return [path('M3.35 7H9.65L11.65 9.2H19.65V18.25H3.35Z','s','i',.82),
            path('M5.75 11.1H21.1L18.55 18.55H3.35Z','a','i')]


def redraw():
    return {
        'measure':[
            path('M4.15 17.8L17.15 4.8 18.65 6.3 5.65 19.3Z','s','i',.82),
            line('M7.2 14.8L9 16.6M9.6 12.4L10.8 13.6M12 10L13.8 11.8M14.4 7.6L15.6 8.8'),
            path('M4.15 17.8L3.5 13.85 6.55 10.8 7.65 11.9 5.65 13.9 5.9 16.05Z','s','i',.82),
            path('M10.6 11.35L9.95 7.4 13 4.35 14.1 5.45 12.1 7.45 12.35 9.6Z','s','i',.82),
            line('M5.7 11.65L6.55 10.8 7.65 11.9M12.15 5.2L13 4.35 14.1 5.45','a')],
        'project_geometry':[
            path('M3.3 15.65L10.3 11.85 20.7 15.4 13.7 19.25Z','s','i',.6),
            line('M5.65 6.1L9.75 4.25 16.9 7.1'),
            line('M5.65 6.1V14.65M16.9 7.1V15.35','i','1.4 1.15'),
            line('M5.65 14.65L9.75 12.8 16.9 15.35','a')],
        'library':[
            path('M3.8 4.35H20.2V19.65H3.8Z','s','i',.74),line('M12 4.35V13M3.8 11.15H20.2'),
            line('M6.35 7.35H9.5M14.45 7.35H17.6M6.35 15.05H9.5'),
            path('M12 13H20.2L21.0 18.05H12Z','s','i'),
            path('M16.5 13.05L18.1 13.9V15.65L16.5 16.5 14.9 15.65V13.9Z','a','i')],
        'auto':[
            line('M4 7.2H15.5V19.65H4Z'),
            line('M5.9 11.65H9.6M5.9 13.65H9.6M11.5 16.1H13.6V18.2','a'),
            path('M17.7 3.0L14.6 8.7H17.4L16.75 12 21 6.5H18.25L19.25 3Z','a')],
        'point': [line('M9 12H3M15 12H21M12 9V3M12 15V21'),dot(12,12,2)],
        'dv_projected':[
            path('M3.65 7.65H10.3V14.3H3.65Z','s','i',.78),
            path('M14.5 7.65H21.15V14.3H14.5Z','s','i',.45),
            *arrow(8.6,11,16,11,2.7)],
        'dv_auxiliary':[
            path('M3.8 19.7V11.7L8.6 6.9 12.3 10.6V19.7Z','s','i',.72),
            line('M3.8 11.7L8.6 6.9','a'),
            path('M14.4 3.3L20.5 9.4 18.25 11.65 12.15 5.55Z','s','i',.61),
            *arrow(8,11.2,14,5.2,2.7)],
        'dv_break':[
            path('M3.1 7.7H9.75L8.5 11.0 9.65 13.25 8.4 16.3H3.1ZM20.9 7.7H15.4L14.15 11 15.3 13.25 14.05 16.3H20.9Z','s','i',.81),
            line('M9.75 7.7L8.5 11 9.65 13.25 8.4 16.3M15.4 7.7L14.15 11 15.3 13.25 14.05 16.3','a')],
        'dv_unbreak':[
            path('M3.1 10H20.9V17.35H3.1Z','s','i',.83),
            *arrow(5.1,6.65,11.15,6.65,2.45),*arrow(18.9,6.65,12.85,6.65,2.45)],
        'update':[
            *part(),path('M17.15 2.6L13.05 9.15H16.1L15.25 14.35 21 6.95H17.95L19.35 2.6Z','a','i')],
        'regenerate':[
            path('M8.05 9.9L12 7.8 15.95 9.9V14.3L12 16.4 8.05 14.3Z','s','i',.84),
            line('M4.2 11A7.85 7.85 0 0 1 16.85 5.9M19.8 13A7.85 7.85 0 0 1 7.15 18.1','a'),
            path('M19 7.9L14.75 6.95 17.15 3.7ZM5 16.1L9.25 17.05 6.85 20.3Z','a')],
        'params':[
            path('M4 4.2H20V19.8H4Z','s','i',.47),
            line('M4 9.4H20M4 14.6H20M6.5 6.8H12.5M6.5 12H11.05M6.5 17.2H12.5'),
            path('M15.4 5.55H18.15V8.05H15.4ZM15.4 10.75H18.15V13.25H15.4ZM15.4 15.95H18.15V18.45H15.4Z','a')],
        'delete':[
            path('M6.05 9.1H17.95L16.3 20.25H7.7Z','r','i'),
            path('M4.35 7.0L18.65 4.8 18.85 6.35 4.55 8.55Z','s','i',.84),
            line('M9.0 6.28L8.85 4.1 13.25 3.4 13.65 5.59')],
        'open':folder(),
        'folder_open':folder(),
        'an_text':[
            line('M3.2 16.7L7 7.3 10.8 16.7M4.75 13.2H9.25'),
            line('M13.0 8.25H20.6','a'),line('M13.0 12H20.6M13.0 15.75H18.75')],
        'an_weld':[
            line('M8.4 9.0H20.85'),line('M8.4 9.0L4.6 17.1'),
            path('M3.85 19.15L4.1 14.4 7.55 16.2Z','i'),
            path('M13.25 9L17.7 9 13.25 13.1Z','a')],
        'an_datum':[
            path('M8.1 3.4H15.9V10.05H8.1Z','s','i',.5),line('M12 10.05V14.9'),
            path('M12 13.85L8.45 17.95H15.55Z','a'),line('M4.35 18.05H19.65')],
    }


def update_svg(folder: Path):
    drawing = redraw()
    changed = 0
    allowed = set(PALETTE.values())
    for file in sorted(folder.glob('*.svg')):
        if file.stem in APPROVED or file.with_suffix('.png').exists():
            continue
        if file.stem in drawing:
            root=ET.Element(f'{{{NS}}}svg', {'viewBox':'0 0 24 24'})
            root.extend(drawing[file.stem])
            modified=True
        else:
            root=ET.parse(file).getroot()
            modified=False
        for el in root.iter():
            if float(el.get('stroke-width','0')) >= 1.5:
                el.set('stroke-width','1.1')
                modified=True
            for attr in ('fill','stroke'):
                if attr not in el.attrib:
                    continue
                color=el.get(attr).lower()
                if color not in allowed:
                    raise ValueError(f'{file.name}: unsupported {attr} {color}')
                if color!=el.get(attr):
                    el.set(attr,color)
                    modified=True
        if root.get('viewBox') != '0 0 24 24' or 'width' in root.attrib or 'height' in root.attrib:
            raise ValueError(f'{file.name}: wrong canvas')
        if modified:
            file.write_bytes(ET.tostring(root, encoding='utf-8'))
            changed+=1
    return changed


if __name__ == '__main__':
    assets=Path(__file__).resolve().parents[2]/'datum/ui/assets/icons'
    print(f'Updated {update_svg(assets)} SVGs.')
