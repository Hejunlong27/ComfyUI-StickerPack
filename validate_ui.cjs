// Validate a UI-format workflow inside a live ComfyUI page.
// Loads it with app.loadGraphData (the same call the sidebar uses), then
// round-trips through app.graphToPrompt and compares with the API workflow.
const path = require('path');
// 需要先 npm i playwright（或在能 require 到它的目录下运行）
const PW = 'playwright';
const { chromium } = require(PW);

const SERVER = process.env.COMFY || 'http://127.0.0.1:8199';
const uiFile = process.argv[2];
const apiFile = process.argv[3];
const shot = process.argv[4] || '';

function sig(node) {
  const w = Object.entries(node.inputs || {})
    .filter(([, v]) => !Array.isArray(v))
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .sort();
  return `${node.class_type}|${w.join(',')}`;
}

(async () => {
  const ui = require(path.resolve(uiFile));
  const api = apiFile ? require(path.resolve(apiFile)) : null;

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));

  await page.goto(SERVER, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => window.app && window.app.graph && window.app.extensionManager, null, { timeout: 120000 });
  await page.waitForTimeout(2500);

  const loadResult = await page.evaluate(async (wf) => {
    try {
      await window.app.loadGraphData(wf);
      return { ok: true };
    } catch (e) {
      return { ok: false, err: String(e && e.stack || e) };
    }
  }, ui);
  console.log('loadGraphData:', loadResult.ok ? 'OK' : 'FAILED\n' + loadResult.err);
  if (!loadResult.ok) { await browser.close(); process.exit(1); }

  const counts = await page.evaluate(() => {
    const g = window.app.graph;
    return {
      nodes: g._nodes.length,
      links: (g.links || []).length !== undefined ? Object.keys(g.links || {}).length : 0,
      types: g._nodes.reduce((a, n) => (a[n.type] = (a[n.type] || 0) + 1, a), {}),
    };
  });
  console.log('graph:', counts.nodes, 'nodes,', counts.links, 'links');

  const prompt = await page.evaluate(async () => {
    const p = await window.app.graphToPrompt();
    return p.output;
  });
  const n = Object.keys(prompt).length;
  console.log('graphToPrompt:', n, 'nodes');

  if (api) {
    const want = Object.values(api).map(sig).sort();
    const got = Object.values(prompt).map(sig).sort();
    const missing = want.filter(x => !got.includes(x));
    const extra = got.filter(x => !want.includes(x));
    console.log('api nodes:', want.length, '| ui->api nodes:', got.length);
    if (missing.length) {
      console.log('MISMATCH - present in api but not reproduced by the graph:');
      missing.slice(0, 6).forEach(m => console.log('  -', m.slice(0, 220)));
    }
    if (extra.length) {
      console.log('EXTRA - produced by the graph but not in api:');
      extra.slice(0, 6).forEach(m => console.log('  +', m.slice(0, 220)));
    }
    if (!missing.length && !extra.length) console.log('ROUND TRIP: identical to the validated API workflow');
  }

  if (shot) {
    await page.evaluate(() => {
      const c = window.app.canvas;
      c.ds.scale = 0.42;
      c.ds.offset = [40, 40];
      c.setDirty(true, true);
    });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: shot, fullPage: false });
    console.log('screenshot ->', shot);
  }

  if (errors.length) {
    console.log('PAGE ERRORS:', errors.slice(0, 3));
  }
  await browser.close();
})();
