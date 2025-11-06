from typing import Callable, Iterable, Optional, TypeVar
from difflib import SequenceMatcher

T = TypeVar('T')

def common_prefix_length(seq_a: Iterable[T], seq_b: Iterable[T]):
    for idx, (a, b) in enumerate(zip(seq_a, seq_b)):
        if a != b:
            return idx
    return min(len(seq_a), len(seq_b))

def sequence_match(
    seq_a: Iterable[T], seq_b: Iterable[T],
    key: Optional[Callable[[T], str]] = None
):
    if key:
        a_cmp = [key(item) for item in seq_a]
        b_cmp = [key(item) for item in seq_b]
    else:
        a_cmp = list(seq_a)
        b_cmp = list(seq_b)

    cpl = common_prefix_length(a_cmp, b_cmp)
    pairs = [(i, i) for i in range(cpl)]
    sm = SequenceMatcher(None, a_cmp[cpl:], b_cmp[cpl:], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for k in range(i2 - i1):
                pairs.append((cpl + i1 + k, cpl + j1 + k))
    return pairs
