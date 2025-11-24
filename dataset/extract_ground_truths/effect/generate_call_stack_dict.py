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

    This is a heuristic to match the module name used by your tracer.
    """
    rel = Path(file_path)
    parts = list(rel.parts)
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]  # strip .py

    # Remove empty parts, join with '.'
    parts = [p for p in parts if p]
    return ".".join(parts) if parts else "<unknown_module>"


def _find_qualname_for_line(
    defs: List[Tuple[int, int, str]], line_no: int
) -> str:
    """
    Given a list of (start, end, qualname) and a line number,
    return the innermost definition that contains the line, if any.

    If no definition contains the line, returns an empty string.
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
               (i.e. line_info["added"] / new_path).
               repo_root should point to the NEW checkout.
      - "old": use removed lines and file paths from the OLD version
               (i.e. line_info["removed"] / old_path).
               repo_root should point to the OLD checkout.
    Returns:
      Sorted list of strings: "<module>:<qualname>".
    """
    mode = mode.lower()
    if mode not in {"new", "old"}:
        raise ValueError(f"Unsupported mode: {mode!r}. Use 'new' or 'old'.")

    repo_root_path = Path(repo_root)  # <- allow Path or str
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
                # Fallback in weird cases; you probably won't hit this
                rel_to_repo = file_on_disk

            module_name = _path_to_module_name(str(rel_to_repo))

            for line_no in lines:
                local_qualname = _find_qualname_for_line(collector.defs, line_no)
                if local_qualname:
                    full_qualname = f"{module_name}:{local_qualname}"
                    modified_qualnames.add(full_qualname)
                else:
                    # For now, ignore module-level changes
                    pass

    if mode in {"new"}:
        _process(line_info["added"])

    if mode in {"old"}:
        _process(line_info["removed"])

    return sorted(modified_qualnames)

def load_jsonl(path: str) -> Iterable[dict]:
    """Yield JSON objects, one per line, from a JSONL file."""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def collect_functions_by_target(
    jsonl_path: str, target_qualnames: Iterable[str]
) -> Dict[str, Set[str]]:
    """
    For each target qualname, collect the union of all function qualnames
    that appear in stacks for that target.

    Returns:
        dict: target_qualname -> set of function qualnames
    """
    targets_set: Set[str] = set(target_qualnames)
    results: Dict[str, Set[str]] = defaultdict(set)

    for entry in load_jsonl(jsonl_path):
        target = entry.get("target")
        if target not in targets_set:
            continue

        stack = entry.get("stack") or []
        for frame in stack:
            _, qualname = frame[0], frame[1]
            results[target].add(qualname)
    return results

def collect_files(root_path: Path, keyword_filter: str = "") -> List[Path]:
    jsonl_files = root_path.rglob("*.jsonl")
    if keyword_filter:
        return [x for x in jsonl_files if keyword_filter in str(x)]
    return list(jsonl_files)

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

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--root-path",
        type=str,
        default="/home/yusuf/explainbench/logs/run_evaluation/track.{agent_name}.1020/{agent_name}/{instance_id}",
        help="Template path to logs; must contain {agent_name} and {instance_id}.",
    )

    parser.add_argument(
        "--agents",
        nargs="+",
        default=["gold"],
        help="List of agent names to process.",
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
            # "astropy__astropy-12907",
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
            "/home/yusuf/explainbench/dataset/extract_ground_truths/localization/swe_bench_repos"
        ),
        help="Root directory under which all Git repos will be cloned.",
    )

    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path(
            "/home/yusuf/explainbench/dataset/extract_ground_truths/effect/test.json"
        ),
        help="Path to the output JSON file.",
    )

    args = parser.parse_args()

    ROOT_PATH = args.root_path
    AGENT_NAMES = args.agents
    INSTANCE_IDS = args.instance_ids
    REPOS_ROOT = args.repos_root
    OUTPUT_PATH = args.output_path
    
    monkey_patch_dataset()
    ds = load_swebench_dataset(instance_ids=INSTANCE_IDS)

    # Final structure: agent -> instance_id -> [functions]
    results: Dict[str, Dict[str, List[str]]] = {}

    for agent in AGENT_NAMES:
        agent_mapping: Dict[str, List[str]] = {}
        for instance in ds:
            instance_id = instance.get("instance_id", "")
            assert instance_id, "instance_id is missing"

            current_root = Path(
                ROOT_PATH.format(agent_name=agent, instance_id=instance_id)
            )
            assert current_root != ""

            buggy_files = collect_files(current_root, "buggy_traces")
            patched_files = collect_files(current_root, "patched_traces")
            
            if not buggy_files or not patched_files:
                continue

            # Ensure repo is at the base commit
            repo_slug = instance["repo"]          # e.g. "astropy/astropy"
            base_commit = instance["base_commit"]
            repo_dir = ensure_repo_at_commit(
                repos_root=REPOS_ROOT,
                repo_slug=repo_slug,
                commit=base_commit,
            )

            # Extract qualnames for OLD version
            patch_content = instance.get("patch", "")
            assert patch_content != ""

            # Qualnames from old and new versions
            old_qualnames = extract_modified_qualnames(
                patch_content=patch_content,
                repo_root=repo_dir,
                mode="old",
            )
            apply_patch_to_repo(repo_dir, patch_content)
            new_qualnames = extract_modified_qualnames(
                patch_content=patch_content,
                repo_root=repo_dir,
                mode="new",
            )

            all_functions: Set[str] = set()

            # Use OLD qualnames for buggy_traces
            for jsonl_path in buggy_files:
                per_target = collect_functions_by_target(
                    jsonl_path=str(jsonl_path),
                    target_qualnames=old_qualnames,
                )
                for funcs in per_target.values():
                    all_functions.update(funcs)

            # Use NEW qualnames for patched_traces
            for jsonl_path in patched_files:
                per_target = collect_functions_by_target(
                    jsonl_path=str(jsonl_path),
                    target_qualnames=new_qualnames,
                )
                for funcs in per_target.values():
                    all_functions.update(funcs)

            agent_mapping[instance_id] = sorted(all_functions)
        results[agent] = agent_mapping

    # Write out the final JSON
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, sort_keys=True)