import os
import json
import atexit
import tarfile
import datasets

from functools import lru_cache
from io import RawIOBase, BufferedReader
from pathlib import PurePosixPath, Path
from datasets import load_dataset
from docker.models.containers import Container
from tracer_plugin.django_plugin import FAIL_TO_PASS_TESTS as DJANGO_FAIL_TO_PASS_TESTS

datasets.disable_progress_bars()

SWEBENCH = load_dataset("SWE-bench/SWE-bench_Verified", split="test")
DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_PATCH_DIR = os.path.join(DIR, "../dataset/explanations/agent_patches")

EXCLUDED_IDS = [
    # Whatever reasons, the offical SWE-bench test harness (Release v4.1.0)
    # reports failures on developer patches (without tracker/tracer injected)
    "astropy__astropy-7606",
    "astropy__astropy-8707",
    "astropy__astropy-8872",
    "django__django-10097",
    "psf__requests-1724",
    "psf__requests-1766",
    "psf__requests-1921",
    "psf__requests-2317",
    "pylint-dev__pylint-6528",
    "pylint-dev__pylint-7277",
    "sphinx-doc__sphinx-8595",
    "sphinx-doc__sphinx-8621",
    "sphinx-doc__sphinx-9711",
    # Tests consume ~100% CPU resources, making concurrent
    # tests/docker operations in other containers timeout
    "scikit-learn__scikit-learn-14710",
    # For patched code, tests fail before test function is even reached
    # In other words, call stack does not include test function
    "django__django-14011",
    "django__django-14672",
    "django__django-16116",
    "pylint-dev__pylint-4551",
    "pylint-dev__pylint-4604",
    "pylint-dev__pylint-4661",
    # Intrusiveness of tracker/injection plugin causes incorrect patched behavior (should pass, but failed)
    "astropy__astropy-13398",
    "django__django-11276",
    "pytest-dev__pytest-5631",
    "pytest-dev__pytest-5787",
    "pytest-dev__pytest-6197",
    "pytest-dev__pytest-6202",
    "sphinx-doc__sphinx-10435",
    "sphinx-doc__sphinx-10614",
    "sphinx-doc__sphinx-8120",
    "sphinx-doc__sphinx-8721",
    "sphinx-doc__sphinx-9229",
    # Intrusiveness of tracer/serializer causes incorrect patched behavior (should pass, but failed)
    "django__django-11066",
    "django__django-11087",
    "django__django-11265",
    "django__django-11734",
    "django__django-11885",
    "django__django-11951",
    "django__django-12419",
    "django__django-12965",
    "django__django-13028",
    "django__django-13128",
    "django__django-13158",
    "django__django-13406",
    "django__django-13590",
    "django__django-13658",
    "django__django-15128",
    "django__django-15280",
    "django__django-15554",
    "django__django-15957",
    "django__django-16032",
    "django__django-16255",
    "django__django-16263",
    "matplotlib__matplotlib-14623",
    "matplotlib__matplotlib-20488",
    "matplotlib__matplotlib-23314",
    "matplotlib__matplotlib-23412",
    "matplotlib__matplotlib-24026",
    "matplotlib__matplotlib-24149",
    "matplotlib__matplotlib-24870",
    "matplotlib__matplotlib-25311",
    "matplotlib__matplotlib-25332",
    "matplotlib__matplotlib-25775",
    "matplotlib__matplotlib-26113",
    "matplotlib__matplotlib-26342",
    "matplotlib__matplotlib-26466",
    "pytest-dev__pytest-8399",
    "scikit-learn__scikit-learn-12682",
    "sphinx-doc__sphinx-8056",
    # Intrusiveness of tracer/serializer causes incorrect buggy behavior (should fail, but passed)
    "django__django-14351",
    # Intrusiveness of tracer/serializer causes pipeline errors
    "astropy__astropy-14539",
    "django__django-11149",
    "django__django-11400",
    "django__django-11749",
    "django__django-12143",
    "django__django-13417",
    "matplotlib__matplotlib-20826",
    "matplotlib__matplotlib-20859",
    # Timeout after 6h
    "django__django-14559",
    "django__django-15022",
    "sympy__sympy-15599",
    # Use of internal context manager in `self.subTest` or `self.assertNumQueries` causes exceptions not raised in test functions
    "django__django-11451",
    "django__django-11964",
    "django__django-14792",
    "django__django-14999",
    "django__django-15561",
    "django__django-16429"
]

