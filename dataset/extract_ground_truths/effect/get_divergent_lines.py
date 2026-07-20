"""Legacy path adapter for package-owned divergence analysis."""

import logging
from pathlib import Path

from dataset.extract_ground_truths.effect.process_agent_patch import (
    get_diff_info_per_instance,
)
from dataset.extract_ground_truths.effect.trace_util import get_trace_dir
from execution.util import get_fail_to_pass_tests
from explainbench.question_builders.local.stages.find_first_divergence import (
    find_first_divergence,
)


logger = logging.getLogger(__name__)


def main(
    instance_id,
    agent="gold",
    test_id=0,
    base_dir=None,
    depth_threshold=3,
):
    """Resolve legacy trace paths and call the canonical package algorithm."""

    trace_root = Path(base_dir or get_trace_dir(agent))
    test_name = get_fail_to_pass_tests(instance_id)[test_id]
    diff_lines = get_diff_info_per_instance(trace_root, Path(instance_id))
    instance_root = trace_root / instance_id
    return find_first_divergence(
        buggy_trace=instance_root / "buggy_traces" / f"{test_name}.jsonl",
        patched_trace=instance_root / "patched_traces" / f"{test_name}.jsonl",
        removed_lines=diff_lines.get("removed", {}),
        added_lines=diff_lines.get("added", {}),
        instance_id=instance_id,
        submission_id=agent,
        test_id=test_id,
        depth_threshold=depth_threshold,
        random_seed=42,
    )


if __name__ == "__main__":
    import sys

    logger.setLevel(logging.DEBUG)
    print(main(sys.argv[1], test_id=0, agent="gold", depth_threshold=3))
