import os
import re
import shutil
import subprocess
import json
import time
import argparse
from pathlib import Path
from typing import List, Dict, Optional

import pandas as pd
from datasets import load_dataset
from git import Repo
from tqdm import tqdm

def clone_repo(repo_name: str, repos_dir: Path) -> Optional[Path]:
    """Clones a repository from GitHub if it doesn't already exist."""
    
    dest_dir = Path(repos_dir, repo_name)
    if dest_dir.exists():
        print(f"Directory '{dest_dir}' already exists. Skipping clone.")
        return dest_dir

    url = f"https://github.com/{repo_name}.git"
    print(f"Cloning {url} into {dest_dir}...")
    try:
        Repo.clone_from(url, dest_dir)
        time.sleep(5)
        return dest_dir
    except:
        print(f"ERROR: Failed to clone {repo_name}.")
        return None

def checkout_commit(repo_path: Path, commit_hash: str) -> bool:
    """Checks out a specific commit in a repository."""
    if not repo_path.exists():
        print(f"ERROR: Repository path {repo_path} does not exist.")
        return False
    try:
        repo = Repo(repo_path)
        repo.git.reset('--hard') # Clean repository state before checkout
        repo.git.checkout(commit_hash, force=True)
        print(f"Checked out commit {commit_hash[:7]} in {repo_path.name}")
        return True
    except:
        print(f"ERROR: Failed to checkout commit {commit_hash} in {repo_path}.")
        return False

def get_modified_files(patch_content: str, version: str) -> List[str]:
    """
    Parses a patch file to extract file paths.
    """
    if version not in ['old', 'new']:
        raise ValueError("Version must be 'old' or 'new'")

    file_patches = patch_content.split('diff --git ')[1:]
    file_header_pattern = re.compile(r'--- (?:a/)?(.*?)\n\+\+\+ (?:b/)?(.*?)\n')
    modified_files = set()
    
    for file_patch in file_patches:
        file_header_match = file_header_pattern.search(file_patch)
        if not file_header_match:
            continue
        
        path = file_header_match.group(1) if version == 'old' else file_header_match.group(2)
        
        # Ignore /dev/null which indicates a new file creation or deletion
        if path != "/dev/null":
            modified_files.add(path)
            
    return list(modified_files)

def write_and_apply_patch(patch_content: str, repo_path: Path) -> bool:
    """Writes patch to a temp file and applies it using 'git apply'."""
    current_path = os.getcwd()
    os.chdir(str(repo_path))
    try:
        with open("temp_patch.patch", "w", encoding='utf-8') as f:
            f.write(patch_content)
        
        # Use git apply. It's more robust than the patch command.
        # -v for verbose, --reject to leave .rej files on failure
        result = subprocess.run(
            ["git", "apply", "-v", "temp_patch.patch"],
            check=True,
            capture_output=True,
            text=True
        )
        print(f"Successfully applied patch in {repo_path.name}")
        return True
    except Exception as e:
        print(f"An unexpected error occurred during patch application: {e}")
        return False
    finally:
        if os.path.exists("temp_patch.patch"):
            os.remove("temp_patch.patch")
        os.chdir(current_path)

def copy_files_to_target(
    source_repo_path: Path,
    relative_paths: List[str],
    target_instance_dir: Path,
    suffix: str
) -> List[str]:
    """Copies a list of files from the repo to a target directory with a new suffix."""
    copied_file_paths = []
    for rel_path in relative_paths:
        source_path = source_repo_path / rel_path
        if not source_path.exists():
            print(f"WARNING: Source file does not exist, cannot copy: {source_path}")
            continue

        target_path = (target_instance_dir / rel_path).resolve()
        
        target_dir = target_path.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        
        new_stem = f"{target_path.stem}{suffix}"        
        final_target_path = target_path.with_stem(new_stem)

        try:
            shutil.copy2(source_path, final_target_path)
            copied_file_paths.append(str(final_target_path))
        except Exception as e:
            print(f"ERROR: Failed to copy {source_path} to {final_target_path}: {e}")
    
    return copied_file_paths