class _IterableReader(RawIOBase):
    def __init__(self, iterable):
        self._iter = iter(iterable)
        self._leftover = b""
    
    def readable(self):
        return True
    
    def readinto(self, b):
        view = memoryview(b)
        written = 0
        while written < len(b):
            if not self._leftover:
                try:
                    self._leftover = next(self._iter)
                except StopIteration:
                    break
            n = min(len(self._leftover), len(b) - written)
            view[written:written + n] = self._leftover[:n]
            self._leftover = self._leftover[n:]
            written += n
            if written:
                break
        return written

def get_tmp_tracer_path():
    return f'/tmp/py-tracer.{os.getpid()}.tar'

def prepare_tracer():
    src = Path(f"{DIR}/../py-tracer")
    dst = PurePosixPath('/root/py-tracer')
    tmp_dir = get_tmp_tracer_path()
    if os.path.exists(tmp_dir):
        try:
            os.unlink(tmp_dir)
        except Exception:
            pass
    with tarfile.open(tmp_dir, 'w') as tar:
        tar.add(src, arcname=dst.name)
    atexit.register(lambda: os.unlink(tmp_dir) if os.path.exists(tmp_dir) else None)

def copy_directory_from_docker(container: Container, src_path: PurePosixPath, dst_path: Path):
    target_path = dst_path / src_path.name
    target_path.mkdir(parents=True, exist_ok=True)
    exec_result = container.exec_run(
        ["tar", "-C", str(src_path), "-czf", "-", "."],
        stream=True,
    )
    reader = BufferedReader(_IterableReader(exec_result.output))
    with tarfile.open(fileobj=reader, mode="r|gz") as tar:
        tar.extractall(path=target_path)

@lru_cache
def get_fail_to_pass_tests(instance_id: str) -> list[str] | str:
    # Patch the errors in SWE-bench dataset
    if instance_id == "sphinx-doc__sphinx-8265":
        return ["tests/test_pycode_ast.py::test_unparse[(1, 2, 3)-(1, 2, 3)]"]
    if 'django__django' in instance_id:
        return DJANGO_FAIL_TO_PASS_TESTS[instance_id]
    instance = SWEBENCH.filter(lambda x: x['instance_id'] == instance_id)[0]
    return json.loads(instance['FAIL_TO_PASS'])

@lru_cache
def get_test_patch(instance_id: str) -> str:
    instance = SWEBENCH.filter(lambda x: x['instance_id'] == instance_id)[0]
    return instance['test_patch'] or ""

def get_instance_ids(value: list[str], apply_exclusions=True) -> list[str]:
    if value == ["all"]:
        return all_instances(apply_exclusions=apply_exclusions)
    if all('__' not in v and '-' not in v for v in value):
        return instances_by_repo(value, apply_exclusions=apply_exclusions)
    return value

def all_instances(apply_exclusions=True):
    exclusion = EXCLUDED_IDS if apply_exclusions else []
    return [data['instance_id'] for data in SWEBENCH if data['instance_id'] not in exclusion]

def instances_by_repo(repo_name: str | list[str], apply_exclusions=True):
    if isinstance(repo_name, str):
        repo_name = [repo_name]
    exclusion = EXCLUDED_IDS if apply_exclusions else []
    return [
        data['instance_id']
        for data in SWEBENCH
        if any(rn in data['repo'] for rn in repo_name)
        and data['instance_id'] not in exclusion
    ]

def get_predictions_path(agent: str):
    if agent == "gold":
        return "gold"
    return os.path.join(AGENT_PATCH_DIR, f"{agent}.json")
