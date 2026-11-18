"""Build InventCraft's standard parts library from open sources.

    python tools/stdlib/build.py <FreeCAD_FastenersWB> <cq_warehouse> <FreeCAD profiles.csv>

Writes one CSV per family into ``datum/stdlib``: the fasteners, the
bearings and the steel profiles.  Every file says where its numbers came
from and under which licence, so the folder can be given away on its own.

The sources, each at a pinned commit (see datum/stdlib/README.md):

* FreeCAD Fasteners Workbench, LGPL-2.1-or-later: bolts, screws, nuts,
  washers, pins, retaining rings;
* cq_warehouse, Apache-2.0: ball bearing dimensions (d, D, B only, the
  ISO 15 boundary dimensions; no manufacturer's ratings);
* FreeCAD BIM profiles.csv, LGPL-2.1-or-later: steel profiles, with root
  radii added from EN 10365 and the DIN 1025 / 1026 rules.

Nothing here is read from any commercial CAD program's library.
"""
from __future__ import annotations

import csv
import glob
import math
import os
import re
import sys
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))))
OUT = os.path.join(ROOT, "datum", "stdlib")

FSWB = "FreeCAD Fasteners Workbench"
FSWB_LICENCE = "LGPL-2.1-or-later"
CQW = "cq_warehouse"
CQW_LICENCE = "Apache-2.0"
BIM = "FreeCAD BIM profiles"
BIM_LICENCE = "LGPL-2.1-or-later"


# ------------------------------------------------------------ the reading

def read_fswb(folder: str):
    """Every table in FsData, by name: {name: (header, {key: row})}.
    Single cell lines name the table that follows; several in a row are
    the same table under several names."""
    tables = {}
    for path in sorted(glob.glob(os.path.join(folder, "FsData", "*.csv"))):
        stem = os.path.splitext(os.path.basename(path))[0]
        with open(path, newline="", encoding="utf-8") as fp:
            names, cur, new, first = {stem}, {}, False, True
            head: List[str] = []
            for line in csv.reader(fp, skipinitialspace=True):
                line = [c.strip() for c in line]
                if not line or not any(line):
                    continue
                if len(line) == 1:
                    if not new:
                        cur, names, new = {}, set(), True
                    names.add(line[0])
                    continue
                if new or first:
                    first = new = False
                    head = line[1:]
                    for n in names:
                        tables[n] = (head, cur)
                    continue
                cur[line[0]] = line[1:]
    return tables


def num(text) -> Optional[float]:
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


INCH = 25.4


def diameter(size: str, dia_list) -> Optional[float]:
    """The nominal diameter a size is called by: M8 and M8x1 are 8,
    1/4in is 6.35, #10 is out of FreeCAD's list, 6 mm and ST4.2 are 6
    and 4.2."""
    s = size.strip().strip("()")
    m = re.match(r"^M(\d+(?:\.\d+)?)", s)
    if m:
        return float(m.group(1))
    m = re.match(r"^ST(\d+(?:\.\d+)?)", s)
    if m:
        return float(m.group(1))
    if s.startswith("#"):
        hit = dia_list.get(s)
        return num(hit[0]) if hit else None
    m = re.match(r"^(\d+(?: \d+/\d+)?|\d+/\d+)\s*in$", s)
    if m:
        return float(sum(Fraction(p) for p in m.group(1).split())) * INCH
    m = re.match(r"^(\d+(?:\.\d+)?)\s*mm$", s)
    if m:
        return float(m.group(1))
    return None


def label(size: str) -> str:
    s = size.strip().strip("()")
    s = re.sub(r"\s*mm$", "", s)
    return s.replace("in", '"') if s.endswith("in") else s


# --------------------------------------------------- the fastener families
#
# Each entry: FreeCAD type, our id, standard as shown, name, where it
# sits, kind, drive, and our columns from FreeCAD's.  A column is a
# FreeCAD column name, a number, or a function of the row (r) and the
# nominal diameter (d).  ``head`` names another table to read the head
# from when a type keeps only its drive (the hexalobular cap screw is an
# ISO 4762 head with a different socket).

B = "Fasteners/Bolts"
S = "Fasteners/Screws"
N = "Fasteners/Nuts"
W = "Fasteners/Washers"
P = "Fasteners/Pins"
R = "Fasteners/Retaining Rings"


def col(*names):
    """The first of several columns a table has."""
    def get(r, d):
        for n in names:
            if n in r and num(r[n]) is not None:
                return num(r[n])
        raise KeyError(names[0])
    return get


def inch(name):
    """A column FreeCAD keeps in inches."""
    return lambda r, d: num(r[name]) * INCH


def csk_k(angle):
    """A countersunk head's height from its diameter, at its angle."""
    return lambda r, d: (num(r["dk_theo"]) - d) / 2.0 / math.tan(
        math.radians(angle / 2.0))


HEX = {"s": col("s", "s_nom", "s_nom_max", "s_max", "F"),
       "k": col("k", "k_nom", "k_max", "H")}
CROSS = {"s": col("mH"), "t": lambda r, d: num(r["mH"]) * 0.45}

