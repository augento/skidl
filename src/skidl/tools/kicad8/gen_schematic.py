# -*- coding: utf-8 -*-

# The MIT License (MIT) - Copyright (c) Dave Vandenbout.

"""
Functions for generating a KiCad 6+ EESCHEMA schematic.
"""

import datetime
import os.path
import re
import time
from collections import Counter, OrderedDict
from typing import List, Dict, Optional, Tuple

from skidl.scriptinfo import get_script_name
from skidl.geometry import BBox, Point, Tx, Vector
from skidl.schematics.net_terminal import NetTerminal
from skidl.utilities import export_to_all
from .constants import BLK_INT_PAD, BOX_LABEL_FONT_SIZE, GRID, PIN_LABEL_FONT_SIZE
from .bboxes import calc_symbol_bbox, calc_hier_label_bbox
from skidl.utilities import rmv_attr
from .core import (
    Wire, Junction, Symbol, Property, Position, PointList, Point as KiCadPoint,
    Stroke, StrokeType, Color, UniversallyUniqueIdentifier, Size, Font, TextEffects,
    Justify, Text, Label, GlobalLabel, HierarchicalLabel, SList, Project, NoConnect
)

__all__ = []


# Sizes of EESCHEMA schematic pages from smallest to largest. Dimensions in mm.
A_sizes_list = [
    ("A4", BBox(Point(0, 0), Point(297, 210))),
    ("A3", BBox(Point(0, 0), Point(420, 297))),
    ("A2", BBox(Point(0, 0), Point(594, 420))),
    ("A1", BBox(Point(0, 0), Point(841, 594))),
    ("A0", BBox(Point(0, 0), Point(1189, 841))),
]

# Create bounding box for each A size sheet.
A_sizes = OrderedDict(A_sizes_list)


def mil_to_mm(mil_value):
    """Convert mils to millimeters."""
    return mil_value * 0.0254


def mm_to_mil(mm_value):
    """Convert millimeters to mils."""
    return mm_value / 0.0254


def point_to_kicad_point(pt: Point, tx: Tx = None) -> KiCadPoint:
    """Convert SKiDL Point to KiCad Point with optional transformation."""
    if tx:
        pt = pt * tx
    # Convert from mils to mm
    return KiCadPoint(mil_to_mm(pt.x), mil_to_mm(pt.y))


def get_A_size(bbox):
    """Return the A-size page needed to fit the given bounding box."""
    # Convert bbox dimensions from mils to mm
    width = mil_to_mm(bbox.w)
    height = mil_to_mm(bbox.h * 1.25)  # HACK: why 1.25?
    
    for A_size, page in A_sizes.items():
        if width < page.w and height < page.h:
            return A_size
    return "A0"  # Nothing fits, so use the largest available.


def calc_sheet_tx(bbox):
    """Compute the page size and positioning for this sheet."""
    A_size = get_A_size(bbox)
    # Convert page bbox to mils for calculation
    page_bbox_mils = BBox(
        Point(0, 0), 
        Point(mm_to_mil(A_sizes[A_size].max.x), mm_to_mil(A_sizes[A_size].max.y))
    )
    page_bbox = bbox * Tx(d=-1)
    move_to_ctr = page_bbox_mils.ctr.snap(GRID) - page_bbox.ctr.snap(GRID)
    move_tx = Tx(d=-1).move(move_to_ctr)
    return move_tx


def calc_pin_dir(pin):
    """Calculate pin direction accounting for part transformation matrix."""
    # Copy the part trans. matrix, but remove the translation vector
    tx = pin.part.tx
    tx = Tx(a=tx.a, b=tx.b, c=tx.c, d=tx.d)

    # Use the pin orientation to compute the pin direction vector
    pin_vector = {
        "U": Point(0, 1),
        "D": Point(0, -1),
        "L": Point(-1, 0),
        "R": Point(1, 0),
    }[pin.orientation]

    # Rotate the direction vector using the part rotation matrix
    pin_vector = pin_vector * tx

    # Create an integer tuple from the rotated direction vector
    pin_vector = (int(round(pin_vector.x)), int(round(pin_vector.y)))

    # Return the pin orientation based on its rotated direction vector
    return {
        (0, 1): "U",
        (0, -1): "D",
        (-1, 0): "L",
        (1, 0): "R",
    }[pin_vector]


