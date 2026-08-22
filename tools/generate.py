"""algoviz module generator — turn a Python LeetCode solution into an
algoviz player module via the DeepSeek API, then validate with node.

Usage:
  python generate.py spec.json [--out ../modules] [--model deepseek-v4-flash] [--retries 3]

spec.json:
{
  "id": "two-sum",                  // module id (also the filename)
  "title": "1 两数之和 · 哈希",       // display title
  "code": "<original python code>",  // the code the player highlights, VERBATIM
  "problem": "题意简述（可选）",
  "default_input": "nums = [...]\ntarget = 9",   // optional, LLM invents if absent
  "test_inputs": ["..."],            // optional extra inputs
  "expected_outputs": ["[0,1]"]      // optional, per input (incl. default)
}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent  # algoviz/
API_URL = "https://api.deepseek.com/v1/chat/completions"

with open(ROOT / "spec" / "module-format.md", encoding="utf-8") as f:
    FORMAT_SPEC = f.read()

with open(ROOT / "examples" / "two-sum.js", encoding="utf-8") as f:
    REFERENCE_MODULE = f.read()


def chat(key: str, model: str, messages: list, temperature: float = 0.2) -> str:
    """v4-flash is a reasoning model; disable thinking via the `thinking`
    switch so max_tokens goes to the answer itself. If the server rejects
    the switch, fall back to a plain call with a large budget."""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 8192,
        "thinking": {"type": "disabled"},
    }
    r = requests.post(
        API_URL,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        json=payload,
        timeout=600,
    )
    if r.status_code == 400:
        payload.pop("thinking")
        payload["max_tokens"] = 24000
        r = requests.post(
            API_URL,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            json=payload,
            timeout=600,
        )
    r.raise_for_status()
    j = r.json()
    ch = j["choices"][0]
    content = ch["message"].get("content") or ""
    if not content.strip() and ch.get("finish_reason") == "length":
        payload.pop("thinking", None)
        payload["max_tokens"] = 48000
        r = requests.post(
            API_URL,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            json=payload,
            timeout=600,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"].get("content") or ""
    return content


def extract_code(reply: str) -> str:
    """Pull the first ```js/```javascript fenced block from the reply."""
    lines = reply.splitlines()
    inside, out, fence = False, [], ""
    for ln in lines:
        if not inside and ln.strip().startswith("```"):
            fence = ln.strip()[3:].lower()
            if fence in ("", "js", "javascript"):
                inside = True
            continue
        if inside and ln.strip().startswith("```"):
            return "\n".join(out)
        if inside:
            out.append(ln)
    if inside:
        return "\n".join(out)
    # fallback: whole reply if it already looks like an IIFE
    if "AlgoVizModules" in reply:
        return reply
    raise ValueError("reply contains no fenced js code block")


def fix_registration(js: str, want_id: str) -> str:
    """LLMs sometimes register the module under a slightly different key;
    force it to the spec id (single registration assumed)."""
    def repl(m):
        return f'AlgoVizModules["{want_id}"]'
    return re.sub(r'AlgoVizModules\["[^"]*"\]', repl, js, count=1)


def module_language(js_path: Path) -> str:
    """Best-effort read of the module's language field ('cpp' vs default 'python')."""
    txt = js_path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'language\s*:\s*"([^"]+)"', txt) or re.search(r"language\s*:\s*'([^']+)'", txt)
    return m.group(1).lower() if m and m.group(1).lower() in ("cpp", "python") else "python"


def validate_module(js_path: Path) -> tuple[bool, str]:
    lang = module_language(js_path)
    truth = ground_truth(js_path, lang)
    env = dict(os.environ)
    if truth:
        env["ALGOVIZ_TRUTH"] = json.dumps({js_path.stem: truth}, ensure_ascii=False)
    p = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "validate.py"), str(js_path)],
        capture_output=True, text=True, timeout=60, env=env,
    )
    return p.returncode == 0, (p.stdout + p.stderr).strip()


def ground_truth(js_path: Path, language: str = "python") -> list[str] | None:
    """Run the ORIGINAL source code with the module's own inputs; returns real
    outputs per input (whitespace-normalized), or None when it can't be run.

    - python: exec the code via crosscheck.py (LeetCode style).
    - cpp:    compile + run via cpp_truth.py (needs g++).
    """
    try:
        runner = "crosscheck.py" if language != "cpp" else "cpp_truth.py"
        p = subprocess.run(
            [sys.executable, str(ROOT / "tools" / runner), str(js_path)],
            capture_output=True, text=True, timeout=120,
        )
        j = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        return None
    if not j.get("ok"):
        return None
    return [o.replace(" ", "") for o in j["outputs"]]