F: List[Tuple] = [
    # -- hex head bolts and screws
    ("ISO4014", "iso-4014", "ISO 4014", "Hex Head Bolt", B + "/Hex Head",
     "hex_bolt", "", dict(HEX)),
    ("ISO4017", "iso-4017", "ISO 4017", "Hex Head Screw, full thread",
     B + "/Hex Head", "hex_bolt", "", dict(HEX)),
    ("ISO4015", "iso-4015", "ISO 4015", "Hex Head Bolt, reduced shank",
     B + "/Hex Head", "hex_bolt", "", dict(HEX)),
    ("ISO4016", "iso-4016", "ISO 4016", "Hex Head Bolt, grade C",
     B + "/Hex Head", "hex_bolt", "", dict(HEX)),
    ("ISO4018", "iso-4018", "ISO 4018", "Hex Head Screw, grade C",
     B + "/Hex Head", "hex_bolt", "", dict(HEX)),
    ("ISO8765", "iso-8765", "ISO 8765", "Hex Head Bolt, fine thread",
     B + "/Hex Head", "hex_bolt", "", dict(HEX)),
    ("ISO8676", "iso-8676", "ISO 8676", "Hex Head Screw, fine thread",
     B + "/Hex Head", "hex_bolt", "", dict(HEX)),
    ("DIN933", "din-933", "DIN 933", "Hex Head Screw, full thread",
     B + "/Hex Head", "hex_bolt", "", dict(HEX)),
    ("DIN961", "din-961", "DIN 961", "Hex Head Screw, fine thread",
     B + "/Hex Head", "hex_bolt", "", dict(HEX)),
    ("ASMEB18.2.1.6", "asme-b18-2-1-hex", "ASME B18.2.1",
     "Hex Cap Screw, UNC", B + "/Hex Head", "hex_bolt", "", dict(HEX)),
    ("DIN571", "din-571", "DIN 571", "Hex Head Wood Screw",
     S + "/Wood", "hex_bolt", "", {"s": col("s"), "k": col("k")}),
    ("ASMEB18.2.1.1", "asme-b18-2-1-square", "ASME B18.2.1",
     "Square Head Bolt, UNC", B + "/Square Head", "square_bolt", "",
     {"s": inch("F"), "k": inch("H")}),
    # -- hex flange bolts
    ("EN1662", "en-1662", "EN 1662", "Hex Flange Bolt, small series",
     B + "/Hex Flange", "hex_bolt", "",
     {"s": col("s"), "k": col("k"), "dc": col("dc"), "c": col("c")}),
    ("EN1665", "en-1665", "EN 1665", "Hex Flange Bolt, heavy series",
     B + "/Hex Flange", "hex_bolt", "",
     {"s": col("s"), "k": col("k"), "dc": col("dc"), "c": col("c")}),
    ("ISO4162", "iso-4162", "ISO 4162", "Hex Flange Bolt",
     B + "/Hex Flange", "hex_bolt", "",
     {"s": col("s_max"), "k": col("k_max"), "dc": col("d_c_max"),
      "c": col("c_min")}),
    ("ISO15071", "iso-15071", "ISO 15071", "Hex Flange Bolt",
     B + "/Hex Flange", "hex_bolt", "",
     {"s": col("s_max"), "k": col("k_max"), "dc": col("d_c_max"),
      "c": col("c_min")}),
    ("ISO15072", "iso-15072", "ISO 15072", "Hex Flange Bolt, fine thread",
     B + "/Hex Flange", "hex_bolt", "",
     {"s": col("s_max"), "k": col("k_max"), "dc": col("d_c_max"),
      "c": col("c_min")}),
    # -- socket head cap screws
    ("ISO4762", "iso-4762", "ISO 4762", "Socket Head Cap Screw",
     B + "/Socket Head", "socket_head", "hex",
     {"dk": col("dk_max"), "k": col("k"), "s": col("s_mean"),
      "t": col("t")}),
    ("DIN7984", "din-7984", "DIN 7984", "Socket Head Cap Screw, low head",
     B + "/Socket Head", "socket_head", "hex",
     {"dk": col("dk_max"), "k": col("k"), "s": col("s_mean"),
      "t": col("t")}),
    ("DIN6912", "din-6912", "DIN 6912",
     "Socket Head Cap Screw, low head with pilot", B + "/Socket Head",
     "socket_head", "hex",
     {"dk": col("dk_max"), "k": col("k"), "s": col("s_mean"),
      "t": col("t1")}),
    ("ISO14579", "iso-14579", "ISO 14579", "Hexalobular Socket Cap Screw",
     B + "/Socket Head", "socket_head", "torx",
     {"dk": col("dk_max"), "k": col("k"), "s": col("A"),
      "t": col("t_mean")}, "ISO4762def"),
    ("ASMEB18.3.1A", "asme-b18-3-cap", "ASME B18.3",
     "Socket Head Cap Screw, UNC", B + "/Socket Head", "socket_head", "hex",
     {"dk": col("dk_max"), "k": col("k"), "s": col("s_mean"),
      "t": col("t")}),
    ("ASMEB18.3.1G", "asme-b18-3-low", "ASME B18.3",
     "Socket Head Cap Screw, low head, UNC", B + "/Socket Head",
     "socket_head", "hex",
     {"dk": col("A"), "k": col("H"), "s": col("J"), "t": col("T")}),
    # -- shoulder screws: L is the shoulder
    ("ISO7379", "iso-7379", "ISO 7379", "Socket Shoulder Screw",
     B + "/Shoulder", "shoulder", "hex",
     {"d1": col("d1"), "dk": col("d3"), "k": col("l3"), "lt": col("l2"),
      "s": col("SW"), "t": lambda r, d: num(r["l3"]) * 0.4}),
    ("ASMEB18.3.4", "asme-b18-3-shoulder", "ASME B18.3",
     "Socket Shoulder Screw, UNC", B + "/Shoulder", "shoulder", "hex",
     {"d1": col("d1"), "dk": col("d3"), "k": col("l3"), "lt": col("l2"),
      "s": col("SW"), "t": lambda r, d: num(r["l3"]) * 0.4}),
    # -- button heads
    ("ISO7380-1", "iso-7380-1", "ISO 7380-1", "Button Head Screw",
     S + "/Button Head", "dome", "hex",
     {"dk": col("dk"), "k": col("k"), "s": col("s_mean"),
      "t": col("t_min")}),
    ("ISO7380-2", "iso-7380-2", "ISO 7380-2",
     "Button Head Screw with collar", S + "/Button Head", "dome", "hex",
     {"dk": col("dk"), "k": col("k"), "s": col("s_mean"),
      "t": col("t_min"), "dc": col("dk_c"), "c": col("c")}),
    ("ASMEB18.3.3A", "asme-b18-3-button", "ASME B18.3",
     "Button Head Screw, UNC", S + "/Button Head", "dome", "hex",
     {"dk": col("dk"), "k": col("k"), "s": col("s"), "t": col("t")}),
    ("ASMEB18.3.3B", "asme-b18-3-button-flange", "ASME B18.3",
     "Button Head Screw with flange, UNC", S + "/Button Head", "dome",
     "hex", {"dk": col("dk"), "k": col("k"), "s": col("s"), "t": col("t"),
             "dc": col("dk_c"), "c": col("c")}),
    # -- countersunk
    ("ISO10642", "iso-10642", "ISO 10642", "Countersunk Socket Screw",
     S + "/Countersunk", "countersunk", "hex",
     {"dk": col("dk_theo"), "k": csk_k(90), "s": col("s_mean"),
      "t": col("t"), "angle": 90}),
    ("ISO2009", "iso-2009", "ISO 2009", "Slotted Countersunk Screw",
     S + "/Countersunk", "countersunk", "slot",
     {"dk": col("dk_theo"), "k": csk_k(90), "s": col("n_min"),
      "t": col("t_mean"), "angle": 90}),
    ("ISO2010", "iso-2010", "ISO 2010", "Slotted Raised Countersunk Screw",
     S + "/Countersunk", "countersunk", "slot",
     {"dk": col("dk_theo"), "k": csk_k(90), "s": col("n_min"),
      "t": col("t_mean"), "angle": 90}),
    ("ISO7046", "iso-7046", "ISO 7046", "Cross Recessed Countersunk Screw",
     S + "/Countersunk", "countersunk", "cross",
     {"dk": col("dk_theo"), "k": csk_k(90), "angle": 90, **CROSS},
     None, "ISO7046extra"),
    ("ISO7047", "iso-7047", "ISO 7047",
     "Cross Recessed Raised Countersunk Screw", S + "/Countersunk",
     "countersunk", "cross",
     {"dk": col("dk_theo"), "k": csk_k(90), "angle": 90,
      "s": lambda r, d: num(r["dk_theo"]) * 0.45,
      "t": lambda r, d: num(r["dk_theo"]) * 0.2}),
    ("ISO14581", "iso-14581", "ISO 14581",
     "Hexalobular Countersunk Screw", S + "/Countersunk", "countersunk",
     "torx", {"dk": col("dk_theo"), "k": csk_k(90), "s": col("A2"),
              "t": col("t_mean"), "angle": 90}),
    ("ISO14582", "iso-14582", "ISO 14582",
     "Hexalobular Countersunk Screw, high head", S + "/Countersunk",
     "countersunk", "torx",
     {"dk": col("dk_theo"), "k": col("csh_height"), "s": col("A2"),
      "t": col("t_mean"), "angle": 90}),
    ("ISO14584", "iso-14584", "ISO 14584",
     "Hexalobular Raised Countersunk Screw", S + "/Countersunk",
     "countersunk", "torx",
     {"dk": col("dk_theo"), "k": csk_k(90), "s": col("A"),
      "t": col("t_mean"), "angle": 90}),
    ("ASMEB18.3.2", "asme-b18-3-countersunk", "ASME B18.3",
     "Countersunk Socket Screw, UNC", S + "/Countersunk", "countersunk",
     "hex", {"dk": col("dk_theo"), "k": csk_k(82), "s": col("s"),
             "t": col("t"), "angle": 82}),
    ("ASMEB18.6.3.1A", "asme-b18-6-3-flat-slot", "ASME B18.6.3",
     "Slotted Flat Countersunk Screw, UNC", S + "/Countersunk",
     "countersunk", "slot",
     {"dk": col("dk_theo"), "k": csk_k(82), "s": col("n_min"),
      "t": col("t_mean"), "angle": 82}),
    # -- cheese and fillister heads
    ("ISO1207", "iso-1207", "ISO 1207", "Slotted Cheese Head Screw",
     S + "/Cheese Head", "cheese", "slot",
     {"dk": col("dk"), "k": col("k"), "s": col("n_min"),
      "t": col("t_min")}),
    ("DIN84", "din-84", "DIN 84", "Slotted Cheese Head Screw",
     S + "/Cheese Head", "cheese", "slot",
     {"dk": col("dk"), "k": col("k"), "s": col("n_min"),
      "t": col("t_min")}),
    ("ISO14580", "iso-14580", "ISO 14580",
     "Hexalobular Cheese Head Screw", S + "/Cheese Head", "cheese", "torx",
     {"dk": col("dk"), "k": col("k"), "s": col("A"), "t": col("t_mean")},
     None, "ISO14580extra"),
    ("ISO7048", "iso-7048", "ISO 7048", "Cross Recessed Cheese Head Screw",
     S + "/Cheese Head", "cheese", "cross",
     {"dk": col("dk"), "k": col("k"), **CROSS}),
    ("ASMEB18.6.3.10A", "asme-b18-6-3-fillister", "ASME B18.6.3",
     "Slotted Fillister Head Screw, UNC", S + "/Cheese Head", "cheese",
     "slot", {"dk": col("A"), "k": col("O"), "s": col("J"),
              "t": col("T")}),
    # -- pan heads
    ("ISO1580", "iso-1580", "ISO 1580", "Slotted Pan Head Screw",
     S + "/Pan Head", "pan", "slot",
     {"dk": col("dk_max"), "k": col("k"), "s": col("n_min"),
      "t": col("t_mean")}),
    ("ISO7045", "iso-7045", "ISO 7045", "Cross Recessed Pan Head Screw",
     S + "/Pan Head", "pan", "cross",
     {"dk": col("dk_max"), "k": col("k"), **CROSS}),
    ("ISO14583", "iso-14583", "ISO 14583", "Hexalobular Pan Head Screw",
     S + "/Pan Head", "pan", "torx",
     {"dk": col("dk"), "k": col("k"), "s": col("A_ref"), "t": col("t")}),
    ("DIN967", "din-967", "DIN 967",
     "Cross Recessed Pan Head Screw with collar", S + "/Pan Head", "pan",
     "cross", {"dk": col("dk"), "k": col("k"), **CROSS}),
    ("ASMEB18.6.3.9A", "asme-b18-6-3-pan-slot", "ASME B18.6.3",
     "Slotted Pan Head Screw, UNC", S + "/Pan Head", "pan", "slot",
     {"dk": col("A"), "k": col("H"), "s": col("J"), "t": col("T")}),
    ("ASMEB18.6.3.9B", "asme-b18-6-3-pan-cross", "ASME B18.6.3",
     "Cross Recessed Pan Head Screw, UNC", S + "/Pan Head", "pan", "cross",
     {"dk": col("A"), "k": col("H"), "s": col("M"),
      "t": lambda r, d: num(r["M"]) * 0.45}),
    ("ISO7049-C", "iso-7049", "ISO 7049",
     "Cross Recessed Pan Head Tapping Screw", S + "/Tapping", "pan",
     "cross", {"dk": col("dk_max"), "k": col("k_max"), "s": col("m_ref"),
               "t": lambda r, d: num(r["m_ref"]) * 0.45}),
    # -- round and truss heads
    ("ASMEB18.6.3.16A", "asme-b18-6-3-round", "ASME B18.6.3",
     "Slotted Round Head Screw, UNC", S + "/Round Head", "dome", "slot",
     {"dk": col("A"), "k": col("H"), "s": col("J"), "t": col("T")}),
    ("ASMEB18.6.3.12A", "asme-b18-6-3-truss", "ASME B18.6.3",
     "Slotted Truss Head Screw, UNC", S + "/Round Head", "dome", "slot",
     {"dk": col("A"), "k": col("H"), "s": col("J"), "t": col("T")}),
    ("DIN96", "din-96", "DIN 96", "Slotted Round Head Wood Screw",
     S + "/Wood", "dome", "slot",
     {"dk": col("dk"), "k": col("k"), "s": col("n"), "t": col("t")}),
    ("DIN7996", "din-7996", "DIN 7996",
     "Cross Recessed Round Head Wood Screw", S + "/Wood", "dome", "cross",
     {"dk": col("dk"), "k": col("k"), "s": col("m"),
      "t": lambda r, d: num(r["m"]) * 0.45}),
    # -- set screws: L is the whole screw
    ("ISO4026", "iso-4026", "ISO 4026", "Socket Set Screw, flat point",
     S + "/Set Screws", "set_screw", "hex",
     {"s": col("s"), "t": col("t"), "point": 0}),
    ("ISO4027", "iso-4027", "ISO 4027", "Socket Set Screw, cone point",
     S + "/Set Screws", "set_screw", "hex",
     {"s": col("s"), "t": col("t"), "point": 1}),
    ("ISO4028", "iso-4028", "ISO 4028", "Socket Set Screw, dog point",
     S + "/Set Screws", "set_screw", "hex",
     {"s": col("s_nom"), "t": col("te_min"), "point": 2}),
    ("ISO4029", "iso-4029", "ISO 4029", "Socket Set Screw, cup point",
     S + "/Set Screws", "set_screw", "hex",
     {"s": col("s"), "t": col("t"), "point": 3}),
    ("ASMEB18.3.5A", "asme-b18-3-set-flat", "ASME B18.3",
     "Socket Set Screw, flat point, UNC", S + "/Set Screws", "set_screw",
     "hex", {"s": col("s"), "t": col("t"), "point": 0}),
    ("ASMEB18.3.5B", "asme-b18-3-set-cone", "ASME B18.3",
     "Socket Set Screw, cone point, UNC", S + "/Set Screws", "set_screw",
     "hex", {"s": col("s"), "t": col("t"), "point": 1}),
    ("ASMEB18.3.5D", "asme-b18-3-set-cup", "ASME B18.3",
     "Socket Set Screw, cup point, UNC", S + "/Set Screws", "set_screw",
     "hex", {"s": col("s"), "t": col("t"), "point": 3}),
    ("ISO4766", "iso-4766", "ISO 4766", "Slotted Set Screw, flat point",
     S + "/Set Screws", "set_screw", "slot",
     {"s": col("n_nom"), "t": col("t_max"), "point": 0}),
    ("ISO7434", "iso-7434", "ISO 7434", "Slotted Set Screw, cone point",
     S + "/Set Screws", "set_screw", "slot",
     {"s": col("n_nom"), "t": col("t_max"), "point": 1}),
    ("ISO7436", "iso-7436", "ISO 7436", "Slotted Set Screw, cup point",
     S + "/Set Screws", "set_screw", "slot",
     {"s": col("n_nom"), "t": col("t_max"), "point": 3}),
    # -- hex nuts
    ("ISO4032", "iso-4032", "ISO 4032", "Hex Nut, style 1", N + "/Hex",
     "nut", "", {"s": col("s_nom"), "m": col("m")}),
    ("ISO4033", "iso-4033", "ISO 4033", "Hex Nut, style 2", N + "/Hex",
     "nut", "", {"s": col("s_nom"), "m": col("m")}),
    ("ISO4034", "iso-4034", "ISO 4034", "Hex Nut, grade C", N + "/Hex",
     "nut", "", {"s": col("s_nom"), "m": col("m_nom")}),
    ("ISO4035", "iso-4035", "ISO 4035", "Hex Thin Nut", N + "/Hex", "nut",
     "", {"s": col("s_nom"), "m": col("m")}),
    ("ISO8673", "iso-8673", "ISO 8673", "Hex Nut, fine thread", N + "/Hex",
     "nut", "", {"s": col("s_nom"), "m": col("m")}),
    ("ISO8674", "iso-8674", "ISO 8674", "Hex High Nut, fine thread",
     N + "/Hex", "nut", "", {"s": col("s_nom"), "m": col("m")}),
    ("ISO8675", "iso-8675", "ISO 8675", "Hex Thin Nut, fine thread",
     N + "/Hex", "nut", "", {"s": col("s_nom"), "m": col("m")}),
    ("DIN934", "din-934", "DIN 934", "Hex Nut", N + "/Hex", "nut", "",
     {"s": col("s_nom"), "m": col("m")}),
    ("DIN6330", "din-6330", "DIN 6330", "Hex Nut, 1.5 d high", N + "/Hex",
     "nut", "", {"s": col("s"), "m": col("m")}),
    ("DIN6334", "din-6334", "DIN 6334", "Long Hex Coupling Nut",
     N + "/Hex", "nut", "", {"s": col("s"), "m": col("m")}),
    ("DIN935", "din-935", "DIN 935", "Castle Nut", N + "/Hex", "nut", "",
     {"s": col("s"), "m": col("m")}),
    ("DIN929", "din-929", "DIN 929", "Hex Weld Nut", N + "/Weld", "nut", "",
     {"s": col("s"), "m": col("m")}),
    ("ASMEB18.2.2.4A", "asme-b18-2-2-hex", "ASME B18.2.2",
     "Hex Nut, UNC", N + "/Hex", "nut", "",
     {"s": col("s"), "m": col("m_a")}),
    ("ASMEB18.2.2.4B", "asme-b18-2-2-thin", "ASME B18.2.2",
     "Hex Jam Nut, UNC", N + "/Hex", "nut", "",
     {"s": col("s"), "m": col("m_b")}),
    ("ASMEB18.2.2.1A", "asme-b18-2-2-machine", "ASME B18.2.2",
     "Hex Machine Screw Nut, UNC", N + "/Hex", "nut", "",
     {"s": col("s"), "m": col("m")}),
    ("ASMEB18.2.2.13", "asme-b18-2-2-coupling", "ASME B18.2.2",
     "Hex Coupling Nut, UNC", N + "/Hex", "nut", "",
     {"s": inch("F"), "m": inch("H")}),
    # -- lock nuts
    ("ISO7040", "iso-7040", "ISO 7040", "Nylon Insert Lock Nut",
     N + "/Lock", "lock_nut", "",
     {"s": col("s_max"), "m": col("m_w_min"), "h": col("h_max"),
      "dw": col("d_w_min")}),
    ("ISO10511", "iso-10511", "ISO 10511", "Nylon Insert Lock Nut, thin",
     N + "/Lock", "lock_nut", "",
     {"s": col("s_max"), "m": col("m_w_min"), "h": col("h_max"),
      "dw": col("d_w_min")}),
    ("ISO10512", "iso-10512", "ISO 10512",
     "Nylon Insert Lock Nut, fine thread", N + "/Lock", "lock_nut", "",
     {"s": col("s_max"), "m": col("m_w_min"), "h": col("h_max"),
      "dw": col("d_w_min")}),
    ("DIN985", "din-985", "DIN 985", "Nylon Insert Lock Nut", N + "/Lock",
     "lock_nut", "", {"s": col("s_nom"), "m": col("m"), "h": col("h"),
                      "dw": col("dw")}),
    ("ISO7719", "iso-7719", "ISO 7719", "All Metal Lock Nut", N + "/Lock",
     "nut", "", {"s": col("s_max"), "m": col("h_max")}),
    ("ISO10513", "iso-10513", "ISO 10513",
     "All Metal Lock Nut, fine thread", N + "/Lock", "nut", "",
     {"s": col("s_max"), "m": col("h_max")}),
    # -- flange nuts
    ("EN1661", "en-1661", "EN 1661", "Hex Flange Nut", N + "/Flange",
     "nut", "", {"s": col("s"), "m": col("m"), "dc": col("dc"),
                 "c": col("c")}),
    ("ISO4161", "iso-4161", "ISO 4161", "Hex Flange Nut", N + "/Flange",
     "nut", "", {"s": col("s_max"), "m": col("m_max"),
                 "dc": col("d_c_max"), "c": col("c_min")}),
    ("ISO10663", "iso-10663", "ISO 10663", "Hex Flange Nut, fine thread",
     N + "/Flange", "nut", "", {"s": col("s_max"), "m": col("m_max"),
                                "dc": col("d_c_max"), "c": col("c_min")}),
    ("ISO7044", "iso-7044", "ISO 7044", "All Metal Flange Lock Nut",
     N + "/Flange", "nut", "", {"s": col("s_max"), "m": col("h_max"),
                                "dc": col("d_c_max"), "c": col("c")}),
    ("ISO7043", "iso-7043", "ISO 7043", "Nylon Insert Flange Lock Nut",
     N + "/Flange", "lock_nut", "",
     {"s": col("s_max"), "m": col("m_w_min"), "h": col("h_max"),
      "dw": col("d_w_min"), "dc": col("d_c_max"), "c": col("c_min")}),
    # -- cap and square nuts
    ("DIN1587", "din-1587", "DIN 1587", "Domed Cap Nut", N + "/Cap",
     "cap_nut", "", {"s": col("s"), "m": col("m"), "h": col("h"),
                     "dk": col("dk")}),
    ("DIN557", "din-557", "DIN 557", "Square Nut", N + "/Square",
     "square_nut", "", {"s": col("s"), "m": col("m")}),
    ("DIN562", "din-562", "DIN 562", "Square Nut, thin", N + "/Square",
     "square_nut", "", {"s": col("s"), "m": col("m")}),
    ("DIN928", "din-928", "DIN 928", "Square Weld Nut", N + "/Weld",
     "square_nut", "", {"s": col("s"), "m": col("m")}),
    ("ASMEB18.2.2.2", "asme-b18-2-2-square", "ASME B18.2.2",
     "Square Nut, UNC", N + "/Square", "square_nut", "",
     {"s": inch("F"), "m": inch("H")}),
    # -- washers
    ("ISO7089", "iso-7089", "ISO 7089", "Plain Washer", W, "washer", "",
     {"d1": col("d1_min"), "d2": col("d2_max"), "h": col("h")}),
    ("ISO7090", "iso-7090", "ISO 7090", "Plain Washer, chamfered", W,
     "washer", "", {"d1": col("d1_min"), "d2": col("d2_max"),
                    "h": col("h")}),
    ("ISO7091", "iso-7091", "ISO 7091", "Plain Washer, grade C", W,
     "washer", "", {"d1": col("d1_min"), "d2": col("d2_max"),
                    "h": col("h")}),
    ("ISO7092", "iso-7092", "ISO 7092", "Plain Washer, small series", W,
     "washer", "", {"d1": col("d1_min"), "d2": col("d2_max"),
                    "h": col("h")}),
    ("ISO7093-1", "iso-7093-1", "ISO 7093-1", "Plain Washer, large series",
     W, "washer", "", {"d1": col("d1_min"), "d2": col("d2_max"),
                       "h": col("h")}),
    ("ISO7094", "iso-7094", "ISO 7094", "Plain Washer, extra large series",
     W, "washer", "", {"d1": col("d1_min"), "d2": col("d2_max"),
                       "h": col("h")}),
    ("ISO8738", "iso-8738", "ISO 8738", "Plain Washer for clevis pins", W,
     "washer", "", {"d1": col("d1_min"), "d2": col("d2_max"),
                    "h": col("h")}),
    ("DIN6340", "din-6340", "DIN 6340", "Washer for clamping devices", W,
     "washer", "", {"d1": col("d1_min"), "d2": col("d2"), "h": col("h")}),
    ("ASMEB18.21.1.12A", "asme-b18-21-1-narrow", "ASME B18.21.1",
     "Plain Washer, narrow", W, "washer", "",
     {"d1": col("d1"), "d2": col("d2_max"), "h": col("h_max")}),
    ("ASMEB18.21.1.12B", "asme-b18-21-1-regular", "ASME B18.21.1",
     "Plain Washer, regular", W, "washer", "",
     {"d1": col("d1"), "d2": col("d2_max"), "h": col("h_max")}),
    ("ASMEB18.21.1.12C", "asme-b18-21-1-wide", "ASME B18.21.1",
     "Plain Washer, wide", W, "washer", "",
     {"d1": col("d1"), "d2": col("d2_max"), "h": col("h_max")}),
    # -- pins: L is the pin
    ("ISO2338", "iso-2338", "ISO 2338", "Parallel Pin", P + "/Parallel",
     "pin", "", {"d": col("d"), "c": col("c")}),
    ("ISO8734", "iso-8734", "ISO 8734", "Dowel Pin, hardened",
     P + "/Parallel", "pin", "", {"d": col("d"), "c": col("c")}),
    ("ISO8733", "iso-8733", "ISO 8733",
     "Parallel Pin with internal thread", P + "/Parallel", "pin", "",
     {"d": col("d_1"), "c": col("c_1")}),
    ("ISO8735", "iso-8735", "ISO 8735",
     "Parallel Pin with internal thread, hardened", P + "/Parallel", "pin",
     "", {"d": col("d_1"), "c": col("c")}),
    ("ISO8740", "iso-8740", "ISO 8740", "Grooved Pin, full length",
     P + "/Grooved", "pin", "", {"d": col("d_1"), "c": col("c_1")}),
    ("ISO8741", "iso-8741", "ISO 8741", "Grooved Pin, reverse taper",
     P + "/Grooved", "pin", "", {"d": col("d_1"), "c": 0}),
    ("ISO8744", "iso-8744", "ISO 8744", "Grooved Pin, taper",
     P + "/Grooved", "pin", "", {"d": col("d_1"), "c": 0}),
    ("ISO2339", "iso-2339", "ISO 2339", "Taper Pin", P + "/Taper",
     "taper_pin", "", {"d": col("d")}),
    ("ISO8736", "iso-8736", "ISO 8736", "Taper Pin with internal thread",
     P + "/Taper", "taper_pin", "", {"d": col("d_1")}),
    ("ISO8752", "iso-8752", "ISO 8752", "Slotted Spring Pin, heavy duty",
     P + "/Spring", "spring_pin", "", {"d": col("d_1"), "s": col("s")}),
    ("ISO13337", "iso-13337", "ISO 13337", "Slotted Spring Pin, light duty",
     P + "/Spring", "spring_pin", "", {"d": col("d_1"), "s": col("s")}),
    ("ISO8748", "iso-8748", "ISO 8748", "Coiled Spring Pin, heavy duty",
     P + "/Spring", "spring_pin", "", {"d": col("d_1"), "s": col("s")}),
    ("ISO8750", "iso-8750", "ISO 8750", "Coiled Spring Pin, standard duty",
     P + "/Spring", "spring_pin", "", {"d": col("d_1"), "s": col("s")}),
    ("ISO2340A", "iso-2340", "ISO 2340", "Clevis Pin without head",
     P + "/Clevis", "pin", "", {"d": col("d_1"), "c": col("c")}),
    ("ISO2341A", "iso-2341", "ISO 2341", "Clevis Pin with head",
     P + "/Clevis", "headed_pin", "",
     {"d": col("d"), "dk": col("d_k"), "k": col("k"), "c": col("c")}),
    ("ISO8746", "iso-8746", "ISO 8746", "Grooved Pin with round head",
     P + "/Grooved", "headed_pin", "",
     {"d": col("d_1_max"), "dk": col("d_k_max"), "k": col("k_max"),
      "c": 0}),
    # -- retaining rings: d is the shaft or the bore
    ("DIN471", "din-471", "DIN 471", "External Retaining Ring", R,
     "ring_external", "", {"d3": col("d_3"), "a": col("a_Max"),
                           "b": col("b"), "s": col("S")}),
    ("DIN472", "din-472", "DIN 472", "Internal Retaining Ring", R,
     "ring_internal", "", {"d3": col("d_3"), "a": col("a_Max"),
                           "b": col("b"), "s": col("S")}),
]