def get_rotation_from_orientation(orientation: str) -> float:
    """Convert orientation letter to rotation angle."""
    return {
        "R": 0,
        "U": 90,
        "L": 180,
        "D": 270,
    }.get(orientation, 0)


def create_default_stroke() -> Stroke:
    """Create a default stroke for wires."""
    return Stroke(
        width=0,
        stroke_type=StrokeType.DEFAULT,
        color=Color(0, 0, 0, 0)
    )


def create_text_effects(size: float = 1.27, bold: bool = False, 
                       italic: bool = False, hide: bool = False) -> TextEffects:
    """Create text effects for labels and properties."""
    font = Font(
        size=(size, size),
        bold=bold,
        italic=italic
    )
    return TextEffects(font=font, hide=hide)


def net_to_kicad6(self, tx):
    """Generate the KiCad 6+ code for the net terminal.

    Args:
        tx (Tx): Transformation matrix for the node containing this net terminal.

    Returns:
        str: KiCad 6+ code string.
    """
    self.pins[0].stub = True
    self.pins[0].orientation = "R"
    return pin_label_to_kicad6(self.pins[0], tx)


def part_to_kicad6(part, tx) -> str:
    """Create KiCad 6+ code for a part.

    Args:
        part (Part): SKiDL part.
        tx (Tx): Transformation matrix.

    Returns:
        str: KiCad 6+ code for the part.
    """
    tx = part.tx * tx
    origin = tx.origin
    unit_num = getattr(part, "num", 1)
    
    # Get rotation from transformation matrix
    rotation = 0
    if tx.a == 0 and tx.b == -1:
        rotation = 90
    elif tx.a == -1 and tx.d == -1:
        rotation = 180
    elif tx.a == 0 and tx.b == 1:
        rotation = 270
    
    # Create position
    position = Position(
        x=mil_to_mm(origin.x),
        y=mil_to_mm(origin.y),
        angle=rotation if rotation != 0 else None
    )
    
    # Create properties
    properties = []
    
    # Reference property (F0)
    # Try to get reference position from part symbol data
    ref_x_offset = 0
    ref_y_offset = 50  # Default fallback
    
    # Look for reference text positioning in draw_cmds
    if hasattr(part, 'draw_cmds') and part.draw_cmds:
        for unit_key, draw_objects in part.draw_cmds.items():
            for obj in draw_objects:
                if (isinstance(obj, list) and len(obj) > 0 and 
                    hasattr(obj[0], 'value') and obj[0].value().lower() == 'text'):
                    # Look for text objects that might be the reference
                    for item in obj[1:]:
                        if (isinstance(item, list) and len(item) > 1 and 
                            hasattr(item[0], 'value') and item[0].value().lower() == 'at'):
                            try:
                                ref_x_offset = mm_to_mil(float(item[1]))  # Convert mm to mils
                                ref_y_offset = mm_to_mil(float(item[2]))
                                break
                            except (ValueError, IndexError):
                                pass
            if ref_x_offset != 0 or ref_y_offset != 50:  # Found something
                break
    
    ref_pos = Position(
        x=mil_to_mm(origin.x + ref_x_offset),
        y=mil_to_mm(origin.y + ref_y_offset),
        angle=0
    )
    properties.append(Property(
        key="Reference",
        value=part.ref,
        id=0,
        position=ref_pos,
        effects=create_text_effects(size=1.27)
    ))
    
    # Value property (F1)
    val_pos = Position(
        x=mil_to_mm(origin.x),
        y=mil_to_mm(origin.y + 100),  # Offset below reference
        angle=0
    )
    properties.append(Property(
        key="Value",
        value=str(part.value) if part.value else part.name,
        id=1,
        position=val_pos,
        effects=create_text_effects(size=1.27)
    ))
    
    # Footprint property (F2)
    if part.footprint:
        fp_pos = Position(
            x=mil_to_mm(origin.x),
            y=mil_to_mm(origin.y - 100),  # Offset above reference
            angle=0
        )
        properties.append(Property(
            key="Footprint",
            value=part.footprint,
            id=2,
            position=fp_pos,
            effects=create_text_effects(size=1.27, hide=True)
        ))
    
    # Create symbol
    lib_name = os.path.splitext(part.lib.filename)[0]
    symbol = Symbol(
        library_identifier=f"{lib_name}:{part.name}",
        position=position,
        unit=str(unit_num),
        in_bom=True,
        on_board=True,
        unique_identifier=UniversallyUniqueIdentifier(None),
        properties=SList(properties),
        instances=SList([Project(
            name="",
            path="/",
            reference=part.ref,
            unit=unit_num
        )])
    )
    
    return str(symbol)


