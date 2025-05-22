# -*- coding: utf-8 -*-

# The MIT License (MIT) - Copyright (c) Dave Vandenbout.


import datetime
import os.path
import re
import time
from collections import Counter, OrderedDict

from skidl.scriptinfo import get_script_name
from skidl.geometry import BBox, Point, Tx, Vector
from skidl.schematics.net_terminal import NetTerminal
from skidl.utilities import export_to_all
from .constants import BLK_INT_PAD, BOX_LABEL_FONT_SIZE, GRID, PIN_LABEL_FONT_SIZE
from .bboxes import calc_symbol_bbox, calc_hier_label_bbox
from skidl.schematics.place import PlacementFailure
from skidl.schematics.route import RoutingFailure
from skidl.utilities import rmv_attr
import sexpdata
from skidl.utilities import to_list


__all__ = []

"""
Functions for generating a KiCad EESCHEMA schematic.
"""


def bbox_to_eeschema(bbox, tx, name=None):
    """Create a bounding box using EESCHEMA graphic lines for KiCad 8.

    Args:
        bbox (BBox): The bounding box to draw.
        tx (Tx): Transformation matrix to apply.
        name (str, optional): Optional name to display. Defaults to None.

    Returns:
        str: KiCad 8 schematic code for drawing the box.
    """
    # Make sure the box corners are integers.
    bbox = (bbox * tx).round()

    graphic_box = []

    if name:
        # Place name at the lower-left corner of the box.
        name_pt = bbox.ul
        graphic_box.append(
            "  (text (at {} {}) (size {} {})\n    (text \"{}\")\n    (effects (font (size 1.27 1.27))))".format(
                name_pt.x, name_pt.y, BOX_LABEL_FONT_SIZE/40, BOX_LABEL_FONT_SIZE/40, name
            )
        )

    # Create a rectangle using polyline in KiCad 8 format
    graphic_box.append(
        "  (polyline\n    (pts\n      (xy {} {})\n      (xy {} {})\n"
        "      (xy {} {})\n      (xy {} {})\n      (xy {} {})\n    )\n"
        "    (stroke (width 0.1) (type default))\n    (fill (type none))\n  )".format(
            bbox.ll.x, bbox.ll.y, 
            bbox.lr.x, bbox.lr.y,
            bbox.ur.x, bbox.ur.y,
            bbox.ul.x, bbox.ul.y,
            bbox.ll.x, bbox.ll.y
        )
    )

    return "\n".join(graphic_box)


def net_to_eeschema(self, tx):
    """Generate the EESCHEMA code for the net terminal in KiCad 8 format.

    Args:
        tx (Tx): Transformation matrix for the node containing this net terminal.

    Returns:
        str: EESCHEMA code string for KiCad 8.
    """
    self.pins[0].stub = True
    self.pins[0].orientation = "R"
    return pin_label_to_eeschema(self.pins[0], tx)


def find_sexp_obj_local(sexp_list, obj_type_to_find):
    for item in sexp_list:
        item_list = to_list(item)
        if not item_list: continue
        if isinstance(item_list[0], sexpdata.Symbol) and item_list[0].value().lower() == obj_type_to_find:
            return item_list
    return []


