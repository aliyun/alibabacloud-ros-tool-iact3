const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');
const yaml = require('js-yaml');

const root = path.resolve(__dirname, '../../iact3/web/static');
const sources = new Map();
function setup() {
  const dom = new JSDOM(fs.readFileSync(path.join(root, 'index.html'), 'utf8'), {
    url: 'http://localhost/', runScripts: 'outside-only',
  });
  const { window } = dom;
  window.jsyaml = yaml;
  window.__coverage__ = global.__coverage__ = global.__coverage__ || {};
  const original = window.document.addEventListener.bind(window.document);
  window.document.addEventListener = (type, listener, ...args) => {
    if (type !== 'DOMContentLoaded') original(type, listener, ...args);
  };
  const context = dom.getInternalVMContext();
  for (const name of ['i18n.js', 'app.js']) {
    const filename = path.join(root, name);
    if (!sources.has(filename)) {
      let source = fs.readFileSync(filename, 'utf8');
      if (process.env.IACT3_COVERAGE) {
        source = require('istanbul-lib-instrument').createInstrumenter().instrumentSync(source, filename);
      }
      sources.set(filename, source);
    }
    vm.runInContext(sources.get(filename), context, { filename });
  }
  window.document.addEventListener = original;
  return { window, context, close: () => window.close() };
}

test('configuration helpers parse ROS YAML and preserve test settings', () => {
  const { window: w, close } = setup();
  try {
    const full = w.buildFullConfigYaml('parameters:\n  Zone: !Ref Region', 'cn-a, cn-b', 'demo');
    // Simple YAML has no intrinsic tag in the parameters editor; full templates do.
    assert.equal(full, 'parameters:\n  Zone: !Ref Region');
    const config = w.buildFullConfigYaml('parameters: {Count: 3}', 'cn-a, cn-b', 'demo');
    const parsed = yaml.load(config);
    assert.equal(parsed.project.name, 'demo');
    assert.deepEqual(parsed.tests.default.regions, ['cn-a', 'cn-b']);
    assert.equal(parsed.tests.default.parameters.Count, 3);
    assert.equal(w.validateTemplateFormat('Value: !Ref Region'), null);
    assert.ok(w.validateTemplateFormat('Value: ['));
    assert.deepEqual(Array.from(w.regionsFromConfig(config)), ['cn-a', 'cn-b']);
    assert.equal(w.regionsFromConfig('bad: ['), null);
  } finally { close(); }
});

test('ROS YAML shorthand tags round trip scalar and sequence intrinsic functions', () => {
  const { window: w, context, close } = setup();
  try {
    const schema = vm.runInContext('ROS_SCHEMA', context);
    const source = 'RefValue: !Ref Region\nJoined: !Join ["-", [one, two]]\nPlain: {Other: value}\n';
    const parsed = yaml.load(source, { schema });
    assert.deepEqual(JSON.parse(JSON.stringify(parsed.RefValue)), { Ref: 'Region' });
    assert.deepEqual(JSON.parse(JSON.stringify(parsed.Joined)), { 'Fn::Join': ['-', ['one', 'two']] });
    const dumped = yaml.dump(parsed, { schema });
    assert.match(dumped, /!Ref/);
    assert.match(dumped, /!Join/);
    assert.deepEqual(yaml.load(dumped, { schema }).Plain, { Other: 'value' });
  } finally { close(); }
});

test('configuration builder handles bare parameters, comments and missing YAML parser', () => {
  const { window: w, close } = setup();
  try {
    let config = yaml.load(w.buildFullConfigYaml('Name: example', 'cn-a, ,cn-b', 'demo'));
    assert.deepEqual(config.tests.default.parameters, { Name: 'example' });
    assert.deepEqual(config.tests.default.regions, ['cn-a', 'cn-b']);
    config = yaml.load(w.buildFullConfigYaml('# comment only', '', 'demo'));
    assert.equal(config.project.name, 'demo');
    assert.equal(config.tests, undefined);
    assert.equal(w.buildFullConfigYaml('null', '', ''), 'null');
    w.jsyaml = undefined;
    assert.equal(w.buildFullConfigYaml('parameters: {Name: user}', 'cn-a', 'demo'), 'parameters: {Name: user}');
  } finally { close(); }
});

test('configuration builder ignores blank regions in minimal and parameter-only configurations', () => {
  const { window: w, close } = setup();
  try {
    const minimal = yaml.load(w.buildFullConfigYaml('', 'cn-a, , cn-b', 'demo'));
    assert.deepEqual(minimal.tests.default.regions, ['cn-a', 'cn-b']);
    const withParameters = yaml.load(w.buildFullConfigYaml('parameters: {Name: demo}', '', 'demo'));
    assert.deepEqual(withParameters.tests.default.regions, []);
    assert.equal(withParameters.tests.default.parameters.Name, 'demo');
  } finally { close(); }
});

test('template and region helpers work before optional data is loaded', () => {
  const { window: w, context, close } = setup();
  try {
    w.jsyaml = undefined;
    assert.equal(w.validateTemplateFormat('Resources: {}'), null);
    vm.runInContext('state.regions = null', context);
    assert.equal(w.regionName({ id: 'cn-a', name: 'A' }), 'A');
    assert.equal(w.regionName('cn-a'), 'cn-a');
    const editor = w.document.getElementById('project-edit-template');
    editor.value = '[{"value": 1}]';
    assert.equal(w.getPeTemplateLanguage(), 'json');
    editor.value = 'Resources: {}';
    assert.equal(w.getPeTemplateLanguage(), 'yaml');
  } finally { close(); }
});

test('region extraction prefers the default test and tolerates missing configuration', () => {
  const { window: w, close } = setup();
  try {
    const config = 'tests:\n  other: {regions: [cn-other]}\n  default: {regions: [cn-a, cn-b]}';
    assert.deepEqual(Array.from(w.regionsFromConfig(config)), ['cn-a', 'cn-b']);
    assert.deepEqual(Array.from(w.regionsFromConfig('tests: {}')), []);
    assert.deepEqual(Array.from(w.regionsFromConfig('tests: {default: null}')), []);
    assert.equal(w.regionsFromConfig(''), null);
    assert.equal(w.regionsFromConfig('project: {}'), null);
    w.jsyaml = undefined;
    assert.equal(w.regionsFromConfig(config), null);
  } finally { close(); }
});

test('confirmation requires the expected text and removes handlers after closing', async () => {
  const { window: w, close } = setup();
  try {
    const result = w.showConfirm('Delete?', { danger: true, verify: { expected: 'demo', hint: 'type demo' } });
    const modal = w.document.getElementById('confirm-modal');
    const input = w.document.getElementById('confirm-modal-verify-input');
    const ok = w.document.getElementById('confirm-modal-ok');
    assert.ok(modal.classList.contains('open'));
    assert.equal(ok.disabled, true);
    input.value = 'demo';
    input.dispatchEvent(new w.Event('input'));
    assert.equal(ok.disabled, false);
    ok.click();
    assert.equal(await result, true);
    assert.equal(modal.classList.contains('open'), false);
    const cancelled = w.showConfirm('Cancel?');
    w.document.getElementById('confirm-modal-cancel').click();
    assert.equal(await cancelled, false);
  } finally { close(); }
});

test('prompt returns trimmed input and supports escape', async () => {
  const { window: w, close } = setup();
  try {
    const input = w.document.getElementById('prompt-modal-input');
    const first = w.showPrompt({ title: 'New file', defaultValue: '  main.tf  ' });
    w.document.getElementById('prompt-modal-ok').click();
    assert.equal(await first, 'main.tf');
    const second = w.showPrompt({});
    input.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape' }));
    assert.equal(await second, null);
  } finally { close(); }
});

test('prompt dialogs support default options and cancellation', async () => {
  const { window: w, close } = setup();
  try {
    const modal = w.showPrompt();
    assert.equal(w.document.getElementById('prompt-modal-input').value, '');
    w.document.getElementById('prompt-modal-cancel').click();
    assert.equal(await modal, null);
    const inline = w.showInlinePrompt();
    assert.equal(w.document.querySelector('.tf-prompt-input').value, '');
    w.document.querySelector('.tf-prompt-cancel').click();
    assert.equal(await inline, null);
  } finally { close(); }
});

test('opening a Terraform menu dismisses existing menus and inline prompts', async () => {
  const { window: w, context, close } = setup();
  try {
    const node = w.document.createElement('div');
    node.innerHTML = '<button class="tf-node-more">...</button>';
    w.document.body.appendChild(node);
    w.showTfNodeMenu(node, 'main.tf', false);
    const oldMenu = w.document.querySelector('.tf-node-menu');
    w.showTfNodeMenu(node, 'vars.tf', false);
    assert.equal(oldMenu.isConnected, false);
    const prompt = w.showInlinePrompt({ anchorEl: node });
    const popover = w.document.querySelector('.tf-prompt-popover');
    const cancel = popover.querySelector('.tf-prompt-cancel');
    w.showTfNodeMenu(node, 'main.tf', false);
    assert.equal(popover.isConnected, false);
    assert.equal(vm.runInContext('state._tfInlinePrompt', context), null);
    cancel.click();
    assert.equal(await prompt, null);
  } finally { close(); }
});

test('API helper handles JSON, text and error responses', async () => {
  const { window: w, close } = setup();
  try {
    let request;
    w.fetch = async (path, opts) => {
      request = { path, opts };
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => '{"ok":true}' };
    };
    assert.equal((await w.api('POST', '/api/test', { a: 1 })).ok, true);
    assert.equal(request.opts.body, '{"a":1}');
    assert.equal(request.opts.headers['Content-Type'], 'application/json');
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'text/plain' }, text: async () => 'log' });
    assert.equal(await w.api('GET', '/api/log'), 'log');
    w.fetch = async () => ({ ok: false, status: 400, headers: { get: () => 'application/json' }, text: async () => '{"error":"invalid"}' });
    await assert.rejects(w.api('GET', '/api/fail'), /invalid/);
  } finally { close(); }
});

test('editor validates names and updates line numbers and button state', () => {
  const { window: w, close } = setup();
  try {
    const name = w.document.getElementById('pg-project-name-input');
    const button = w.document.getElementById('btn-pg-save-confirm');
    w.bindProjectNameLive(name, button);
    name.value = 'invalid/name';
    name.dispatchEvent(new w.Event('input'));
    assert.equal(button.disabled, true);
    name.value = 'valid-name';
    name.dispatchEvent(new w.Event('input'));
    assert.equal(button.disabled, false);
    const editor = w.document.getElementById('template-editor');
    editor.value = 'one\ntwo\nthree';
    w.updateTemplateLineNumbers();
    assert.equal(w.document.getElementById('template-line-numbers').textContent, '123');
    w.setBtnLoading(button, true);
    assert.equal(button.disabled, true);
    w.setBtnLoading(button, false);
    assert.equal(button.disabled, false);
  } finally { close(); }
});

test('syntax highlighting keeps content readable when the highlighter fails', () => {
  const { window: w, close } = setup();
  try {
    const editor = w.document.getElementById('template-editor');
    const code = w.document.getElementById('template-highlight');
    editor.value = 'value\n';
    w.hljs = { highlight: () => ({ value: '<span>value</span>' }) };
    w.highlightEditor('template-editor', 'template-highlight', 'yaml');
    assert.equal(code.querySelector('span').textContent, 'value');
    assert.ok(code.textContent.endsWith('\n'));
    w.hljs = { highlight: () => { throw new Error('bad grammar'); } };
    editor.value = '<unsafe>';
    w.highlightEditor('template-editor', 'template-highlight', 'yaml');
    assert.equal(code.textContent, '<unsafe>');
    assert.equal(code.querySelector('unsafe'), null);
    const pre = w.document.createElement('pre');
    pre.className = 'old language-json hljs';
    w.highlightPre(pre, '<unsafe>', 'yaml');
    assert.equal(pre.textContent, '<unsafe>');
    assert.ok(pre.classList.contains('language-yaml'));
    assert.equal(pre.classList.contains('language-json'), false);
    w.highlightPre(pre, '', 'yaml');
    assert.equal(pre.textContent, '\n');
  } finally { close(); }
});

test('editor scroll synchronization tolerates missing optional highlight elements', () => {
  const { window: w, close } = setup();
  try {
    const pairs = [
      ['project-edit-template', 'pe-template-highlight'],
      ['project-edit-tf-template', 'pe-tf-highlight'],
      ['project-edit-config', 'pe-config-highlight'],
    ];
    for (const [editorId, highlightId] of pairs) {
      const editor = w.document.getElementById(editorId);
      const highlight = w.document.getElementById(highlightId);
      editor.scrollTop = 23;
      editor.scrollLeft = 11;
      w.syncPeHighlightScroll();
      assert.equal(highlight.parentElement.scrollTop, 23);
      assert.equal(highlight.parentElement.scrollLeft, 11);
      highlight.remove();
      w.syncPeHighlightScroll();
      editor.remove();
      w.syncPeHighlightScroll();
    }
  } finally { close(); }
});

test('live project name validation shows and clears its hint', () => {
  const { window: w, close } = setup();
  try {
    const input = w.document.getElementById('project-edit-name');
    const button = w.document.getElementById('project-edit-save');
    const hint = input.parentElement.querySelector('.project-edit-name-hint');
    w.bindProjectNameLive(input, button);
    input.value = 'bad/name';
    input.dispatchEvent(new w.Event('input'));
    assert.equal(button.disabled, true);
    assert.ok(hint.classList.contains('visible'));
    assert.ok(hint.textContent);
    input.value = '';
    input.dispatchEvent(new w.Event('input'));
    assert.equal(button.disabled, false);
    assert.equal(hint.textContent, '');
    assert.equal(hint.classList.contains('visible'), false);
    input.value = 'valid-name';
    input.dispatchEvent(new w.Event('input'));
    assert.equal(button.disabled, false);
  } finally { close(); }
});

test('pagination renders ellipses and dispatches selected pages and page size', () => {
  const { window: w, close } = setup();
  try {
    const container = w.document.createElement('div');
    w.document.body.appendChild(container);
    container.innerHTML = w.buildPaginationHTML(5, 10, 100, 10, [10, 20], 'tasks');
    assert.equal(container.querySelectorAll('.pagination-ellipsis').length, 2);
    const pages = [], sizes = [];
    w.bindPaginationEvents(container, 10, page => pages.push(page), size => sizes.push(size));
    container.querySelector('[data-page="6"]').click();
    container.querySelector('.pagination-per-page-trigger').click();
    assert.ok(container.querySelector('.pagination-per-page-wrapper').classList.contains('open'));
    container.querySelector('.pagination-per-page-option[data-value="20"]').click();
    assert.deepEqual(pages, [6]);
    assert.deepEqual(sizes, [20]);
  } finally { close(); }
});

test('pagination disables navigation at boundaries and omits unnecessary ellipses', () => {
  const { window: w, close } = setup();
  try {
    const container = w.document.createElement('div');
    container.innerHTML = w.buildPaginationHTML(1, 3, 21, 10, [10, 20], 'tasks');
    let nav = container.querySelectorAll('.pagination-nav-btn');
    assert.equal(nav[0].disabled, true);
    assert.equal(nav[1].disabled, false);
    assert.equal(container.querySelectorAll('.pagination-ellipsis').length, 0);
    container.innerHTML = w.buildPaginationHTML(10, 10, 100, 10, [10, 20], 'tasks');
    nav = container.querySelectorAll('.pagination-nav-btn');
    assert.equal(nav[0].disabled, false);
    assert.equal(nav[1].disabled, true);
    assert.equal(container.querySelectorAll('.pagination-ellipsis').length, 1);
  } finally { close(); }
});

test('resource price rows include associations and preserve service errors', () => {
  const { window: w, close } = setup();
  try {
    const result = w.extractCostRows({ region: 'cn-a', price: {
      Instance: { Type: 'ALIYUN::ECS::Instance', Result: {
        Order: { Currency: 'CNY', TradeAmount: 2 }, OrderSupplement: { ChargeType: 'PostPaid', Quantity: 1 },
        AssociationProducts: { Disk: { Type: 'ALIYUN::ECS::Disk', Result: { Order: { TradeAmount: 1 } } } },
      } },
      Failed: { Success: false, Result: { Code: 'Denied', Message: 'no permission' } },
    } });
    assert.equal(result.rows.length, 2);
    assert.equal(result.rows[0].resource, 'Instance');
    assert.equal(result.rows[1].resource, '');
    assert.equal(result.errors[0].code, 'Denied');
    assert.match(w.formatCostMoney(2, 'CNY', '/hour'), /¥2/);
    assert.equal(w.formatCostMoney(null, 'CNY', ''), '-');
    assert.equal(w.formatCostDiscount(0, 'CNY'), '-');
    assert.equal(w.formatDuration('PostPaid', 1, 'Month'), '-');
    assert.equal(w.formatPeriodUnit('Custom'), '/Custom');
  } finally { close(); }
});

test('cost formatting handles missing fields, zero amounts and alternate billing units', () => {
  const { window: w, close } = setup();
  try {
    const result = w.extractCostRows({ price: {
      Basic: { Result: { Order: { ChargeType: 'PrePaid', OriginalAmount: 0, DiscountAmount: 0, TradeAmount: 0 },
        OrderSupplement: { PeriodUnit: 'Month', Quantity: 0 } } },
      Unknown: { Success: false },
    } });
    assert.equal(result.rows[0].region, '-');
    assert.equal(result.rows[0].chargeType, 'PrePaid');
    assert.equal(result.rows[0].periodUnit, 'Month');
    assert.equal(result.rows[0].quantity, 0);
    assert.equal(result.rows[0].tradeAmount, 0);
    assert.equal(result.errors[0].code, 'Error');
    assert.equal(w.formatCostAttributes(null), '-');
    assert.match(w.formatCostAttributes([{}]), /: /);
    assert.equal(w.formatBillingMethod('custom'), 'custom');
    assert.equal(w.formatDuration('Buy', 1, 'Month'), '-');
    assert.equal(w.formatDuration('PrePaid', 0, 'Month'), '-');
    assert.equal(w.formatPeriodUnit(''), '');
    assert.equal(w.formatMoneyRaw('not a number'), '0');
    assert.equal(w.formatCostMoney(undefined, 'USD', ''), '-');
    assert.equal(w.formatCostMoney('', 'USD', ''), '-');
    assert.match(w.formatCostMoney(0, 'USD', ''), /\$0/);
  } finally { close(); }
});

test('stack status and version diff classify changes correctly', () => {
  const { window: w, close } = setup();
  try {
    assert.equal(w.isStackFailed({ status: 'CREATE_ROLLBACK_COMPLETE' }), true);
    assert.equal(w.isRunSettled({ status: 'completed', stacks: [{ status: 'DELETE_IN_PROGRESS' }] }), false);
    assert.equal(w.isRunSettled({ status: 'completed', stacks: [{ status: 'DELETE_COMPLETE' }] }), true);
    const stats = w.calcStackStats([{ launch_succeeded: true, status: 'CREATE_COMPLETE' },
                                    { launch_succeeded: false, status: 'CREATE_FAILED' }]);
    assert.equal(stats.ratio, 50);
    const diff = w.computeLineDiff('one\ntwo', 'one\nthree');
    assert.deepEqual(Array.from(diff, line => line.type), ['unchanged', 'removed', 'added']);
    const container = w.document.createElement('div');
    w.renderDiffView(container, 'one\ntwo', 'one\nthree', 'old', 'new');
    assert.match(container.textContent, /three/);
  } finally { close(); }
});

test('region selector filters, selects visible entries and clears them', () => {
  const { window: w, context, close } = setup();
  try {
    const selected = [];
    w.regionChanged = values => selected.push(Array.from(values));
    const selector = vm.runInContext("new RegionSelect('pg-region-trigger', 'pg-region-dropdown', regionChanged)", context);
    selector.setData([{ id: 'cn-hangzhou', name: 'Hangzhou' }, { id: 'cn-shanghai', name: 'Shanghai' },
                      { id: 'ap-tokyo', name: 'Tokyo' }]);
    selector.toggle();
    const dropdown = w.document.getElementById('pg-region-dropdown');
    assert.ok(dropdown.classList.contains('open'));
    const search = dropdown.querySelector('.region-search');
    search.value = 'cn-';
    search.dispatchEvent(new w.Event('input'));
    assert.equal(dropdown.querySelectorAll('.region-option').length, 2);
    dropdown.querySelector('.region-select-all').click();
    assert.deepEqual(Array.from(selector.getSelected()), ['cn-hangzhou', 'cn-shanghai']);
    dropdown.querySelector('.region-clear-all').click();
    assert.deepEqual(Array.from(selector.getSelected()), []);
    assert.equal(selected.length, 2);
    search.value = '';
    search.dispatchEvent(new w.Event('input'));
    assert.equal(dropdown.querySelectorAll('.region-option').length, 3);
    dropdown.querySelector('.region-select-all').click();
    assert.equal(selector.getSelected().length, 3);
    dropdown.querySelector('.region-clear-all').click();
    assert.deepEqual(Array.from(selector.getSelected()), []);
    selector.close();
    assert.equal(dropdown.classList.contains('open'), false);
  } finally { close(); }
});

test('run payload uses selected regions and editor content for ROS and Terraform', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = { getSelected: () => ['cn-a', 'cn-b'] }", context);
    w.document.getElementById('config-editor').value = 'parameters: {Count: 2}';
    w.document.getElementById('template-editor').value = 'Resources: {}';
    let payload = w.getRunPayload();
    assert.equal(payload.regions, 'cn-a,cn-b');
    assert.equal(payload.template_content, 'Resources: {}');
    assert.equal(yaml.load(payload.config_content).tests.default.parameters.Count, 2);
    assert.equal(w.isTemplateEmpty(), false);
    vm.runInContext("state.tfMode = true; state.tfFiles = {'main.tf': 'old', 'folder/': ''}; state.tfActiveFile = 'main.tf'", context);
    w.document.getElementById('template-editor').value = 'resource "new" {}';
    payload = w.getRunPayload();
    assert.equal(payload.template_files['main.tf'], 'resource "new" {}');
    assert.equal(Object.hasOwn(payload.template_files, 'folder/'), false);
  } finally { close(); }
});

test('run payload handles an empty Terraform workspace with no active file', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}; state.tfMode = true; state.tfFiles = {}; state.tfActiveFile = null", context);
    const payload = w.getRunPayload();
    assert.equal(Object.keys(payload.template_files).length, 0);
    assert.equal(payload.template_content, undefined);
    assert.equal(w.isTemplateEmpty(), true);
  } finally { close(); }
});

test('template emptiness accounts for whitespace and Terraform directory entries', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => []}", context);
    w.document.getElementById('template-editor').value = '  \n';
    assert.equal(w.isTemplateEmpty(), true);
    w.document.getElementById('template-editor').value = 'Resources: {}';
    assert.equal(w.isTemplateEmpty(), false);
    w.enterTfMode({ 'empty.tf': '   ', 'folder/': '' });
    assert.equal(w.isTemplateEmpty(), true);
    w.document.getElementById('template-editor').value = 'resource {}';
    assert.equal(w.isTemplateEmpty(), false);
    assert.equal(w.getRunPayload().template_files['empty.tf'], 'resource {}');
    assert.equal(Object.hasOwn(w.getRunPayload().template_files, 'folder/'), false);
  } finally { close(); }
});

test('initialization loads regions, samples and settings from API', async () => {
  const { window: w, context, close } = setup();
  try {
    const requests = [];
    w.fetch = async path => {
      requests.push(path);
      let result = {};
      if (path.startsWith('/api/regions')) result = { regions: [{ id: 'cn-hangzhou', name: 'Hangzhou' }] };
      if (path === '/api/samples') result = { samples: [{ id: 'sample', name: 'Sample' }] };
      if (path === '/api/settings') result = { settings: { source: 'env' } };
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(result) };
    };
    await w.init();
    assert.ok(requests.some(path => path.startsWith('/api/regions')));
    assert.ok(requests.includes('/api/samples'));
    assert.ok(requests.includes('/api/settings'));
    assert.equal(w.document.getElementById('sample-select').options.length, 1);
    assert.deepEqual(Array.from(vm.runInContext('state.pgRegionSelect.getSelected()', context)), ['cn-hangzhou']);
    assert.equal(w.ensureCredentials(), true);
    w.stopTaskPolling();
  } finally { close(); }
});

test('initialization tolerates empty service responses and detects browser language', async () => {
  const { window: w, context, close } = setup();
  try {
    Object.defineProperty(w.navigator, 'language', { value: 'zh-CN', configurable: true });
    w.api = async () => ({});
    w.loadSettings = async () => {};
    w.startTaskPolling = () => {};
    await w.init();
    assert.equal(vm.runInContext('state.lang', context), 'zh');
    assert.equal(vm.runInContext('state.regions.length', context), 0);
    assert.equal(vm.runInContext('state.samples.length', context), 0);
    assert.equal(w.document.getElementById('sample-select').options.length, 0);
    vm.runInContext("state.pgRegionSelect = null; state.taskStatusSelect = null; state.actionResults.cost = {title:'old'}; state.lastCostPrices = []; state.currentAction = 'run'", context);
    w.document.getElementById('result-cost').remove();
    w.t = () => '';
    w.dispatchEvent(new w.CustomEvent('iact3-lang-change'));
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(vm.runInContext('state.lang', context), 'en');
    assert.equal(vm.runInContext('state.actionResults.cost.title', context), 'Cost Estimate Result');
  } finally { close(); }
});

test('initialization reports failed region loading and still loads settings', async () => {
  const { window: w, close } = setup();
  try {
    const requests = [], notices = [];
    w.fetch = async path => {
      requests.push(path);
      if (path.startsWith('/api/regions')) throw new Error('regions unavailable');
      const data = path === '/api/samples' ? {} : { settings: { source: 'env' } };
      return { ok: true, status: 200, headers: { get: () => 'application/json' },
        text: async () => JSON.stringify(data) };
    };
    w.toast = (message, type) => notices.push([message, type]);
    await w.init();
    assert.ok(requests.includes('/api/settings'));
    assert.ok(notices.some(([message, type]) => message === 'regions unavailable' && type === 'error'));
    assert.equal(w.ensureCredentials(), true);
    w.stopTaskPolling();
  } finally { close(); }
});

test('task list escapes names and maintains checkbox selection', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext(`state.tasks = [
      { id: 'a', name: '<unsafe>', status: 'running', progress: 30, created_at: '2026-01-01T00:00:00Z' },
      { id: 'b', name: 'Done', status: 'completed', progress: 100, created_at: '2026-01-01T00:00:00Z' }
    ]; state.taskTotal = 2`, context);
    w.renderTasks();
    const list = w.document.getElementById('tasks-list');
    assert.equal(list.querySelectorAll('tr').length, 2);
    assert.ok(list.textContent.includes('<unsafe>'));
    assert.equal(list.querySelector('unsafe'), null);
    const checkbox = list.querySelector('.task-row-checkbox');
    checkbox.checked = true;
    checkbox.dispatchEvent(new w.Event('change'));
    assert.equal(w.document.getElementById('btn-batch-delete-task').disabled, false);
    checkbox.checked = false;
    checkbox.dispatchEvent(new w.Event('change'));
    assert.equal(w.document.getElementById('btn-batch-delete-task').disabled, true);
  } finally { close(); }
});

test('task list shows report links and clears selection controls for an empty list', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.tasks = [{id:'run', name:'Example', status:'completed', report_url:'/outputs/report.html'}]; state.taskTotal = 1", context);
    w.renderTasks();
    const link = w.document.querySelector('#tasks-list .btn-view-report');
    assert.equal(link.getAttribute('href'), '/outputs/report.html');
    assert.equal(link.target, '_blank');
    vm.runInContext('state.tasks = []; state.taskTotal = 0', context);
    w.document.getElementById('task-select-all-header').checked = true;
    w.renderTasks();
    assert.ok(w.document.querySelector('#tasks-list .empty-state'));
    assert.equal(w.document.getElementById('task-select-all-header').checked, false);
  } finally { close(); }
});

test('project list safely renders and tracks selected projects', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext(`state.projects = [
      { name: '<project>', resource_count: 1, test_count: 2, is_terraform: true },
      { name: 'other', resource_count: 0, test_count: 0, is_terraform: false }
    ]`, context);
    w.renderProjects();
    const list = w.document.getElementById('projects-list');
    assert.equal(list.querySelectorAll('tr').length, 2);
    assert.equal(list.querySelector('project'), null);
    const checkbox = list.querySelector('.project-row-checkbox');
    checkbox.checked = true;
    checkbox.dispatchEvent(new w.Event('change'));
    assert.equal(w.document.getElementById('btn-batch-delete-project').disabled, false);
    checkbox.checked = false;
    checkbox.dispatchEvent(new w.Event('change'));
    assert.equal(w.document.getElementById('btn-batch-delete-project').disabled, true);
  } finally { close(); }
});

test('Terraform project editor keeps file edits when changing active file', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.projectEditTfFiles = {'main.tf': 'initial', 'vars.tf': 'variables', 'sub/': ''}; state.projectEditTfActiveFile = 'main.tf'", context);
    const editor = w.document.getElementById('project-edit-tf-template');
    editor.value = 'changed';
    w.selectProjectEditTfFile('vars.tf');
    assert.equal(editor.value, 'variables');
    assert.equal(vm.runInContext("state.projectEditTfFiles['main.tf']", context), 'changed');
    assert.equal(w.document.querySelectorAll('#project-edit-tf-file-tree .tf-tree-node').length, 3);
    assert.equal(w.hasValidTfFiles({ 'main.tf': '' }), false);
    assert.equal(w.hasValidTfFiles({ 'main.tf': 'resource {}' }), true);
    assert.equal(w.isTerraformProject({ template_files: { 'main.tf': 'resource {}' } }), true);
  } finally { close(); }
});

test('custom select updates selection and reports user choices', () => {
  const { window: w, close } = setup();
  try {
    const container = w.document.createElement('div');
    container.id = 'sample-custom-select';
    container.className = 'custom-select';
    container.innerHTML = '<button class="custom-select-trigger"><span class="custom-select-text"></span></button><div class="custom-select-dropdown"></div>';
    w.document.body.appendChild(container);
    const selected = [];
    w.renderCustomSelectOptions(container.id, [{ value: 'one', label: 'One' }, { value: 'two', label: 'Two' }], 'one');
    w.initCustomSelect(container.id, value => selected.push(value));
    container.querySelector('.custom-select-trigger').click();
    assert.ok(container.classList.contains('open'));
    container.querySelector('[data-value="two"]').click();
    assert.deepEqual(selected, ['two']);
    assert.equal(container.dataset.value, 'two');
    assert.equal(container.querySelector('.custom-select-text').textContent, 'Two');
    assert.equal(container.classList.contains('open'), false);
  } finally { close(); }
});

test('custom select allows clearing the options and ignores clicks without a selection callback', () => {
  const { window: w, close } = setup();
  try {
    const container = w.document.createElement('div');
    container.id = 'optional-callback-select';
    container.className = 'custom-select';
    container.innerHTML = '<button class="custom-select-trigger"><span class="custom-select-text"></span></button><div class="custom-select-dropdown"></div>';
    w.document.body.appendChild(container);
    w.renderCustomSelectOptions(container.id, [], 'missing');
    assert.equal(container.dataset.value, '');
    assert.equal(container.querySelector('.custom-select-text').textContent, '');
    w.renderCustomSelectOptions(container.id, [{ value: 'one', label: 'One' }], 'one');
    w.initCustomSelect(container.id);
    container.querySelector('.custom-select-trigger').click();
    assert.ok(container.classList.contains('open'));
    container.querySelector('.custom-select-trigger').click();
    assert.equal(container.classList.contains('open'), false);
    container.querySelector('.custom-select-dropdown').click();
    container.querySelector('.custom-select-option').click();
    assert.equal(container.dataset.value, 'one');
    assert.equal(container.querySelector('.custom-select-text').textContent, 'One');
  } finally { close(); }
});

test('custom select remains usable when optional trigger text and dropdown are absent', () => {
  const { window: w, context, close } = setup();
  try {
    const container = w.document.createElement('div');
    container.id = 'partial-select';
    container.className = 'custom-select';
    w.document.body.appendChild(container);
    const selector = vm.runInContext("new CustomSelect('partial-select')", context);
    selector.setData([{ value: 'one', label: 'One' }]);
    selector.setValue('one');
    assert.equal(selector.getValue(), 'one');
    const option = w.document.createElement('div');
    option.className = 'custom-select-option';
    option.dataset.value = 'two';
    container.appendChild(option);
    option.click();
    assert.equal(selector.getValue(), 'two');
  } finally { close(); }
});

test('legacy custom select can render and select options without a text label', () => {
  const { window: w, close } = setup();
  try {
    const container = w.document.createElement('div');
    container.id = 'legacy-partial-select';
    container.className = 'custom-select';
    container.innerHTML = '<button class="custom-select-trigger"></button><div class="custom-select-dropdown"></div>';
    w.document.body.appendChild(container);
    const selected = [];
    w.renderCustomSelectOptions(container.id, [{ value: 'one', label: 'One' }], 'one');
    w.initCustomSelect(container.id, value => selected.push(value));
    container.querySelector('.custom-select-option').click();
    assert.deepEqual(selected, ['one']);
    assert.equal(container.dataset.value, 'one');
  } finally { close(); }
});

