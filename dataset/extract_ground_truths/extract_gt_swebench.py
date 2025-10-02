# %%
from datasets import load_dataset

# %%
ds = load_dataset("SWE-bench/SWE-bench_Verified")

# %%
test = ds["test"].to_pandas()

# %%
test

# %%
from root_cause import extract_buggy_line_numbers, extract_buggy_function_names, extract_buggy_filenames, extract_new_created_filenames, extract_deleted_filenames, parse_patch, extract_buggy_line_contents

# %%
df =  test.copy()
df["parsed_patch"] = df.apply(lambda x: parse_patch(x.patch), axis=1)
df["buggy_function_names"] = df.apply(lambda x: extract_buggy_function_names(x.parsed_patch), axis=1)
df["buggy_file_names"] = df.apply(lambda x: extract_buggy_filenames(x.parsed_patch), axis=1)
df["new_created_files"] = df.apply(lambda x: extract_new_created_filenames(x.parsed_patch), axis=1)
df["new_deleted_files"] = df.apply(lambda x: extract_deleted_filenames(x.parsed_patch), axis=1)
df["buggy_line_numbers"] = df.apply(lambda x: extract_buggy_line_numbers(x.parsed_patch), axis=1)
df["buggy_line_contents"] = df.apply(lambda x: extract_buggy_line_contents(x.parsed_patch), axis=1)

# %%
is_exist = len(df["buggy_line_numbers"]) > 0

# %%
df["is_exist"] = df.apply(lambda x: len(x.buggy_line_numbers) > 0, axis=1)

# %%
df.is_exist.value_counts()

# %%
df[df.is_exist==False].iloc[0].parsed_patch

# %%
print(df[df.is_exist==False].iloc[0].patch)

# %%
df = df[["instance_id", "buggy_function_names", "buggy_file_names", "new_created_files", "new_deleted_files", "buggy_line_numbers", "buggy_line_contents"]].copy()

# %%
df.to_json('ground_truth.jsonl', orient='records', lines=True)

# %%



