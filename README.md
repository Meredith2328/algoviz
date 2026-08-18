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
├── player/            播放器（algoviz.js / algoviz.css）
├── modules/           可视化模块（每题一个 js，含 run() 轨迹生成器）
├── spec/
│   ├── module-format.md   模块格式规范（给 LLM 的提示也用它）
│   └── pending/           待生成题目 spec（从博客/题库抽取）
├── demo/index.html    本地演示页
└── tools/
    ├── extract_from_blog.py  从 pilog 算法文章抽题解 → spec/pending/
    ├── generate.py           单题：spec → deepseek 生成模块 → node 验证 → modules/
    ├── batch_generate.py     批量版（并发 + 失败重试 + report）
    ├── validate.js           node 验证器（结构/行号/步数/输出全检）
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
# 1) 手写 spec（code 字段 = 原始 Python，逐字保留）
# 2) 生成 + 验证（key 放 ~/.deepseek-key）
python tools/generate.py spec/pending/my-problem.json
# 3) 验证器独立可用
node tools/validate.js modules/my-problem.js
# 4) 同步到两个项目（同步前自动跑完整性校验，不过则中止）
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

命名约定：`lc<题号>-<短名>[-vN].js`。**文件名务必短**（长描述放模块内 `title` 字段），
同题多版本用 `-v2`/`-v3` 后缀，下游按版本号取最高。提交镜像时 manifest 与 modules/
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
`modules/two-sum.js` 是手写参考实现。
