import argparse
import ast
import json
import subprocess

from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

from dataset.extract_ground_truths.effect.process_agent_patch import extract_modified_lines
from execution.monkey_patch.dataset import monkey_patch_dataset
from swebench.harness.utils import load_swebench_dataset


class _DefCollector(ast.NodeVisitor):
    """
    Collects class/function definitions with their [start, end] line ranges
    and qualnames (relative to the module).
    """

    def __init__(self) -> None:
        self.stack: List[str] = []  # name components for qualname
        # entries: (start_lineno, end_lineno, qualname)
        self.defs: List[Tuple[int, int, str]] = []

    def _record_def(self, node: ast.AST, name: str) -> None:
        qualname = ".".join(self.stack + [name]) if self.stack else name
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)
        if start is None:
            return
        if end is None:
            # Fallback if end_lineno is not present (older Python)
            end = start
        self.defs.append((start, end, qualname))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._record_def(node, node.name)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_def(node, node.name)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_def(node, node.name)
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()


def _path_to_module_name(file_path: str) -> str:
    """
    Convert a repo-relative file path like 'astropy/modeling/separable.py'
    into a module name like 'astropy.modeling.separable'.
    """
    rel = Path(file_path)
    parts = list(rel.parts)
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]  # strip .py

    parts = [p for p in parts if p]
    return ".".join(parts) if parts else "<unknown_module>"


def _find_qualname_for_line(
    defs: List[Tuple[int, int, str]], line_no: int
) -> str:
    """
    Given a list of (start, end, qualname) and a line number,
    return the innermost definition that contains the line, if any.
    """
    candidates = [
        (start, end, q)
        for (start, end, q) in defs
        if start <= line_no <= end
    ]
    if not candidates:
        return ""
    # Innermost = the one with the largest start line
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][2]


def extract_modified_qualnames(
    patch_content: str,
    repo_root: str | Path,
    mode: str = "new",
) -> List[str]:
    """
    Given a unified diff patch content and a repo root, extract the full
    qualified names ('module:qualname') of classes/functions whose bodies
    include at least one modified line.

    mode:
      - "new": use added lines and file paths from the NEW version
      - "old": use removed lines and file paths from the OLD version
    """
    mode = mode.lower()
    if mode not in {"new", "old"}:
        raise ValueError(f"Unsupported mode: {mode!r}. Use 'new' or 'old'.")

    repo_root_path = Path(repo_root)
    line_info = extract_modified_lines(patch_content)

    modified_qualnames: Set[str] = set()

    def _process(path_to_lines: Dict[str, List[int]]) -> None:
        for rel_path, lines in path_to_lines.items():
            file_on_disk = repo_root_path / rel_path
            source = file_on_disk.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(file_on_disk))

            collector = _DefCollector()
            collector.visit(tree)

            # Compute module name RELATIVE to repo_root
            try:
                rel_to_repo = file_on_disk.relative_to(repo_root_path)
            except ValueError:
                rel_to_repo = file_on_disk

            module_name = _path_to_module_name(str(rel_to_repo))

            for line_no in lines:
                local_qualname = _find_qualname_for_line(collector.defs, line_no)
                if local_qualname:
                    full_qualname = f"{module_name}:{local_qualname}"
                    modified_qualnames.add(full_qualname)
                else:
                    # Ignore module-level changes
                    pass

    if mode in {"new"}:
        _process(line_info["added"])

    if mode in {"old"}:
        _process(line_info["removed"])

    return sorted(modified_qualnames)


def ensure_repo_at_commit(
    repos_root: Path,
    repo_slug: str,
    commit: str,
    remote_base: str = "https://github.com",
) -> Path:
    """
    Ensure that the repository identified by `repo_slug` (e.g. 'astropy/astropy')
    is cloned under `repos_root` and checked out at `commit`.

    Layout on disk:
        repos_root / owner / repo_name

    Returns:
        Path to the repo directory on disk.
    """
    owner, name = repo_slug.split("/", 1)
    repo_dir = repos_root / owner / name

    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    if not repo_dir.exists():
        # Clone if repo_dir does not exist
        clone_url = f"{remote_base}/{repo_slug}.git"
        print(f"[git] Cloning {clone_url} into {repo_dir} ...")
        subprocess.run(
            ["git", "clone", clone_url, str(repo_dir)],
            check=True,
        )
    else:
        # Make sure the working tree is clean before switching commits
        print(f"[git] Cleaning existing repo at {repo_dir} ...")
        subprocess.run(
            ["git", "-C", str(repo_dir), "reset", "--hard", "HEAD"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo_dir), "clean", "-fdx"],
            check=True,
        )
        print(f"[git] Fetching updates ...")
        subprocess.run(
            ["git", "-C", str(repo_dir), "fetch", "--all", "--tags", "--prune"],
            check=True,
        )

    print(f"[git] Checking out {commit} in {repo_dir} ...")
    subprocess.run(
        ["git", "-C", str(repo_dir), "checkout", commit],
        check=True,
    )

    return repo_dir


