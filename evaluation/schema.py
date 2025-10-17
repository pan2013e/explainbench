from typing import List, Literal
from pydantic import BaseModel

__all__ = [
    'Region',
    'File',
    'Line',
]

###### Buggy Location Schemas ######
class RegionInfo(BaseModel):
    type: Literal['class', 'function']
    identifier: str

class Region(BaseModel):
    region: List[RegionInfo]

class File(BaseModel):
    file: List[str]

###### Effect Schemas ######
class Value(BaseModel):
    value: str

class Variable(BaseModel):
    value: str