import re
import json
import os

def remove_comments_and_docstrings(source: str) -> str:
    """
    Remove comments and docstrings from Python source code using regex.
    Works well for most valid Python code.
    """
    pattern = r"""
        ('''[\s\S]*?''') |             
        (\"\"\"[\s\S]*?\"\"\") |       
        (\#[^\n]*)                     
    """
    cleaned = re.sub(pattern, '', source, flags=re.VERBOSE)
    cleaned = re.sub(r'\n\s*\n+', '\n\n', cleaned).strip()
    return cleaned


def main():
    PATH = "/home/yusuf/explainbench/dataset/extract_ground_truths/localization/swe_bench_files/modified_files.jsonl"

    with open(PATH, "r") as f:
        lines = f.readlines()

    for l in lines:
        item_dict = json.loads(l)

        for key in ("old_files", "new_files"):
            file_list = item_dict.get(key, [])

            for temp_path in file_list:
                if not os.path.exists(temp_path):
                    print(f"Warning: file not found: {temp_path}")
                    continue

                with open(temp_path, "r", encoding="utf-8") as f1:
                    code = f1.read()

                cleaned_code = remove_comments_and_docstrings(code)

                with open(temp_path, "w", encoding="utf-8") as f1:
                    f1.write(cleaned_code)


if __name__ == "__main__":
    main()