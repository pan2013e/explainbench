import os
from pathlib import Path

from docker.models.containers import Container

from execution.pbt.util import (
    REPRODUCER_LOC,
    FullReproResult,
    setup,
    apply_patch,
    write_to_container
)

DIR = os.path.dirname(os.path.abspath(__file__))

def run_test(container: Container, test_content: str, patch: str = ""):
    write_to_container(container, test_content, Path(REPRODUCER_LOC))
    if patch != "":
        try:
            apply_patch(container, patch)
        except AssertionError:
            pass
    exit_code, response = container.exec_run(
        f"bash -c \"source ~/.bashrc && timeout 300s python {REPRODUCER_LOC}\"", workdir="/testbed"
    )
    return exit_code, response  

def evaluate_test(
    instance_id: str, 
    test_content: str, 
    distinct_id: int = 0,
    patch: str | None = None
) -> FullReproResult:
    container = None
    try:
        container, instance_info = setup(instance_id, distinct_id)
        if patch is None:
            patch = instance_info["patch"]
        assert patch is not None
        buggy_exit_code, buggy_response = run_test(container, test_content)
        try:
            fixed_exit_code, fixed_response = run_test(
                container, test_content,
                patch = patch
            )
        except AssertionError:
            fixed_exit_code = -1
            fixed_response = f"File {REPRODUCER_LOC}, line 0\nPatchApplicationFailedError".encode()
        return FullReproResult(
            buggy_stdout=buggy_response.decode(),
            buggy_stderr="",
            buggy_returncode=buggy_exit_code,
            fixed_stdout=fixed_response.decode(),
            fixed_stderr="",
            fixed_returncode=fixed_exit_code
        )
    except Exception as e:
        raise
    finally:
        if container is not None:
            container.stop()
            container.remove()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run_file")
    parser.add_argument("--instance_id")
    args = parser.parse_args()

    with open(args.run_file) as f:
        real_test = f.read()
    
    reproresult = evaluate_test(args.instance_id, real_test)
    print(reproresult)