# a type's sizes come from its def table; some keep the head elsewhere
LENGTHS_BOLT = [3, 4, 5, 6, 8, 10, 12, 14, 16, 18, 20, 22, 25, 28, 30, 32,
                35, 38, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100, 110,
                120, 130, 140, 150, 160, 180, 200, 220, 240, 260, 280, 300]
LENGTHS_ROD = [100, 250, 500, 1000, 2000, 3000]
NEEDS_LENGTH = {"hex_bolt", "square_bolt", "socket_head", "shoulder",
                "dome", "countersunk", "cheese", "pan", "set_screw", "pin",
                "taper_pin", "spring_pin", "headed_pin", "rod"}


def fastener_family(tables, entry):
    ftype, fid, standard, name, category, kind, drive, cols = entry[:8]
    head = entry[8] if len(entry) > 8 else None
    extra = entry[9] if len(entry) > 9 else None
    dia_list = tables.get("DiaList", ([], {}))[1]
    key = ftype + "def"
    if key not in tables:
        raise KeyError("FreeCAD has no table " + key)
    header, rows = tables[key]
    ranges = tables.get(ftype + "range", tables.get(ftype + "Range"))
    lengths_table = tables.get(ftype + "length")
    out_rows, ranges_out, skipped = [], {}, []
    for size, row in rows.items():
        d = diameter(size, dia_list)
        if d is None:
            skipped.append(size)
            continue
        r = dict(zip(header, row))
        if head and head in tables:
            hh, hr = tables[head]
            if size in hr:
                r = {**dict(zip(hh, hr[size])), **r}
        if extra and extra in tables:
            eh, er = tables[extra]
            if size in er:
                r.update(dict(zip(eh, er[size])))
        try:
            values = {"d": d}
            for c, how in cols.items():
                values[c] = float(how(r, d) if callable(how) else how)
        except (KeyError, TypeError, ValueError):
            skipped.append(size)
            continue
        if any(v != v or v < 0 for v in values.values()):
            skipped.append(size)
            continue
        out_rows.append([label(size)] + [values["d"]]
                        + [values[c] for c in cols if c != "d"])
        if ranges and size in ranges[1]:
            lo, hi = (num(x) for x in ranges[1][size][:2])
            if lo is not None and hi is not None:
                ranges_out[label(size)] = (lo, hi)
    columns = ["d"] + [c for c in cols if c != "d"]
    lengths = []
    if kind in NEEDS_LENGTH:
        if lengths_table:
            for nominal in lengths_table[1]:
                value = diameter(nominal, dia_list) if "in" in nominal \
                    else num(nominal)
                if value:
                    lengths.append(round(value, 3))
        lengths = sorted(set(lengths)) or list(LENGTHS_BOLT)
    source = "%s, FsData table %s" % (FSWB, key)
    return dict(id=fid, name=name, standard=standard, category=category,
                kind=kind, drive=drive, columns=columns, rows=out_rows,
                lengths=lengths, ranges=ranges_out, source=source,
                licence=FSWB_LICENCE), skipped


