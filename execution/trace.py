import os
import sys

from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from pathlib import Path
from swebench.harness.run_evaluation import main as run_evaluation_main
from swebench.harness.constants import RUN_EVALUATION_LOG_DIR

from execution.monkey_patch.trace import (
    get_active_container_aggregate,
    get_run_completion,
    monkey_patch_execution,
)
from execution.resource_monitor import (
    RUN_RESOURCE_FILENAME,
    RunResourceConfig,
    RunResourceMonitor,
    collect_docker_metadata,
)
from execution.util import prepare_tracer, get_instance_ids, get_predictions_path


TRACE_TIMEOUT_SECONDS = 21600


def _positive_float(value):
    parsed = float(value)
    if parsed <= 0:
        raise ValueError("must be greater than zero")
    return parsed


def main(**kwargs):
    instance_ids = get_instance_ids(kwargs["instance_ids"])
    run_id = f"trace.{kwargs['agent']}.{os.getuid()}"
    resource_monitoring = not kwargs.get("disable_resource_monitoring", False)
    sample_interval = kwargs.get("resource_sample_interval", 1.0)

    docker_metadata = None
    docker_metadata_errors = []
    if resource_monitoring:
        docker_metadata, docker_metadata_errors = collect_docker_metadata()

    monkey_patch_execution(
        agent=kwargs["agent"],
        resource_monitoring=resource_monitoring,
        resource_sample_interval=sample_interval,
        cgroup_version=(
            docker_metadata.get("cgroup_version", "unknown")
            if docker_metadata is not None
            else "unknown"
        ),
    )

    run_kwargs = {
        "dataset_name": "SWE-bench/SWE-bench_Verified",
        "split": "test",
        "instance_ids": instance_ids,
        "predictions_path": get_predictions_path(kwargs["agent"]),
        "max_workers": kwargs["max_workers"],
        "force_rebuild": False,
        "cache_level": "env",
        "clean": False,
        "open_file_limit": 4096,
        "run_id": run_id,
        "timeout": TRACE_TIMEOUT_SECONDS,
        "namespace": "swebench",
        "rewrite_reports": False,
        "modal": False,
        "instance_image_tag": "latest",
        "env_image_tag": "latest",
        "report_dir": ".",
    }

    if not resource_monitoring:
        prepare_tracer()
        return run_evaluation_main(**run_kwargs)

    run_output_dir = Path(RUN_EVALUATION_LOG_DIR) / run_id
    monitor = RunResourceMonitor(
        config=RunResourceConfig(
            run_id=run_id,
            agent=kwargs["agent"],
            instance_selection=kwargs["instance_ids"],
            resolved_instance_ids=instance_ids,
            max_workers=kwargs["max_workers"],
            timeout_seconds=TRACE_TIMEOUT_SECONDS,
            cache_state=kwargs.get("resource_cache_state", "unknown"),
        ),
        output_path=run_output_dir / RUN_RESOURCE_FILENAME,
        trace_output_path=run_output_dir,
        interval_seconds=sample_interval,
        container_aggregate_provider=get_active_container_aggregate,
        docker_metadata=docker_metadata,
        docker_metadata_errors=docker_metadata_errors,
    )
    monitor_started = False
    try:
        monitor.start()
        monitor_started = True
    except Exception as error:
        print(f"Resource monitoring could not start: {error}", file=sys.stderr)

    try:
        prepare_tracer()
        result = run_evaluation_main(**run_kwargs)
    except BaseException as error:
        if monitor_started:
            run_state = (
                "interrupted"
                if isinstance(error, (KeyboardInterrupt, SystemExit))
                else "failed"
            )
            try:
                monitor.stop(get_run_completion(run_state))
            except Exception as monitor_error:
                print(
                    f"Resource monitoring could not finalize: {monitor_error}",
                    file=sys.stderr,
                )
        raise
    else:
        if monitor_started:
            try:
                monitor.stop(get_run_completion())
            except Exception as error:
                print(f"Resource monitoring could not finalize: {error}", file=sys.stderr)
        return result

if __name__ == "__main__":
    parser = ArgumentParser(
        description="Run evaluation harness for the given dataset and predictions.",
        formatter_class=ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-i",
        "--instance_ids",
        nargs="+",
        type=str,
        help="Instance IDs to run (space separated) - 'all' for all instances; repo name(s) for all instances in the repo(s); or specific instance IDs",
    )
    parser.add_argument(
        "--agent",
        type=str,
        help="Agent submission ID - if 'gold', uses gold predictions",
        required=True,
    )
    parser.add_argument(
        "--max_workers",
        type=int,
        default=4,
        help="Maximum number of workers (should be <= 75%% of CPU cores)",
    )
    parser.add_argument(
        "--resource-sample-interval",
        type=_positive_float,
        default=1.0,
        help="Seconds between host and container resource samples",
    )
    parser.add_argument(
        "--resource-cache-state",
        choices=("cold", "warm", "mixed", "unknown"),
        default="unknown",
        help="Controlled Docker cache state for capacity benchmark metadata",
    )
    parser.add_argument(
        "--disable-resource-monitoring",
        action="store_true",
        help="Run tracing without writing resource usage records",
    )
    args = parser.parse_args()
    main(**vars(args))
