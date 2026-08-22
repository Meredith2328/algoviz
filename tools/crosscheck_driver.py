# -*- coding: utf-8 -*-
"""Build the standalone driver script that computes a solution's real outputs.

`crosscheck.py` writes the题解 source and a JSON job into a temp directory, then
runs `python <driver.py>` there. The Python interpreter itself executes the
solution — nothing in this repo calls exec/eval on it — mirroring how
`cpp_truth.py` hands C++ to g++.

The driver is emitted as text so the temp script stays self-contained:
    solution.py   the题解 verbatim, imported as a module
    job.json      {"inputs": [{param: value}, ...]}
    driver.py     this template; prints {"ok":..., "outputs":[...]} on stdout
"""
from __future__ import annotations

DRIVER_TEMPLATE = '''# -*- coding: utf-8 -*-
"""Auto-generated driver: import the solution module, call its single public
method once per input, print JSON results. Runs in a throwaway temp dir."""
import inspect
import json
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


class List:  # typing shims for annotations like List[int]
    pass


def _tree_cls():
    class N:
        def __init__(self, val=0, left=None, right=None):
            self.val, self.left, self.right = val, left, right
    return N


def _list_cls():
    class N:
        def __init__(self, val=0, next=None):
            self.val, self.next = val, next
    return N


def prelude():
    """Names LeetCode snippets assume exist, injected as builtins before the
    solution module is imported.

    These must be real subscriptable objects, not placeholder strings: the
    solution's annotations (List[int], Optional[TreeNode]) get evaluated when we
    read the method signature, so a string would raise TypeError.
    """
    import builtins
    import collections
    import functools
    import heapq
    import itertools
    import math
    import re
    import string
    import typing
    builtins.List = typing.List
    builtins.Optional = typing.Optional
    builtins.Dict = typing.Dict
    builtins.DefaultDict = typing.DefaultDict
    builtins.Tuple = typing.Tuple
    builtins.Set = typing.Set
    builtins.Any = typing.Any
    builtins.TreeNode = _tree_cls()
    builtins.ListNode = _list_cls()
    builtins.deque = collections.deque
    builtins.defaultdict = collections.defaultdict
    builtins.Counter = collections.Counter
    builtins.heapq = heapq
    builtins.math = math
    builtins.itertools = itertools
    builtins.functools = functools
    builtins.string = string
    builtins.re = re


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


def main():
    prelude()
    code = (HERE / "solution.py").read_text(encoding="utf-8")
    job = json.loads((HERE / "job.json").read_text(encoding="utf-8"))
    inputs = job.get("inputs") or []

    import importlib
    solution = importlib.import_module("solution")

    sol_cls = None
    for v in vars(solution).values():
        if inspect.isclass(v) and v.__name__ == "Solution":
            sol_cls = v
            break
    if sol_cls is None:
        raise ValueError("no class Solution")

    pub = [n for n in dir(sol_cls)
           if not n.startswith("_") and callable(getattr(sol_cls, n))]
    if len(pub) != 1:
        raise ValueError("expected exactly 1 public method, got %s" % pub)
    method = pub[0]

    params = list(inspect.signature(getattr(sol_cls, method)).parameters)
    arg_names = [p for p in params if p != "self"]

    import builtins
    # prefer node classes the solution itself defines, so isinstance/attr checks
    # line up with the objects it builds; fall back to the injected ones
    LN = getattr(solution, "ListNode", None) or builtins.ListNode
    TN = getattr(solution, "TreeNode", None) or builtins.TreeNode

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

    state = {}

    def prep(arg):
        if wants_list and isinstance(arg, list) and arg and not isinstance(arg[0], list):
            return to_nodes(arg, state.get("pos"))
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
        state = env
        args = [prep(env.get(a)) for a in arg_names]
        # LCA-family: map selector values (p/q) to real tree nodes
        if wants_tree and args and hasattr(args[0], "val"):
            for i, a in enumerate(arg_names):
                if a in ("p", "q", "u", "v") and isinstance(args[i], (int, str)):
                    args[i] = find_node(args[0], args[i])
        result = getattr(sol, method)(*args)
        if result is None:
            # in-place problems return None; report the mutated argument
            for raw in args:
                if isinstance(raw, list):
                    result = raw
                    break
            if result is None and wants_list and args and args[0] is not None:
                result = ser(args[0])
        outs.append(json.dumps(ser(result), ensure_ascii=False))
    return outs


if __name__ == "__main__":
    try:
        print(json.dumps({"ok": True, "outputs": main()}, ensure_ascii=False))
    except Exception:
        print(json.dumps({"ok": False, "error": traceback.format_exc(limit=3)},
                         ensure_ascii=False))
'''