def get_property_details(part_draw_cmds_unit, prop_name):
    prop_at_x, prop_at_y, prop_at_angle = 0, 0, 0 # Defaults
    prop_size_x, prop_size_y = 1.27, 1.27 # KiCad default size in mm
    prop_effects_str = "" # For bold/italic, not directly used in (at ...) but for style

    for cmd_s_expr in part_draw_cmds_unit:
        if not cmd_s_expr or not isinstance(cmd_s_expr[0], sexpdata.Symbol):
            continue
        if cmd_s_expr[0].value().lower() == "property" and len(cmd_s_expr) > 1 and cmd_s_expr[1] == prop_name:
            # Found the property, e.g., (property "Reference" ... (at ...) (effects ...))
            at_list = find_sexp_obj_local(cmd_s_expr, "at")
            if at_list and len(at_list) >= 4: # (at x y angle) or (at x y)
                prop_at_x = float(at_list[1])
                prop_at_y = float(at_list[2])
                if len(at_list) > 3:
                    prop_at_angle = float(at_list[3]) # Usually 0 for text fields

            effects_list = find_sexp_obj_local(cmd_s_expr, "effects")
            if effects_list:
                font_list = find_sexp_obj_local(effects_list, "font")
                if font_list:
                    size_list = find_sexp_obj_local(font_list, "size")
                    if size_list and len(size_list) > 2:
                        prop_size_x = float(size_list[1])
                        prop_size_y = float(size_list[2])
                    # Could parse bold/italic here if needed for style string
                    if find_sexp_obj_local(font_list, "italic"):
                        prop_effects_str += " italic"
                    if find_sexp_obj_local(font_list, "bold"):
                        prop_effects_str += " bold"
            return prop_at_x, prop_at_y, prop_at_angle, prop_size_x, prop_size_y, prop_effects_str.strip()
    return prop_at_x, prop_at_y, prop_at_angle, prop_size_x, prop_size_y, prop_effects_str # Defaults if not found


