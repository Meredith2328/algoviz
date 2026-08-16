/* Build modules.json for the algoviz site: [{id, title}, ...]
 * Usage: node tools/build_modules_json.js <out.json> */
"use strict";
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const modsDir = path.join(root, "modules");
const out = process.argv[2];
if (!out) { console.error("usage: node build_modules_json.js <out.json>"); process.exit(2); }

const list = [];
for (const f of fs.readdirSync(modsDir).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"))) {
  if (!f.endsWith(".js")) continue;
  const src = fs.readFileSync(path.join(modsDir, f), "utf8");
  const m = /title:\s*"((?:[^"\\]|\\.)*)"/.exec(src) ||
            /title:\s*'((?:[^'\\]|\\.)*)'/.exec(src);
  list.push({ id: path.basename(f, ".js"), title: m ? m[1] : path.basename(f, ".js") });
}
fs.writeFileSync(out, JSON.stringify(list), "utf8");
console.log(`modules.json: ${list.length} modules -> ${out}`);
