/* algoviz module runner — reports one module's trace as JSON on stdout.
 *
 * The module itself is preloaded by Node via `--require <module.js>` BEFORE this
 * file runs, so this file never loads a path of its own. It only reads what is
 * already registered on `window.AlgoVizModules` and reports it.
 *
 * Invocation (see validate.js):
 *   node --require <this file> --require <module.js> -e ""
 * with env:
 *   ALGOVIZ_MODULE_ID    which registered id to report on
 *   ALGOVIZ_INPUT_INDEX  0 = defaultInput, 1..n = testInputs[n-1], -1 = meta only
 *
 * Running each module in its own short-lived process keeps module code out of
 * the validator's heap and lets the parent enforce a timeout.
 *
 * Output: a single line, `ALGOVIZ_RESULT=<json>`, so Node's own preload noise
 * can never be confused for the payload.
 *   { ok: true,  meta, steps, stepCount, output, outputPresent }
 *   { ok: false, stage: "load"|"parse"|"run", error, meta? }
 */
"use strict";

// make sure the browser-ish global exists before the module preload registers
global.window = global.window || {};

function emit(obj) {
  process.stdout.write("ALGOVIZ_RESULT=" + JSON.stringify(obj) + "\n");
}

function describe(mod) {
  return {
    title: typeof mod.title === "string" ? mod.title : null,
    code: typeof mod.code === "string" ? mod.code : null,
    language: typeof mod.language === "string" ? mod.language : null,
    link: typeof mod.link === "string" ? mod.link : null,
    views: mod.views && typeof mod.views === "object"
      ? Object.keys(mod.views).reduce(function (acc, k) {
          acc[k] = { type: mod.views[k] && mod.views[k].type };
          return acc;
        }, {})
      : null,
    hasRun: typeof mod.run === "function",
    inputCount: 1 + ((mod.testInputs || []).length),
    expectedOutputs: Array.isArray(mod.expectedOutputs) ? mod.expectedOutputs : null,
  };
}

function report() {
  const id = process.env.ALGOVIZ_MODULE_ID || "";
  const inputIndex = Number(process.env.ALGOVIZ_INPUT_INDEX || 0);
  const mods = global.window.AlgoVizModules || {};
  const mod = mods[id];

  if (!mod) {
    emit({
      ok: false, stage: "load",
      error: `window.AlgoVizModules["${id}"] not defined`,
      registered: Object.keys(mods),
    });
    return;
  }

  const meta = describe(mod);

  if (inputIndex < 0) {
    emit({ ok: true, meta: meta, steps: null, output: null });
    return;
  }
  if (!meta.hasRun) {
    emit({ ok: false, stage: "load", error: "run() missing", meta: meta });
    return;
  }

  const texts = [mod.defaultInput].concat(mod.testInputs || []);
  const text = texts[inputIndex];

  let input;
  try {
    input = mod.parseInput ? mod.parseInput(text) : text;
  } catch (e) {
    emit({ ok: false, stage: "parse", error: (e && e.message) || String(e), meta: meta });
    return;
  }

  let res;
  try {
    res = mod.run(input);
  } catch (e) {
    emit({ ok: false, stage: "run", error: (e && e.message) || String(e), meta: meta });
    return;
  }

  const steps = Array.isArray(res) ? res : (res && res.steps);
  const output = Array.isArray(res) ? undefined : (res && res.output);

  // ship only the fields the validator checks, so long traces stay cheap to pipe
  const slim = Array.isArray(steps)
    ? steps.map(function (s) {
        return {
          line: s && s.line,
          msg: s && s.msg,
          viewKeys: s && s.views && typeof s.views === "object" ? Object.keys(s.views) : null,
          hasViews: !!(s && s.views && typeof s.views === "object"),
        };
      })
    : null;

  emit({
    ok: true,
    meta: meta,
    steps: slim,
    stepCount: Array.isArray(steps) ? steps.length : 0,
    output: output === undefined ? null : output,
    outputPresent: output !== undefined,
  });
}

// the module is preloaded after this file, so defer until preloads are done
process.once("beforeExit", function () {
  if (global.__algovizReported) return;
  global.__algovizReported = true;
  try {
    report();
  } catch (e) {
    emit({ ok: false, stage: "run", error: (e && e.message) || String(e) });
  }
});
