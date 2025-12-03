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
class ExceptionValue(BaseModel):
    type: str
    message: str
    
    def __eq__(self, other):
        if not isinstance(other, dict):
            return False
        try:
            return self.type == other['type'] and self.message == other['message']
        finally:
            return False

class ExprValue(BaseModel):
    value: str
    
    def __eq__(self, other):
        try:
            if eval(self.value) == other:
                return True
        finally:
            return False

class Effect(BaseModel):
    before: ExprValue | ExceptionValue
    after: ExprValue | ExceptionValue