def rod_family(tables):
    header, rows = tables["ThreadedRoddef"]
    out = []
    for size in rows:
        d = diameter(size, {})
        if d:
            out.append([label(size), d])
    return dict(id="din-976-1", name="Threaded Rod", standard="DIN 976-1",
                category="Fasteners/Threaded Rods", kind="rod", drive="",
                columns=["d"], rows=out, lengths=LENGTHS_ROD, ranges={},
                source="%s, FsData table ThreadedRoddef" % FSWB,
                licence=FSWB_LICENCE)


def bearing_families(folder: str):
    """Deep groove ball bearings: the boundary dimensions only."""
    out = []
    for stem, fid, name in (
            ("single_row_deep_groove_ball_bearing", "iso-15-deep-groove",
             "Deep Groove Ball Bearing, open"),
            ("single_row_capped_deep_groove_ball_bearing",
             "iso-15-deep-groove-2z", "Deep Groove Ball Bearing, shielded")):
        path = glob.glob(os.path.join(folder, "**", stem + "_parameters.csv"),
                         recursive=True)[0]
        rows = []
        with open(path, newline="", encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                vals = [num(r.get("SKT:" + c)) for c in ("d", "D", "B")]
                design = (r.get("SKT:Designation") or "").strip()
                if None in vals or not design:
                    continue
                rows.append([design] + vals)
        rows.sort(key=lambda r: (r[1], r[2]))
        out.append(dict(id=fid, name=name, standard="ISO 15",
                        category="Bearings/Ball Bearings", kind="bearing",
                        drive="", columns=["d", "D", "B"], rows=rows,
                        lengths=[], ranges={},
                        source="%s, %s_parameters.csv, d D B and "
                               "designation only" % (CQW, stem),
                        licence=CQW_LICENCE))
    return out


# ---------------------------------------------------------- the profiles
#
# FreeCAD gives the overall sizes and the thicknesses; the root radius is
# the standard's own rule or table, added here.  H rows are width,
# height, web, flange; U rows height, width, web, flange.

# EN 10365 root radius by the height in the designation
R_IPE = {80: 5, 100: 7, 120: 7, 140: 7, 160: 9, 180: 9, 200: 12, 220: 12,
         240: 15, 270: 15, 300: 15, 330: 18, 360: 18, 400: 21, 450: 21,
         500: 21, 550: 24, 600: 24}
R_HE = {100: 12, 120: 12, 140: 12, 160: 15, 180: 15, 200: 18, 220: 18,
        240: 21, 260: 24, 280: 24, 300: 27, 320: 27, 340: 27, 360: 27,
        400: 27, 450: 27, 500: 27, 550: 27, 600: 27, 650: 27, 700: 27,
        800: 30, 900: 30, 1000: 30}
R_UPE = {80: 8, 100: 9, 120: 9, 140: 10, 160: 10, 180: 11, 200: 12,
         220: 12, 240: 13, 270: 14, 300: 15, 330: 16, 360: 18, 400: 18}
# BS 4-1 root radius by serial size
R_BS4 = {"127x76": 7.6, "152x89": 7.6, "178x102": 7.6, "203x102": 7.6,
         "203x133": 7.6, "254x102": 7.6, "254x146": 7.6, "305x102": 7.6,
         "305x127": 8.9, "305x165": 8.9, "356x127": 10.2, "356x171": 10.2,
         "406x140": 10.2, "406x178": 10.2, "457x152": 10.2,
         "457x191": 10.2, "533x210": 12.7, "533x312": 12.7,
         "610x229": 12.7, "610x305": 16.5, "686x254": 15.2,
         "762x267": 16.5, "838x292": 17.8, "914x305": 19.1,
         "914x419": 24.1, "1016x305": 30.0,
         "152x152": 7.6, "203x203": 10.2, "254x254": 12.7,
         "305x305": 15.2, "356x368": 15.2, "356x406": 15.2}

# DIN 1026-1 UPN: h, b, tw, tf; r1 is tf, r2 half of it, 8 % taper
UPN = [(50, 38, 5, 7), (65, 42, 5.5, 7.5), (80, 45, 6, 8),
       (100, 50, 6, 8.5), (120, 55, 7, 9), (140, 60, 7, 10),
       (160, 65, 7.5, 10.5), (180, 70, 8, 11), (200, 75, 8.5, 11.5),
       (220, 80, 9, 12.5), (240, 85, 9.5, 13), (260, 90, 10, 14),
       (280, 95, 10, 15), (300, 100, 10, 16), (320, 100, 14, 17.5),
       (350, 100, 14, 16), (380, 102, 13.5, 16), (400, 110, 14, 18)]

PROFILE_GROUPS = {
    "HEA": ("en-10365-hea", "HEA Beams", "EN 10365", "I and H Beams",
            "i_beam", "H", R_HE, 0),
    "HEB": ("en-10365-heb", "HEB Beams", "EN 10365", "I and H Beams",
            "i_beam", "H", R_HE, 0),
    "HEM": ("en-10365-hem", "HEM Beams", "EN 10365", "I and H Beams",
            "i_beam", "H", R_HE, 0),
    "IPE": ("en-10365-ipe", "IPE Beams", "EN 10365", "I and H Beams",
            "i_beam", "H", R_IPE, 0),
    "INP": ("en-10365-ipn", "IPN Beams, tapered flanges", "EN 10365",
            "I and H Beams", "i_beam", "H", None, 14),
    "UB": ("bs-4-1-ub", "Universal Beams", "BS 4-1", "I and H Beams",
           "i_beam", "H", None, 0),
    "UC": ("bs-4-1-uc", "Universal Columns", "BS 4-1", "I and H Beams",
           "i_beam", "H", None, 0),
    "American Wide Flange": ("astm-a6-w", "W Shapes", "ASTM A6",
                             "I and H Beams", "i_beam", "H", None, 0),
    "IS Beam": ("is-808-beam", "Beams", "IS 808", "I and H Beams",
                "i_beam", "H", None, 0),
    "UPE": ("en-10365-upe", "UPE Channels, parallel flanges", "EN 10365",
            "Channels", "channel", "U", R_UPE, 0),
    "IS Channel": ("is-808-channel", "Channels", "IS 808", "Channels",
                   "channel", "U", None, 0),
    "Aluminium C Channel": ("alu-c-channel", "Aluminium C Channels",
                            "Aluminium", "Channels", "channel", "U",
                            None, 0),
    "IS Angle": ("is-808-angle", "Angles", "IS 808", "Angles",
                 "unequal_angle", "L", None, 0),
    "IS Tee": ("is-808-tee", "T Sections", "IS 808", "T Sections", "tee",
               "T", None, 0),
    "CHS": ("en-10219-chs", "Circular Hollow Sections", "EN 10219-2",
            "Round Tubes", "round_tube", "C", None, 0),
    "RHS": ("en-10219-rhs", "Rectangular Hollow Sections", "EN 10219-2",
            "Rectangular Tubes", "rect_tube", "RH", None, 0),
    "IS RHS": ("is-4923-rhs", "Rectangular Hollow Sections", "IS 4923",
               "Rectangular Tubes", "rect_tube", "RH", None, 0),
    "IS SHS": ("is-4923-shs", "Square Hollow Sections", "IS 4923",
               "Rectangular Tubes", "rect_tube", "RH", None, 0),
}


def _height(name: str) -> Optional[int]:
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else None


def profile_families(path: str):
    groups: Dict[str, List] = {}
    with open(path, newline="", encoding="utf-8") as fp:
        for line in csv.reader(fp, skipinitialspace=True):
            if not line or line[0].startswith("#") or len(line) < 4:
                continue
            groups.setdefault(line[0].strip(), []).append(
                [c.strip() for c in line[1:]])
    out = []
    for group, (fid, name, standard, category, kind, shape, radii,
                slope) in PROFILE_GROUPS.items():
        rows, seen = [], set()
        for line in groups.get(group, []):
            size, cls = line[0], line[1]
            v = [num(x) for x in line[2:]]
            if cls != shape or None in v or size in seen:
                continue
            seen.add(size)
            if shape == "H":
                b, h, tw, tf = v[:4]
                r = (radii or {}).get(_height(size), 0)
                if group in ("UB", "UC"):
                    serial = re.match(r"^U[BC](\d+x\d+)", size)
                    r = R_BS4.get(serial.group(1), 0) if serial else 0
                r2 = 0.0
                if slope:          # DIN 1025-1: r1 is the web, r2 0.6 of it
                    r, r2 = tw, round(0.6 * tw, 2)
                label_ = re.sub(r"^([A-Z]+)(\d)", r"\1 \2", size)
                label_ = re.sub(r"^INP ", "IPN ", label_)
                rows.append([label_, h, b, tw, tf, r, slope, r2])
            elif shape == "U":
                h, b, tw, tf = v[:4]
                r = (radii or {}).get(_height(size), 0)
                label_ = re.sub(r"^([A-Z]+)(\d)", r"\1 \2", size)
                rows.append([label_, h, b, tw, tf, r, 0, 0])
            elif shape == "L":
                a, b, t = v[:3]
                rows.append([size, a, b, t, 0, 0])
            elif shape == "T":
                b, h, tw, tf = v[:4]
                rows.append([size, h, b, tw, tf, 0, 0])
            elif shape == "C":
                d, t = v[:2]
                rows.append([size, d, t])
            elif shape == "RH":
                h, b, t = v[:3]
                rows.append([size, h, b, t, round(2 * t, 2)])
        if not rows:
            continue
        columns = {"i_beam": ["h", "b", "tw", "tf", "r", "slope", "r2"],
                   "channel": ["h", "b", "tw", "tf", "r", "slope", "r2"],
                   "unequal_angle": ["a", "b", "t", "r1", "r2"],
                   "tee": ["h", "b", "tw", "tf", "r", "r2"],
                   "round_tube": ["d", "t"],
                   "rect_tube": ["h", "b", "t", "ro"]}[kind]
        note = ("; root radii from %s" % standard) if radii or slope else ""
        out.append(dict(id=fid, name=name, standard=standard,
                        category=category, kind=kind, drive="",
                        columns=columns, rows=rows, lengths=[], ranges={},
                        source="%s, group %s%s" % (BIM, group, note),
                        licence=BIM_LICENCE))
    # DIN 1026-1 UPN, typed in from the standard's dimensions
    out.append(dict(
        id="din-1026-1-upn", name="UPN Channels, tapered flanges",
        standard="DIN 1026-1", category="Channels", kind="channel",
        drive="", columns=["h", "b", "tw", "tf", "r", "slope", "r2"],
        rows=[["UPN %d" % h, h, b, tw, tf, tf, 8, round(tf / 2, 2)]
              for h, b, tw, tf in UPN],
        lengths=[], ranges={}, source="DIN 1026-1 dimensions",
        licence="CC0-1.0"))
    # bars: the sizes EN 10058 and EN 10060 list, any mill rolls them
    flats = [(b, t) for b in (10, 12, 15, 16, 20, 25, 30, 35, 40, 45, 50,
                              60, 70, 80, 90, 100, 110, 120, 140, 150, 160,
                              180, 200)
             for t in (3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30)
             if t < b and t <= b / 2 + 5]
    out.append(dict(id="en-10058-flat", name="Flat Bars", standard="EN 10058",
                    category="Bars", kind="flat_bar", drive="",
                    columns=["b", "t", "r"],
                    rows=[["FL %dx%d" % (b, t), b, t, 0] for b, t in flats],
                    lengths=[], ranges={}, source="EN 10058 size range",
                    licence="CC0-1.0"))
    rounds = [6, 8, 10, 12, 14, 16, 18, 20, 22, 25, 28, 30, 32, 35, 36, 40,
              45, 50, 55, 60, 63, 65, 70, 75, 80, 90, 100, 110, 120, 130,
              140, 150, 160, 180, 200]
    out.append(dict(id="en-10060-round", name="Round Bars",
                    standard="EN 10060", category="Bars", kind="round_bar",
                    drive="", columns=["d"],
                    rows=[["RD %d" % d, d] for d in rounds], lengths=[],
                    ranges={}, source="EN 10060 size range",
                    licence="CC0-1.0"))
    out += pipe_families()
    return out


def bend_radius(d):
    """A bend radius to start from: three and a half diameters, to the
    whole millimetre, about what a lever bender gives; set per run."""
    return math.ceil(3.5 * d)


# copper tube for refrigeration and air conditioning, outside diameter
# and wall in mm.  EN 12735-1: the metric sizes stockists carry.
EN_12735_1 = [(6, 1), (8, 1), (10, 1), (12, 1), (15, 1), (16, 1), (18, 1),
              (22, 1), (28, 1), (28, 1.5), (35, 1.5), (42, 1.5), (54, 2),
              (64, 2), (76.1, 2), (88.9, 2.5), (108, 2.5)]
# ASTM B280 ACR tube, inch sizes: (name, OD in, wall in).  Annealed
# coils, and drawn straight lengths (their walls are Type L's).
B280_COILS = [("1/8", 0.125, 0.030), ("3/16", 0.1875, 0.030),
              ("1/4", 0.25, 0.030), ("5/16", 0.3125, 0.032),
              ("3/8", 0.375, 0.032), ("1/2", 0.5, 0.032),
              ("5/8", 0.625, 0.035), ("3/4", 0.75, 0.042),
              ("7/8", 0.875, 0.045), ("1-1/8", 1.125, 0.050),
              ("1-3/8", 1.375, 0.055), ("1-5/8", 1.625, 0.060)]
B280_DRAWN = [("3/8", 0.375, 0.030), ("1/2", 0.5, 0.035),
              ("5/8", 0.625, 0.040), ("3/4", 0.75, 0.042),
              ("7/8", 0.875, 0.045), ("1-1/8", 1.125, 0.050),
              ("1-3/8", 1.375, 0.055), ("1-5/8", 1.625, 0.060),
              ("2-1/8", 2.125, 0.070), ("2-5/8", 2.625, 0.080),
              ("3-1/8", 3.125, 0.090), ("3-5/8", 3.625, 0.100),
              ("4-1/8", 4.125, 0.110)]


# capillary solder fittings for copper tube, EN 1254-1: the depth a tube
# goes into a socket (L, the standard's minimum capillary length), and
# what the standard leaves to the maker, typical values: the fitting's
# wall s, an elbow's centre line radius R, a tee's centre to socket
# bottom zt and a coupling's stop zc either side of its middle
FITTING_DEPTHS = [(6, 5.8), (8, 6.8), (10, 7.8), (12, 8.6), (15, 10.6),
                  (16, 10.6), (18, 12.6), (22, 15.4), (28, 18.4), (35, 23.0),
                  (42, 27.4), (54, 32.4), (64, 32.4), (76.1, 33.5),
                  (88.9, 37.5), (108, 47.5)]


def fitting_families():
    rows = []
    for d, depth in FITTING_DEPTHS:
        wall = round(max(0.8, 0.04 * d + 0.5), 1)
        rows.append(["%g" % d, d, depth, wall, d, round(d / 2 + wall + 1, 1),
                     1.0])
    return [dict(id="en-1254-1-solder", name="Solder Fittings for Copper Tube",
                 standard="EN 1254-1", category="Piping/Fittings",
                 kind="socket", drive="", columns=["d", "L", "s", "R", "zt",
                                                   "zc"],
                 rows=rows, lengths=[], ranges={},
                 source="EN 1254-1 capillary depths L; s, R, zt and zc "
                        "typical of the makers' 90 degree elbows, tees and "
                        "couplings, check against yours",
                 licence="CC0-1.0")]


def pipe_families():
    def inch_rows(table):
        return [['%s in' % name, round(od * 25.4, 2), round(t * 25.4, 2),
                 bend_radius(od * 25.4)] for name, od, t in table]

    common = dict(category="Piping/Copper", kind="pipe", drive="",
                  columns=["d", "t", "r"], lengths=[], ranges={},
                  licence="CC0-1.0")
    return [
        dict(common, id="en-12735-1-copper",
             name="Copper Tube for Refrigeration", standard="EN 12735-1",
             rows=[["%gx%g" % (d, t), d, t, bend_radius(d)]
                   for d, t in EN_12735_1],
             source="EN 12735-1 dimensions, the sizes stockists carry; "
                    "r a bend radius to start from, 3.5 x d"),
        dict(common, id="astm-b280-coil", name="ACR Copper Tube, Coils",
             standard="ASTM B280", rows=inch_rows(B280_COILS),
             source="ASTM B280 dimensions, annealed coils; r a bend radius "
                    "to start from, 3.5 x d"),
        dict(common, id="astm-b280-drawn",
             name="ACR Copper Tube, Straight Lengths", standard="ASTM B280",
             rows=inch_rows(B280_DRAWN),
             source="ASTM B280 dimensions, drawn straight lengths; r a bend "
                    "radius to start from, 3.5 x d"),
    ]


# --------------------------------------------------------------- writing

def write(fam, folder):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, fam["id"] + ".csv")
    with open(path, "w", newline="\n", encoding="utf-8") as fp:
        fp.write("# InventCraft standard parts library\n")
        for key in ("id", "name", "standard", "category", "kind", "drive",
                    "source", "licence"):
            if fam.get(key):
                fp.write("# %s: %s\n" % (key, fam[key]))
        if fam["lengths"]:
            fp.write("# lengths: %s\n" % " ".join(
                "%g" % v for v in fam["lengths"]))
        writer = csv.writer(fp, lineterminator="\n")
        ranged = bool(fam["ranges"])
        writer.writerow(["size"] + fam["columns"]
                        + (["lmin", "lmax"] if ranged else []))
        for row in fam["rows"]:
            extra = []
            if ranged:
                lo, hi = fam["ranges"].get(str(row[0]), ("", ""))
                extra = ["%g" % lo if lo != "" else "",
                         "%g" % hi if hi != "" else ""]
            writer.writerow([row[0]] + ["%g" % round(float(v), 4)
                                        for v in row[1:]] + extra)
    return path


