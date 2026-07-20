"""Legacy batch wrapper for package-owned patched-function discovery."""

import argparse
import json
import subprocess
from pathlib import Path

from swebench.harness.utils import load_swebench_dataset
from tqdm.auto import tqdm

from execution.util import get_instance_ids
from explainbench.question_builders.local.stages.identify_patched_functions import (
    extract_modified_qualnames as _extract_modified_qualnames,
)


DIR = Path(__file__).parent.resolve()
LEGACY_AGENTS = [
    "gold",
    "20250603_Refact_Agent_claude-4-sonnet",
    "20250720_Lingxi-v1.5_claude-4-sonnet-20250514",
    "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct",
    "20250928_trae_doubao_seed_code",
    "20250807_mini-v1.7.0_gpt-5-mini",
    "20251127_openhands_claude-opus-4-5",
    "openhands_gpt-5-mini",
    "openhands_minimax-m2.5",
]


def extract_modified_qualnames(
    patch_content: str,
    repo_root: str | Path,
    mode: str = "new",
) -> list[str]:
    """Compatibility adapter over the canonical package implementation."""

    return _extract_modified_qualnames(
        patch_content,
        repo_root,
        version=mode,
    )


def ensure_repo_at_commit(
    repos_root: Path,
    repo_slug: str,
    commit: str,
    remote_base: str = "https://github.com",
) -> Path:
    """Prepare the legacy shared repository checkout."""

    owner, name = repo_slug.split("/", 1)
    repo_dir = repos_root / owner / name
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    if not repo_dir.exists():
        subprocess.run(
            [
                "git",
                "clone",
                f"{remote_base}/{repo_slug}.git",
                str(repo_dir),
            ],
            check=True,
        )
    else:
        subprocess.run(
            ["git", "-C", str(repo_dir), "reset", "--hard", "HEAD"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_dir), "clean", "-fdx"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_dir), "fetch", "--all", "--tags", "--prune"],
            check=True,
        )
    subprocess.run(
        ["git", "-C", str(repo_dir), "checkout", commit],
        check=True,
    )
    return repo_dir


def apply_patch_to_repo(repo_dir: Path, patch_content: str) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_dir),
            "apply",
            "--whitespace=nowarn",
            "-",
        ],
        input=patch_content.encode("utf-8"),
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy multi-agent wrapper around ExplainBench's canonical "
            "identify-patched-functions implementation."
        )
    )
    parser.add_argument("--agents", nargs="+", default=LEGACY_AGENTS)
    parser.add_argument("--instance-ids", nargs="+", default=["all"])
    parser.add_argument(
        "--repos-root",
        type=Path,
        default=DIR / "../swe_bench_repos",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DIR / "../../../execution/allowed_qualnames.json",
    )
    arguments = parser.parse_args()

    instance_ids = get_instance_ids(arguments.instance_ids)
    dataset = load_swebench_dataset(
        name="SWE-bench/SWE-bench_Verified",
        instance_ids=instance_ids,
    )
    patch_directory = DIR / "../../explanations/agent_patches"
    if arguments.output_path.exists():
        results = json.loads(arguments.output_path.read_text(encoding="utf-8"))
    else:
        results = {}
    arguments.output_path.parent.mkdir(parents=True, exist_ok=True)

    for agent in arguments.agents:
        agent_results = results.setdefault(agent, {})
        if agent == "gold":
            patch_reference = {
                record["instance_id"]: record["patch"] for record in dataset
            }
        else:
            patch_data = json.loads(
                (patch_directory / f"{agent}.json").read_text(encoding="utf-8")
            )
            if isinstance(patch_data, list):
                patch_reference = {
                    item["instance_id"]: item["model_patch"]
                    for item in patch_data
                }
            else:
                patch_reference = {
                    instance_id: record["model_patch"]
                    for instance_id, record in patch_data.items()
                }

        for record in tqdm(dataset, desc=f"Agent {agent}", unit="instance"):
            instance_id = record["instance_id"]
            if instance_id in agent_results:
                continue
            patch = patch_reference.get(instance_id)
            if not patch:
                continue
            try:
                repository = ensure_repo_at_commit(
                    arguments.repos_root,
                    record["repo"],
                    record["base_commit"],
                )
                old_functions = extract_modified_qualnames(
                    patch,
                    repository,
                    mode="old",
                )
                apply_patch_to_repo(repository, patch)
                new_functions = extract_modified_qualnames(
                    patch,
                    repository,
                    mode="new",
                )
                agent_results[instance_id] = sorted(
                    set(old_functions) | set(new_functions)
                )
                arguments.output_path.write_text(
                    json.dumps(results, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
            except Exception as error:
                print(f"[error] {agent}/{instance_id}: {error}")


if __name__ == "__main__":
    main()