def process_swe_bench_instance(
    row: pd.Series,
    repos_dir: Path,
    output_dir: Path
) -> Optional[Dict]:
    """
    Processes a single row from the SWE-bench dataset.
    Clones, checks out commit, copies old files, applies patch, copies new files.
    """
    instance_id = row['instance_id']
    repo_name = row['repo']
    base_commit = row['base_commit']
    patch_content = row['patch']
    
    print(f"\n--- Processing instance: {instance_id} ---")

    # 1. Clone repo
    repo_path = clone_repo(repo_name, repos_dir)
    if not repo_path:
        return None

    # 2. Checkout base commit to get the "before" state
    if not checkout_commit(repo_path, base_commit):
        return None

    # 3. Get old file paths and copy them
    target_instance_dir = output_dir / instance_id
    target_instance_dir.mkdir(parents=True, exist_ok=True)
    
    old_files_relative = get_modified_files(patch_content, version='old')
    copied_old_files = copy_files_to_target(
        source_repo_path=repo_path,
        relative_paths=old_files_relative,
        target_instance_dir=target_instance_dir,
        suffix=".old"
    )

    # # 4. Apply the patch to get the "after" state
    if not write_and_apply_patch(patch_content, repo_path):
        print(f"Skipping instance {instance_id} due to patch application failure.")
        # Clean up the repo to its base state for the next run
        repo = Repo(repo_path)
        repo.git.reset('--hard')
        return None

    # # 5. Get new file paths and copy them
    new_files_relative = get_modified_files(patch_content, version='new')
    copied_new_files = copy_files_to_target(
        source_repo_path=repo_path,
        relative_paths=new_files_relative,
        target_instance_dir=target_instance_dir,
        suffix=".new"
    )

    # # 6. Construct the result
    result = {
        "instance_id": instance_id,
        "old_files": copied_old_files,
        "new_files": copied_new_files
    }
    
    # Clean up repo
    repo = Repo(repo_path)
    repo.git.reset('--hard')

    return result


def main():
    """Main function to run the data processing pipeline."""
    parser = argparse.ArgumentParser(
        description="Process SWE-bench dataset to extract before and after versions of patched files."
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="swe_bench_files",
        help="The directory to save the extracted files and the final JSONL."
    )
    parser.add_argument(
        "--repos_dir",
        type=str,
        default="swe_bench_repos",
        help="The directory to clone the git repositories into."
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    repos_dir = Path(args.repos_dir)
    output_jsonl_path = Path("modified_files.jsonl")

    output_dir.mkdir(parents=True, exist_ok=True)
    repos_dir.mkdir(parents=True, exist_ok=True)

    print("Loading SWE-bench dataset...")

    ds = load_dataset("SWE-bench/SWE-bench_Verified")
    df = ds["test"].to_pandas()
    print(f"Found {len(df)} instances to process.")

    processed_ids = set()
    if output_jsonl_path.exists():
        with open(output_jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                data = json.loads(line)
                if 'instance_id' in data:
                    processed_ids.add(data['instance_id'])
        print(f"Found {len(processed_ids)} already processed instances. They will be skipped.")

    original_count = len(df)
    df_to_process = df[~df['instance_id'].isin(processed_ids)].copy()
    remaining_count = len(df_to_process)

    if remaining_count == 0:
        print("All instances have already been processed. Exiting.")
        return
        
    print(f"Total instances in dataset: {original_count}")
    print(f"Processing {remaining_count} new instances.")

    successful_runs = 0
    for _, row in tqdm(df_to_process.iterrows(), total=remaining_count, desc="Processing new instances"):
        result = process_swe_bench_instance(row, repos_dir, output_dir)
        if result:
            with open(output_jsonl_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(result) + '\n')
            successful_runs += 1
    
    if successful_runs == 0:
        print("\nNo new instances were successfully processed in this run.")
    else:
        print(f"\nSuccessfully processed and saved {successful_runs} new instances.")

    print(f"\nProcessing complete.")
    print(f"Extracted files are located in: {output_dir.resolve()}")
    print(f"Repositories are located in: {repos_dir.resolve()}")
    print(f"Output manifest saved to: {output_jsonl_path.resolve()}")

if __name__ == "__main__":
    main()