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
import sys
import traceback
from pathlib import Path


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
    """Exec code defining class Solution, call its (first) method per input."""
    ns: dict = {"__builtins__": __builtins__}
    # typing shims so `from typing import List` style hints survive without imports
    for t in ("List", "Optional", "Dict", "DefaultDict", "Tuple", "Set", "deque"):
        ns[t] = t
    ns["TreeNode"] = TreeNode()
    ns["ListNode"] = ListNode()
    ns["deque"] = __import__("collections").deque
    ns["heapq"] = __import__("heapq")
    ns["math"] = __import__("math")
    ns["itertools"] = __import__("itertools")
    ns["functools"] = __import__("functools")
    ns["string"] = __import__("string")
    ns["re"] = __import__("re")
    exec(code, ns)  # noqa: S102 - trusted local blog code
    sol_cls = None
    for v in ns.values():
        if inspect.isclass(v) and v.__name__ == "Solution":
            sol_cls = v
            break
    if sol_cls is None:
        raise ValueError("no class Solution")

    method = None
    pub = [n for n in dir(sol_cls)
           if not n.startswith("_") and callable(getattr(sol_cls, n))]
    if len(pub) != 1:
        raise ValueError(f"expected exactly 1 public method, got {pub}")
    method = pub[0]

    params = list(inspect.signature(getattr(sol_cls, method)).parameters)
    arg_names = [p for p in params if p != "self"]

    def ser(v):
        if isinstance(v, (int, float, str, bool)) or v is None:
            if isinstance(v, float) and v == int(v):
                return int(v)  # 2.0 -> 2 to match JSON-ish module outputs
            return v
        if isinstance(v, (list, tuple)):
            return [ser(x) for x in v]
        if isinstance(v, dict):
            return {str(k): ser(x) for k, x in v.items()}
        if hasattr(v, "val") and hasattr(v, "left"):  # TreeNode -> level array
            def tn(n):
                if n is None:
                    return None
                out = [n.val]
                q = [n]
                while q:
                    cur = q.pop(0)
                    for c in (cur.left, cur.right):
                        if c is not None:
                            out.append(c.val)
                            q.append(c)
                return out
            return tn(v)
        if hasattr(v, "val") and hasattr(v, "next"):  # ListNode
            def ln(n):
                out = []
                while n is not None:
                    out.append(n.val)
                    n = n.next
                return out
            return ln(v)
        return str(v)

    # node constructors from arrays, used when the solution walks .next/.left
    LN = ns.get("ListNode") or ListNode()
    TN = ns.get("TreeNode") or TreeNode()

    def to_nodes(v, pos=None):
        if not isinstance(v, list) or not v:
            return v
        nodes = [LN(x) for x in v]
        for i in range(len(nodes) - 1):
            nodes[i].next = nodes[i + 1]
        if pos is not None and 0 <= pos < len(nodes):
            nodes[-1].next = nodes[pos]
        return nodes[0]

    def to_tree(v):
        # level-order array (LC style): [1,2,3,4] with nulls as None
        if not isinstance(v, list) or not v:
            return None
        root = TN(v[0])
        q = [root]
        i = 1
        while q and i < len(v):
            n = q.pop(0)
            if i < len(v) and v[i] is not None:
                n.left = TN(v[i]); q.append(n.left)
            i += 1
            if i < len(v) and v[i] is not None:
                n.right = TN(v[i]); q.append(n.right)
            i += 1
        return root

    wants_list = ".next" in code
    wants_tree = (".left" in code or ".right" in code) and ".next" not in code

    def prep(arg_name, arg):
        if wants_list and isinstance(arg, list) and arg and not isinstance(arg[0], list):
            pos = env_pos.get("pos")
            return to_nodes(arg, pos)
        if wants_tree and isinstance(arg, list) and arg:
            return to_tree(arg)
        return arg

    def find_node(root, val):
        q = [root]
        while q:
            n = q.pop(0)
            if n is None:
                continue
            if n.val == val:
                return n
            q.append(n.left); q.append(n.right)
        return val

    outs = []
    for env in inputs:
        sol = sol_cls()
        env_pos = env
        raw_args = [env.get(a) for a in arg_names]
        args = [prep(a, v) for a, v in zip(arg_names, raw_args)]
        # LCA-family: map selector values (p/q) to actual tree nodes
        if wants_tree and args and isinstance(args[0], object) and hasattr(args[0], "val"):
            for i, a in enumerate(arg_names):
                if a in ("p", "q", "u", "v") and isinstance(args[i], (int, str)):
                    args[i] = find_node(args[0], args[i])
        result = getattr(sol, method)(*args)
        if result is None:
            # in-place problems return None; report the mutated argument:
            # nested list (matrix), flat list (array), or linked list
            for raw in args:
                if isinstance(raw, list):
                    result = raw
                    break
            if result is None and wants_list and args and args[0] is not None:
                result = ser(args[0])
        outs.append(json.dumps(ser(result), ensure_ascii=False))
    return outs


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