def part_to_eeschema(part, tx):
    """Create EESCHEMA code for a part in KiCad 8 format.

    Args:
        part (Part): SKiDL part.
        tx (Tx): Transformation matrix.

    Returns:
        string: EESCHEMA code for the part.
    """
    abs_tx = part.tx * tx # Absolute transformation for the part
    part_origin_abs = abs_tx.origin.round() # Absolute origin of the part
    
    # KiCad symbol origin is (0,0) within its own definition.
    # The (at x y) in the schematic is the part's absolute position.
    # The (at x y angle) for properties inside the symbol are relative to the symbol's origin.
    
    unit_num = getattr(part, "num", 1) # num is the KiCad unit number (1-based)

    # Determine the key for draw_cmds for this unit
    # This logic should mirror how unit keys are resolved in bboxes.py or how lib.py stores them.
    # For simple parts, part.unit is often {'uA': self} and draw_cmds might be keyed by 1.
    draw_cmds_key = unit_num # Default to the KiCad unit number
    if len(part.unit) == 1 and list(part.unit.keys())[0] == 'uA' and unit_num == 1 : # Common case for single unit parts
         # lib.py often stores draw_cmds under integer keys (1, 2, ...)
         # if part.unit has 'uA', it implies unit 1.
         # No specific re-mapping needed if draw_cmds is already keyed by '1' (as integer or string)
         # The actual key in draw_cmds can be int 1 or string '1'
         if 1 in part.draw_cmds: draw_cmds_key = 1
         elif '1' in part.draw_cmds: draw_cmds_key = '1'
         # If it's a multi-unit part and part.num gives e.g. 2, draw_cmds_key should be 2 or '2'
    
    # Ensure we have a valid key for draw_cmds, falling back if needed
    if draw_cmds_key not in part.draw_cmds and 1 in part.draw_cmds: # Fallback for simple parts if unit_num wasn't 1
        active_logger.warning(f"Falling back to draw_cmds key 1 for part {part.ref} unit {unit_num}")
        draw_cmds_key = 1
    elif draw_cmds_key not in part.draw_cmds and '1' in part.draw_cmds:
        active_logger.warning(f"Falling back to draw_cmds key '1' for part {part.ref} unit {unit_num}")
        draw_cmds_key = '1'


    part_draw_cmds_for_unit = part.draw_cmds.get(draw_cmds_key, [])
    if not part_draw_cmds_for_unit:
        active_logger.warning(f"No draw_cmds found for part {part.ref} unit key {draw_cmds_key}. Using defaults for properties.")

    ref_at_x, ref_at_y, ref_at_angle, ref_size_x, ref_size_y, ref_effects = get_property_details(part_draw_cmds_for_unit, "Reference")
    val_at_x, val_at_y, val_at_angle, val_size_x, val_size_y, val_effects = get_property_details(part_draw_cmds_for_unit, "Value")
    fp_at_x, fp_at_y, fp_at_angle, fp_size_x, fp_size_y, fp_effects = get_property_details(part_draw_cmds_for_unit, "Footprint")

    # Apply part's absolute transformation to relative property positions
    # The (at x y) for properties in the schematic is absolute.
    # The (at x y) in the library symbol for a property is relative to symbol (0,0)
    # So, transform the relative property `at` by the part's absolute transform `abs_tx`
    ref_pos_abs = Point(ref_at_x, ref_at_y) * abs_tx
    val_pos_abs = Point(val_at_x, val_at_y) * abs_tx
    fp_pos_abs = Point(fp_at_x, fp_at_y) * abs_tx
    
    # Angle for property text field is usually 0 in schematic unless symbol itself is rotated
    # The abs_tx.get_rotation_deg() gives the part's overall rotation.
    # Property rotation in schematic = property's library angle + part's schematic angle
    ref_angle_abs = (ref_at_angle + abs_tx.get_rotation_deg()) % 360
    val_angle_abs = (val_at_angle + abs_tx.get_rotation_deg()) % 360
    fp_angle_abs = (fp_at_angle + abs_tx.get_rotation_deg()) % 360


    eeschema = []
    # Symbol definition: lib_id, at (part's absolute origin), unit, mirror, rotation
    # Rotation and mirroring are handled by the transformation matrix `abs_tx`
    mirror_str = ""
    if abs_tx.a < 0: mirror_str += " mirror_x" # Simplified check for mirroring
    if abs_tx.d < 0: mirror_str += " mirror_y" # Simplified check for mirroring
        
    eeschema.append("  (symbol (lib_id \"{}:{}\") (at {} {}) (unit {}){} (rotate {}) (in_bom yes) (on_board yes)".format(
        os.path.splitext(part.lib.filename)[0], 
        part.name, 
        part_origin_abs.x, 
        part_origin_abs.y,
        unit_num,
        mirror_str,
        abs_tx.get_rotation_deg() # Used get_rotation_deg() for part's overall rotation
    ))
        
    # Add reference designator
    eeschema.append("    (property \\\"Reference\\\" \\\"{}\\\" (id 0) (at {} {} {})".format(
        part.ref,
        ref_pos_abs.x, # Absolute X
        ref_pos_abs.y, # Absolute Y
        ref_angle_abs  # Absolute angle
    ))
    eeschema.append("      (effects (font (size {} {}) {}))".format( # size x, size y
        ref_size_x, ref_size_y,
        ref_effects
    ))
    eeschema.append("    )")
    
    # Add value
    eeschema.append("    (property \\\"Value\\\" \\\"{}\\\" (id 1) (at {} {} {})".format(
        str(part.value), # Ensure value is string
        val_pos_abs.x,
        val_pos_abs.y,
        val_angle_abs
    ))
    eeschema.append("      (effects (font (size {} {}) {}))".format(
        val_size_x, val_size_y,
        val_effects
    ))
    eeschema.append("    )")
    
    # Add footprint
    # Footprint field is often hidden in schematics
    eeschema.append("    (property \\\"Footprint\\\" \\\"{}\\\" (id 2) (at {} {} {})".format(
        part.footprint,
        fp_pos_abs.x,
        fp_pos_abs.y,
        fp_angle_abs
    ))
    eeschema.append("      (effects (font (size {} {}) {}) hide)".format( # Added hide
        fp_size_x, fp_size_y,
        fp_effects
    ))
    eeschema.append("    )")
    
    # Add other explicit fields/properties the part might have
    # Standard fields like Datasheet, etc.
    # KiCad 8 symbol format can include many properties directly.
    # This part needs to be more generic if all symbol properties from library should be included.
    # For now, sticking to Ref, Value, Footprint.

    # Close the symbol
    eeschema.append("  )")
    
    return "\\n".join(eeschema)


