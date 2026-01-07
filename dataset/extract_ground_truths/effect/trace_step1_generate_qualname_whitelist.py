import argparse
import ast
import json
import subprocess

from pathlib import Path
from typing import Dict, List, Set, Tuple

from swebench.harness.utils import load_swebench_dataset
from execution.util import get_instance_ids
from dataset.extract_ground_truths.effect.process_agent_patch import extract_modified_lines
from tqdm.auto import tqdm 


class QualnameVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.stack: List[str] = []
        self.qualnames: Dict[Tuple[str, int], str] = {}
        self.defs: List[Tuple[int, int, str]] = []

    def _record_def_range(self, node: ast.AST, qualname: str) -> None:
        if getattr(node, "decorator_list", ()):
            start = node.decorator_list[0].lineno
        else:
            start = node.lineno
        end = getattr(node, "end_lineno", start)
        self.defs.append((start, end, qualname))

    def add_qualname(self, node: ast.AST, name: str | None = None) -> None:
        name = name or node.name
        self.stack.append(name)
        if getattr(node, 'decorator_list', ()):
            lineno = node.decorator_list[0].lineno
        else:
            lineno = node.lineno
        self.qualnames.setdefault((name, lineno), ".".join(self.stack))
        qualname = ".".join(self.stack)
        self._record_def_range(node, qualname)

    def visit_FunctionDef(self, node, name=None):
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)), node
        self.add_qualname(node, name)
        self.stack.append("<locals>")
        if isinstance(node, ast.Lambda):
            children = [node.body]
        else:
            children = node.body

        for child in children:
            self.visit(child)

        self.stack.pop() 
        self.stack.pop()

        for field, child in ast.iter_fields(node):
            if field == "body":
                continue
            if isinstance(child, ast.AST):
                self.visit(child)
            elif isinstance(child, list):
                for grandchild in child:
                    if isinstance(grandchild, ast.AST):
                        self.visit(grandchild)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        assert isinstance(node, ast.Lambda)
        self.visit_FunctionDef(node, "<lambda>")

    def visit_ClassDef(self, node):
        assert isinstance(node, ast.ClassDef)
        self.add_qualname(node, node.name)
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
    if parts and (parts[0] == "lib" or parts[0] == "src"):
        parts = parts[1:]
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
            if not rel_path.endswith(".py"):
                continue
            
            file_on_disk = repo_root_path / rel_path
            source = file_on_disk.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(file_on_disk))

            visitor = QualnameVisitor()
            visitor.visit(tree)

            # Compute module name RELATIVE to repo_root
            try:
                rel_to_repo = file_on_disk.relative_to(repo_root_path)
            except ValueError:
                rel_to_repo = file_on_disk

            module_name = _path_to_module_name(str(rel_to_repo))

            for line_no in lines:
                local_qualname = _find_qualname_for_line(visitor.defs, line_no)
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
                    "and save to a single JSON file, updating incrementally."
    )

    parser.add_argument(
        "--agents",
        nargs="+",
        default=[
            # "gold",
            # "20250603_Refact_Agent_claude-4-sonnet",
            # "20250720_Lingxi-v1.5_claude-4-sonnet-20250514",
            # "20250805_openhands-Qwen3-Coder-480B-A35B-Instruct",
            # "20250928_trae_doubao_seed_code",
            "20250807_mini-v1.7.0_gpt-5-mini"
        ],
        help="List of agent names to process (used as top-level keys in the JSON).",
    )

    parser.add_argument(
        "--instance-ids",
        nargs="+",
        default=["all"],
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
        default=Path("/home/yusuf/explainbench/shared_logs") / "allowed_qualnames.json",
        help="Path to the single output JSON file.",
    )

    args = parser.parse_args()

    AGENT_NAMES = args.agents
    INSTANCE_IDS = get_instance_ids(args.instance_ids)
    REPOS_ROOT = args.repos_root
    OUTPUT_PATH = args.output_path

    # Load existing JSON if present so we can resume/append.
    if OUTPUT_PATH.exists():
        with OUTPUT_PATH.open("r", encoding="utf-8") as f:
            results: Dict[str, Dict[str, List[str]]] = json.load(f)
        print(f"[info] Loaded existing results from {OUTPUT_PATH}")
    else:
        results = {}

    # Ensure the parent directory exists for the output file.
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    ds = load_swebench_dataset(
        name="SWE-bench/SWE-bench_Verified",
        instance_ids=INSTANCE_IDS,
    )

    AGENT_JSON_PATH = Path("/home/yusuf/explainbench/dataset/explanations/agent_patches")

    for agent in AGENT_NAMES:
        print(f"Processing agent: {agent}")

        # Ensure we have a dict for this agent in the global results.
        agent_mapping: Dict[str, List[str]] = results.setdefault(agent, {})

        # Load patch reference for this agent once.
        if agent != "gold":
            with open(AGENT_JSON_PATH / f"{agent}.json", "r", encoding="utf-8") as f:
                patch_reference = json.load(f)
            patch_key = "model_patch"
        else:
            patch_reference = ds
            patch_key = "patch"

        for idx, instance in enumerate(tqdm(ds, desc=f"Agent {agent}", unit="inst")):
            instance_id = instance.get("instance_id", "")
            assert instance_id, "instance_id is missing"

            # If this (agent, instance_id) is already in results, do not overwrite it.
            if instance_id in agent_mapping:
                print(f"  {instance_id}: already present for agent {agent}, skipping.")
                continue

            repo_slug = instance["repo"]      # e.g. "astropy/astropy"
            base_commit = instance["base_commit"]

            if isinstance(patch_reference, list):
                patch_content = patch_reference[idx][patch_key]
            else:
                patch_content = patch_reference[instance_id][patch_key]

            if not patch_content:
                print(f"[warn] No patch for {instance_id}, skipping.")
                continue
            
            try:
                # Ensure repo is at the base commit.
                repo_dir = ensure_repo_at_commit(
                    repos_root=REPOS_ROOT,
                    repo_slug=repo_slug,
                    commit=base_commit,
                )

                # Qualnames for old version.
                old_qualnames = extract_modified_qualnames(
                    patch_content=patch_content,
                    repo_root=repo_dir,
                    mode="old",
                )

                # Apply patch and get qualnames for new version.
                apply_patch_to_repo(repo_dir, patch_content)
                new_qualnames = extract_modified_qualnames(
                    patch_content=patch_content,
                    repo_root=repo_dir,
                    mode="new",
                )

                merged = sorted(set(old_qualnames) | set(new_qualnames))
                agent_mapping[instance_id] = list(merged)

                # Persist full JSON after each new instance update.
                with OUTPUT_PATH.open("w", encoding="utf-8") as f:
                    json.dump(results, f, indent=2, sort_keys=True)

                print(f"  {instance_id}: {len(merged)} qualnames (saved)")
            except Exception as e:
                print(f"[error] Failed to process {instance_id} for agent {agent}: {e}")
                continue

    print(f"Finished. JSON at {OUTPUT_PATH}")



if __name__ == "__main__":
    main()
