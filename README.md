# algoviz — 模块化的像素风算法步骤可视化播放器

<img width="1371" height="641" alt="image" src="https://github.com/user-attachments/assets/9a0c9905-698d-4165-8823-e0f996ba562e" />

**在线演示**：<https://meredith2328.github.io/algoviz/> 

可切换内置题库，也可用自己的大模型按提示词生成模块后粘贴导入（全程本地运行，不上传）。

- 左边展示上传的原始 Python 题解, 并像调试器一样逐步高亮当前行；
- 右边是结构化可视化视图（数组/条形/堆/树/图/栈/队列/变量等），支持播放/单步/倍速/进度条、收起/展开（保留进度），
- 右上角可编辑测试用例并即时重新生成全部步骤。

零依赖、纯静态：一个 `algoviz.js` + `algoviz.css` + 一堆模块文件。

```
algoviz/
├── player/            播放器（algoviz.js / algoviz.css，支持 python/cpp 高亮 + 原题跳转）
├── modules/           可视化模块（每题一个 js，含 run() 轨迹生成器）
├── spec/
│   ├── module-format.md   模块格式规范（给 LLM 的提示也用它）
│   ├── import/            从机试笔记抽出的题目 spec（C++ 题解 + 链接）
│   └── pending/           待生成题目 spec（从博客/题库抽取）
├── demo/index.html    本地演示页
└── tools/
    ├── import_from_notes.py  从机试笔记抽题解+链接 → spec/import/（可复用，固化为 skill）
    ├── extract_from_blog.py  从 pilog 算法文章抽题解 → spec/pending/
    ├── generate.py           单题：spec → deepseek 生成模块 → 验证 → modules/（支持 cpp）
    ├── batch_generate.py     批量版（并发 + 失败重试 + report）
    ├── cpp_truth.py          C++ 题解用 g++ 编译跑真实 expectedOutputs（OJ/main 型）
    ├── validate.py           验证器（结构/行号/步数/输出全检，模块在隔离子进程里跑）
    ├── validate_runner.js    被 node 预加载的取数 runner（配合 validate.py）
    ├── fix_expected_outputs.py 用真值校正模块的 expectedOutputs（数量错位/值不符）
    ├── build_modules_json.py 重建 modules.json（lc→lgp→oj 排序）
    ├── embed_in_blog.py      把 <div class="algoviz">… 嵌到 pilog 文章代码块上方
    └── sync_integrations.py  同步 player+modules 到 pilog / leetgotya
```

## 用法（作为库）

```html
<link rel="stylesheet" href="algoviz/algoviz.css">

<div class="algoviz" data-module="lc1-两数之和"
     data-title="两数之和 · 步骤可视化"></div>

<script src="algoviz/algoviz.js"
        onload="AlgoViz.mountAll(document, {base: 'algoviz/'})"></script>
```

- `data-module`：模块 id（`modules/<id>.js`）
- `data-title`：海报标题；`data-auto="1"` 页面加载即挂载（缺省点击挂载）
- 主题：默认 auto，跟随页面 `[data-theme]`/`[data-mode]`；可 `data-theme="light"`
- 也可编程调用：`AlgoViz.mount(el, {base, theme})`

## 新增一题

```bash
# 1) 手写 spec（code 字段 = 原始代码，Python 或 C++，逐字保留；也可先用
#    tools/import_from_notes.py 从机试笔记自动抽取多道题的 spec）
python tools/import_from_notes.py "D:/CoursesNow/10_课程/面向机试-XXX.md" --out spec/import
# 2) 生成 + 验证（key 放 ~/.deepseek-key；C++ 用 cpp_truth 编译跑真值）
python tools/generate.py spec/import/my-problem.json
# 3) 验证器独立可用（C++ 模块会自动走 cpp_truth 真值）
python tools/validate.py modules/my-problem.js
# 4) 重建模块清单（新题入库）
python tools/build_modules_json.py
# 5) 同步到两个项目（同步前自动跑完整性校验，不过则中止）
python tools/sync_integrations.py
```

## 校验与同步（防线上事故）

`tools/validate_manifest.py` 在**每次同步前自动运行**，把历史上出过的事故拦在提交前：

| 检查项 | 拦截的事故 |
|---|---|
| 文件名 ≤200 字节、无非法字符 | 286 字节文件名超 Linux 255 上限 → 下游 Actions checkout 失败、整站部署中断 |
| manifest 引用与 modules/ 文件一一对应 | manifest 提交了但 JS 漏提交 → 线上 404 |
| modules.json 与 modules/ 同步 | 新增模块后清单未重建 → 消费方拿到过期数据 |
| `node --check` 全量语法校验 | 半成品/损坏模块进入镜像 |
| 下游镜像（leetgotya/pilog）与源一致 | 同步中断留下的半成品状态 |

```bash
python tools/validate_manifest.py            # 日常自检
python tools/validate_manifest.py --strict   # 供 CI：有 WARN 也退出 1
```

全量跑一遍模块自检（每个模块在隔离子进程里执行，输出与 `expectedOutputs` 比对）：

```bash
python tools/validate.py modules/*.js        # 现状：298 条 ok / 3 条已知差异
python tools/fix_expected_outputs.py         # 预演：用真值校正 expectedOutputs
python tools/fix_expected_outputs.py --apply --also-values
```

**3 条已知差异**（非模块缺陷，无需再排查）：

| 模块 | 差异 | 原因 |
|---|---|---|
| `lc141-环形链表` | `true` vs `false` | 真值 harness 只给第一个链表参数按 `pos` 成环，无环用例建模不了 |
| `lc160-相交链表` | `null` vs `8` | 需按 `skipA/skipB` 把两链表在交点接起来，harness 未建模 |
| `lc347-前k个高频元素` | `[2,-1]` vs `[-1,2]` | 同频元素顺序：Python 的 sort 稳定按插入序，两种输出都是合法答案 |

`tools/fix_expected_outputs.py` 里的 `UNTRUSTED_TRUTH` 列出真值不可采信的模块（含上面两例
及 `lc236`——答案是树节点，harness 会把整棵子树序列化），修复脚本不会覆盖它们的期望值。

命名约定：`lc<题号>-<短名>[-vN].js`（LeetCode）、`lgp<题号>-<短名>.js`（洛谷）、
`oj<题号>-<短名>.js`（其他机试题，如 noobdream）。**文件名务必短**（长描述放模块内 `title` 字段），
同题多版本用 `-v2`/`-v3` 后缀。模块可设 `language: "cpp"`（默认 python）显示 C++ 徽标与高亮，
设 `link` 可渲染「◈ 原题」跳转（仅 LeetCode / 洛谷）。提交镜像时 manifest 与 modules/
必须在**同一个 commit** 里（`git add algoviz/` 整目录一起加）。

[leetgotya](https://meredith2328.github.io/leetgotya/) 里已接好：揭示面板对预存的题目显示「▶ 步骤可视化」按钮
（通过 `algoviz/manifest.json` 的题号映射）。

## 性能约定（步数很多也不会卡）

- 播放器只渲染当前步（跳转 O(1)），10 万步内不预渲染任何 DOM。
- 模块 `run()` 同步返回 steps 数组；步数硬上限 100000。
- 生成侧由验证器把关：行号必须落在原始代码内、每步必须有 msg 和 views、
  expectedOutputs 逐输入比对输出。

## 模块格式

见 `spec/module-format.md`（视图状态形状、parseInput 约定、ES5 限制等）。
`examples/two-sum.js` 是手写参考实现（格式示例，不参与同步/索引）。