test('version and report modals stay open when their content is clicked', () => {
  const { window: w, close } = setup();
  try {
    w.bindProjectDetail();
    w.bindDetail();
    const version = w.document.getElementById('version-modal');
    version.classList.add('open');
    w.document.getElementById('version-modal-body').click();
    assert.ok(version.classList.contains('open'));
    const report = w.document.getElementById('report-modal');
    report.classList.add('open');
    w.document.getElementById('report-iframe').click();
    assert.ok(report.classList.contains('open'));
    version.click();
    report.click();
    assert.equal(version.classList.contains('open'), false);
    assert.equal(report.classList.contains('open'), false);
  } finally { close(); }
});

test('custom select preserves the selected value and supports silent updates', () => {
  const { window: w, context, close } = setup();
  try {
    const container = w.document.createElement('div');
    container.id = 'test-select';
    container.className = 'custom-select';
    container.innerHTML = '<button class="custom-select-trigger"><span class="custom-select-text"></span></button>' +
      '<div class="custom-select-dropdown"></div>';
    w.document.body.appendChild(container);
    const updates = [];
    w.selectChanged = value => updates.push(value);
    const selector = vm.runInContext("new CustomSelect('test-select', selectChanged)", context);
    selector.setData([{ value: 1, label: 'One' }, { value: 2, label: 'Two' }]);
    assert.equal(selector.getValue(), '1');
    selector.setValue(2, true);
    assert.deepEqual(updates, []);
    assert.equal(container.querySelector('.custom-select-text').textContent, 'Two');
    selector.setData([{ value: 2, label: 'Updated' }]);
    assert.equal(selector.getValue(), '2');
    assert.equal(container.querySelector('.custom-select-text').textContent, 'Updated');
    selector.setValue(3, false);
    assert.deepEqual(updates, ['3']);
    assert.equal(container.querySelector('.custom-select-text').textContent, '');
    const missing = vm.runInContext("new CustomSelect('not-present')", context);
    missing.setData([]);
    missing.toggle();
    missing.close();
  } finally { close(); }
});

test('custom select opens, closes and ignores non-option clicks', () => {
  const { window: w, context, close } = setup();
  try {
    const container = w.document.createElement('div');
    container.id = 'class-select';
    container.className = 'custom-select';
    container.innerHTML = '<button class="custom-select-trigger"><span class="custom-select-text"></span></button>' +
      '<div class="custom-select-dropdown"></div>';
    w.document.body.appendChild(container);
    const selector = vm.runInContext("new CustomSelect('class-select')", context);
    selector.setData([{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }], 'a');
    const trigger = container.querySelector('.custom-select-trigger');
    trigger.click();
    assert.ok(container.classList.contains('open'));
    container.querySelector('.custom-select-dropdown').click();
    assert.ok(container.classList.contains('open'));
    trigger.click();
    assert.equal(container.classList.contains('open'), false);
    trigger.click();
    container.querySelector('[data-value="b"]').click();
    assert.equal(selector.getValue(), 'b');
    assert.equal(container.querySelector('.custom-select-text').textContent, 'B');
    assert.equal(container.classList.contains('open'), false);
  } finally { close(); }
});

test('Terraform file tree syncs edits when tabs are switched and closed', () => {
  const { window: w, context, close } = setup();
  try {
    w.setTemplateTab('terraform');
    w.enterTfMode({ 'main.tf': 'main', 'modules/network.tf': 'network', 'empty/': '' });
    const editor = w.document.getElementById('template-editor');
    assert.equal(editor.value, 'main');
    editor.value = 'edited main';
    w.openTfFile('modules/network.tf');
    assert.equal(editor.value, 'network');
    assert.equal(vm.runInContext("state.tfFiles['main.tf']", context), 'edited main');
    assert.equal(w.document.querySelectorAll('.tf-tab').length, 2);
    w.closeTfFile('modules/network.tf');
    assert.equal(editor.value, 'edited main');
    w.toggleTfDir('modules');
    w.exitTfMode();
    assert.ok(w.document.getElementById('tf-file-list').classList.contains('hidden'));
    assert.equal(editor.value, '');
  } finally { close(); }
});

test('auto parameter generation defaults the region and displays the updated config', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext(`state.pgRegionSelect = {
      selected: [], getSelected() { return this.selected; }, setSelected(items) { this.selected = items; }
    }`, context);
    w.document.getElementById('template-editor').value = 'Parameters: {}';
    let body;
    w.fetch = async (path, options) => {
      assert.equal(path, '/api/generate-params');
      body = JSON.parse(options.body);
      return { ok: true, status: 200, headers: { get: () => 'application/json' },
               text: async () => JSON.stringify({ parameters: 'parameters: {}', config: 'parameters: {A: generated}' }) };
    };
    await w.autoGenerateParams();
    assert.equal(body.regions, 'cn-hangzhou');
    assert.equal(w.document.getElementById('config-editor').value, 'parameters: {A: generated}');
    assert.equal(w.document.getElementById('btn-generate-params').disabled, false);
  } finally { close(); }
});

test('parameter and cost actions handle successful responses with no generated data', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}; state._templateDirty = true", context);
    w.document.getElementById('template-editor').value = 'Resources: {}';
    w.document.getElementById('config-editor').value = 'parameters: {Name: existing}';
    const calls = [];
    w.api = async (method, url) => { calls.push([method, url]); return {}; };
    await w.autoGenerateParams();
    assert.equal(w.document.getElementById('config-editor').value, 'parameters: {Name: existing}');
    assert.equal(vm.runInContext('state._templateDirty', context), true);
    await w.estimateCost();
    assert.deepEqual(calls, [['POST', '/api/generate-params'], ['POST', '/api/cost']]);
    assert.equal(vm.runInContext('state.lastCostPrices.length', context), 0);
    assert.ok(w.document.getElementById('result-cost').querySelector('.empty-state'));
    assert.equal(w.document.getElementById('btn-cost').disabled, false);
  } finally { close(); }
});

test('auto parameter generation displays warnings and logs with legacy parameter response', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}; state._templateDirty = true", context);
    w.document.getElementById('template-editor').value = 'Parameters: {}';
    const logs = [], notices = [];
    w.consoleLog = (message, options) => logs.push([message, options.action, options.raw]);
    w.toast = (message, type) => notices.push(type);
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ parameters: 'parameters: {VpcId: pending}', warning: 'partial', logs: 'details' }) });
    await w.autoGenerateParams();
    assert.equal(w.document.getElementById('config-editor').value, 'parameters: {VpcId: pending}');
    assert.deepEqual(logs, [['details', 'generate-params', true]]);
    assert.deepEqual(notices, ['warning']);
    assert.equal(vm.runInContext('state._templateDirty', context), false);
  } finally { close(); }
});

test('validation and policy actions surface success and service errors', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.settings = {source: 'env'}; state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.document.getElementById('template-editor').value = 'Resources: {}';
    w.document.getElementById('config-editor').value = 'parameters: {}';
    let fail = false;
    w.fetch = async path => {
      const data = path === '/api/validate' ? { result: 'valid' } : (fail ? { error: 'denied' } : { policy: { Statement: [] } });
      return { ok: !fail || path === '/api/validate', status: fail ? 400 : 200,
               headers: { get: () => 'application/json' }, text: async () => JSON.stringify(data) };
    };
    assert.equal(await w.prevalidate('policy'), true);
    await w.generatePolicy();
    assert.ok(w.document.getElementById('result-policy').textContent.includes('Statement'));
    fail = true;
    await w.generatePolicy();
    assert.match(w.document.getElementById('toast').textContent, /denied/);
    assert.equal(w.document.getElementById('btn-policy').disabled, false);
  } finally { close(); }
});

test('cost action renders resource charges without double-counting associated products', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.document.getElementById('template-editor').value = 'Resources: {}';
    w.document.getElementById('config-editor').value = 'parameters: {}';
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ prices: [{ test_name: 'test', region: 'cn-a', price: {
        Instance: { Type: 'ALIYUN::ECS::Instance', Result: {
          Order: { Currency: 'CNY', TradeAmount: 5 }, OrderSupplement: { PriceUnit: 'Hour' },
          AssociationProducts: { Disk: { Result: { Order: { Currency: 'CNY', TradeAmount: 2 } } } },
        } },
      } }] }) });
    await w.estimateCost();
    const panel = w.document.getElementById('result-cost');
    assert.equal(panel.querySelectorAll('tbody tr').length, 2);
    assert.match(panel.querySelector('.cost-summary').textContent, /¥5/);
    assert.equal(w.document.getElementById('btn-cost').disabled, false);
    assert.match(w.renderCostResultsHtml([{ test_name: '<bad>', error: '<denied>' }]), /&lt;denied&gt;/);
    assert.match(w.renderCostResultsHtml([]), /empty-state/);
  } finally { close(); }
});

test('run status renders stack links and escapes error details', () => {
  const { window: w, close } = setup();
  try {
    const html = w.renderRunStatusHtml({ id: 'abc', name: '<name>', status: 'failed', progress: 100,
      created_at: '2026-01-01T00:00:00Z', completed_at: '2026-01-01T00:01:00Z', error: '<error>',
      report_url: '/outputs/report', stacks: [{ stack_id: 'stack-1', stack_name: 'name', region: 'cn-a',
                                                status: 'CREATE_FAILED', launch_succeeded: false }] });
    assert.match(html, /&lt;name&gt;/);
    assert.match(html, /&lt;error&gt;/);
    assert.match(html, /ros\.console\.aliyun\.com\/cn-a\/stacks\/stack-1/);
    assert.match(html, /0\/1 \(0%\)/);
  } finally { close(); }
});

test('run detail renders ROS template conversion and config parameters', () => {
  const { window: w, close } = setup();
  try {
    const run = { params: { raw_template_content: 'Resources: {}\nParameters: {A: {Type: String}}',
                            raw_config_content: 'tests: {default: {parameters: {A: value}}}' } };
    w.renderRunTemplate(run);
    const template = w.document.getElementById('detail-template');
    assert.match(template.textContent, /Resources/);
    template.querySelector('[data-run-format="json"]').click();
    assert.match(w.document.getElementById('run-template-content').textContent, /"Resources"/);
    w.renderRunConfig(run);
    assert.match(w.document.getElementById('detail-params').textContent, /value/);
  } finally { close(); }
});

test('run detail switches Terraform file tabs', () => {
  const { window: w, close } = setup();
  try {
    w.renderRunTemplate({ params: { raw_template_files: { 'main.tf': 'first', 'variables.tf': 'second' } } });
    const tabs = w.document.getElementById('run-tf-tabs-bar');
    assert.equal(tabs.querySelectorAll('.tf-tab').length, 2);
    tabs.querySelector('[data-path="variables.tf"]').click();
    assert.match(w.document.getElementById('run-tf-content').textContent, /second/);
  } finally { close(); }
});

test('task detail copies selected templates and reports with fallback labels', async () => {
  const { window: w, close } = setup();
  try {
    w.t = () => '';
    const copied = [];
    w.copyToClipboard = async text => copied.push(text);
    w.setTimeout = () => 1;
    w.renderRunTemplate({ params: { raw_template_files: { 'main.tf': 'resource {}', 'empty.tf': '' } } });
    w.document.querySelector('#run-tf-tabs-bar [data-path="empty.tf"]').click();
    w.document.querySelector('.run-tf-copy-btn').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(copied[0], '');
    assert.equal(w.document.querySelector('.run-tf-copy-btn').textContent, 'Copied');
    w.renderRunTemplate({ params: { raw_template_content: 'Resources: {}' } });
    w.document.querySelector('.run-template-copy-btn').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.match(copied[1], /Resources/);
    assert.equal(w.document.querySelector('.run-template-copy-btn').textContent, 'Copied');
    const report = w.document.createElement('div');
    report.id = 'detail-report';
    w.document.body.appendChild(report);
    w.renderReport({ logs: [{ name: 'log.txt', content: 'run log' }] });
    w.document.querySelector('.log-copy').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(copied[2], 'run log');
    assert.equal(w.document.querySelector('.log-copy').textContent, 'Copied');
  } finally { close(); }
});

test('stack detail tolerates missing region and status while displaying update time', () => {
  const { window: w, close } = setup();
  try {
    w.renderDetailStacks({ stacks: [{ stack_id: 'stack-id', region: null,
      status_time: '2026-01-01T00:00:00Z' }] });
    const row = w.document.querySelector('#detail-stacks .pd-stack-row');
    assert.match(row.textContent, /stack-id/);
    assert.match(row.textContent, /Unknown/);
    assert.equal(row.querySelector('.stack-link'), null);
    assert.ok(row.querySelectorAll('.pd-kv-item').length >= 2);
  } finally { close(); }
});

test('version history displays current version and views Terraform files', async () => {
  const { window: w, close } = setup();
  try {
    w.fetch = async url => {
      const data = url.endsWith('/versions')
        ? { current_version: 2, versions: [{ version: 1 }, { version: 2 }] }
        : { version: 1, template_files: { 'main.tf': 'first', 'vars.tf': 'second' }, config: 'parameters: {}' };
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(data) };
    };
    await w.renderVersionHistory('demo');
    const history = w.document.getElementById('project-detail-versions');
    assert.equal(history.querySelectorAll('tbody tr').length, 2);
    assert.equal(history.querySelector('tr.is-current .version-badge').textContent, 'v2');
    await w.viewVersionContent('demo', 1);
    assert.ok(w.document.getElementById('version-modal').classList.contains('open'));
    w.document.querySelector('#ver-tf-tabs-bar [data-path="vars.tf"]').click();
    assert.equal(w.document.getElementById('ver-tf-content').textContent, 'second');
    w.closeVersionModal();
  } finally { close(); }
});

test('version viewer shows empty ROS content and closes only on backdrop', async () => {
  const { window: w, close } = setup();
  try {
    w.api = async () => ({ template: '', config: '' });
    w.bindProjectDetail();
    await w.viewVersionContent('demo', 1);
    const modal = w.document.getElementById('version-modal');
    assert.match(modal.textContent, /\(empty\)/);
    w.document.getElementById('version-modal-body').click();
    assert.ok(modal.classList.contains('open'));
    modal.click();
    assert.equal(modal.classList.contains('open'), false);
  } finally { close(); }
});

test('version comparison renders template and config changes', async () => {
  const { window: w, close } = setup();
  try {
    w.fetch = async url => {
      const data = url.endsWith('/versions/1')
        ? { template: 'old', config: 'parameters: {A: old}' }
        : { template: 'new', config: 'parameters: {A: new}' };
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(data) };
    };
    await w.viewVersionDiff('demo', 1);
    const modal = w.document.getElementById('version-modal');
    assert.ok(modal.classList.contains('open'));
    assert.match(modal.textContent, /old/);
    assert.match(modal.textContent, /new/);
  } finally { close(); }
});

test('stack details display failures and expand without treating links as toggles', () => {
  const { window: w, close } = setup();
  try {
    const run = { stacks: [{ stack_id: 'stack-1', stack_name: 'example', test_name: 'smoke', region: 'cn-a',
      status: 'CREATE_FAILED', launch_succeeded: false, status_reason: 'Resource CREATE failed: denied',
      create_time: '2026-01-01T00:00:00Z', status_time: '2026-01-01T00:01:00Z' }] };
    w.renderDetailStacks(run);
    const row = w.document.querySelector('#detail-stacks .pd-stack-row');
    assert.ok(row.classList.contains('collapsed'));
    assert.match(row.textContent, /denied/);
    row.querySelector('.pd-stack-row-header').click();
    assert.equal(row.classList.contains('collapsed'), false);
    assert.match(row.querySelector('a').href, /stacks\/stack-1/);
  } finally { close(); }
});

test('stack details show create and delete errors even when links are unavailable', () => {
  const { window: w, close } = setup();
  try {
    w.renderDetailStacks({ stacks: [
      { stack_id: 'orphan', status: 'CREATE_COMPLETE', launch_succeeded: false,
        create_error: '<create denied>', status_time: '2026-01-01T00:01:00Z' },
      { status: 'DELETE_FAILED', error: '<generic failure>', delete_error: '<delete denied>',
        status_time: '2026-01-01T00:02:00Z' },
      {},
    ] });
    const rows = w.document.querySelectorAll('#detail-stacks .pd-stack-row');
    assert.equal(rows.length, 3);
    assert.equal(rows[0].querySelector('a'), null);
    assert.match(rows[0].textContent, /<create denied>/);
    assert.match(rows[1].textContent, /<generic failure>/);
    assert.match(rows[1].textContent, /<delete denied>/);
    assert.equal(rows[1].querySelector('delete'), null);
    assert.equal(rows[2].querySelector('.stack-id-text'), null);
  } finally { close(); }
});

test('CLI log viewer colors error levels and escapes service text', async () => {
  const { window: w, close } = setup();
  try {
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'text/plain' },
      text: async () => '2026-01-01 12:00:00,123 [ERROR] : <failure>\nplain' });
    await w.renderCliLogs('run');
    const logs = w.document.getElementById('detail-logs');
    assert.equal(logs.querySelector('.term-error').textContent, '[ERROR]');
    assert.match(logs.textContent, /<failure>/);
    assert.equal(logs.querySelector('failure'), null);
  } finally { close(); }
});

test('CLI log viewer renders warning, info and debug levels and handles empty responses', async () => {
  const { window: w, close } = setup();
  try {
    let content = ['WARNING', 'INFO', 'DEBUG'].map(level =>
      `2026-01-01 12:00:00,123 [${level}] : ${level} detail`).join('\n');
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'text/plain' },
      text: async () => content });
    await w.renderCliLogs('run');
    const logs = w.document.getElementById('detail-logs');
    for (const level of ['warning', 'info', 'debug']) {
      assert.ok(logs.querySelector(`.term-${level}`));
    }
    content = '  ';
    await w.renderCliLogs('run');
    assert.ok(logs.querySelector('.empty-state'));
    w.fetch = async () => { throw new Error('unavailable'); };
    await w.renderCliLogs('run');
    assert.ok(logs.querySelector('.empty-state'));
  } finally { close(); }
});

test('project detail renders Terraform files and project options', () => {
  const { window: w, close } = setup();
  try {
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ versions: [], regions: [] }) });
    w.renderProjectDetail({ name: 'demo', template_files: { 'main.tf': 'first', 'vars.tf': 'second' },
      config: 'tests: {default: {parameters: {A: value}}}', current_version: 1, no_delete: true }, []);
    assert.match(w.document.getElementById('project-detail-overview').textContent, /demo/);
    w.document.querySelector('#pd-tf-tabs-bar [data-path="vars.tf"]').click();
    assert.match(w.document.getElementById('pd-tf-content').textContent, /second/);
    assert.match(w.document.getElementById('project-detail-configs').textContent, /value/);
  } finally { close(); }
});

test('project detail displays timestamps and options and switches to an empty Terraform file', () => {
  const { window: w, close } = setup();
  try {
    w.renderVersionHistory = async () => {};
    w.renderProjectDetail({ name: 'demo', created_at: 1700000000, updated_at: 1700000100,
      keep_failed: true, dont_wait_for_delete: true,
      template_files: { 'main.tf': 'resource {}', 'empty.tf': '', 'module/': '' } }, []);
    const overview = w.document.getElementById('project-detail-overview');
    assert.doesNotMatch(overview.textContent, /Invalid Date/);
    assert.equal(overview.querySelectorAll('#pd-section-options .pd-kv-value')[1].textContent, w.t('yes'));
    assert.equal(overview.querySelectorAll('#pd-section-options .pd-kv-value')[2].textContent, w.t('yes'));
    w.document.querySelector('#pd-tf-tabs-bar [data-path="empty.tf"]').click();
    assert.equal(w.document.getElementById('pd-tf-content').textContent.trim(), '');
    assert.equal(w.document.querySelector('#pd-tf-tabs-bar [data-path="module/"]'), null);
  } finally { close(); }
});

test('task cancellation and batch deletion require confirmation and send selected IDs', async () => {
  const { window: w, context, close } = setup();
  try {
    const requests = [];
    vm.runInContext("state.tasks = [{id: 'a', name: 'Task A', status: 'running'}]; state.selectedTasks = new Set(['a', 'b'])", context);
    w.loadTasks = async () => {};
    w.fetch = async (url, options) => {
      requests.push({ url, options });
      const data = url.includes('batch-delete') ? { deleted: ['a', 'b'] } : { runs: [], total: 0 };
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(data) };
    };
    const cancel = w.cancelTask('a');
    w.document.getElementById('confirm-modal-cancel').click();
    await cancel;
    assert.equal(requests.length, 0);
    const confirmed = w.cancelTask('a');
    w.document.getElementById('confirm-modal-ok').click();
    await confirmed;
    assert.ok(requests.some(request => request.url === '/api/runs/a/cancel' && request.options.method === 'POST'));
    const batch = w.batchDeleteTasks();
    w.document.getElementById('confirm-modal-ok').click();
    await batch;
    const request = requests.find(item => item.url === '/api/runs/batch-delete');
    assert.deepEqual(JSON.parse(request.options.body).ids, ['a', 'b']);
    assert.equal(vm.runInContext('state.selectedTasks.size', context), 0);
  } finally { close(); }
});

test('project batch deletion sends selected names after confirmation', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.selectedProjects = new Set(['first', 'second'])", context);
    w.loadProjects = async () => {};
    const requests = [];
    w.fetch = async (url, options) => {
      requests.push({ url, options });
      const data = url.includes('batch-delete') ? { deleted: ['first', 'second'] } : { projects: [], total: 0 };
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(data) };
    };
    const action = w.batchDeleteProjects();
    w.document.getElementById('confirm-modal-ok').click();
    await action;
    const request = requests.find(item => item.url === '/api/projects/batch-delete');
    assert.deepEqual(JSON.parse(request.options.body).names, ['first', 'second']);
    assert.equal(vm.runInContext('state.selectedProjects.size', context), 0);
  } finally { close(); }
});

test('project deletion confirms, escapes the name and refreshes only on success', async () => {
  const { window: w, close } = setup();
  try {
    let confirmed = false, refreshes = 0, fail = false;
    const requests = [], notices = [];
    w.showConfirm = async () => confirmed;
    w.loadProjects = () => { refreshes++; };
    w.toast = (message, type) => notices.push([message, type]);
    w.api = async (method, path) => {
      requests.push([method, path]);
      if (fail) throw new Error('offline');
    };
    await w.deleteProject('demo/name');
    assert.deepEqual(requests, []);
    confirmed = true;
    await w.deleteProject('demo/name');
    assert.deepEqual(requests, [['DELETE', '/api/projects/demo%2Fname']]);
    assert.equal(refreshes, 1);
    fail = true;
    await w.deleteProject('demo/name');
    assert.deepEqual(notices.at(-1), ['offline', 'error']);
    assert.equal(refreshes, 1);
  } finally { close(); }
});

test('project editor opens saved Terraform project and saves updated files', async () => {
  const { window: w, close } = setup();
  try {
    const requests = [];
    w.loadEditVersions = async () => {};
    w.loadProjects = async () => {};
    w.fetch = async (url, options) => {
      requests.push({ url, options });
      const result = options.method === 'GET'
        ? { template_files: { 'main.tf': 'old' }, config: 'parameters: {A: 1}', no_delete: true }
        : { status: 'ok' };
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(result) };
    };
    await w.openEditProject('demo');
    assert.ok(w.document.getElementById('project-edit-modal').classList.contains('open'));
    assert.equal(w.document.getElementById('project-edit-no-delete').checked, true);
    w.document.getElementById('project-edit-tf-template').value = 'updated';
    await w.saveEditProject();
    const save = requests.find(request => request.url === '/api/projects' && request.options.method === 'POST');
    const payload = JSON.parse(save.options.body);
    assert.equal(payload.template_files['main.tf'], 'updated');
    assert.equal(payload.allow_overwrite, true);
    assert.equal(payload.no_delete, true);
    assert.equal(w.document.getElementById('project-edit-modal').classList.contains('open'), false);
  } finally { close(); }
});

test('project editor accepts an empty legacy project and clears stale input hints', async () => {
  const { window: w, context, close } = setup();
  try {
    const hint = w.document.getElementById('project-edit-name-hint');
    hint.textContent = 'old error';
    hint.classList.add('visible');
    vm.runInContext("state.projectEditTfFiles = {'old.tf': 'old'}; state.projectEditTfActiveFile = 'old.tf'; state.projectEditTfMode = true", context);
    w.loadEditVersions = () => {};
    w.api = async () => ({ configs: [{}] });
    await w.openEditProject('demo');
    assert.equal(w.document.getElementById('project-edit-template').value, '');
    assert.equal(w.document.getElementById('project-edit-config').value, '');
    assert.equal(vm.runInContext('state.projectEditTfMode', context), false);
    assert.equal(vm.runInContext('Object.keys(state.projectEditTfFiles).length', context), 0);
    assert.equal(hint.textContent, '');
    assert.equal(hint.classList.contains('visible'), false);
  } finally { close(); }
});

test('project editor refuses an invalid name and saves an empty Terraform workspace', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.page = 'project-detail'; state.projectEditTfMode = true; state.projectEditTfFiles = {'folder/': ''}; state.projectEditTfActiveFile = null", context);
    const requests = [], navigations = [];
    w.api = async (method, path, payload) => { requests.push(payload); return {}; };
    w.loadProjects = () => {};
    w.navigate = (page, params) => navigations.push([page, params.projectName]);
    const input = w.document.getElementById('project-edit-name');
    input.value = 'bad/name';
    await w.saveEditProject();
    assert.equal(requests.length, 0);
    input.value = 'demo';
    await w.saveEditProject();
    assert.equal(requests.length, 1);
    assert.equal(requests[0].template, '');
    assert.equal(Object.keys(requests[0].template_files).length, 0);
    assert.deepEqual(navigations, [['project-detail', 'demo']]);
  } finally { close(); }
});

test('project editor parameter generation uses selected region and displays results', async () => {
  const { window: w, close } = setup();
  try {
    w.loadEditVersions = async () => {};
    w.openNewProject();
    w.document.getElementById('project-edit-template').value = 'Resources: {}';
    w.document.getElementById('project-edit-config').value = 'parameters: {}';
    let sent;
    w.fetch = async (url, options) => {
      sent = JSON.parse(options.body);
      return { ok: true, status: 200, headers: { get: () => 'application/json' },
               text: async () => JSON.stringify({ parameters: 'parameters: {}', config: 'parameters: {A: 1}' }) };
    };
    await w.generateParamsForProjectEdit();
    assert.equal(sent.template_content, 'Resources: {}');
    assert.equal(sent.regions, 'cn-hangzhou');
    assert.equal(w.document.getElementById('project-edit-config').value, 'parameters: {A: 1}');
    assert.equal(w.document.getElementById('project-edit-generate-params').disabled, false);
  } finally { close(); }
});

test('project parameter generation preserves config on empty results and reports warnings', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.projectEditTfMode = true; state.projectEditTfFiles = {'main.tf':'saved', 'module/':''}; state.projectEditTfActiveFile = 'main.tf'", context);
    w.document.getElementById('project-edit-tf-template').value = 'unsaved';
    w.document.getElementById('project-edit-config').value = 'parameters: {Old: keep}';
    const requests = [], notices = [], logs = [];
    w.toast = (message, type) => notices.push(type);
    w.console.log = message => logs.push(message);
    w.api = async (method, path, payload) => {
      requests.push(payload);
      return requests.length === 1 ? {} : { parameters: 'parameters: {New: value}', warning: true, logs: 'details' };
    };
    await w.generateParamsForProjectEdit();
    assert.equal(w.document.getElementById('project-edit-config').value, 'parameters: {Old: keep}');
    await w.generateParamsForProjectEdit();
    assert.equal(requests[0].template_files['main.tf'], 'unsaved');
    assert.equal(Object.hasOwn(requests[0].template_files, 'module/'), false);
    assert.equal(w.document.getElementById('project-edit-config').value, 'parameters: {New: value}');
    assert.deepEqual(notices, ['warning']);
    assert.match(logs[0], /details/);
  } finally { close(); }
});

test('project editor reports empty templates and parameter service failures', async () => {
  const { window: w, close } = setup();
  try {
    w.openNewProject();
    const notices = [];
    let requests = 0;
    w.toast = (message, type) => notices.push([message, type]);
    w.fetch = async () => { requests++; throw new Error('generation unavailable'); };
    w.document.getElementById('project-edit-template').value = '';
    await w.generateParamsForProjectEdit();
    assert.equal(requests, 0);
    assert.equal(notices[0][1], 'error');
    w.document.getElementById('project-edit-template').value = 'Resources: {}';
    await w.generateParamsForProjectEdit();
    assert.equal(requests, 1);
    assert.deepEqual(notices[1], ['generation unavailable', 'error']);
    assert.equal(w.document.getElementById('project-edit-generate-params').disabled, false);
    await w.openEditProject('unavailable');
    assert.deepEqual(notices[2], ['generation unavailable', 'error']);
  } finally { close(); }
});

test('playground save requests overwrite only after typed confirmation', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.projects = [{name: 'demo'}]; state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.document.getElementById('pg-project-name-input').value = 'demo';
    w.document.getElementById('template-editor').value = 'Resources: {}';
    w.document.getElementById('config-editor').value = 'parameters: {}';
    const requests = [];
    w.fetch = async (url, options) => {
      requests.push({ url, options });
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => '{}' };
    };
    const save = w.pgSaveFromPlayground();
    const verify = w.document.getElementById('confirm-modal-verify-input');
    assert.equal(w.document.getElementById('confirm-modal-ok').disabled, true);
    verify.value = 'demo';
    verify.dispatchEvent(new w.Event('input'));
    w.document.getElementById('confirm-modal-ok').click();
    await save;
    const payload = JSON.parse(requests[0].options.body);
    assert.equal(payload.name, 'demo');
    assert.equal(payload.allow_overwrite, true);
    assert.deepEqual(yaml.load(payload.config).tests.default.regions, ['cn-a']);
  } finally { close(); }
});

test('playground save handles a server conflict arising after the project list was loaded', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext('state.projects = []; state.pgRegionSelect = null', context);
    w.document.getElementById('pg-project-name-input').value = 'demo';
    w.document.getElementById('template-editor').value = 'Resources: {}';
    let requests = 0, confirmations = 0;
    w.fetch = async () => {
      requests++;
      return { ok: false, status: 409, headers: { get: () => 'application/json' },
        text: async () => '{"error":"conflict"}' };
    };
    w.confirmOverwrite = async name => { confirmations++; assert.equal(name, 'demo'); return false; };
    await w.pgSaveFromPlayground();
    assert.equal(requests, 1);
    assert.equal(confirmations, 1);
    assert.equal(w.document.getElementById('btn-pg-save-confirm').disabled, false);
    assert.equal(w.document.getElementById('pg-project-name-input').value, 'demo');
  } finally { close(); }
});

test('playground does not save a project with an invalid name', async () => {
  const { window: w, close } = setup();
  try {
    let requests = 0;
    w.api = async () => { requests++; };
    w.document.getElementById('pg-project-name-input').value = 'invalid/name';
    await w.pgSaveFromPlayground();
    assert.equal(requests, 0);
    assert.ok(w.document.getElementById('toast').classList.contains('error'));
    assert.equal(w.document.activeElement, w.document.getElementById('pg-project-name-input'));
  } finally { close(); }
});

test('playground retries an unexpected project conflict only after overwrite confirmation', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext('state.projects = []; state.pgRegionSelect = null', context);
    w.document.getElementById('pg-project-name-input').value = 'demo';
    w.document.getElementById('template-editor').value = 'Resources: {}';
    const requests = [];
    w.confirmOverwrite = async name => name === 'demo';
    w.api = async (method, path, body) => {
      requests.push(body);
      if (requests.length === 1) throw new Error('project conflict detected');
      return { status: 'ok' };
    };
    await w.pgSaveFromPlayground();
    assert.equal(requests.length, 2);
    assert.equal(requests[0].allow_overwrite, undefined);
    assert.equal(requests[1].allow_overwrite, true);
    assert.equal(w.document.getElementById('pg-project-name-input').value, '');
    assert.equal(w.document.getElementById('btn-pg-save-confirm').disabled, false);
  } finally { close(); }
});

test('playground save payload uses unsaved Terraform content and ignores empty workspaces', () => {
  const { window: w, context, close } = setup();
  try {
    w.document.getElementById('config-editor').value = 'parameters: {}';
    w.enterTfMode({ 'main.tf': 'old', 'folder/': '' });
    w.document.getElementById('template-editor').value = 'edited';
    let payload = w.getProjectSavePayload();
    assert.equal(payload.template, '');
    assert.equal(payload.template_files['main.tf'], 'edited');
    assert.equal(payload.config, 'parameters: {}');
    vm.runInContext("state.tfFiles = {'folder/': ''}; state.tfActiveFile = null", context);
    payload = w.getProjectSavePayload();
    assert.equal(Object.keys(payload.template_files).length, 0);
    w.exitTfMode();
    w.document.getElementById('template-editor').value = 'Resources: {}';
    payload = w.getProjectSavePayload();
    assert.equal(payload.template, 'Resources: {}');
    assert.equal(Object.keys(payload.template_files).length, 0);
  } finally { close(); }
});

