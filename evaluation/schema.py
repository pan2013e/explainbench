from typing import List
from pydantic import BaseModel

__all__ = [
    'Function',
    'File',
    'Line',
]

class Function(BaseModel):
    function: List[str]

class File(BaseModel):
    file: List[str]

class Range(BaseModel):
    start: int
    end: int

class Line(BaseModel):
    line: List[Range]
