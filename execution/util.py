import os
import json
import atexit
import tarfile
import datasets

from io import BytesIO
from pathlib import PurePosixPath, Path
from datasets import load_dataset
from docker.models.containers import Container

datasets.disable_progress_bars()

SWEBENCH = load_dataset("SWE-bench/SWE-bench_Verified", split="test")
DIR = os.path.dirname(os.path.abspath(__file__))

def prepare_tracer():
    src = Path(f"{DIR}/../py-tracer")
    dst = PurePosixPath('/root/py-tracer')
    tmp_dir = f'/tmp/py-tracer.tar'
    if os.path.exists(tmp_dir):
        os.unlink(tmp_dir)
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

def get_fail_to_pass_tests(instance_id: str) -> list[str]:
    instance = SWEBENCH.filter(lambda x: x['instance_id'] == instance_id)[0]
    return json.loads(instance['FAIL_TO_PASS'])

def all_instances():
    return [data['instance_id'] for data in SWEBENCH]

def instances_by_repo(repo_name: str | list[str]):
    if isinstance(repo_name, str):
        repo_name = [repo_name]
    return [
        data['instance_id']
        for data in SWEBENCH
        if any(rn in data['repo'] for rn in repo_name)
    ]