test('server-side save conflict can be cancelled without overwriting', async () => {
  const { window: w, close } = setup();
  try {
    w.loadEditVersions = async () => {};
    w.openNewProject();
    w.document.getElementById('project-edit-name').value = 'demo';
    let calls = 0;
    w.fetch = async () => {
      calls++;
      return { ok: false, status: 409, headers: { get: () => 'application/json' },
               text: async () => JSON.stringify({ error: 'conflict' }) };
    };
    const action = w.saveEditProject();
    for (let i = 0; i < 10 && !w.document.getElementById('confirm-modal').classList.contains('open'); i++) {
      await new Promise(resolve => setImmediate(resolve));
    }
    assert.ok(w.document.getElementById('confirm-modal').classList.contains('open'));
    w.document.getElementById('confirm-modal-cancel').click();
    await action;
    assert.equal(calls, 1);
    assert.ok(w.document.getElementById('project-edit-modal').classList.contains('open'));
    assert.equal(w.document.getElementById('project-edit-save').disabled, false);
  } finally { close(); }
});

test('project editor retries a server conflict only after overwrite confirmation', async () => {
  const { window: w, close } = setup();
  try {
    w.openNewProject();
    w.document.getElementById('project-edit-name').value = 'demo';
    w.document.getElementById('project-edit-template').value = 'Resources: {}';
    const requests = [];
    w.confirmOverwrite = async name => name === 'demo';
    w.loadProjects = () => {};
    w.api = async (method, path, body) => {
      requests.push(body);
      if (requests.length === 1) throw new Error('project conflict detected');
      return {};
    };
    await w.saveEditProject();
    assert.equal(requests.length, 2);
    assert.equal(requests[0].allow_overwrite, undefined);
    assert.equal(requests[1].allow_overwrite, true);
    assert.equal(requests[1].template, 'Resources: {}');
    assert.equal(w.document.getElementById('project-edit-modal').classList.contains('open'), false);
    assert.equal(w.document.getElementById('project-edit-save').disabled, false);
  } finally { close(); }
});

test('renaming a Terraform folder cannot overwrite an existing folder', async () => {
  const { window: w, context, close } = setup();
  try {
    w.enterTfMode({ 'old/main.tf': 'old content', 'new/main.tf': 'keep me' });
    const action = w.renameTfNode('old', true);
    w.document.getElementById('prompt-modal-input').value = 'new';
    w.document.getElementById('prompt-modal-ok').click();
    await action;
    assert.equal(vm.runInContext("state.tfFiles['new/main.tf']", context), 'keep me');
    assert.equal(vm.runInContext("state.tfFiles['old/main.tf']", context), 'old content');
  } finally { close(); }
});

test('project rename handles known conflicts and reports service errors', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.projects = [{name:'target'}]", context);
    w.document.getElementById('project-edit-modal').dataset.name = 'original';
    w.document.getElementById('project-edit-name').value = 'target';
    let requests = 0;
    w.fetch = async () => { requests++; throw new Error('network unavailable'); };
    w.confirmOverwrite = async () => false;
    await w.saveEditProject();
    assert.equal(requests, 0);
    w.confirmOverwrite = async () => true;
    const errors = [];
    w.toast = (message, type) => errors.push([message, type]);
    await w.saveEditProject();
    assert.equal(requests, 1);
    assert.deepEqual(errors, [['network unavailable', 'error']]);
    assert.equal(w.document.getElementById('project-edit-save').disabled, false);
  } finally { close(); }
});

test('renaming a Terraform folder moves files and keeps active tab in sync', async () => {
  const { window: w, context, close } = setup();
  try {
    w.enterTfMode({ 'old/main.tf': 'content' });
    const action = w.renameTfNode('old', true);
    w.document.getElementById('prompt-modal-input').value = 'renamed';
    w.document.getElementById('prompt-modal-ok').click();
    await action;
    assert.equal(vm.runInContext("state.tfFiles['renamed/main.tf']", context), 'content');
    assert.equal(vm.runInContext('state.tfActiveFile', context), 'renamed/main.tf');
    assert.equal(vm.runInContext("Object.hasOwn(state.tfFiles, 'old/main.tf')", context), false);
  } finally { close(); }
});

test('Terraform tabs preserve edited content when switching to an empty file', () => {
  const { window: w, context, close } = setup();
  try {
    w.enterTfMode({ 'main.tf': 'original', 'empty.tf': '' });
    w.openTfFile('main.tf');
    w.document.getElementById('template-editor').value = 'edited';
    w.openTfFile('empty.tf');
    assert.equal(vm.runInContext("state.tfFiles['main.tf']", context), 'edited');
    assert.equal(w.document.getElementById('template-editor').value, '');
    w.switchTfFile('main.tf');
    assert.equal(w.document.getElementById('template-editor').value, 'edited');
    w.switchTfFile('main.tf');
    assert.equal(w.document.getElementById('template-editor').value, 'edited');
    w.switchTfFile('empty.tf');
    assert.equal(w.document.getElementById('template-editor').value, '');
  } finally { close(); }
});

test('project editor keeps the active file when deleting an inactive Terraform file', async () => {
  const { window: w, context, close } = setup();
  try {
    w.bindProjects();
    vm.runInContext("state.projectEditTfFiles = {'main.tf': 'main', 'other.tf': 'other'}; state.projectEditTfActiveFile = 'main.tf'", context);
    w.document.getElementById('project-edit-tf-template').value = 'unsaved main';
    w.document.getElementById('project-edit-tf-template').dispatchEvent(new w.Event('input'));
    w.t = () => '';
    let message;
    w.showConfirm = async value => { message = value; return true; };
    await w.deleteProjectEditTfFile('other.tf');
    assert.equal(message, 'Delete file "other.tf"?');
    assert.equal(vm.runInContext('state.projectEditTfActiveFile', context), 'main.tf');
    assert.equal(w.document.getElementById('project-edit-tf-template').value, 'unsaved main');
    assert.equal(vm.runInContext("Object.hasOwn(state.projectEditTfFiles, 'other.tf')", context), false);
  } finally { close(); }
});

test('renaming a nested Terraform folder preserves expanded state and open files', async () => {
  const { window: w, context, close } = setup();
  try {
    w.enterTfMode({ 'module/old/first.tf': 'first', 'module/old/second.tf': 'second', 'main.tf': 'main' });
    vm.runInContext("state.tfOpenFiles = ['main.tf', 'module/old/first.tf', 'module/old/second.tf']; " +
      "state.tfActiveFile = 'module/old/second.tf'; state.tfExpandedDirs.add('module/old')", context);
    w.document.getElementById('template-editor').value = 'unsaved';
    w.showPrompt = async () => 'new';
    await w.renameTfNode('module/old', true);
    assert.deepEqual(Array.from(vm.runInContext('state.tfOpenFiles', context)),
      ['main.tf', 'module/new/first.tf', 'module/new/second.tf']);
    assert.equal(vm.runInContext('state.tfActiveFile', context), 'module/new/second.tf');
    assert.equal(vm.runInContext("state.tfFiles['module/new/second.tf']", context), 'unsaved');
    assert.equal(vm.runInContext("state.tfExpandedDirs.has('module/new')", context), true);
    assert.equal(vm.runInContext("state.tfExpandedDirs.has('module/old')", context), false);
  } finally { close(); }
});

test('closing an edited Terraform tab keeps its unsaved content when reopened', () => {
  const { window: w, context, close } = setup();
  try {
    w.enterTfMode({ 'main.tf': 'old', 'vars.tf': 'vars' });
    w.openTfFile('vars.tf');
    w.document.getElementById('template-editor').value = 'unsaved variables';
    w.closeTfFile('vars.tf');
    assert.equal(vm.runInContext('state.tfActiveFile', context), 'main.tf');
    w.openTfFile('vars.tf');
    assert.equal(w.document.getElementById('template-editor').value, 'unsaved variables');
    w.document.getElementById('template-editor').value = 'more edits';
    w.closeTfFile('main.tf');
    assert.equal(vm.runInContext("state.tfFiles['vars.tf']", context), 'more edits');
  } finally { close(); }
});

test('Terraform file and folder operations preserve unrelated files', async () => {
  const { window: w, context, close } = setup();
  try {
    w.enterTfMode({ 'main.tf': 'main', 'group/old.tf': 'old' });
    w.showInlinePrompt = async () => 'new.tf';
    await w.createTfFile('group');
    assert.equal(vm.runInContext("state.tfFiles['group/new.tf']", context), '');
    w.showInlinePrompt = async () => 'sub';
    await w.createTfFolder('group');
    assert.equal(vm.runInContext("state.tfFiles['group/sub/']", context), '');
    w.showPrompt = async () => 'renamed.tf';
    await w.renameTfNode('group/old.tf', false);
    assert.equal(vm.runInContext("state.tfFiles['group/renamed.tf']", context), 'old');
    w.showConfirm = async () => true;
    await w.deleteTfFile('group/new.tf');
    await w.deleteTfFolder('group');
    assert.deepEqual(Array.from(vm.runInContext('Object.keys(state.tfFiles)', context)), ['main.tf']);
  } finally { close(); }
});

test('Terraform deletion preserves files on cancellation and updates active tab on confirmation', async () => {
  const { window: w, context, close } = setup();
  try {
    w.enterTfMode({ 'main.tf': 'main', 'dir/file.tf': 'nested' });
    w.openTfFile('dir/file.tf');
    w.showConfirm = async () => false;
    await w.deleteTfFile('dir/file.tf');
    await w.deleteTfFolder('dir');
    assert.equal(vm.runInContext('state.tfActiveFile', context), 'dir/file.tf');
    assert.equal(vm.runInContext("state.tfFiles['dir/file.tf']", context), 'nested');
    w.showConfirm = async () => true;
    await w.deleteTfFolder('dir/');
    assert.equal(vm.runInContext('state.tfActiveFile', context), 'main.tf');
    assert.equal(w.document.getElementById('template-editor').value, 'main');
    await w.deleteTfFile('main.tf');
    assert.equal(vm.runInContext('state.tfActiveFile', context), null);
    assert.equal(w.document.getElementById('template-editor').value, '');
  } finally { close(); }
});

test('version switching restores unsaved Terraform edits when returning to current', async () => {
  const { window: w, context, close } = setup();
  try {
    w.fetch = async url => {
      const data = url.endsWith('/versions')
        ? { current_version: 2, versions: [{ version: 1 }, { version: 2 }] }
        : { template_files: { 'main.tf': 'old version' }, config: 'parameters: {A: old}' };
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(data) };
    };
    vm.runInContext("state.projectEditTfFiles = {'main.tf': 'saved'}; state.projectEditTfActiveFile = 'main.tf'; state.projectEditTfMode = false", context);
    w.setProjectEditTemplateTab('terraform');
    const editor = w.document.getElementById('project-edit-tf-template');
    editor.value = 'unsaved edit';
    w.document.getElementById('project-edit-config').value = 'parameters: {A: current}';
    await w.loadEditVersions('demo');
    const select = w.document.getElementById('project-edit-version-select');
    select.value = '1';
    await w.onEditVersionChange('demo');
    assert.equal(editor.value, 'old version');
    select.value = 'current';
    await w.onEditVersionChange('demo');
    assert.equal(editor.value, 'unsaved edit');
    assert.equal(w.document.getElementById('project-edit-config').value, 'parameters: {A: current}');
  } finally { close(); }
});

test('renaming the active project editor file preserves unsaved text', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.projectEditTfFiles = {'main.tf': 'saved'}; state.projectEditTfActiveFile = 'main.tf'", context);
    w.document.getElementById('project-edit-tf-template').value = 'unsaved edit';
    w.showPrompt = async () => 'renamed.tf';
    await w.renameProjectEditTfFile('main.tf');
    assert.equal(vm.runInContext("state.projectEditTfFiles['renamed.tf']", context), 'unsaved edit');
    assert.equal(w.document.getElementById('project-edit-tf-template').value, 'unsaved edit');
  } finally { close(); }
});

test('project editor rejects duplicate and cancelled Terraform file operations', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.projectEditTfFiles = {'main.tf': 'original', 'folder/': ''}; state.projectEditTfActiveFile = 'main.tf'", context);
    w.document.getElementById('project-edit-tf-template').value = 'original';
    const notices = [];
    w.toast = (message, type) => notices.push(type);
    w.showPrompt = async () => 'main.tf';
    await w.addProjectEditTfFile();
    w.showPrompt = async () => 'folder';
    await w.addProjectEditTfFolder();
    w.showPrompt = async () => 'folder/';
    await w.renameProjectEditTfFile('main.tf');
    assert.deepEqual(notices, ['error', 'error', 'error']);
    w.showPrompt = async () => null;
    await w.addProjectEditTfFile();
    await w.addProjectEditTfFolder();
    await w.renameProjectEditTfFile('main.tf');
    w.showConfirm = async () => false;
    await w.deleteProjectEditTfFile('main.tf');
    assert.equal(vm.runInContext("state.projectEditTfFiles['main.tf']", context), 'original');
    assert.equal(vm.runInContext('state.projectEditTfActiveFile', context), 'main.tf');
  } finally { close(); }
});

test('project editor ignores whitespace paths and saves edits when leaving Terraform', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.projectEditTfFiles = {'main.tf': 'saved'}; state.projectEditTfActiveFile = 'main.tf'; state.projectEditTfMode = true", context);
    const editor = w.document.getElementById('project-edit-tf-template');
    editor.value = 'unsaved';
    w.setProjectEditTemplateTab('ros');
    assert.equal(vm.runInContext("state.projectEditTfFiles['main.tf']", context), 'unsaved');
    w.showPrompt = async () => '  ';
    await w.addProjectEditTfFile();
    await w.addProjectEditTfFolder();
    await w.renameProjectEditTfFile('main.tf');
    assert.deepEqual(Array.from(vm.runInContext('Object.keys(state.projectEditTfFiles)', context)), ['main.tf']);
    w.showPrompt = async () => 'main.tf';
    await w.renameProjectEditTfFile('main.tf');
    assert.equal(vm.runInContext("state.projectEditTfFiles['main.tf']", context), 'unsaved');
  } finally { close(); }
});

test('project editor reports file and folder conflicts with fallback text', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.projectEditTfFiles = {'main.tf':'main', 'folder/':''}; state.projectEditTfActiveFile = 'main.tf'", context);
    w.t = () => '';
    const prompts = [], notices = [];
    w.toast = (message, type) => notices.push([message, type]);
    let next = 'main.tf';
    w.showPrompt = async options => { prompts.push(options); return next; };
    await w.addProjectEditTfFile();
    next = 'folder';
    await w.addProjectEditTfFolder();
    next = 'folder/';
    await w.renameProjectEditTfFile('main.tf');
    assert.equal(prompts[0].title, 'New Terraform File');
    assert.equal(prompts[0].placeholder, 'filename.tf');
    assert.equal(prompts[1].title, 'Create Folder');
    assert.equal(prompts[1].placeholder, 'e.g. modules');
    assert.equal(prompts[2].title, 'Rename File');
    assert.deepEqual(notices, [['File already exists', 'error'], ['Folder already exists', 'error'],
      ['File already exists', 'error']]);
    assert.equal(vm.runInContext("state.projectEditTfFiles['main.tf']", context), 'main');
  } finally { close(); }
});

test('custom selects show empty and default choices', () => {
  const { window: w, close } = setup();
  try {
    const container = w.document.createElement('div');
    container.id = 'custom-empty';
    container.innerHTML = '<span class="custom-select-text"></span><div class="custom-select-dropdown"></div>';
    w.document.body.appendChild(container);
    w.renderCustomSelectOptions(container.id, [], 'missing');
    assert.equal(container.dataset.value, '');
    assert.equal(container.querySelector('.custom-select-text').textContent, '');
    w.renderCustomSelectOptions(container.id, [{ value: 'first', label: 'First' }], 'missing');
    assert.equal(container.dataset.value, 'first');
    assert.equal(container.querySelector('.custom-select-text').textContent, 'First');
  } finally { close(); }
});

test('pagination opens one page-size menu at a time', () => {
  const { window: w, close } = setup();
  try {
    const a = w.document.createElement('div');
    const b = w.document.createElement('div');
    w.document.body.append(a, b);
    a.innerHTML = w.buildPaginationHTML(1, 2, 20, 10, [10, 20], 'a');
    b.innerHTML = w.buildPaginationHTML(1, 2, 20, 10, [10, 20], 'b');
    w.bindPaginationEvents(a, 2, () => {}, () => {});
    w.bindPaginationEvents(b, 2, () => {}, () => {});
    a.querySelector('.pagination-per-page-trigger').click();
    b.querySelector('.pagination-per-page-trigger').click();
    assert.equal(a.querySelector('.pagination-per-page-wrapper').classList.contains('open'), false);
    assert.equal(b.querySelector('.pagination-per-page-wrapper').classList.contains('open'), true);
    b.querySelector('.pagination-per-page-trigger').click();
    assert.equal(b.querySelector('.pagination-per-page-wrapper').classList.contains('open'), false);
  } finally { close(); }
});

test('Terraform file tree clicks expand folders and open files without treating actions as selections', () => {
  const { window: w, context, close } = setup();
  try {
    w.enterTfMode({ 'main.tf': 'main', 'module/vars.tf': 'variables' });
    let folder = w.document.querySelector('.tf-tree-node[data-path="module"]');
    assert.ok(folder);
    folder.querySelector('.tf-tree-name').click();
    assert.equal(vm.runInContext("state.tfExpandedDirs.has('module')", context), true);
    const file = w.document.querySelector('.tf-tree-node[data-path="module/vars.tf"]');
    file.querySelector('.tf-tree-name').click();
    assert.equal(vm.runInContext('state.tfActiveFile', context), 'module/vars.tf');
    assert.equal(w.document.getElementById('template-editor').value, 'variables');
    folder = w.document.querySelector('.tf-tree-node[data-path="module"]');
    folder.querySelector('.tf-tree-actions').click();
    assert.equal(vm.runInContext("state.tfExpandedDirs.has('module')", context), true);
    folder.querySelector('.tf-tree-name').click();
    assert.equal(vm.runInContext("state.tfExpandedDirs.has('module')", context), false);
  } finally { close(); }
});

test('Terraform tabs handle an empty workspace and closing the last file', () => {
  const { window: w, context, close } = setup();
  try {
    w.enterTfMode({});
    assert.equal(vm.runInContext('state.tfActiveFile', context), null);
    assert.equal(w.document.getElementById('template-editor').value, '');
    w.openTfFile('missing.tf');
    assert.equal(vm.runInContext('state.tfOpenFiles.length', context), 0);
    w.enterTfMode({ 'main.tf': 'saved' });
    w.document.getElementById('template-editor').value = 'unsaved';
    w.switchTfFile('main.tf');
    assert.equal(w.document.getElementById('template-editor').value, 'unsaved');
    w.closeTfFile('main.tf');
    assert.equal(vm.runInContext('state.tfActiveFile', context), null);
    assert.equal(w.document.getElementById('template-editor').value, '');
    assert.equal(vm.runInContext("state.tfFiles['main.tf']", context), 'unsaved');
    assert.equal(w.document.getElementById('tf-tabs-bar').textContent, '');
  } finally { close(); }
});

test('removing the active project editor file selects a remaining file or clears the editor', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.projectEditTfFiles = {'a.tf': 'first', 'b.tf': 'second'}; state.projectEditTfActiveFile = 'a.tf'", context);
    w.showConfirm = async () => true;
    await w.deleteProjectEditTfFile('a.tf');
    assert.equal(vm.runInContext('state.projectEditTfActiveFile', context), 'b.tf');
    assert.equal(w.document.getElementById('project-edit-tf-template').value, 'second');
    await w.deleteProjectEditTfFile('b.tf');
    assert.equal(vm.runInContext('state.projectEditTfActiveFile', context), null);
    assert.equal(w.document.getElementById('project-edit-tf-template').value, '');
  } finally { close(); }
});

test('renaming the active playground Terraform file preserves unsaved text', async () => {
  const { window: w, context, close } = setup();
  try {
    w.enterTfMode({ 'main.tf': 'saved' });
    w.document.getElementById('template-editor').value = 'unsaved edit';
    w.showPrompt = async () => 'renamed.tf';
    await w.renameTfNode('main.tf', false);
    assert.equal(vm.runInContext("state.tfFiles['renamed.tf']", context), 'unsaved edit');
  } finally { close(); }
});

test('local Terraform imports filter files and preserve relative paths', () => {
  const { window: w, context, close } = setup();
  try {
    w.FileReader = class { readAsText(file) { this.onload({ target: { result: file.contents } }); } };
    const files = [
      { name: 'main.tf', webkitRelativePath: 'project/main.tf', contents: 'main' },
      { name: 'vars.tf', webkitRelativePath: 'project/sub/vars.tf', contents: 'vars' },
      { name: 'readme.txt', contents: 'ignored' },
    ];
    w.loadLocalTfFiles(files);
    assert.equal(vm.runInContext("state.tfFiles['main.tf']", context), 'main');
    assert.equal(vm.runInContext("state.tfFiles['sub/vars.tf']", context), 'vars');
    assert.equal(vm.runInContext('Object.keys(state.tfFiles).length', context), 2);
    w.loadProjectEditLocalTfFiles(files);
    assert.equal(vm.runInContext("state.projectEditTfFiles['sub/vars.tf']", context), 'vars');
    w.loadLocalTfFiles([{ name: 'readme.txt' }]);
    assert.ok(w.document.getElementById('toast').classList.contains('error'));
  } finally { close(); }
});

test('run polling updates the result and stops when replaced', async () => {
  const { window: w, context, close } = setup();
  try {
    const requests = [];
    w.fetch = async url => {
      requests.push(url);
      const logs = url.endsWith('/logs');
      return { ok: true, status: 200, headers: { get: () => logs ? 'text/plain' : 'application/json' },
        text: async () => logs ? 'running log' : JSON.stringify({ id: 'a', name: 'test', status: 'running', progress: 30 }) };
    };
    w.pollRunInModal('a');
    for (let i = 0; i < 10 && !w.document.getElementById('result-run').textContent.includes('30%'); i++) {
      await new Promise(resolve => setImmediate(resolve));
    }
    assert.match(w.document.getElementById('result-run').textContent, /30%/);
    assert.ok(requests.includes('/api/runs/a/logs'));
    vm.runInContext('state._activeRunPoller.stop()', context);
    assert.equal(vm.runInContext('state._activeRunPoller', context), null);
  } finally { close(); }
});

test('task polling stops only after every run and deletion is settled', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.page = 'tasks'; state.tasks = [{status: 'completed', stacks: [{status: 'DELETE_IN_PROGRESS'}]}]", context);
    w.startTaskPolling();
    w.checkStopTaskPolling();
    assert.ok(vm.runInContext('state.taskTimer', context));
    vm.runInContext("state.tasks[0].stacks[0].status = 'DELETE_COMPLETE'", context);
    w.checkStopTaskPolling();
    assert.equal(vm.runInContext('state.taskTimer', context), null);
  } finally { close(); }
});

test('run polling reports a failed status request without leaking a running poller', async () => {
  const { window: w, context, close } = setup();
  try {
    w.fetch = async url => {
      if (url.endsWith('/logs')) return { ok: true, status: 200, headers: { get: () => 'text/plain' }, text: async () => '' };
      throw new Error('network unavailable');
    };
    w.pollRunInModal('failure');
    for (let i = 0; i < 10 && !w.document.getElementById('log-run').textContent.includes('network unavailable'); i++) {
      await new Promise(resolve => setImmediate(resolve));
    }
    assert.match(w.document.getElementById('log-run').textContent, /network unavailable/);
    vm.runInContext('state._activeRunPoller.stop()', context);
    assert.equal(vm.runInContext('state._activeRunPoller', context), null);
  } finally { close(); }
});

test('loading a saved project restores its configuration and selected regions', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext(`state.pgRegionSelect = {
      selected: [], getSelected() { return this.selected; }, setSelected(items) { this.selected = items; }
    }`, context);
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ template: 'Resources: {}',
        config: 'tests: {default: {regions: [cn-a, cn-b], parameters: {A: 1}}}' }) });
    await w.loadProjectIntoPlayground('demo');
    assert.equal(w.document.getElementById('template-editor').value, 'Resources: {}');
    assert.deepEqual(Array.from(vm.runInContext('state.pgRegionSelect.getSelected()', context)), ['cn-a', 'cn-b']);
    assert.match(w.document.getElementById('config-editor').value, /parameters/);
  } finally { close(); }
});

test('loading a Terraform project restores files and works without an initialized region selector', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext('state.pgRegionSelect = null', context);
    w.api = async () => ({ template_files: { 'main.tf': 'resource {}', 'vars.tf': 'variable {}' },
      configs: [{ config: 'tests: {default: {regions: [cn-a]}}' }] });
    let page;
    w.navigate = value => { page = value; };
    await w.loadProjectIntoPlayground('demo');
    assert.equal(vm.runInContext('state.tfMode', context), true);
    assert.equal(w.document.getElementById('template-editor').value, 'resource {}');
    assert.equal(vm.runInContext("state.tfFiles['vars.tf']", context), 'variable {}');
    assert.match(w.document.getElementById('config-editor').value, /cn-a/);
    assert.equal(page, 'playground');
  } finally { close(); }
});

test('project history shows failures without treating successful status reasons as errors', () => {
  const { window: w, context, close } = setup();
  try {
    const runs = [
      { id: 'one', name: 'completed', status: 'completed', progress: 100, created_at: '2026-01-01T00:00:00Z',
        stacks: [{ stack_name: 'ok', region: 'cn-a', status: 'CREATE_COMPLETE', status_reason: 'success' }] },
      { id: 'two', name: 'failed', status: 'failed', progress: 100, created_at: '2026-01-01T00:00:00Z',
        stacks: [{ stack_name: 'bad', region: 'cn-a', status: 'CREATE_FAILED', status_reason: 'Resource CREATE failed: denied' }] },
    ];
    vm.runInContext('state.runHistoryPerPage = 10; state.runHistoryPage = 1', context);
    const container = w.document.getElementById('project-detail-runs');
    w.renderProjectRunHistory(container, runs, { name: 'demo' });
    const cards = container.querySelectorAll('.pd-run-card');
    assert.equal(cards.length, 2);
    assert.equal(cards[0].querySelector('.pd-run-analysis'), null);
    assert.match(cards[1].querySelector('.pd-run-analysis').textContent, /denied/);
    cards[1].querySelector('.pd-run-header').click();
    assert.ok(cards[1].classList.contains('expanded'));
  } finally { close(); }
});

test('project history lists mixed stack states and escapes failure details', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext('state.runHistoryPerPage = 10; state.runHistoryPage = 1', context);
    const container = w.document.getElementById('project-detail-runs');
    w.renderProjectRunHistory(container, [{ id: 'run', name: 'example', status: 'running',
      created_at: '2026-01-01T00:00:00Z', error: '<operation failed>', report_url: '/outputs/result',
      stacks: [{ test_name: 'pending', status: 'CREATE_IN_PROGRESS' },
        { test_name: 'failed', status: 'CREATE_FAILED', status_reason: '<denied>' }] }], { name: 'demo' });
    assert.equal(container.querySelectorAll('.status-badge.status-running').length >= 1, true);
    assert.equal(container.querySelectorAll('.status-badge.status-failed').length, 1);
    assert.match(container.querySelector('.pd-run-analysis').textContent, /<operation failed>/);
    assert.match(container.querySelector('.pd-run-analysis').textContent, /<denied>/);
    assert.equal(container.querySelector('denied'), null);
    assert.match(container.querySelector('a').href, /outputs\/result/);
  } finally { close(); }
});

test('project run validates first and reuses request id after a transient failure', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.loadProjectDetail = async () => {};
    const attempts = [];
    w.fetch = async (url, options) => {
      let data;
      let ok = true;
      if (url === '/api/projects/demo') data = { template: 'Resources: {}', config: 'parameters: {}' };
      else if (url === '/api/validate') data = { result: 'valid' };
      else if (url === '/api/runs') {
        attempts.push(JSON.parse(options.body));
        ok = attempts.length > 1;
        data = ok ? { id: 'run' } : { error: 'temporary failure' };
      } else throw new Error('unexpected URL ' + url);
      return { ok, status: ok ? 200 : 503, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(data) };
    };
    await w.runProjectFromDetail('demo');
    await w.runProjectFromDetail('demo');
    assert.equal(attempts.length, 2);
    assert.equal(attempts[0].request_id, attempts[1].request_id);
    assert.equal(attempts[0].project_name, 'demo');
    assert.equal(vm.runInContext("state.pendingProjectRunRequestIds['demo']", context), undefined);
    assert.equal(w.document.getElementById('btn-project-detail-run').disabled, false);
  } finally { close(); }
});

test('project run stops when template validation fails', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    const requests = [];
    w.fetch = async url => {
      requests.push(url);
      const data = url === '/api/projects/demo' ? { template: 'bad', config: '' } : { result: 'invalid' };
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(data) };
    };
    await w.runProjectFromDetail('demo');
    assert.deepEqual(requests, ['/api/projects/demo', '/api/validate']);
    assert.equal(w.document.getElementById('btn-project-detail-run').disabled, false);
  } finally { close(); }
});

test('project run uses detail region and shows validation logs without starting a run', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-fallback']}", context);
    const region = w.document.getElementById('pd-region-select');
    region.add(new w.Option('Region B', 'cn-b'));
    region.value = 'cn-b';
    const requests = [], logs = [];
    w.consoleLog = (message, options) => logs.push([message, options.action, options.raw]);
    w.fetch = async (url, options) => {
      requests.push([url, options.body && JSON.parse(options.body)]);
      const result = url === '/api/projects/demo' ? { template: 'Resources: {}' }
        : { result: 'invalid', logs: 'validation denied' };
      return { ok: true, status: 200, headers: { get: () => 'application/json' },
        text: async () => JSON.stringify(result) };
    };
    await w.runProjectFromDetail('demo');
    assert.equal(requests.length, 2);
    assert.equal(requests[1][1].regions, 'cn-b');
    assert.deepEqual(logs, [['validation denied', 'validate', true]]);
    assert.equal(w.document.getElementById('btn-project-detail-run').disabled, false);
  } finally { close(); }
});

test('project run accepts legacy config without regions and does not submit twice', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext('state.pgRegionSelect = null', context);
    const requests = [];
    w.api = async (method, url, body) => {
      requests.push({ method, url, body });
      return url === '/api/projects/demo' ? { configs: [{ config: 'parameters: {Name: example}' }] }
        : { result: 'invalid' };
    };
    await w.runProjectFromDetail('demo');
    assert.equal(requests.length, 2);
    assert.equal(requests[1].body.regions, '');
    assert.equal(requests[1].body.template_content, '');
    assert.equal(yaml.load(requests[1].body.config_content).tests.default.parameters.Name, 'example');
    w.document.getElementById('btn-project-detail-run').disabled = true;
    await w.runProjectFromDetail('demo');
    assert.equal(requests.length, 2);
  } finally { close(); }
});

test('task template viewer preserves content when the YAML parser is unavailable', () => {
  const { window: w, close } = setup();
  try {
    w.renderRunTemplate({ params: { raw_template_content: 'Resources: {}' } });
    w.jsyaml = undefined;
    w.document.querySelector('#detail-template [data-run-format="json"]').click();
    assert.equal(w.document.getElementById('run-template-content').textContent, 'Resources: {}');
    w.renderRunTemplate({});
    assert.equal(w.document.getElementById('run-template-content').textContent.trim(), '');
    w.renderRunConfig({});
    assert.ok(w.document.getElementById('detail-params').querySelector('.empty-state'));
  } finally { close(); }
});

test('version activation and deletion send requests only after confirmation', async () => {
  const { window: w, close } = setup();
  try {
    const requests = [];
    w.showConfirm = async () => true;
    w.loadProjectDetail = async () => {};
    w.fetch = async (url, options) => {
      requests.push({ url, method: options.method });
      return { ok: true, status: 200, headers: { get: () => 'application/json' },
        text: async () => JSON.stringify({ auto_switched: true, current_version: 2 }) };
    };
    await w.activateVersion('demo', 1);
    await w.deleteVersion('demo', 1);
    assert.deepEqual(requests, [
      { url: '/api/projects/demo/versions/1/activate', method: 'POST' },
      { url: '/api/projects/demo/versions/1', method: 'DELETE' },
    ]);
    w.showConfirm = async () => false;
    await w.deleteVersion('demo', 2);
    assert.equal(requests.length, 2);
  } finally { close(); }
});

test('prevalidation blocks missing credentials, missing regions and invalid templates', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.settings = {source: 'none'}; state.pgRegionSelect = {getSelected: () => []}", context);
    assert.equal(await w.prevalidate('run'), false);
    assert.ok(w.document.getElementById('confirm-modal').classList.contains('open'));
    w.document.getElementById('confirm-modal-ok').click();
    vm.runInContext("state.settings = {source: 'env'}", context);
    assert.equal(await w.prevalidate('run'), false);
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.document.getElementById('template-editor').value = 'Resources: {}';
    w.document.getElementById('config-editor').value = 'parameters: {}';
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ result: 'invalid', logs: 'validation error' }) });
    assert.equal(await w.prevalidate('run'), false);
  } finally { close(); }
});

