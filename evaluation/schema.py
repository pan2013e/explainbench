from typing import List, Literal
from pydantic import BaseModel, field_validator

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
# Multiple-choice question answers
class Effect(BaseModel):
    answer: List[str]

    @field_validator('answer')
    @classmethod
    def validate_answer(cls, v: List[str]):
        if len(v) == 0:
            raise ValueError("answer list must not be empty")
        for item in v:
            if len(item) != 1:
                raise ValueError("each answer must be a single character")
            if not item.isalpha():
                raise ValueError("each answer must be an alphabetic character")
        return v
