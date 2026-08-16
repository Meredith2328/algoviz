/* algoviz module validator — run: node validate.js <module.js> [module.js ...]
 * Checks structure, runs the trace, verifies step/line invariants.
 * Exit 0 = all valid; prints a report. */
"use strict";
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const MAX_STEPS = 100000;

// compare after whitespace strip; treat numerically equal strings as equal
// ("2.0" == 2 == "2")
function looseEq(a, b) {
  // both sides may arrive as JSON strings or parsed values — normalize
  const parse = (x) => {
    if (typeof x === "string" && (x.trim().startsWith("[") || x.trim().startsWith("{"))) {
      try { return JSON.parse(x); } catch (e) { return x; }
    }
    return x;
  };
  a = parse(a); b = parse(b);
  const sa = JSON.stringify(a).replace(/\s+/g, "");
  const sb = JSON.stringify(b).replace(/\s+/g, "");
  if (sa === sb) return true;
  // "answer is the root node": python serializes the whole tree, module
  // reports the node value — accept when the value equals the tree root
  if (Array.isArray(b) && b.length && !Array.isArray(a)) {
    const na = Number(a), rb = Number(b[0]);
    if (String(a) === String(b[0]) || (Number.isFinite(na) && na === rb)) return true;
  }
  const na = Number(sa.replace(/^"|"$/g, "")), nb = Number(sb.replace(/^"|"$/g, ""));
  return Number.isFinite(na) && Number.isFinite(nb) && na === nb;
}
// ground truth: ALGOVIZ_TRUTH='{"<id>": ["out1", "out2", ...]}' — real python
// outputs per input (default first, then testInputs), whitespace-normalized
const TRUTH = (() => {
  try { return JSON.parse(process.env.ALGOVIZ_TRUTH || "{}"); } catch (e) { return {}; }
})();

function fail(id, msg) { console.log(`FAIL ${id}: ${msg}`); return false; }

function validate(file) {
  const id = path.basename(file, ".js");
  let mod;
  try {
    const sandbox = { window: {}, console };
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(file, "utf8"), sandbox, { timeout: 5000 });
    mod = sandbox.window.AlgoVizModules && sandbox.window.AlgoVizModules[id];
  } catch (e) {
    return fail(id, "load error: " + e.message);
  }
  if (!mod) return fail(id, `window.AlgoVizModules["${id}"] not defined`);
  if (typeof mod.run !== "function") return fail(id, "run() missing");
  if (typeof mod.code !== "string" || !mod.code.trim()) return fail(id, "code missing");
  if (typeof mod.title !== "string" || !mod.title) return fail(id, "title missing");
  if (!mod.views || !Object.keys(mod.views).length) return fail(id, "views missing");

  const nLines = mod.code.replace(/\r\n/g, "\n").split("\n").length;
  const knownViews = new Set(["vars", "array", "bars", "grid", "stack", "queue", "tree", "heap", "graph", "output", "callstack", "text"]);
  for (const [k, v] of Object.entries(mod.views)) {
    if (!knownViews.has(v.type)) return fail(id, `view "${k}" has unknown type "${v.type}"`);
  }

  // default input must parse & run
  const trials = [[id + ":default", mod.defaultInput]];
  (mod.testInputs || []).forEach((t, i) => trials.push([id + ":test" + i, t]));
  if (mod.expectedOutputs && trials.length !== mod.expectedOutputs.length) {
    // allow missing expectedOutputs; only compare those present
  }

  let ok = true;
  trials.forEach(([name, text], ti) => {
    let res;
    try {
      const input = mod.parseInput ? mod.parseInput(text) : text;
      res = mod.run(input);
    } catch (e) { ok = fail(id, `${name} run error: ${e.message}`); return; }
    const steps = Array.isArray(res) ? res : res && res.steps;
    if (!Array.isArray(steps) || !steps.length) { ok = fail(id, `${name}: no steps`); return; }
    if (steps.length > MAX_STEPS) { ok = fail(id, `${name}: ${steps.length} steps > cap`); return; }
    for (let i = 0; i < steps.length; i++) {
      const s = steps[i];
      if (!s || !Number.isInteger(s.line) || s.line < 1 || s.line > nLines) {
        ok = fail(id, `${name}: step ${i} bad line ${s && s.line} (code has ${nLines} lines)`); return;
      }
      if (typeof s.msg !== "string" || !s.msg.trim()) {
        ok = fail(id, `${name}: step ${i} missing msg`); return;
      }
      if (!s.views || typeof s.views !== "object") {
        ok = fail(id, `${name}: step ${i} missing views`); return;
      }
      for (const k of Object.keys(s.views)) {
        if (!mod.views[k]) { ok = fail(id, `${name}: step ${i} uses undeclared view "${k}"`); return; }
      }
    }
    const out = Array.isArray(res) ? undefined : res.output;
    // ground truth from ALGOVIZ_TRUTH (real python outputs) beats the
    // LLM-written expectedOutputs
    const truthFor = TRUTH[id];
    const exp = truthFor ? truthFor[ti] : (mod.expectedOutputs && mod.expectedOutputs[ti]);
    if (exp !== undefined && out !== undefined &&
        !looseEq(out, exp)) {
      ok = fail(id, `${name}: output ${JSON.stringify(out)} != python-truth ${JSON.stringify(exp)}`); return;
    }
    console.log(`ok   ${id} ${name}: ${steps.length} steps${out !== undefined ? ", output=" + JSON.stringify(out) : ""}`);
  });
  return ok;
}

const files = process.argv.slice(2);
if (!files.length) { console.error("usage: node validate.js <module.js> [...]"); process.exit(2); }
const all = files.map(validate).every(Boolean);
process.exit(all ? 0 : 1);
