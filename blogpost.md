# ExplainBench: Evaluating Code Explanations from Agents
TL;DR: Coding agents often provide final explanations to summarize what they changed and why the patch should work. However, our analysis shows that these explanations do not always reflect the actual behavior of the submitted patch. We introduce ExplainBench, a benchmark that evaluates whether coding-agent explanations accurately capture both the intended change and the patch’s actual effect. Across five agents and 297 SWE-bench Verified instances, explanation quality did not align with patch efficacy, and 79.3% of unsuccessful patches were explained in a way that suggested the bug-reproducing test would pass.

---

When interacting with coding agents, it's easy to focus more on the natural language summaries the agents provide than go the code changes it made line by line. Surprisingly, there was no way to evaluate how faithful those natural language summaries or explanations were!

ExplainBench changes this. ExplainBench evaluates whether coding agent explanations accurately capture the intent and efffect of a code change, by having a question-answering model use the explanations to answer questions with ground-truth answers. If the explanations are helpful and informative, the questions can be answered correctly - on the other hand, if the explanations are vague or misleading, the questions will be answered inaccurately. ExplainBench leverages this intuition to evaluate how faithful the explanations are to the actual change. Our evaluations on ExplainBench show that just because an agent makes good patches doesn't mean it makes good explanations, meaning explanations are on a separate axis that we should keep an eye on. Find out more about our work [here](link)!

## Explanations from Coding Agents

As coding agents take on larger tasks, their trajectories can include repository inspection, code edits, tool calls, and test execution. Reviewing every agent step to understand what an agent did ranges from time-consuming when it made small changes, to practically impossible when it autonomously changed thousands of lines. To make their work easier to review, coding agents usually provide a final explanation summarizing the task. Like a handoff from another developer, this explanation may describe what caused the bug, what changed, why the change should work, and what was tested. It can help users understand a patch quickly and decide where to focus their review.

But how well do these explanations reflect what the patch actually does?

## Preliminary Exploration

In a preliminary analysis, we found that explanations do not always align with the actual behavior of the submitted patches.

Consider this submission for the SWE-bench Verified instance django__django-15987, which involves fixture-directory handling in Django. Specifically, Django allows fixture-directory paths to be represented as either strings or `Path` objects. However, a bug occurred because `app_dir`, represented as a string, was compared directly with entries in `fixture_dirs`, which could include `Path` objects.

The relevant function contains two separate duplicate checks:

```python
# Detect duplicates within fixture_dirs
if len(fixture_dirs) != len(set(fixture_dirs)):
    raise ImproperlyConfigured(...)

# Detect whether an application fixture directory is also in fixture_dirs
if app_dir in fixture_dirs:
    raise ImproperlyConfigured(...)
```

To fix this bug, the Refact agent submitted a patch that changes the first check by normalizing entries in `fixture_dirs` before looking for duplicates:

```diff
- if len(fixture_dirs) != len(set(fixture_dirs)):
+ normalized_dirs = []
+ for directory in fixture_dirs:
+     normalized_dirs.append(
+         str(os.path.realpath(os.path.expanduser(directory)))
+     )
+
+ if len(normalized_dirs) != len(set(normalized_dirs)):
      raise ImproperlyConfigured(...)
```

Alongside the patch, the agent provided a confident explanation:

```markdown
### Changes Applied

Fixed the duplicate detection logic to properly handle Path instances.

...

### Functionality Verified

- Mixed Path/string duplicates are now properly detected.
- Valid Path usage continues to work without false positives.

...

The GitHub issue has been completely resolved with a robust,
backward-compatible solution that properly normalizes paths.
```

At first glance, the patch and the explanation appear consistent because both discuss path normalization and duplicate detection. However, the reported bug actually occurs in the second check, where the string `app_dir` is compared directly with entries that may be `Path` objects. However, the submitted patch left this comparison unchanged. As a result, the string-versus-`Path` mismatch remains and the bug persists. The explanation therefore presents the patch as a successful fix even though the patch does not affect the buggy behavior. 

This example illustrates a broader problem: an explanation can sound specific and convincing while failing to reflect what the submitted patch actually does.

## ExplainBench: Evaluating Explanations from Coding Agents

This is where ExplainBench comes in. ExplainBench is a benchmark that evaluates an agent's propensity to make these sorts of mistakes. ExplainBench examines whether an explanation accurately communicates both the intended behavior of the software and the actual effect of the agent's patch.

The main idea behind ExplainBench is: if an explanation contains the right information, an LLM, acting as a QA model, should be able to use it to answer concrete questions about the bug and the patch. To construct questions with verifiable answers, ExplainBench grounds the questions in observable program behavior. For intent questions, it uses the behavior introduced by the developer patch as a proxy for the intended fix. For effect questions, it uses the behavior introduced by the agent patch to capture what the submitted patch actually does. This distinction matters because the intended behavior and the actual effect of a patch may differ, as the example above shows. 

ExplainBench evaluates explanations along four dimensions: end-to-end intent, end-to-end effect, local intent, and local effect. In other words, it asks whether the explanation captures what the program should do and what the patch actually does, both at the program level and at the function level. ExplainBench then turns this behavioral evidence into multiple-choice questions and scores an explanation by the proportion of questions that a question-answering LLM answers correctly using the explanation. 

We built ExplainBench from 297 real-world bugs in SWE-bench Verified and evaluated explanations from five coding agents: refact, Lingxi, OpenHands, trae-agent, and mini-SWE-agent.  

## Findings

### Patch success does not guarantee explanation quality

Patch efficacy and explanation quality are different capabilities. Trae-agent achieved the highest patch efficacy but ranked fourth in explanation quality, while OpenHands showed the opposite pattern, ranking fourth in patch efficacy but first in explanation quality.  This ranking reversal shows that the agent that fixes the most issues is not necessarily the agent that explains its patches most reliably.

### Agents explain the big picture better than local behavior

Explanations were consistently better at describing broad program behavior than precise function-level behavior. Across all evaluated agents, end-to-end scores were higher than local scores. Agents could often describe the overall goal of a change, but they tend not to explain precisely what should happen inside the affected function or what their patch actually changed there. 

### Incorrect patches often come with confident explanations

Explanations were frequently overconfident when a patch was wrong. Across all evaluated agents, 79.3% of unsuccessful patches were explained in a way that led the evaluator to predict that the bug-reproducing test would pass.  The Django example captures this pattern, where the explanation confidently reported that the issue had been resolved, while the patch did not affect the failing behavior.

## Perspective

Our findings suggest that an explanation from a coding agent is not necessarily faithful to the actual program behavior. As coding agents take on larger tasks, developers will increasingly rely on their summaries to guide review, making the trustworthiness of these summaries critical. Therefore, a coding agent should not only produce a patch that solves the issue, but also faithfully communicate what the patch was intended to change and what it actually changed. Our vision for ExplainBench is that it will help the development of more trustworthy coding agents whose explanations accurately reflect the intended and actual behavior of the patches they produce.

The full paper is available at: [insert paper link].