def wire_to_eeschema(net, wire, tx):
    """Create EESCHEMA code for a multi-segment wire in KiCad 8 format.

    Args:
        net (Net): Net associated with the wire.
        wire (list): List of Segments for a wire.
        tx (Tx): transformation matrix for each point in the wire.

    Returns:
        string: Text to be placed into EESCHEMA file.
    """
    eeschema = []
    
    for segment in wire:
        w = (segment * tx).round()
        eeschema.append("  (wire (pts (xy {} {}) (xy {} {}))".format(
            w.p1.x, w.p1.y, w.p2.x, w.p2.y
        ))
        eeschema.append("    (stroke (width 0) (type default) (color 0 0 0 0))")
        
        # Add net class information if available
        if hasattr(net, 'netclass') and net.netclass:
            eeschema.append("    (net {})".format(net.code))
        
        eeschema.append("  )")
    
    return "\n".join(eeschema)


def junction_to_eeschema(net, junctions, tx):
    """Create EESCHEMA code for junctions in KiCad 8 format.

    Args:
        net (Net): Net associated with the junctions.
        junctions (list): List of Point objects for each junction.
        tx (Tx): Transformation matrix for the junction locations.

    Returns:
        string: Text to be placed into EESCHEMA file.
    """
    eeschema = []
    
    for junction in junctions:
        pt = (junction * tx).round()
        eeschema.append("  (junction (at {} {})".format(pt.x, pt.y))
        
        # Add net class information if available
        if hasattr(net, 'code'):
            eeschema.append("    (net {})".format(net.code))
        
        eeschema.append("  )")
    
    return "\n".join(eeschema)


def power_part_to_eeschema(part, tx=Tx()):
    """Generate EESCHEMA code for a power component.
    
    Args:
        part (Part): The part that may contain pins connected to power nets.
        tx (Tx, optional): Transformation matrix. Defaults to Tx().
        
    Returns:
        str: EESCHEMA code for any power symbols needed.
    """
    out = []
    for pin in part.pins:
        try:
            if not (pin.net is None):
                if pin.net.netclass == "Power":
                    # strip out the '_...' section from power nets
                    t = pin.net.name
                    u = t.split("_")
                    symbol_name = u[0]
                    # find the stub in the part
                    time_hex = hex(int(time.time()))[2:]
                    
                    # Calculate pin position with transformation
                    part_tx = part.tx * tx
                    pin_pt = (pin.pt * part_tx).round()
                    x, y = pin_pt.x, pin_pt.y
                    
                    out.append("$Comp\n")
                    out.append("L power:{} #PWR?\n".format(symbol_name))
                    out.append("U 1 1 {}\n".format(time_hex))
                    out.append("P {} {}\n".format(str(x), str(y)))
                    
                    # Add part symbols. For now we are only adding the designator
                    n_F0 = 1
                    for i in range(len(part.draw)):
                        if re.search("^DrawF0", str(part.draw[i])):
                            n_F0 = i
                            break
                    part_orientation = part.draw[n_F0].orientation
                    part_horizontal_align = part.draw[n_F0].halign
                    part_vertical_align = part.draw[n_F0].valign

                    # Default orientation
                    orientation = [1, 0, 0, 1]  
                    
                    # check if the pin orientation will clash with the power part
                    if "+" in symbol_name:
                        # voltage sources face up, so check if the pin is facing down (opposite logic y-axis)
                        if pin.orientation == "U":
                            orientation = [-1, 0, 0, 1]
                    elif "gnd" in symbol_name.lower():
                        # gnd points down so check if the pin is facing up (opposite logic y-axis)
                        if pin.orientation == "D":
                            orientation = [-1, 0, 0, 1]
                            
                    out.append(
                        'F 0 "{}" {} {} {} {} {} {} {}\n'.format(
                            "#PWR?",
                            part_orientation,
                            str(x + 25),
                            str(y + 25),
                            str(40),
                            "001",
                            part_horizontal_align,
                            part_vertical_align,
                        )
                    )
                    out.append(
                        'F 1 "{}" {} {} {} {} {} {} {}\n'.format(
                            symbol_name,
                            part_orientation,
                            str(x + 25),
                            str(y + 25),
                            str(40),
                            "000",
                            part_horizontal_align,
                            part_vertical_align,
                        )
                    )
                    out.append("   1   {} {}\n".format(str(x), str(y)))
                    out.append(
                        "   {}   {}  {}  {}\n".format(
                            orientation[0],
                            orientation[1],
                            orientation[2],
                            orientation[3],
                        )
                    )
                    out.append("$EndComp\n")
        except Exception as inst:
            print(type(inst))
            print(inst.args)
            print(inst)
    
    return "\n" + "".join(out) if out else ""


