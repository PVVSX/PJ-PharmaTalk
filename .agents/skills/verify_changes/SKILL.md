---
name: verify_changes
description: A mandatory skill to verify code changes, check for errors, and double-check tool call success before concluding a task.
---

# Verify Changes Skill

You must strictly adhere to the following verification protocols after making ANY code changes or executing tool calls:

1. **Verify Tool Call Success**: Whenever you use a tool like `multi_replace_file_content` or `run_command`, strictly read the tool's output. If a replacement chunk fails (e.g., "target content not found"), DO NOT ignore it. You MUST execute a follow-up tool call to properly apply the missing change before proceeding.

2. **Run Diagnostics/Linting**: If you edit Python files, consider running a quick syntax check (e.g., `python -m py_compile <file>`) or a linter if available, to catch simple `NameError` or `SyntaxError` issues before handing the work back to the user.

3. **Check for Missing Dependencies/Variables**: When moving code between files, explicitly verify that all required imports (e.g., `PYAUDIO_AVAILABLE`, `sys`, `Path`) are carried over to the destination file.

4. **Never Rush**: Do not prematurely tell the user "I'm done" if you haven't actually confirmed that ALL parts of your planned changes were successfully applied to the files.

Always verify your work before concluding your turn.