test('prevalidation asks before unresolved automatic parameters are used', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.settings = {source: 'env'}; state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.document.getElementById('template-editor').value = 'Resources: {}';
    w.document.getElementById('config-editor').value = 'parameters:\n  VpcId: $[iact3-auto]';
    let calls = 0;
    w.fetch = async () => {
      calls++;
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => '{"result":"valid"}' };
    };
    const cancel = w.prevalidate('run');
    w.document.getElementById('confirm-modal-cancel').click();
    assert.equal(await cancel, false);
    assert.equal(calls, 0);
    const proceed = w.prevalidate('run');
    w.document.getElementById('confirm-modal-ok').click();
    assert.equal(await proceed, true);
    assert.equal(calls, 1);
  } finally { close(); }
});

test('prevalidation warns about unresolved placeholders even when no parameter name can be parsed', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.settings = {source: 'env'}; state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.getRunPayload = () => ({ template_content: 'Resources: {}', config_content: 'message: prefix-$[iact3-auto]' });
    let prompt;
    w.showConfirm = async (message, options) => { prompt = [message, options]; return false; };
    let requests = 0;
    w.api = async () => { requests++; return { result: 'valid' }; };
    assert.equal(await w.prevalidate('Run'), false);
    assert.ok(prompt);
    assert.equal(requests, 0);
  } finally { close(); }
});

test('prevalidation refuses to run before a region selector is available', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.settings = {source: 'env'}; state.pgRegionSelect = null", context);
    let requests = 0;
    w.api = async () => { requests++; };
    w.updateRegionHint();
    assert.equal(w.document.getElementById('config-region-hint').style.display, 'none');
    assert.equal(await w.prevalidate('Run'), false);
    assert.equal(requests, 0);
    assert.ok(w.document.getElementById('toast').classList.contains('error'));
  } finally { close(); }
});

test('prevalidation offers a fallback continue label for unresolved parameters', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.settings = {source: 'env'}; state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.document.getElementById('template-editor').value = 'Resources: {}';
    w.document.getElementById('config-editor').value = 'parameters:\n  VpcId: $[iact3-auto]';
    w.t = () => '';
    let options;
    w.showConfirm = async (message, config) => { options = config; return false; };
    let calls = 0;
    w.api = async () => { calls++; return { result: 'valid' }; };
    assert.equal(await w.prevalidate('Run'), false);
    assert.equal(options.okText, 'Continue');
    assert.equal(calls, 0);
  } finally { close(); }
});

test('inline prompt accepts input and supports cancellation', async () => {
  const { window: w, close } = setup();
  try {
    const anchor = w.document.getElementById('template-editor');
    const first = w.showInlinePrompt({ anchorEl: anchor, title: 'New file', defaultValue: '  main.tf  ' });
    w.document.querySelector('.tf-prompt-ok').click();
    assert.equal(await first, 'main.tf');
    assert.equal(w.document.querySelector('.tf-prompt-popover'), null);
    const second = w.showInlinePrompt({ anchorEl: anchor });
    w.document.querySelector('.tf-prompt-input').dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape' }));
    assert.equal(await second, null);
  } finally { close(); }
});

test('task detail loads a run and renders its stacks and raw template', async () => {
  const { window: w, context, close } = setup();
  try {
    const run = { id: 'run', name: 'Example', status: 'completed', progress: 100,
      created_at: '2026-01-01T00:00:00Z', params: { raw_template_content: 'Resources: {}', raw_config_content: '' },
      stacks: [{ stack_id: 'stack-1', region: 'cn-a', status: 'CREATE_COMPLETE', launch_succeeded: true }] };
    w.fetch = async url => ({ ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(run) });
    w.renderCliLogs = async () => {};
    await w.loadDetail('run');
    assert.equal(vm.runInContext('state.currentRunId', context), 'run');
    assert.match(w.document.getElementById('detail-overview').textContent, /Example/);
    assert.match(w.document.getElementById('detail-stacks').textContent, /stack-1/);
    assert.match(w.document.getElementById('detail-template').textContent, /Resources/);
  } finally { close(); }
});

test('task detail resets the tab once and keeps it on later refreshes', async () => {
  const { window: w, context, close } = setup();
  try {
    const tabs = [], rendered = [];
    w.switchTaskDetailTab = name => tabs.push(name);
    w.renderDetail = run => rendered.push(run.id);
    w.checkStopTaskPolling = () => {};
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ id: 'run', status: 'running' }) });
    vm.runInContext('state._detailNeedsTabReset = true', context);
    await w.loadDetail('run');
    await w.loadDetail('run');
    assert.deepEqual(tabs, ['overview']);
    assert.deepEqual(rendered, ['run', 'run']);
    w.fetch = async () => { throw new Error('offline'); };
    await w.loadDetail('run');
    assert.match(w.document.getElementById('toast').textContent, /offline/);
  } finally { close(); }
});

test('navigation loads the appropriate page and resets task detail pagination', () => {
  const { window: w, context, close } = setup();
  try {
    const calls = [];
    w.startTaskPolling = () => calls.push('poll');
    w.loadTasks = () => calls.push('tasks');
    w.loadProjects = () => calls.push('projects');
    w.loadDetail = id => calls.push(['detail', id]);
    w.loadProjectDetail = name => calls.push(['project', name]);
    vm.runInContext('state._stacksPage = 4', context);
    w.navigate('tasks');
    w.navigate('projects');
    w.navigate('detail', { runId: 'run' });
    w.navigate('project-detail', { projectName: 'demo' });
    assert.deepEqual(calls, ['poll', 'tasks', 'projects', 'poll', ['detail', 'run'], ['project', 'demo']]);
    assert.equal(vm.runInContext('state._stacksPage', context), 1);
    assert.equal(vm.runInContext('state._detailNeedsTabReset', context), true);
    assert.equal(vm.runInContext('state.currentProjectName', context), 'demo');
  } finally { close(); }
});

test('task list ignores stale responses from earlier requests', async () => {
  const { window: w, context, close } = setup();
  try {
    let resolveFirst;
    let count = 0;
    w.fetch = async () => {
      count++;
      if (count === 1) return new Promise(resolve => { resolveFirst = resolve; });
      return { ok: true, status: 200, headers: { get: () => 'application/json' },
        text: async () => JSON.stringify({ runs: [{ id: 'new', status: 'completed' }], total: 1 }) };
    };
    const first = w.loadTasks();
    await w.loadTasks();
    resolveFirst({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ runs: [{ id: 'old', status: 'completed' }], total: 1 }) });
    await first;
    assert.equal(vm.runInContext('state.tasks[0].id', context), 'new');
  } finally { close(); }
});

test('project detail loads project and run history together', async () => {
  const { window: w, context, close } = setup();
  try {
    const requests = [];
    w.fetch = async url => {
      requests.push(url);
      const data = url.endsWith('/runs') ? { runs: [{ id: 'run', name: 'Test', status: 'completed', stacks: [] }] }
        : url.endsWith('/versions') ? { versions: [] }
        : { name: 'demo', template: 'Resources: {}', config: '' };
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(data) };
    };
    await w.loadProjectDetail('demo');
    assert.equal(vm.runInContext('state.currentProjectName', context), 'demo');
    assert.match(w.document.getElementById('project-detail-runs').textContent, /Test/);
    assert.ok(requests.includes('/api/projects/demo/runs'));
    await new Promise(resolve => setImmediate(resolve));
  } finally { close(); }
});

test('run button retains request id after failure and clears it after successful retry', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.document.getElementById('template-editor').value = 'Resources: {}';
    w.document.getElementById('config-editor').value = 'parameters: {}';
    w.prevalidate = async () => true;
    w.pollRunInModal = () => {};
    const attempts = [];
    w.fetch = async (url, options) => {
      attempts.push(JSON.parse(options.body));
      const ok = attempts.length > 1;
      return { ok, status: ok ? 200 : 503, headers: { get: () => 'application/json' },
        text: async () => JSON.stringify(ok ? { id: 'run', status: 'running' } : { error: 'temporary failure' }) };
    };
    w.bindPlayground();
    const button = w.document.getElementById('btn-run');
    button.click();
    for (let i = 0; i < 20 && (attempts.length < 1 || button.disabled); i++) await new Promise(resolve => setImmediate(resolve));
    assert.equal(attempts.length, 1);
    assert.equal(vm.runInContext('state.pendingRunRequestId', context), attempts[0].request_id);
    button.click();
    for (let i = 0; i < 20 && (attempts.length < 2 || button.disabled); i++) await new Promise(resolve => setImmediate(resolve));
    assert.equal(attempts.length, 2);
    assert.equal(attempts[1].request_id, attempts[0].request_id);
    assert.equal(vm.runInContext('state.pendingRunRequestId', context), null);
  } finally { close(); }
});

test('run button displays startup logs and fallback result title', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.document.getElementById('template-editor').value = 'Resources: {}';
    w.t = () => '';
    w.prevalidate = async () => true;
    const logs = [], results = [], polls = [];
    w.consoleLog = (message, options) => logs.push([message, options.action]);
    w.showActionResult = (action, title, run, type) => results.push([action, title, run.id, type]);
    w.pollRunInModal = id => polls.push(id);
    w.api = async () => ({ id: 'run-id', status: 'running', logs: 'started' });
    w.bindPlayground();
    const button = w.document.getElementById('btn-run');
    button.click();
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(logs, [['started', 'run']]);
    assert.deepEqual(results, [['run', 'Run Started', 'run-id', 'run']]);
    assert.deepEqual(polls, ['run-id']);
    assert.equal(button.disabled, false);
    assert.equal(vm.runInContext('state.pendingRunRequestId', context), null);
  } finally { close(); }
});

test('project run stops after invalid validation and explains the failure without translations', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.t = () => '';
    const calls = [], notices = [], logs = [];
    w.toast = (message, type) => notices.push([message, type]);
    w.consoleLog = message => logs.push(message);
    w.api = async (method, path) => {
      calls.push([method, path]);
      return method === 'GET' ? { template: 'Resources: {}' } : { result: 'invalid', error: 'denied' };
    };
    await w.runProjectFromDetail('demo');
    assert.deepEqual(calls, [['GET', '/api/projects/demo'], ['POST', '/api/validate']]);
    assert.deepEqual(notices, [['Validating...', 'info'], ['Validation failed before Run', 'error']]);
    assert.match(logs[0], /denied/);
    assert.equal(w.document.getElementById('btn-project-detail-run').disabled, false);
  } finally { close(); }
});

test('sample loading switches between Terraform and ROS templates', async () => {
  const { window: w, context, close } = setup();
  try {
    w.fetch = async url => {
      const data = url.endsWith('/tf') ? { template_files: { 'main.tf': 'resource {}' }, config: 'parameters: {}' }
        : { template: '{"Resources":{}}', config: 'parameters: {A: 1}' };
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(data) };
    };
    await w.loadSample('tf');
    assert.equal(vm.runInContext('state.tfMode', context), true);
    assert.equal(w.document.getElementById('template-editor').value, 'resource {}');
    await w.loadSample('ros');
    assert.equal(vm.runInContext('state.tfMode', context), false);
    assert.equal(w.document.getElementById('template-editor').value, '{"Resources":{}}');
    assert.equal(vm.runInContext('state.templateFormat', context), 'json');
  } finally { close(); }
});

test('loading an empty sample clears prior Terraform and configuration content', async () => {
  const { window: w, context, close } = setup();
  try {
    w.enterTfMode({ 'main.tf': 'resource {}' });
    w.document.getElementById('config-editor').value = 'parameters: {Old: value}';
    w.api = async () => ({});
    await w.loadSample('empty');
    assert.equal(vm.runInContext('state.tfMode', context), false);
    assert.equal(vm.runInContext('state.templateFormat', context), 'yaml');
    assert.equal(w.document.getElementById('template-editor').value, '');
    assert.equal(w.document.getElementById('config-editor').value, '');
  } finally { close(); }
});

test('project editor adds and deletes Terraform files and folders', async () => {
  const { window: w, context, close } = setup();
  try {
    w.showPrompt = async () => 'main.tf';
    await w.addProjectEditTfFile();
    assert.equal(vm.runInContext("state.projectEditTfFiles['main.tf']", context), '');
    w.showPrompt = async () => 'modules';
    await w.addProjectEditTfFolder();
    assert.equal(vm.runInContext("state.projectEditTfFiles['modules/']", context), '');
    w.showConfirm = async () => true;
    await w.deleteProjectEditTfFile('main.tf');
    assert.equal(vm.runInContext("Object.hasOwn(state.projectEditTfFiles, 'main.tf')", context), false);
  } finally { close(); }
});

test('stack cleanup reports partial errors and refreshes task details', async () => {
  const { window: w, close } = setup();
  try {
    let loaded;
    w.showConfirm = async () => true;
    w.startTaskPolling = () => {};
    w.loadDetail = async id => { loaded = id; };
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ deleted: 1, errors: 1, details: [{ error: 'access denied' }] }) });
    await w.deleteRunStacks('run');
    assert.equal(loaded, 'run');
    assert.match(w.document.getElementById('toast').textContent, /access denied/);
    assert.ok(w.document.getElementById('toast').classList.contains('warning'));
  } finally { close(); }
});

test('project polling updates the displayed history when status changes', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.currentProject = {name: 'demo'}; state.currentProjectRuns = [{id: 'run', status: 'running'}]", context);
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ runs: [{ id: 'run', name: 'Test', status: 'completed', stacks: [] }] }) });
    await w.pollProjectRuns('demo');
    assert.equal(vm.runInContext('state.currentProjectRuns[0].status', context), 'completed');
    assert.match(w.document.getElementById('project-detail-runs').textContent, /Test/);
  } finally { close(); }
});

test('project polling keeps unchanged history and ignores transient failures', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.currentProject = {name:'demo'}; state.currentProjectRuns = [{id:'run', status:'running'}]", context);
    const renders = [];
    w.renderProjectRunHistory = (element, runs) => renders.push(runs.length);
    let response = { runs: [{ id: 'run', status: 'running' }] };
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify(response) });
    await w.pollProjectRuns('demo');
    assert.deepEqual(renders, []);
    response = { runs: [] };
    await w.pollProjectRuns('demo');
    assert.deepEqual(renders, [0]);
    w.fetch = async () => { throw new Error('offline'); };
    await w.pollProjectRuns('demo');
    assert.deepEqual(renders, [0]);
    assert.equal(vm.runInContext('state.currentProjectRuns.length', context), 0);
  } finally { close(); }
});

test('project polling handles an absent run list while no project is displayed', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.currentProject = null; state.currentProjectRuns = [{id:'run', status:'running'}]", context);
    let renders = 0;
    w.renderProjectRunHistory = () => { renders++; };
    w.api = async () => ({});
    await w.pollProjectRuns('demo');
    assert.equal(vm.runInContext('state.currentProjectRuns.length', context), 0);
    assert.equal(renders, 0);
  } finally { close(); }
});

test('project polling initializes an absent history and tolerates a missing pagination control', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext('state.currentProjectRuns = null; state.currentProject = null', context);
    w.api = async () => ({ runs: [{ id: 'run', status: 'running' }] });
    await w.pollProjectRuns('demo');
    assert.equal(vm.runInContext('state.currentProjectRuns[0].id', context), 'run');
    w.document.getElementById('run-history-pagination').remove();
    const runs = w.document.getElementById('project-detail-runs');
    w.renderProjectRunHistory(runs, [], { name: 'demo' });
    assert.ok(runs.querySelector('.empty-state'));
    w.renderRunHistoryPagination(20);
  } finally { close(); }
});

test('report viewer escapes content and copies the selected log', async () => {
  const { window: w, close } = setup();
  try {
    let copied = '';
    w.copyToClipboard = async text => { copied = text; };
    const report = w.document.createElement('div');
    report.id = 'detail-report';
    w.document.body.appendChild(report);
    w.renderReport({ logs: [{ name: '<log>', content: '<script>alert(1)</script>' }] });
    const container = w.document.getElementById('detail-report');
    assert.equal(container.querySelector('script'), null);
    assert.ok(container.textContent.includes('<script>'));
    container.querySelector('.log-copy').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(copied, '<script>alert(1)</script>');
    w.renderReport({ logs: [] });
    assert.ok(container.querySelector('.empty-state'));
  } finally { close(); }
});

test('report viewer handles omitted logs and copies an empty log', async () => {
  const { window: w, close } = setup();
  try {
    const report = w.document.createElement('div');
    report.id = 'detail-report';
    w.document.body.appendChild(report);
    w.renderReport({});
    assert.ok(report.querySelector('.empty-state'));
    let copied = null;
    w.copyToClipboard = async text => { copied = text; };
    w.renderReport({ logs: [{ name: 'empty' }] });
    report.querySelector('.log-copy').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(copied, '');
  } finally { close(); }
});

test('task detail treats a missing stack list as empty', () => {
  const { window: w, close } = setup();
  try {
    w.renderCliLogs = () => {};
    w.renderDetail({ id: 'run', name: 'Task', status: 'completed', stacks: null });
    assert.ok(w.document.getElementById('detail-stacks').querySelector('.empty-state'));
    assert.equal(w.document.querySelector('#detail-header-actions .btn-delete-stacks'), null);
    assert.equal(w.document.querySelector('#detail-header-actions .btn-cancel-task'), null);
    w.renderDetail({ id: 'run', name: 'Task', status: 'completed', stacks: [{ stack_id: 'stack' }] });
    assert.ok(w.document.querySelector('#detail-header-actions .btn-delete-stacks'));
  } finally { close(); }
});

test('CLI output formatter handles nested, empty and circular values', () => {
  const { window: w, close } = setup();
  try {
    const data = { name: 'demo', empty: [], child: { value: null } };
    data.self = data;
    const text = w.formatCliOutput(data);
    assert.match(text, /name: demo/);
    assert.match(text, /<empty list>/);
    assert.match(text, /value: <null>/);
    assert.match(text, /<circular>/);
  } finally { close(); }
});

test('language switching updates visible text, placeholders, titles and emits an event', () => {
  const { window: w, context, close } = setup();
  try {
    const label = w.document.createElement('span');
    label.dataset.i18n = 'runBtn';
    const input = w.document.createElement('input');
    input.dataset.i18nPlaceholder = 'runBtn';
    input.dataset.i18nTitle = 'runBtn';
    w.document.body.append(label, input);
    let language;
    w.addEventListener('iact3-lang-change', event => { language = event.detail; });
    w.setLang('zh');
    assert.equal(label.textContent, w.t('runBtn'));
    assert.equal(input.placeholder, label.textContent);
    assert.equal(input.title, label.textContent);
    assert.equal(language, 'zh');
    assert.equal(w.localStorage.getItem('iact3-lang'), 'zh');
    assert.equal(w.extractErrorMessage(''), '');
    assert.match(w.extractErrorMessage('ResultReason: StackValidationFailed'), /资源栈校验失败/);
    assert.match(w.translateStatusReason('Resource CREATE failed: code: 403'), /资源创建失败.*状态码/);
    w.setLang('unsupported');
    assert.equal(w.t('runBtn'), vm.runInContext('I18N.en.runBtn', context));
    assert.equal(w.tStackStatus('UNKNOWN'), 'UNKNOWN');
  } finally { close(); }
});

test('API helper preserves plain errors and non-JSON responses', async () => {
  const { window: w, close } = setup();
  try {
    w.fetch = async () => ({ ok: false, status: 502, headers: { get: () => 'text/plain' }, text: async () => 'upstream failed' });
    await assert.rejects(w.api('GET', '/api/failure'), /upstream failed/);
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => 'not json' });
    assert.equal((await w.api('GET', '/api/raw')).raw, 'not json');
    w.fetch = async () => ({ ok: false, status: 500, headers: { get: () => 'application/json' }, text: async () => '{}' });
    await assert.rejects(w.api('GET', '/api/failure'), /GET \/api\/failure failed \(500\)/);
  } finally { close(); }
});

test('run request IDs use crypto when available and produce UUIDs on older browsers', () => {
  const { window: w, close } = setup();
  try {
    Object.defineProperty(w.crypto, 'randomUUID', { configurable: true, value: () => 'crypto-id' });
    assert.equal(w.newRunRequestId(), 'crypto-id');
    Object.defineProperty(w.crypto, 'randomUUID', { configurable: true, value: undefined });
    const first = w.newRunRequestId();
    const second = w.newRunRequestId();
    assert.match(first, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    assert.match(second, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    assert.notEqual(first, second);
  } finally { close(); }
});

test('sample names and multi-region hints reflect language and selected regions', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.samples = [{id:'one', name:'English', zh_name:'中文'}, {id:'two', name:'Default'}]; state.lang = 'zh'", context);
    w.populateSamples();
    const select = w.document.getElementById('sample-select');
    assert.deepEqual(Array.from(select.options, option => option.textContent), ['中文', 'Default']);
    vm.runInContext("state.lang = 'en'; state.pgRegionSelect = {getSelected: () => ['cn-a', 'cn-b']}", context);
    w.populateSamples();
    assert.equal(select.options[0].textContent, 'English');
    w.t = () => '';
    w.updateRegionHint();
    const hint = w.document.getElementById('config-region-hint');
    assert.match(hint.textContent, /resolved per region/);
    assert.equal(hint.style.display, 'inline');
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.updateRegionHint();
    assert.equal(hint.style.display, 'none');
  } finally { close(); }
});

test('confirm and prompt dialogs handle keyboard and backdrop cancellation', async () => {
  const { window: w, close } = setup();
  try {
    const verified = w.showConfirm('Confirm?', { verify: { expected: 'yes' } });
    const input = w.document.getElementById('confirm-modal-verify-input');
    input.value = 'yes';
    input.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter' }));
    assert.equal(await verified, true);
    const confirm = w.showConfirm('Cancel?');
    w.document.getElementById('confirm-modal').click();
    assert.equal(await confirm, false);
    const prompt = w.showPrompt({ defaultValue: ' value ' });
    w.document.getElementById('prompt-modal-input').dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter' }));
    assert.equal(await prompt, 'value');
  } finally { close(); }
});

test('dialogs ignore clicks inside their content and reject an incorrect verification', async () => {
  const { window: w, close } = setup();
  try {
    const confirmation = w.showConfirm('Confirm?', { verify: { expected: 'yes' } });
    const modal = w.document.getElementById('confirm-modal');
    const input = w.document.getElementById('confirm-modal-verify-input');
    input.value = 'no';
    input.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter' }));
    w.document.getElementById('confirm-modal-message').click();
    assert.ok(modal.classList.contains('open'));
    modal.click();
    assert.equal(await confirmation, false);

    const prompt = w.showPrompt({ title: 'Name', placeholder: 'enter name', okText: 'Save', cancelText: 'Cancel' });
    const promptModal = w.document.getElementById('prompt-modal');
    w.document.getElementById('prompt-modal-title').click();
    assert.ok(promptModal.classList.contains('open'));
    assert.equal(w.document.getElementById('prompt-modal-ok').textContent, 'Save');
    assert.equal(w.document.getElementById('prompt-modal-cancel').textContent, 'Cancel');
    promptModal.click();
    assert.equal(await prompt, null);
  } finally { close(); }
});

test('policy and result modals render data and copy visible text', async () => {
  const { window: w, close } = setup();
  try {
    let copied = '';
    w.copyToClipboard = async text => { copied = text; };
    w.openPolicyModal({ Statement: [] });
    assert.ok(w.document.getElementById('policy-modal').classList.contains('open'));
    await w.copyPolicyToClipboard();
    assert.match(copied, /Statement/);
    w.openResultModal('Result', { ok: true }, 'json');
    assert.match(w.document.getElementById('result-body').textContent, /"ok"/);
    await w.copyResultToClipboard();
    assert.match(copied, /"ok"/);
    w.openResultModal('Result', '<b>html</b>', 'html');
    assert.equal(w.document.querySelector('#result-body b').textContent, 'html');
  } finally { close(); }
});

test('policy and run result modals render raw strings safely and expose run details', () => {
  const { window: w, close } = setup();
  try {
    w.openPolicyModal('<script>bad</script>');
    const policy = w.document.getElementById('policy-body');
    assert.equal(policy.textContent, '<script>bad</script>');
    assert.equal(policy.querySelector('script'), null);
    w.openResultModal('Run', { id: 'run-id', name: 'task', status: 'running', stacks: [] }, 'run');
    const result = w.document.getElementById('result-body');
    assert.match(result.textContent, /run-id/);
    assert.match(result.textContent, /task/);
    assert.equal(w.document.querySelector('.modal-content-result').dataset.type, 'run');
  } finally { close(); }
});

test('result modal defaults to JSON and log output defaults to the run panel', () => {
  const { window: w, context, close } = setup();
  try {
    w.openResultModal('Result', { value: 1 });
    assert.match(w.document.getElementById('result-body').textContent, /"value": 1/);
    vm.runInContext("state.pgRegionSelect = {getSelected: () => []}", context);
    w.showActionResult('policy', 'Policy', { value: 1 });
    assert.match(w.document.getElementById('result-policy').textContent, /"value": 1/);
    vm.runInContext('state.currentAction = null', context);
    w.consoleLog('default action');
    assert.match(w.document.getElementById('log-run').textContent, /default action/);
    w.syncOutputSections(null);
  } finally { close(); }
});

test('running status uses fallback duration label while translations are unavailable', () => {
  const { window: w, context, close } = setup();
  try {
    w.t = () => '';
    vm.runInContext('state.runActiveTab = null', context);
    const html = w.renderRunStatusHtml({ status: 'running', created_at: '2026-01-01T00:00:00Z' });
    assert.match(html, /Duration/);
    assert.match(html, /data-run-tab="detail"/);
  } finally { close(); }
});

test('Terraform context menu invokes actions and closes', async () => {
  const { window: w, close } = setup();
  try {
    w.enterTfMode({ 'main.tf': 'content' });
    const node = w.document.querySelector('#tf-file-list .tf-tree-node');
    let target;
    w.deleteTfFile = async path => { target = path; };
    w.showTfNodeMenu(node, 'main.tf', false);
    const menu = w.document.querySelector('.tf-node-menu');
    assert.ok(menu);
    menu.querySelector('[data-action="delete"]').click();
    assert.equal(target, 'main.tf');
    assert.equal(w.document.querySelector('.tf-node-menu'), null);
  } finally { close(); }
});

test('action output panels show results, retain separate tabs and clear safely', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.document.getElementById('template-editor').value = 'Resources: {}';
    w.showActionLoading('cost', 'Calculating');
    assert.match(w.document.getElementById('result-cost').textContent, /Calculating/);
    w.showActionResult('policy', 'Policy', { value: '<safe>' }, 'json');
    assert.match(w.document.getElementById('result-policy').textContent, /<safe>/);
    assert.equal(w.document.querySelector('#result-policy safe'), null);
    w.showActionResult('cost', 'Cost', '<b>price</b>', 'html');
    assert.equal(w.document.querySelector('#result-cost b').textContent, 'price');
    w.setCurrentAction('policy');
    assert.equal(w.document.getElementById('pg-output-title').textContent, 'Policy');
    w.clearAllActionOutputs();
    assert.equal(w.document.getElementById('result-cost').textContent, '');
    assert.equal(w.document.getElementById('result-policy').textContent, '');
    assert.ok(w.document.getElementById('pg-output').classList.contains('collapsed'));
  } finally { close(); }
});

test('clearing output tolerates a missing log panel', () => {
  const { window: w, context, close } = setup();
  try {
    w.document.getElementById('log-cost').remove();
    vm.runInContext("state.currentAction = 'cost'", context);
    w.clearResultPanel();
    vm.runInContext('state.currentAction = null; state._hasActionOutput = true', context);
    w.clearResultPanel();
    w.clearAllActionOutputs();
    assert.equal(vm.runInContext('state._hasActionOutput', context), false);
    assert.ok(w.document.getElementById('pg-output').classList.contains('collapsed'));
  } finally { close(); }
});

test('log entries escape text, expand and clear without changing other tabs', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.currentAction = 'run'", context);
    const longText = Array.from({ length: 25 }, (_, i) => `line ${i}`).join('\n');
    w.consoleLog(longText, { action: 'run', type: 'error' });
    const log = w.document.getElementById('log-run');
    const content = log.querySelector('.log-entry-content');
    assert.ok(content.classList.contains('collapsed'));
    log.querySelector('.log-entry-toggle').click();
    assert.equal(content.classList.contains('collapsed'), false);
    w.consoleClear();
    assert.equal(log.textContent, '');
    w.consoleLog('2026-01-01 00:00:00,000 [ERROR] : <bad>', { action: 'run', raw: true });
    assert.equal(log.querySelector('bad'), null);
    assert.match(log.textContent, /<bad>/);
  } finally { close(); }
});

test('terminal logs render levels and plain lines, and copy errors are surfaced', async () => {
  const { window: w, close } = setup();
  try {
    const log = w.document.getElementById('log-run');
    w.consoleLog('  ', { action: 'run' });
    assert.equal(log.children.length, 0);
    w.consoleLog('missing panel', { action: 'nonexistent' });
    w.consoleLog('2026-01-01 00:00:00,000 [WARNING] : caution\n\n' +
      '2026-01-01 00:00:00,000 [INFO] : ok\n' +
      '2026-01-01 00:00:00,000 [DEBUG] : details\nplain <line>', { raw: true });
    assert.equal(log.querySelectorAll('.term-warning').length, 1);
    assert.equal(log.querySelectorAll('.term-info').length, 1);
    assert.equal(log.querySelectorAll('.term-debug').length, 1);
    assert.match(log.textContent, /plain <line>/);
    assert.equal(log.querySelector('line'), null);
    w.consoleClear();
    const notices = [];
    w.copyToClipboard = async () => { throw new Error('clipboard denied'); };
    w.toast = (message, type) => notices.push(type);
    w.consoleLog('message', { type: 'warn', level: 'CUSTOM' });
    log.querySelector('.log-entry-copy').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(notices, ['error']);
    assert.ok(log.querySelector('.log-level-custom'));
  } finally { close(); }
});

test('long log entries use fallback labels and report clipboard success or failure', async () => {
  const { window: w, close } = setup();
  try {
    const notices = [];
    let copied;
    w.t = () => '';
    w.toast = (message, type) => notices.push([message, type]);
    w.copyToClipboard = async text => { copied = text; };
    const text = Array.from({ length: 21 }, (_, i) => `line ${i}`).join('\n');
    w.consoleLog(text, { action: 'run', type: 'success' });
    const log = w.document.getElementById('log-run');
    const toggle = log.querySelector('.log-entry-toggle');
    assert.equal(toggle.textContent, 'Expand');
    toggle.click();
    assert.equal(toggle.textContent, 'Collapse');
    toggle.click();
    assert.equal(toggle.textContent, 'Expand');
    const copy = log.querySelector('.log-entry-copy');
    assert.equal(copy.textContent, 'Copy');
    copy.click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(copied, text);
    w.copyToClipboard = async () => { throw new Error('denied'); };
    copy.click();
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(notices, [['Copied', 'success'], ['Copy failed', 'error']]);
  } finally { close(); }
});

test('run status retains readable labels when translations are empty', () => {
  const { window: w, close } = setup();
  try {
    w.t = () => '';
    const html = w.renderRunStatusHtml({ id: 'id-1', name: 'task', status: 'failed', progress: 25,
      created_at: '2026-01-01T00:00:00Z', completed_at: '2026-01-01T00:00:30Z',
      report_url: '/report', error: '<failure>' });
    for (const label of ['Run ID', 'Status', 'Name', 'Created', 'Progress', 'Finished', 'Duration',
      'Report', 'View Report', 'Error', 'No stacks yet.']) assert.match(html, new RegExp(label));
    assert.match(html, /&lt;failure&gt;/);
    assert.match(html, /25%/);
    assert.match(html, /status-failed/);
  } finally { close(); }
});

test('Terraform actions use fallback prompts and retain files after name conflicts', async () => {
  const { window: w, context, close } = setup();
  try {
    w.enterTfMode({ 'main.tf': 'content', 'module/': '' });
    w.t = () => '';
    const prompts = [], notices = [];
    w.toast = (message, type) => notices.push([message, type]);
    w.showInlinePrompt = async options => { prompts.push(options); return options.defaultValue; };
    await w.createTfFile();
    await w.createTfFolder();
    assert.equal(prompts[0].title, 'Create File');
    assert.equal(prompts[0].placeholder, 'e.g. main.tf');
    assert.equal(prompts[1].title, 'Create Folder');
    assert.equal(prompts[1].placeholder, 'e.g. modules');
    assert.deepEqual(notices, [['File already exists', 'error']]);
    assert.equal(vm.runInContext("state.tfFiles['main.tf']", context), 'content');
    assert.equal(vm.runInContext("Object.hasOwn(state.tfFiles, 'modules/')", context), true);
    w.showPrompt = async options => { prompts.push(options); return 'modules'; };
    await w.renameTfNode('module', true);
    assert.equal(prompts[2].title, 'Rename Folder');
    assert.deepEqual(notices[1], ['Target already exists', 'error']);
    assert.equal(vm.runInContext("Object.hasOwn(state.tfFiles, 'module/')", context), true);
  } finally { close(); }
});