# Sizes of EESCHEMA schematic pages from smallest to largest. Dimensions in mils.
A_sizes_list = [
    ("A4", BBox(Point(0, 0), Point(11693, 8268))),
    ("A3", BBox(Point(0, 0), Point(16535, 11693))),
    ("A2", BBox(Point(0, 0), Point(23386, 16535))),
    ("A1", BBox(Point(0, 0), Point(33110, 23386))),
    ("A0", BBox(Point(0, 0), Point(46811, 33110))),
]

# Create bounding box for each A size sheet.
A_sizes = OrderedDict(A_sizes_list)


def get_A_size(bbox):
    """Return the A-size page needed to fit the given bounding box."""

    width = bbox.w
    height = bbox.h * 1.25  # HACK: why 1.25?
    for A_size, page in A_sizes.items():
        if width < page.w and height < page.h:
            return A_size
    return "A0"  # Nothing fits, so use the largest available.


def calc_sheet_tx(bbox):
    """Compute the page size and positioning for this sheet."""
    A_size = get_A_size(bbox)
    page_bbox = bbox * Tx(d=-1)
    move_to_ctr = A_sizes[A_size].ctr.snap(GRID) - page_bbox.ctr.snap(GRID)
    move_tx = Tx(d=-1).move(move_to_ctr)
    return move_tx


def calc_pin_dir(pin):
    """Calculate pin direction accounting for part transformation matrix."""

    # Copy the part trans. matrix, but remove the translation vector, leaving only scaling/rotation stuff.
    tx = pin.part.tx
    tx = Tx(a=tx.a, b=tx.b, c=tx.c, d=tx.d)

    # Use the pin orientation to compute the pin direction vector.
    pin_vector = {
        "U": Point(0, 1),
        "D": Point(0, -1),
        "L": Point(-1, 0),
        "R": Point(1, 0),
    }[pin.orientation]

    # Rotate the direction vector using the part rotation matrix.
    pin_vector = pin_vector * tx

    # Create an integer tuple from the rotated direction vector.
    pin_vector = (int(round(pin_vector.x)), int(round(pin_vector.y)))

    # Return the pin orientation based on its rotated direction vector.
    return {
        (0, 1): "U",
        (0, -1): "D",
        (-1, 0): "L",
        (1, 0): "R",
    }[pin_vector]


