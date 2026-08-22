# algoviz 模块格式规范（v1）

一个模块是一个自包含 JS 文件，注册到全局：

```js
(function (global) {
  global.AlgoVizModules = global.AlgoVizModules || {};
  global.AlgoVizModules["<id>"] = {
    title: "题号 标题 · 解法名",       // 必填，展示在播放器头部
    language: "python",               // 可选，"python" | "cpp"，缺省 "python"
    link: "https://leetcode.cn/problems/...", // 可选，原题链接（仅 LeetCode/洛谷会渲染跳转按钮）
    code: "原始 Python 代码（逐字保留，不改任何字符）",  // 必填
    defaultInput: "可编辑文本，每行一个变量",             // 必填
    inputHint: "输入格式说明",          // 可选
    testInputs: ["...", "..."],        // 可选，额外测试输入
    expectedOutputs: ["...", "..."],   // 可选，与 [defaultInput, ...testInputs] 一一对应的期望输出

    views: {                           // 必填，2-4 个视图
      vars: { type: "vars", title: "变量" },
      xxx: { type: "array", title: "nums" }
    },

    parseInput: function (text) { /* text -> input 对象；缺省时直接传原文 */ },
    run: function (input) { /* input -> { steps, output } 或 steps 数组 */ }
  };
})(typeof window !== "undefined" ? window : this);
```

## run() 与步骤

`run(input)` 同步执行并返回轨迹：

- 返回 `{ steps: [...], output: <最终输出> }`（推荐，output 会显示在 OUTPUT 框）
- 或直接返回 steps 数组

每个 step：

```js
{
  line: 4,        // 必填：1-based，对应 code 字段的行号（播放器会高亮该行）
  msg: "简体中文解释",   // 必填：一句话说明这一步在做什么
  views: {        // 至少一个视图的状态；未列出的视图显示"（未变化）"
    vars: { i: 0, val: 2 },
    nums: { items: [...], highlights: [0] }
  }
}
```

要点：

1. JS 实现必须与 Python 逻辑完全等价（同输入同输出），但要把 Python 里的一行
   拆成有教学价值的步骤：每条语句 1-2 步即可，不要每个赋值记多步。
2. `line` 必须指向用户原始 Python 代码中正在"执行"的那一行——这是调试器式高亮的核心。
3. 步骤总数对小型输入控制在 30-200；绝不允许超过 100000。
4. 不确定的库行为（如 `collections.deque`）用等价 JS 结构模拟，行为要对。
5. 模块必须无外部依赖（不许 import/require/fetch），纯 ES5 语法（var、function，
   不用箭头函数、模板字符串、let/const、Set/Map 之外的 ES6+ API 可以用 JSON/Array 常规方法）。

## 语言与链接（language / link）

- `language`：`"python"`（缺省）或 `"cpp"`。播放器据此选语法高亮器并在标题旁显示
  `Python` / `C++` 徽标。**C++ 模块务必设 `language: "cpp"`**，否则代码会按 Python 规则高亮。
- `link`：原题链接（可选）。只对 LeetCode（`leetcode.cn` / `leetcode.com`）和
  洛谷（`luogu.com.cn`）渲染「◈ 原题」跳转按钮，其他域名不显示跳转。

C++ 模块同样要满足 run() 等价、line 对准原始代码、步骤数适中等约束；视图类型不受语言影响。

## 视图类型与状态形状

### vars — 变量名值对
状态：`{ 名: 值, ... }`；要把某个标成"刚变化"用 `{ value: 值, __hot: true }`。

### array — 一维数组
`{ items: [...], highlights: [i], ok: [i], bad: [i], pointers: { 名: 下标 }, showIndex: true/false }`

### bars — 数轴上的区间条（区间调度/会议室类）
`{ bars: [{ start, end, label?, status? }, ...], highlights: [i], axis: { min, max, ticks } }`

### grid — 二维矩阵
`{ cells: [[...], ...], highlights: [[r,c]], ok: [[r,c]], bad: [[r,c]] }`

### stack / queue
`{ items: [...], highlights: [i] }`（stack 底部在下方）

### tree — 二叉树/多叉树
`{ root: { val, children: [{...}], status? } }`，status ∈ "hi"/"ok"/"bad"

### heap — 数组表示的最小堆（自动画成完全二叉树 + 数组）
`{ items: [...], highlights: [i] }`

### graph — 图
`{ nodes: [{ id, val?, x?, y? }], edges: [[id1, id2]], highlights: [id] }`

### output — 最终答案框（播放器自动渲染 run 返回的 output，一般不用手动加）

### callstack — 递归调用栈
`{ frames: ["f(4)", "f(3)", ...] }`

### text — 自由文本说明
`"任意文本"` 或 `{ text: "..." }`

## parseInput

把编辑器里的多行文本解析成 input 对象。约定每行 `名字 = JSON值`，例如：

```js
parseInput: function (text) {
  var env = {};
  text.split(/\n/).forEach(function (line) {
    var m = /^\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*$/.exec(line);
    if (!m) return;
    try { env[m[1]] = JSON.parse(m[2].replace(/'/g, '"')); }
    catch (e) { env[m[1]] = m[2]; }
  });
  if (!Array.isArray(env.nums)) throw new Error("缺少 nums = [...]");
  return env;
}
```

抛 Error 会显示在编辑弹窗里，所以校验要给清楚的中文提示。

## 输出（output）

字符串或 JSON 可序列化的值。建议直接 `JSON.stringify(答案)`，与期望输出比对时按字符串相等。