test('Terraform delete and rename confirmations use fallback text without overwriting files', async () => {
  const { window: w, context, close } = setup();
  try {
    w.enterTfMode({ 'main.tf': 'main', 'other.tf': 'other', 'folder/a.tf': 'a' });
    w.t = () => '';
    const confirmations = [], notices = [];
    w.toast = (message, type) => notices.push([message, type]);
    w.showConfirm = async message => { confirmations.push(message); return false; };
    await w.deleteTfFile('main.tf');
    await w.deleteTfFolder('folder');
    assert.deepEqual(confirmations, ['Delete file "main.tf"?', 'Delete folder "folder" and its contents?']);
    w.showPrompt = async () => 'other.tf';
    await w.renameTfNode('main.tf', false);
    assert.deepEqual(notices, [['File already exists', 'error']]);
    assert.equal(vm.runInContext("state.tfFiles['main.tf']", context), 'main');
    assert.equal(vm.runInContext("state.tfFiles['other.tf']", context), 'other');
  } finally { close(); }
});

test('deleting an inactive file preserves the editor and deleting the last folder clears it', async () => {
  const { window: w, context, close } = setup();
  try {
    w.enterTfMode({ 'folder/main.tf': 'main', 'other.tf': 'other' });
    w.openTfFile('folder/main.tf');
    w.document.getElementById('template-editor').value = 'editing';
    w.showConfirm = async () => true;
    await w.deleteTfFile('other.tf');
    assert.equal(w.document.getElementById('template-editor').value, 'editing');
    assert.equal(vm.runInContext('state.tfActiveFile', context), 'folder/main.tf');
    await w.deleteTfFolder('folder');
    assert.equal(vm.runInContext('state.tfActiveFile', context), null);
    assert.equal(w.document.getElementById('template-editor').value, '');
    assert.equal(vm.runInContext('Object.keys(state.tfFiles).length', context), 0);
  } finally { close(); }
});

test('project listing re-requests a valid page after the last page disappears', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.projectPage = 3; state.projectPerPage = 10", context);
    const requests = [];
    w.fetch = async url => {
      requests.push(url);
      return { ok: true, status: 200, headers: { get: () => 'application/json' },
        text: async () => JSON.stringify({ projects: [{ name: 'demo' }], total: 1 }) };
    };
    await w.loadProjects();
    assert.equal(requests.length, 2);
    assert.match(requests[0], /page=3/);
    assert.match(requests[1], /page=1/);
    assert.match(w.document.getElementById('projects-list').textContent, /demo/);
  } finally { close(); }
});

test('project listing keeps the search term when response omits projects and total', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.projectSearch = 'web demo'; state.projectPage = 1", context);
    let requested;
    w.api = async (method, url) => { requested = url; return {}; };
    await w.loadProjects();
    assert.match(requested, /search=web\+demo/);
    assert.equal(vm.runInContext('state.projects.length', context), 0);
    assert.equal(vm.runInContext('state.projectTotal', context), 0);
    assert.match(w.document.getElementById('projects-list').textContent, /no projects/i);
  } finally { close(); }
});

test('clipboard helper uses secure API or removes the fallback textarea', async () => {
  const { window: w, close } = setup();
  try {
    let copied;
    Object.defineProperty(w, 'isSecureContext', { value: true, configurable: true });
    Object.defineProperty(w.navigator, 'clipboard', { value: { writeText: async text => { copied = text; } }, configurable: true });
    await w.copyToClipboard('secure');
    assert.equal(copied, 'secure');
    Object.defineProperty(w, 'isSecureContext', { value: false, configurable: true });
    w.document.execCommand = command => { assert.equal(command, 'copy'); return true; };
    const before = w.document.querySelectorAll('textarea').length;
    await w.copyToClipboard('fallback');
    assert.equal(w.document.querySelectorAll('textarea').length, before);
  } finally { close(); }
});

test('status selector updates filter and clears selected tasks', () => {
  const { window: w, context, close } = setup();
  try {
    let calls = 0;
    w.loadTasks = async () => { calls++; };
    vm.runInContext("state.selectedTasks = new Set(['old']); state.taskPage = 3", context);
    w.initTaskStatusSelect();
    const container = w.document.getElementById('task-status-filter');
    container.querySelector('.custom-select-trigger').click();
    container.querySelector('[data-value="failed"]').click();
    assert.equal(vm.runInContext('state.taskStatusFilter', context), 'failed');
    assert.equal(vm.runInContext('state.taskPage', context), 1);
    assert.equal(vm.runInContext('state.selectedTasks.size', context), 0);
    assert.equal(calls, 1);
  } finally { close(); }
});

test('editor bindings convert formats and regenerate only after changed input', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    let generated = 0;
    w.autoGenerateParams = () => { generated++; };
    w.bindPlayground();
    const editor = w.document.getElementById('template-editor');
    editor.value = 'Resources: {}';
    editor.dispatchEvent(new w.Event('input'));
    const jsonTab = w.document.querySelector('.template-format-tabs .format-btn[data-format="json"]');
    jsonTab.click();
    assert.deepEqual(JSON.parse(editor.value), { Resources: {} });
    const pane = w.document.querySelector('.pg-body > .editor-pane:not(.config-editor-pane)');
    pane.dispatchEvent(new w.Event('mouseleave'));
    pane.dispatchEvent(new w.Event('mouseleave'));
    assert.equal(generated, 1);
    assert.equal(vm.runInContext('state._templateDirty', context), false);
  } finally { close(); }
});

test('template format controls preserve skeleton and report invalid conversion', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => []}", context);
    w.bindPlayground();
    const editor = w.document.getElementById('template-editor');
    const jsonTab = w.document.querySelector('.template-format-tabs .format-btn[data-format="json"]');
    const yamlTab = w.document.querySelector('.template-format-tabs .format-btn[data-format="yaml"]');
    editor.value = vm.runInContext('ROS_YAML_SKELETON', context);
    jsonTab.click();
    assert.equal(editor.value, vm.runInContext('ROS_JSON_SKELETON', context));
    yamlTab.click();
    assert.equal(editor.value, vm.runInContext('ROS_YAML_SKELETON', context));
    editor.value = 'Resources: [';
    const notices = [];
    w.toast = (message, type) => notices.push([message, type]);
    jsonTab.click();
    assert.equal(editor.value, 'Resources: [');
    assert.match(notices[0][0], /Format conversion failed/);
    assert.equal(notices[0][1], 'error');
    w.setTemplateTab('terraform');
    editor.value = 'resource {}';
    yamlTab.click();
    assert.equal(editor.value, 'resource {}');
  } finally { close(); }
});

test('playground converts JSON to YAML and ignores cancelled file selections', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.bindPlayground();
    const editor = w.document.getElementById('template-editor');
    editor.value = '{"Resources":{"Server":{}}}';
    w.document.querySelector('.template-format-tabs .format-btn[data-format="yaml"]').click();
    assert.deepEqual(yaml.load(editor.value), { Resources: { Server: {} } });
    for (const id of ['upload-template', 'upload-template-file']) {
      const input = w.document.getElementById(id);
      Object.defineProperty(input, 'files', { value: [], configurable: true });
      input.dispatchEvent(new w.Event('change'));
    }
    assert.deepEqual(yaml.load(editor.value), { Resources: { Server: {} } });
  } finally { close(); }
});

test('policy button validates before generating and Enter saves a project', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    const actions = [];
    w.prevalidate = async label => { actions.push(['validate', label]); return true; };
    w.generatePolicy = () => actions.push(['policy']);
    w.pgSaveFromPlayground = () => actions.push(['save']);
    w.bindPlayground();
    w.document.getElementById('btn-policy').click();
    await new Promise(resolve => setImmediate(resolve));
    w.document.getElementById('pg-project-name-input').dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter' }));
    assert.deepEqual(actions.map(item => item[0]), ['validate', 'policy', 'save']);
  } finally { close(); }
});

test('playground output actions copy and clear the active result', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.document.getElementById('template-editor').value = 'Resources: {}';
    let copied;
    w.copyToClipboard = async value => { copied = value; };
    w.bindPlayground();
    w.showActionResult('policy', 'Policy', { Action: 'read' }, 'json');
    w.document.getElementById('btn-copy-output').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.match(copied, /read/);
    w.document.getElementById('btn-clear-output').click();
    assert.equal(w.document.getElementById('result-policy').textContent, '');
  } finally { close(); }
});

test('cost button validates before estimating and modal controls close their own dialogs', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => []}", context);
    let valid = false, estimated = 0;
    w.prevalidate = async () => valid;
    w.estimateCost = () => { estimated++; };
    w.bindCost();
    w.document.getElementById('btn-cost').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(estimated, 0);
    valid = true;
    w.document.getElementById('btn-cost').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(estimated, 1);
    for (const id of ['policy', 'result']) {
      const modal = w.document.getElementById(`${id}-modal`);
      modal.classList.add('open');
      w.document.getElementById(`${id}-modal-close`).click();
      assert.equal(modal.classList.contains('open'), false);
      modal.classList.add('open');
      modal.click();
      assert.equal(modal.classList.contains('open'), false);
    }
  } finally { close(); }
});

test('playground save popover closes and clears invalid input on cancel or escape', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => []}", context);
    w.bindPlayground();
    const input = w.document.getElementById('pg-project-name-input');
    const popover = w.document.getElementById('pg-save-popover');
    for (const closeMethod of ['cancel', 'escape']) {
      w.document.getElementById('btn-pg-save-project').click();
      assert.ok(popover.classList.contains('open'));
      input.value = 'invalid/name';
      input.dispatchEvent(new w.Event('input'));
      assert.ok(input.classList.contains('input-invalid'));
      if (closeMethod === 'cancel') w.document.getElementById('btn-pg-save-cancel').click();
      else input.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape' }));
      assert.equal(popover.classList.contains('open'), false);
      assert.equal(input.value, '');
      assert.equal(input.classList.contains('input-invalid'), false);
    }
  } finally { close(); }
});

test('template upload selects ROS format or Terraform mode by extension', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => []}", context);
    w.FileReader = class { readAsText(file) { this.onload({ target: { result: file.content } }); } };
    w.bindPlayground();
    const input = w.document.getElementById('upload-template');
    for (const [name, content, mode, format] of [
      ['main.tf', 'resource {}', true, null],
      ['template.json', '{"Resources":{}}', false, 'json'],
      ['template.yaml', 'Resources: {}', false, 'yaml'],
    ]) {
      Object.defineProperty(input, 'files', { value: [{ name, content }], configurable: true });
      input.dispatchEvent(new w.Event('change'));
      assert.equal(vm.runInContext('state.tfMode', context), mode);
      if (format) assert.equal(vm.runInContext('state.templateFormat', context), format);
      assert.equal(w.document.getElementById('template-editor').value, content);
    }
  } finally { close(); }
});

test('stack detail pagination navigates pages and changes page size', () => {
  const { window: w, context, close } = setup();
  try {
    const stacks = Array.from({ length: 12 }, (_, i) => ({ stack_id: `stack-${i}`, region: { id: 'cn-a' },
      status: i === 11 ? 'DELETE_FAILED' : 'CREATE_COMPLETE', launch_succeeded: i !== 11,
      delete_error: i === 11 ? 'delete denied' : '' }));
    w.renderDetailStacks({ stacks });
    const container = w.document.getElementById('detail-stacks');
    assert.equal(container.querySelectorAll('.pd-stack-row').length, 10);
    container.querySelector('button[data-page="2"]').click();
    assert.equal(container.querySelectorAll('.pd-stack-row').length, 2);
    assert.match(container.textContent, /delete denied/);
    const row = container.querySelector('.pd-stack-row');
    row.querySelector('a').dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
    assert.ok(row.classList.contains('collapsed'));
    container.querySelector('.pagination-per-page-option[data-value="20"]').click();
    assert.equal(vm.runInContext('state._stacksPerPage', context), 20);
    assert.equal(container.querySelectorAll('.pd-stack-row').length, 12);
    w.renderDetailStacks({ stacks: [] });
    assert.ok(container.querySelector('.empty-state'));
  } finally { close(); }
});

test('cost results show per-resource service errors and empty prices', () => {
  const { window: w, close } = setup();
  try {
    const html = w.renderCostResultsHtml([{ test_name: 'test', region: 'cn-a', price: {
      Failing: { Success: false, Result: { Code: 'Denied', Message: '<no access>' } },
    } }]);
    assert.match(html, /Denied/);
    assert.match(html, /&lt;no access&gt;/);
    assert.match(html, /empty-state/);
    assert.equal(w.formatPrice(null), '-');
    assert.equal(w.formatPrice({}), '-');
    assert.match(w.formatPrice({ value: '<unsafe>' }), /&lt;unsafe&gt;/);
    assert.equal(w.formatCostAttributes([]), '-');
    assert.match(w.formatCostAttributes([{ Code: '<x>', Value: '<y>' }]), /&lt;x&gt;/);
  } finally { close(); }
});

test('cost results tolerate incomplete pricing records and unidentified errors', () => {
  const { window: w, close } = setup();
  try {
    const result = w.extractCostRows({ price: { Instance: {} } });
    assert.equal(result.rows.length, 1);
    assert.equal(result.rows[0].resource, 'Instance');
    assert.equal(result.rows[0].region, '-');
    assert.equal(result.rows[0].tradeAmount, null);
    assert.equal(result.rows[0].currency, '-');
    assert.equal(w.extractCostRows({}).rows.length, 0);
    const html = w.renderCostResultsHtml([{ error: 'service unavailable' }, { price: { Instance: {} } }]);
    assert.match(html, /service unavailable/);
    assert.match(html, /Instance/);
    const messages = [];
    w.consoleLog = message => messages.push(message);
    w.logCostSummary([{ error: 'service unavailable' }]);
    assert.match(messages[0], /service unavailable/);
  } finally { close(); }
});

test('language changes refresh loaded regions and cost results', async () => {
  const { window: w, context, close } = setup();
  try {
    const requests = [];
    w.fetch = async url => {
      requests.push(url);
      const data = url.startsWith('/api/regions') ? { regions: [{ id: 'cn-a', name: 'Region A' }] }
        : url === '/api/samples' ? { samples: [] } : { settings: { source: 'env' } };
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(data) };
    };
    await w.init();
    vm.runInContext("state.lastCostPrices = []; state.actionResults.cost = {title: 'old'}; state.currentAction = 'cost'", context);
    w.setLang('zh');
    for (let i = 0; i < 20 && !requests.some(url => url.includes('lang=zh')); i++) {
      await new Promise(resolve => setImmediate(resolve));
    }
    await new Promise(resolve => setImmediate(resolve));
    assert.ok(requests.some(url => url.includes('lang=zh')));
    assert.ok(w.document.getElementById('result-cost').querySelector('.empty-state'));
    w.stopTaskPolling();
  } finally { close(); }
});

test('language changes refresh the currently visible project, task, or detail page', async () => {
  const { window: w, context, close } = setup();
  try {
    w.fetch = async url => ({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify(url.startsWith('/api/regions') ? { regions: [] }
        : url === '/api/samples' ? { samples: [] } : { settings: {} }) });
    await w.init();
    w.stopTaskPolling();
    const calls = [];
    for (const name of ['renderProjects', 'renderProjectPagination', 'updateProjectSelectionUI',
      'renderTasks', 'renderTaskPagination', 'updateTaskSelectionUI', 'loadDetail',
      'renderProjectDetail', 'switchProjectDetailTab', 'renderPdRegionSelect']) {
      w[name] = (...args) => calls.push([name, ...args]);
    }
    vm.runInContext("state.currentRunId = 'run-1'; state.currentProject = {name:'demo'}; state.currentProjectRuns = []", context);
    for (const page of ['projects', 'tasks', 'detail', 'project-detail']) {
      vm.runInContext(`state.page = '${page}'`, context);
      w.dispatchEvent(new w.CustomEvent('iact3-lang-change', { detail: 'en' }));
      await new Promise(resolve => setImmediate(resolve));
      await new Promise(resolve => setImmediate(resolve));
    }
    for (const name of ['renderProjects', 'renderProjectPagination', 'updateProjectSelectionUI',
      'renderTasks', 'renderTaskPagination', 'updateTaskSelectionUI', 'loadDetail',
      'renderProjectDetail', 'switchProjectDetailTab', 'renderPdRegionSelect']) {
      assert.ok(calls.some(call => call[0] === name), name);
    }
    assert.equal(calls.find(call => call[0] === 'loadDetail')[1], 'run-1');
  } finally { close(); }
});

test('run output tabs and log controls switch, collapse and copy content', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => []}", context);
    w.bindPlayground();
    const result = w.document.getElementById('result-run');
    result.innerHTML = '<button class="run-inner-tab active" data-run-tab="first">First</button>' +
      '<button class="run-inner-tab" data-run-tab="second">Second</button>' +
      '<div class="run-inner-pane" data-run-pane="first">one</div>' +
      '<div class="run-inner-pane hidden" data-run-pane="second">two</div>' +
      '<div class="logs-section"><div class="output-section-head">Logs ' +
      '<button class="output-section-copy">Copy</button></div><div class="output-section-body">log text</div></div>';
    result.querySelector('[data-run-tab="second"]').click();
    assert.equal(vm.runInContext('state.runActiveTab', context), 'second');
    assert.equal(result.querySelector('[data-run-pane="first"]').classList.contains('hidden'), true);
    assert.equal(result.querySelector('[data-run-pane="second"]').classList.contains('hidden'), false);
    let copied;
    w.copyToClipboard = async text => { copied = text; };
    result.querySelector('.output-section-copy').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(copied, 'log text');
    result.querySelector('.output-section-head').click();
    assert.equal(result.querySelector('.logs-section').classList.contains('collapsed'), true);
  } finally { close(); }
});

test('output copy controls report clipboard failures and fallback messages', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => []}; state.currentAction = null", context);
    w.t = () => '';
    const notices = [], copied = [];
    w.toast = (message, type) => notices.push([message, type]);
    w.bindPlayground();
    w.copyToClipboard = async text => { copied.push(text); };
    w.document.getElementById('policy-body').textContent = 'policy';
    w.document.getElementById('result-body').textContent = 'result';
    await w.copyPolicyToClipboard();
    await w.copyResultToClipboard();
    w.document.getElementById('btn-copy-output').click();
    await new Promise(resolve => setImmediate(resolve));
    const log = w.document.getElementById('log-run');
    log.textContent = 'log text';
    w.document.querySelector('#logs-section-run .output-section-copy').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(copied[0], 'policy');
    assert.equal(copied[1], 'result');
    assert.equal(copied[3], 'log text');
    w.copyToClipboard = async () => { throw new Error('clipboard denied'); };
    await w.copyPolicyToClipboard();
    await w.copyResultToClipboard();
    w.document.getElementById('btn-copy-output').click();
    w.document.querySelector('#logs-section-run .output-section-copy').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(notices, Array(4).fill(['Copied', 'success']).concat(Array(4).fill(['Copy failed', 'error'])));
  } finally { close(); }
});

test('parameter generation displays fallback notices for empty input, warnings and errors', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.t = () => '';
    const notices = [];
    w.toast = (message, type) => notices.push([message, type]);
    const editor = w.document.getElementById('template-editor');
    editor.value = '';
    await w.autoGenerateParams();
    editor.value = 'Resources: {}';
    w.api = async () => ({ parameters: 'parameters: {A: 1}', warning: true });
    await w.autoGenerateParams();
    w.api = async () => ({ parameters: 'parameters: {A: 2}' });
    await w.autoGenerateParams();
    w.api = async () => { throw new Error(''); };
    await w.autoGenerateParams();
    assert.equal(w.document.getElementById('config-editor').value, 'parameters: {A: 2}');
    assert.deepEqual(notices, [
      ['Template is empty', 'error'],
      ['Parameters generated with warnings: some parameters could not be resolved. Please check the log for details.', 'warning'],
      ['Parameters generated successfully', 'success'], ['Failed to generate parameters', 'error'],
    ]);
    assert.equal(w.document.getElementById('btn-generate-params').disabled, false);
  } finally { close(); }
});

test('project editor opens Terraform menus and loads a local file', () => {
  const { window: w, context, close } = setup();
  try {
    w.FileReader = class { readAsText(file) { this.onload({ target: { result: file.content } }); } };
    w.bindProjects();
    const trigger = w.document.getElementById('project-edit-tf-open-trigger');
    const menu = w.document.getElementById('project-edit-tf-open-menu');
    trigger.click();
    assert.equal(menu.classList.contains('open'), true);
    const input = w.document.getElementById('project-edit-upload-template-file');
    Object.defineProperty(input, 'files', { value: [{ name: 'main.tf', content: 'variable "v" {}' }] });
    input.dispatchEvent(new w.Event('change'));
    assert.equal(vm.runInContext("state.projectEditTfFiles['main.tf']", context), 'variable "v" {}');
    assert.equal(vm.runInContext('state.projectEditTfActiveFile', context), 'main.tf');
    assert.equal(w.document.getElementById('project-edit-tf-template').value, 'variable "v" {}');
    w.document.getElementById('project-edit-tf-add-trigger').click();
    assert.equal(w.document.getElementById('project-edit-tf-add-menu').classList.contains('open'), true);
  } finally { close(); }
});

test('project editor ignores empty imports and only switches versions for saved projects', () => {
  const { window: w, context, close } = setup();
  try {
    const versions = [];
    w.onEditVersionChange = name => versions.push(name);
    w.bindProjects();
    const modal = w.document.getElementById('project-edit-modal');
    const version = w.document.getElementById('project-edit-version-select');
    modal.dataset.name = '';
    version.dispatchEvent(new w.Event('change'));
    modal.dataset.name = 'demo';
    version.dispatchEvent(new w.Event('change'));
    assert.deepEqual(versions, ['demo']);
    const input = w.document.getElementById('project-edit-upload-template-file');
    Object.defineProperty(input, 'files', { value: [], configurable: true });
    input.dispatchEvent(new w.Event('change'));
    w.document.getElementById('project-edit-tf-clear').click();
    w.document.getElementById('project-edit-tf-file-tree').click();
    assert.equal(vm.runInContext('Object.keys(state.projectEditTfFiles).length', context), 0);
    const open = w.document.getElementById('project-edit-tf-open-trigger');
    const openMenu = w.document.getElementById('project-edit-tf-open-menu');
    open.click();
    open.click();
    assert.equal(openMenu.classList.contains('open'), false);
    const add = w.document.getElementById('project-edit-tf-add-trigger');
    const addMenu = w.document.getElementById('project-edit-tf-add-menu');
    add.click();
    add.click();
    assert.equal(addMenu.classList.contains('open'), false);
  } finally { close(); }
});

test('loading state preserves a button label across repeated starts', () => {
  const { window: w, close } = setup();
  try {
    const button = w.document.createElement('button');
    button.textContent = 'Run <test>';
    w.setBtnLoading(null, true);
    w.setBtnLoading(button, true);
    w.setBtnLoading(button, true);
    assert.equal(button.disabled, true);
    assert.equal(button.querySelectorAll('.btn-spinner').length, 1);
    assert.equal(button.textContent, 'Run <test>');
    w.setBtnLoading(button, false);
    assert.equal(button.disabled, false);
    assert.equal(button.textContent, 'Run <test>');
  } finally { close(); }
});

test('project editor handles ROS projects, legacy configs and Terraform parameter generation', async () => {
  const { window: w, context, close } = setup();
  try {
    w.loadEditVersions = async () => {};
    let payload;
    w.fetch = async (url, options) => ({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => {
        if (options.method === 'GET') return JSON.stringify({ template: 'Resources: {}', configs: [{ config: 'parameters: {}' }] });
        payload = JSON.parse(options.body);
        return JSON.stringify({ parameters: 'parameters: {Generated: 1}', warning: 'partial' });
      } });
    await w.openEditProject('ros');
    assert.equal(w.document.getElementById('project-edit-template').value, 'Resources: {}');
    assert.equal(w.document.getElementById('project-edit-config').value, 'parameters: {}');
    vm.runInContext("state.projectEditTfMode = true; state.projectEditTfFiles = {'main.tf': 'old', 'dir/': ''}; state.projectEditTfActiveFile = 'main.tf'", context);
    w.document.getElementById('project-edit-tf-template').value = 'new contents';
    await w.generateParamsForProjectEdit();
    assert.deepEqual(payload.template_files, { 'main.tf': 'new contents' });
    assert.equal(w.document.getElementById('project-edit-config').value, 'parameters: {Generated: 1}');
    assert.ok(w.document.getElementById('toast').classList.contains('warning'));
  } finally { close(); }
});

test('stack cleanup distinguishes failed, successful and rejected requests', async () => {
  const { window: w, close } = setup();
  try {
    let requests = 0;
    let response = { deleted: 0, errors: 1, details: [{ error: 'denied' }] };
    w.showConfirm = async () => false;
    w.startTaskPolling = () => {};
    w.loadDetail = async () => {};
    w.fetch = async () => {
      requests++;
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(response) };
    };
    await w.deleteRunStacks('run');
    assert.equal(requests, 0);
    w.showConfirm = async () => true;
    await w.deleteRunStacks('run');
    assert.match(w.document.getElementById('toast').textContent, /denied/);
    assert.ok(w.document.getElementById('toast').classList.contains('error'));
    response = { deleted: 2, errors: 0 };
    await w.deleteRunStacks('run');
    assert.ok(w.document.getElementById('toast').classList.contains('success'));
    w.fetch = async () => { throw new Error('offline'); };
    await w.deleteRunStacks('run');
    assert.match(w.document.getElementById('toast').textContent, /offline/);
  } finally { close(); }
});

test('stack cleanup reports failures even without per-stack details', async () => {
  const { window: w, close } = setup();
  try {
    const notices = [];
    let refreshed = 0;
    w.toast = (message, type) => notices.push([message, type]);
    w.showConfirm = async () => true;
    w.startTaskPolling = () => {};
    w.loadDetail = async () => { refreshed++; };
    w.api = async () => ({ deleted: 1, errors: 2 });
    await w.deleteRunStacks('run');
    w.api = async () => ({ deleted: 0, errors: 1, details: [] });
    await w.deleteRunStacks('run');
    assert.equal(notices[0][1], 'warning');
    assert.equal(notices[1][1], 'error');
    assert.ok(notices.every(([message]) => message.length > 0));
    assert.equal(refreshed, 2);
  } finally { close(); }
});

test('built-in examples reset editors and request parameter generation', () => {
  const { window: w, context, close } = setup();
  try {
    let generated = 0;
    w.autoGenerateParams = () => { generated++; };
    w.document.getElementById('config-editor').value = 'stale config';
    w.loadRosExample();
    assert.equal(vm.runInContext('state.tfMode', context), false);
    assert.match(w.document.getElementById('template-editor').value, /Resources/);
    assert.equal(w.document.getElementById('config-editor').value, '');
    assert.ok(w.document.getElementById('pg-output').classList.contains('collapsed'));
    w.loadTfExample();
    assert.equal(vm.runInContext('state.tfMode', context), true);
    assert.ok(vm.runInContext('Object.keys(state.tfFiles).length > 0', context));
    assert.equal(generated, 2);
  } finally { close(); }
});

test('region selection clears stale generated parameters only on entering multi-region mode', () => {
  const { window: w, context, close } = setup();
  try {
    let selected = ['cn-a'];
    let generated = 0;
    w.selector = { getSelected: () => selected };
    vm.runInContext('state.pgRegionSelect = selector', context);
    w.autoGenerateParams = () => { generated++; };
    w.bindPlayground();
    const config = w.document.getElementById('config-editor');
    config.value = 'parameters: {Region: old}';
    selected = ['cn-a', 'cn-b'];
    w.selector.onChange();
    assert.equal(config.value, '');
    assert.equal(w.document.getElementById('config-region-hint').style.display, 'inline');
    config.value = 'new configuration';
    w.selector.onChange();
    assert.equal(config.value, 'new configuration');
    w.selector.onClose();
    w.selector.onClose();
    assert.equal(generated, 1);
    selected = ['cn-a'];
    w.selector.onChange();
    assert.equal(w.document.getElementById('config-region-hint').style.display, 'none');
  } finally { close(); }
});

test('version selector restores unsaved ROS edits and handles unavailable versions', async () => {
  const { window: w, close } = setup();
  try {
    let fail = false;
    w.fetch = async url => {
      if (fail) throw new Error('offline');
      const data = url.endsWith('/versions')
        ? { current_version: 2, versions: [{ version: 1 }, { version: 2 }] }
        : { template: 'historical template', configs: [{ config: 'historical config' }] };
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(data) };
    };
    w.setProjectEditTemplateTab('ros');
    w.document.getElementById('project-edit-template').value = 'unsaved template';
    w.document.getElementById('project-edit-config').value = 'unsaved config';
    await w.loadEditVersions('demo');
    const select = w.document.getElementById('project-edit-version-select');
    select.value = '1';
    await w.onEditVersionChange('demo');
    assert.equal(w.document.getElementById('project-edit-template').value, 'historical template');
    assert.equal(w.document.getElementById('project-edit-config').value, 'historical config');
    select.value = 'current';
    await w.onEditVersionChange('demo');
    assert.equal(w.document.getElementById('project-edit-template').value, 'unsaved template');
    assert.equal(w.document.getElementById('project-edit-config').value, 'unsaved config');
    fail = true;
    select.value = '1';
    await w.onEditVersionChange('demo');
    assert.ok(w.document.getElementById('toast').classList.contains('error'));
    select.value = 'current';
    await w.onEditVersionChange('demo');
    assert.equal(w.document.getElementById('project-edit-template').value, 'unsaved template');
    await w.loadEditVersions('demo');
    assert.equal(w.document.getElementById('project-edit-version-wrap').style.display, 'none');
  } finally { close(); }
});

test('version controls handle missing version lists and cancelled activation', async () => {
  const { window: w, close } = setup();
  try {
    const wrap = w.document.getElementById('project-edit-version-wrap');
    let calls = 0;
    w.api = async () => { calls++; return {}; };
    await w.loadEditVersions('demo');
    assert.equal(wrap.style.display, 'none');
    w.showConfirm = async () => false;
    await w.activateVersion('demo', 1);
    assert.equal(calls, 1);
    const notices = [];
    w.toast = (message, type) => notices.push([message, type]);
    w.showConfirm = async () => true;
    w.api = async () => { throw new Error(''); };
    await w.deleteVersion('demo', 1);
    assert.deepEqual(notices, [[w.t('versionDeleteFailed'), 'error']]);
  } finally { close(); }
});

test('run template viewer copies the selected Terraform file and converted ROS text', async () => {
  const { window: w, close } = setup();
  try {
    const copied = [];
    w.copyToClipboard = async value => { copied.push(value); };
    w.renderRunTemplate({ params: { raw_template_files: { 'main.tf': 'first', 'vars.tf': 'second' } } });
    w.document.querySelector('#run-tf-tabs-bar [data-path="vars.tf"]').click();
    w.document.querySelector('.run-tf-copy-btn').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(copied.pop(), 'second');
    w.renderRunTemplate({ params: { raw_template_content: 'Resources: {}' } });
    w.document.querySelector('[data-run-format="json"]').click();
    w.document.querySelector('.run-template-copy-btn').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(JSON.parse(copied.pop()), { Resources: {} });
    w.renderRunTemplate({ params: { raw_template_content: 'Resources: [' } });
    w.document.querySelector('[data-run-format="json"]').click();
    assert.ok(w.document.getElementById('toast').classList.contains('error'));
    assert.match(w.document.getElementById('run-template-content').textContent, /Resources/);
  } finally { close(); }
});

test('run template viewer converts JSON to YAML and keeps original on invalid conversion', () => {
  const { window: w, context, close } = setup();
  try {
    w.renderRunTemplate({ params: { raw_template_content: '{"Resources":{}}' } });
    w.document.querySelector('[data-run-format="json"]').click();
    assert.equal(vm.runInContext('state._runTemplateFormat', context), 'json');
    w.document.querySelector('[data-run-format="yaml"]').click();
    assert.equal(vm.runInContext('state._runTemplateFormat', context), 'yaml');
    assert.match(w.document.getElementById('run-template-content').textContent, /Resources/);
    w.renderRunTemplate({ params: { raw_template_content: '{invalid' } });
    w.document.querySelector('[data-run-format="yaml"]').click();
    assert.equal(vm.runInContext('state._runTemplateFormat', context), 'json');
    assert.equal(w.document.getElementById('run-template-content').textContent, '{invalid');
    assert.ok(w.document.getElementById('toast').classList.contains('error'));
  } finally { close(); }
});

test('version history marks latest when current is missing and wires row actions', async () => {
  const { window: w, close } = setup();
  try {
    const calls = [];
    w.viewVersionContent = (name, ver) => calls.push(['view', name, ver]);
    w.viewVersionDiff = (name, ver) => calls.push(['diff', name, ver]);
    w.activateVersion = (name, ver) => calls.push(['activate', name, ver]);
    w.deleteVersion = (name, ver) => calls.push(['delete', name, ver]);
    let versions = [{ version: 1, created_at: '1' }, { version: 2 }];
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ versions, current_version: 99 }) });
    await w.renderVersionHistory('demo');
    const container = w.document.getElementById('project-detail-versions');
    assert.match(container.querySelector('.is-current').textContent, /v2/);
    container.querySelector('.btn-version-view[data-ver="1"]').click();
    container.querySelector('.btn-version-diff[data-ver="1"]').click();
    container.querySelector('.btn-version-activate[data-ver="1"]').click();
    container.querySelector('.btn-version-delete[data-ver="1"]').click();
    assert.deepEqual(calls, [['view', 'demo', 1], ['diff', 'demo', 1], ['activate', 'demo', 1], ['delete', 'demo', 1]]);
    versions = [{ version: 1 }];
    await w.renderVersionHistory('demo');
    assert.equal(container.querySelector('.btn-version-delete').disabled, true);
    versions = [];
    await w.renderVersionHistory('demo');
    assert.ok(container.querySelector('.empty-state'));
  } finally { close(); }
});