@export_to_all
def pin_label_to_eeschema(pin, tx):
    """Create EESCHEMA text of net label attached to a pin for KiCad 8.

    Args:
        pin (Pin): The pin to attach the label to.
        tx (Tx): Transformation matrix.

    Returns:
        str: EESCHEMA code string for KiCad 8.
    """
    if pin.stub is False or not pin.is_connected():
        # No label if pin is not connected or is connected to an explicit wire.
        return ""

    label_type = "hierarchical"  # Default for HLabel
    for pn in pin.net.pins:
        if pin.part.hierarchy.startswith(pn.part.hierarchy):
            continue
        if pn.part.hierarchy.startswith(pin.part.hierarchy):
            continue
        label_type = "global"  # For GLabel
        break

    part_tx = pin.part.tx * tx
    pt = pin.pt * part_tx

    pin_dir = calc_pin_dir(pin)
    orientation_map = {
        "R": 0,
        "D": 90,  # In KiCad 8, angles are in degrees
        "L": 180,
        "U": 270,
    }
    orientation = orientation_map[pin_dir]

    # KiCad 8 uses a different format for labels
    return "  (label (at {} {}) (size {} {})\n    (text \"{}\")\n    (effects (font (size 1.27 1.27)))\n    (net {} \"{}\"))".format(
        int(round(pt.x)),
        int(round(pt.y)),
        PIN_LABEL_FONT_SIZE/40,  # Convert to mm
        PIN_LABEL_FONT_SIZE/40,
        pin.net.name,
        getattr(pin.net, 'code', 0),
        pin.net.name
    )


