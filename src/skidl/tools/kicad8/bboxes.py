# -*- coding: utf-8 -*-

# The MIT License (MIT) - Copyright (c) Dave Vandenbout.

"""
Calculate bounding boxes for part symbols and hierarchical sheets.
"""

from collections import namedtuple
import math
import sexpdata # Ensure sexpdata is imported if find_sexp_obj uses it

from skidl.logger import active_logger
from skidl.part import Part
from skidl.pin import Pin
from skidl.geometry import (
    BBox,
    Point,
    Tx,
    Vector,
    mils_per_mm,
    mms_per_mil,
)
from skidl.utilities import export_to_all, to_list # Keep to_list if find_sexp_obj needs it
from .constants import HIER_TERM_SIZE, PIN_LABEL_FONT_SIZE
from skidl.geometry import Segment


@export_to_all
def calc_symbol_bbox(part, options={}):
    """Calculate the bounding box for a part symbol for KiCad 8.

    Args:
        part (Part): Part.
        options (dict, optional): Dictionary of options for BBox calculation. Defaults to {}.

    Returns:
        list: List of bounding boxes for the part and its units. The first
            bounding box is for the entire part. The others are for the
            individual units of the part.
    """

    # Helper function to find a particular S-expression object type in a list of S-expressions.
    def find_sexp_obj(sexp_list, obj_type_to_find):
        # sexp_list is expected to be a list of S-expression elements, e.g. from obj (like polyline obj)
        # obj_type_to_find is a string like "pts"
        for item in sexp_list: 
            item_list = to_list(item) # Ensure item is a list
            if not item_list: continue
            if isinstance(item_list[0], sexpdata.Symbol) and item_list[0].value().lower() == obj_type_to_find:
                return item_list
        return [] # Return empty list if not found

    part_bbox = BBox()
    unit_bboxes_objects = {}

    for unit_num in part.unit.keys():
        unit_bbox = BBox()
        
        actual_draw_cmds_key = unit_num # Default assumption
        if isinstance(unit_num, str) and unit_num.startswith('u') and unit_num[1:].isalpha(): # e.g. uA, uB
             # Try to map to numeric key if draw_cmds uses that, e.g. 1 for uA
             try:
                 # This logic depends on how unit_num in draw_cmds is stored (e.g. integer 1, 2 or string '1', '2')
                 # And how Part.unit keys are (e.g. 'uA' or 1)
                 # Assuming draw_cmds might be keyed by integer unit id if Part.unit keys are like 'uA'
                 potential_numeric_key = ord(unit_num[1].upper()) - ord('A') + 1
                 if potential_numeric_key in part.draw_cmds:
                     actual_draw_cmds_key = potential_numeric_key
                 elif str(potential_numeric_key) in part.draw_cmds: # Check for stringified number
                     actual_draw_cmds_key = str(potential_numeric_key)
                 # else keep unit_num as is, hoping it's a direct key like 1, 0 etc.
             except TypeError: # unit_num is not like 'uA'
                 pass 
        elif isinstance(unit_num, int) and unit_num == 0 and 1 in part.draw_cmds and 0 not in part.draw_cmds: 
            # Special case for global common unit 0, if its draw_cmds are stored under unit 1 for single-unit parts
            # This depends on lib.py logic where a single unit might be re-assigned to unit 1.
             actual_draw_cmds_key = 1

        if actual_draw_cmds_key not in part.draw_cmds or not part.draw_cmds[actual_draw_cmds_key]:
            pass # Continue to the default bbox logic if no draw cmds
        else:
            for obj_s_expr in part.draw_cmds[actual_draw_cmds_key]:
                if not obj_s_expr or not isinstance(obj_s_expr[0], sexpdata.Symbol):
                    continue
                obj_type = obj_s_expr[0].value().lower()

                try:
                    if obj_type == "polyline":
                        pts_list = find_sexp_obj(obj_s_expr, "pts")
                        if pts_list and len(pts_list) > 1:
                            for pt_item in pts_list[1:]:
                                if pt_item and isinstance(pt_item, list) and len(pt_item) > 2 and isinstance(pt_item[0], sexpdata.Symbol) and pt_item[0].value().lower() == "xy":
                                    x, y = float(pt_item[1]), float(pt_item[2])
                                    unit_bbox.add(Point(x, y))
                    elif obj_type == "rectangle":
                        start_list = find_sexp_obj(obj_s_expr, "start")
                        end_list = find_sexp_obj(obj_s_expr, "end")
                        if start_list and len(start_list) > 2 and end_list and len(end_list) > 2:
                            xs, ys = float(start_list[1]), float(start_list[2])
                            xe, ye = float(end_list[1]), float(end_list[2])
                            unit_bbox.add(Point(xs, ys)); unit_bbox.add(Point(xe, ye))
                    elif obj_type == "circle":
                        center_list = find_sexp_obj(obj_s_expr, "center")
                        radius_list = find_sexp_obj(obj_s_expr, "radius")
                        if center_list and len(center_list) > 2 and radius_list and len(radius_list) > 1:
                            xc, yc = float(center_list[1]), float(center_list[2])
                            r = float(radius_list[1])
                            unit_bbox.add(Point(xc - r, yc - r)); unit_bbox.add(Point(xc + r, yc + r))
                    elif obj_type == "arc":
                        start_list = find_sexp_obj(obj_s_expr, "start")
                        end_list = find_sexp_obj(obj_s_expr, "end")
                        if start_list and len(start_list) > 2 and end_list and len(end_list) > 2:
                            xs, ys = float(start_list[1]), float(start_list[2])
                            xe, ye = float(end_list[1]), float(end_list[2])
                            unit_bbox.add(Point(xs,ys)); unit_bbox.add(Point(xe,ye))
                    elif obj_type == "text":
                        at_list = find_sexp_obj(obj_s_expr, "at")
                        if at_list and len(at_list) > 2:
                            x, y = float(at_list[1]), float(at_list[2])
                            text_size_approx = 1.0
                            unit_bbox.add(Point(x - text_size_approx/2, y - text_size_approx/2))
                            unit_bbox.add(Point(x + text_size_approx/2, y + text_size_approx/2))
                    elif obj_type == "pin":
                        at_list = find_sexp_obj(obj_s_expr, "at")
                        length_list = find_sexp_obj(obj_s_expr, "length")
                        if at_list and len(at_list) > 3 and length_list and len(length_list) > 1:
                            px, py, pangle = float(at_list[1]), float(at_list[2]), float(at_list[3])
                            plen = float(length_list[1])
                            pin_base_pt = Point(px, py)
                            unit_bbox.add(pin_base_pt)
                            pangle_rad = math.radians(pangle)
                            if pangle == 0:    pin_end_pt = pin_base_pt + Point(plen, 0)
                            elif pangle == 90:   pin_end_pt = pin_base_pt + Point(0, -plen)
                            elif pangle == 180:  pin_end_pt = pin_base_pt + Point(-plen, 0)
                            elif pangle == 270:  pin_end_pt = pin_base_pt + Point(0, plen)
                            else:
                                pin_end_pt = pin_base_pt + Point(plen * math.cos(pangle_rad), plen * math.sin(pangle_rad))
                            unit_bbox.add(pin_end_pt)
                except (ValueError, TypeError, IndexError) as e:
                    pass # Silently ignore parsing errors for individual elements for now
            
        if unit_bbox.min.x == float('inf'):
            unit_bbox.add(Point(0,0)); unit_bbox.add(Point(1,1))
        
        unit_bboxes_objects[unit_num] = unit_bbox
        part_bbox.add(unit_bbox)

    if part_bbox.min.x != float('inf') and part_bbox.min.y != float('inf'):
        part.bbox = part_bbox.round()
    else:
        part.bbox = BBox(Point(0,0),Point(1,1)).round()

    final_unit_bboxes_list = []
    for unit_key in part.unit.keys():
        ubox = unit_bboxes_objects.get(unit_key, BBox(Point(0,0),Point(1,1)))
        part.unit[unit_key].bbox = ubox.round()
        final_unit_bboxes_list.append(ubox.round())

    return [part.bbox] + final_unit_bboxes_list


@export_to_all
def calc_hier_label_bbox(label, dir):
    """Calculate the bounding box for a hierarchical label.

    Args:
        label (str): String for the label.
        dir (str): Orientation ("U", "D", "L", "R").

    Returns:
        BBox: Bounding box for the label and hierarchical terminal.
    """

    raise NotImplementedError

    # Rotation matrices for each direction.
    lbl_tx = {
        "U": tx_rot_90,  # Pin on bottom pointing upwards.
        "D": tx_rot_270,  # Pin on top pointing down.
        "L": tx_rot_180,  # Pin on right pointing left.
        "R": tx_rot_0,  # Pin on left pointing right.
    }

    # Calculate length and height of label + hierarchical marker.
    lbl_len = len(label) * PIN_LABEL_FONT_SIZE + HIER_TERM_SIZE
    lbl_hgt = max(PIN_LABEL_FONT_SIZE, HIER_TERM_SIZE)

    # Create bbox for label on left followed by marker on right.
    bbox = BBox(Point(0, lbl_hgt / 2), Point(-lbl_len, -lbl_hgt / 2))

    # Rotate the bbox in the given direction.
    bbox *= lbl_tx[dir]

    return bbox