test('version history treats service error messages as text', async () => {
  const { window: w, close } = setup();
  try {
    w.fetch = async () => { throw new Error('<img src=x onerror=alert(1)>'); };
    await w.renderVersionHistory('demo');
    const container = w.document.getElementById('project-detail-versions');
    assert.equal(container.querySelector('img'), null);
    assert.match(container.textContent, /<img src=x onerror=alert\(1\)>/);
  } finally { close(); }
});

test('project detail tolerates missing version data and empty template content', async () => {
  const { window: w, close } = setup();
  try {
    w.api = async () => ({});
    await w.renderVersionHistory('demo');
    assert.ok(w.document.getElementById('project-detail-versions').querySelector('.empty-state'));
    w.renderPdTemplateContent('missing element');
    const pre = w.document.createElement('pre');
    pre.id = 'pd-template-content';
    w.document.body.appendChild(pre);
    w.renderPdTemplateContent('');
    assert.equal(pre.textContent, '');
    w.renderPdTemplateContent('{"Resources": {}}');
    assert.ok(pre.classList.contains('language-json'));
  } finally { close(); }
});

test('version actions report failures and do not refresh the project', async () => {
  const { window: w, close } = setup();
  try {
    const notices = [];
    let refreshed = 0;
    w.toast = (message, type) => notices.push([message, type]);
    w.showConfirm = async () => true;
    w.loadProjectDetail = () => { refreshed++; };
    w.fetch = async () => { throw new Error('service unavailable'); };
    await w.viewVersionContent('demo', 1);
    await w.viewVersionDiff('demo', 1);
    await w.activateVersion('demo', 1);
    await w.deleteVersion('demo', 1);
    assert.equal(notices.length, 4);
    assert.ok(notices.every(([, type]) => type === 'error'));
    assert.equal(notices[3][0], 'service unavailable');
    assert.equal(refreshed, 0);
  } finally { close(); }
});

test('Terraform version viewer and comparison display selected files and changes', async () => {
  const { window: w, close } = setup();
  try {
    w.fetch = async url => {
      const data = url.endsWith('/versions/1')
        ? { template_files: { 'main.tf': 'old main', 'sub/vars.tf': 'old vars', 'sub/': '' }, config: '' }
        : { template_files: { 'main.tf': 'new main' }, config: '' };
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(data) };
    };
    await w.viewVersionContent('demo', 1);
    w.document.querySelector('#ver-tf-tabs-bar [data-path="sub/vars.tf"]').click();
    assert.equal(w.document.getElementById('ver-tf-content').textContent, 'old vars');
    await w.viewVersionDiff('demo', 1);
    const body = w.document.getElementById('version-modal-body');
    assert.match(body.textContent, /old main/);
    assert.match(body.textContent, /new main/);
    assert.match(body.textContent, /vars.tf/);
    w.fetch = async () => { throw new Error('offline'); };
    await w.viewVersionDiff('demo', 1);
    assert.ok(w.document.getElementById('toast').classList.contains('error'));
    await w.viewVersionContent('demo', 1);
    assert.ok(w.document.getElementById('toast').classList.contains('error'));
  } finally { close(); }
});

test('version viewer switches to an empty Terraform file', async () => {
  const { window: w, close } = setup();
  try {
    w.api = async () => ({ template_files: { 'main.tf': 'resource {}', 'empty.tf': '' } });
    await w.viewVersionContent('demo', 1);
    w.document.querySelector('#ver-tf-tabs-bar [data-path="empty.tf"]').click();
    assert.equal(w.document.getElementById('ver-tf-content').textContent, '');
    assert.ok(w.document.querySelector('#ver-tf-tabs-bar [data-path="empty.tf"]').classList.contains('active'));
  } finally { close(); }
});

test('version comparison handles changes between ROS and Terraform templates', async () => {
  const { window: w, close } = setup();
  try {
    let old = { template: 'Resources: {Old: {}}' };
    let current = { template_files: { 'main.tf': 'resource "new" {}' } };
    w.api = async (method, url) => url.endsWith('/versions/1') ? old : current;
    await w.viewVersionDiff('demo', 1);
    let body = w.document.getElementById('version-modal-body');
    assert.match(body.textContent, /Old/);
    assert.match(body.textContent, /resource "new"/);
    old = { template_files: { 'main.tf': 'resource "old" {}' } };
    current = { template: 'Resources: {New: {}}' };
    await w.viewVersionDiff('demo', 1);
    body = w.document.getElementById('version-modal-body');
    assert.match(body.textContent, /resource "old"/);
    assert.match(body.textContent, /New/);
  } finally { close(); }
});

test('task list corrects out-of-range pages and preserves query filters', async () => {
  const { window: w, context, close } = setup();
  try {
    const urls = [];
    vm.runInContext("state.page = 'tasks'; state.taskPage = 4; state.taskPerPage = 10; state.taskSearch = 'test'; state.taskStatusFilter = 'failed'", context);
    w.fetch = async url => {
      urls.push(url);
      return { ok: true, status: 200, headers: { get: () => 'application/json' },
        text: async () => JSON.stringify({ total: 11, runs: [{ id: 'a', name: 'A', status: 'failed' }] }) };
    };
    await w.loadTasks();
    assert.equal(urls.length, 2);
    assert.match(urls[0], /page=4/);
    assert.match(urls[1], /page=2/);
    assert.match(urls[1], /search=test/);
    assert.match(urls[1], /status=failed/);
    assert.equal(vm.runInContext('state.taskPage', context), 2);
    assert.match(w.document.getElementById('tasks-list').textContent, /A/);
  } finally { close(); }
});

test('task row navigation and bulk selection respect controls', () => {
  const { window: w, context, close } = setup();
  try {
    const navigations = [];
    w.navigate = (page, params) => navigations.push([page, params.runId]);
    w.cancelTask = () => {};
    w.deleteTask = () => {};
    vm.runInContext("state.tasks = [{id:'a',name:'A',status:'running'},{id:'b',name:'B',status:'failed'}]; state.taskTotal = 2", context);
    w.bindTasks();
    w.renderTasks();
    const list = w.document.getElementById('tasks-list');
    list.querySelector('tr').click();
    list.querySelector('.btn-cancel-task').click();
    assert.deepEqual(navigations, [['detail', 'a']]);
    const header = w.document.getElementById('task-select-all-header');
    header.checked = true;
    header.dispatchEvent(new w.Event('change'));
    assert.equal(vm.runInContext('state.selectedTasks.size', context), 2);
    header.checked = false;
    header.dispatchEvent(new w.Event('change'));
    assert.equal(vm.runInContext('state.selectedTasks.size', context), 0);
  } finally { close(); }
});

test('task deletion retains selection on request failure and navigates away on success', async () => {
  const { window: w, context, close } = setup();
  try {
    let fail = true;
    let navigated = '';
    vm.runInContext("state.page = 'detail'; state.currentRunId = 'a'; state.selectedTasks = new Set(['a'])", context);
    w.showConfirm = async () => true;
    w.navigate = page => { navigated = page; };
    w.loadTasks = async () => {};
    w.fetch = async () => {
      if (fail) throw new Error('offline');
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => '{}' };
    };
    await w.deleteTask('a', 'A');
    assert.equal(vm.runInContext('state.selectedTasks.has("a")', context), true);
    assert.match(w.document.getElementById('toast').textContent, /offline/);
    fail = false;
    await w.deleteTask('a', 'A');
    assert.equal(navigated, 'tasks');
    assert.equal(vm.runInContext('state.selectedTasks.size', context), 0);
  } finally { close(); }
});

test('task deletion cancellation keeps the task and deleting another task leaves the detail page open', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.page = 'detail'; state.currentRunId = 'current'; state.selectedTasks = new Set(['other'])", context);
    let approved = false, navigations = 0, reloads = 0;
    const requests = [];
    w.showConfirm = async () => approved;
    w.navigate = () => { navigations++; };
    w.loadTasks = () => { reloads++; };
    w.api = async (method, path) => requests.push([method, path]);
    await w.deleteTask('other', 'Other');
    assert.deepEqual(requests, []);
    assert.equal(vm.runInContext("state.selectedTasks.has('other')", context), true);
    approved = true;
    await w.deleteTask('other', 'Other');
    assert.deepEqual(requests, [['DELETE', '/api/runs/other']]);
    assert.equal(navigations, 0);
    assert.equal(reloads, 1);
    assert.equal(vm.runInContext('state.selectedTasks.size', context), 0);
  } finally { close(); }
});

test('batch task deletion requires selection and confirmation, then clears selection', async () => {
  const { window: w, context, close } = setup();
  try {
    let confirmations = 0, reloads = 0;
    const requests = [], notices = [];
    w.showConfirm = async () => { confirmations++; return false; };
    w.loadTasks = () => { reloads++; };
    w.toast = (message, type) => notices.push([message, type]);
    w.api = async (method, path, body) => { requests.push([method, path, body]); return {}; };
    await w.batchDeleteTasks();
    assert.equal(confirmations, 0);
    vm.runInContext("state.selectedTasks = new Set(['one', 'two'])", context);
    await w.batchDeleteTasks();
    assert.equal(confirmations, 1);
    assert.equal(requests.length, 0);
    assert.equal(vm.runInContext('state.selectedTasks.size', context), 2);
    w.showConfirm = async () => true;
    await w.batchDeleteTasks();
    assert.deepEqual(Array.from(requests[0][2].ids), ['one', 'two']);
    assert.equal(vm.runInContext('state.selectedTasks.size', context), 0);
    assert.equal(reloads, 1);
    assert.equal(notices[0][1], 'success');
  } finally { close(); }
});

test('batch project deletion retains selection when cancelled or the request fails', async () => {
  const { window: w, context, close } = setup();
  try {
    let confirmations = 0, requests = 0;
    w.showConfirm = async () => { confirmations++; return false; };
    w.api = async () => { requests++; throw new Error('offline'); };
    await w.batchDeleteProjects();
    assert.equal(confirmations, 0);
    vm.runInContext("state.selectedProjects = new Set(['demo'])", context);
    await w.batchDeleteProjects();
    assert.equal(requests, 0);
    w.showConfirm = async () => true;
    await w.batchDeleteProjects();
    assert.equal(requests, 1);
    assert.equal(vm.runInContext('state.selectedProjects.has("demo")', context), true);
    assert.match(w.document.getElementById('toast').textContent, /offline/);
    w.loadProjects = () => {};
    w.api = async () => ({});
    await w.batchDeleteProjects();
    assert.equal(vm.runInContext('state.selectedProjects.size', context), 0);
  } finally { close(); }
});

test('project Terraform tree routes file actions, selection and clear confirmation', async () => {
  const { window: w, context, close } = setup();
  try {
    const actions = [];
    w.renameProjectEditTfFile = path => actions.push(['rename', path]);
    w.deleteProjectEditTfFile = path => actions.push(['delete', path]);
    w.addProjectEditTfFile = () => actions.push(['add-file']);
    w.addProjectEditTfFolder = () => actions.push(['add-folder']);
    w.showConfirm = async () => false;
    vm.runInContext("state.projectEditTfFiles = {'main.tf':'main', 'folder/':'', 'folder/other.tf':'other'}; state.projectEditTfActiveFile = null", context);
    w.bindProjects();
    w.renderProjectEditTfFileList();
    const tree = w.document.getElementById('project-edit-tf-file-tree');
    tree.querySelector('[data-pe-path="main.tf"] [data-pe-action="rename"]').click();
    tree.querySelector('[data-pe-path="main.tf"] [data-pe-action="delete"]').click();
    tree.querySelector('[data-pe-path="folder/"]').click();
    assert.equal(vm.runInContext('state.projectEditTfActiveFile', context), null);
    tree.querySelector('[data-pe-path="main.tf"]').click();
    assert.equal(w.document.getElementById('project-edit-tf-template').value, 'main');
    w.document.querySelector('[data-pe-tf-action="file"]').click();
    w.document.querySelector('[data-pe-tf-action="folder"]').click();
    assert.deepEqual(actions, [['rename', 'main.tf'], ['delete', 'main.tf'], ['add-file'], ['add-folder']]);
    w.document.getElementById('project-edit-tf-clear').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(vm.runInContext('Object.keys(state.projectEditTfFiles).length', context), 3);
    w.t = () => '';
    let confirmMessage;
    w.showConfirm = async message => { confirmMessage = message; return true; };
    w.document.getElementById('project-edit-tf-clear').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(confirmMessage, 'Clear all Terraform files?');
    assert.equal(vm.runInContext('Object.keys(state.projectEditTfFiles).length', context), 0);
    assert.equal(w.document.getElementById('project-edit-tf-template').value, '');
  } finally { close(); }
});

test('project editor folder import and modal controls update UI state', () => {
  const { window: w, context, close } = setup();
  try {
    const files = [{ name: 'main.tf', webkitRelativePath: 'project/main.tf', content: 'resource {}' }];
    w.FileReader = class { readAsText(file) { this.onload({ target: { result: file.content } }); } };
    w.bindProjects();
    const input = w.document.getElementById('project-edit-upload-template-dir');
    Object.defineProperty(input, 'files', { value: files });
    input.dispatchEvent(new w.Event('change'));
    assert.equal(vm.runInContext("state.projectEditTfFiles['main.tf']", context), 'resource {}');
    const editor = w.document.getElementById('project-edit-tf-template');
    editor.value = 'updated';
    editor.dispatchEvent(new w.Event('input'));
    assert.equal(vm.runInContext("state.projectEditTfFiles['main.tf']", context), 'updated');
    w.document.getElementById('project-edit-tf-open-trigger').click();
    assert.ok(w.document.getElementById('project-edit-tf-open-menu').classList.contains('open'));
    w.document.querySelector('#project-edit-tf-open-dropdown label.tf-open-item').click();
    assert.equal(w.document.getElementById('project-edit-tf-open-menu').classList.contains('open'), false);
    const modal = w.document.getElementById('project-edit-modal');
    modal.classList.add('open');
    w.document.getElementById('project-edit-close').click();
    assert.equal(modal.classList.contains('open'), false);
    modal.classList.add('open');
    modal.click();
    assert.equal(modal.classList.contains('open'), false);
  } finally { close(); }
});

test('project editor imports Terraform files only after all reads finish', () => {
  const { window: w, context, close } = setup();
  try {
    const pending = [], notices = [];
    w.toast = (message, type) => notices.push(type);
    w.FileReader = class { readAsText(file) { pending.push(() => this.onload({ target: { result: file.content } })); } };
    w.loadProjectEditLocalTfFiles([{ name: 'README.md', content: 'ignored' }]);
    assert.deepEqual(notices, ['error']);
    w.loadProjectEditLocalTfFiles([
      { name: 'b.tf', content: 'second', webkitRelativePath: 'root/sub/b.tf' },
      { name: 'a.tf', content: 'first' }, { name: 'ignore.txt', content: 'ignored' },
    ]);
    assert.equal(pending.length, 2);
    pending[1]();
    assert.equal(vm.runInContext('state.projectEditTfActiveFile', context), null);
    pending[0]();
    assert.equal(vm.runInContext('state.projectEditTfActiveFile', context), 'a.tf');
    assert.equal(vm.runInContext("state.projectEditTfFiles['sub/b.tf']", context), 'second');
    assert.equal(w.document.getElementById('project-edit-tf-template').value, 'first');
  } finally { close(); }
});

test('project editor dropdown and modal close controls reset their UI', () => {
  const { window: w, close } = setup();
  try {
    w.bindProjects();
    const openMenu = w.document.getElementById('project-edit-tf-open-menu');
    const addMenu = w.document.getElementById('project-edit-tf-add-menu');
    w.document.getElementById('project-edit-tf-open-trigger').click();
    w.document.getElementById('project-edit-tf-add-trigger').click();
    assert.ok(openMenu.classList.contains('open'));
    assert.ok(addMenu.classList.contains('open'));
    w.dispatchEvent(new w.Event('resize'));
    assert.equal(openMenu.classList.contains('open'), false);
    assert.equal(addMenu.classList.contains('open'), false);
    w.document.getElementById('project-edit-tf-open-trigger').click();
    let uploadClicks = 0;
    w.document.getElementById('project-edit-upload-template-dir').click = () => { uploadClicks++; };
    w.document.getElementById('project-edit-open-folder-item').click();
    assert.equal(uploadClicks, 1);
    assert.equal(openMenu.classList.contains('open'), false);
    w.document.getElementById('project-edit-tf-open-trigger').click();
    w.document.querySelector('#project-edit-tf-open-dropdown label').click();
    assert.equal(openMenu.classList.contains('open'), false);
    const modal = w.document.getElementById('project-edit-modal');
    modal.classList.add('open');
    w.document.getElementById('project-edit-close').click();
    assert.equal(modal.classList.contains('open'), false);
    modal.classList.add('open');
    modal.click();
    assert.equal(modal.classList.contains('open'), false);
  } finally { close(); }
});

test('output tabs start missing actions and reuse existing results', async () => {
  const { window: w, context, close } = setup();
  try {
    const calls = [];
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.prevalidate = async label => { calls.push(['validate', label]); return true; };
    w.generatePolicy = () => calls.push(['policy']);
    w.estimateCost = () => calls.push(['cost']);
    w.bindPlayground();
    const policy = w.document.querySelector('.output-tab[data-action="policy"]');
    const cost = w.document.querySelector('.output-tab[data-action="cost"]');
    policy.click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls.filter(item => item[0] === 'policy').length, 1);
    cost.click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls.filter(item => item[0] === 'cost').length, 1);
    assert.equal(calls.filter(item => item[0] === 'validate').length, 2);
    w.showActionResult('policy', 'Policy', { action: 'read' }, 'json');
    const before = calls.length;
    policy.click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls.length, before);
    assert.equal(vm.runInContext('state.currentAction', context), 'policy');
    assert.equal(w.document.getElementById('pg-output').classList.contains('collapsed'), false);
  } finally { close(); }
});

test('output tabs do not trigger actions when validation fails and reuse existing logs', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    let actions = 0, validations = 0;
    w.prevalidate = async () => { validations++; return false; };
    w.generatePolicy = () => { actions++; };
    w.estimateCost = () => { actions++; };
    w.bindPlayground();
    const policy = w.document.querySelector('.output-tab[data-action="policy"]');
    const cost = w.document.querySelector('.output-tab[data-action="cost"]');
    policy.click();
    cost.click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(validations, 2);
    assert.equal(actions, 0);
    w.consoleLog('existing policy log', { action: 'policy' });
    policy.click();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(validations, 2);
    assert.equal(vm.runInContext('state.currentAction', context), 'policy');
  } finally { close(); }
});

test('run output tab launches a run and sample changes ignore empty selections', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    const samples = [], calls = [];
    w.loadSample = id => samples.push(id);
    w.prevalidate = async () => true;
    w.pollRunInModal = id => calls.push(['poll', id]);
    w.api = async (method, path) => { calls.push([method, path]); return { id: 'run', status: 'running' }; };
    w.bindPlayground();
    const select = w.document.getElementById('sample-select');
    select.innerHTML = '<option value="">Choose</option><option value="sample">Sample</option>';
    select.value = '';
    select.dispatchEvent(new w.Event('change'));
    select.value = 'sample';
    select.dispatchEvent(new w.Event('change'));
    assert.deepEqual(samples, ['sample']);
    w.document.querySelector('.output-tab[data-action="run"]').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(calls, [['POST', '/api/runs'], ['poll', 'run']]);
  } finally { close(); }
});

test('action buttons use fallback names and do not send requests when validation fails', async () => {
  const { window: w, context, close } = setup();
  try {
    const labels = [], actions = [];
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.t = () => '';
    w.prevalidate = async label => { labels.push(label); return false; };
    w.generatePolicy = () => actions.push('policy');
    w.estimateCost = () => actions.push('cost');
    w.bindPlayground();
    w.bindCost();
    w.document.getElementById('btn-run').click();
    w.document.getElementById('btn-policy').click();
    w.document.getElementById('btn-cost').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(labels, ['Run Test', 'Generate Policy', 'Estimate Cost']);
    assert.deepEqual(actions, []);
    assert.equal(w.document.getElementById('btn-run').disabled, false);
  } finally { close(); }
});

test('prevalidation rejects empty template, service failures and invalid results without logs', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.settings = {source: 'env'}; state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    const logs = [];
    w.consoleLog = message => logs.push(message);
    w.document.getElementById('template-editor').value = '';
    assert.equal(await w.prevalidate('run'), false);
    w.document.getElementById('template-editor').value = 'Resources: {}';
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ result: 'invalid', errors: ['denied'] }) });
    assert.equal(await w.prevalidate('run'), false);
    assert.match(logs[0], /denied/);
    w.fetch = async () => { throw new Error('offline'); };
    assert.equal(await w.prevalidate('run'), false);
    assert.match(logs[1], /offline/);
  } finally { close(); }
});

test('prevalidation explains missing regions and service errors without localized strings', async () => {
  const { window: w, context, close } = setup();
  try {
    const notices = [];
    vm.runInContext("state.settings = {source: 'env'}; state.pgRegionSelect = {getSelected: () => []}", context);
    w.t = () => '';
    w.toast = (message, type) => notices.push([message, type]);
    w.consoleLog = () => {};
    assert.equal(await w.prevalidate('Run'), false);
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.document.getElementById('template-editor').value = '';
    assert.equal(await w.prevalidate('Run'), false);
    w.document.getElementById('template-editor').value = 'Resources: {}';
    w.api = async () => ({ result: 'invalid' });
    assert.equal(await w.prevalidate('Run'), false);
    w.api = async () => { throw new Error('offline'); };
    assert.equal(await w.prevalidate('Run'), false);
    assert.deepEqual(notices, [
      ['Please select at least one region.', 'error'], ['Template is empty', 'error'],
      ['Validating before Run...', 'info'], ['Validation failed before Run', 'error'],
      ['Validating before Run...', 'info'], ['Validation failed before Run', 'error'],
    ]);
  } finally { close(); }
});

test('cost and policy actions show fallback labels and render API results', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.document.getElementById('template-editor').value = 'Resources: {}';
    w.t = () => '';
    const loading = [], results = [], logs = [];
    w.showActionLoading = (action, title) => loading.push([action, title]);
    w.showActionResult = (action, title, content, type) => results.push([action, title, type]);
    w.consoleLog = text => logs.push(text);
    w.logCostSummary = () => {};
    w.api = async (method, path) => path === '/api/cost'
      ? { prices: [], logs: 'cost log' } : { policy: { Statement: [] }, logs: 'policy log' };
    await w.estimateCost();
    await w.generatePolicy();
    assert.deepEqual(loading, [['cost', 'Cost estimating...'], ['policy', 'Generating policy...']]);
    assert.deepEqual(results, [['cost', 'Cost Estimate Result', 'html'], ['policy', 'Policy Result', 'json']]);
    assert.deepEqual(logs, ['cost log', 'policy log']);
    assert.equal(w.document.getElementById('btn-cost').disabled, false);
    assert.equal(w.document.getElementById('btn-policy').disabled, false);
  } finally { close(); }
});

test('Terraform deletion cancellation and active folder removal preserve unrelated tabs', async () => {
  const { window: w, context, close } = setup();
  try {
    w.enterTfMode({ 'main.tf': 'main', 'group/a.tf': 'a', 'group/b.tf': 'b' });
    w.openTfFile('group/a.tf');
    w.openTfFile('group/b.tf');
    w.showConfirm = async () => false;
    await w.deleteTfFile('group/b.tf');
    await w.deleteTfFolder('group');
    assert.equal(vm.runInContext('state.tfActiveFile', context), 'group/b.tf');
    assert.equal(vm.runInContext('Object.keys(state.tfFiles).length', context), 3);
    w.showConfirm = async () => true;
    await w.deleteTfFolder('group');
    assert.equal(vm.runInContext('state.tfActiveFile', context), 'main.tf');
    assert.equal(w.document.getElementById('template-editor').value, 'main');
    assert.deepEqual(Array.from(vm.runInContext('state.tfOpenFiles', context)), ['main.tf']);
    await w.deleteTfFile('missing.tf');
    await w.deleteTfFolder('missing');
    assert.deepEqual(Array.from(vm.runInContext('Object.keys(state.tfFiles)', context)), ['main.tf']);
  } finally { close(); }
});

test('Terraform create and rename reject duplicates or cancellation without overwriting content', async () => {
  const { window: w, context, close } = setup();
  try {
    w.enterTfMode({ 'main.tf': 'original', 'group/': '' });
    w.showInlinePrompt = async () => 'main.tf';
    await w.createTfFile();
    assert.equal(vm.runInContext("state.tfFiles['main.tf']", context), 'original');
    assert.ok(w.document.getElementById('toast').classList.contains('error'));
    w.showInlinePrompt = async () => 'group';
    await w.createTfFolder();
    assert.ok(w.document.getElementById('toast').classList.contains('error'));
    w.showInlinePrompt = async () => null;
    await w.createTfFile();
    await w.createTfFolder();
    w.showPrompt = async () => null;
    await w.renameTfNode('main.tf', false);
    assert.deepEqual(Array.from(vm.runInContext('Object.keys(state.tfFiles)', context)), ['main.tf', 'group/']);
  } finally { close(); }
});

test('cost breakdown renders associated resources, service errors and mixed billing periods', () => {
  const { window: w, close } = setup();
  try {
    const prices = [{ test_name: 'example', region: 'cn-a', price: {
      Instance: { Type: 'ALIYUN::ECS::Instance', Result: {
        Order: { Currency: 'USD', OriginalAmount: 10, DiscountAmount: 2, TradeAmount: 8 },
        OrderSupplement: { ChargeType: 'PostPaid', PriceUnit: 'Hour', Quantity: 1 },
        AssociationProducts: { Disk: { Type: 'ALIYUN::ECS::Disk', Result: {
          Order: { Currency: 'USD', TradeAmount: 3 }, OrderSupplement: { PeriodUnit: 'Month', Quantity: 2 },
        } } },
      } },
      Error: { Success: false, Result: { Code: 'Unavailable', Message: 'not offered' } },
    } }];
    const result = w.extractCostRows(prices[0]);
    assert.equal(result.rows.length, 2);
    assert.equal(result.rows[0].resource, 'Instance');
    assert.equal(result.rows[1].resource, '');
    assert.equal(result.rows[1].type, 'ECS::Instance-Disk');
    assert.equal(result.errors[0].code, 'Unavailable');
    const html = w.renderCostResultsHtml(prices);
    assert.match(html, /Unavailable/);
    assert.match(html, /not offered/);
    assert.match(html, /ECS::Instance-Disk/);
    assert.match(html, /\$8/);
    assert.equal(w.formatDuration('PostPaid', 1, 'Month'), '-');
    assert.notEqual(w.formatDuration('PrePaid', 1, 'Month'), '-');
    assert.equal(w.formatPeriodUnit('Unknown'), '/Unknown');
    assert.equal(w.formatCurrencySymbol('XYZ'), 'XYZ ');
    assert.match(w.formatCostDiscount(2, 'USD'), /\$2/);
  } finally { close(); }
});

test('stack statistics recognize failed, rollback and uncertain results', () => {
  const { window: w, close } = setup();
  try {
    for (const status of ['CREATE_FAILED', 'ROLLBACK_COMPLETE', 'CREATE_UNCONFIRMED', 'DELETE_TIMEOUT']) {
      assert.equal(w.isStackFailed({ status }), true);
    }
    assert.equal(w.isStackFailed({}), false);
    assert.equal(w.calcStackStats([]).ratio, 0);
    assert.equal(w.calcStackStats([{ status: 'CREATE_COMPLETE', launch_succeeded: true }]).ratio, 100);
    const mixed = w.calcStackStats([{ status: 'CREATE_COMPLETE', launch_succeeded: true },
      { status: 'CREATE_FAILED', launch_succeeded: false }]);
    assert.equal(mixed.ratio, 50);
    assert.equal(mixed.ratioColor, '');
    assert.equal(w.isRunSettled({ status: 'completed', stacks: [{ status: 'DELETE_REQUESTING' }] }), false);
    assert.equal(w.isRunSettled({ status: 'completed', stacks: [{ status: 'DELETE_COMPLETE' }] }), true);
  } finally { close(); }
});

test('project list routes row actions and selects visible projects', () => {
  const { window: w, context, close } = setup();
  try {
    const calls = [];
    w.navigate = (page, params) => calls.push([page, params.projectName]);
    w.loadProjectIntoPlayground = name => calls.push(['load', name]);
    w.openEditProject = name => calls.push(['edit', name]);
    w.deleteProject = name => calls.push(['delete', name]);
    vm.runInContext("state.projects = [{name:'first', is_terraform:true, resource_count:3, test_count:1}, {name:'second'}]", context);
    w.bindProjects();
    w.renderProjects();
    const list = w.document.getElementById('projects-list');
    list.querySelector('.project-name-link').click();
    list.querySelector('.btn-view-project').click();
    list.querySelector('.btn-load-project').click();
    list.querySelector('.btn-edit-project').click();
    list.querySelector('.btn-delete-project').click();
    assert.deepEqual(calls, [['project-detail', 'first'], ['project-detail', 'first'],
      ['load', 'first'], ['edit', 'first'], ['delete', 'first']]);
    const selectAll = w.document.getElementById('project-select-all-header');
    selectAll.checked = true;
    selectAll.dispatchEvent(new w.Event('change'));
    assert.equal(vm.runInContext('state.selectedProjects.size', context), 2);
    assert.equal(w.document.getElementById('btn-batch-delete-project').disabled, false);
    selectAll.checked = false;
    selectAll.dispatchEvent(new w.Event('change'));
    assert.equal(vm.runInContext('state.selectedProjects.size', context), 0);
    assert.equal(w.document.getElementById('btn-batch-delete-project').disabled, true);
  } finally { close(); }
});

test('project row navigation ignores checkbox clicks and opens on row click', () => {
  const { window: w, context, close } = setup();
  try {
    const calls = [];
    w.navigate = (page, params) => calls.push([page, params.projectName]);
    vm.runInContext("state.projects = [{name:'demo', updated_at:'1', resource_count:0, test_count:0}]", context);
    w.renderProjects();
    const row = w.document.querySelector('#projects-list tr');
    row.querySelector('input').click();
    assert.deepEqual(calls, []);
    assert.equal(vm.runInContext("state.selectedProjects.has('demo')", context), true);
    row.querySelector('td:nth-child(4)').click();
    assert.deepEqual(calls, [['project-detail', 'demo']]);
    vm.runInContext('state.projects = []', context);
    w.renderProjects();
    assert.ok(w.document.querySelector('#projects-list .empty-state'));
  } finally { close(); }
});

test('pagination shows ellipses and responds to page-size changes', () => {
  const { window: w, close } = setup();
  try {
    const container = w.document.createElement('div');
    container.innerHTML = w.buildPaginationHTML(5, 10, 100, 10, [10, 20], 'test');
    w.document.body.appendChild(container);
    assert.equal(container.querySelectorAll('.pagination-ellipsis').length, 2);
    const pages = [];
    const sizes = [];
    w.bindPaginationEvents(container, 10, value => pages.push(value), value => sizes.push(value));
    container.querySelector('[data-page="6"]').click();
    container.querySelector('.pagination-per-page-trigger').click();
    assert.ok(container.querySelector('.pagination-per-page-wrapper').classList.contains('open'));
    container.querySelector('.pagination-per-page-option[data-value="20"]').click();
    assert.deepEqual(pages, [6]);
    assert.deepEqual(sizes, [20]);
    assert.equal(container.querySelector('.pagination-per-page-wrapper').classList.contains('open'), false);
  } finally { close(); }
});

test('pagination near the beginning keeps adjacent pages and rejects invalid navigation', () => {
  const { window: w, close } = setup();
  try {
    const container = w.document.createElement('div');
    container.innerHTML = w.buildPaginationHTML(2, 10, 100, 10, [10, 20], 'test');
    w.document.body.appendChild(container);
    assert.equal(container.querySelectorAll('.pagination-ellipsis').length, 1);
    assert.deepEqual(Array.from(container.querySelectorAll('.pagination-page-btn')).map(b => b.textContent), ['1', '2', '3', '10']);
    const pages = [];
    const invalid = w.document.createElement('button');
    invalid.dataset.page = '11';
    container.appendChild(invalid);
    w.bindPaginationEvents(container, 10, page => pages.push(page), () => {});
    invalid.click();
    container.querySelector('[data-page="3"]').click();
    assert.deepEqual(pages, [3]);
  } finally { close(); }
});

