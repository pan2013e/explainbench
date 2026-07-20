import re
from typing import Dict, List
from pathlib import Path

from explainbench.question_builders.local.stages.identify_patched_functions import (
    extract_modified_lines,
)

TEST_FILE_PATTERN = {
    'astropy': re.compile(r'astropy/.*/tests/.*\.py$'),
    'django': re.compile(r'tests/.*\.py$'),
    'matplotlib': re.compile(r'(lib/matplotlib/tests/.*\.py)|(lib/mpl_toolkits/tests/.*\.py)$'),
    'pallets': re.compile(r'tests/.*\.py$'), # flask
    'psf': re.compile(r'tests/.*\.py$'), # requests
    'pydata': re.compile(r'xarray/tests/.*\.py$'), # xarray
    'pylint-dev': re.compile(r'tests/.*\.py$'),
    'pytest-dev': re.compile(r'testing/.*\.py$'),
    'scikit-learn': re.compile(r'sklearn/.*/tests/.*\.py$'),
    'sphinx-doc': re.compile(r'tests/.*\.py$'),
    'sympy': re.compile(r'sympy/.*/tests/.*\.py$'),
}

def read_patch(input_filepath: Path)->str:
    with open(input_filepath, "r") as f:
        return f.read()

def get_diff_info_per_instance(agent_output_dir: Path, instance_id: Path)->Dict[str, Dict]:
    repo = str(instance_id).split("__")[0]
    test_file_pattern = TEST_FILE_PATTERN.get(repo, None)
    patch_path = Path(agent_output_dir, instance_id, "patch.diff")
    try:
        patch_content = read_patch(patch_path)
        modified_lines = extract_modified_lines(patch_content)
        if test_file_pattern:
            added_files = list(modified_lines["added"].keys())
            removed_files = list(modified_lines["removed"].keys())
            for filename in added_files:
                if test_file_pattern.match(filename):
                    del modified_lines["added"][filename]
            for filename in removed_files:
                if test_file_pattern.match(filename):
                    del modified_lines["removed"][filename]
        return modified_lines
    except FileNotFoundError:
        # ignore warning for now due to incomplete data
        # print(f"{patch_path} does not exists")
        pass
    return {}

def get_all_instance_ids(agent_output_dir: Path)->List[Path]:
    outputs= []
    for dir in agent_output_dir.iterdir():
        if dir.is_dir():
            outputs.append(Path(agent_output_dir, dir))
    return sorted(outputs)

def get_diff_info_per_agent(output_dir: str, run_id: str, agent_id: str)->Dict:
    agent_output_dir = Path(output_dir, run_id, agent_id)
    instance_ids = get_all_instance_ids(agent_output_dir)
    records = {}
    for id in instance_ids:
        records[id] = {}
        record = get_diff_info_per_instance(
            agent_output_dir,
            id
        )
        if record:
            records[id] = record

    return records