def wire_to_kicad6(net, wire, tx) -> str:
    """Create KiCad 6+ code for a multi-segment wire.

    Args:
        net (Net): Net associated with the wire.
        wire (list): List of Segments for a wire.
        tx (Tx): transformation matrix for each point in the wire.

    Returns:
        str: Text to be placed into KiCad file.
    """
    kicad_wires = []
    
    for segment in wire:
        # Transform and convert points
        p1 = segment.p1 * tx
        p2 = segment.p2 * tx
        
        points = [
            point_to_kicad_point(p1),
            point_to_kicad_point(p2)
        ]
        
        wire_obj = Wire(
            point_list=PointList(points),
            stroke=create_default_stroke(),
            unique_identifier=UniversallyUniqueIdentifier(None)
        )
        
        kicad_wires.append(str(wire_obj))
    
    return "\n".join(kicad_wires)


def junction_to_kicad6(net, junctions, tx) -> str:
    """Create KiCad 6+ code for junctions."""
    kicad_junctions = []
    
    for junction in junctions:
        pt = junction * tx
        position = Position(
            x=mil_to_mm(pt.x),
            y=mil_to_mm(pt.y),
            angle=None
        )
        
        junction_obj = Junction(
            position=position,
            diameter=0,
            color=Color(0, 0, 0, 0),
            unique_identifier=UniversallyUniqueIdentifier(None)
        )
        
        kicad_junctions.append(str(junction_obj))
    
    return "\n".join(kicad_junctions)


@export_to_all
def pin_label_to_kicad6(pin, tx) -> str:
    """Create KiCad 6+ text of net label attached to a pin."""
    if pin.stub is False or not pin.is_connected():
        return ""

    # Determine label type
    label_type = "HLabel"
    for pn in pin.net.pins:
        if pin.part.hierarchy.startswith(pn.part.hierarchy):
            continue
        if pn.part.hierarchy.startswith(pin.part.hierarchy):
            continue
        label_type = "GLabel"
        break

    part_tx = pin.part.tx * tx
    pt = pin.pt * part_tx

    pin_dir = calc_pin_dir(pin)
    rotation = get_rotation_from_orientation(pin_dir)

    position = Position(
        x=mil_to_mm(pt.x),
        y=mil_to_mm(pt.y),
        angle=rotation if rotation != 0 else None
    )

    effects = create_text_effects(size=mil_to_mm(PIN_LABEL_FONT_SIZE))

    if label_type == "HLabel":
        label = HierarchicalLabel(
            text=pin.net.name,
            position=position,
            effects=effects,
            unique_identifier=UniversallyUniqueIdentifier(None)
        )
    else:
        label = GlobalLabel(
            text=pin.net.name,
            position=position,
            effects=effects,
            unique_identifier=UniversallyUniqueIdentifier(None)
        )

    return str(label)


def create_kicad6_file(
    filename,
    contents,
    cur_sheet_num=1,
    total_sheet_num=1,
    title="Default",
    rev_major=0,
    rev_minor=1,
    year=datetime.date.today().year,
    month=datetime.date.today().month,
    day=datetime.date.today().day,
    A_size="A2",
):
    """Write KiCad 6+ header, contents, and footer to a file."""
    
    # KiCad 6+ uses a completely different format
    version = "20250114"  # KiCad 8 version from example
    generator = "eeschema"
    
    paper_width = A_sizes[A_size].max.x
    paper_height = A_sizes[A_size].max.y
    
    with open(filename, "w") as f:
        f.write(f"""(kicad_sch
\t(version {version})
\t(generator "{generator}")
\t(generator_version "9.0")
\t(uuid "084da128-17b4-4da8-842f-d3fafd978fe7")
\t(paper "{A_size}")
\t(title_block
\t\t(title "{title}")
\t\t(date "{year}-{month:02d}-{day:02d}")
\t\t(rev "v{rev_major}.{rev_minor}")
\t\t(company "")
\t\t(comment 1 "")
\t\t(comment 2 "")
\t\t(comment 3 "")
\t\t(comment 4 "")
\t)
\t(lib_symbols)
{contents}
\t(sheet_instances
\t\t(path "/"
\t\t\t(page "{cur_sheet_num}")
\t\t)
\t)
\t(embedded_fonts no)
)
""")