def main(argv):
    fswb, cqw, profiles = argv[1:4]
    tables = read_fswb(fswb)
    fasteners, report = [], []
    for entry in F:
        try:
            fam, skipped = fastener_family(tables, entry)
        except KeyError as exc:
            report.append("%s: left out, %s" % (entry[0], exc))
            continue
        if not fam["rows"]:
            report.append("%s: no sizes" % entry[0])
            continue
        if skipped:
            report.append("%s: skipped %s" % (entry[0], ", ".join(skipped)))
        fasteners.append(fam)
    fasteners.append(rod_family(tables))
    bearings = bearing_families(cqw)
    shapes = profile_families(profiles)
    for sub in ("fasteners", "bearings", "profiles", "fittings"):
        for old in glob.glob(os.path.join(OUT, sub, "*.csv")):
            os.remove(old)
    for fam in fasteners:
        write(fam, os.path.join(OUT, "fasteners"))
    for fam in bearings:
        write(fam, os.path.join(OUT, "bearings"))
    for fam in shapes:
        write(fam, os.path.join(OUT, "profiles"))
    for fam in fitting_families():
        write(fam, os.path.join(OUT, "fittings"))
    print("fasteners %d families, %d sizes" % (
        len(fasteners), sum(len(f["rows"]) for f in fasteners)))
    print("bearings %d families, %d sizes" % (
        len(bearings), sum(len(f["rows"]) for f in bearings)))
    print("profiles %d families, %d sizes" % (
        len(shapes), sum(len(f["rows"]) for f in shapes)))
    for line in report:
        print("  " + line)


if __name__ == "__main__":
    main(sys.argv)
