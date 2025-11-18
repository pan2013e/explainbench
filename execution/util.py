import os
import json
import atexit
import tarfile
import datasets

from io import BytesIO
from pathlib import PurePosixPath, Path
from datasets import load_dataset
from docker.models.containers import Container
from tracer_plugin.django_plugin import FAIL_TO_PASS_TESTS as DJANGO_FAIL_TO_PASS_TESTS

datasets.disable_progress_bars()

SWEBENCH = load_dataset("SWE-bench/SWE-bench_Verified", split="test")
DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_PATCH_DIR = os.path.join(DIR, "../dataset/explanations/agent_patches")

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
    tar_stream, _ = container.get_archive(str(src_path))
    file_content = b""
    for chunk in tar_stream:
        file_content += chunk
    with tarfile.open(fileobj=BytesIO(file_content)) as tar:
        tar.extractall(path=dst_path)

def get_fail_to_pass_tests(instance_id: str) -> list[str] | str:
    if 'django__django' in instance_id:
        return DJANGO_FAIL_TO_PASS_TESTS[instance_id]
    instance = SWEBENCH.filter(lambda x: x['instance_id'] == instance_id)[0]
    tests = json.loads(instance['FAIL_TO_PASS'])
    if 'sympy__sympy' in instance_id:
        return ' or '.join(tests)
    return tests

def get_instance_ids(value: list[str]) -> list[str]:
    if value == ["all"]:
        return all_instances()
    if all('__' not in v and '-' not in v for v in value):
        return instances_by_repo(value)
    return value

def all_instances():
    return [data['instance_id'] for data in SWEBENCH]

def instances_by_repo(repo_name: str | list[str]):
    if isinstance(repo_name, str):
        repo_name = [repo_name]
    return [
        data['instance_id']
        for data in SWEBENCH
        if any(rn in data['repo'] for rn in repo_name) and data['instance_id'] != 'astropy__astropy-7606'
    ]

def get_predictions_path(agent: str):
    if agent == "gold":
        return "gold"
    return os.path.join(AGENT_PATCH_DIR, f"{agent}.json")