@export_to_all
def node_to_kicad6(node, sheet_tx=Tx()) -> str:
    """Convert node circuitry to a KiCad 6+ sheet.

    Args:
        node: Node to convert
        sheet_tx (Tx, optional): Scaling/translation matrix for sheet. Defaults to Tx().

    Returns:
        str: KiCad 6+ text for the node circuitry.
    """
    from skidl import HIER_SEP

    # List to hold all the KiCad code for this node
    kicad_code = []

    if node.flattened:
        # Create the transformation matrix for the placement of the parts in the node
        tx = node.tx * sheet_tx
    else:
        # Unflattened nodes are placed in their own sheet
        flattened_bbox = node.internal_bbox()
        tx = calc_sheet_tx(flattened_bbox)

    # Generate KiCad code for each child of this node
    for child in node.children.values():
        kicad_code.append(node_to_kicad6(child, tx))

    # Generate KiCad code for each part in the node
    for part in node.parts:
        if isinstance(part, NetTerminal):
            kicad_code.append(net_to_kicad6(part, tx=tx))
        else:
            kicad_code.append(part_to_kicad6(part, tx=tx))

    # Generate KiCad wiring code between the parts in the node
    for net, wire in node.wires.items():
        wire_code = wire_to_kicad6(net, wire, tx)
        kicad_code.append(wire_code)
    
    for net, junctions in node.junctions.items():
        junction_code = junction_to_kicad6(net, junctions, tx)
        kicad_code.append(junction_code)

    # Generate pin labels for stubbed nets on each part in the node
    for part in node.parts:
        for pin in part:
            pin_label_code = pin_label_to_kicad6(pin, tx)
            if pin_label_code:
                kicad_code.append(pin_label_code)

    # Join KiCad code into one big string
    kicad_code = "\n".join(kicad_code)

    # If this node was flattened, return the KiCad code
    if node.flattened:
        # For KiCad 6+, we don't use graphic boxes for hierarchical blocks
        # They are represented differently
        return kicad_code

    # Create a hierarchical sheet file for storing this unflattened node
    A_size = get_A_size(node.internal_bbox())
    filepath = os.path.join(node.filepath, node.sheet_filename)
    create_kicad6_file(filepath, kicad_code, title=node.title, A_size=A_size)

    # Create the hierarchical sheet for insertion into the calling node sheet
    # In KiCad 6+, hierarchical sheets are represented differently
    # This would need to be implemented based on the actual KiCad 6+ format
    bbox = (node.bbox * node.tx * sheet_tx).round()
    
    # For now, return empty string as hierarchical sheet representation
    # would need more complex implementation
    return ""


# Re-export the main generation functions with modifications for KiCad 6+
from ..kicad5.gen_schematic import finalize_parts_and_nets
from .bboxes import calc_symbol_bbox

