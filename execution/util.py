import json
import tarfile

from io import BytesIO
from pathlib import PurePosixPath, Path
from datasets import load_dataset
from docker.models.containers import Container

SWEBENCH = load_dataset("SWE-bench/SWE-bench_Verified", split="test")

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
