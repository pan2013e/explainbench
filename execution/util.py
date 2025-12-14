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
    "astropy__astropy-7606",
    "astropy__astropy-8707",
    "django__django-10097",
    "psf__requests-1724",
    "psf__requests-1766",
    "psf__requests-1921",
    "psf__requests-2317",
    "pylint-dev__pylint-6528",
    "pylint-dev__pylint-7277",
    "scikit-learn__scikit-learn-14710",
    "sphinx-doc__sphinx-8595",
    "sphinx-doc__sphinx-9711",
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
    if 'django__django' in instance_id:
        return DJANGO_FAIL_TO_PASS_TESTS[instance_id]
    instance = SWEBENCH.filter(lambda x: x['instance_id'] == instance_id)[0]
    return json.loads(instance['FAIL_TO_PASS'])

@lru_cache
def get_test_patch(instance_id: str) -> str:
    instance = SWEBENCH.filter(lambda x: x['instance_id'] == instance_id)[0]
    return instance['test_patch'] or ""

def get_instance_ids(value: list[str]) -> list[str]:
    if value == ["all"]:
        return all_instances()
    if all('__' not in v and '-' not in v for v in value):
        return instances_by_repo(value)
    return value

def all_instances():
    return [data['instance_id'] for data in SWEBENCH if data['instance_id'] not in EXCLUDED_IDS]

def instances_by_repo(repo_name: str | list[str]):
    if isinstance(repo_name, str):
        repo_name = [repo_name]
    return [
        data['instance_id']
        for data in SWEBENCH
        if any(rn in data['repo'] for rn in repo_name)
        and data['instance_id'] not in EXCLUDED_IDS
    ]

def get_predictions_path(agent: str):
    if agent == "gold":
        return "gold"
    return os.path.join(AGENT_PATCH_DIR, f"{agent}.json")
