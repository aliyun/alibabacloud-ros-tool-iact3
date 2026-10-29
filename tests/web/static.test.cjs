const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../../iact3/web/static');
const sources = new Map();
function load(name, context) {
  const filename = path.join(root, name);
  if (!sources.has(filename)) {
    let source = fs.readFileSync(filename, 'utf8');
    if (process.env.IACT3_COVERAGE) {
      const { createInstrumenter } = require('istanbul-lib-instrument');
      source = createInstrumenter().instrumentSync(source, filename);
    }
    sources.set(filename, source);
  }
  if (process.env.IACT3_COVERAGE) {
    context.__coverage__ = global.__coverage__ = global.__coverage__ || {};
  }
  vm.runInContext(sources.get(filename), context, { filename });
}
function browser(language = 'en') {
  const storage = new Map();
  const context = vm.createContext({
    navigator: { language },
    localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) },
    document: { addEventListener() {}, querySelectorAll() { return []; } },
    window: { dispatchEvent() {} },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
  });
  load('i18n.js', context);
  load('app.js', context);
  return { context, storage };
}

test('translations fall back to keys and interpolate variables', () => {
  const { context, storage } = browser();
  assert.equal(context.t('missing.translation'), 'missing.translation');
  assert.equal(context.tStackStatus('UNKNOWN_STATUS'), 'UNKNOWN_STATUS');
  assert.equal(context.tStackStatus(''), '');
  context.setLang('zh');
  assert.equal(storage.get('iact3-lang'), 'zh');
  assert.match(context.translateStatusReason('QuotaExceeded: code: 403'), /配额超限.*状态码: 403/);
  assert.equal(context.extractErrorMessage('Resource CREATE failed: QuotaExceeded'), '配额超限');
  context.setLang('en');
  assert.equal(context.extractErrorMessage('ResultReason: failure'), 'failure');
  assert.equal(context.translateStatusReason('QuotaExceeded'), 'QuotaExceeded');
});

test('API redirects expired sessions and handles errors with empty response bodies', async () => {
  const { context } = browser();
  let location;
  context.window.location = { assign: value => { location = value; } };
  context.fetch = async () => ({ status: 401 });
  await assert.rejects(context.api('GET', '/api/private'), /Authentication required/);
  assert.equal(location, '/');
  context.fetch = async () => ({ status: 503, ok: false, headers: { get: () => 'text/plain' }, text: async () => '' });
  await assert.rejects(context.api('GET', '/api/private'), /GET \/api\/private failed \(503\)/);
  context.fetch = async () => ({ status: 200, ok: true, headers: { get: () => null }, text: async () => '{"ok":true}' });
  assert.equal((await context.api('GET', '/api/private')).ok, true);
});

test('project names, html and ansi output are handled safely', () => {
  const { context } = browser();
  assert.equal(context.validateProjectName('good_project-1'), null);
  assert.ok(context.validateProjectName(''));
  assert.ok(context.validateProjectName('../bad'));
  assert.equal(context.escapeHtml('<a href="x">&'), '&lt;a href=&quot;x&quot;&gt;&amp;');
  assert.match(context.ansiToHtml('\x1b[31m<failure>\x1b[0m'), /color:#cc0000.*&lt;failure&gt;<\/span>/);
});

test('config and template helpers preserve user input', () => {
  const { context } = browser();
  assert.equal(context.stripProjectSection('project:\n  name: x\nparameters:\n  A: 1\n'), 'parameters:\n  A: 1');
  assert.match(context.buildFullConfigYaml('', 'cn-a, cn-b', 'example'), /name: "example"[\s\S]*- cn-a[\s\S]*- cn-b/);
  assert.equal(context.validateTemplateFormat('{"ok": true}'), null);
  assert.ok(context.validateTemplateFormat('{bad json}'));
  assert.equal(context.duration('2026-01-01T00:00:00Z', '2026-01-01T01:01:05Z'), '1h 1m');
  assert.equal(context.detectLanguage('  {"Resources":{}}'), 'json');
  assert.equal(context.detectLanguage(' [1, 2]'), 'json');
  assert.equal(context.detectLanguage('Resources: {}'), 'yaml');
  assert.equal(context.detectLanguage(null), 'yaml');
});

test('HCL grammar registers Terraform aliases and tokens', () => {
  let grammar;
  const hljs = { COMMENT: (start, end) => ({ start, end }), C_NUMBER_MODE: {}, BACKSLASH_ESCAPE: {},
    registerLanguage(name, factory) { assert.equal(name, 'hcl'); grammar = factory(this); } };
  const context = vm.createContext({ hljs });
  load('hcl.js', context);
  assert.deepEqual(Array.from(grammar.aliases), ['terraform', 'tf']);
  assert.match(grammar.keywords.keyword, /resource/);
  assert.ok(grammar.contains.some(item => item.className === 'attr'));
});

test('language selection and error descriptions handle missing values and fallbacks', () => {
  const { context } = browser('zh-CN');
  assert.equal(context.translateStatusReason(''), '');
  assert.equal(context.extractErrorMessage(null), '');
  assert.match(context.extractErrorMessage('ResultReason: StackValidationFailed\ncode: 403'), /资源栈校验失败/);
  assert.equal(context.extractErrorMessage('  Resource DELETE failed: ResourceNotFound  '), '资源不存在');
  context.setLang('unsupported');
  assert.equal(context.t('missing.translation'), 'missing.translation');
  assert.equal(context.t('versionLabel', { ver: 3 }), 'v3');
  assert.equal(context.tStackStatus('UNKNOWN_STATUS'), 'UNKNOWN_STATUS');
  assert.equal(context.translateStatusReason('Property error'), 'Property error');
});

test('time and region helpers handle empty values and localized names', () => {
  const { context } = browser();
  assert.equal(context.formatTime(''), '-');
  assert.equal(context.formatTime('bad date'), 'bad date');
  assert.equal(context.duration('', ''), '-');
  assert.equal(context.duration('2026-01-01T00:00:10Z', '2026-01-01T00:00:00Z'), '0s');
  assert.equal(context.duration('2026-01-01T00:00:00Z', '2026-01-01T00:01:03Z'), '1m 3s');
  vm.runInContext("state.regions = [{id: 'cn-a', name: 'Localized'}]", context);
  assert.equal(context.regionName(null), '-');
  assert.equal(context.regionName({}), '-');
  assert.equal(context.regionName({id: 'cn-a', name: 'Original'}), 'Localized');
  assert.equal(context.regionName({name: 'Name only'}), 'Name only');
  assert.equal(context.regionName('unknown'), 'unknown');
});
