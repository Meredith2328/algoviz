"""Cross-check an algoviz module against the ORIGINAL Python code.

Executes the Python solution with each testcase input and prints the real
outputs as JSON lines; generate.py uses these as ground-truth
expected_outputs instead of trusting the LLM.

Usage:
  python crosscheck.py <module.js>            # reads defaultInput/testInputs
  python crosscheck.py <spec.json>            # reads spec code + inputs

Only supports standard LeetCode style:
  class Solution: def <method>(self, a, b, ...) -> ...
Inputs are "name = JSON" lines matched to the method's parameter names.
Prints one JSON per input line, or {"error": ...} when it cannot run.
"""
from __future__ import annotations

import ast
import inspect
import json
import re
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

RUN_TIMEOUT_S = 60


def parse_input_text(text: str) -> dict:
    env: dict = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_]\w*)\s*=\s*(.+)$", line)
        if not m:
            continue
        raw = m.group(2)
        try:
            env[m.group(1)] = json.loads(raw)
        except Exception:
            try:
                env[m.group(1)] = ast.literal_eval(raw)
            except Exception:
                env[m.group(1)] = raw
    return env


class List:  # common leetcode typing shims
    pass


def TreeNode():
    class N:
        def __init__(self, val=0, left=None, right=None):
            self.val, self.left, self.right = val, left, right
    return N


def ListNode():
    class N:
        def __init__(self, val=0, next=None):
            self.val, self.next = val, next
    return N


def run_python(code: str, inputs: list[dict]) -> list:
    """Compute the solution's real outputs by running it in a separate process.

    The题解 is written to a temp dir together with a generated driver, then the
    Python interpreter is invoked on the driver (argv list, no shell). Nothing
    here calls exec/eval — the interpreter does the executing, the same way
    cpp_truth.py hands C++ to g++. A runaway solution can only stall its own
    short-lived process, which we bound with a timeout.
    """
    from crosscheck_driver import DRIVER_TEMPLATE

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "solution.py").write_text(code, encoding="utf-8")
        (d / "job.json").write_text(
            json.dumps({"inputs": inputs}, ensure_ascii=False), encoding="utf-8")
        driver = d / "driver.py"
        driver.write_text(DRIVER_TEMPLATE, encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, str(driver)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=RUN_TIMEOUT_S, cwd=str(d), shell=False,
        )

    out = (proc.stdout or "").strip().splitlines()
    if not out:
        err = (proc.stderr or "").strip() or "solution driver produced no output"
        raise RuntimeError(err.splitlines()[-1])
    try:
        payload = json.loads(out[-1])
    except Exception:
        raise RuntimeError("unparsable driver output: " + out[-1][:200])
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "solution failed")
    return payload.get("outputs") or []


def load_inputs(target: Path) -> tuple[str, list[dict]]:
    if target.suffix == ".json":
        spec = json.loads(target.read_text(encoding="utf-8"))
        inputs = [parse_input_text(spec.get("default_input", ""))]
        for t in spec.get("test_inputs", []):
            inputs.append(parse_input_text(t))
        return spec["code"], inputs
    js = target.read_text(encoding="utf-8")
    code_m = re.search(r'code:\s*(\[.*?\]\.join\("\\n"\)|"(?:[^"\\]|\\.)*")', js, re.S)
    # extract code from the JS module (handles array-join or single string form)
    code = ""
    m = re.search(r"code:\s*\[((?:.|\n)*?)\]\s*\.join", js)
    if m:
        parts = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
        code = "\n".join(p.replace("\\\\", "\x00").replace('\\"', '"').replace("\\n", "\n").replace("\x00", "\\") for p in parts)
    else:
        m2 = re.search(r'code:\s*"((?:[^"\\]|\\.)*)"', js, re.S)
        if m2:
            code = m2.group(1).replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
    texts = []
    # double-quoted JS strings: defaultInput: "..." / testInputs: "..."
    for t in re.findall(r'defaultInput\s*:\s*"((?:[^"\\]|\\.)*)"', js):
        texts.append(t.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\"))
    arr = re.search(r"testInputs\s*:\s*\[(.*?)\]", js, re.S)
    if arr:
        for t in re.findall(r'"((?:[^"\\]|\\.)*)"', arr.group(1)):
            texts.append(t.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\"))
    # single-quoted JS strings: defaultInput: '...'
    for t in re.findall(r"defaultInput\s*:\s*'((?:[^'\\]|\\.)*)'", js):
        texts.append(t.replace("\\n", "\n").replace("\\'", "'"))
    arr2 = re.search(r"testInputs\s*:\s*\[(.*?)\]", js, re.S)
    if arr2:
        for t in re.findall(r"'((?:[^'\\]|\\.)*)'", arr2.group(1)):
            texts.append(t.replace("\\n", "\n").replace("\\'", "'"))
    inputs = [parse_input_text(t) for t in texts]
    seen, uniq = set(), []
    for i in inputs:
        key = json.dumps(i, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            uniq.append(i)
    return code, uniq


def main() -> None:
    target = Path(sys.argv[1])
    code, inputs = load_inputs(target)
    try:
        outs = run_python(code, inputs)
        print(json.dumps({"ok": True, "outputs": outs}, ensure_ascii=False))
    except Exception:
        print(json.dumps({"ok": False, "error": traceback.format_exc(limit=3)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
