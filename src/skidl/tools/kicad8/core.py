from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Union, Literal
from uuid import UUID, uuid4
from enum import Enum
import re

class Serializable(ABC):
    @abstractmethod
    def __str__(self) -> str:
        raise NotImplementedError()

@dataclass
class Color(Serializable):
    r: int
    g: int
    b: int
    alpha: Optional[int]
   
    def __str__(self) -> str:
        return f'(color {self.r} {self.g} {self.b} {self.alpha or ''})'

@dataclass
class Point(Serializable):
    x: float
    y: float
    
    def __str__(self) -> str:
        return f'(xy {self.x} {self.y})'

@dataclass    
class Position(Point, Serializable):
    angle: Optional[float]
    
    def __str__(self) -> str:
        angle = self.angle if self.angle is not None else 0
        return f'(at {self.x} {self.y} {angle})'
  
@dataclass  
class SList[T: Serializable](Serializable):
    elements: list[T]
    
    def __str__(self) -> str:
        point_list = '\n'.join(str(element) for element in self.elements)
        return f'({point_list})'

   
@dataclass 
class PointList(Serializable):
    points: list[Point]
    
    def __str__(self) -> str:
        point_list = '\n'.join(str(point) for point in self.points)
        return f'(pts {point_list})'

class StrokeType(Enum):
    DASH = 'dash'
    DASH_DOT = 'dash_dot'
    DASH_DOT_DOT = 'dash_dot_dot'
    DOT = 'dot'
    DEFAULT = 'default'
    SOLID = 'solid'
    
    def __str__(self) -> str:
        return self.value


@dataclass 
class Stroke(Serializable):
    width: float
    stroke_type: StrokeType
    color: Color
    
    def __str__(self) -> str:
        return f'(stroke (width {self.width}) (type {self.stroke_type}) {self.color})'
    
@dataclass
class Size(Serializable):
    x: float
    y: float
    
    def __str__(self) -> str:
        return f'(size {self.x} {self.y})'

class UniversallyUniqueIdentifier(Serializable):
    uuid: UUID
    
    def __init__(self, uuid: Optional[UUID]) -> None:
        if uuid is None:
            self.uuid = uuid4()
        else:
            self.uuid = uuid
    
    
    def __str__(self) -> str:
        return f'(uuid {str(self.uuid)})'
   
@dataclass 
class Junction(Serializable):
    position: Position
    color: Color
    unique_identifier: UniversallyUniqueIdentifier
    diameter: Optional[int] = None
    
    def __str__(self) -> str:
        return f'(junction {self.position} (diameter {self.diameter or 0}) {self.color} {self.unique_identifier})'
   
@dataclass 
class NoConnect(Serializable):
    position: Position
    unique_identifier: UniversallyUniqueIdentifier
    
    def __str__(self) -> str:
        return f'(no_connect {self.position} {self.unique_identifier})'
    
@dataclass
class BusEntry(Serializable):
    position: Position
    size: Size
    stroke: Stroke
    unique_identifier: UniversallyUniqueIdentifier
    
    def __str__(self) -> str:
        return f'(bus_entry {self.position} {self.size} {self.unique_identifier})'
    

@dataclass
class Wire(Serializable):
    point_list: PointList
    stroke: Stroke
    unique_identifier: UniversallyUniqueIdentifier
    
    def __str__(self) -> str:
        return f'(wire {self.point_list} {self.stroke} {self.unique_identifier})'

@dataclass 
class Bus(Serializable):
    point_list: PointList
    stroke: Stroke
    unique_identifier: UniversallyUniqueIdentifier
    
    def __str__(self) -> str:
        return f'(bus {self.point_list} {self.stroke} {self.unique_identifier})'
    
    
"""
Image Section belongs here
"""

@dataclass
class Polyline(Serializable):
    point_list: PointList
    stroke: Stroke
    unique_identifier: UniversallyUniqueIdentifier
    
    def __str__(self) -> str:
        return f'(polyline {self.point_list} {self.stroke} {self.unique_identifier})'
   
@dataclass
class Font(Serializable):
    size: tuple[float, float]
    face: Optional[str] = None
    thickness: Optional[float] = None
    line_spacing: Optional[float] = None
    bold: bool = False
    italic: bool = False
    
    def __str__(self) -> str:
        face = f'\n\t\t\t\t\t(face {self.face})' if self.face is not None else ''
        thickness = f'\n\t\t\t\t\t(thickness {self.thickness})' if self.thickness is not None else ''
        bold = '\n\t\t\t\t\tbold' if self.bold else ''
        italic = '\n\t\t\t\t\titalic' if self.italic else ''
        line_spacing = f'\n\t\t\t\t\t(line_spacing {self.line_spacing})' if self.line_spacing is not None else ''
        
        return f'(font{face}\n\t\t\t\t\t(size {self.size[0]} {self.size[1]}){thickness}{bold}{italic}{line_spacing}\n\t\t\t\t)'
 