def create_eeschema_file(
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
    """Write EESCHEMA header, contents, and footer to a file for KiCad 8.
    
    KiCad 8 uses a modified schematic file format compared to KiCad 5.
    """
    with open(filename, "w") as f:
        f.write(
            "\n".join(
                (
                    "(kicad_sch (version 20231120) (generator skidl)",
                    "  (paper \"{}\"".format(A_size),
                    "    (title_block",
                    '      (title "{}")'.format(title),
                    '      (date "{}-{:02d}-{:02d}")'.format(year, month, day),
                    '      (rev "v{}.{}")'.format(rev_major, rev_minor),
                    "    )",
                    "  )",
                    "",
                    "  {}".format(contents),
                    ")",
                )
            )
        )


@export_to_all
def node_to_eeschema(node, sheet_tx=Tx()):
    """Convert node circuitry to an EESCHEMA sheet.

    Args:
        sheet_tx (Tx, optional): Scaling/translation matrix for sheet. Defaults to Tx().

    Returns:
        str: EESCHEMA text for the node circuitry.
    """

    from skidl import HIER_SEP

    # List to hold all the EESCHEMA code for this node.
    eeschema_code = []

    if node.flattened:
        # Create the transformation matrix for the placement of the parts in the node.
        tx = node.tx * sheet_tx
    else:
        # Unflattened nodes are placed in their own sheet, so compute
        # their bounding box as if they *were* flattened and use that to
        # find the transformation matrix for an appropriately-sized sheet.
        flattened_bbox = node.internal_bbox()
        tx = calc_sheet_tx(flattened_bbox)

    # Generate EESCHEMA code for each child of this node.
    for child in node.children.values():
        eeschema_code.append(node_to_eeschema(child, tx))

    # Generate EESCHEMA code for each part in the node.
    for part in node.parts:
        if isinstance(part, NetTerminal):
            eeschema_code.append(net_to_eeschema(part, tx=tx))
        else:
            eeschema_code.append(part_to_eeschema(part, tx=tx))

    # Generate EESCHEMA wiring code between the parts in the node.
    for net, wire in node.wires.items():
        wire_code = wire_to_eeschema(net, wire, tx=tx)
        eeschema_code.append(wire_code)
    for net, junctions in node.junctions.items():
        junction_code = junction_to_eeschema(net, junctions, tx=tx)
        eeschema_code.append(junction_code)

    # Generate power connections for the each part in the node.
    for part in node.parts:
        stub_code = power_part_to_eeschema(part, tx=tx)
        if len(stub_code) != 0:
            eeschema_code.append(stub_code)

    # Generate pin labels for stubbed nets on each part in the node.
    for part in node.parts:
        for pin in part:
            pin_label_code = pin_label_to_eeschema(pin, tx=tx)
            eeschema_code.append(pin_label_code)

    # Join EESCHEMA code into one big string.
    eeschema_code = "\n".join(eeschema_code)

    # If this node was flattened, then return the EESCHEMA code and surrounding box
    # for inclusion in the parent node.
    if node.flattened:

        # Generate the graphic box that surrounds the flattened hierarchical block of this node.
        block_name = node.name.split(HIER_SEP)[-1]
        pad = Vector(BLK_INT_PAD, BLK_INT_PAD)
        bbox_code = bbox_to_eeschema(node.bbox.resize(pad), tx, block_name)

        return "\n".join((eeschema_code, bbox_code))

    # Create a hierarchical sheet file for storing this unflattened node.
    A_size = get_A_size(flattened_bbox)
    filepath = os.path.join(node.filepath, node.sheet_filename)
    create_eeschema_file(filepath, eeschema_code, title=node.title, A_size=A_size)

    # Create the hierarchical sheet for insertion into the calling node sheet.
    bbox = (node.bbox * node.tx * sheet_tx).round()
    time_hex = hex(int(time.time()))[2:]
    return "\n".join(
        (
            "$Sheet",
            "S {} {} {} {}".format(bbox.ll.x, bbox.ll.y, bbox.w, bbox.h),
            "U {}".format(time_hex),
            'F0 "{}" {}'.format(node.name, node.name_sz),
            'F1 "{}" {}'.format(node.sheet_filename, node.filename_sz),
            "$EndSheet",
            "",
        )
    )


"""
Generate a KiCad EESCHEMA schematic from a Circuit object.
"""

# TODO: Handle symio attribute.


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

    def rotate_power_pins(part):
        """Rotate a part based on the direction of its power pins.

        This function is to make sure that voltage sources face up and gnd pins
        face down.
        """

        # Don't rotate parts that are already explicitly rotated/flipped.
        if not getattr(part, "symtx", ""):
            return

        def is_pwr(net):
            return net_name.startswith("+")

        def is_gnd(net):
            return "gnd" in net_name.lower()

        dont_rotate_pin_cnt = options.get("dont_rotate_pin_count", 10000)

        for part_unit in units(part):
            # Don't rotate parts with too many pins.
            if len(part_unit) > dont_rotate_pin_cnt:
                return

            # Tally what rotation would make each pwr/gnd pin point up or down.
            rotation_tally = Counter()
            for pin in part_unit:
                net_name = getattr(pin.net, "name", "").lower()
                if is_gnd(net_name):
                    if pin.orientation == "U":
                        rotation_tally[0] += 1
                    if pin.orientation == "D":
                        rotation_tally[180] += 1
                    if pin.orientation == "L":
                        rotation_tally[90] += 1
                    if pin.orientation == "R":
                        rotation_tally[270] += 1
                elif is_pwr(net_name):
                    if pin.orientation == "D":
                        rotation_tally[0] += 1
                    if pin.orientation == "U":
                        rotation_tally[180] += 1
                    if pin.orientation == "L":
                        rotation_tally[270] += 1
                    if pin.orientation == "R":
                        rotation_tally[90] += 1

            # Rotate the part unit in the direction with the most tallies.
            try:
                rotation = rotation_tally.most_common()[0][0]
            except IndexError:
                pass
            else:
                # Rotate part unit 90-degrees clockwise until the desired rotation is reached.
                tx_cw_90 = Tx(a=0, b=-1, c=1, d=0)  # 90-degree trans. matrix.
                for _ in range(int(round(rotation / 90))):
                    part_unit.tx = part_unit.tx * tx_cw_90

    def calc_part_bbox(part):
        """Calculate the labeled bounding boxes and store it in the part."""

        # Find part/unit bounding boxes excluding any net labels on pins.
        calc_symbol_bbox(part)

        for part_unit in part.unit.values():
            # Expand the bounding box if it's too small in either dimension.
            resize_wh = Vector(0, 0)
            if part_unit.bbox.w < 100:
                resize_wh.x = (100 - part_unit.bbox.w) / 2
            if part_unit.bbox.h < 100:
                resize_wh.y = (100 - part_unit.bbox.h) / 2
            bare_bbox = part_unit.bbox.resize(resize_wh)

            # Find expanded bounding box that includes any hier labels attached to pins.
            part_unit.lbl_bbox = BBox()
            part_unit.lbl_bbox.add(bare_bbox)
            for pin in part_unit:
                if pin.stub:
                    # Find bounding box for net stub label attached to pin.
                    hlbl_bbox = calc_hier_label_bbox(pin.net.name, pin.orientation)
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

        # Rotate parts.  Power pins should face up. GND pins should face down.
        rotate_power_pins(part)

        # Compute bounding boxes around parts
        calc_part_bbox(part)


def finalize_parts_and_nets(circuit, **options):
    """Restore parts and nets after place & route is done."""

    # Remove any NetTerminals that were added.
    net_terminals = (p for p in circuit.parts if isinstance(p, NetTerminal))
    circuit.rmv_parts(*net_terminals)

    # Return pins from the part units to their parent part.
    for part in circuit.parts:
        part.grab_pins()

    # Remove some stuff added to parts during schematic generation process.
    rmv_attr(circuit.parts, ("force", "bbox", "lbl_bbox", "tx"))


@export_to_all
def gen_schematic(
    circuit,
    filepath=".",
    top_name=get_script_name(),
    title="SKiDL-Generated Schematic",
    flatness=0.0,
    retries=2,
    **options
):
    """Create a schematic file from a Circuit object.

    Args:
        circuit (Circuit): The Circuit object that will have a schematic generated for it.
        filepath (str, optional): The directory where the schematic files are placed. Defaults to ".".
        top_name (str, optional): The name for the top of the circuit hierarchy. Defaults to get_script_name().
        title (str, optional): The title of the schematic. Defaults to "SKiDL-Generated Schematic".
        flatness (float, optional): Determines how much the hierarchy is flattened in the schematic. Defaults to 0.0 (completely hierarchical).
        retries (int, optional): Number of times to re-try if routing fails. Defaults to 2.
        options (dict, optional): Dict of options and values, usually for drawing/debugging.
    """

    from skidl import KICAD8
    from skidl.schematics.place import PlacementFailure
    from skidl.schematics.route import RoutingFailure
    from skidl.tools import tool_modules
    from skidl.schematics.node import Node

    # Part placement options that should always be turned on.
    options["use_push_pull"] = True
    options["rotate_parts"] = True
    options["pt_to_pt_mult"] = 5  # HACK: Ad-hoc value.
    options["pin_normalize"] = True

    # Start with default routing area.
    expansion_factor = 1.0

    # Try to place & route one or more times.
    for _ in range(retries):
        preprocess_circuit(circuit, **options)

        node = Node(circuit, tool_modules[KICAD8], filepath, top_name, title, flatness)

        try:
            # Place parts.
            node.place(expansion_factor=expansion_factor, **options)

            # Route parts.
            node.route(**options)

        except PlacementFailure:
            # Placement failed, so clean up ...
            finalize_parts_and_nets(circuit, **options)
            # ... and try again.
            continue

        except RoutingFailure:
            # Routing failed, so clean up ...
            finalize_parts_and_nets(circuit, **options)
            # ... and expand routing area ...
            expansion_factor *= 1.5  # HACK: Ad-hoc increase of expansion factor.
            # ... and try again.
            continue

        # Generate EESCHEMA code for the schematic.
        node_to_eeschema(node)

        # Append place & route statistics for the schematic to a file.
        if options.get("collect_stats"):
            stats = node.collect_stats(**options)
            with open(options["stats_file"], "a") as f:
                f.write(stats)

        # Clean up.
        finalize_parts_and_nets(circuit, **options)

        # Place & route was successful if we got here, so exit.
        return

    # Append failed place & route statistics for the schematic to a file.
    if options.get("collect_stats"):
        stats = "-1\n"
        with open(options["stats_file"], "a") as f:
            f.write(stats)

    # Clean-up after failure.
    finalize_parts_and_nets(circuit, **options)

    # Exited the loop without successful routing.
    raise RoutingFailure