def preprocess_circuit(circuit, **options):
    """Add stuff to parts & nets for doing placement and routing of schematics."""

    def units(part):
        if len(part.unit) == 0:
            return [part]
        else:
            return part.unit.values()

    def initialize(part):
        """Initialize part or its part units."""

        # Initialize the units of the part, or the part itself if it has no units.
        pin_limit = options.get("orientation_pin_limit", 44)
        for part_unit in units(part):
            # Initialize transform matrix.
            part_unit.tx = Tx.from_symtx(getattr(part_unit, "symtx", ""))

            # Lock part orientation if symtx was specified. Also lock parts with a lot of pins
            # since they're typically drawn the way they're supposed to be oriented.
            # And also lock single-pin parts because these are usually power/ground and
            # they shouldn't be flipped around.
            num_pins = len(part_unit.pins)
            part_unit.orientation_locked = getattr(part_unit, "symtx", False) or not (
                1 < num_pins <= pin_limit
            )

            # Assign pins from the parent part to the part unit.
            part_unit.grab_pins()

            # Initialize pin attributes used for generating schematics.
            for pin in part_unit:
                pin.pt = Point(pin.x, pin.y)
                pin.routed = False

    def calc_part_bbox(part):
        """Calculate the labeled bounding boxes and store it in the part."""

        # Find part/unit bounding boxes excluding any net labels on pins.
        # Use KiCad8-specific calc_symbol_bbox function
        bare_bboxes = calc_symbol_bbox(part)[1:]

        for part_unit, bare_bbox in zip(units(part), bare_bboxes):
            # Expand the bounding box if it's too small in either dimension.
            resize_wh = Vector(0, 0)
            if bare_bbox.w < 100:
                resize_wh.x = (100 - bare_bbox.w) / 2
            if bare_bbox.h < 100:
                resize_wh.y = (100 - bare_bbox.h) / 2
            bare_bbox = bare_bbox.resize(resize_wh)

            # Find expanded bounding box that includes any hier labels attached to pins.
            part_unit.lbl_bbox = BBox()
            part_unit.lbl_bbox.add(bare_bbox)
            for pin in part_unit:
                if pin.stub:
                    # For KiCad8, we'll use a simple approximation for hierarchical label bbox
                    # since calc_hier_label_bbox is not implemented
                    hlbl_bbox = BBox(Point(-50, -10), Point(50, 10))  # Simple approximation
                    # Move the label bbox to the pin location.
                    hlbl_bbox *= Tx().move(pin.pt)
                    # Update the bbox for the labelled part with this pin label.
                    part_unit.lbl_bbox.add(hlbl_bbox)

            # Set the active bounding box to the labeled version.
            part_unit.bbox = part_unit.lbl_bbox

    # Pre-process parts
    for part in circuit.parts:
        # Initialize part attributes used for generating schematics.
        initialize(part)

        # Compute bounding boxes around parts
        calc_part_bbox(part)


@export_to_all
def gen_schematic(
    circuit,
    filepath=".",
    top_name=None,
    title="SKiDL-Generated Schematic",
    flatness=0.0,
    retries=2,
    **options
):
    """Create a KiCad 6+ schematic file from a Circuit object.

    Args:
        circuit (Circuit): The Circuit object that will have a schematic generated for it.
        filepath (str, optional): The directory where the schematic files are placed. Defaults to ".".
        top_name (str, optional): The name for the top of the circuit hierarchy. Defaults to script name.
        title (str, optional): The title of the schematic. Defaults to "SKiDL-Generated Schematic".
        flatness (float, optional): Determines how much the hierarchy is flattened. Defaults to 0.0.
        retries (int, optional): Number of times to re-try if routing fails. Defaults to 2.
        options (dict, optional): Dict of options and values, usually for drawing/debugging.
    """
    from skidl import KICAD8  # Assuming KICAD8 constant exists
    from skidl.schematics.place import PlacementFailure
    from skidl.schematics.route import RoutingFailure
    from skidl.tools import tool_modules
    from skidl.schematics.node import Node

    if top_name is None:
        top_name = get_script_name()

    # Part placement options that should always be turned on
    options["use_push_pull"] = True
    options["rotate_parts"] = True
    options["pt_to_pt_mult"] = 5  # HACK: Ad-hoc value
    options["pin_normalize"] = True

    # Start with default routing area
    expansion_factor = 1.0

    # Try to place & route one or more times
    for _ in range(retries):
        preprocess_circuit(circuit, **options)

        node = Node(circuit, tool_modules[KICAD8], filepath, top_name, title, flatness)

        try:
            # Place parts
            node.place(expansion_factor=expansion_factor, **options)

            # Route parts
            node.route(**options)

        except PlacementFailure:
            # Placement failed, so clean up and try again
            finalize_parts_and_nets(circuit, **options)
            continue

        except RoutingFailure:
            # Routing failed, so clean up and try again with expanded area
            finalize_parts_and_nets(circuit, **options)
            expansion_factor *= 1.5
            continue

        # Generate KiCad 6+ code for the schematic
        node_to_kicad6(node)

        # Append place & route statistics for the schematic to a file
        if options.get("collect_stats"):
            stats = node.collect_stats(**options)
            with open(options["stats_file"], "a") as f:
                f.write(stats)

        # Clean up
        finalize_parts_and_nets(circuit, **options)

        # Place & route was successful if we got here, so exit
        return

    # Append failed place & route statistics for the schematic to a file
    if options.get("collect_stats"):
        stats = "-1\n"
        with open(options["stats_file"], "a") as f:
            f.write(stats)

    # Clean-up after failure
    finalize_parts_and_nets(circuit, **options)

    # Exited the loop without successful routing
    raise RoutingFailure("Failed to route schematic after {} retries".format(retries))