@dataclass 
class Justify(Serializable):
    class Horizontally(Enum):
        LEFT = 'left'
        RIGHT = 'right'

    class Vertically(Enum):
        TOP = 'top'
        BOTTOM = 'bottom'
        
    horizontally: Optional[Horizontally] = None
    vertically: Optional[Vertically] = None
    mirror: bool = False
    
    def __str__(self) -> str:
        horizontally = f' {self.horizontally.value}' if self.horizontally is not None else '' 
        vertically = f' {self.vertically.value}' if self.vertically is not None else ''
        mirror = ' mirror' if self.mirror else ''
        return f'(justify{horizontally}{vertically}{mirror})'
  
@dataclass 
class TextEffects(Serializable):
    font: Font
    justify: Optional[Justify] = None
    hide: bool = False
    
    def __str__(self) -> str:
        justify = f'\n\t\t\t\t{self.justify}' if self.justify is not None else ''
        hide = '\n\t\t\t\t(hide yes)' if self.hide else ''
        return f'(effects\n\t\t\t\t{self.font}{justify}{hide}\n\t\t\t)'
    
@dataclass
class Text(Serializable):
    text: str
    position: Position
    effects: TextEffects
    unique_identifier: UniversallyUniqueIdentifier
    
    def __str__(self) -> str:
        return f'(text "{re.escape(self.text)}" {self.position} {self.effects} {self.unique_identifier})'
   
@dataclass 
class Label(Serializable):
    text: str
    position: Position
    effects: TextEffects
    unique_identifier: UniversallyUniqueIdentifier 
    
    def __str__(self) -> str:
        return f'(label "{re.escape(self.text)}" {self.position} {self.effects} {self.unique_identifier})'
    
@dataclass
class GlobalLabel(Serializable):
    text: str
    position: Position
    effects: TextEffects
    unique_identifier: UniversallyUniqueIdentifier
    
    def __str__(self) -> str:
        return f'(global_label "{re.escape(self.text)}" {self.position} {self.effects} {self.unique_identifier})'
   
@dataclass 
class HierarchicalLabel(Serializable):
    text: str
    position: Position
    effects: TextEffects
    unique_identifier: UniversallyUniqueIdentifier
    
    def __str__(self) -> str:
        return f'(hierarchical_label "{re.escape(self.text)}" {self.position} {self.effects} {self.unique_identifier})'
    
@dataclass 
class Property(Serializable):
    key: str
    value: str
    id: int
    position: Position
    effects: TextEffects
    
    def __str__(self) -> str:
        return f'\t\t(property "{self.key}" "{self.value}"\n\t\t\t{self.position}\n\t\t\t{self.effects}\n\t\t)'
    
@dataclass
class Project(Serializable):
    name: str
    path: str
    reference: str
    unit: int
    
    def __str__(self) -> str:
        return f'(project "{self.name}" (path "{self.path}" (reference "{self.reference}") (unit {self.unit})))'
    
@dataclass
class Symbol(Serializable):
    library_identifier: str
    position: Position
    unit: str
    in_bom: bool
    on_board: bool
    unique_identifier: UniversallyUniqueIdentifier
    properties: SList[Property]
    instances: SList[Project]
    
    def __str__(self) -> str:
        in_bom = 'yes' if self.in_bom else 'no'
        on_board = 'yes' if self.on_board else 'no'
        exclude_from_sim = 'no'  # Default value
        dnp = 'no'  # Default value
        fields_autoplaced = 'yes'  # Default value
        
        # Format properties properly
        properties_str = ""
        if self.properties and self.properties.elements:
            for prop in self.properties.elements:
                properties_str += f"\t\t{prop}\n"
        
        # Format instances properly  
        instances_str = ""
        if self.instances and self.instances.elements:
            for instance in self.instances.elements:
                instances_str += f"\t\t\t{instance}\n"
        
        return f"""\t(symbol
\t\t(lib_id "{self.library_identifier}")
\t\t{self.position}
\t\t(unit {self.unit})
\t\t(exclude_from_sim {exclude_from_sim})
\t\t(in_bom {in_bom})
\t\t(on_board {on_board})
\t\t(dnp {dnp})
\t\t(fields_autoplaced {fields_autoplaced})
\t\t{self.unique_identifier}
{properties_str}\t\t(instances
{instances_str}\t\t)
\t)"""