import tarfile

from enum import Enum
import io, tarfile
from io import BytesIO
from pathlib import PurePosixPath, Path
import docker
from docker.models.containers import Container
from tempfile import NamedTemporaryFile

from swebench.harness.constants import (
    LOG_INSTANCE,
    RUN_EVALUATION_LOG_DIR,
)
from swebench.harness.test_spec.test_spec import make_test_spec
from swebench.harness.docker_utils import (
    copy_to_container,
    exec_run_with_timeout
)
from swebench.harness.docker_build import (
    build_container,
    setup_logger,
)
from swebench.harness.utils import load_swebench_dataset

RUN_ID = "test-execution"
REPRODUCER_LOC = "/testbed/reproducer.py"

def setup(instance_id: str, distinct_id: int) -> tuple[Container, dict]:
    local_run_id = f"{RUN_ID}.{distinct_id}"
    all_instances = load_swebench_dataset(
        instance_ids = [instance_id]
    )
    assert len(all_instances) == 1
    relevant_instance = all_instances[0]

    client = docker.from_env()
    log_dir = RUN_EVALUATION_LOG_DIR / local_run_id / instance_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_INSTANCE
    logger = setup_logger(instance_id, log_file)
    test_spec = make_test_spec(
        relevant_instance,
        namespace="swebench",
        instance_image_tag="latest",
        env_image_tag="latest",
    )
    container = build_container(
        test_spec, client, local_run_id, logger, False, False
    )
    container.start()

    # install necessaries
    container.exec_run(
        "bash -c \"source ~/.bashrc && python -m pip install hypothesis\"", workdir="/testbed"
    )
    return container, relevant_instance

def copy_directory_from_docker(container: Container, src_path: PurePosixPath, dst_path: Path):
    tar_stream, _ = container.get_archive(str(src_path))
    file_content = b""
    for chunk in tar_stream:
        file_content += chunk
    with tarfile.open(fileobj=BytesIO(file_content)) as tar:
        tar.extractall(path=dst_path)

def read_from_container(container: Container, pathname: str) -> str:
    abs_pathname = "/testbed/" + pathname
    stream, stat = container.get_archive(abs_pathname)

    file_like = io.BytesIO(b"".join(stream))
    with tarfile.open(fileobj=file_like) as tar:
        member = tar.getmembers()[0]
        file_content = tar.extractfile(member).read().decode("utf-8")
    return file_content

def write_to_container(container: Container, content: str, pathname: Path) -> None:
    with NamedTemporaryFile(buffering=0) as f:
        f.write(content.encode())
        copy_to_container(container, Path(f.name), pathname)

def apply_patch(container: Container, patch_content: str) -> None:
    with NamedTemporaryFile(
        buffering=0, prefix="patch-", suffix=".patch"
    ) as patch_f:
        patch_f.write(patch_content.encode())
        copy_to_container(container, Path(patch_f.name), PurePosixPath("/testbed/dev_patch.patch"))
        exit_code, _ = container.exec_run("git apply dev_patch.patch", workdir="/testbed")
        assert exit_code == 0

class ReproStatus(Enum):
    REPRODUCED = "reproduced"
    PASS_IN_BUGGY = "pass_in_buggy"
    FAIL_IN_FIXED = "fail_in_fixed"

class FullReproResult:
    reproduced: bool
    buggy_stdout: str
    buggy_stderr: str
    fixed_stdout: str
    fixed_stderr: str
    buggy_returncode: int
    fixed_returncode: int

    def __init__(
        self,
        buggy_stdout: str,
        buggy_stderr: str,
        buggy_returncode: int,
        fixed_stdout: str,
        fixed_stderr: str,
        fixed_returncode: int,
    ) -> None:
        self.buggy_stdout = buggy_stdout
        self.buggy_stderr = buggy_stderr
        self.buggy_returncode = buggy_returncode
        self.fixed_stdout = fixed_stdout
        self.fixed_stderr = fixed_stderr
        self.fixed_returncode = fixed_returncode
        self.reproduced = (
            buggy_returncode != 0
            and fixed_returncode == 0
        )
    
    @property
    def failure_case(self) -> ReproStatus:
        if self.reproduced:
            return ReproStatus.REPRODUCED
        elif self.buggy_returncode == 0:
            return ReproStatus.PASS_IN_BUGGY
        elif self.fixed_returncode != 0:
            return ReproStatus.FAIL_IN_FIXED
        else:
            raise ValueError("This should not happen")
    
    def __str__(self) -> str:
        return "\n".join(
            [
                f"Reproduced: {self.reproduced}",
                "",
                "Buggy Stdout:",
                self.buggy_stdout,
                "",
                "Buggy Stderr:",
                self.buggy_stderr,
                "",
                "Fixed Stdout:",
                self.fixed_stdout,
                "",
                "Fixed Stderr:",
                self.fixed_stderr,
            ]
        )