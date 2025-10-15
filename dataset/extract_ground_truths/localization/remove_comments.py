import re
import json
import os

import io
import tokenize

def remove_comments_and_docstrings(source: str) -> str:
    """
    Remove all comments and docstrings from a Python source string.
    """
    io_obj = io.StringIO(source)
    output_tokens = []

    prev_toktype = tokenize.INDENT
    last_lineno = -1
    last_col = 0

    try:
        for tok in tokenize.generate_tokens(io_obj.readline):
            token_type, token_string, (start_line, start_col), (end_line, end_col), _ = tok

            # Remove comments
            if token_type == tokenize.COMMENT:
                continue

            # Remove docstrings (triple-quoted strings that appear at module, class, or function start)
            if token_type == tokenize.STRING:
                if prev_toktype == tokenize.INDENT or last_lineno == 0:
                    # Likely a module-level docstring
                    continue
                elif prev_toktype == tokenize.NEWLINE:
                    # Function/class docstring
                    continue

            # Keep other tokens
            if start_line > last_lineno:
                last_col = 0
            if start_col > last_col:
                output_tokens.append(" " * (start_col - last_col))
            output_tokens.append(token_string)
            prev_toktype = token_type
            last_col = end_col
            last_lineno = end_line
    except tokenize.TokenError:
        # In case of malformed input
        pass

    return "".join(output_tokens)


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