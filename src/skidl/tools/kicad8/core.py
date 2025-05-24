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
        return f'(at {self.x} {self.y} {self.angle or ''})'
  
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
        face = f'(face {self.face})' if not self.face is None else ''
        thickness = f'(thickness {self.thickness})' if not self.thickness is None else ''
        bold = 'bold' if self.bold else ''
        italic = 'italic' if self.italic else ''
        line_spacing = f'(line_spacing {self.line_spacing})' if not self.line_spacing is None else ''
        
        return f'(font {face} (size {self.size[0]} {self.size[1]}) {thickness} {bold} {italic} {line_spacing})'
 
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
        horizontally = self.horizontally.value if not self.horizontally is None else '' 
        vertically = self.vertically.value if not self.vertically is None else ''
        mirror = 'mirror' if self.mirror else ''
        return f'(justify {horizontally} {vertically} {mirror})'
  
@dataclass 
class TextEffects(Serializable):
    font: Font
    justify: Optional[Justify] = None
    hide: bool = False
    
    def __str__(self) -> str:
        justify = str(self.justify) if not self.justify is None else ''
        hide = 'hide' if not self.hide is None else ''
        return f'(effects {self.font} {justify} {hide})'
    
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
    """
    TODO
    """
   
@dataclass 
class HierarchicalLabel(Serializable):
    """
    TODO
    """
   
@dataclass 
class Property(Serializable):
    key: str
    value: str
    id: int
    position: Position
    effects: TextEffects
    
    def __str__(self) -> str:
        return f'(property "{re.escape(self.key)}" "{re.escape(self.value)}" (id {self.id}) {self.position} {self.effects})'
    
@dataclass
class Project(Serializable):
    name: str
    path: str
    reference: str
    unit: int
    
    def __str__(self) -> str:
        return f'(project "{re.escape(self.name)}" (path "{re.escape(self.path)}" (reference "{re.escape(self.reference)}") (unit {self.unit})))'
    
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
        
        return f'''
        (symbol
            "{re.escape(self.library_identifier)}"
            {self.position}
            (unit {self.unit})
            (in_bom {in_bom})
            (on_board {on_board})
            {self.unique_identifier}
            {self.properties}
            (pin "1" (uuid e148648c-6605-4af1-832a-31eaf808c2f8))    
            (instances
                {self.instances}
            )
        )
        '''
        pass