def build_prompt(spec: dict) -> list[dict]:
    lang = spec.get("language") or "python"
    lang_label = "C++" if lang == "cpp" else "Python"
    sys_msg = (
        "你是 algoviz 可视化模块生成器。algoviz 是一个算法步骤播放器：左边显示原始 "
        f"{lang_label} 代码并像调试器一样逐步高亮当前行，右边显示若干可视化视图。"
        f"你的任务是把给定的 {lang_label} 题解转译成一个自包含的 JS 模块，该模块的 run(input) "
        "要忠实复现原解法的执行过程并产出步骤数组。只输出一个 ```js 代码块，"
        "不要输出其它解释。"
    )
    user_msg = f"""# algoviz 模块格式规范

{FORMAT_SPEC}

# 参考实现（手写范本，格式务必与它一致）

```js
{REFERENCE_MODULE}
```

# 本次任务

模块 id: {spec['id']}
标题: {spec['title']}
语言: {lang_label}（模块的 language 字段必须写 {json.dumps(lang)}）
{("原题链接: " + spec['link']) if spec.get('link') else ""}
{("题意: " + spec['problem']) if spec.get('problem') else ""}
{("OJ 型（标准输入输出）: " + spec['oj_hint']) if spec.get('oj_hint') else ""}

原始 {lang_label} 代码（模块的 code 字段必须与它逐字一致，不得改动任何字符，
因为行高亮要对准用户的原始代码；JS 实现里的 line 号必须对应这段代码的 1-based 行号）:

```{lang}
{spec['code'].rstrip()}
```

要求：
1. run(input) 的算法逻辑必须与这段 {lang_label} 完全等价，输出也要一致。
2. 模块要有 language 字段（{"\"cpp\"" if lang == "cpp" else "\"python\""}），
   且若上方给了原题链接，模块的 link 字段就填它（只对 LeetCode/洛谷渲染跳转）。
3. defaultInput 用一个简短、能体现算法过程的用例；testInputs 再给 1-2 个（含边界情况），
   expectedOutputs 给出每个输入对应 {lang_label} 解法的真实输出（认真模拟，别瞎写）。
4. views 选 2-4 个最能体现该算法结构的视图（参考规范里的视图类型说明）。
5. 每步 msg 用简体中文解释这一行在做什么。
6. 步骤数控制在 30-200 之间（对小型输入）；不要为一次赋值记录多步。
{spec['oj_rules'] if spec.get('oj_rules') else ""}
"""
    return [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]


def fix_prompt(spec: dict, js: str, errors: str) -> list[dict]:
    return build_prompt(spec) + [
        {"role": "assistant", "content": "```js\n" + js + "\n```"},
        {"role": "user", "content": f"你生成的模块没有通过验证，错误信息：\n\n{errors}\n\n"
         "请修复后重新输出完整的 ```js 模块（注意 code 字段必须与原始代码逐字一致，"
         "language 字段要写对，若给了 link 字段也请保留）。"},
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--out", default=str(ROOT / "modules"))
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--key")
    ap.add_argument("--key-file")
    args = ap.parse_args()

    key = args.key
    if not key and args.key_file:
        key = Path(args.key_file).read_text(encoding="utf-8").strip()
    if not key:
        for cand in (Path.home() / ".deepseek-key", ROOT / ".deepseek-key"):
            if cand.is_file():
                key = cand.read_text(encoding="utf-8").strip()
                break
    if not key:
        sys.exit("no API key: use --key, --key-file or ~/.deepseek-key")

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{spec['id']}.js"

    messages = build_prompt(spec)
    last_err = ""
    for attempt in range(args.retries + 1):
        t0 = time.time()
        reply = chat(key, args.model, messages)
        dt = time.time() - t0
        try:
            js = extract_code(reply)
        except ValueError as e:
            last_err = str(e)
            messages = fix_prompt(spec, "", last_err)
            print(f"[{spec['id']}] attempt {attempt}: {e}")
            continue
        js = fix_registration(js, spec["id"])
        out_path.write_text(js, encoding="utf-8")
        ok, report = validate_module(out_path)
        print(f"[{spec['id']}] attempt {attempt} ({dt:.0f}s): {'OK' if ok else 'FAIL'}")
        print("  " + report.replace("\n", "\n  "))
        if ok:
            print(f"written: {out_path}")
            return
        last_err = report
        messages = fix_prompt(spec, js, last_err)
    out_path.unlink(missing_ok=True)
    sys.exit(f"[{spec['id']}] gave up after {args.retries + 1} attempts:\n{last_err}")


if __name__ == "__main__":
    main()
