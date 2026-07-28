#!/usr/bin/env python3
"""
Post-tool wiring checker for AUDHD coding rules.
Runs as PostToolUse hook on Edit/Write for code files.
Detects orphaned code, debug leftovers, and structural violations.

Exit codes:
  0 = pass (stdout warnings go to Claude as feedback)
  Non-zero exits are reserved for future hard blocks.

Zero context window cost. Pure deterministic check.
"""

import ast
import json
import os
import re
import sys


# File extensions we check
CODE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".sh"}

# Debug patterns to flag
DEBUG_PATTERNS = [
    (r"\bprint\s*\(", ".py", "print() statement"),
    (r"\bconsole\.\s*log\s*\(", ".js,.ts,.tsx,.jsx", "console.log() statement"),
    (r"\bdebugger\b", ".js,.ts,.tsx,.jsx", "debugger statement"),
    (r"\bbreakpoint\s*\(", ".py", "breakpoint() statement"),
    (r"#\s*TODO|#\s*FIXME|#\s*HACK|#\s*XXX", None, "TODO/FIXME comment"),
    (r"//\s*TODO|//\s*FIXME|//\s*HACK|//\s*XXX", ".js,.ts,.tsx,.jsx", "TODO/FIXME comment"),
]

# Max nesting depth
MAX_NESTING = 2
# Max function length
MAX_FUNC_LINES = 30


def get_hook_input():
    """Read hook input from stdin."""
    try:
        return json.loads(sys.stdin.read())
    except (json.JSONDecodeError, IOError):
        return {}


def get_file_path(hook_input):
    """Extract file path from hook input."""
    tool_input = hook_input.get("tool_input", {})
    return tool_input.get("file_path", "")


def is_code_file(file_path):
    """Check if file is a code file we should analyze."""
    _, ext = os.path.splitext(file_path)
    return ext in CODE_EXTENSIONS


def check_debug_statements(file_path, content, ext):
    """Find leftover debug statements."""
    warnings = []
    for pattern, applies_to, label in DEBUG_PATTERNS:
        if applies_to and ext not in applies_to:
            continue
        for i, line in enumerate(content.split("\n"), 1):
            if re.search(pattern, line):
                # Skip if it's in a comment explaining something (not actual debug)
                stripped = line.strip()
                if label.startswith("TODO"):
                    warnings.append(f"  Line {i}: {label} - {stripped}")
                elif not stripped.startswith("#") and not stripped.startswith("//"):
                    warnings.append(f"  Line {i}: {label} - {stripped}")
    return warnings


def check_python_structure(file_path, content):
    """Check Python-specific structural issues."""
    warnings = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return warnings

    lines = content.split("\n")

    for node in ast.walk(tree):
        # Check function length
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.end_lineno and node.lineno:
                length = node.end_lineno - node.lineno + 1
                if length > MAX_FUNC_LINES:
                    warnings.append(
                        f"  Line {node.lineno}: function `{node.name}()` is {length} lines (max {MAX_FUNC_LINES}). Consider splitting."
                    )

        # Check nesting depth
        if isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
            depth = _nesting_depth(node)
            if depth > MAX_NESTING:
                warnings.append(
                    f"  Line {node.lineno}: nesting depth {depth} (max {MAX_NESTING}). Extract inner block."
                )

    # Check for bare except
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            warnings.append(
                f"  Line {node.lineno}: bare `except:` - name the specific exception."
            )

    # Check unused imports (simple heuristic)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                imports.append((name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = alias.asname or alias.name
                imports.append((name, node.lineno))

    for name, lineno in imports:
        # Simple check: does the name appear elsewhere in the file?
        count = 0
        for line in lines:
            if name in line:
                count += 1
        if count <= 1:  # Only in the import line itself
            warnings.append(
                f"  Line {lineno}: import `{name}` appears unused."
            )

    # Check for new function defs not called in same file
    func_defs = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip dunder methods and test functions
            if not node.name.startswith("__") and not node.name.startswith("test_"):
                func_defs.append((node.name, node.lineno))

    for name, lineno in func_defs:
        # Count references (excluding the def line itself)
        ref_count = 0
        for i, line in enumerate(lines, 1):
            if i == lineno:
                continue
            if name in line:
                ref_count += 1
        if ref_count == 0:
            warnings.append(
                f"  Line {lineno}: function `{name}()` defined but never called in this file. Verify it's wired from another file."
            )

    return warnings