test('loading a legacy ROS project exits Terraform mode and restores saved regions', async () => {
  const { window: w, context, close } = setup();
  try {
    let selected;
    let page;
    w.selector = { getSelected: () => selected || [], setSelected: regions => { selected = Array.from(regions); } };
    vm.runInContext('state.pgRegionSelect = selector', context);
    w.navigate = destination => { page = destination; };
    w.enterTfMode({ 'main.tf': 'resource {}' });
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ template: 'Resources: {}', configs: [{ config: 'tests: {default: {regions: [cn-a]}}' }] }) });
    await w.loadProjectIntoPlayground('demo');
    assert.equal(vm.runInContext('state.tfMode', context), false);
    assert.equal(w.document.getElementById('template-editor').value, 'Resources: {}');
    assert.deepEqual(selected, ['cn-a']);
    assert.equal(page, 'playground');
    w.fetch = async () => { throw new Error('offline'); };
    await w.loadProjectIntoPlayground('demo');
    assert.match(w.document.getElementById('toast').textContent, /offline/);
  } finally { close(); }
});

test('playground Terraform upload controls import local files and folder contents', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => []}", context);
    w.FileReader = class { readAsText(file) { this.onload({ target: { result: file.content } }); } };
    w.bindPlayground();
    const fileInput = w.document.getElementById('upload-template-file');
    Object.defineProperty(fileInput, 'files', { value: [{ name: 'main.tf', content: 'main' }], configurable: true });
    fileInput.dispatchEvent(new w.Event('change'));
    assert.equal(vm.runInContext("state.tfFiles['main.tf']", context), 'main');
    assert.equal(vm.runInContext('state._templateDirty', context), true);
    const folderInput = w.document.getElementById('upload-template-dir');
    Object.defineProperty(folderInput, 'files', { value: [
      { name: 'vars.tf', webkitRelativePath: 'project/sub/vars.tf', content: 'vars' },
      { name: 'README.md', content: 'ignored' },
    ] });
    folderInput.dispatchEvent(new w.Event('change'));
    assert.equal(vm.runInContext("state.tfFiles['sub/vars.tf']", context), 'vars');
    assert.equal(vm.runInContext('Object.keys(state.tfFiles).length', context), 1);
  } finally { close(); }
});

test('Terraform imports wait for every file and handle single-component relative paths', () => {
  const { window: w, context, close } = setup();
  try {
    const readers = [];
    w.FileReader = class { readAsText(file) { readers.push([this, file]); } };
    const files = [
      { name: 'main.tf', webkitRelativePath: 'main.tf', content: 'main' },
      { name: 'vars.tf', webkitRelativePath: 'root/nested/vars.tf', content: 'vars' },
      { name: 'notes.txt', content: 'ignored' },
    ];
    w.loadLocalTfFiles(files);
    assert.equal(readers.length, 2);
    readers[1][0].onload({ target: { result: readers[1][1].content } });
    assert.equal(vm.runInContext('state.tfMode', context), false);
    readers[0][0].onload({ target: { result: readers[0][1].content } });
    assert.equal(vm.runInContext("state.tfFiles['main.tf']", context), 'main');
    assert.equal(vm.runInContext("state.tfFiles['nested/vars.tf']", context), 'vars');
    readers.length = 0;
    w.loadProjectEditLocalTfFiles(files);
    readers[1][0].onload({ target: { result: readers[1][1].content } });
    readers[0][0].onload({ target: { result: readers[0][1].content } });
    assert.equal(vm.runInContext("state.projectEditTfFiles['main.tf']", context), 'main');
    assert.equal(vm.runInContext("state.projectEditTfFiles['nested/vars.tf']", context), 'vars');
  } finally { close(); }
});

test('playground Terraform menu invokes create actions and closes on outside clicks', () => {
  const { window: w, context, close } = setup();
  try {
    const calls = [];
    vm.runInContext("state.pgRegionSelect = {getSelected: () => []}", context);
    w.createTfFile = path => calls.push(['file', path]);
    w.createTfFolder = path => calls.push(['folder', path]);
    w.bindPlayground();
    w.setTemplateTab('terraform');
    w.document.getElementById('tf-add-trigger').click();
    w.document.querySelector('#tf-add-dropdown [data-action="file"]').click();
    w.document.getElementById('tf-add-trigger').click();
    w.document.querySelector('#tf-add-dropdown [data-action="folder"]').click();
    assert.deepEqual(calls, [['file', ''], ['folder', '']]);
    w.document.getElementById('template-upload-trigger').click();
    assert.ok(w.document.getElementById('template-upload-menu').classList.contains('open'));
    w.document.body.click();
    assert.equal(w.document.getElementById('template-upload-menu').classList.contains('open'), false);
  } finally { close(); }
});

test('template upload menu switches controls for ROS and Terraform', () => {
  const { window: w, close } = setup();
  try {
    w.setTemplateTab('ros');
    const dropdown = w.document.getElementById('template-upload-dropdown');
    assert.equal(dropdown.querySelector('label').htmlFor, 'upload-template');
    w.setTemplateTab('terraform');
    assert.equal(dropdown.querySelector('label').htmlFor, 'upload-template-file');
    let folderClicks = 0;
    w.document.getElementById('upload-template-dir').click = () => { folderClicks++; };
    const menu = w.document.getElementById('template-upload-menu');
    menu.classList.add('open');
    dropdown.querySelector('#tf-open-folder-item').click();
    assert.equal(folderClicks, 1);
    assert.equal(menu.classList.contains('open'), false);
  } finally { close(); }
});

test('template upload and file menus use readable fallback labels', () => {
  const { window: w, close } = setup();
  try {
    w.t = () => '';
    w.setTemplateTab('ros');
    const trigger = w.document.getElementById('template-upload-trigger');
    const dropdown = w.document.getElementById('template-upload-dropdown');
    assert.equal(trigger.title, 'Upload ROS template');
    assert.equal(dropdown.querySelector('label').textContent, 'Upload File');
    w.setTemplateTab('terraform');
    assert.equal(trigger.title, 'Open local file or folder');
    assert.deepEqual(Array.from(dropdown.querySelectorAll('.tf-open-item'), x => x.textContent),
      ['Open Local File', 'Open Local Folder']);
    const node = w.document.createElement('div');
    w.document.body.appendChild(node);
    w.showTfNodeMenu(node, 'module', true);
    assert.deepEqual(Array.from(w.document.querySelectorAll('.tf-node-menu-item'), x => x.textContent),
      ['Create File', 'Create Folder', 'Rename', 'Delete']);
  } finally { close(); }
});

test('local Terraform imports handle root files and report empty selections', () => {
  const { window: w, context, close } = setup();
  try {
    w.t = () => '';
    const notices = [];
    w.toast = (message, type) => notices.push([message, type]);
    w.FileReader = class { readAsText(file) { this.onload({ target: { result: file.content } }); } };
    w.loadLocalTfFiles([{ name: 'readme.txt' }]);
    w.loadProjectEditLocalTfFiles([]);
    assert.deepEqual(notices, [['No .tf files found', 'error'], ['No .tf files found', 'error']]);
    const files = [{ name: 'main.tf', webkitRelativePath: 'main.tf', content: 'resource {}' }];
    w.loadLocalTfFiles(files);
    assert.equal(vm.runInContext("state.tfFiles['main.tf']", context), 'resource {}');
    w.loadProjectEditLocalTfFiles(files);
    assert.equal(vm.runInContext("state.projectEditTfFiles['main.tf']", context), 'resource {}');
  } finally { close(); }
});

test('Terraform folder menu dispatches create, rename and delete actions', () => {
  const { window: w, context, close } = setup();
  try {
    const calls = [];
    w.createTfFile = path => calls.push(['file', path]);
    w.createTfFolder = path => calls.push(['folder', path]);
    w.renameTfNode = (path, folder) => calls.push(['rename', path, folder]);
    w.deleteTfFolder = path => calls.push(['delete', path]);
    const node = w.document.createElement('div');
    node.innerHTML = '<button class="tf-node-more">...</button>';
    w.document.body.appendChild(node);
    for (const action of ['create-file', 'create-folder', 'rename', 'delete']) {
      w.showTfNodeMenu(node, 'module', true);
      w.document.querySelector(`.tf-node-menu [data-action="${action}"]`).click();
      assert.equal(vm.runInContext('state._tfOpenMenu', context), null);
    }
    assert.deepEqual(calls, [['file', 'module'], ['folder', 'module'],
      ['rename', 'module', true], ['delete', 'module']]);
  } finally { close(); }
});

test('cost summary log matches the displayed total for associated products', () => {
  const { window: w, close } = setup();
  try {
    const logs = [];
    w.consoleLog = (message, options) => logs.push({ message, options });
    const price = [{ region: 'cn-a', price: { Instance: { Type: 'ALIYUN::ECS::Instance', Result: {
      Order: { Currency: 'CNY', TradeAmount: 5 }, OrderSupplement: { PriceUnit: 'Hour' },
      AssociationProducts: { Disk: { Result: { Order: { Currency: 'CNY', TradeAmount: 2 } } } },
    } } } }];
    w.logCostSummary(price);
    assert.match(logs[0].message, /¥5/);
    assert.doesNotMatch(logs[0].message, /¥7/);
    assert.equal(logs[0].options.type, 'success');
    w.logCostSummary([]);
    assert.equal(logs[1].options.type, 'warn');
    w.logCostSummary([{ region: 'cn-a', error: 'denied' }]);
    assert.equal(logs[2].options.type, 'error');
  } finally { close(); }
});

test('parameter generation and cost estimation recover from empty input and service failure', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.document.getElementById('template-editor').value = '';
    let calls = 0;
    w.fetch = async () => { calls++; throw new Error('offline'); };
    await w.autoGenerateParams();
    await w.estimateCost();
    await w.generatePolicy();
    assert.equal(calls, 0);
    w.document.getElementById('template-editor').value = 'Resources: {}';
    await w.autoGenerateParams();
    assert.match(w.document.getElementById('toast').textContent, /offline/);
    await w.estimateCost();
    assert.ok(w.document.getElementById('toast').classList.contains('error'));
    assert.equal(w.document.getElementById('btn-cost').disabled, false);
    assert.equal(w.document.getElementById('btn-generate-params').disabled, false);
  } finally { close(); }
});

test('replaced run poller ignores late status and log responses', async () => {
  const { window: w, context, close } = setup();
  try {
    const pending = {};
    w.fetch = async url => {
      if (url.includes('/old')) return new Promise(resolve => { pending[url] = resolve; });
      return { ok: true, status: 200, headers: { get: () => url.endsWith('/logs') ? 'text/plain' : 'application/json' },
        text: async () => url.endsWith('/logs') ? 'new log' : JSON.stringify({ id: 'new', name: 'new', status: 'running', progress: 70 }) };
    };
    w.pollRunInModal('old');
    w.pollRunInModal('new');
    await new Promise(resolve => setImmediate(resolve));
    pending['/api/runs/old']({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ id: 'old', name: 'old', status: 'running', progress: 10 }) });
    pending['/api/runs/old/logs']({ ok: true, status: 200, headers: { get: () => 'text/plain' }, text: async () => 'old log' });
    await new Promise(resolve => setImmediate(resolve));
    assert.match(w.document.getElementById('result-run').textContent, /70%/);
    assert.doesNotMatch(w.document.getElementById('log-run').textContent, /old log/);
    assert.equal(vm.runInContext('state._activeRunPoller.runId', context), 'new');
    vm.runInContext('state._activeRunPoller.stop()', context);
  } finally { close(); }
});

test('stopped run poller ignores late request failures and does not retry', async () => {
  const { window: w, context, close } = setup();
  try {
    const pending = [], timers = [], logs = [];
    w.setTimeout = (callback, delay) => { timers.push(delay); return timers.length; };
    w.clearTimeout = () => {};
    w.setInterval = () => 1;
    w.clearInterval = () => {};
    w.consoleLog = message => logs.push(message);
    w.api = async () => new Promise((resolve, reject) => pending.push(reject));
    w.pollRunInModal('run');
    assert.equal(pending.length, 2);
    vm.runInContext('state._activeRunPoller.stop()', context);
    pending.forEach(reject => reject(new Error('late failure')));
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(logs, []);
    assert.deepEqual(timers, []);
    assert.equal(vm.runInContext('state._activeRunPoller', context), null);
  } finally { close(); }
});

test('run polling retains the current output tab and supplies a fallback title', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.currentAction = 'cost'", context);
    w.document.getElementById('pg-output-title').textContent = 'Cost';
    w.t = () => '';
    w.setTimeout = () => 1;
    w.clearTimeout = () => {};
    w.setInterval = () => 2;
    w.clearInterval = () => {};
    w.api = async (method, url) => url.endsWith('/logs') ? '  ' : { id: 'run', status: 'running', progress: 20 };
    w.pollRunInModal('run');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(w.document.getElementById('pg-output-title').textContent, 'Cost');
    assert.equal(vm.runInContext('state.actionResults.run.title', context), 'Run running');
    assert.match(w.document.getElementById('result-run').textContent, /20%/);
    assert.equal(w.document.getElementById('log-run').textContent, '');
    vm.runInContext('state._activeRunPoller.stop()', context);
  } finally { close(); }
});

test('completed run fetches trailing logs before stopping the poller', async () => {
  const { window: w, context, close } = setup();
  try {
    let finalCallback;
    let logCalls = 0;
    w.setTimeout = (callback, delay) => { if (delay === 1500) finalCallback = callback; return 1; };
    w.clearTimeout = () => {};
    w.setInterval = () => 2;
    w.clearInterval = () => {};
    w.fetch = async url => ({ ok: true, status: 200,
      headers: { get: () => url.endsWith('/logs') ? 'text/plain' : 'application/json' },
      text: async () => url.endsWith('/logs') ? (++logCalls >= 3 ? 'initial\ntrailing' : 'initial')
        : JSON.stringify({ id: 'run', name: 'run', status: 'completed', progress: 100 }) });
    w.pollRunInModal('run');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(typeof finalCallback, 'function');
    await finalCallback();
    assert.match(w.document.getElementById('log-run').textContent, /trailing/);
    assert.equal(vm.runInContext('state._activeRunPoller', context), null);
  } finally { close(); }
});

test('replacing a completed run cancels its delayed final log fetch', async () => {
  const { window: w, context, close } = setup();
  try {
    const timers = new Map();
    let nextId = 0;
    w.setTimeout = (callback, delay) => { const id = ++nextId; timers.set(id, { callback, delay }); return id; };
    w.clearTimeout = id => timers.delete(id);
    w.setInterval = () => 100;
    w.clearInterval = () => {};
    w.fetch = async url => ({ ok: true, status: 200,
      headers: { get: () => url.endsWith('/logs') ? 'text/plain' : 'application/json' },
      text: async () => url.endsWith('/logs') ? '' : JSON.stringify({ id: url.split('/').pop(), status: url.endsWith('/old') ? 'completed' : 'running' }) });
    w.pollRunInModal('old');
    await new Promise(resolve => setImmediate(resolve));
    assert.ok(Array.from(timers.values()).some(timer => timer.delay === 1500));
    w.pollRunInModal('new');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(Array.from(timers.values()).some(timer => timer.delay === 1500), false);
    assert.equal(vm.runInContext('state._activeRunPoller.runId', context), 'new');
    vm.runInContext('state._activeRunPoller.stop()', context);
  } finally { close(); }
});

test('late completion of an old poller cannot clear a replacement for the same run', async () => {
  const { window: w, context, close } = setup();
  try {
    let finalCallback;
    let resolveFinalLog;
    let logCalls = 0;
    let statusCalls = 0;
    w.setTimeout = (callback, delay) => { if (delay === 1500) finalCallback = callback; return 1; };
    w.clearTimeout = () => {};
    w.setInterval = () => 2;
    w.clearInterval = () => {};
    w.fetch = async url => {
      if (url.endsWith('/logs') && ++logCalls === 3) {
        return new Promise(resolve => { resolveFinalLog = resolve; });
      }
      const data = url.endsWith('/logs') ? '' : JSON.stringify({ id: 'same', status: ++statusCalls === 1 ? 'completed' : 'running' });
      return { ok: true, status: 200, headers: { get: () => url.endsWith('/logs') ? 'text/plain' : 'application/json' }, text: async () => data };
    };
    w.pollRunInModal('same');
    await new Promise(resolve => setImmediate(resolve));
    const oldCompletion = finalCallback();
    w.pollRunInModal('same');
    await new Promise(resolve => setImmediate(resolve));
    resolveFinalLog({ ok: true, status: 200, headers: { get: () => 'text/plain' }, text: async () => 'late' });
    await oldCompletion;
    assert.equal(vm.runInContext('state._activeRunPoller.runId', context), 'same');
    assert.doesNotMatch(w.document.getElementById('log-run').textContent, /late/);
    vm.runInContext('state._activeRunPoller.stop()', context);
  } finally { close(); }
});

test('project run history paginates, navigates and clears the empty state', () => {
  const { window: w, context, close } = setup();
  try {
    const calls = [];
    w.navigate = (page, params) => calls.push([page, params.runId]);
    const runs = Array.from({ length: 12 }, (_, i) => ({ id: `r${i}`, name: `run ${i}`, status: 'completed',
      progress: 100, stacks: [{ status: 'CREATE_COMPLETE', test_name: 'test', region: 'cn-a' }] }));
    w.testRuns = runs;
    vm.runInContext("state.currentProject = {name: 'demo'}; state.currentProjectRuns = testRuns; state.runHistoryPage = 1; state.runHistoryPerPage = 10", context);
    const container = w.document.getElementById('project-detail-runs');
    w.renderProjectRunHistory(container, runs, { name: 'demo' });
    assert.equal(container.querySelectorAll('.pd-run-card').length, 10);
    const pagination = w.document.getElementById('run-history-pagination');
    pagination.querySelector('button[data-page="2"]').click();
    assert.equal(container.querySelectorAll('.pd-run-card').length, 2);
    container.querySelector('.pd-run-header').click();
    assert.ok(container.querySelector('.pd-run-card').classList.contains('expanded'));
    container.querySelector('.btn-view-task').click();
    assert.deepEqual(calls, [['detail', 'r10']]);
    assert.equal(vm.runInContext('state.detailSource.projectName', context), 'demo');
    w.renderProjectRunHistory(container, [], { name: 'demo' });
    assert.ok(container.querySelector('.empty-state'));
    assert.equal(pagination.innerHTML, '');
  } finally { close(); }
});

test('project history handles missing stack status and failures without explanations', () => {
  const { window: w, close } = setup();
  try {
    const container = w.document.createElement('div');
    w.document.body.appendChild(container);
    w.renderProjectRunHistory(container, [
      { id: 'running', name: 'incomplete', status: 'running', stacks: [{ test_name: 'unknown' }] },
      { id: 'failed', name: 'failed', status: 'failed', stacks: [] },
    ], { name: 'demo' });
    const cards = container.querySelectorAll('.pd-run-card');
    assert.equal(cards.length, 2);
    assert.match(cards[0].textContent, /unknown/);
    assert.ok(cards[0].querySelector('.status-running'));
    assert.equal(cards[1].querySelector('.pd-run-analysis'), null);
  } finally { close(); }
});

test('project history displays incomplete runs and unnamed failed stacks safely', () => {
  const { window: w, close } = setup();
  try {
    const container = w.document.createElement('div');
    w.document.body.appendChild(container);
    w.renderProjectRunHistory(container, [
      { name: 'no stack list', status: 'completed', stacks: null },
      { name: 'failed stack', status: 'completed', stacks: [{ status: 'CREATE_FAILED', status_reason: 'denied' }] },
    ], { name: 'demo' });
    const cards = container.querySelectorAll('.pd-run-card');
    assert.equal(cards.length, 2);
    assert.equal(cards[0].querySelector('.pd-run-analysis'), null);
    assert.match(cards[1].querySelector('.pd-run-analysis').textContent, /denied/);
  } finally { close(); }
});

test('project detail region selector preserves choices and chooses default region', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.regions = [{id:'cn-a', name:'A'}, {id:'cn-hangzhou', name:'Hangzhou'}]", context);
    const select = w.document.getElementById('pd-region-select');
    w.renderPdRegionSelect();
    assert.equal(select.value, 'cn-hangzhou');
    select.value = 'cn-a';
    w.renderPdRegionSelect();
    assert.equal(select.value, 'cn-a');
    vm.runInContext("state.regions = [{id:'cn-b', name:'B'}]", context);
    w.renderPdRegionSelect();
    assert.equal(select.value, 'cn-b');
    vm.runInContext('state.regions = []', context);
    w.renderPdRegionSelect();
    assert.equal(select.options.length, 0);
  } finally { close(); }
});

test('project detail uses region IDs when display names are missing', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.regions = [{id: 'cn-a'}]", context);
    w.renderPdRegionSelect();
    const option = w.document.getElementById('pd-region-select').options[0];
    assert.equal(option.textContent, 'cn-a');
    assert.equal(option.title, 'cn-a (cn-a)');
  } finally { close(); }
});

test('credentials warning works with optional modal decorations absent', () => {
  const { window: w, context, close } = setup();
  try {
    for (const id of ['confirm-modal-icon', 'confirm-modal-message', 'confirm-modal-warning',
      'confirm-modal-verify', 'confirm-modal-verify-hint', 'confirm-modal-cancel']) {
      w.document.getElementById(id)?.remove();
    }
    w.t = () => '';
    vm.runInContext('state.settings = null', context);
    assert.equal(w.ensureCredentials(), false);
    const modal = w.document.getElementById('confirm-modal');
    assert.ok(modal.classList.contains('open'));
    assert.equal(w.document.getElementById('confirm-modal-ok').textContent, 'Close');
    modal.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    assert.equal(modal.classList.contains('open'), false);
  } finally { close(); }
});

test('credentials warning closes on the backdrop but not on its title', () => {
  const { window: w, close } = setup();
  try {
    w.showCredentialMissingModal();
    const modal = w.document.getElementById('confirm-modal');
    w.document.getElementById('confirm-modal-title').click();
    assert.ok(modal.classList.contains('open'));
    modal.click();
    assert.equal(modal.classList.contains('open'), false);
  } finally { close(); }
});

test('editor helpers handle optional UI elements that have been removed', () => {
  const { window: w, context, close } = setup();
  try {
    const input = w.document.createElement('input');
    w.bindProjectNameLive(input, null);
    input.value = 'bad name';
    input.dispatchEvent(new w.Event('input'));
    assert.ok(input.classList.contains('input-invalid'));
    input.value = '';
    input.dispatchEvent(new w.Event('input'));
    assert.equal(input.classList.contains('input-invalid'), false);
    w.bindTemplateFormatLive(null, null);
    w.highlightEditor('missing', 'template-highlight', 'yaml');
    w.highlightPre(null, 'text', 'yaml');
    w.document.getElementById('template-line-numbers').remove();
    w.document.getElementById('template-highlight').remove();
    w.document.getElementById('config-highlight').remove();
    w.updateTemplateLineNumbers();
    w.syncLineNumberScroll();
    w.document.getElementById('log-cost').remove();
    vm.runInContext("state.currentAction = 'cost'", context);
    w.consoleClear();
    vm.runInContext('state.currentAction = null', context);
    w.consoleClear();
  } finally { close(); }
});

test('view helpers tolerate missing optional controls during initialization', () => {
  const { window: w, close } = setup();
  try {
    for (const id of ['config-region-hint', 'template-format-bar', 'btn-policy',
      'template-upload-dropdown', 'detail-stacks', 'pd-region-select', 'project-edit-region']) {
      w.document.getElementById(id).remove();
    }
    w.updateRegionHint();
    w.setTemplateTab('terraform');
    w.setTemplateFormat('json');
    w.renderTemplateUploadMenu();
    w.renderDetailStacks({ stacks: [] });
    w.renderPdRegionSelect();
    w.populateProjectEditRegionSelect();
    assert.ok(w.document.getElementById('template-editor').closest('.editor-pane').classList.contains('tf-mode-active'));
  } finally { close(); }
});

test('project detail loads empty run history and opens requested runs tab', async () => {
  const { window: w, context, close } = setup();
  try {
    const calls = [];
    w.api = async (method, url) => { calls.push([method, url]); return url.endsWith('/runs') ? {} : { name: 'demo' }; };
    w.renderProjectDetail = (project, runs) => calls.push(['render', project.name, runs.length]);
    w.switchProjectDetailTab = tab => calls.push(['tab', tab]);
    vm.runInContext('state._switchToRunsTab = true', context);
    await w.loadProjectDetail('demo');
    assert.deepEqual(calls, [['GET', '/api/projects/demo'], ['GET', '/api/projects/demo/runs'],
      ['render', 'demo', 0], ['tab', 'runs']]);
    assert.equal(vm.runInContext('state._switchToRunsTab', context), false);
    assert.equal(vm.runInContext('state.currentProjectName', context), 'demo');
  } finally { close(); }
});

test('file menu deletes a file and outside clicks dismiss its menu', () => {
  const { window: w, context, close } = setup();
  try {
    const node = w.document.createElement('div');
    node.innerHTML = '<button class="tf-node-more">...</button>';
    w.document.body.appendChild(node);
    const deleted = [];
    w.deleteTfFile = path => deleted.push(path);
    w.showTfNodeMenu(node, 'main.tf', false);
    w.document.querySelector('.tf-node-menu [data-action="delete"]').click();
    assert.deepEqual(deleted, ['main.tf']);
    w.showTfNodeMenu(node, 'main.tf', false);
    const menu = w.document.querySelector('.tf-node-menu');
    w.tfMenuClickOutside({target: menu});
    assert.ok(menu.isConnected);
    w.tfMenuClickOutside({target: node.querySelector('button')});
    assert.ok(menu.isConnected);
    w.tfMenuClickOutside({target: w.document.body});
    assert.equal(menu.isConnected, false);
    assert.equal(vm.runInContext('state._tfOpenMenu', context), null);
  } finally { close(); }
});

test('version deletion reports automatic switch and refreshes the project', async () => {
  const { window: w, close } = setup();
  try {
    const calls = [], notices = [];
    w.showConfirm = async () => true;
    w.api = async (method, url) => { calls.push([method, url]); return { auto_switched: true, current_version: 2 }; };
    w.loadProjectDetail = name => calls.push(['refresh', name]);
    w.t = (key, values) => `${key}:${values.ver}:${values.newVer}`;
    w.toast = (message, type) => notices.push([message, type]);
    await w.deleteVersion('demo', 1);
    assert.deepEqual(calls, [['DELETE', '/api/projects/demo/versions/1'], ['refresh', 'demo']]);
    assert.deepEqual(notices, [['versionDeletedAndSwitched:1:2', 'success']]);
  } finally { close(); }
});

test('loading historical Terraform content restores the unsaved ROS editor afterward', async () => {
  const { window: w, close } = setup();
  try {
    w.api = async (method, url) => url.endsWith('/versions')
      ? { current_version: 2, versions: [{ version: 1 }, { version: 2 }] }
      : { template_files: { 'main.tf': 'historical terraform' }, configs: [{ config: 'historical config' }] };
    w.setProjectEditTemplateTab('ros');
    w.document.getElementById('project-edit-template').value = 'unsaved ROS';
    w.document.getElementById('project-edit-config').value = 'unsaved config';
    await w.loadEditVersions('demo');
    const select = w.document.getElementById('project-edit-version-select');
    select.value = '1';
    await w.onEditVersionChange('demo');
    assert.equal(w.document.getElementById('project-edit-tf-template').value, 'historical terraform');
    assert.equal(w.document.getElementById('project-edit-config').value, 'historical config');
    select.value = 'current';
    await w.onEditVersionChange('demo');
    assert.equal(w.document.getElementById('project-edit-template').value, 'unsaved ROS');
    assert.equal(w.document.getElementById('project-edit-config').value, 'unsaved config');
  } finally { close(); }
});

test('project editor region selector preserves available choices and falls back when removed', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.regions = [{id:'cn-a', name:'A'}, {id:'cn-hangzhou', name:'Hangzhou'}]", context);
    const select = w.document.getElementById('project-edit-region');
    w.populateProjectEditRegionSelect();
    assert.equal(select.value, 'cn-hangzhou');
    select.value = 'cn-a';
    w.populateProjectEditRegionSelect();
    assert.equal(select.value, 'cn-a');
    vm.runInContext("state.regions = [{id:'cn-b'}]", context);
    w.populateProjectEditRegionSelect();
    assert.equal(select.value, 'cn-b');
    assert.equal(select.options[0].textContent, 'cn-b');
    vm.runInContext('state.regions = []', context);
    w.populateProjectEditRegionSelect();
    assert.equal(select.options.length, 0);
  } finally { close(); }
});

test('parameter tables support multiple tests, empty parameters and invalid YAML', () => {
  const { window: w, close } = setup();
  try {
    assert.match(w.renderParamsTable(''), /empty/);
    assert.match(w.renderParamsTable('parameters: {}'), /empty/);
    const html = w.renderParamsTable('tests:\n  first:\n    parameters: {Name: "<unsafe>", Count: 2}\n  second:\n    parameters: {Enabled: false}');
    assert.match(html, /first/);
    assert.match(html, /second/);
    assert.match(html, /&lt;unsafe&gt;/);
    assert.match(html, /false/);
    assert.match(w.renderParamsTable('invalid: [<unsafe>'), /&lt;unsafe&gt;/);
    assert.match(w.renderParamsTable('other: value'), /other: value/);
    assert.match(w.renderParamsTable('parameters: {Empty: null}'), /Empty/);
  } finally { close(); }
});

test('parameter tables retain raw configuration when parsing is unavailable or no test has parameters', () => {
  const { window: w, close } = setup();
  try {
    const config = 'tests: {default: {regions: [cn-a]}}';
    assert.match(w.renderParamsTable(config), /cn-a/);
    w.jsyaml = undefined;
    const html = w.renderParamsTable('parameters: {Name: "<value>"}');
    assert.match(html, /&lt;value&gt;/);
    assert.doesNotMatch(html, /<value>/);
  } finally { close(); }
});

test('project parameter generation reports empty template and an error without a message', async () => {
  const { window: w, close } = setup();
  try {
    const notices = [];
    w.t = key => key === 'generateParamsFailed' ? 'Generation failed' : '';
    w.toast = (message, type) => notices.push([message, type]);
    w.document.getElementById('project-edit-template').value = '';
    await w.generateParamsForProjectEdit();
    w.document.getElementById('project-edit-template').value = 'Resources: {}';
    w.api = async () => { throw new Error(''); };
    await w.generateParamsForProjectEdit();
    assert.deepEqual(notices, [['Template is empty', 'error'], ['Generation failed', 'error']]);
    assert.equal(w.document.getElementById('project-edit-generate-params').disabled, false);
  } finally { close(); }
});

test('run summary renders available links, status, failures and absent stack fields', () => {
  const { window: w, close } = setup();
  try {
    const html = w.renderRunStatusHtml({ id: 'r', name: '<task>', status: 'failed', progress: 80,
      created_at: '2026-01-01T00:00:00Z', completed_at: '2026-01-01T00:01:00Z',
      error: '<denied>', report_url: '/outputs/report', stacks: [
        { stack_id: 'id', stack_name: '<stack>', region: { id: 'cn-a' }, status: 'CREATE_FAILED', launch_succeeded: false },
        { test_name: 'pending' },
      ] });
    assert.match(html, /&lt;task&gt;/);
    assert.match(html, /&lt;denied&gt;/);
    assert.match(html, /&lt;stack&gt;/);
    assert.match(html, /ros\.console\.aliyun\.com\/cn-a\/stacks\/id/);
    assert.match(html, /outputs\/report/);
    assert.match(html, /80%/);
    assert.doesNotMatch(html, /<denied>/);
    const noStacks = w.renderRunStatusHtml({});
    assert.match(noStacks, /0%/);
  } finally { close(); }
});

test('full configuration preserves tests and updates selected regions without losing options', () => {
  const { window: w, close } = setup();
  try {
    const original = 'project: {name: original}\ntests:\n  default:\n    regions: [cn-old]\n    parameters: {Name: old}\n  other:\n    regions: [cn-other]\n';
    const unchanged = yaml.load(w.buildFullConfigYaml(original, '', 'replacement'));
    assert.equal(unchanged.project.name, 'original');
    assert.deepEqual(unchanged.tests.default.regions, ['cn-old']);
    const changed = yaml.load(w.buildFullConfigYaml(original, ' cn-a, ,cn-b ', 'replacement'));
    assert.deepEqual(changed.tests.default.regions, ['cn-a', 'cn-b']);
    assert.deepEqual(changed.tests.other.regions, ['cn-other']);
    assert.equal(changed.tests.default.parameters.Name, 'old');
    const withoutProject = yaml.load(w.buildFullConfigYaml('tests: {default: {regions: [cn-a]}}', '', 'demo'));
    assert.equal(withoutProject.project.name, 'demo');
    assert.deepEqual(Array.from(w.regionsFromConfig('tests: {first: {regions: "cn-a, cn-b"}}')), ['cn-a', 'cn-b']);
    assert.deepEqual(Array.from(w.regionsFromConfig('tests: {default: {}}')), []);
    assert.equal(w.regionsFromConfig('tests: []'), null);
  } finally { close(); }
});

