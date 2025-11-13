import tarfile

from enum import Enum
from io import BytesIO
from pathlib import PurePosixPath, Path
from docker.models.containers import Container

def copy_directory_from_docker(container: Container, src_path: PurePosixPath, dst_path: Path):
    tar_stream, _ = container.get_archive(str(src_path))
    file_content = b""
    for chunk in tar_stream:
        file_content += chunk
    with tarfile.open(fileobj=BytesIO(file_content)) as tar:
        tar.extractall(path=dst_path)

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