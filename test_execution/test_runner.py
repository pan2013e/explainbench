import os
from pathlib import Path, PurePosixPath

import docker
from docker.models.containers import Container
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
from tempfile import NamedTemporaryFile

from test_execution.util import FullReproResult

RUN_ID = "test-execution"
DIR = os.path.dirname(os.path.abspath(__file__))

def inject_file(container: Container, test_content: str, test_loc: str) -> None:
    with NamedTemporaryFile(
        buffering=0, prefix="reproducer-", suffix=".py"
    ) as f:
        f.write(test_content.encode())
        copy_to_container(container, Path(f.name), PurePosixPath(test_loc))

def run_test(container: Container, test_content: str, patch: str = ""):
    test_loc = "/testbed/reproducer.py"
    inject_file(container, test_content, test_loc)
    if patch != "":
        with NamedTemporaryFile(
            buffering=0, prefix="patch-", suffix=".patch"
        ) as patch_f:
            patch_f.write(patch.encode())
            copy_to_container(container, Path(patch_f.name), PurePosixPath("/testbed/dev_patch.patch"))
            container.exec_run("git apply dev_patch.patch", workdir="/testbed")
    exit_code, response = container.exec_run(
        f"bash -c \"source ~/.bashrc && timeout 300s python {test_loc}\"", workdir="/testbed"
    )
    return exit_code, response  


def setup(instance_id: str) -> tuple[Container, dict]:
    all_instances = load_swebench_dataset(
        instance_ids = [instance_id]
    )
    assert len(all_instances) == 1
    relevant_instance = all_instances[0]

    client = docker.from_env()
    log_dir = RUN_EVALUATION_LOG_DIR / RUN_ID / instance_id
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
        test_spec, client, RUN_ID, logger, False, False
    )
    container.start()

    # install necessaries
    container.exec_run(
        "bash -c \"source ~/.bashrc && python -m pip install hypothesis\"", workdir="/testbed"
    )
    return container, relevant_instance


def evaluate_test(
    instance_id: str, test_content: str
) -> FullReproResult:
    container = None
    try:
        container, instance_info = setup(instance_id)
        buggy_exit_code, buggy_response = run_test(container, test_content)
        fixed_exit_code, fixed_response = run_test(
            container, test_content,
            patch = instance_info["patch"]
        )
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