test('task polling refreshes the current page and stops after settlement', async () => {
  const { window: w, context, close } = setup();
  try {
    let callback;
    let cleared = false;
    const calls = [];
    w.setInterval = handler => { callback = handler; return 42; };
    w.clearInterval = () => { cleared = true; };
    w.loadDetail = async id => calls.push(['detail', id]);
    w.pollProjectRuns = async name => calls.push(['project', name]);
    vm.runInContext("state.page = 'detail'; state.currentRunId = 'r'; state.currentRun = {status:'running'}", context);
    w.startTaskPolling();
    await callback();
    assert.deepEqual(calls, [['detail', 'r']]);
    vm.runInContext("state.page = 'project-detail'; state.currentProjectName = 'demo'; state.currentProjectRuns = []", context);
    await callback();
    assert.deepEqual(calls, [['detail', 'r'], ['project', 'demo']]);
    assert.equal(cleared, true);
    assert.equal(vm.runInContext('state.taskTimer', context), null);
  } finally { close(); }
});

test('task polling does not create duplicate timers and stops for a settled detail', async () => {
  const { window: w, context, close } = setup();
  try {
    let callback, starts = 0, clears = 0, refreshes = 0;
    w.setInterval = handler => { starts++; callback = handler; return 7; };
    w.clearInterval = () => { clears++; };
    w.loadTasks = async () => { refreshes++; };
    vm.runInContext("state.page = 'tasks'; state.tasks = [{status:'running'}]", context);
    w.startTaskPolling();
    w.startTaskPolling();
    assert.equal(starts, 1);
    await callback();
    assert.equal(refreshes, 1);
    assert.equal(clears, 0);
    vm.runInContext("state.page = 'detail'; state.currentRun = {status:'completed', stacks:[]}", context);
    w.checkStopTaskPolling();
    w.stopTaskPolling();
    assert.equal(clears, 1);
    assert.equal(vm.runInContext('state.taskTimer', context), null);
  } finally { close(); }
});

test('project polling stays active while stacks delete and stops after settlement', () => {
  const { window: w, context, close } = setup();
  try {
    const stopped = [];
    w.clearInterval = id => stopped.push(id);
    vm.runInContext("state.page = 'project-detail'; state.taskTimer = 7; state.currentProjectRuns = [{status:'completed', stacks:[{status:'DELETE_IN_PROGRESS'}]}]", context);
    w.checkStopTaskPolling();
    assert.deepEqual(stopped, []);
    vm.runInContext("state.currentProjectRuns[0].stacks[0].status = 'DELETE_COMPLETE'", context);
    w.checkStopTaskPolling();
    assert.deepEqual(stopped, [7]);
    vm.runInContext('state.taskTimer = 8; state.currentProjectRuns = []', context);
    w.checkStopTaskPolling();
    assert.deepEqual(stopped, [7, 8]);
  } finally { close(); }
});

test('task refresh from detail page tolerates an empty response and refreshes the current run', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.page = 'detail'; state.currentRunId = 'run-id'; state.tasks = [{id:'old'}]", context);
    const loaded = [];
    w.api = async () => ({});
    w.loadDetail = id => loaded.push(id);
    await w.loadTasks();
    assert.deepEqual(loaded, ['run-id']);
    assert.equal(vm.runInContext('state.tasks.length', context), 0);
    assert.equal(vm.runInContext('state.taskTotal', context), 0);
  } finally { close(); }
});

test('CLI log viewer handles empty, failed and colorized responses safely', async () => {
  const { window: w, close } = setup();
  try {
    let content = '';
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'text/plain' }, text: async () => content });
    await w.renderCliLogs('run');
    const container = w.document.getElementById('detail-logs');
    assert.ok(container.querySelector('.empty-state'));
    content = '2026-01-01 12:00:00,000 [ERROR] : \x1b[31m<denied>\x1b[0m\nplain';
    await w.renderCliLogs('run');
    assert.ok(container.querySelector('.term-error'));
    assert.match(container.textContent, /<denied>/);
    assert.equal(container.querySelector('denied'), null);
    assert.match(container.textContent, /plain/);
    w.fetch = async () => { throw new Error('offline'); };
    await w.renderCliLogs('run');
    assert.ok(container.querySelector('.empty-state'));
  } finally { close(); }
});

test('task completion logs only status transitions into terminal states', () => {
  const { window: w, context, close } = setup();
  try {
    const logs = [];
    w.consoleLog = (message, options) => logs.push({ message, options });
    vm.runInContext("state.taskStatusMap = {first:'running', second:'pending', unchanged:'completed'}", context);
    w.logTaskCompletion([
      { id: 'first', name: 'A', status: 'completed' },
      { id: 'second', name: 'B', status: 'failed' },
      { id: 'unchanged', name: 'C', status: 'completed' },
      { id: 'new', name: 'D', status: 'failed' },
    ]);
    assert.equal(logs.length, 2);
    assert.equal(logs[0].options.type, 'success');
    assert.equal(logs[1].options.type, 'error');
    assert.match(logs[0].message, /A/);
    assert.match(logs[1].message, /B/);
  } finally { close(); }
});

test('project run validates Terraform payload and preserves options and legacy config', async () => {
  const { window: w, context, close } = setup();
  try {
    const requests = [];
    let refreshed;
    vm.runInContext("state.pgRegionSelect = {getSelected: () => ['cn-a']}", context);
    w.loadProjectDetail = async name => { refreshed = name; };
    w.fetch = async (url, options) => {
      const payload = options.body ? JSON.parse(options.body) : null;
      requests.push({ url, payload });
      const data = url === '/api/projects/demo'
        ? { template_files: { 'main.tf': 'resource {}' }, configs: [{ config: 'parameters: {Name: value}' }],
            no_delete: true, keep_failed: true, dont_wait_for_delete: true }
        : url === '/api/validate' ? { result: 'valid' } : { id: 'run' };
      return { ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => JSON.stringify(data) };
    };
    await w.runProjectFromDetail('demo');
    assert.deepEqual(requests.map(item => item.url), ['/api/projects/demo', '/api/validate', '/api/runs']);
    const sent = requests[1].payload;
    assert.deepEqual(sent.template_files, { 'main.tf': 'resource {}' });
    assert.equal(sent.regions, 'cn-a');
    assert.equal(sent.no_delete, true);
    assert.equal(sent.keep_failed, true);
    assert.equal(sent.dont_wait_for_delete, true);
    assert.equal(yaml.load(sent.config_content).tests.default.parameters.Name, 'value');
    assert.ok(requests[2].payload.request_id);
    assert.equal(refreshed, 'demo');
  } finally { close(); }
});

test('project run shows lookup failures and does not send validation or run requests', async () => {
  const { window: w, close } = setup();
  try {
    let requests = 0;
    w.fetch = async () => { requests++; throw new Error('project unavailable'); };
    await w.runProjectFromDetail('demo');
    assert.equal(requests, 1);
    assert.match(w.document.getElementById('toast').textContent, /project unavailable/);
    assert.equal(w.document.getElementById('btn-project-detail-run').disabled, false);
  } finally { close(); }
});

test('live template validation updates and clears hints after debounce', () => {
  const { window: w, close } = setup();
  try {
    let callback;
    let cancelled = 0;
    w.setTimeout = handler => { callback = handler; return 1; };
    w.clearTimeout = () => { cancelled++; };
    const editor = w.document.getElementById('project-edit-template');
    const hint = w.document.getElementById('project-edit-template-hint');
    w.bindTemplateFormatLive(editor, hint);
    editor.value = '{invalid';
    editor.dispatchEvent(new w.Event('input'));
    callback();
    assert.ok(editor.classList.contains('input-invalid'));
    assert.ok(hint.classList.contains('visible'));
    editor.value = '{"Resources":{}}';
    editor.dispatchEvent(new w.Event('input'));
    callback();
    assert.equal(editor.classList.contains('input-invalid'), false);
    assert.equal(hint.classList.contains('visible'), false);
    assert.ok(cancelled >= 2);
  } finally { close(); }
});

test('ANSI output handles combined colors, reset and HTML escaping', () => {
  const { window: w, close } = setup();
  try {
    const output = w.ansiToHtml('\x1b[1;31;44m<bad>\x1b[m normal');
    assert.match(output, /color:#cc0000/);
    assert.match(output, /background:#3465a4/);
    assert.match(output, /font-weight:bold/);
    assert.match(output, /&lt;bad&gt;<\/span> normal/);
    assert.equal(w.ansiToHtml(''), '');
    assert.equal(w.validateProjectName('A'.repeat(255)), null);
    assert.ok(w.validateProjectName('A'.repeat(256)));
  } finally { close(); }
});

test('ANSI output closes existing spans when styles change or reset', () => {
  const { window: w, close } = setup();
  try {
    const html = w.ansiToHtml('\x1b[31mred\x1b[44mcombined\x1b[0mplain\x1b[42mgreen-bg');
    const container = w.document.createElement('div');
    container.innerHTML = html;
    assert.equal(container.textContent, 'redcombinedplaingreen-bg');
    const spans = container.querySelectorAll('span');
    assert.equal(spans.length, 3);
    assert.match(spans[1].getAttribute('style'), /color:#cc0000/);
    assert.match(spans[1].getAttribute('style'), /background:#3465a4/);
    assert.match(spans[2].getAttribute('style'), /background:#4e9a06/);
    assert.equal(spans[0].textContent, 'red');
  } finally { close(); }
});

test('ANSI reset without active styling and unknown codes leave text intact', () => {
  const { window: w, close } = setup();
  try {
    const container = w.document.createElement('div');
    container.innerHTML = w.ansiToHtml('\x1b[0mplain\x1b[999m unchanged\x1b[31m red');
    assert.equal(container.textContent, 'plain unchanged red');
    assert.equal(container.querySelectorAll('span').length, 1);
  } finally { close(); }
});

test('run polling retries failures without duplicate errors and reports a later failure after recovery', async () => {
  const { window: w, context, close } = setup();
  try {
    let retry;
    let logPoll;
    let statusCalls = 0;
    const messages = [];
    w.setTimeout = (callback, delay) => { if (delay === 5000) retry = callback; return 1; };
    w.clearTimeout = () => {};
    w.setInterval = callback => { logPoll = callback; return 2; };
    w.clearInterval = () => {};
    w.consoleLog = message => messages.push(message);
    w.fetch = async url => {
      if (url.endsWith('/logs')) throw new Error('logs unavailable');
      statusCalls++;
      if (statusCalls !== 3) throw new Error('status unavailable');
      return { ok: true, status: 200, headers: { get: () => 'application/json' },
        text: async () => JSON.stringify({ id: 'run', status: 'running', progress: 40 }) };
    };
    w.pollRunInModal('run');
    await new Promise(resolve => setImmediate(resolve));
    await logPoll();
    await retry();
    assert.equal(messages.filter(message => message.includes('logs unavailable')).length, 1);
    assert.equal(messages.filter(message => message.includes('status unavailable')).length, 1);
    await retry();
    assert.match(w.document.getElementById('result-run').textContent, /40%/);
    await retry();
    assert.equal(messages.filter(message => message.includes('status unavailable')).length, 2);
    vm.runInContext('state._activeRunPoller.stop()', context);
  } finally { close(); }
});

test('cost summary treats missing or zero amounts as zero', () => {
  const { window: w, close } = setup();
  try {
    const messages = [];
    w.consoleLog = message => messages.push(message);
    w.logCostSummary([{ price: { Instance: { Result: { Order: { Currency: 'CNY', TradeAmount: 0 } } } } }]);
    assert.match(messages[0], /¥0/);
  } finally { close(); }
});

test('cost summaries default currency and retain an already-prefixed billing unit', () => {
  const { window: w, close } = setup();
  try {
    const messages = [];
    w.consoleLog = (message, options) => messages.push([message, options.type]);
    const price = { region: 'cn-a', price: {
      Instance: { Type: 'ALIYUN::ECS::Instance', Result: {
        Order: { TradeAmount: 1.5 }, OrderSupplement: { PriceUnit: '/hour' },
      } },
    } };
    const html = w.renderCostResultsHtml([price]);
    assert.match(html, /¥1\.5/);
    assert.match(html, /\/hour/);
    assert.doesNotMatch(html, /\/\/hour/);
    w.logCostSummary([price]);
    assert.match(messages[0][0], /¥1\.5\/hour/);
    assert.equal(messages[0][1], 'success');
    assert.equal(w.formatPrice(5), '5');
  } finally { close(); }
});

test('cost summaries retain resource errors and do not combine incompatible units', () => {
  const { window: w, close } = setup();
  try {
    const messages = [];
    w.consoleLog = (message, options) => messages.push({ message, options });
    const price = { price: {
      First: { Result: { Order: { Currency: 'USD', TradeAmount: 1 }, OrderSupplement: { PriceUnit: '/Hour' } } },
      Second: { Result: { Order: { Currency: 'USD', TradeAmount: 2 }, OrderSupplement: { PriceUnit: 'Month' } } },
      Failed: { Success: false, Result: { Code: 'Denied', Message: '<private>' } },
    } };
    const html = w.renderCostResultsHtml([price]);
    assert.match(html, /&lt;private&gt;/);
    assert.match(html, /\$3/);
    w.logCostSummary([price]);
    assert.equal(messages[0].options.type, 'error');
    assert.equal(messages[1].options.type, 'info');
    assert.match(messages[1].message, /\$3/);
    assert.doesNotMatch(messages[1].message, /\/Hour|\/Month/);
    w.logCostSummary([{ price: { Failed: { Success: false } } }]);
    assert.equal(messages[2].options.type, 'error');
    assert.equal(messages[3].options.type, 'warn');
  } finally { close(); }
});

test('run status shows completed and pending stacks with appropriate links', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.runActiveTab = 'stacks'", context);
    const html = w.renderRunStatusHtml({ status: 'completed', created_at: '2026-01-01T00:00:00Z', stacks: [
      { stack_id: 'stack/one', test_name: 'test <one>', region: { id: 'cn-a' }, launch_succeeded: true },
      { stack_id: 'orphan', region: {}, launch_succeeded: false },
      { status: 'CREATE_IN_PROGRESS' },
    ] });
    const element = w.document.createElement('div');
    element.innerHTML = html;
    assert.ok(element.querySelector('.progress-fill.completed'));
    assert.ok(element.querySelector('[data-run-tab="stacks"].active'));
    assert.match(element.querySelector('a.stack-link').href, /cn-a\/stacks\/stack%2Fone/);
    assert.equal(element.querySelector('a.stack-link').textContent, 'test <one>');
    assert.equal(element.querySelectorAll('.stack-id-text:not(a)').length, 1);
    assert.ok(element.querySelector('.pd-stack-stat-succeeded'));
    assert.ok(element.querySelector('.pd-stack-stat-failed'));
  } finally { close(); }
});

test('renaming an inactive Terraform file preserves its stored content', async () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.projectEditTfFiles = {'active.tf': 'active', 'other.tf': 'stored'}; state.projectEditTfActiveFile = 'active.tf'", context);
    w.document.getElementById('project-edit-tf-template').value = 'unsaved active';
    w.showPrompt = async () => 'renamed.tf';
    await w.renameProjectEditTfFile('other.tf');
    assert.equal(vm.runInContext("state.projectEditTfFiles['renamed.tf']", context), 'stored');
    assert.equal(vm.runInContext('state.projectEditTfActiveFile', context), 'active.tf');
    assert.equal(w.document.getElementById('project-edit-tf-template').value, 'unsaved active');
  } finally { close(); }
});

test('CLI formatter detects real cycles without mistaking repeated arrays for cycles', () => {
  const { window: w, close } = setup();
  try {
    const shared = ['one'];
    const formatted = w.formatCliOutput({ first: shared, second: shared });
    assert.equal((formatted.match(/one/g) || []).length, 2);
    assert.doesNotMatch(formatted, /circular/);
    const cycle = [];
    cycle.push(cycle);
    assert.match(w.formatCliOutput(cycle), /<circular>/);
    assert.match(w.formatCliOutput({ empty: [], missing: null }), /<empty list>/);
    assert.match(w.formatCliOutput({ empty: [], missing: null }), /missing: <null>/);
  } finally { close(); }
});

test('CLI formatter displays empty and scalar results without losing indentation', () => {
  const { window: w, close } = setup();
  try {
    assert.equal(w.formatCliOutput(undefined), '<null>');
    assert.equal(w.formatCliOutput({}), '<empty>');
    assert.equal(w.formatCliOutput([]), '<empty list>');
    assert.equal(w.formatCliOutput(false), 'false');
    assert.match(w.formatCliOutput({ nested: { value: 2 }, missing: undefined }), /nested:\n  value: 2/);
    assert.match(w.formatCliOutput({ missing: undefined }), /missing: <null>/);
  } finally { close(); }
});

test('project ROS detail switches highlight format, copies text and collapses sections', async () => {
  const { window: w, context, close } = setup();
  try {
    let copied;
    w.renderVersionHistory = async () => {};
    w.copyToClipboard = async text => { copied = text; };
    w.renderProjectDetail({ name: 'demo', template: '{"Resources":{}}', config: 'parameters: {Name: sample}' }, []);
    const panel = w.document.getElementById('project-detail-template');
    assert.equal(vm.runInContext('state.pdTemplateFormat', context), 'json');
    panel.querySelector('[data-pd-format="yaml"]').click();
    assert.equal(vm.runInContext('state.pdTemplateFormat', context), 'yaml');
    assert.match(w.document.getElementById('pd-template-content').textContent, /Resources/);
    panel.querySelector('.pd-template-copy-btn').click();
    await new Promise(resolve => setImmediate(resolve));
    assert.match(copied, /Resources/);
    const section = w.document.getElementById('pd-section-basic');
    section.querySelector('.pd-section-header').click();
    assert.ok(section.classList.contains('collapsed'));
  } finally { close(); }
});

test('project detail buttons navigate and dispatch actions for the selected project', () => {
  const { window: w, close } = setup();
  try {
    const calls = [];
    w.navigate = page => calls.push(['navigate', page]);
    w.loadProjectIntoPlayground = name => calls.push(['load', name]);
    w.openEditProject = name => calls.push(['edit', name]);
    w.runProjectFromDetail = name => calls.push(['run', name]);
    w.bindProjectDetail();
    for (const action of ['load', 'edit', 'run']) {
      const btn = w.document.getElementById(`btn-project-detail-${action}`);
      btn.dataset.name = 'demo';
      btn.click();
    }
    w.document.getElementById('btn-project-detail-back').click();
    assert.deepEqual(calls, [['load', 'demo'], ['edit', 'demo'], ['run', 'demo'], ['navigate', 'projects']]);
  } finally { close(); }
});

test('region selector toggles checkboxes, reports counts and invokes close once', () => {
  const { window: w, context, close } = setup();
  try {
    const updates = [];
    let closed = 0;
    w.regionChanged = values => updates.push(Array.from(values));
    const selector = vm.runInContext("new RegionSelect('pg-region-trigger', 'pg-region-dropdown', regionChanged)", context);
    selector.onClose = () => { closed++; };
    selector.setData([{ id: 'cn-a', name: 'Alpha' }, { id: 'cn-b', name: 'Beta' }, { id: 'cn-c', name: 'Gamma' }]);
    selector.setSelected(['cn-a', 'cn-b', 'unknown']);
    assert.match(w.document.querySelector('#pg-region-trigger span').textContent, /3/);
    selector.toggle();
    const dropdown = w.document.getElementById('pg-region-dropdown');
    const search = dropdown.querySelector('.region-search');
    search.value = 'gamma';
    search.dispatchEvent(new w.Event('input'));
    const option = dropdown.querySelector('.region-option');
    assert.match(option.textContent, /Gamma/);
    option.click();
    assert.ok(Array.from(selector.getSelected()).includes('cn-c'));
    const checkbox = option.querySelector('input');
    checkbox.checked = false;
    checkbox.dispatchEvent(new w.Event('change', { bubbles: true }));
    assert.equal(Array.from(selector.getSelected()).includes('cn-c'), false);
    assert.equal(updates.length, 2);
    selector.toggle();
    selector.close();
    assert.equal(closed, 1);
  } finally { close(); }
});

test('region selector handles direct checkbox clicks and optional toolbar controls', () => {
  const { window: w, context, close } = setup();
  try {
    const updates = [];
    w.regionChanged = values => updates.push(Array.from(values));
    const selector = vm.runInContext("new RegionSelect('pg-region-trigger', 'pg-region-dropdown', regionChanged)", context);
    selector.setData([{ id: 'cn-a', name: 'A' }]);
    const dropdown = w.document.getElementById('pg-region-dropdown');
    const checkbox = dropdown.querySelector('.region-option input');
    checkbox.click();
    assert.deepEqual(updates, [['cn-a']]);
    dropdown.querySelector('.region-select-all').remove();
    dropdown.querySelector('.region-clear-all').remove();
    dropdown.querySelector('.region-search').remove();
    w.document.querySelector('#pg-region-trigger span').remove();
    selector.toggle();
    selector.setSelected([]);
    selector.close();
    assert.equal(dropdown.classList.contains('open'), false);
  } finally { close(); }
});

test('region selector supports missing DOM elements and unknown regions', () => {
  const { context, close } = setup();
  try {
    const selector = vm.runInContext("new RegionSelect('missing-trigger', 'missing-dropdown')", context);
    selector.setData([{ id: 'cn-a', name: 'Alpha' }]);
    selector.setSelected(['unknown']);
    assert.deepEqual(Array.from(selector.getSelected()), ['unknown']);
    selector.toggle();
    selector.close();
  } finally { close(); }
});

test('output modals handle empty policy, text and clipboard failures', async () => {
  const { window: w, close } = setup();
  try {
    w.openPolicyModal(null);
    assert.ok(w.document.getElementById('policy-body').textContent.length > 0);
    w.openResultModal('Text', 'plain result', 'text');
    assert.equal(w.document.getElementById('result-body').textContent, 'plain result');
    w.copyToClipboard = async () => { throw new Error('clipboard unavailable'); };
    await w.copyPolicyToClipboard();
    assert.ok(w.document.getElementById('toast').classList.contains('error'));
    await w.copyResultToClipboard();
    assert.ok(w.document.getElementById('toast').classList.contains('error'));
  } finally { close(); }
});

test('clearing all output removes every result and log when no action is active', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => []}", context);
    for (const action of ['policy', 'cost', 'run']) {
      w.showActionResult(action, action, { value: action }, 'json');
      w.consoleLog(`log ${action}`, { action });
    }
    vm.runInContext('state.currentAction = null', context);
    w.clearResultPanel();
    for (const action of ['policy', 'cost', 'run']) {
      assert.equal(w.document.getElementById(`result-${action}`).textContent, '');
      assert.equal(w.document.getElementById(`log-${action}`).textContent, '');
    }
    assert.equal(w.document.getElementById('pg-body').classList.contains('collapsed'), false);
  } finally { close(); }
});

test('output helpers ignore unknown actions and missing optional result panels', () => {
  const { window: w, context, close } = setup();
  try {
    vm.runInContext("state.pgRegionSelect = {getSelected: () => []}; state.currentAction = null", context);
    w.setCurrentAction('unknown');
    w.showActionResult('unknown', 'Ignored', '<unsafe>', 'html');
    w.showActionLoading('unknown', 'Ignored');
    assert.equal(vm.runInContext('state.currentAction', context), null);
    assert.equal(vm.runInContext('state._hasActionOutput', context), false);
    w.document.getElementById('result-cost').remove();
    w.document.getElementById('logs-section-cost').remove();
    w.showActionResult('cost', 'Cost', 'content', 'text');
    w.showActionLoading('cost', 'Loading');
    w.syncOutputSections('cost');
    w.clearActionResult('cost');
    w.clearActionResult(null);
    assert.equal(vm.runInContext('state.actionResults.cost', context), null);
  } finally { close(); }
});

test('version diff aligns unequal changes and renders content as text', () => {
  const { window: w, close } = setup();
  try {
    const container = w.document.createElement('div');
    w.renderDiffView(container, 'same\nremoved one\nremoved two\nend',
      'same\n<added>\nend\nextra', 'Old', 'New');
    const panes = container.querySelectorAll('.diff-pane');
    assert.equal(panes.length, 2);
    assert.equal(panes[0].querySelectorAll('.diff-line').length, panes[1].querySelectorAll('.diff-line').length);
    assert.ok(container.querySelectorAll('.diff-placeholder').length >= 2);
    assert.ok(container.querySelector('.diff-removed'));
    assert.ok(container.querySelector('.diff-added'));
    assert.match(container.textContent, /<added>/);
    assert.equal(container.querySelector('added'), null);
    assert.deepEqual(Array.from(w.computeLineDiff('same', 'same'), row => row.type), ['unchanged']);
    assert.deepEqual(Array.from(w.computeLineDiff('a\nb', 'a'), row => row.type), ['unchanged', 'removed']);
    assert.deepEqual(Array.from(w.computeLineDiff('a', 'a\nb'), row => row.type), ['unchanged', 'added']);
    const longText = Array.from({ length: 100 }, (_, i) => `line ${i}`).join('\n');
    assert.equal(w.computeLineDiff(longText, longText).length, 100);
  } finally { close(); }
});

test('credential warning and confirmation dialogs restore shared controls between uses', async () => {
  const { window: w, context, close } = setup();
  try {
    const ordinary = w.showConfirm('Ordinary');
    w.document.getElementById('confirm-modal-cancel').click();
    assert.equal(await ordinary, false);
    vm.runInContext("state.settings = {source: 'none'}", context);
    assert.equal(w.ensureCredentials(), false);
    const modal = w.document.getElementById('confirm-modal');
    assert.equal(w.document.getElementById('confirm-modal-title').classList.contains('hidden'), false);
    assert.equal(w.document.getElementById('confirm-modal-cancel').style.display, 'none');
    modal.click();
    assert.equal(modal.classList.contains('open'), false);
    const confirmation = w.showConfirm('Overwrite?', { verify: { expected: 'demo', hint: 'Type demo' } });
    assert.equal(w.document.getElementById('confirm-modal-cancel').style.display, '');
    assert.equal(w.document.getElementById('confirm-modal-verify-hint').classList.contains('hidden'), false);
    assert.equal(w.document.getElementById('confirm-modal-verify-hint').textContent, 'Type demo');
    w.document.getElementById('confirm-modal-cancel').click();
    assert.equal(await confirmation, false);
  } finally { close(); }
});

test('credential warning still opens when the optional title element is absent', () => {
  const { window: w, close } = setup();
  try {
    w.document.getElementById('confirm-modal-title').remove();
    w.showCredentialMissingModal();
    const modal = w.document.getElementById('confirm-modal');
    assert.ok(modal.classList.contains('open'));
    w.document.getElementById('confirm-modal-ok').click();
    assert.equal(modal.classList.contains('open'), false);
  } finally { close(); }
});

test('settings load honors silent mode and reports errors', async () => {
  const { window: w, context, close } = setup();
  try {
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ settings: { source: 'env' } }) });
    await w.loadSettings(false);
    assert.equal(vm.runInContext('state.settings.source', context), 'env');
    assert.equal(w.ensureCredentials(), true);
    w.fetch = async () => ({ ok: true, status: 200, headers: { get: () => 'application/json' }, text: async () => '{}' });
    await w.loadSettings();
    assert.equal(vm.runInContext('Object.keys(state.settings).length', context), 0);
    assert.equal(w.document.getElementById('toast').textContent, w.t('settingsLoaded'));
    w.fetch = async () => { throw new Error('settings unavailable'); };
    await w.loadSettings();
    assert.match(w.document.getElementById('toast').textContent, /settings unavailable/);
    assert.ok(w.document.getElementById('toast').classList.contains('error'));
  } finally { close(); }
});

test('inline prompt closes on outside click and ignores clicks on its anchor', async () => {
  const { window: w, close } = setup();
  try {
    const anchor = w.document.getElementById('template-editor');
    const pending = w.showInlinePrompt({ anchorEl: anchor, title: '<name>', placeholder: 'File' });
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.equal(w.document.querySelector('.tf-prompt-title').textContent, '<name>');
    anchor.click();
    assert.ok(w.document.querySelector('.tf-prompt-popover'));
    w.document.body.click();
    assert.equal(await pending, null);
    assert.equal(w.document.querySelector('.tf-prompt-popover'), null);
  } finally { close(); }
});

test('inline prompt supports keyboard confirmation and cancellation without an anchor', async () => {
  const { window: w, close } = setup();
  try {
    const confirm = w.showInlinePrompt({ title: 'File', defaultValue: '  main.tf  ' });
    let input = w.document.querySelector('.tf-prompt-input');
    input.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter' }));
    assert.equal(await confirm, 'main.tf');
    const cancel = w.showInlinePrompt({ title: 'Folder' });
    input = w.document.querySelector('.tf-prompt-input');
    input.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape' }));
    assert.equal(await cancel, null);
    assert.equal(w.document.querySelector('.tf-prompt-popover'), null);
  } finally { close(); }
});

test('confirmation shows warning and requires matching input before acceptance', async () => {
  const { window: w, close } = setup();
  try {
    const pending = w.showConfirm('Delete?', { title: 'Confirm delete', warning: 'Cannot undo',
      okText: 'Delete', cancelText: 'Keep', verify: { expected: 'demo', hint: 'Type demo' } });
    const warning = w.document.getElementById('confirm-modal-warning');
    const ok = w.document.getElementById('confirm-modal-ok');
    const input = w.document.getElementById('confirm-modal-verify-input');
    assert.equal(warning.textContent, 'Cannot undo');
    assert.equal(ok.disabled, true);
    input.value = 'wrong';
    input.dispatchEvent(new w.Event('input'));
    assert.equal(ok.disabled, true);
    input.value = ' demo ';
    input.dispatchEvent(new w.Event('input'));
    assert.equal(ok.disabled, false);
    ok.click();
    assert.equal(await pending, true);
  } finally { close(); }
});

test('task detail exposes appropriate actions and opens the report viewer', () => {
  const { window: w, close } = setup();
  try {
    const calls = [];
    w.renderCliLogs = async () => {};
    w.cancelTask = id => calls.push(['cancel', id]);
    w.deleteRunStacks = id => calls.push(['delete-stacks', id]);
    w.renderDetail({ id: 'run', name: 'Task', status: 'running', params: {}, stacks: [{ stack_id: 's', status: 'CREATE_COMPLETE' }] });
    const actions = w.document.getElementById('detail-header-actions');
    actions.querySelector('.btn-cancel-task').click();
    assert.equal(actions.querySelector('.btn-delete-stacks'), null);
    w.renderDetail({ id: 'run', name: 'Task', status: 'completed', params: {}, report_url: '/outputs/report.html',
      stacks: [{ stack_id: 's', status: 'DELETE_FAILED' }] });
    actions.querySelector('.btn-delete-stacks').click();
    w.document.querySelector('#detail-overview .btn-view-report').click();
    assert.deepEqual(calls, [['cancel', 'run'], ['delete-stacks', 'run']]);
    assert.ok(w.document.getElementById('report-modal').classList.contains('open'));
    assert.match(w.document.getElementById('report-iframe').src, /report\.html/);
    w.closeReportModal();
    assert.equal(w.document.getElementById('report-modal').classList.contains('open'), false);
    w.renderDetail({ id: 'run', name: 'Task', status: 'completed', params: {},
      stacks: [{ stack_id: 's', status: 'DELETE_COMPLETE' }] });
    assert.equal(actions.querySelector('.btn-delete-stacks'), null);
  } finally { close(); }
});

test('task detail cannot delete stacks while deletion is already in progress', () => {
  const { window: w, close } = setup();
  try {
    w.renderCliLogs = async () => {};
    const actions = w.document.getElementById('detail-header-actions');
    for (const status of ['DELETE_REQUESTING', 'DELETE_IN_PROGRESS', 'DELETE_COMPLETE']) {
      w.renderDetail({ id: 'run', name: 'Task', status: 'completed', params: {}, stacks: [{ stack_id: 's', status }] });
      assert.equal(actions.querySelector('.btn-delete-stacks'), null, status);
    }
    w.renderDetail({ id: 'run', name: 'Task', status: 'pending', params: {},
      stacks: [{ stack_id: 's', status: 'CREATE_COMPLETE' }] });
    assert.equal(actions.querySelector('.btn-delete-stacks'), null);
    w.renderDetail({ id: 'run', name: 'Task', status: 'completed', params: {}, stacks: [{ status: 'CREATE_COMPLETE' }] });
    assert.equal(actions.querySelector('.btn-delete-stacks'), null);
  } finally { close(); }
});

test('task detail back navigation returns to originating project or task list', () => {
  const { window: w, context, close } = setup();
  try {
    const calls = [];
    w.navigate = (page, params) => calls.push([page, params && params.projectName]);
    w.bindDetail();
    vm.runInContext("state.detailSource = {page: 'project-detail', projectName: 'demo'}", context);
    w.document.getElementById('btn-detail-back').click();
    assert.equal(vm.runInContext('state._switchToRunsTab', context), true);
    w.document.getElementById('btn-detail-back').click();
    assert.deepEqual(calls, [['project-detail', 'demo'], ['tasks', undefined]]);
    w.openReportModal('/outputs/report.html');
    w.document.getElementById('report-modal').click();
    assert.equal(w.document.getElementById('report-modal').classList.contains('open'), false);
  } finally { close(); }
});