def _nesting_depth(node):
    """Calculate max nesting depth of control flow."""
    max_depth = 0
    for child in ast.walk(node):
        if child is node:
            continue
        if isinstance(child, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
            max_depth = max(max_depth, 1 + _nesting_depth(child))
    return max_depth


def check_js_structure(file_path, content):
    """Check JS/TS structural issues (regex-based, no AST)."""
    warnings = []
    lines = content.split("\n")

    # Track function lengths (heuristic: function/const arrow to next function or end)
    func_starts = []
    for i, line in enumerate(lines):
        if re.match(r"\s*(export\s+)?(async\s+)?function\s+\w+", line):
            func_name = re.search(r"function\s+(\w+)", line)
            if func_name:
                func_starts.append((func_name.group(1), i + 1))
        elif re.match(r"\s*(export\s+)?(const|let)\s+\w+\s*=\s*(async\s+)?\(", line):
            var_name = re.search(r"(const|let)\s+(\w+)", line)
            if var_name:
                func_starts.append((var_name.group(2), i + 1))

    # Rough nesting check
    for i, line in enumerate(lines):
        # Count leading indentation depth by braces
        depth = 0
        for j in range(max(0, i - 20), i):
            depth += lines[j].count("{") - lines[j].count("}")
        if depth > MAX_NESTING + 2:  # +2 for function + class wrapper
            stripped = line.strip()
            if stripped and not stripped.startswith("//") and not stripped.startswith("*"):
                warnings.append(
                    f"  Line {i + 1}: deep nesting detected. Consider extracting."
                )
                break  # One warning is enough

    return warnings


def check_hardcoded_values(content, ext):
    """Flag likely hardcoded values that should be config."""
    warnings = []
    patterns = [
        (r'https?://\S+', "hardcoded URL"),
        (r':\d{4,5}\b', "hardcoded port number"),
    ]
    for pattern, label in patterns:
        for i, line in enumerate(content.split("\n"), 1):
            stripped = line.strip()
            # Skip comments and imports
            if stripped.startswith("#") or stripped.startswith("//") or "import" in stripped:
                continue
            if re.search(pattern, line):
                # Skip if it's in a test file
                if "test" in stripped.lower():
                    continue
                warnings.append(f"  Line {i}: possible {label} - consider using config/constant.")
                break  # One per pattern is enough
    return warnings


def main():
    hook_input = get_hook_input()
    file_path = get_file_path(hook_input)

    if not file_path or not is_code_file(file_path):
        sys.exit(0)

    if not os.path.exists(file_path):
        sys.exit(0)

    try:
        with open(file_path) as f:
            content = f.read()
    except IOError:
        sys.exit(0)

    _, ext = os.path.splitext(file_path)
    all_warnings = []

    # Debug statement check
    all_warnings.extend(check_debug_statements(file_path, content, ext))

    # Language-specific structural checks
    if ext == ".py":
        all_warnings.extend(check_python_structure(file_path, content))
    elif ext in (".js", ".ts", ".tsx", ".jsx"):
        all_warnings.extend(check_js_structure(file_path, content))

    # Hardcoded values (skip test files)
    basename = os.path.basename(file_path).lower()
    if "test" not in basename and "spec" not in basename:
        all_warnings.extend(check_hardcoded_values(content, ext))

    if all_warnings:
        # Output as feedback to Claude (not a block, a nudge)
        short_path = os.path.basename(file_path)
        print(json.dumps({
            "message": f"Wiring check on {short_path}:\n" + "\n".join(all_warnings)
        }))

    sys.exit(0)


if __name__ == "__main__":
    main()