def apply_patch_to_repo(repo_dir: Path, patch_content: str) -> None:
    """
    Apply a unified diff patch to the working tree of `repo_dir` using `git apply`.
    """
    subprocess.run(
        ["git", "-C", str(repo_dir), "apply", "--whitespace=nowarn", "-"],
        input=patch_content.encode("utf-8"),
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract modified qualnames (old+new) per agent/instance "
                    "and save to JSON."
    )

    parser.add_argument(
        "--agents",
        nargs="+",
        default=["gold"],
        help="List of agent names to process (used as top-level keys in the JSON).",
    )

    parser.add_argument(
        "--instance-ids",
        nargs="+",
        default=[
            "astropy__astropy-7166",
            "astropy__astropy-7336",
            "astropy__astropy-7671",
            "astropy__astropy-8707",
            "astropy__astropy-8872",
            "astropy__astropy-12907",
            "astropy__astropy-13033",
            "astropy__astropy-13236",
            "astropy__astropy-13398",
            "astropy__astropy-13453",
            "astropy__astropy-13579",
            "astropy__astropy-13977",
            "sympy__sympy-13615",
        ],
        help="List of instance_ids to load from the dataset.",
    )

    parser.add_argument(
        "--repos-root",
        type=Path,
        default=Path(
            "/home/yusuf/explainbench/dataset/extract_ground_truths/"
            "localization/swe_bench_repos"
        ),
        help="Root directory under which all Git repos will be cloned.",
    )

    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path(
            "/home/yusuf/explainbench/dataset/extract_ground_truths/"
            "effect/allowed_qualnames.json"
        ),
        help="Path to the output JSON file.",
    )

    args = parser.parse_args()

    AGENT_NAMES = args.agents
    INSTANCE_IDS = args.instance_ids
    REPOS_ROOT = args.repos_root
    OUTPUT_PATH = args.output_path

    # Load dataset
    monkey_patch_dataset()
    ds = load_swebench_dataset(instance_ids=INSTANCE_IDS)

    # Final structure: agent -> instance_id -> [qualnames]
    results: Dict[str, Dict[str, List[str]]] = {}

    for agent in AGENT_NAMES:
        agent_mapping: Dict[str, List[str]] = {}
        print(f"Processing agent: {agent}")
        for instance in ds:
            instance_id = instance.get("instance_id", "")
            assert instance_id, "instance_id is missing"

            repo_slug = instance["repo"]          # e.g. "astropy/astropy"
            base_commit = instance["base_commit"]
            patch_content = instance.get("patch", "")
            if not patch_content:
                print(f"[warn] No patch for {instance_id}, skipping.")
                continue

            # Ensure repo is at the base commit
            repo_dir = ensure_repo_at_commit(
                repos_root=REPOS_ROOT,
                repo_slug=repo_slug,
                commit=base_commit,
            )

            # Qualnames for old version
            old_qualnames = extract_modified_qualnames(
                patch_content=patch_content,
                repo_root=repo_dir,
                mode="old",
            )

            # Apply patch and get qualnames for new version
            apply_patch_to_repo(repo_dir, patch_content)
            new_qualnames = extract_modified_qualnames(
                patch_content=patch_content,
                repo_root=repo_dir,
                mode="new",
            )

            merged = sorted(set(old_qualnames) | set(new_qualnames))
            agent_mapping[instance_id] = merged
            print(f"  {instance_id}: {len(merged)} qualnames")

        results[agent] = agent_mapping

    # Write out the final JSON
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, sort_keys=True)

    print(f"Wrote qualnames JSON to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
