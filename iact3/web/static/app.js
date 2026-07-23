const ROS_YAML_SKELETON = `ROSTemplateFormatVersion: '2015-09-01'
Parameters: {}
Resources: {}
Outputs: {}
`;

const ROS_JSON_SKELETON = `{
  "ROSTemplateFormatVersion": "2015-09-01",
  "Parameters": {},
  "Resources": {},
  "Outputs": {}
}`;

const ROS_EXAMPLE_TEMPLATE = `ROSTemplateFormatVersion: '2015-09-01'
Parameters:
  ZoneId:
    Type: String
Resources:
  Vpc:
    Type: ALIYUN::ECS::VPC
    Properties:
      CidrBlock: 192.168.0.0/16
  VSwitch:
    Type: ALIYUN::ECS::VSwitch
    Properties:
      VpcId:
        Ref: Vpc
      ZoneId:
        Ref: ZoneId
      CidrBlock: 192.168.0.0/24
Outputs:
  VpcId:
    Value:
      Ref: Vpc
  VSwitchId:
    Value:
      Ref: VSwitch`;

const ROS_EXAMPLE_CONFIG = `parameters:
  ZoneId: cn-hangzhou-a`;

const TF_EXAMPLE_FILES = {
    'main.tf': `resource "alicloud_vpc" "demo" {
  vpc_name   = "demo-vpc"
  cidr_block = "192.168.0.0/16"
}

resource "alicloud_vswitch" "demo" {
  vpc_id     = alicloud_vpc.demo.id
  cidr_block = "192.168.0.0/24"
  zone_id    = var.zone_id
}`,
    'variables.tf': `variable "zone_id" {
  type    = string
  default = "cn-hangzhou-a"
}`
};

const TF_EXAMPLE_CONFIG = `# No parameters required`;

const DEFAULT_NEW_PROJECT_CONFIG = `parameters: {}`;

// Helper: Extract parameters section from full YAML config
// Returns only the "parameters:" portion or full content if already simplified
function extractParametersYaml(fullConfig) {
    if (!fullConfig) return '';
    const trimmed = fullConfig.trim();
    // If already starts with "parameters:", it's simplified format
    if (trimmed.startsWith('parameters:') || trimmed.startsWith('#')) {
        return stripProjectSection(fullConfig);
    }
    // Try to parse and extract
    try {
        const parsed = typeof jsyaml !== 'undefined' ? jsyaml.load(fullConfig) : null;
        if (!parsed) return stripProjectSection(fullConfig);
        // Check if it has tests section
        if (parsed.tests && parsed.tests.default && parsed.tests.default.parameters) {
            const params = parsed.tests.default.parameters;
            if (typeof jsyaml !== 'undefined') {
                return jsyaml.dump({ parameters: params }, { lineWidth: -1, noRefs: true });
            }
        } else if (parsed.parameters) {
            if (typeof jsyaml !== 'undefined') {
                return jsyaml.dump({ parameters: parsed.parameters }, { lineWidth: -1, noRefs: true });
            }
        }
    } catch (e) {
        // Fallback: search for "parameters:" section manually
    }
    return stripProjectSection(fullConfig);
}

// Remove the `project:` top-level section from config YAML so the parameter
// editor only shows actual parameters, not internal bookkeeping fields.
function stripProjectSection(yaml) {
    if (!yaml) return '';
    const lines = yaml.split('\n');
    const result = [];
    let inProject = false;
    for (const line of lines) {
        if (/^project\s*:/.test(line)) {
            inProject = true;
            continue;
        }
        if (inProject) {
            const trimmed = line.trim();
            // End of project block: non-indented non-empty line (or document separator)
            if (trimmed && !line.startsWith(' ') && !line.startsWith('\t') && trimmed !== '---') {
                inProject = false;
            } else {
                continue; // skip indented lines under project:
            }
        }
        result.push(line);
    }
    // Trim trailing blank lines left by removal
    while (result.length && !result[result.length - 1].trim()) result.pop();
    return result.join('\n');
}

// Helper: Build full config YAML from parameters + current regions + optional project name
// Handles both simplified parameters format and already-full YAML
function buildFullConfigYaml(paramsYaml, regions, projectName) {
    if (!paramsYaml || !paramsYaml.trim() || paramsYaml.trim().startsWith('#')) {
        // No parameters, build minimal config
        const lines = [];
        if (projectName) lines.push('project:', '  name: ' + JSON.stringify(projectName));
        if (regions) {
            lines.push('tests:', '  default:', '    regions:');
            regions.split(',').forEach(r => { if (r.trim()) lines.push('      - ' + r.trim()); });
        }
        return lines.join('\n') + '\n';
    }
    
    try {
        const parsed = typeof jsyaml !== 'undefined' ? jsyaml.load(paramsYaml) : null;
        if (!parsed) return paramsYaml;
        
        // If it already has tests section, it's full YAML - return as-is (possibly updating regions)
        if (parsed.tests && typeof parsed.tests === 'object') {
            const result = { ...parsed };
            if (projectName && !result.project) result.project = { name: projectName };
            // Update regions: set to selected list, or clear if none selected
            if (result.tests && result.tests.default) {
                result.tests.default.regions = regions
                    ? regions.split(',').map(r => r.trim()).filter(Boolean)
                    : [];
            }
            if (typeof jsyaml !== 'undefined') {
                return jsyaml.dump(result, { lineWidth: -1, noRefs: true });
            }
            return paramsYaml;
        }
        
        // Simplified parameters format - build full structure
        const result = { tests: { default: { regions: [] } } };
        if (projectName) result.project = { name: projectName };
        
        if (regions) {
            regions.split(',').forEach(r => { if (r.trim()) result.tests.default.regions.push(r.trim()); });
        }
        
        // If it has "parameters:" key, use its value
        if (parsed.parameters !== undefined) {
            result.tests.default.parameters = parsed.parameters;
        } else {
            // Assume it's the params map itself
            result.tests.default.parameters = parsed;
        }
        
        if (typeof jsyaml !== 'undefined') {
            return jsyaml.dump(result, { lineWidth: -1, noRefs: true });
        }
    } catch (e) {
        // Fallback: just append tests section
    }
    return paramsYaml;
}

// Custom schema so ROS shorthand intrinsic functions (!Ref, !GetAtt, !Select,
// !Join, !Sub, etc.) are parsed into the same { Fn::XXX: value } / { Ref: value }
// object as the full function syntax. Dumping round-trips back to shorthand form.

function _makeRosScalarType(tag, fnName) {
    return new jsyaml.Type(tag, {
        kind: 'scalar',
        construct: function (data) { var o = {}; o[fnName] = data; return o; },
        predicate: function (obj) {
            return obj && typeof obj === 'object' &&
                   Object.keys(obj).length === 1 && fnName in obj &&
                   !Array.isArray(obj[fnName]);
        },
        represent: function (obj) { return obj[fnName]; }
    });
}

function _makeRosSequenceType(tag, fnName) {
    return new jsyaml.Type(tag, {
        kind: 'sequence',
        construct: function (data) { var o = {}; o[fnName] = data; return o; },
        predicate: function (obj) {
            return obj && typeof obj === 'object' &&
                   Object.keys(obj).length === 1 && fnName in obj && Array.isArray(obj[fnName]);
        },
        represent: function (obj) { return obj[fnName]; }
    });
}

var ROS_TYPES = (typeof jsyaml !== 'undefined') ? [
    _makeRosScalarType('!Ref', 'Ref'),
    _makeRosScalarType('!GetAtt', 'Fn::GetAtt'),
    _makeRosScalarType('!Base64', 'Fn::Base64'),
    _makeRosScalarType('!Sub', 'Fn::Sub'),
    _makeRosScalarType('!GetAZs', 'Fn::GetAZs'),
    _makeRosSequenceType('!Select', 'Fn::Select'),
    _makeRosSequenceType('!Join', 'Fn::Join'),
    _makeRosSequenceType('!Split', 'Fn::Split'),
    _makeRosSequenceType('!FindInMap', 'Fn::FindInMap'),
    _makeRosSequenceType('!Equals', 'Fn::Equals'),
    _makeRosSequenceType('!If', 'Fn::If'),
    _makeRosSequenceType('!Not', 'Fn::Not'),
    _makeRosSequenceType('!And', 'Fn::And'),
    _makeRosSequenceType('!Or', 'Fn::Or'),
] : null;

const ROS_SCHEMA = (typeof jsyaml !== 'undefined' && ROS_TYPES) ?
    jsyaml.DEFAULT_SCHEMA.extend(ROS_TYPES) : null;

const state = {
    page: 'playground',
    regions: [],
    settings: {},
    samples: [],
    projects: [],
    projectTotal: 0,
    projectPage: 1,
    projectPerPage: 12,
    projectSearch: '',
    selectedProjects: new Set(),
    tasks: [],
    taskTotal: 0,
    taskPage: 1,
    taskPerPage: 10,
    taskSearch: '',
    taskStatusFilter: '',
    taskRequestId: 0,
    taskStatusSelect: null,
    selectedTasks: new Set(),
    currentRunId: null,
    currentRun: null,
    currentProjectName: null,
    currentProject: null,
    currentProjectRuns: [],
    runHistoryPage: 1,
    runHistoryPerPage: 10,
    projectEditConfig: '',
    projectEditTfMode: false,
    projectEditTfFiles: {},
    projectEditTfActiveFile: null,
    projectEditNoDelete: false,
    projectEditKeepFailed: false,
    projectEditDontWait: false,
    taskTimer: null,
    pgRegionSelect: null,
    pdRegionSelect: null,  // Region select for project detail page
    taskStatusMap: {},
    tfFiles: {},      // {path: content} for Terraform directory mode (paths may contain '/')
    tfActiveFile: null,
    tfOpenFiles: [],  // list of currently open file paths
    tfExpandedDirs: new Set(), // expanded directory paths in the tree
    _tfInlinePrompt: null,       // active inline prompt popover
    tfMode: false,
    templateTab: 'ros',       // 'ros' | 'terraform'
    templateFormat: 'yaml',   // 'yaml' | 'json' (only for ROS)
    currentAction: 'run',     // 'policy' | 'cost' | 'run'
    actionResults: { policy: null, cost: null, run: null },
    _hasActionOutput: false,  // flag to avoid DOM queries on every keystroke in clearAllActionOutputs
    runActiveTab: 'detail',
    pdTemplateFormat: 'yaml',  // 'yaml' | 'json' (project detail template tab)
    _pdTemplateRaw: '',        // raw template content for format switching
};

const el = (id) => document.getElementById(id);
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// Clipboard helper with fallback for non-secure contexts (HTTP without localhost)
async function copyToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
    } else {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        ta.style.top = '-9999px';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        try {
            document.execCommand('copy');
        } finally {
            document.body.removeChild(ta);
        }
    }
}

// --- Token authentication helpers ---
// When the server is started with --token, every API request must include
// an Authorization: Bearer header.  The token is stored in localStorage
// after the user enters it via a prompt.  Output URLs (/outputs/) use a
// ?token= query parameter since browser navigation cannot set headers.

function getApiToken() {
    return localStorage.getItem('iact3_api_token') || '';
}

function setApiToken(token) {
    if (token) {
        localStorage.setItem('iact3_api_token', token);
    } else {
        localStorage.removeItem('iact3_api_token');
    }
}

function authUrl(url) {
    // Append token query parameter to /outputs/ URLs for direct navigation.
    const token = getApiToken();
    if (!token || !url || !url.startsWith('/outputs/')) return url;
    const sep = url.includes('?') ? '&' : '?';
    return `${url}${sep}token=${encodeURIComponent(token)}`;
}

async function _promptForToken() {
    return new Promise((resolve) => {
        const modal = document.createElement('div');
        modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:99999';
        const box = document.createElement('div');
        box.style.cssText = 'background:#fff;padding:24px;border-radius:8px;max-width:400px;box-shadow:0 2px 12px rgba(0,0,0,0.2)';
        box.innerHTML = `
            <h3 style="margin:0 0 12px;font-size:16px;color:#333">Authentication Required</h3>
            <p style="margin:0 0 12px;font-size:13px;color:#666">This server requires a bearer token. Please enter it below:</p>
            <input type="password" id="iact3_token_input" style="width:100%;padding:8px;border:1px solid #ddd;border-radius:4px;box-sizing:border-box;margin-bottom:12px" placeholder="Bearer token">
            <div style="display:flex;gap:8px;justify-content:flex-end">
                <button id="iact3_token_cancel" style="padding:6px 16px;border:1px solid #ddd;border-radius:4px;cursor:pointer;background:#fff">Cancel</button>
                <button id="iact3_token_ok" style="padding:6px 16px;border:none;border-radius:4px;cursor:pointer;background:#1890ff;color:#fff">OK</button>
            </div>`;
        modal.appendChild(box);
        document.body.appendChild(modal);
        const input = box.querySelector('#iact3_token_input');
        input.focus();
        box.querySelector('#iact3_token_ok').onclick = () => {
            const val = input.value.trim();
            document.body.removeChild(modal);
            resolve(val);
        };
        box.querySelector('#iact3_token_cancel').onclick = () => {
            document.body.removeChild(modal);
            resolve('');
        };
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') box.querySelector('#iact3_token_ok').click();
            if (e.key === 'Escape') box.querySelector('#iact3_token_cancel').click();
        });
    });
}

async function api(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }
    // Attach bearer token if one is stored
    const token = getApiToken();
    if (token) {
        opts.headers['Authorization'] = `Bearer ${token}`;
    }
    let res = await fetch(path, opts);
    // If 401 and we have no token (or token is wrong), prompt and retry once
    if (res.status === 401) {
        const newToken = await _promptForToken();
        if (newToken) {
            setApiToken(newToken);
            opts.headers['Authorization'] = `Bearer ${newToken}`;
            res = await fetch(path, opts);
        }
    }
    const text = await res.text();
    const contentType = res.headers.get('Content-Type') || '';
    if (contentType.includes('text/plain')) {
        if (!res.ok) throw new Error(text || `${method} ${path} failed (${res.status})`);
        return text;
    }
    let data = {};
    try { data = JSON.parse(text); } catch { data = { raw: text }; }
    if (!res.ok) {
        const msg = data.error || data.message || `${method} ${path} failed (${res.status})`;
        const err = new Error(msg);
        err.data = data;
        throw err;
    }
    return data;
}

function escapeHtml(s) {
    if (!s) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// ANSI escape code → HTML converter for terminal-style log rendering
function ansiToHtml(text) {
    if (!text) return '';
    const fgColors = {
        30: '#000000', 31: '#cc0000', 32: '#4e9a06', 33: '#c4a000',
        34: '#3465a4', 35: '#75507b', 36: '#06989a', 37: '#d3d7cf'
    };
    const bgColors = {
        40: '#000000', 41: '#cc0000', 42: '#4e9a06', 43: '#c4a000',
        44: '#3465a4', 45: '#75507b', 46: '#06989a', 47: '#d3d7cf'
    };
    let result = '';
    let currentFg = '';
    let currentBg = '';
    let bold = false;
    let inSpan = false;
    const ansiRegex = /\x1b\[([\d;]*)m/g;
    let lastIndex = 0;
    let match;
    while ((match = ansiRegex.exec(text)) !== null) {
        result += escapeHtml(text.substring(lastIndex, match.index));
        lastIndex = match.index + match[0].length;
        const codes = match[1].split(';').filter(c => c !== '').map(c => parseInt(c));
        if (codes.length === 0) codes.push(0); // \x1b[m means reset
        for (const code of codes) {
            if (code === 0) {
                if (inSpan) { result += '</span>'; inSpan = false; }
                currentFg = '';
                currentBg = '';
                bold = false;
            } else if (code === 1) {
                bold = true;
            } else if (fgColors[code]) {
                currentFg = fgColors[code];
            } else if (bgColors[code]) {
                currentBg = bgColors[code];
            }
        }
        if (currentFg || currentBg || bold) {
            if (inSpan) { result += '</span>'; }
            const styles = [];
            if (currentFg) styles.push(`color:${currentFg}`);
            if (currentBg) styles.push(`background:${currentBg}`);
            if (bold) styles.push('font-weight:bold');
            result += `<span style="${styles.join(';')}">`;
            inSpan = true;
        }
    }
    result += escapeHtml(text.substring(lastIndex));
    if (inSpan) result += '</span>';
    return result;
}

// Project name validation: max 255 chars, must start with a letter,
// may contain only letters, digits, hyphens (-), and underscores (_).
const PROJECT_NAME_RE = /^[A-Za-z][A-Za-z0-9_-]{0,254}$/;
function validateProjectName(name) {
    if (!name) return t('projectNameRequired');
    if (!PROJECT_NAME_RE.test(name)) return t('projectNameInvalid');
    return null;
}

// Bind real-time project-name validation to an input element.
// Shows a red border and visible error hint below the input while invalid.
function bindProjectNameLive(inputEl, saveBtnEl) {
    const hintEl = inputEl.parentElement ? inputEl.parentElement.querySelector('.project-edit-name-hint') : null;
    const onInput = () => {
        const val = inputEl.value.trim();
        if (!val) {
            // Empty: remove invalid styling (required check is deferred to save time)
            inputEl.classList.remove('input-invalid');
            inputEl.title = '';
            if (hintEl) { hintEl.textContent = ''; hintEl.classList.remove('visible'); }
            if (saveBtnEl) saveBtnEl.disabled = false;
            return;
        }
        const err = validateProjectName(val);
        inputEl.classList.toggle('input-invalid', !!err);
        inputEl.title = err || '';
        if (hintEl) {
            hintEl.textContent = err || '';
            hintEl.classList.toggle('visible', !!err);
        }
        if (saveBtnEl) saveBtnEl.disabled = !!err;
    };
    inputEl.addEventListener('input', onInput);
}

// Validate template content and show format hint
function validateTemplateFormat(content) {
    if (!content || !content.trim()) return null;
    const trimmed = content.trim();
    // Try JSON first
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
        try {
            JSON.parse(trimmed);
            return null; // Valid JSON
        } catch (e) {
            return t('templateFormatJsonError') + ': ' + e.message;
        }
    }
    // Try YAML (with ROS schema for intrinsic functions)
    if (typeof jsyaml !== 'undefined') {
        try {
            const schema = ROS_SCHEMA || jsyaml.DEFAULT_SCHEMA;
            jsyaml.load(trimmed, { schema });
            return null; // Valid YAML
        } catch (e) {
            return t('templateFormatYamlError') + ': ' + e.message;
        }
    }
    return null;
}

function bindTemplateFormatLive(textareaEl, hintEl) {
    if (!textareaEl || !hintEl) return;
    let debounceTimer = null;
    const onInput = () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            const err = validateTemplateFormat(textareaEl.value);
            hintEl.textContent = err || '';
            hintEl.classList.toggle('visible', !!err);
            textareaEl.classList.toggle('input-invalid', !!err);
        }, 500);
    };
    textareaEl.addEventListener('input', onInput);
}

function formatTime(iso) {
    if (!iso) return '-';
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleString();
}

function duration(startIso, endIso) {
    if (!startIso) return '-';
    const start = new Date(startIso).getTime();
    const end = endIso ? new Date(endIso).getTime() : Date.now();
    const secs = Math.max(0, Math.round((end - start) / 1000));
    if (secs < 60) return `${secs}s`;
    const m = Math.floor(secs / 60), s = secs % 60;
    if (m < 60) return `${m}m ${s}s`;
    const h = Math.floor(m / 60), rm = m % 60;
    return `${h}h ${rm}m`;
}

function regionName(id) {
    if (!id) return '-';
    // Normalize: if region is an object (dict), extract the string ID
    const regionId = typeof id === 'object' ? (id.id || '') : id;
    const regionDisplayName = typeof id === 'object' ? (id.name || '') : '';
    if (!regionId && !regionDisplayName) return '-';
    // Always look up in state.regions first for localized name
    const r = (state.regions || []).find(r => r.id === regionId);
    if (r?.name) return r.name;
    // Fall back to dict's name, then raw ID
    return regionDisplayName || regionId || '-';
}

function toast(msg, type = 'info') {
    const t = el('toast');
    t.textContent = msg;
    t.className = `toast ${type} show`;
    setTimeout(() => t.classList.remove('show'), 3000);
}

function setBtnLoading(btn, loading) {
    if (!btn) return;
    if (loading) {
        if (!btn.dataset.originalText) btn.dataset.originalText = btn.textContent;
        const rect = btn.getBoundingClientRect();
        btn.style.minWidth = `${rect.width}px`;
        btn.disabled = true;
        btn.classList.add('btn-loading');
        btn.innerHTML = `<span class="btn-spinner"></span><span>${escapeHtml(btn.dataset.originalText)}</span>`;
    } else {
        btn.classList.remove('btn-loading');
        btn.disabled = false;
        btn.style.minWidth = '';
        if (btn.dataset.originalText) {
            btn.textContent = btn.dataset.originalText;
            btn.dataset.originalText = '';
        }
    }
}

function consoleLog(msg, { type = 'info', action = '', level = null, raw = false } = {}) {
    const actionKey = action || state.currentAction || 'run';
    const body = el(`log-${actionKey}`);
    if (!body) return;
    const text = String(msg);
    const now = new Date();
    const date = now.toISOString().replace('T', ' ').slice(0, 23);
    const lvl = level || (type === 'error' ? 'ERROR' : type === 'success' ? 'INFO' : type === 'warn' ? 'WARN' : 'INFO');

    // Trim leading/trailing whitespace and blank lines so the log output sits
    // flush against the top of the panel without extra vertical gaps.
    const trimmedText = text.trim();
    if (!trimmedText) return;

    if (raw) {
        // Terminal-style output with colorized log levels + ANSI support
        let termOutput = body.querySelector('.terminal-output');
        if (!termOutput) {
            termOutput = document.createElement('div');
            termOutput.className = 'terminal-output';
            termOutput.innerHTML = `<div class="terminal-header">
                <span class="terminal-dot terminal-dot-red"></span>
                <span class="terminal-dot terminal-dot-yellow"></span>
                <span class="terminal-dot terminal-dot-green"></span>
                <span class="terminal-title">iact3 — CLI</span>
            </div>
            <pre class="terminal-body"></pre>`;
            body.innerHTML = '';
            body.appendChild(termOutput);
        }
        const termBody = termOutput.querySelector('.terminal-body');
        trimmedText.split('\n').forEach((lineText) => {
            if (!lineText.trim()) return;
            // Parse: timestamp [LEVEL] : message
            const m = lineText.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+)\s*\[\s*(\w+)\s*\]\s*:\s*(.*)$/);
            let lineHtml;
            if (m) {
                const ts = escapeHtml(m[1]);
                const parsedLevel = m[2].trim();
                const msg = ansiToHtml(m[3]);
                const levelClass = parsedLevel === 'ERROR' ? 'term-error' : parsedLevel === 'WARNING' ? 'term-warning' : parsedLevel === 'INFO' ? 'term-info' : 'term-debug';
                lineHtml = `<span class="term-ts">${ts}</span> <span class="term-level ${levelClass}">[${escapeHtml(parsedLevel)}]</span> <span class="term-msg">${msg}</span>`;
            } else {
                lineHtml = ansiToHtml(lineText);
            }
            termBody.insertAdjacentHTML('beforeend', lineHtml + '\n');
        });
        termBody.scrollTop = termBody.scrollHeight;
    } else {
        // Render each logical log message as a card with copy/expand buttons so multi-line
        // output (validate / policy / run summaries) is easy to read, copy, and navigate.
        const entry = document.createElement('div');
        entry.className = 'log-entry';

        const header = document.createElement('div');
        header.className = 'log-entry-header';
        header.innerHTML = `<span class="log-entry-time">${date}</span> <span class="log-entry-level log-level-${lvl.toLowerCase()}">${lvl}</span>${action ? ` <span class="log-entry-action">[${escapeHtml(action)}]</span>` : ''}`;
        entry.appendChild(header);

        const content = document.createElement('pre');
        content.className = 'log-entry-content';
        content.textContent = trimmedText;
        entry.appendChild(content);

        const actions = document.createElement('div');
        actions.className = 'log-entry-actions';
        header.appendChild(actions);

        const copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'log-entry-copy';
        copyBtn.textContent = t('copyBtn') || 'Copy';
        copyBtn.addEventListener('click', async (e) => {
            e.stopPropagation();
            try {
                await copyToClipboard(text);
                toast(t('copied') || 'Copied', 'success');
            } catch (e) {
                toast(t('copyFailed') || 'Copy failed', 'error');
            }
        });
        actions.appendChild(copyBtn);

        // Long log entries are collapsed by default with an expand toggle.
        const MAX_COLLAPSED_LINES = 20;
        const lineCount = trimmedText.split('\n').length;
        if (lineCount > MAX_COLLAPSED_LINES) {
            content.classList.add('collapsed');
            const toggleBtn = document.createElement('button');
            toggleBtn.type = 'button';
            toggleBtn.className = 'log-entry-toggle';
            toggleBtn.textContent = t('expandBtn') || 'Expand';
            toggleBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const isCollapsed = content.classList.toggle('collapsed');
                toggleBtn.textContent = isCollapsed ? (t('expandBtn') || 'Expand') : (t('collapseBtn') || 'Collapse');
            });
            actions.insertBefore(toggleBtn, copyBtn);
        }

        const color = type === 'error' ? '#b91c1c' : type === 'success' ? '#15803d' : type === 'warn' ? '#b45309' : '';
        if (color) {
            entry.style.borderLeftColor = color;
            content.style.color = color;
        }

        body.appendChild(entry);
    }
    body.scrollTop = body.scrollHeight;
    state._hasActionOutput = true;
    updateActionTabs();
}

function formatCliOutput(data, opts = {}) {
    const { indent = 0, visited = new WeakSet() } = opts;
    const pad = '  '.repeat(indent);
    if (data === null || data === undefined) return `${pad}<null>`;
    if (typeof data !== 'object') return `${pad}${String(data)}`;
    if (visited.has(data)) return `${pad}<circular>`;
    visited.add(data);
    if (Array.isArray(data)) {
        return data.map((item, i) => formatCliOutput(item, { indent: indent + 1, visited })).join('\n') || `${pad}<empty list>`;
    }
    const lines = [];
    for (const [key, value] of Object.entries(data)) {
        if (value === null || value === undefined) {
            lines.push(`${pad}${key}: <null>`);
        } else if (typeof value === 'object') {
            lines.push(`${pad}${key}:`);
            lines.push(formatCliOutput(value, { indent: indent + 1, visited }));
        } else {
            lines.push(`${pad}${key}: ${String(value)}`);
        }
    }
    visited.delete(data);
    return lines.join('\n') || `${pad}<empty>`;
}

function consoleClear() {
    const actionKey = state.currentAction;
    if (actionKey) {
        const logBody = el(`log-${actionKey}`);
        if (logBody) logBody.innerHTML = '';
    } else {
        ['policy', 'cost', 'run'].forEach(a => {
            const logBody = el(`log-${a}`);
            if (logBody) logBody.innerHTML = '';
        });
    }
}

/* ============== Credentials Check ============== */
function ensureCredentials() {
    const s = state.settings || {};
    if (s.source && s.source !== 'none') return true;
    // No credentials detected: show a modal with instructions
    showCredentialMissingModal();
    return false;
}

function showCredentialMissingModal() {
    const modal = el('confirm-modal');
    const icon = el('confirm-modal-icon');
    const titleEl = el('confirm-modal-title');
    const msgEl = el('confirm-modal-message');
    const warnEl = el('confirm-modal-warning');
    const verifyEl = el('confirm-modal-verify');
    const verifyHintEl = el('confirm-modal-verify-hint');
    const okBtn = el('confirm-modal-ok');
    const cancelBtn = el('confirm-modal-cancel');

    if (icon) { icon.className = 'confirm-modal-icon icon-danger'; icon.textContent = ''; }
    if (titleEl) titleEl.textContent = t('credentialMissingTitle');
    if (msgEl) msgEl.innerHTML = t('credentialMissingMessage');
    if (warnEl) warnEl.classList.add('hidden');
    if (verifyEl) verifyEl.classList.add('hidden');
    if (verifyHintEl) verifyHintEl.classList.add('hidden');
    if (okBtn) { okBtn.textContent = t('closeBtn') || 'Close'; okBtn.className = 'btn btn-primary'; okBtn.disabled = false; okBtn.style.display = ''; }
    if (cancelBtn) cancelBtn.style.display = 'none';

    const onClose = () => {
        modal.classList.remove('open');
        okBtn.removeEventListener('click', onClose);
        modal.removeEventListener('click', onBackdrop);
    };
    const onBackdrop = (e) => { if (e.target === modal) onClose(); };

    okBtn.addEventListener('click', onClose);
    modal.addEventListener('click', onBackdrop);
    modal.classList.add('open');
}

/* ============== Confirm Dialog ============== */
function showConfirm(message, { danger = false, okText = null, cancelText = null, title = null, warning = null, verify = null } = {}) {
    return new Promise((resolve) => {
        const modal = el('confirm-modal');
        const icon = el('confirm-modal-icon');
        const titleEl = el('confirm-modal-title');
        const msgEl = el('confirm-modal-message');
        const warnEl = el('confirm-modal-warning');
        const verifyEl = el('confirm-modal-verify');
        const verifyHintEl = el('confirm-modal-verify-hint');
        const verifyInput = el('confirm-modal-verify-input');
        const btnOk = el('confirm-modal-ok');
        const btnCancel = el('confirm-modal-cancel');

        msgEl.textContent = message;
        if (title) {
            titleEl.textContent = title;
            titleEl.classList.remove('hidden');
        } else {
            titleEl.classList.add('hidden');
        }
        if (warning) {
            warnEl.textContent = warning;
            warnEl.classList.remove('hidden');
        } else {
            warnEl.classList.add('hidden');
        }

        let onVerifyInput = null;
        let onVerifyKeydown = null;
        if (verify && verify.expected) {
            verifyHintEl.textContent = verify.hint || '';
            verifyInput.value = '';
            verifyInput.placeholder = verify.placeholder || '';
            verifyEl.classList.remove('hidden');
            setTimeout(() => verifyInput.focus(), 50);
            onVerifyInput = () => {
                btnOk.disabled = verifyInput.value.trim() !== verify.expected;
            };
            onVerifyKeydown = (e) => {
                if (e.key === 'Enter' && verifyInput.value.trim() === verify.expected) {
                    finish(true);
                }
            };
            verifyInput.addEventListener('input', onVerifyInput);
            verifyInput.addEventListener('keydown', onVerifyKeydown);
            btnOk.disabled = true;
        } else {
            verifyEl.classList.add('hidden');
            btnOk.disabled = false;
        }

        icon.className = 'confirm-modal-icon' + (danger ? ' icon-danger' : '');
        btnOk.className = 'btn ' + (danger ? 'btn-danger' : 'btn-primary');
        btnCancel.style.display = '';
        if (okText) btnOk.textContent = okText;
        else btnOk.textContent = t('confirmBtn');
        if (cancelText) btnCancel.textContent = cancelText;
        else btnCancel.textContent = t('cancelBtn');

        modal.classList.add('open');

        function finish(result) {
            modal.classList.remove('open');
            btnOk.removeEventListener('click', onOk);
            btnCancel.removeEventListener('click', onCancel);
            modal.removeEventListener('click', onBackdrop);
            if (onVerifyInput) verifyInput.removeEventListener('input', onVerifyInput);
            if (onVerifyKeydown) verifyInput.removeEventListener('keydown', onVerifyKeydown);
            btnOk.disabled = false;
            resolve(result);
        }
        const onOk = () => finish(true);
        const onCancel = () => finish(false);
        const onBackdrop = (e) => { if (e.target === modal) finish(false); };

        btnOk.addEventListener('click', onOk);
        btnCancel.addEventListener('click', onCancel);
        modal.addEventListener('click', onBackdrop);
    });
}

function confirmOverwrite(name) {
    return showConfirm(t('confirmOverwriteProject', { name }), {
        danger: true,
        title: t('confirmOverwriteTitle'),
        warning: t('confirmOverwriteWarning', { name }),
        okText: t('overwriteBtn'),
        verify: {
            expected: name,
            hint: t('overwriteConfirmHint', { name }),
            placeholder: t('overwriteConfirmPlaceholder'),
        },
    });
}

/* ============== Prompt Dialog ============== */
function showPrompt({ title = '', placeholder = '', defaultValue = '', okText = null, cancelText = null } = {}) {
    return new Promise((resolve) => {
        const modal = el('prompt-modal');
        const titleEl = el('prompt-modal-title');
        const input = el('prompt-modal-input');
        const btnOk = el('prompt-modal-ok');
        const btnCancel = el('prompt-modal-cancel');

        titleEl.textContent = title;
        input.placeholder = placeholder;
        input.value = defaultValue;
        if (okText) btnOk.textContent = okText;
        else btnOk.textContent = t('confirmBtn');
        if (cancelText) btnCancel.textContent = cancelText;
        else btnCancel.textContent = t('cancelBtn');

        modal.classList.add('open');
        setTimeout(() => input.focus(), 50);

        function finish(value) {
            modal.classList.remove('open');
            btnOk.removeEventListener('click', onOk);
            btnCancel.removeEventListener('click', onCancel);
            input.removeEventListener('keydown', onKeydown);
            modal.removeEventListener('click', onBackdrop);
            resolve(value);
        }
        const onOk = () => finish(input.value.trim());
        const onCancel = () => finish(null);
        const onBackdrop = (e) => { if (e.target === modal) finish(null); };
        const onKeydown = (e) => {
            if (e.key === 'Enter') finish(input.value.trim());
            if (e.key === 'Escape') finish(null);
        };

        btnOk.addEventListener('click', onOk);
        btnCancel.addEventListener('click', onCancel);
        input.addEventListener('keydown', onKeydown);
        modal.addEventListener('click', onBackdrop);
    });
}

/* ============== Inline Prompt ============== */
function showInlinePrompt({ anchorEl, title = '', placeholder = '', defaultValue = '', okText = null, cancelText = null } = {}) {
    return new Promise((resolve) => {
        closeAllTfMenus();
        const rect = anchorEl ? anchorEl.getBoundingClientRect() : { left: 0, top: 0, width: 0, height: 0 };
        const popover = document.createElement('div');
        popover.className = 'tf-prompt-popover';
        popover.innerHTML = `
            <div class="tf-prompt-title">${escapeHtml(title)}</div>
            <input type="text" class="tf-prompt-input" placeholder="${escapeHtml(placeholder)}" value="${escapeHtml(defaultValue)}">
            <div class="tf-prompt-actions">
                <button type="button" class="btn btn-sm tf-prompt-cancel">${escapeHtml(cancelText || t('cancelBtn'))}</button>
                <button type="button" class="btn btn-primary btn-sm tf-prompt-ok">${escapeHtml(okText || t('confirmBtn'))}</button>
            </div>
        `;
        popover.style.top = `${rect.bottom + window.scrollY + 2}px`;
        popover.style.left = `${rect.left + window.scrollX}px`;
        document.body.appendChild(popover);
        state._tfInlinePrompt = popover;

        const input = popover.querySelector('.tf-prompt-input');
        setTimeout(() => input.focus(), 30);

        function finish(value) {
            if (popover.parentNode) popover.parentNode.removeChild(popover);
            state._tfInlinePrompt = null;
            resolve(value);
        }

        const onOk = () => finish(input.value.trim());
        const onCancel = () => finish(null);
        const onKeydown = (e) => {
            if (e.key === 'Enter') onOk();
            if (e.key === 'Escape') onCancel();
        };

        popover.querySelector('.tf-prompt-ok').addEventListener('click', onOk);
        popover.querySelector('.tf-prompt-cancel').addEventListener('click', onCancel);
        input.addEventListener('keydown', onKeydown);

        setTimeout(() => {
            document.addEventListener('click', function onDocClick(e) {
                if (!popover.contains(e.target) && !(anchorEl && anchorEl.contains(e.target))) {
                    finish(null);
                    document.removeEventListener('click', onDocClick);
                }
            });
        }, 0);
    });
}

/* ============== Region Select ============== */
class RegionSelect {
    constructor(triggerId, dropdownId, onChange) {
        this.trigger = el(triggerId);
        this.dropdown = el(dropdownId);
        this.selected = new Set();
        this._allRegions = [];
        this.onChange = onChange || (() => {});
        this._hasDom = !!(this.trigger && this.dropdown);
        if (this.trigger) {
            this.trigger.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggle();
            });
        }
        if (this.dropdown) {
            document.addEventListener('click', () => this.close());
            this.dropdown.addEventListener('click', (e) => e.stopPropagation());
        }
    }

    setData(regions) {
        this._allRegions = regions;
        if (this.dropdown) {
            this._buildDropdown(regions);
        }
        this._renderTrigger();
    }

    _buildDropdown(regions) {
        this.dropdown.innerHTML = '';

        // Toolbar: search + select all + clear all
        const toolbar = document.createElement('div');
        toolbar.className = 'region-toolbar';
        toolbar.innerHTML = `
            <input type="text" class="region-search" placeholder="${t('searchRegion')}" autocomplete="off">
            <div class="region-toolbar-actions">
                <button type="button" class="btn-text region-select-all">${t('selectAll')}</button>
                <span class="region-toolbar-sep">|</span>
                <button type="button" class="btn-text region-clear-all">${t('clearAll')}</button>
            </div>
        `;
        this.dropdown.appendChild(toolbar);

        // Options container (scrollable)
        const list = document.createElement('div');
        list.className = 'region-options-list';
        this._renderOptions(list, regions);
        this.dropdown.appendChild(list);
        this._list = list;

        // Search filter
        const searchInput = toolbar.querySelector('.region-search');
        searchInput.addEventListener('input', () => {
            const q = searchInput.value.trim().toLowerCase();
            const filtered = q
                ? this._allRegions.filter(r => r.id.toLowerCase().includes(q) || r.name.toLowerCase().includes(q))
                : this._allRegions;
            this._renderOptions(this._list, filtered);
        });
        searchInput.addEventListener('click', (e) => e.stopPropagation());

        // Select all (only visible)
        toolbar.querySelector('.region-select-all').addEventListener('click', (e) => {
            e.stopPropagation();
            const q = searchInput.value.trim().toLowerCase();
            const visible = q
                ? this._allRegions.filter(r => r.id.toLowerCase().includes(q) || r.name.toLowerCase().includes(q))
                : this._allRegions;
            visible.forEach(r => this.selected.add(r.id));
            this._renderOptions(this._list, visible);
            this._renderTrigger();
            this.onChange([...this.selected]);
        });

        // Clear all
        toolbar.querySelector('.region-clear-all').addEventListener('click', (e) => {
            e.stopPropagation();
            this.selected.clear();
            const q = searchInput.value.trim().toLowerCase();
            const visible = q
                ? this._allRegions.filter(r => r.id.toLowerCase().includes(q) || r.name.toLowerCase().includes(q))
                : this._allRegions;
            this._renderOptions(this._list, visible);
            this._renderTrigger();
            this.onChange([...this.selected]);
        });
    }

    _renderOptions(container, regions) {
        container.innerHTML = '';
        regions.forEach(r => {
            const div = document.createElement('div');
            div.className = 'region-option';
            const checked = this.selected.has(r.id);
            div.innerHTML = `<input type="checkbox" value="${r.id}"${checked ? ' checked' : ''}> <span>${escapeHtml(r.name)} <code style="color:var(--text-muted);font-size:11px">${r.id}</code></span>`;
            div.addEventListener('click', (e) => {
                if (e.target.tagName === 'INPUT') return;
                const cb = div.querySelector('input');
                cb.checked = !cb.checked;
                this._toggle(r.id, cb.checked);
            });
            div.querySelector('input').addEventListener('change', (e) => {
                this._toggle(r.id, e.target.checked);
            });
            container.appendChild(div);
        });
    }

    _toggle(id, checked) {
        if (checked) this.selected.add(id);
        else this.selected.delete(id);
        this._renderTrigger();
        this.onChange([...this.selected]);
    }

    setSelected(ids) {
        this.selected = new Set(ids);
        if (this._list) {
            this._list.querySelectorAll('input').forEach(cb => {
                cb.checked = this.selected.has(cb.value);
            });
        }
        this._renderTrigger();
    }

    getSelected() {
        return [...this.selected];
    }

    _renderTrigger() {
        if (!this.trigger) return;
        const text = this.trigger.querySelector('span');
        if (!text) return;
        if (this.selected.size === 0) {
            text.textContent = t('regionEmpty');
        } else if (this.selected.size <= 2) {
            const names = [...this.selected].map(id => {
                const r = this._allRegions.find(r => r.id === id);
                return r ? r.name : id;
            });
            text.textContent = names.join(', ');
        } else {
            text.textContent = t('regionCount', { count: this.selected.size });
        }
    }

    toggle() {
        if (!this.dropdown) return;
        const open = this.dropdown.classList.contains('open');
        if (open) {
            this.close();
        } else {
            document.querySelectorAll('.region-dropdown').forEach(d => d.classList.remove('open'));
            this.dropdown.classList.add('open');
            // Re-render toolbar texts in current language
            const sa = this.dropdown.querySelector('.region-select-all');
            const ca = this.dropdown.querySelector('.region-clear-all');
            const si = this.dropdown.querySelector('.region-search');
            if (sa) sa.textContent = t('selectAll');
            if (ca) ca.textContent = t('clearAll');
            if (si) si.placeholder = t('searchRegion');
            // Focus search
            if (si) setTimeout(() => si.focus(), 50);
        }
    }

    close() {
        if (!this.dropdown) return;
        const wasOpen = this.dropdown.classList.contains('open');
        this.dropdown.classList.remove('open');
        if (wasOpen && typeof this.onClose === 'function') {
            this.onClose();
        }
    }
}

/* ============== Custom Select (single-select) ============== */
class CustomSelect {
    constructor(containerId, onChange) {
        this.container = el(containerId);
        if (!this.container) return;
        this._items = [];
        this._value = '';
        this.onChange = onChange || (() => {});
        const trigger = this.container.querySelector('.custom-select-trigger');
        if (trigger) {
            trigger.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggle();
            });
        }
        this.container.addEventListener('click', (e) => {
            const option = e.target.closest('.custom-select-option');
            if (!option) return;
            e.stopPropagation();
            this.select(option.dataset.value);
            this.close();
        });
    }

    setData(items, selectedValue) {
        this._items = items;
        if (selectedValue !== undefined) {
            this._value = String(selectedValue);
        } else if (items.length && !this._value) {
            this._value = String(items[0].value);
        }
        this._render();
    }

    getValue() {
        return this._value;
    }

    setValue(value, silent) {
        this._value = String(value);
        this._render();
        if (!silent) this.onChange(this._value);
    }

    select(value) {
        this._value = String(value);
        this._render();
        this.onChange(this._value);
    }

    _render() {
        if (!this.container) return;
        const textEl = this.container.querySelector('.custom-select-text');
        const dropdown = this.container.querySelector('.custom-select-dropdown');
        const item = this._items.find(i => String(i.value) === this._value);
        if (textEl) textEl.textContent = item ? item.label : '';
        if (dropdown) {
            dropdown.innerHTML = this._items.map(i =>
                `<div class="custom-select-option ${String(i.value) === this._value ? 'selected' : ''}" data-value="${escapeHtml(String(i.value))}">${escapeHtml(i.label)}</div>`
            ).join('');
        }
    }

    toggle() {
        if (!this.container) return;
        const isOpen = this.container.classList.contains('open');
        closeAllCustomSelects();
        if (!isOpen) this.container.classList.add('open');
    }

    close() {
        if (!this.container) return;
        this.container.classList.remove('open');
    }
}

/* ============== Navigation ============== */
function navigate(page, params = {}) {
    state.page = page;
    if (params.runId) {
        state.currentRunId = params.runId;
        state._detailNeedsTabReset = true;
        state._stacksPage = 1;
    }
    if (params.projectName) state.currentProjectName = params.projectName;

    $$('.nav-menu a').forEach(a => a.classList.toggle('active', a.dataset.page === page));
    $$('.page').forEach(p => p.classList.toggle('active', p.id === `page-${page}`));

    if (page === 'tasks') {
        startTaskPolling();
        loadTasks();
    }
    if (page === 'projects') loadProjects();
    if (page === 'detail' && state.currentRunId) {
        startTaskPolling();
        loadDetail(state.currentRunId);
    }
    if (page === 'project-detail' && state.currentProjectName) loadProjectDetail(state.currentProjectName);
}

/* ============== Initialization ============== */
async function init() {
    state.lang = localStorage.getItem('iact3-lang') || (navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en');
    setLang(state.lang);

    state.pgRegionSelect = new RegionSelect('pg-region-trigger', 'pg-region-dropdown');

    bindNav();
    bindPlayground();
    bindCost();
    bindProjects();
    bindTasks();
    bindSettings();
    bindDetail();
    bindProjectDetail();

    window.addEventListener('iact3-lang-change', async (e) => {
        state.lang = e.detail || 'en';
        await loadRegions();
        updateRegionHint();
        if (state.taskStatusSelect) state.taskStatusSelect.setData(getTaskStatusOptions(), state.taskStatusFilter);
        populateSamples();
        if (state.pgRegionSelect) state.pgRegionSelect._renderTrigger();
        updateTfModeUI();
        renderTfFileList();
        renderTfTabs();
        renderSettings();
        if (state.actionResults.cost && Array.isArray(state.lastCostPrices)) {
            const title = t('costResultTitle') || 'Cost Estimate Result';
            const content = renderCostResultsHtml(state.lastCostPrices);
            state.actionResults.cost = { title, content, type: 'html' };
            const costContainer = el('result-cost');
            if (costContainer) costContainer.innerHTML = content;
            if (state.currentAction === 'cost') {
                showActionResult('cost', title, content, 'html');
            }
        }
        if (state.page === 'projects') {
            renderProjects();
            renderProjectPagination();
            updateProjectSelectionUI();
        }
        if (state.page === 'tasks') {
            renderTasks();
            renderTaskPagination();
            updateTaskSelectionUI();
        }
        if (state.page === 'detail' && state.currentRunId) loadDetail(state.currentRunId);
        if (state.page === 'project-detail' && state.currentProject) {
            const activeTab = $('.project-detail-tab.active', el('project-detail-tabs-bar'));
            const currentTab = activeTab ? activeTab.dataset.pdTab : 'overview';
            renderProjectDetail(state.currentProject, state.currentProjectRuns);
            switchProjectDetailTab(currentTab);
            renderPdRegionSelect();
        }
    });

    try {
        const [regionsData, samplesData] = await Promise.all([
            api('GET', `/api/regions?lang=${state.lang}`),
            api('GET', '/api/samples'),
        ]);
        state.regions = regionsData.regions || [];
        state.samples = samplesData.samples || [];
        state.pgRegionSelect.setData(state.regions);
        // Default-select cn-hangzhou
        state.pgRegionSelect.setSelected(['cn-hangzhou']);
        updateRegionHint();
        populateSamples();

        // Default to empty playground entry
        setTemplateTab('ros');
        setTemplateFormat('yaml');
        el('template-editor').value = '';
        el('config-editor').value = '';
        updateTemplateLineNumbers();
        highlightConfig();
    } catch (e) {
        toast(e.message, 'error');
    }

    await loadSettings(false);
    startTaskPolling();

    // Show the unified output panel by default on page load.
    setCurrentAction(state.currentAction);
}

async function loadRegions() {
    try {
        const data = await api('GET', `/api/regions?lang=${state.lang}`);
        state.regions = data.regions || [];
        if (state.pgRegionSelect) state.pgRegionSelect.setData(state.regions);
    } catch (e) {
        toast(e.message, 'error');
    }
}

function bindNav() {
    $$('.nav-menu a').forEach(a => {
        a.addEventListener('click', (e) => {
            e.preventDefault();
            navigate(a.dataset.page);
        });
    });
}

/* ============== Playground ============== */
function updateRegionHint() {
    const hint = el('config-region-hint');
    if (!hint) return;
    const regions = state.pgRegionSelect ? state.pgRegionSelect.getSelected() : [];
    if (regions.length > 1) {
        hint.textContent = t('multiRegionHint') || 'In multi-region mode, $[iact3-auto] parameters will be resolved per region at runtime';
        hint.style.display = 'inline';
    } else {
        hint.style.display = 'none';
    }
}

function populateSamples() {
    const sel = el('sample-select');
    sel.innerHTML = '';
    state.samples.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.id;
        opt.textContent = state.lang === 'zh' && s.zh_name ? s.zh_name : s.name;
        sel.appendChild(opt);
    });
}

async function loadSample(id) {
    try {
        const data = await api('GET', `/api/samples/${id}`);
        el('config-editor').value = extractParametersYaml(data.config || '');
        highlightConfig();
        el('sample-select').value = id;
        if (isTerraformProject(data)) {
            setTemplateTab('terraform');
            enterTfMode(data.template_files);
        } else {
            setTemplateTab('ros');
            if (state.tfMode) exitTfMode();
            const isJson = data.template && data.template.trim().startsWith('{');
            setTemplateFormat(isJson ? 'json' : 'yaml');
            el('template-editor').value = data.template || '';
            updateTemplateLineNumbers();
        }
    } catch (e) {
        toast(e.message, 'error');
    }
}

function setTemplateTab(tab) {
    state.templateTab = tab;
    state.tfMode = tab === 'terraform';
    const formatBar = el('template-format-bar');
    if (formatBar) {
        formatBar.classList.toggle('hidden', tab === 'terraform');
    }
    updateTfModeUI();
    highlightTemplate();
}

function setTemplateFormat(format) {
    if (state.templateTab !== 'ros') return;
    state.templateFormat = format;
    $$('.template-format-tabs .format-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.format === format);
    });
    highlightTemplate();
}

function loadRosExample() {
    clearAllActionOutputs();
    setTemplateTab('ros');
    setTemplateFormat('yaml');
    el('template-editor').value = ROS_EXAMPLE_TEMPLATE;
    el('config-editor').value = '';
    updateTemplateLineNumbers();
    highlightConfig();
    focusTemplateEditor();
    // Auto-generate parameters from the loaded template
    autoGenerateParams();
}

function loadTfExample() {
    clearAllActionOutputs();
    setTemplateTab('terraform');
    enterTfMode(TF_EXAMPLE_FILES);
    el('config-editor').value = '';
    updateTemplateLineNumbers();
    highlightConfig();
    focusTemplateEditor();
    // Auto-generate parameters from the loaded template
    autoGenerateParams();
}

function focusTemplateEditor() {
    // Expand the template/config editor area and collapse the output panel
    // so the user can focus on editing the loaded example.
    el('pg-body').classList.remove('collapsed');
    el('pg-output').classList.add('collapsed');
}

function getTemplateHighlightLanguage() {
    if (state.tfMode) return 'hcl';
    return state.templateFormat === 'json' ? 'json' : 'yaml';
}

function highlightEditor(textareaId, codeId, language) {
    const textarea = el(textareaId);
    const codeEl = el(codeId);
    if (!textarea || !codeEl) return;
    const text = textarea.value;
    codeEl.className = `language-${language} hljs`;
    if (typeof hljs !== 'undefined') {
        try {
            const result = hljs.highlight(text, { language, ignoreIllegal: true });
            codeEl.innerHTML = result.value;
        } catch (e) {
            codeEl.textContent = text;
        }
    } else {
        codeEl.textContent = text;
    }
    // Trailing newline: textarea shows an extra empty line, match it in <pre>
    if (text.endsWith('\n') || text === '') {
        codeEl.innerHTML += '\n';
    }
}

function highlightTemplate() {
    highlightEditor('template-editor', 'template-highlight', getTemplateHighlightLanguage());
}

function highlightConfig() {
    highlightEditor('config-editor', 'config-highlight', 'yaml');
}

function refreshEditorHighlight() {
    highlightTemplate();
    highlightConfig();
}

/* === Read-only <pre> highlighting (task detail & project detail) === */
function detectLanguage(text) {
    const trimmed = (text || '').trim();
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) return 'json';
    return 'yaml';
}

function highlightPre(preEl, text, language) {
    if (!preEl) return;
    preEl.textContent = text || '';
    preEl.className = preEl.className.replace(/\blanguage-\S+|\bhljs\b/g, '').trim();
    preEl.classList.add('hljs', `language-${language}`);
    if (typeof hljs !== 'undefined') {
        try {
            const result = hljs.highlight(text || '', { language, ignoreIllegal: true });
            preEl.innerHTML = result.value;
        } catch (e) {
            /* keep plain text */
        }
    }
    if ((text || '').endsWith('\n') || !text) {
        preEl.innerHTML += '\n';
    }
}

/* === Project Edit editor highlighting === */
function getPeTemplateLanguage() {
    const content = (el('project-edit-template')?.value || '').trim();
    if (content.startsWith('{') || content.startsWith('[')) return 'json';
    return 'yaml';
}

function highlightPeTemplate() {
    highlightEditor('project-edit-template', 'pe-template-highlight', getPeTemplateLanguage());
}

function highlightPeTf() {
    highlightEditor('project-edit-tf-template', 'pe-tf-highlight', 'hcl');
}

function highlightPeConfig() {
    highlightEditor('project-edit-config', 'pe-config-highlight', 'yaml');
}

function refreshPeHighlight() {
    highlightPeTemplate();
    highlightPeTf();
    highlightPeConfig();
}

function syncPeHighlightScroll() {
    const pairs = [
        ['project-edit-template', 'pe-template-highlight'],
        ['project-edit-tf-template', 'pe-tf-highlight'],
        ['project-edit-config', 'pe-config-highlight'],
    ];
    for (const [taId, codeId] of pairs) {
        const ta = el(taId);
        const code = el(codeId);
        if (ta && code && code.parentElement) {
            code.parentElement.scrollTop = ta.scrollTop;
            code.parentElement.scrollLeft = ta.scrollLeft;
        }
    }
}

function updateTemplateLineNumbers() {
    const textarea = el('template-editor');
    const lineNumbers = el('template-line-numbers');
    if (!textarea || !lineNumbers) return;
    const lines = textarea.value.split('\n').length;
    lineNumbers.innerHTML = Array.from({ length: lines }, (_, i) => i + 1).join('<br>');
    syncLineNumberScroll();
    highlightTemplate();
}

function syncLineNumberScroll() {
    const textarea = el('template-editor');
    const lineNumbers = el('template-line-numbers');
    if (textarea && lineNumbers) {
        lineNumbers.scrollTop = textarea.scrollTop;
    }
    // Sync template highlight layer
    const tplHl = el('template-highlight');
    if (textarea && tplHl && tplHl.parentElement) {
        tplHl.parentElement.scrollTop = textarea.scrollTop;
        tplHl.parentElement.scrollLeft = textarea.scrollLeft;
    }
    // Sync config highlight layer
    const cfgTa = el('config-editor');
    const cfgHl = el('config-highlight');
    if (cfgTa && cfgHl && cfgHl.parentElement) {
        cfgHl.parentElement.scrollTop = cfgTa.scrollTop;
        cfgHl.parentElement.scrollLeft = cfgTa.scrollLeft;
    }
}

function getRunPayload() {
    const regions = state.pgRegionSelect.getSelected().join(',');
    const payload = {
        config_content: buildFullConfigYaml(el('config-editor').value, regions),
        regions: regions,
        no_delete: false,
        keep_failed: false,
        dont_wait_for_delete: false,
    };
    if (state.tfMode) {
        // Sync current editor content back to active file before sending
        if (state.tfActiveFile && state.tfFiles.hasOwnProperty(state.tfActiveFile)) {
            state.tfFiles[state.tfActiveFile] = el('template-editor').value;
        }
        const files = {};
        for (const [p, content] of Object.entries(state.tfFiles)) {
            if (!p.endsWith('/')) files[p] = content;
        }
        payload.template_files = files;
    } else {
        payload.template_content = el('template-editor').value;
    }
    return payload;
}

function isTemplateEmpty() {
    const payload = getRunPayload();
    if (payload.template_content !== undefined) {
        return !payload.template_content.trim();
    }
    if (payload.template_files) {
        return Object.values(payload.template_files).every(c => !c.trim());
    }
    return true;
}

/* Auto-generate parameters from the current template */
async function autoGenerateParams() {
    // Expand the template/config area so the user can see the generated parameters.
    el('pg-body').classList.remove('collapsed');
    const btn = el('btn-generate-params');
    setBtnLoading(btn, true);
    try {
        // If no region is selected, default to cn-hangzhou so the backend
        // has a region context for resolving $[iact3-auto] parameters.
        if (state.pgRegionSelect && state.pgRegionSelect.getSelected().length === 0) {
            state.pgRegionSelect.setSelected(['cn-hangzhou']);
            updateRegionHint();
        }
        const payload = getRunPayload();
        if (!payload.template_content && !payload.template_files) {
            toast(t('templateEmpty') || 'Template is empty', 'error');
            return;
        }
        const res = await api('POST', '/api/generate-params', payload);
        if (res.parameters) {
            el('config-editor').value = res.parameters;
            highlightConfig();
            state._templateDirty = false;

            if (res.logs) {
                consoleLog(res.logs, { type: 'info', action: 'generate-params', level: 'INFO', raw: true });
            }

            if (res.warning) {
                toast(t('generateParamsWarning') || 'Parameters generated with warnings: some parameters could not be resolved. Please check the log for details.', 'warning');
            } else {
                toast(t('generateParamsSuccess') || 'Parameters generated successfully', 'success');
            }
        }
    } catch (e) {
        toast(e.message || (t('generateParamsFailed') || 'Failed to generate parameters'), 'error');
    } finally {
        setBtnLoading(btn, false);
        el('pg-output').classList.add('collapsed');
    }
}

/* ============== Terraform Directory Mode ============== */
function enterTfMode(files) {
    state.tfMode = true;
    state.tfFiles = { ...files };
    const names = Object.keys(state.tfFiles).filter(p => !p.endsWith('/'));
    state.tfOpenFiles = names.length ? [names[0]] : [];
    state.tfActiveFile = state.tfOpenFiles[0] || null;
    // expand all parent directories of active file
    state.tfExpandedDirs = new Set();
    expandParentDirs(state.tfActiveFile);
    el('template-editor').value = state.tfActiveFile ? state.tfFiles[state.tfActiveFile] : '';
    renderTfFileList();
    renderTfTabs();
    updateTfModeUI();
    updateTemplateLineNumbers();
}

function exitTfMode() {
    state.tfMode = false;
    state.tfFiles = {};
    state.tfActiveFile = null;
    state.tfOpenFiles = [];
    state.tfExpandedDirs = new Set();
    el('template-editor').value = '';
    renderTfFileList();
    renderTfTabs();
    updateTfModeUI();
    updateTemplateLineNumbers();
}

function expandParentDirs(path) {
    if (!path) return;
    const parts = path.split('/');
    parts.pop();
    let acc = '';
    for (const part of parts) {
        acc = acc ? `${acc}/${part}` : part;
        state.tfExpandedDirs.add(acc);
    }
}

function updateTfModeUI() {
    const pane = el('template-editor').closest('.editor-pane');
    if (state.tfMode) {
        pane.classList.add('tf-mode-active');
        el('tf-file-list').classList.remove('hidden');
        el('tf-tabs-bar').classList.remove('hidden');
    } else {
        pane.classList.remove('tf-mode-active');
        el('tf-file-list').classList.add('hidden');
        el('tf-tabs-bar').classList.add('hidden');
    }
    const policyBtn = el('btn-policy');
    if (policyBtn) {
        policyBtn.title = t('policyTooltip');
    }
    renderTemplateUploadMenu();
}

function renderTemplateUploadMenu() {
    const dropdown = el('template-upload-dropdown');
    const trigger = el('template-upload-trigger');
    if (!dropdown || !trigger) return;
    dropdown.innerHTML = '';
    if (state.templateTab === 'terraform') {
        trigger.title = t('openLocalTooltip') || 'Open local file or folder';
        trigger.dataset.i18nTitle = 'openLocalTooltip';
        // Open Local File
        const fileLabel = document.createElement('label');
        fileLabel.className = 'tf-open-item';
        fileLabel.htmlFor = 'upload-template-file';
        fileLabel.dataset.i18n = 'openLocalFile';
        fileLabel.textContent = t('openLocalFile') || 'Open Local File';
        dropdown.appendChild(fileLabel);
        // Open Local Folder
        const folderItem = document.createElement('div');
        folderItem.className = 'tf-open-item';
        folderItem.id = 'tf-open-folder-item';
        folderItem.dataset.i18n = 'openLocalFolder';
        folderItem.textContent = t('openLocalFolder') || 'Open Local Folder';
        folderItem.addEventListener('click', () => {
            el('template-upload-menu').classList.remove('open');
            el('upload-template-dir').click();
        });
        dropdown.appendChild(folderItem);
    } else {
        trigger.title = t('uploadFileTooltip') || 'Upload ROS template';
        trigger.dataset.i18nTitle = 'uploadFileTooltip';
        const label = document.createElement('label');
        label.className = 'tf-open-item';
        label.htmlFor = 'upload-template';
        label.dataset.i18n = 'uploadBtn';
        label.textContent = t('uploadBtn') || 'Upload File';
        dropdown.appendChild(label);
    }
}

function tfTreeFromPaths(paths) {
    const root = { name: '', children: [], isFolder: true };
    for (const path of paths) {
        if (path.endsWith('/')) {
            // ensure folder nodes exist
            const parts = path.slice(0, -1).split('/');
            let node = root;
            for (const part of parts) {
                let child = node.children.find(c => c.name === part && c.isFolder);
                if (!child) {
                    child = { name: part, children: [], isFolder: true, parent: node };
                    node.children.push(child);
                }
                node = child;
            }
        } else {
            const parts = path.split('/');
            const fileName = parts.pop();
            let node = root;
            for (const part of parts) {
                let child = node.children.find(c => c.name === part && c.isFolder);
                if (!child) {
                    child = { name: part, children: [], isFolder: true, parent: node };
                    node.children.push(child);
                }
                node = child;
            }
            node.children.push({ name: fileName, isFolder: false, path, parent: node, children: [] });
        }
    }
    // sort folders first, then files
    const sortNode = (n) => {
        if (!Array.isArray(n.children)) return;
        n.children.sort((a, b) => {
            if (a.isFolder && !b.isFolder) return -1;
            if (!a.isFolder && b.isFolder) return 1;
            return a.name.localeCompare(b.name);
        });
        n.children.forEach(sortNode);
    };
    sortNode(root);
    return root;
}

function nodePath(node) {
    const parts = [];
    let n = node;
    while (n && n.name) {
        parts.unshift(n.name);
        n = n.parent;
    }
    return parts.join('/');
}

function renderTfFileList() {
    const treeEl = el('tf-file-tree');
    if (!state.tfMode) {
        treeEl.innerHTML = '';
        return;
    }
    const paths = Object.keys(state.tfFiles);
    if (!paths.length) {
        treeEl.innerHTML = `<div class="tf-empty">${escapeHtml(t('tfEmptyFiles'))}</div>`;
        return;
    }
    try {
        const root = tfTreeFromPaths(paths);
        treeEl.innerHTML = renderTfTreeNode(root, 0, true);
        bindTfTreeEvents(treeEl);
    } catch (e) {
        console.error('renderTfFileList error:', e);
        treeEl.innerHTML = `<div class="tf-empty">${escapeHtml(t('tfEmptyFiles'))}</div>`;
    }
}

function renderTfTreeNode(node, depth, isRoot) {
    if (isRoot) {
        return node.children.map(c => renderTfTreeNode(c, depth, false)).join('');
    }
    const path = nodePath(node);
    const isExpanded = node.isFolder && state.tfExpandedDirs.has(path);
    const isActive = !node.isFolder && state.tfActiveFile === path;
    const px = 10 + depth * 14;
    if (node.isFolder) {
        const childrenHtml = isExpanded
            ? node.children.map(c => renderTfTreeNode(c, depth + 1, false)).join('')
            : '';
        return `
            <div class="tf-tree-node folder ${isExpanded ? 'expanded' : 'collapsed'}" data-path="${escapeHtml(path)}" data-type="folder" style="--depth-px:${px}px">
                <span class="tf-tree-icon chevron">▶</span>
                <span class="tf-tree-icon">📁</span>
                <span class="tf-tree-name">${escapeHtml(node.name)}</span>
                <div class="tf-tree-actions">
                    <button class="tf-tree-action tf-node-more" data-path="${escapeHtml(path)}" data-type="folder" title="${escapeHtml(t('moreActions') || 'Actions')}">⋮</button>
                </div>
            </div>
            ${childrenHtml}`;
    }
    return `
        <div class="tf-tree-node ${isActive ? 'active' : ''}" data-path="${escapeHtml(path)}" data-type="file" style="--depth-px:${px}px">
            <span class="tf-tree-icon" style="visibility:hidden">▶</span>
            <span class="tf-tree-icon">📄</span>
            <span class="tf-tree-name">${escapeHtml(node.name)}</span>
            <div class="tf-tree-actions">
                <button class="tf-tree-action tf-node-more" data-path="${escapeHtml(path)}" data-type="file" title="${escapeHtml(t('moreActions') || 'Actions')}">⋮</button>
            </div>
        </div>`;
}

function bindTfTreeEvents(rootEl) {
    rootEl.querySelectorAll('.tf-tree-node').forEach(nodeEl => {
        const path = nodeEl.dataset.path;
        const type = nodeEl.dataset.type;
        const more = nodeEl.querySelector('.tf-node-more');
        nodeEl.addEventListener('click', (e) => {
            if (e.target.closest('.tf-tree-actions')) return;
            if (type === 'folder') {
                toggleTfDir(path);
            } else {
                openTfFile(path);
            }
        });
        if (more) {
            more.addEventListener('click', (e) => {
                e.stopPropagation();
                showTfNodeMenu(nodeEl, path, type === 'folder');
            });
        }
    });
}

function toggleTfDir(path) {
    if (state.tfExpandedDirs.has(path)) state.tfExpandedDirs.delete(path);
    else state.tfExpandedDirs.add(path);
    renderTfFileList();
}

function openTfFile(path) {
    if (!state.tfFiles.hasOwnProperty(path)) return;
    syncEditorToActive();
    if (!state.tfOpenFiles.includes(path)) state.tfOpenFiles.push(path);
    state.tfActiveFile = path;
    el('template-editor').value = state.tfFiles[path] || '';
    renderTfFileList();
    renderTfTabs();
    updateTemplateLineNumbers();
}

function closeTfFile(path) {
    state.tfOpenFiles = state.tfOpenFiles.filter(p => p !== path);
    if (state.tfActiveFile === path) {
        const next = state.tfOpenFiles[state.tfOpenFiles.length - 1] || null;
        state.tfActiveFile = next;
        el('template-editor').value = next ? state.tfFiles[next] : '';
    }
    renderTfFileList();
    renderTfTabs();
    updateTemplateLineNumbers();
}

function switchTfFile(path) {
    if (state.tfActiveFile === path) return;
    syncEditorToActive();
    state.tfActiveFile = path;
    el('template-editor').value = state.tfFiles[path] || '';
    renderTfFileList();
    renderTfTabs();
    updateTemplateLineNumbers();
}

function syncEditorToActive() {
    if (state.tfActiveFile && state.tfFiles.hasOwnProperty(state.tfActiveFile)) {
        state.tfFiles[state.tfActiveFile] = el('template-editor').value;
    }
}

function renderTfTabs() {
    const bar = el('tf-tabs-bar');
    if (!state.tfMode || !state.tfOpenFiles.length) {
        bar.innerHTML = '';
        return;
    }
    try {
        bar.innerHTML = state.tfOpenFiles.map(path => {
            const active = path === state.tfActiveFile;
            const name = path.split('/').pop();
            return `
                <div class="tf-tab ${active ? 'active' : ''}" data-path="${escapeHtml(path)}">
                    <span class="tf-tab-name">${escapeHtml(name)}</span>
                    <button class="tf-tab-close" data-path="${escapeHtml(path)}" title="${escapeHtml(t('closeTab') || 'Close')}">×</button>
                </div>`;
        }).join('');
        bar.querySelectorAll('.tf-tab').forEach(tab => {
            tab.addEventListener('click', (e) => {
                if (e.target.closest('.tf-tab-close')) return;
                switchTfFile(tab.dataset.path);
            });
        });
        bar.querySelectorAll('.tf-tab-close').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                closeTfFile(btn.dataset.path);
            });
        });
    } catch (e) {
        console.error('renderTfTabs error:', e);
        bar.innerHTML = '';
    }
}

async function deleteTfFile(path) {
    if (!state.tfFiles.hasOwnProperty(path)) return;
    if (!await showConfirm(t('confirmDeleteFile', { name: path.split('/').pop() }) || `Delete file "${path}"?`, { danger: true })) return;
    delete state.tfFiles[path];
    state.tfOpenFiles = state.tfOpenFiles.filter(p => p !== path);
    if (state.tfActiveFile === path) {
        const next = state.tfOpenFiles[state.tfOpenFiles.length - 1] || null;
        state.tfActiveFile = next;
        el('template-editor').value = next ? state.tfFiles[next] : '';
    }
    renderTfFileList();
    renderTfTabs();
    updateTemplateLineNumbers();
}

async function deleteTfFolder(path) {
    const prefix = path.endsWith('/') ? path : `${path}/`;
    const affected = Object.keys(state.tfFiles).filter(p => p === path || p.startsWith(prefix));
    if (!affected.length) return;
    if (!await showConfirm(t('confirmDeleteFolder', { name: path.split('/').pop() }) || `Delete folder "${path}" and its contents?`, { danger: true })) return;
    affected.forEach(p => delete state.tfFiles[p]);
    state.tfOpenFiles = state.tfOpenFiles.filter(p => p !== path && !p.startsWith(prefix));
    if (state.tfActiveFile && (state.tfActiveFile === path || state.tfActiveFile.startsWith(prefix))) {
        const next = state.tfOpenFiles[state.tfOpenFiles.length - 1] || null;
        state.tfActiveFile = next;
        el('template-editor').value = next ? state.tfFiles[next] : '';
    }
    state.tfExpandedDirs.delete(path);
    renderTfFileList();
    renderTfTabs();
    updateTemplateLineNumbers();
}

async function renameTfNode(oldPath, isFolder) {
    const oldName = oldPath.split('/').pop() || oldPath;
    const newName = await showPrompt({
        title: t(isFolder ? 'renameFolderTitle' : 'renameFileTitle') || (isFolder ? 'Rename Folder' : 'Rename File'),
        placeholder: t('namePlaceholder') || 'Name',
        defaultValue: oldName,
    });
    if (newName === null || !newName || newName === oldName) return;
    const parent = oldPath.includes('/') ? oldPath.split('/').slice(0, -1).join('/') : '';
    const newPath = parent ? `${parent}/${newName}` : newName;
    if (isFolder) {
        const oldPrefix = `${oldPath}/`;
        const newPrefix = `${newPath}/`;
        const entries = Object.entries(state.tfFiles).filter(([p]) => p === oldPath || p.startsWith(oldPrefix));
        if (entries.some(([p]) => p === newPath || p.startsWith(`${newPath}/`))) {
            toast(t('pathExists') || 'Target already exists', 'error');
            return;
        }
        entries.forEach(([p, content]) => {
            const rest = p === oldPath ? '' : p.slice(oldPrefix.length);
            const target = rest ? `${newPrefix}${rest}` : newPath;
            delete state.tfFiles[p];
            state.tfFiles[target] = content;
        });
        // update open files / active / expanded
        state.tfOpenFiles = state.tfOpenFiles.map(p => {
            if (p === oldPath) return newPath;
            if (p.startsWith(oldPrefix)) return `${newPrefix}${p.slice(oldPrefix.length)}`;
            return p;
        });
        if (state.tfActiveFile) {
            if (state.tfActiveFile === oldPath) state.tfActiveFile = newPath;
            else if (state.tfActiveFile.startsWith(oldPrefix)) state.tfActiveFile = `${newPrefix}${state.tfActiveFile.slice(oldPrefix.length)}`;
        }
        if (state.tfExpandedDirs.has(oldPath)) {
            state.tfExpandedDirs.delete(oldPath);
            state.tfExpandedDirs.add(newPath);
        }
    } else {
        if (state.tfFiles.hasOwnProperty(newPath)) {
            toast(t('fileExists') || 'File already exists', 'error');
            return;
        }
        const content = state.tfFiles[oldPath];
        delete state.tfFiles[oldPath];
        state.tfFiles[newPath] = content;
        state.tfOpenFiles = state.tfOpenFiles.map(p => p === oldPath ? newPath : p);
        if (state.tfActiveFile === oldPath) state.tfActiveFile = newPath;
    }
    renderTfFileList();
    renderTfTabs();
}

async function createTfFile(parentDir = '', anchorEl = null) {
    const name = await showInlinePrompt({
        anchorEl,
        title: t('createFileTitle') || 'Create File',
        placeholder: t('addFilePlaceholder') || 'e.g. main.tf',
        defaultValue: 'main.tf',
    });
    if (name === null || !name) return;
    const path = parentDir ? `${parentDir}/${name}` : name;
    if (state.tfFiles.hasOwnProperty(path)) {
        toast(t('fileExists') || 'File already exists', 'error');
        return;
    }
    state.tfFiles[path] = '';
    expandParentDirs(path);
    openTfFile(path);
}

async function createTfFolder(parentDir = '', anchorEl = null) {
    const name = await showInlinePrompt({
        anchorEl,
        title: t('createFolderTitle') || 'Create Folder',
        placeholder: t('folderPlaceholder') || 'e.g. modules',
        defaultValue: 'modules',
    });
    if (name === null || !name) return;
    const path = parentDir ? `${parentDir}/${name}` : name;
    const folderKey = `${path}/`;
    if (state.tfFiles.hasOwnProperty(folderKey) || state.tfFiles.hasOwnProperty(path)) {
        toast(t('pathExists') || 'Folder already exists', 'error');
        return;
    }
    // folders are represented by a trailing-slash entry with empty content
    state.tfFiles[folderKey] = '';
    state.tfExpandedDirs.add(path);
    renderTfFileList();
}

function showTfNodeMenu(nodeEl, path, isFolder) {
    closeAllTfMenus();
    const more = nodeEl.querySelector('.tf-node-more');
    const anchor = more || nodeEl;
    const rect = anchor.getBoundingClientRect();
    const menu = document.createElement('div');
    menu.className = 'tf-node-menu';
    let items = '';
    if (isFolder) {
        items += `<div class="tf-node-menu-item" data-action="create-file">${escapeHtml(t('createFile') || 'Create File')}</div>`;
        items += `<div class="tf-node-menu-item" data-action="create-folder">${escapeHtml(t('createFolder') || 'Create Folder')}</div>`;
    }
    items += `<div class="tf-node-menu-item" data-action="rename">${escapeHtml(t('renameBtn') || 'Rename')}</div>`;
    items += `<div class="tf-node-menu-item danger" data-action="delete">${escapeHtml(t('deleteBtn') || 'Delete')}</div>`;
    menu.innerHTML = items;
    menu.style.top = `${rect.bottom + window.scrollY + 2}px`;
    menu.style.left = `${rect.left + window.scrollX}px`;
    document.body.appendChild(menu);
    menu.querySelectorAll('.tf-node-menu-item').forEach(item => {
        item.addEventListener('click', () => {
            const action = item.dataset.action;
            if (action === 'create-file') createTfFile(path, anchor);
            else if (action === 'create-folder') createTfFolder(path, anchor);
            else if (action === 'rename') renameTfNode(path, isFolder);
            else if (action === 'delete') {
                if (isFolder) deleteTfFolder(path);
                else deleteTfFile(path);
            }
            menu.remove();
            state._tfOpenMenu = null;
        });
    });
    state._tfOpenMenu = menu;
}

function closeAllTfMenus() {
    if (state._tfOpenMenu) {
        state._tfOpenMenu.remove();
        state._tfOpenMenu = null;
    }
    if (state._tfInlinePrompt) {
        state._tfInlinePrompt.remove();
        state._tfInlinePrompt = null;
    }
    el('template-upload-menu').classList.remove('open');
    el('tf-add-dropdown').parentElement.classList.remove('open');
}

function tfMenuClickOutside(e) {
    const menu = state._tfOpenMenu;
    if (menu && !menu.contains(e.target) && !e.target.closest('.tf-node-more')) {
        menu.remove();
        state._tfOpenMenu = null;
    }
    if (!e.target.closest('#template-upload-menu')) el('template-upload-menu').classList.remove('open');
    if (!e.target.closest('#tf-add-dropdown') && !e.target.closest('#tf-add-trigger')) {
        el('tf-add-dropdown').parentElement.classList.remove('open');
    }
}

function loadLocalTfFiles(files) {
    const tfFiles = {};
    let count = 0;
    let loaded = 0;
    files.forEach(f => {
        if (!f.name.endsWith('.tf')) return;
        const relPath = f.webkitRelativePath
            ? f.webkitRelativePath.split('/').slice(1).join('/') || f.name
            : f.name;
        tfFiles[relPath] = null;
        count++;
    });
    if (!count) {
        toast(t('noTfFiles') || 'No .tf files found', 'error');
        return;
    }
    const readOne = (f, key) => {
        const reader = new FileReader();
        reader.onload = (ev) => {
            tfFiles[key] = ev.target.result;
            loaded++;
            if (loaded === count) {
                setTemplateTab('terraform');
                enterTfMode(tfFiles);
            }
        };
        reader.readAsText(f);
    };
    files.forEach(f => {
        if (!f.name.endsWith('.tf')) return;
        const relPath = f.webkitRelativePath
            ? f.webkitRelativePath.split('/').slice(1).join('/') || f.name
            : f.name;
        readOne(f, relPath);
    });
}

function loadProjectEditLocalTfFiles(files) {
    const tfFiles = {};
    let count = 0;
    let loaded = 0;
    files.forEach(f => {
        if (!f.name.endsWith('.tf')) return;
        const relPath = f.webkitRelativePath
            ? f.webkitRelativePath.split('/').slice(1).join('/') || f.name
            : f.name;
        tfFiles[relPath] = null;
        count++;
    });
    if (!count) {
        toast(t('noTfFiles') || 'No .tf files found', 'error');
        return;
    }
    const readOne = (f, key) => {
        const reader = new FileReader();
        reader.onload = (ev) => {
            tfFiles[key] = ev.target.result;
            loaded++;
            if (loaded === count) {
                setProjectEditTemplateTab('terraform');
                state.projectEditTfFiles = { ...tfFiles };
                state.projectEditTfActiveFile = null;
                const first = Object.keys(state.projectEditTfFiles).sort()[0];
                if (first) selectProjectEditTfFile(first);
                else renderProjectEditTfFileList();
            }
        };
        reader.readAsText(f);
    };
    files.forEach(f => {
        if (!f.name.endsWith('.tf')) return;
        const relPath = f.webkitRelativePath
            ? f.webkitRelativePath.split('/').slice(1).join('/') || f.name
            : f.name;
        readOne(f, relPath);
    });
}

function bindTfMenus() {
    el('template-upload-trigger').addEventListener('click', () => {
        el('template-upload-menu').classList.toggle('open');
    });
    el('tf-add-trigger').addEventListener('click', () => {
        el('tf-add-dropdown').parentElement.classList.toggle('open');
    });
    el('tf-add-dropdown').querySelectorAll('.tf-add-item').forEach(item => {
        item.addEventListener('click', () => {
            const action = item.dataset.action;
            const anchor = el('tf-add-trigger');
            if (action === 'file') createTfFile('', anchor);
            else if (action === 'folder') createTfFolder('', anchor);
            el('tf-add-dropdown').parentElement.classList.remove('open');
        });
    });
    document.addEventListener('click', tfMenuClickOutside);
}

// Shared validation helper used before policy/cost/run actions.
async function prevalidate(actionLabel) {
    if (!ensureCredentials()) return false;
    // Check that at least one region is selected
    const selectedRegions = state.pgRegionSelect ? state.pgRegionSelect.getSelected() : [];
    if (selectedRegions.length === 0) {
        toast(t('regionNotSelected') || 'Please select at least one region.', 'error');
        return false;
    }
    try {
        const payload = getRunPayload();
        if (!payload.template_content && !payload.template_files) {
            toast(t('templateEmpty') || 'Template is empty', 'error');
            return false;
        }

        // Check for unresolved $[iact3-auto] placeholders in config
        const cfgStr = payload.config_content || '';
        if (cfgStr.includes('$[iact3-auto]')) {
            const unresolvedKeys = [];
            const re = /^\s*(\w+)\s*:\s*\$\[iact3-auto\]/gm;
            let m;
            while ((m = re.exec(cfgStr)) !== null) unresolvedKeys.push(m[1]);
            const paramList = unresolvedKeys.length > 0 ? unresolvedKeys.join(', ') : '';
            const proceed = await showConfirm(
                t('unresolvedParamsMessage', { params: paramList }),
                {
                    title: t('unresolvedParamsTitle'),
                    okText: t('continueBtn') || 'Continue',
                }
            );
            if (!proceed) return false;
        }

        toast(t('preValidating', { action: actionLabel }) || `Validating before ${actionLabel}...`, 'info');
        const res = await api('POST', '/api/validate', payload);
        if (res.result !== 'valid') {
            if (res.logs) {
                consoleLog(res.logs, { type: 'info', action: 'validate', level: 'INFO', raw: true });
            } else {
                const summary = JSON.stringify(res, null, 2);
                consoleLog(`Validate result: ${res.result}\n${summary}`, { type: 'warn', action: 'validate', level: 'WARN' });
            }
            toast(t('validateFailedBeforeAction', { action: actionLabel }) || `Validation failed before ${actionLabel}`, 'error');
            return false;
        }
        return true;
    } catch (e) {
        consoleLog(`Validate failed: ${e.message}`, { type: 'error', action: 'validate' });
        toast(t('validateFailedBeforeAction', { action: actionLabel }) || `Validation failed before ${actionLabel}`, 'error');
        return false;
    }
}

function bindPlayground() {
    el('sample-select').addEventListener('change', (e) => {
        if (e.target.value) loadSample(e.target.value);
    });

    el('btn-run').addEventListener('click', async () => {
        setCurrentAction('run');
        if (!await prevalidate(t('runBtn') || 'Run Test')) return;
        state.runActiveTab = 'detail';
        const btn = el('btn-run');
        setBtnLoading(btn, true);
        try {
            const payload = getRunPayload();
            const run = await api('POST', '/api/runs', payload);
            if (run.logs) {
                consoleLog(run.logs, { type: 'info', action: 'run', level: 'INFO', raw: true });
            }
            showActionResult('run', t('runStartedTitle') || 'Run Started', run, 'run');
            pollRunInModal(run.id);
        } catch (e) {
            consoleLog(e.message, { type: 'error', action: 'run' });
            toast(t('runFailed'), 'error');
        } finally {
            setBtnLoading(btn, false);
        }
    });

    el('btn-policy').addEventListener('click', async () => {
        setCurrentAction('policy');
        if (!await prevalidate(t('policyBtn') || 'Generate Policy')) return;
        generatePolicy();
    });

    el('btn-generate-params').addEventListener('click', () => autoGenerateParams());

    const readFile = (file, cb) => {
        const reader = new FileReader();
        reader.onload = (ev) => cb(ev.target.result);
        reader.readAsText(file);
    };

    // ROS template upload
    el('upload-template').addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;
        if (file.name.endsWith('.tf')) {
            setTemplateTab('terraform');
            readFile(file, text => enterTfMode({ [file.name]: text }));
        } else if (file.name.endsWith('.json')) {
            setTemplateTab('ros');
            if (state.tfMode) exitTfMode();
            readFile(file, text => {
                setTemplateFormat('json');
                el('template-editor').value = text;
                updateTemplateLineNumbers();
                state._templateDirty = true;
            });
        } else {
            setTemplateTab('ros');
            if (state.tfMode) exitTfMode();
            readFile(file, text => {
                setTemplateFormat('yaml');
                el('template-editor').value = text;
                updateTemplateLineNumbers();
                state._templateDirty = true;
            });
        }
        e.target.value = '';
    });
    // Terraform open local file
    el('upload-template-file').addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;
        readFile(file, text => {
            setTemplateTab('terraform');
            enterTfMode({ [file.name]: text });
            state._templateDirty = true;
        });
        e.target.value = '';
    });
    // Terraform open local folder
    el('upload-template-dir').addEventListener('change', (e) => {
        loadLocalTfFiles(Array.from(e.target.files || []));
        state._templateDirty = true;
        e.target.value = '';
    });

    bindTfMenus();
    // Update region hint when multi-select changes; clear params when going multi-region
    if (state.pgRegionSelect) {
        state.pgRegionSelect.onChange = () => {
            const regions = state.pgRegionSelect.getSelected();
            if (regions.length > 1 && (state._prevRegionCount || 1) <= 1) {
                el('config-editor').value = '';
                highlightConfig();
            }
            state._prevRegionCount = regions.length;
            state._regionSelectionChanged = true;
            updateRegionHint();
        };
        state.pgRegionSelect.onClose = () => {
            if (state._regionSelectionChanged) {
                state._regionSelectionChanged = false;
                autoGenerateParams();
            }
        };
    }

    // ROS format switching (JSON / YAML)
    $$('.template-format-tabs .format-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (state.templateTab !== 'ros') return;
            const format = btn.dataset.format;
            const editor = el('template-editor');
            const current = editor.value.trim();
            const isSkeleton = current === ROS_YAML_SKELETON.trim() || current === ROS_JSON_SKELETON.trim();
            setTemplateFormat(format);
            if (isSkeleton) {
                editor.value = format === 'json' ? ROS_JSON_SKELETON : ROS_YAML_SKELETON;
            } else if (typeof jsyaml !== 'undefined') {
                try {
                    const schema = ROS_SCHEMA || jsyaml.DEFAULT_SCHEMA;
                    const parsed = jsyaml.load(current, { schema });
                    if (format === 'json') {
                        editor.value = JSON.stringify(parsed, null, 2);
                    } else {
                        editor.value = jsyaml.dump(parsed, { schema, lineWidth: -1, noRefs: true });
                    }
                } catch (e) {
                    toast(`Format conversion failed: ${e.message}`, 'error');
                }
            }
            updateTemplateLineNumbers();
        });
    });

    // Line numbers sync + code highlight
    el('template-editor').addEventListener('input', () => {
        updateTemplateLineNumbers();
        state._templateDirty = true;
        // Clear execution results when template content changes
        clearAllActionOutputs();
    });
    el('template-editor').addEventListener('scroll', syncLineNumberScroll);
    el('config-editor').addEventListener('input', highlightConfig);
    el('config-editor').addEventListener('scroll', syncLineNumberScroll);
    window.addEventListener('resize', updateTemplateLineNumbers);
    // Initial highlight
    refreshEditorHighlight();

    // Auto-generate parameters when mouse leaves the template pane
    const templatePane = document.querySelector('.pg-body > .editor-pane:not(.config-editor-pane)');
    if (templatePane) {
        templatePane.addEventListener('mouseleave', () => {
            if (state._templateDirty) {
                state._templateDirty = false;
                autoGenerateParams();
            }
        });
    }

    el('load-ros-example').addEventListener('click', loadRosExample);
    el('load-tf-example').addEventListener('click', loadTfExample);

    el('pg-body-toggle').addEventListener('click', (e) => {
        e.stopPropagation();
        el('pg-body').classList.toggle('collapsed');
    });

    // Unified output panel: tabs, head toggle, copy, clear
    $$('.output-tab').forEach(tab => {
        tab.addEventListener('click', async () => {
            const action = tab.dataset.action;
            const hasResult = hasActionResult(action);
            const hasLogs = hasActionLogs(action);

            if (hasResult || hasLogs) {
                // Already has content — just switch to this tab
                setCurrentAction(action);
                el('pg-output').classList.remove('collapsed');
            } else {
                // No result yet — auto-trigger the corresponding action
                setCurrentAction(action);
                el('pg-output').classList.remove('collapsed');
                if (action === 'run') {
                    // btn-run click handler already calls prevalidate internally
                    el('btn-run').click();
                } else {
                    if (!await prevalidate(t(action + 'Btn'))) return;
                    if (action === 'policy') {
                        generatePolicy();
                    } else if (action === 'cost') {
                        estimateCost();
                    }
                }
            }
        });
    });

    el('btn-clear-output').addEventListener('click', clearResultPanel);
    el('pg-output').querySelector('.output-head').addEventListener('click', (e) => {
        if (e.target.closest('.output-actions')) return;
        el('pg-output').classList.toggle('collapsed');
    });
    el('btn-copy-output').addEventListener('click', async () => {
        const action = state.currentAction;
        const container = action ? el(`result-${action}`) : el('pg-output-body');
        const text = (container ? container.textContent : '') || '';
        try {
            await copyToClipboard(text);
            toast(t('copied') || 'Copied', 'success');
        } catch (e) {
            toast(t('copyFailed') || 'Copy failed', 'error');
        }
    });

    // Logs sections: toggle collapse and copy logs
    el('pg-output-body').addEventListener('click', (e) => {
        // Run inner tab switching
        const runTab = e.target.closest('.run-inner-tab');
        if (runTab) {
            e.stopPropagation();
            const tabName = runTab.dataset.runTab;
            state.runActiveTab = tabName;
            const container = el('result-run');
            if (container) {
                container.querySelectorAll('.run-inner-tab').forEach(t => t.classList.toggle('active', t.dataset.runTab === tabName));
                container.querySelectorAll('.run-inner-pane').forEach(p => p.classList.toggle('hidden', p.dataset.runPane !== tabName));
            }
            return;
        }
        const copyBtn = e.target.closest('.logs-section .output-section-copy');
        if (copyBtn) {
            e.stopPropagation();
            const body = copyBtn.closest('.logs-section')?.querySelector('.output-section-body');
            const text = body ? body.textContent : '';
            copyToClipboard(text).then(
                () => toast(t('copied') || 'Copied', 'success'),
                () => toast(t('copyFailed') || 'Copy failed', 'error')
            );
            return;
        }
        const head = e.target.closest('.logs-section .output-section-head');
        if (head) {
            head.closest('.logs-section')?.classList.toggle('collapsed');
        }
    });

    // Save-as-project popover
    const pgSavePopover = el('pg-save-popover');
    const pgNameInput = el('pg-project-name-input');
    el('btn-pg-save-project').addEventListener('click', (e) => {
        e.stopPropagation();
        pgSavePopover.classList.toggle('open');
        if (pgSavePopover.classList.contains('open')) setTimeout(() => pgNameInput.focus(), 30);
    });
    el('btn-pg-save-cancel').addEventListener('click', () => {
        pgSavePopover.classList.remove('open');
        pgNameInput.value = '';
        pgNameInput.classList.remove('input-invalid');
        pgNameInput.title = '';
    });
    el('btn-pg-save-confirm').addEventListener('click', () => pgSaveFromPlayground());
    pgNameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') pgSaveFromPlayground();
        if (e.key === 'Escape') { pgSavePopover.classList.remove('open'); pgNameInput.value = ''; pgNameInput.classList.remove('input-invalid'); pgNameInput.title = ''; }
    });
    bindProjectNameLive(pgNameInput, el('btn-pg-save-confirm'));
    // Click outside to close
    document.addEventListener('click', (e) => {
        if (!el('pg-save-project-wrap').contains(e.target)) {
            pgSavePopover.classList.remove('open');
        }
    });
}

/* ============== Cost Estimate ============== */
function bindCost() {
    el('btn-cost').addEventListener('click', async () => {
        setCurrentAction('cost');
        if (!await prevalidate(t('costBtn') || 'Estimate Cost')) return;
        estimateCost();
    });

    el('policy-modal-close').addEventListener('click', () => el('policy-modal').classList.remove('open'));
    el('policy-modal-copy').addEventListener('click', copyPolicyToClipboard);
    el('policy-modal').addEventListener('click', (e) => {
        if (e.target === el('policy-modal')) el('policy-modal').classList.remove('open');
    });

    el('result-modal-close').addEventListener('click', () => el('result-modal').classList.remove('open'));
    el('result-modal-copy').addEventListener('click', copyResultToClipboard);
    el('result-modal').addEventListener('click', (e) => {
        if (e.target === el('result-modal')) el('result-modal').classList.remove('open');
    });
}

async function estimateCost() {
    const btn = el('btn-cost');
    setBtnLoading(btn, true);
    try {
        const payload = getRunPayload();
        if (!payload.template_content && !payload.template_files) {
            toast(t('templateEmpty') || 'Template is empty', 'error');
            return;
        }
        showActionLoading('cost', t('costEstimating') || 'Cost estimating...');
        const res = await api('POST', '/api/cost', payload);
        state.lastCostPrices = res.prices || [];
        if (res.logs) {
            consoleLog(res.logs, { type: 'info', action: 'cost', level: 'INFO', raw: true });
        }
        showActionResult('cost', t('costResultTitle') || 'Cost Estimate Result', renderCostResultsHtml(state.lastCostPrices), 'html');
        logCostSummary(state.lastCostPrices);
    } catch (e) {
        consoleLog(`Cost estimate failed: ${e.message}`, { type: 'error', action: 'cost' });
        toast(t('costFailed'), 'error');
        clearActionResult('cost');
    } finally {
        setBtnLoading(btn, false);
    }
}

async function generatePolicy() {
    const btn = el('btn-policy');
    setBtnLoading(btn, true);
    try {
        const payload = getRunPayload();
        if (!payload.template_content && !payload.template_files) {
            toast(t('templateEmpty') || 'Template is empty', 'error');
            return;
        }
        showActionLoading('policy', t('policyGenerating') || 'Generating policy...');
        const res = await api('POST', '/api/policy', payload);
        if (res.logs) {
            consoleLog(res.logs, { type: 'info', action: 'policy', level: 'INFO', raw: true });
        }
        showActionResult('policy', t('policyResultTitle') || 'Policy Result', res.policy, 'json');
    } catch (e) {
        consoleLog(`Policy generation failed: ${e.message}`, { type: 'error', action: 'policy' });
        toast(e.message, 'error');
        clearActionResult('policy');
    } finally {
        setBtnLoading(btn, false);
    }
}

function pollRunInModal(runId) {
    // Stop any previous active poller to prevent log/status interleaving
    if (state._activeRunPoller) {
        state._activeRunPoller.stop();
    }

    const terminal = new Set(['completed', 'failed', 'cancelled']);
    let lastLogLength = 0;
    let logTimer = null;
    let pollTimer = null;
    let stopped = false;
    let logErrorReported = false;
    let statusErrorReported = false;

    const stop = () => {
        stopped = true;
        if (logTimer) clearInterval(logTimer);
        if (pollTimer) clearTimeout(pollTimer);
        if (state._activeRunPoller && state._activeRunPoller.runId === runId) {
            state._activeRunPoller = null;
        }
    };

    const fetchLogs = async (final = false) => {
        try {
            const logs = await api('GET', `/api/runs/${runId}/logs`);
            if (typeof logs === 'string' && logs.length > lastLogLength) {
                const newLogs = logs.substring(lastLogLength).trim();
                if (newLogs) consoleLog(newLogs, { type: 'info', action: 'run', level: 'INFO', raw: true });
                lastLogLength = logs.length;
            }
            if (final) return;
        } catch (e) {
            // Only log once to avoid spamming the console when the modal is closed.
            if (!stopped && !logErrorReported) {
                logErrorReported = true;
                consoleLog(`Run logs poll failed: ${e.message}`, { type: 'error', action: 'run' });
            }
        }
    };

    const poll = async () => {
        if (stopped) return;
        try {
            const run = await api('GET', `/api/runs/${runId}`);
            statusErrorReported = false;
            // Update the run result panel without switching focus away from other actions.
            const runContainer = el('result-run');
            if (runContainer) {
                const title = t('runStatusTitle') || `Run ${run.status}`;
                runContainer.innerHTML = renderRunStatusHtml(run);
                state.actionResults.run = { title, content: run, type: 'run' };
                if (state.currentAction === 'run') {
                    el('pg-output-title').textContent = title;
                    syncOutputSections('run');
                }
                updateActionTabs();
            }
            if (!terminal.has(run.status)) {
                pollTimer = setTimeout(poll, 5000);
            } else {
                // Final log fetch immediately, then one more after a short delay
                // to catch any trailing writes (e.g. DELETE_COMPLETE / completed).
                fetchLogs(true);
                setTimeout(() => {
                    fetchLogs(true);
                    stop();
                }, 1500);
            }
        } catch (e) {
            if (!stopped && !statusErrorReported) {
                statusErrorReported = true;
                consoleLog(`Run poll failed: ${e.message}`, { type: 'error', action: 'run' });
            }
            // Retry after delay even on error to avoid stopping polling entirely
            if (!stopped) {
                pollTimer = setTimeout(poll, 5000);
            }
        }
    };

    // Closing the modal only hides the overlay; polling continues so that
    // progress and logs are still printed to the console output area.
    state._activeRunPoller = { stop, runId };
    poll();
    fetchLogs();
    logTimer = setInterval(fetchLogs, 3000);
}

function renderRunStatusHtml(run) {
    const status = (run.status || 'pending').toLowerCase();
    const statusLabel = t(`status${status.charAt(0).toUpperCase() + status.slice(1)}`) || run.status;
    const progress = typeof run.progress === 'number' ? run.progress : 0;

    const infoItems = [
        `<div class="pd-kv-item"><span class="pd-kv-label">${t('runId') || 'Run ID'}</span><span class="pd-kv-value"><code>${escapeHtml(run.id || '')}</code></span></div>`,
        `<div class="pd-kv-item"><span class="pd-kv-label">${t('detailStatus') || 'Status'}</span><span class="pd-kv-value"><span class="status-badge status-${status}">${escapeHtml(statusLabel)}</span></span></div>`,
        `<div class="pd-kv-item"><span class="pd-kv-label">${t('runName') || 'Name'}</span><span class="pd-kv-value">${escapeHtml(run.name || '-')}</span></div>`,
        `<div class="pd-kv-item"><span class="pd-kv-label">${t('detailCreated') || 'Created'}</span><span class="pd-kv-value">${escapeHtml(formatTime(run.created_at))}</span></div>`,
        `<div class="pd-kv-item"><span class="pd-kv-label">${t('runProgress') || 'Progress'}</span><span class="pd-kv-value"><div class="progress-bar"><div class="progress-fill ${status === 'completed' ? 'completed' : status === 'failed' ? 'failed' : ''}" style="width:${progress}%"></div></div> <span style="font-size:12px;color:var(--text-muted)">${progress}%</span></span></div>`,
    ];
    if (run.completed_at) {
        infoItems.push(`<div class="pd-kv-item"><span class="pd-kv-label">${t('runFinishedAt') || 'Finished'}</span><span class="pd-kv-value">${escapeHtml(formatTime(run.completed_at))}</span></div>`);
        infoItems.push(`<div class="pd-kv-item"><span class="pd-kv-label">${t('detailDuration') || 'Duration'}</span><span class="pd-kv-value">${escapeHtml(duration(run.created_at, run.completed_at))}</span></div>`);
    } else if (run.created_at) {
        infoItems.push(`<div class="pd-kv-item"><span class="pd-kv-label">${t('detailDuration') || 'Duration'}</span><span class="pd-kv-value">${escapeHtml(duration(run.created_at))}</span></div>`);
    }
    // Stack stats
    const stacks = Array.isArray(run.stacks) ? run.stacks : [];
    if (stacks.length > 0) {
        const { total: totalStacks, succeeded: succeededStacks, ratio: successRatio, ratioColor } = calcStackStats(stacks);
        infoItems.push(`<div class="pd-kv-item"><span class="pd-kv-label">${t('stackTotal')}</span><span class="pd-kv-value">${totalStacks}</span></div>`);
        infoItems.push(`<div class="pd-kv-item"><span class="pd-kv-label">${t('stackSuccessRatio')}</span><span class="pd-kv-value ${ratioColor}">${succeededStacks}/${totalStacks} (${successRatio}%)</span></div>`);
    }
    if (run.report_url) {
        infoItems.push(`<div class="pd-kv-item"><span class="pd-kv-label">${t('runReport') || 'Report'}</span><span class="pd-kv-value"><a href="${escapeHtml(authUrl(run.report_url))}" target="_blank" class="btn-view-report">${t('viewReportBtn') || 'View Report'}</a></span></div>`);
    }
    if (run.error) {
        infoItems.push(`<div class="pd-kv-item" style="grid-column:1/-1"><span class="pd-kv-label">${t('runError') || 'Error'}</span><span class="pd-kv-value" style="color:var(--danger)">${escapeHtml(run.error)}</span></div>`);
    }

    const infoHtml = `<div class="pd-kv-grid">${infoItems.join('')}</div>`;

    const activeTab = state.runActiveTab || 'detail';

    let stacksPaneHtml;
    if (stacks.length) {
        stacksPaneHtml = `
            <div class="task-table-wrap">
                <table class="cost-table stacks-table">
                    <thead><tr>
                        <th>${t('stackNameOrId')}</th>
                        <th>${t('stackRegion')}</th>
                        <th>${t('stackStatus')}</th>
                        <th>${t('launchSucceeded')}</th>
                    </tr></thead>
                    <tbody>
                        ${stacks.map(s => {
                            const sStatus = (s.status || 'pending').toLowerCase().replace(/_/g, '-');
                            const sRegionId = typeof s.region === 'object' ? (s.region?.id || '') : (s.region || '');
                            const rosUrl = s.stack_id && sRegionId
                                ? `https://ros.console.aliyun.com/${encodeURIComponent(sRegionId)}/stacks/${encodeURIComponent(s.stack_id)}`
                                : '';
                            const nameText = escapeHtml(s.stack_name || s.test_name || '-');
                            const idText = s.stack_id ? escapeHtml(s.stack_id) : '';
                            const nameHtml = rosUrl
                                ? `<a class="stack-link" href="${rosUrl}" target="_blank" rel="noopener">${nameText}</a>`
                                : `<span class="res-name">${nameText}</span>`;
                            const idHtml = idText
                                ? (rosUrl
                                    ? `<a class="stack-id-text stack-link" href="${rosUrl}" target="_blank" rel="noopener">${idText}</a>`
                                    : `<span class="stack-id-text">${idText}</span>`)
                                : '';
                            return `<tr>
                                <td>
                                    <div class="stack-name-cell">
                                        ${nameHtml}
                                        ${idHtml}
                                    </div>
                                </td>
                                <td>${escapeHtml(regionName(s.region))}</td>
                                <td>
                                    <span class="status-badge status-${sStatus}">${escapeHtml(tStackStatus(s.status) || s.status || '-')}</span>
                                </td>
                                <td>
                                    ${s.launch_succeeded !== undefined
                                        ? `<span class="${s.launch_succeeded ? 'pd-stack-stat-succeeded' : 'pd-stack-stat-failed'}">${s.launch_succeeded ? t('yes') : t('no')}</span>`
                                        : '-'}
                                </td>
                            </tr>`;
                        }).join('')}
                    </tbody>
                </table>
            </div>`;
    } else {
        stacksPaneHtml = `<div class="empty-state" style="padding:24px">${t('runNoStacks') || 'No stacks yet.'}</div>`;
    }

    return `
        <div style="white-space:normal">
            <div class="run-inner-tabs">
                <button class="run-inner-tab ${activeTab === 'detail' ? 'active' : ''}" data-run-tab="detail">${t('runDetailTab')}</button>
                <button class="run-inner-tab ${activeTab === 'stacks' ? 'active' : ''}" data-run-tab="stacks">${t('runStacksTab')}</button>
            </div>
            <div class="run-inner-pane ${activeTab !== 'detail' ? 'hidden' : ''}" data-run-pane="detail">
                <div class="detail-card" style="margin-bottom:16px">
                    ${infoHtml}
                </div>
            </div>
            <div class="run-inner-pane ${activeTab !== 'stacks' ? 'hidden' : ''}" data-run-pane="stacks">
                ${stacksPaneHtml}
            </div>
        </div>`;
}

function openPolicyModal(policy) {
    const body = el('policy-body');
    if (!policy) {
        body.textContent = t('policyEmpty');
    } else if (typeof policy === 'string') {
        body.textContent = policy;
    } else {
        body.textContent = JSON.stringify(policy, null, 2);
    }
    el('policy-modal').classList.add('open');
}

function openResultModal(title, content, type = 'json') {
    el('result-modal-title').textContent = title;
    const body = el('result-body');
    if (type === 'html') {
        body.innerHTML = content;
    } else if (type === 'run') {
        body.innerHTML = renderRunStatusHtml(content);
    } else if (type === 'json' && typeof content !== 'string') {
        body.textContent = JSON.stringify(content, null, 2);
    } else {
        body.textContent = content;
    }
    // Mark the modal content with the result type so CSS can adapt the width.
    const modalContent = el('result-modal').querySelector('.modal-content-result');
    if (modalContent) modalContent.dataset.type = type;
    el('result-modal').classList.add('open');
}

function hasActionResult(action) {
    return !!(state.actionResults[action] && el(`result-${action}`)?.childNodes.length > 0);
}

function hasActionLogs(action) {
    return !!(el(`log-${action}`)?.childNodes.length > 0);
}

function updateActionTabs() {
    const action = state.currentAction;
    $$('.output-tab').forEach(tab => {
        const a = tab.dataset.action;
        tab.classList.toggle('active', a === action);
    });
    syncOutputPanelCollapse();
}

function syncOutputPanelCollapse() {
    const hasAnyContent = ['policy', 'cost', 'run'].some(a => hasActionResult(a) || hasActionLogs(a));
    el('pg-output').classList.toggle('collapsed', !hasAnyContent);
}

function setCurrentAction(action) {
    if (!['policy', 'cost', 'run'].includes(action)) return;
    state.currentAction = action;
    // Collapse the editor to make room for the action output, but keep it
    // expanded when the template is empty so the user can see and edit it.
    if (!isTemplateEmpty()) {
        el('pg-body').classList.add('collapsed');
    }
    // The output panel is always visible; just update the title and active pane.
    const result = state.actionResults[action];
    el('pg-output-title').textContent = result?.title || (t('resultTitle') || 'Result');
    // Show only this action's output pane.
    $$('.output-pane').forEach(p => p.classList.toggle('hidden', p.id !== `output-pane-${action}`));
    // Sync result/logs section visibility for the active action.
    syncOutputSections(action);
    updateActionTabs();
}

function syncOutputSections(action) {
    if (!action) return;
    const resultPane = el(`result-${action}`);
    const logsSection = el(`logs-section-${action}`);
    if (resultPane) resultPane.classList.toggle('hidden', !hasActionResult(action));
    if (logsSection) logsSection.classList.toggle('hidden', !hasActionLogs(action));
}

function showActionResult(action, title, content, type = 'json') {
    if (!['policy', 'cost', 'run'].includes(action)) return;
    const container = el(`result-${action}`);
    if (!container) return;
    if (type === 'html') {
        container.innerHTML = content;
    } else if (type === 'run') {
        container.innerHTML = renderRunStatusHtml(content);
    } else if (type === 'json' && typeof content !== 'string') {
        container.innerHTML = `<pre class="result-pre">${escapeHtml(JSON.stringify(content, null, 2))}</pre>`;
    } else {
        container.innerHTML = `<pre class="result-pre">${escapeHtml(String(content))}</pre>`;
    }
    state.actionResults[action] = { title, content, type };
    state._hasActionOutput = true;
    setCurrentAction(action);
    el('pg-output').classList.remove('collapsed');
    container.scrollTop = 0;
}

function showActionLoading(action, message) {
    if (!['policy', 'cost', 'run'].includes(action)) return;
    const container = el(`result-${action}`);
    if (!container) return;
    container.innerHTML = `<div class="result-loading"><span class="result-loading-spinner"></span><span>${escapeHtml(message)}</span></div>`;
    state.actionResults[action] = { title: message, content: null, type: 'loading' };
    state._hasActionOutput = true;
    setCurrentAction(action);
    el('pg-output').classList.remove('collapsed');
}

function clearResultPanel() {
    const action = state.currentAction;
    if (action) {
        clearActionResult(action);
        const logBody = el(`log-${action}`);
        if (logBody) logBody.innerHTML = '';
        syncOutputSections(action);
    } else {
        ['policy', 'cost', 'run'].forEach(a => {
            clearActionResult(a);
            const logBody = el(`log-${a}`);
            if (logBody) logBody.innerHTML = '';
            syncOutputSections(a);
        });
    }
    // Keep the output panel visible; just expand the editor area again.
    el('pg-body').classList.remove('collapsed');
    updateActionTabs();
}

// Clear all action results and logs (called when template content changes)
function clearAllActionOutputs() {
    if (!state._hasActionOutput) return;
    ['policy', 'cost', 'run'].forEach(a => {
        clearActionResult(a);
        const logBody = el(`log-${a}`);
        if (logBody) logBody.innerHTML = '';
        syncOutputSections(a);
    });
    state._hasActionOutput = false;
    el('pg-output').classList.add('collapsed');
    el('pg-body').classList.remove('collapsed');
    updateActionTabs();
}

function clearActionResult(action) {
    if (!action) return;
    state.actionResults[action] = null;
    const container = el(`result-${action}`);
    if (container) container.innerHTML = '';
    syncOutputSections(action);
}

async function copyPolicyToClipboard() {
    const text = el('policy-body').textContent || '';
    try {
        await copyToClipboard(text);
        toast(t('copied') || 'Copied', 'success');
    } catch (e) {
        toast(t('copyFailed') || 'Copy failed', 'error');
    }
}

async function copyResultToClipboard() {
    const text = el('result-body').textContent || '';
    try {
        await copyToClipboard(text);
        toast(t('copied') || 'Copied', 'success');
    } catch (e) {
        toast(t('copyFailed') || 'Copy failed', 'error');
    }
}

function renderCostResultsHtml(prices) {
    if (!prices.length) {
        return `<div class="empty-state" style="padding:32px 24px;text-align:left">
            <div style="font-size:16px;font-weight:600;margin-bottom:8px">${t('costEmpty')}</div>
            <div style="font-size:13px;color:var(--text-muted);max-width:480px;line-height:1.6">${t('costNoResultHint')}</div>
        </div>`;
    }

    const sections = prices.map(p => {
        if (p.error) {
            return `<div class="cost-section" style="margin-bottom:18px">
                <div style="font-size:13px;font-weight:500;margin-bottom:6px">${escapeHtml(p.test_name || '')} · ${escapeHtml(regionName(p.region))}</div>
                <div class="status-badge status-failed">${escapeHtml(p.status || 'Error')}</div>
                <div style="margin-top:6px;color:var(--danger);font-size:13px">${escapeHtml(p.error)}</div>
            </div>`;
        }
        const { rows, errors } = extractCostRows(p);
        const hasRows = rows.length > 0;
        const hasErrors = errors.length > 0;

        let html = `<div class="cost-section" style="margin-bottom:18px">
            <div style="font-size:13px;font-weight:500;margin-bottom:8px">${escapeHtml(p.test_name || '')} · ${escapeHtml(regionName(p.region))}</div>`;

        if (hasErrors) {
            html += `<div class="cost-error-banner">
                <div style="font-weight:600;margin-bottom:4px">${t('costResourceError')}</div>
                ${errors.map(e => `<div><span class="err-code">${escapeHtml(e.logicalId)} · ${escapeHtml(e.code)}</span>: ${escapeHtml(e.message)}</div>`).join('')}
            </div>`;
        }

        if (!hasRows) {
            html += `<div class="empty-state" style="padding:30px 20px;text-align:left">
                <div style="font-weight:600;margin-bottom:6px">${t('costNoBillableResources')}</div>
                <div style="font-size:12px;color:var(--text-muted);line-height:1.5">${t('costNoResultHint')}</div>
            </div></div>`;
            return html;
        }

        html += `<div class="task-table-wrap"><table class="cost-table">
            <thead><tr>
                <th>${t('costResource')}</th>
                <th>${t('costRegion')}</th>
                <th>${t('costResourceType')}</th>
                <th>${t('costChargeType')}</th>
                <th>${t('costPeriodUnit')}</th>
                <th>${t('costQuantity')}</th>
                <th>${t('costCurrency')}</th>
                <th>${t('costOriginalAmount')}</th>
                <th>${t('costDiscountAmount')}</th>
                <th>${t('costTradeAmount')}</th>
            </tr></thead>
            <tbody>`;

        rows.forEach((r) => {
            const resourceCell = r.resource
                ? `<span class="res-name">${escapeHtml(r.resource)}</span>`
                : `<span style="color:var(--text-muted)">-</span>`;
            html += `<tr>
                <td class="resource-cell">${resourceCell}</td>
                <td>${escapeHtml(regionName(r.region))}</td>
                <td>${escapeHtml(r.type)}</td>
                <td>${escapeHtml(r.chargeType)}</td>
                <td>${escapeHtml(r.periodUnit)}</td>
                <td>${escapeHtml(String(r.quantity))}</td>
                <td>${escapeHtml(r.currency)}</td>
                <td class="cost-amount">${formatCostMoney(r.originalAmount, r.currency, '', 'cost-original')}</td>
                <td class="cost-amount">${formatCostMoney(r.discountAmount, r.currency, '', 'cost-discount')}</td>
                <td class="cost-amount">${formatCostMoney(r.tradeAmount, r.currency, '', 'cost-price')}</td>
            </tr>`;
        });

        html += `</tbody></table></div>`;
        const total = rows.reduce((sum, r) => sum + (r.resource ? (Number(r.tradeAmount) || 0) : 0), 0);
        const currency = rows.find(r => r.currency && r.currency !== '-')?.currency || 'CNY';
        // Check if all rows share the same billing period
        const units = [...new Set(rows.map(r => r.periodUnit).filter(u => u && u !== '-'))];
        const unit = units.length === 1 ? (units[0].startsWith('/') ? units[0] : '/' + units[0]) : '';
        html += `<div class="cost-summary">
            <span>${t('costTotal')}</span>
            <span>${formatCostMoney(total, currency, unit, 'cost-price')}</span>
        </div></div>`;
        return html;
    });

    return sections.join('');
}

function extractCostRows(priceEntry) {
    const rows = [];
    const errors = [];
    const price = priceEntry.price || {};
    const region = priceEntry.region || '-';

    function addRows(logicalId, res, prefix = '') {
        const type = res.Type || logicalId;
        const result = res.Result || {};
        const order = result.Order || {};
        const supplement = result.OrderSupplement || {};
        const currency = order.Currency || '-';
        const typeShort = type.includes('::') ? type.slice(type.indexOf('::') + 2) : type;
        const resourceName = prefix ? '' : logicalId;
        const displayType = prefix ? `${prefix}-${logicalId}` : type;

        rows.push({
            resource: resourceName,
            region,
            type: displayType,
            chargeType: supplement.ChargeType || order.ChargeType || '-',
            periodUnit: supplement.PriceUnit || supplement.PeriodUnit || '-',
            quantity: supplement.Quantity !== undefined ? supplement.Quantity : '-',
            currency,
            originalAmount: order.OriginalAmount !== undefined ? order.OriginalAmount : null,
            discountAmount: order.DiscountAmount !== undefined ? order.DiscountAmount : null,
            tradeAmount: order.TradeAmount !== undefined ? order.TradeAmount : null,
        });

        const associationProducts = result.AssociationProducts || {};
        Object.entries(associationProducts).forEach(([assocName, assocRes]) => {
            addRows(assocName, assocRes, typeShort);
        });
    }

    Object.entries(price).forEach(([logicalId, res]) => {
        if (res.Success === false || (res.Result && res.Result.Code)) {
            errors.push({
                logicalId,
                code: (res.Result && res.Result.Code) || 'Error',
                message: (res.Result && res.Result.Message) || t('costFailed')
            });
            return;
        }
        addRows(logicalId, res);
    });

    return { rows, errors };
}

function formatCostAttributes(attrs) {
    if (!Array.isArray(attrs) || !attrs.length) return '-';
    return attrs.map(a => `${escapeHtml(a.Code || '')}: ${escapeHtml(String(a.Value || ''))}`).join('<br>');
}

function formatBillingMethod(chargeType) {
    const map = {
        'PostPaid': t('costPostPaid'),
        'PrePaid': t('costPrePaid'),
        'Buy': t('costPostPaid'),
    };
    return map[chargeType] || chargeType;
}

function formatDuration(chargeType, period, periodUnit) {
    if (chargeType === 'PostPaid' || chargeType === 'Buy' || !period) return '-';
    return `${period}${formatPeriodUnit(periodUnit)}`;
}

function formatPeriodUnit(unit) {
    const map = {
        'Month': t('costMonth'),
        'Year': t('costYear'),
        'Hour': t('costHourly'),
        'Day': t('costDay'),
    };
    return map[unit] || (unit ? `/${unit}` : '');
}

function formatCurrencySymbol(currency) {
    const map = { 'CNY': '¥', 'USD': '$', 'EUR': '€', 'JPY': '¥' };
    return map[currency] || `${currency} `;
}

function formatMoneyRaw(value) {
    const n = Number(value) || 0;
    return n.toFixed(6).replace(/\.?0+$/, '') || '0';
}

function formatCostMoney(amount, currency, unit, cssClass = 'cost-original') {
    if (amount === null || amount === undefined || amount === '') return '-';
    const symbol = formatCurrencySymbol(currency);
    return `<span class="${cssClass}">${symbol}${formatMoneyRaw(amount)}<span class="cost-unit">${unit}</span></span>`;
}

function formatCostDiscount(amount, currency) {
    const n = Number(amount) || 0;
    if (!n) return '-';
    const symbol = formatCurrencySymbol(currency);
    return `<span class="cost-discount">${t('costSave')}${symbol}${formatMoneyRaw(n)}</span>`;
}

function logCostSummary(prices) {
    if (!prices.length) {
        consoleLog(t('costLogEmpty', { hint: t('costNoResultHint') }), { type: 'warn', action: 'cost' });
        return;
    }
    prices.forEach(p => {
        if (p.error) {
            consoleLog(t('costLogError', { region: p.region || '-', error: p.error }), { type: 'error', action: 'cost' });
            return;
        }
        const { rows, errors } = extractCostRows(p);
        errors.forEach(e => {
            consoleLog(t('costLogResourceError', {
                region: p.region || '-',
                logicalId: e.logicalId,
                code: e.code,
                message: e.message
            }), { type: 'error', action: 'cost' });
        });
        if (!rows.length) {
            consoleLog(t('costLogEmpty', { hint: t('costNoResultHint') }), { type: 'warn', action: 'cost' });
            return;
        }
        const total = rows.reduce((sum, r) => sum + (Number(r.tradeAmount) || 0), 0);
        const currency = rows.find(r => r.currency && r.currency !== '-')?.currency || 'CNY';
        const units = [...new Set(rows.map(r => r.periodUnit).filter(u => u && u !== '-'))];
        const unit = units.length === 1 ? (units[0].startsWith('/') ? units[0] : '/' + units[0]) : '';
        consoleLog(t('costLogTotal', {
            region: p.region || '-',
            amount: `${formatCurrencySymbol(currency)}${formatMoneyRaw(total)}${unit}`
        }), { type: errors.length ? 'info' : 'success', action: 'cost' });
    });
}

function formatPrice(price) {
    if (price === null || price === undefined) return '-';
    if (typeof price === 'object') {
        const keys = Object.keys(price);
        if (!keys.length) return '-';
        return `<pre style="margin:0;font-size:12px">${escapeHtml(JSON.stringify(price, null, 2))}</pre>`;
    }
    return escapeHtml(String(price));
}

/* ============== Projects ============== */
async function loadProjects() {
    try {
        const params = new URLSearchParams();
        params.set('page', String(state.projectPage));
        params.set('per_page', String(state.projectPerPage));
        if (state.projectSearch) params.set('search', state.projectSearch);
        const data = await api('GET', `/api/projects?${params.toString()}`);
        state.projects = data.projects || [];
        state.projectTotal = data.total || 0;
        const totalPages = Math.max(1, Math.ceil(state.projectTotal / state.projectPerPage));
        if (state.projectTotal > 0 && state.projectPage > totalPages) {
            state.projectPage = totalPages;
            return loadProjects();
        }
        renderProjects();
        renderProjectPagination();
    } catch (e) {
        toast(e.message, 'error');
    }
}

function renderProjects() {
    const tbody = el('projects-list');
    if (!state.projects.length) {
        tbody.innerHTML = `<tr><td colspan="7" class="empty-state">${t('projectEmpty')}</td></tr>`;
        el('project-select-all').checked = false;
        el('project-select-all-header').checked = false;
        updateProjectSelectionUI();
        return;
    }
    tbody.innerHTML = state.projects.map(p => {
        const checked = state.selectedProjects.has(p.name) ? 'checked' : '';
        const type = p.is_terraform ? t('terraformTab') : t('rosTab');
        const typeClass = p.is_terraform ? 'status-terraform' : 'status-ros';
        const updatedAt = p.updated_at ? Number(p.updated_at) * 1000 : null;
        const updatedText = updatedAt ? new Date(updatedAt).toLocaleString() : '-';
        const resourceCount = p.resource_count || 0;
        const testCount = p.test_count || 0;
        return `
        <tr class="clickable" data-name="${escapeHtml(p.name)}">
            <td><input type="checkbox" class="project-row-checkbox" data-name="${escapeHtml(p.name)}" ${checked}></td>
            <td><strong class="project-name-link" data-name="${escapeHtml(p.name)}">${escapeHtml(p.name)}</strong></td>
            <td><span class="status-badge ${typeClass}">${type}</span></td>
            <td><span class="${resourceCount ? '' : 'count-zero'}">${resourceCount || '—'}</span></td>
            <td><span class="${testCount ? '' : 'count-zero'}">${testCount || '—'}</span></td>
            <td>${updatedText}</td>
            <td class="actions-cell">
                <div class="actions-group">
                    <button class="btn btn-sm btn-view-project" data-name="${escapeHtml(p.name)}" title="${escapeHtml(t('viewBtnTooltip'))}">${t('viewBtn')}</button>
                    <button class="btn btn-sm btn-load-project" data-name="${escapeHtml(p.name)}" title="${escapeHtml(t('loadProjectBtnTooltip'))}">${t('loadProjectBtn')}</button>
                    <button class="btn btn-sm btn-edit-project" data-name="${escapeHtml(p.name)}" title="${escapeHtml(t('editProjectBtnTooltip'))}">${t('editProjectBtn')}</button>
                    <button class="btn btn-sm btn-danger btn-delete-project" data-name="${escapeHtml(p.name)}" title="${escapeHtml(t('deleteProjectBtnTooltip'))}">${t('deleteProjectBtn')}</button>
                </div>
            </td>
        </tr>`;
    }).join('');

    $$('.project-row-checkbox', tbody).forEach(cb => cb.addEventListener('change', (e) => {
        if (e.target.checked) state.selectedProjects.add(e.target.dataset.name);
        else state.selectedProjects.delete(e.target.dataset.name);
        updateProjectSelectionUI();
    }));
    $$('tr.clickable', tbody).forEach(tr => tr.addEventListener('click', (e) => {
        if (e.target.tagName === 'BUTTON' || e.target.type === 'checkbox' || e.target.closest('.project-name-link')) return;
        navigate('project-detail', { projectName: tr.dataset.name });
    }));
    $$('.project-name-link', tbody).forEach(n => n.addEventListener('click', () => navigate('project-detail', { projectName: n.dataset.name })));
    $$('.btn-view-project', tbody).forEach(b => b.addEventListener('click', () => navigate('project-detail', { projectName: b.dataset.name })));
    $$('.btn-load-project', tbody).forEach(b => b.addEventListener('click', () => loadProjectIntoPlayground(b.dataset.name)));
    $$('.btn-edit-project', tbody).forEach(b => b.addEventListener('click', () => openEditProject(b.dataset.name)));
    $$('.btn-delete-project', tbody).forEach(b => b.addEventListener('click', () => deleteProject(b.dataset.name)));
    updateProjectSelectionUI();
}

function updateProjectSelectionUI() {
    const allCheckbox = el('project-select-all');
    const headerCheckbox = el('project-select-all-header');
    const batchBtn = el('btn-batch-delete-project');
    const countEl = el('project-selected-count');
    const visibleNames = new Set(state.projects.map(p => p.name));
    const selectedVisible = state.projects.filter(p => state.selectedProjects.has(p.name));
    const allChecked = visibleNames.size > 0 && selectedVisible.length === visibleNames.size;
    allCheckbox.checked = allChecked;
    headerCheckbox.checked = allChecked;
    batchBtn.disabled = state.selectedProjects.size === 0;
    if (state.selectedProjects.size > 0) {
        countEl.textContent = t('selectedCount', { count: state.selectedProjects.size });
    } else {
        countEl.textContent = '';
    }
}

/* ============== Shared Pagination ============== */
function buildPaginationHTML(current, totalPages, total, perPage, perPageOptions, dataType) {
    // Generate page number list with ellipsis
    const pages = [];
    if (totalPages <= 7) {
        for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
        pages.push(1);
        if (current > 4) pages.push('...');
        const start = Math.max(2, current - 1);
        const end = Math.min(totalPages - 1, current + 1);
        for (let i = start; i <= end; i++) pages.push(i);
        if (current < totalPages - 3) pages.push('...');
        pages.push(totalPages);
    }

    let html = `<div class="pagination-right">`;
    html += `<span class="pagination-per-page-label">${t('perPageLabel')}</span>`;
    html += `<div class="pagination-per-page-wrapper" data-type="${dataType}">`;
    html += `<button type="button" class="pagination-per-page-trigger" data-type="${dataType}">`;
    html += `<span class="pagination-per-page-value">${perPage}</span>`;
    html += `<span class="pagination-per-page-arrow"></span>`;
    html += `</button>`;
    html += `<div class="pagination-per-page-dropdown">`;
    perPageOptions.forEach(opt => {
        html += `<div class="pagination-per-page-option ${opt === perPage ? 'selected' : ''}" data-value="${opt}" data-type="${dataType}">`;
        html += `<span class="pagination-per-page-check">${opt === perPage ? '✓' : ''}</span>`;
        html += `<span class="pagination-per-page-option-text">${opt}</span>`;
        html += `</div>`;
    });
    html += `</div>`;
    html += `</div>`;
    html += `<span class="pagination-total-info">${t('totalItems', { count: total })}</span>`;
    html += `<span class="pagination-sep"></span>`;
    html += `<button class="pagination-nav-btn" data-page="${current - 1}" ${current <= 1 ? 'disabled' : ''}>${t('prevPage')}</button>`;
    pages.forEach(p => {
        if (p === '...') {
            html += `<span class="pagination-ellipsis">...</span>`;
        } else {
            html += `<button class="pagination-page-btn ${p === current ? 'active' : ''}" data-page="${p}">${p}</button>`;
        }
    });
    html += `<button class="pagination-nav-btn" data-page="${current + 1}" ${current >= totalPages ? 'disabled' : ''}>${t('nextPage')}</button>`;
    html += `</div>`;

    return html;
}

function bindPaginationEvents(container, totalPages, onPageChange, onPerPageChange) {
    $$('button[data-page]', container).forEach(btn => {
        btn.addEventListener('click', () => {
            const page = Number(btn.dataset.page);
            if (page >= 1 && page <= totalPages) onPageChange(page);
        });
    });

    // Custom per-page dropdown
    const trigger = $('.pagination-per-page-trigger', container);
    const dropdown = $('.pagination-per-page-dropdown', container);
    const wrapper = $('.pagination-per-page-wrapper', container);
    if (trigger && dropdown) {
        trigger.addEventListener('click', (e) => {
            e.stopPropagation();
            // Close any other open dropdowns first
            document.querySelectorAll('.pagination-per-page-wrapper.open').forEach(w => {
                if (w !== wrapper) w.classList.remove('open');
            });
            wrapper.classList.toggle('open');
        });
        $$('.pagination-per-page-option', dropdown).forEach(opt => {
            opt.addEventListener('click', () => {
                const val = Number(opt.dataset.value);
                wrapper.classList.remove('open');
                onPerPageChange(val);
            });
        });
    }
}

// Global click handler to close pagination dropdowns (initialized once)
if (!window._paginationDropdownInit) {
    window._paginationDropdownInit = true;
    document.addEventListener('click', () => {
        document.querySelectorAll('.pagination-per-page-wrapper.open').forEach(w => {
            w.classList.remove('open');
        });
    });
}

function renderProjectPagination() {
    const container = el('project-pagination');
    const total = state.projectTotal;
    const perPage = state.projectPerPage;
    const totalPages = Math.max(1, Math.ceil(total / perPage));
    const current = Math.min(state.projectPage, totalPages);
    const perPageOptions = [12, 24, 48, 100];
    container.innerHTML = buildPaginationHTML(current, totalPages, total, perPage, perPageOptions, 'project');
    bindPaginationEvents(container, totalPages,
        (page) => { state.projectPage = page; loadProjects(); },
        (newPerPage) => { state.projectPerPage = newPerPage; state.projectPage = 1; loadProjects(); }
    );
}

async function batchDeleteProjects() {
    const names = Array.from(state.selectedProjects);
    if (!names.length) return;
    if (!await showConfirm(t('confirmBatchDeleteProject', { count: names.length }), { danger: true })) return;
    try {
        const res = await api('POST', '/api/projects/batch-delete', { names });
        state.selectedProjects.clear();
        toast(t('batchDeleted', { count: res.deleted?.length || 0 }), 'success');
        loadProjects();
    } catch (e) {
        toast(e.message, 'error');
    }
}

function populateProjectEditRegionSelect() {
    const sel = el('project-edit-region');
    if (!sel) return;
    const previousValue = sel.value;
    sel.innerHTML = '';
    let defaultIndex = -1;
    state.regions.forEach((r, idx) => {
        const opt = document.createElement('option');
        opt.value = r.id;
        opt.textContent = r.name || r.id;
        sel.appendChild(opt);
        if (r.id === 'cn-hangzhou') defaultIndex = idx;
    });
    let targetValue = '';
    if (previousValue && state.regions.some(r => r.id === previousValue)) {
        targetValue = previousValue;
    } else if (defaultIndex >= 0) {
        targetValue = state.regions[defaultIndex].id;
    } else if (state.regions.length) {
        targetValue = state.regions[0].id;
    }
    sel.value = targetValue;
    if (!sel.value && state.regions.length) sel.selectedIndex = 0;
}

async function generateParamsForProjectEdit() {
    const btn = el('project-edit-generate-params');
    setBtnLoading(btn, true);
    try {
        // Sync TF editor content back to state
        if (state.projectEditTfMode && state.projectEditTfActiveFile) {
            state.projectEditTfFiles[state.projectEditTfActiveFile] = el('project-edit-tf-template').value;
        }
        const payload = {};
        if (state.projectEditTfMode) {
            const files = {};
            for (const [p, content] of Object.entries(state.projectEditTfFiles)) {
                if (!p.endsWith('/')) files[p] = content;
            }
            payload.template_files = files;
        } else {
            payload.template_content = el('project-edit-template').value;
        }
        if (!payload.template_content && !payload.template_files) {
            toast(t('templateEmpty') || 'Template is empty', 'error');
            return;
        }
        const region = el('project-edit-region').value || 'cn-hangzhou';
        payload.regions = region;
        payload.config_content = el('project-edit-config').value;
        const res = await api('POST', '/api/generate-params', payload);
        if (res.parameters) {
            el('project-edit-config').value = res.parameters;
            highlightPeConfig();
            // Show logs in browser console for debugging
            if (res.logs) {
                console.log('[generate-params logs]\n' + res.logs);
            }
            if (res.warning) {
                toast(t('generateParamsWarning'), 'warning');
            } else {
                toast(t('generateParamsSuccess'), 'success');
            }
        }
    } catch (e) {
        toast(e.message || t('generateParamsFailed'), 'error');
    } finally {
        setBtnLoading(btn, false);
    }
}

async function openEditProject(name) {
    _editOriginalContent = null; // clear version-switch cache when opening modal
    try {
        const data = await api('GET', `/api/projects/${encodeURIComponent(name)}`);
        el('project-edit-name').value = name;
        el('project-edit-name').classList.remove('input-invalid');
        el('project-edit-name').title = '';
        const hintEl = el('project-edit-name-hint');
        if (hintEl) { hintEl.textContent = ''; hintEl.classList.remove('visible'); }
        const isTf = isTerraformProject(data);
        if (isTf) {
            state.projectEditTfFiles = { ...data.template_files };
            state.projectEditTfActiveFile = Object.keys(state.projectEditTfFiles).sort()[0] || null;
        } else {
            state.projectEditTfFiles = {};
            state.projectEditTfActiveFile = null;
        }

        // Read single config (fallback to legacy configs array)
        let config = data.config || '';
        if (!config && data.configs && data.configs.length) {
            config = data.configs[0].config || '';
        }
        state.projectEditConfig = extractParametersYaml(config);
        el('project-edit-config').value = state.projectEditConfig;
        highlightPeConfig();

        // Reset tf mode before switching tabs to avoid saving stale editor content into the loaded files.
        state.projectEditTfMode = false;
        el('project-edit-tf-template').value = '';
        setProjectEditTemplateTab(isTf ? 'terraform' : 'ros');
        if (!isTf) {
            el('project-edit-template').value = data.template || '';
            // Validate template format and show hint
            const templateHint = el('project-edit-template-hint');
            if (templateHint) {
                const err = validateTemplateFormat(data.template || '');
                templateHint.textContent = err || '';
                templateHint.classList.toggle('visible', !!err);
                el('project-edit-template').classList.toggle('input-invalid', !!err);
            }
            highlightPeTemplate();
        }
        if (isTf && state.projectEditTfActiveFile) {
            selectProjectEditTfFile(state.projectEditTfActiveFile);
        }

        state.projectEditNoDelete = Boolean(data.no_delete);
        state.projectEditKeepFailed = Boolean(data.keep_failed);
        state.projectEditDontWait = Boolean(data.dont_wait_for_delete);
        el('project-edit-no-delete').checked = state.projectEditNoDelete;
        el('project-edit-keep-failed').checked = state.projectEditKeepFailed;
        el('project-edit-dont-wait').checked = state.projectEditDontWait;

        el('project-edit-modal').dataset.name = name;
        el('project-edit-modal').classList.add('open');
        populateProjectEditRegionSelect();
        loadEditVersions(name);
        setTimeout(() => el('project-edit-name').select(), 50);
    } catch (e) {
        toast(e.message, 'error');
    }
}

function openNewProject() {
    el('project-edit-name').value = '';
    el('project-edit-name').classList.remove('input-invalid');
    el('project-edit-name').title = '';
    const hintEl = el('project-edit-name-hint');
    if (hintEl) { hintEl.textContent = ''; hintEl.classList.remove('visible'); }
    el('project-edit-template').value = '';
    el('project-edit-template').disabled = false;
    el('project-edit-template').classList.remove('input-invalid');
    const tplHint = el('project-edit-template-hint');
    if (tplHint) { tplHint.textContent = ''; tplHint.classList.remove('visible'); }
    state.projectEditTfFiles = {};
    state.projectEditTfActiveFile = null;
    state.projectEditConfig = DEFAULT_NEW_PROJECT_CONFIG;
    state.projectEditNoDelete = false;
    state.projectEditKeepFailed = false;
    state.projectEditDontWait = false;
    el('project-edit-no-delete').checked = false;
    el('project-edit-keep-failed').checked = false;
    el('project-edit-dont-wait').checked = false;
    el('project-edit-config').value = state.projectEditConfig;
    setProjectEditTemplateTab('ros');
    refreshPeHighlight();
    el('project-edit-modal').dataset.name = '';
    el('project-edit-modal').classList.add('open');
    populateProjectEditRegionSelect();
    loadEditVersions('');
    setTimeout(() => el('project-edit-name').focus(), 50);
}

function setProjectEditTemplateTab(tab) {
    if (state.projectEditTfMode && state.projectEditTfActiveFile) {
        state.projectEditTfFiles[state.projectEditTfActiveFile] = el('project-edit-tf-template').value;
    }
    state.projectEditTfMode = tab === 'terraform';
    el('project-edit-tab-ros').classList.toggle('active', tab === 'ros');
    el('project-edit-tab-terraform').classList.toggle('active', tab === 'terraform');
    el('project-edit-template').classList.toggle('hidden', tab !== 'ros');
    el('project-edit-tf-wrap').classList.toggle('hidden', tab !== 'terraform');
    if (state.projectEditTfMode) renderProjectEditTfFileList();
    highlightPeTemplate();
    highlightPeTf();
}

function renderProjectEditTfFileList() {
    const tree = el('project-edit-tf-file-tree');
    const paths = Object.keys(state.projectEditTfFiles).sort();
    if (!paths.length) {
        tree.innerHTML = `<div class="empty-state" style="padding:12px;font-size:12px;color:var(--text-muted)">${t('tfEmptyFiles')}</div>`;
        el('project-edit-tf-template').value = '';
        state.projectEditTfActiveFile = null;
        highlightPeTf();
        return;
    }
    tree.innerHTML = paths.map(path => {
        const isFolder = path.endsWith('/');
        return `
        <div class="tf-tree-node ${state.projectEditTfActiveFile === path ? 'active' : ''} ${isFolder ? 'folder' : ''}" data-pe-path="${escapeHtml(path)}">
            <span class="tf-tree-icon" style="visibility:hidden">▶</span>
            <span class="tf-tree-icon">${isFolder ? '📁' : '📄'}</span>
            <span class="tf-tree-name">${escapeHtml(isFolder ? path.slice(0, -1) : path)}</span>
            <div class="tf-tree-actions">
                <button class="tf-tree-action" data-pe-action="rename" title="${escapeHtml(t('renameBtn'))}">✎</button>
                <button class="tf-tree-action danger" data-pe-action="delete" title="${escapeHtml(t('deleteBtn'))}">✕</button>
            </div>
        </div>`;
    }).join('');
}

function selectProjectEditTfFile(path) {
    if (state.projectEditTfActiveFile && state.projectEditTfActiveFile !== path) {
        state.projectEditTfFiles[state.projectEditTfActiveFile] = el('project-edit-tf-template').value;
    }
    state.projectEditTfActiveFile = path;
    el('project-edit-tf-template').value = state.projectEditTfFiles[path] || '';
    renderProjectEditTfFileList();
    highlightPeTf();
}

async function addProjectEditTfFile() {
    const path = await showPrompt({ title: t('addFileTitle') || 'New Terraform File', placeholder: t('tfFileNamePlaceholder') || 'filename.tf' });
    if (!path) return;
    const clean = path.trim();
    if (!clean) return;
    if (state.projectEditTfFiles.hasOwnProperty(clean)) {
        toast(t('fileExists') || 'File already exists', 'error');
        return;
    }
    state.projectEditTfFiles[clean] = '';
    selectProjectEditTfFile(clean);
}

async function addProjectEditTfFolder() {
    const path = await showPrompt({ title: t('createFolderTitle') || 'Create Folder', placeholder: t('folderPlaceholder') || 'e.g. modules' });
    if (!path) return;
    const clean = path.trim();
    if (!clean) return;
    const folderKey = `${clean}/`;
    if (state.projectEditTfFiles.hasOwnProperty(folderKey) || state.projectEditTfFiles.hasOwnProperty(clean)) {
        toast(t('pathExists') || 'Folder already exists', 'error');
        return;
    }
    state.projectEditTfFiles[folderKey] = '';
    renderProjectEditTfFileList();
}

async function renameProjectEditTfFile(oldPath) {
    const newPath = await showPrompt({ title: t('renameFileTitle') || 'Rename File', placeholder: t('tfFileNamePlaceholder') || 'filename.tf', defaultValue: oldPath });
    if (!newPath) return;
    const clean = newPath.trim();
    if (!clean || clean === oldPath) return;
    if (state.projectEditTfFiles.hasOwnProperty(clean)) {
        toast(t('fileExists') || 'File already exists', 'error');
        return;
    }
    const content = state.projectEditTfFiles[oldPath];
    delete state.projectEditTfFiles[oldPath];
    state.projectEditTfFiles[clean] = content;
    if (state.projectEditTfActiveFile === oldPath) state.projectEditTfActiveFile = clean;
    renderProjectEditTfFileList();
    if (state.projectEditTfActiveFile === clean) selectProjectEditTfFile(clean);
}

async function deleteProjectEditTfFile(path) {
    if (!await showConfirm(t('confirmDeleteFile', { name: path }) || `Delete file "${path}"?`, { danger: true })) return;
    delete state.projectEditTfFiles[path];
    if (state.projectEditTfActiveFile === path) {
        const remaining = Object.keys(state.projectEditTfFiles).sort();
        state.projectEditTfActiveFile = remaining.length ? remaining[0] : null;
    }
    if (state.projectEditTfActiveFile) selectProjectEditTfFile(state.projectEditTfActiveFile);
    else renderProjectEditTfFileList();
}

function hasValidTfFiles(files) {
    if (!files || typeof files !== 'object') return false;
    return Object.entries(files).some(([name, content]) =>
        Boolean(content) && String(name).endsWith('.tf')
    );
}

function isTerraformProject(project) {
    return hasValidTfFiles(project && project.template_files);
}

function renderCustomSelectOptions(containerId, items, selectedValue) {
    const container = el(containerId);
    const triggerText = container.querySelector('.custom-select-text');
    const dropdown = container.querySelector('.custom-select-dropdown');
    const normalizedSelected = String(selectedValue);
    const selectedItem = items.find(item => String(item.value) === normalizedSelected) || items[0];
    container.dataset.value = selectedItem ? String(selectedItem.value) : '';
    if (triggerText) triggerText.textContent = selectedItem ? selectedItem.label : '';
    dropdown.innerHTML = items.map(item =>
        `<div class="custom-select-option ${String(item.value) === normalizedSelected ? 'selected' : ''}" data-value="${item.value}">${escapeHtml(item.label)}</div>`
    ).join('');
}

function initCustomSelect(containerId, onSelect) {
    const container = el(containerId);
    const trigger = container.querySelector('.custom-select-trigger');
    trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = container.classList.contains('open');
        closeAllCustomSelects();
        if (!isOpen) container.classList.add('open');
    });
    container.addEventListener('click', (e) => {
        const option = e.target.closest('.custom-select-option');
        if (!option) return;
        e.stopPropagation();
        const value = option.dataset.value;
        const text = option.textContent;
        container.dataset.value = value;
        const triggerText = container.querySelector('.custom-select-text');
        if (triggerText) triggerText.textContent = text;
        container.querySelectorAll('.custom-select-option').forEach(opt => opt.classList.toggle('selected', opt.dataset.value === value));
        if (onSelect) onSelect(value);
        closeAllCustomSelects();
    });
}

function closeAllCustomSelects() {
    $$('.custom-select.open').forEach(c => c.classList.remove('open'));
}

async function saveEditProject(allowOverwrite = false) {
    const oldName = el('project-edit-modal').dataset.name;
    const newName = el('project-edit-name').value.trim();
    const nameErr = validateProjectName(newName);
    if (nameErr) { el('project-edit-name').focus(); return toast(nameErr, 'error'); }
    const isRename = oldName && oldName !== newName;
    if (isRename && !allowOverwrite && state.projects.some(p => p.name === newName)) {
        if (await confirmOverwrite(newName)) await saveEditProject(true);
        return;
    }
    const btn = el('project-edit-save');
    setBtnLoading(btn, true);
    try {
        const isTf = state.projectEditTfMode;
        const payload = {
            name: newName,
            config: el('project-edit-config').value,
            no_delete: el('project-edit-no-delete').checked,
            keep_failed: el('project-edit-keep-failed').checked,
            dont_wait_for_delete: el('project-edit-dont-wait').checked,
        };
        if (isTf) {
            if (state.projectEditTfActiveFile) {
                state.projectEditTfFiles[state.projectEditTfActiveFile] = el('project-edit-tf-template').value;
            }
            const tfFiles = { ...state.projectEditTfFiles };
            const hasTfFiles = hasValidTfFiles(tfFiles);
            payload.template = '';
            payload.template_files = hasTfFiles ? tfFiles : {};
        } else {
            payload.template = el('project-edit-template').value;
            payload.template_files = {};
        }
        if (oldName && oldName !== newName) payload.old_name = oldName;
        // When editing the same project (name unchanged), always allow overwrite
        if (allowOverwrite || (oldName && oldName === newName)) payload.allow_overwrite = true;
        await api('POST', '/api/projects', payload);
        _editOriginalContent = null; // clear version-switch cache after save
        el('project-edit-modal').classList.remove('open');
        toast(t('saved'), 'success');
        loadProjects();
        if (state.page === 'project-detail') {
            navigate('project-detail', { projectName: newName });
        }
    } catch (e) {
        if (e.message === 'conflict' || (e.message && e.message.includes('conflict'))) {
            // Only prompt overwrite when renaming to an existing name
            setBtnLoading(btn, false);
            if (await confirmOverwrite(newName)) await saveEditProject(true);
            return;
        }
        toast(e.message, 'error');
    } finally {
        setBtnLoading(btn, false);
    }
}

async function loadProjectIntoPlayground(name) {
    try {
        const data = await api('GET', `/api/projects/${encodeURIComponent(name)}`);
        let config = data.config || '';
        if (!config && data.configs && data.configs.length) {
            config = data.configs[0].config || '';
        }
        if (isTerraformProject(data)) {
            enterTfMode(data.template_files);
        } else {
            if (state.tfMode) exitTfMode();
            el('template-editor').value = data.template || '';
        }
        el('config-editor').value = extractParametersYaml(config);
        highlightConfig();
        // Clear previous action results/logs and expand the template editor area
        state.currentAction = null;
        clearResultPanel();
        focusTemplateEditor();
        navigate('playground');
        toast(t('loadedProject', { name }));
    } catch (e) {
        toast(e.message, 'error');
    }
}

function getProjectSavePayload() {
    const payload = {
        template: el('template-editor').value,
        config: el('config-editor').value,
    };
    if (state.tfMode) {
        if (state.tfActiveFile && state.tfFiles.hasOwnProperty(state.tfActiveFile)) {
            state.tfFiles[state.tfActiveFile] = el('template-editor').value;
        }
        const tfFiles = { ...state.tfFiles };
        const hasTfFiles = hasValidTfFiles(tfFiles);
        payload.template = '';
        payload.template_files = hasTfFiles ? tfFiles : {};
    } else {
        payload.template_files = {};
    }
    return payload;
}

async function pgSaveFromPlayground(allowOverwrite = false) {
    const nameInput = el('pg-project-name-input');
    const name = nameInput.value.trim();
    const nameErr = validateProjectName(name);
    if (nameErr) { nameInput.focus(); return toast(nameErr, 'error'); }
    if (!allowOverwrite && state.projects.some(p => p.name === name)) {
        if (await confirmOverwrite(name)) await pgSaveFromPlayground(true);
        return;
    }
    const btn = el('btn-pg-save-confirm');
    setBtnLoading(btn, true);
    try {
        const savePayload = getProjectSavePayload();
        const regions = state.pgRegionSelect ? state.pgRegionSelect.getSelected().join(',') : '';
        const fullConfig = buildFullConfigYaml(savePayload.config, regions, name);
        const payload = {
            name,
            template: savePayload.template,
            template_files: savePayload.template_files,
            config: fullConfig,
        };
        if (allowOverwrite) payload.allow_overwrite = true;
        await api('POST', '/api/projects', payload);
        el('pg-save-popover').classList.remove('open');
        nameInput.value = '';
        toast(t('saved'), 'success');
    } catch (e) {
        if (e.message === 'conflict' || (e.message && e.message.includes('conflict'))) {
            setBtnLoading(btn, false);
            if (await confirmOverwrite(name)) await pgSaveFromPlayground(true);
            return;
        }
        toast(e.message, 'error');
    } finally {
        setBtnLoading(btn, false);
    }
}

async function deleteProject(name) {
    if (!await showConfirm(t('confirmDeleteProject', { name }), { danger: true })) return;
    try {
        await api('DELETE', `/api/projects/${encodeURIComponent(name)}`);
        toast(t('deleted'), 'success');
        loadProjects();
    } catch (e) {
        toast(e.message, 'error');
    }
}

function bindProjects() {
    el('project-edit-save').addEventListener('click', () => saveEditProject());
    el('project-edit-close').addEventListener('click', () => { _editOriginalContent = null; el('project-edit-modal').classList.remove('open'); });
    el('project-edit-modal').addEventListener('click', (e) => {
        if (e.target === el('project-edit-modal')) { _editOriginalContent = null; el('project-edit-modal').classList.remove('open'); }
    });
    const projectEditNameInput = el('project-edit-name');
    bindProjectNameLive(projectEditNameInput, el('project-edit-save'));
    bindTemplateFormatLive(el('project-edit-template'), el('project-edit-template-hint'));
    el('project-edit-generate-params').addEventListener('click', generateParamsForProjectEdit);
    el('project-edit-tab-ros').addEventListener('click', () => setProjectEditTemplateTab('ros'));
    el('project-edit-tab-terraform').addEventListener('click', () => setProjectEditTemplateTab('terraform'));
    // Highlight + scroll sync for project edit editors
    el('project-edit-template').addEventListener('input', highlightPeTemplate);
    el('project-edit-template').addEventListener('scroll', syncPeHighlightScroll);
    el('project-edit-tf-template').addEventListener('input', highlightPeTf);
    el('project-edit-tf-template').addEventListener('scroll', syncPeHighlightScroll);
    el('project-edit-config').addEventListener('input', highlightPeConfig);
    el('project-edit-config').addEventListener('scroll', syncPeHighlightScroll);
    el('project-edit-tf-file-tree').addEventListener('click', (e) => {
        const actionBtn = e.target.closest('[data-pe-action]');
        const node = e.target.closest('[data-pe-path]');
        if (actionBtn && node) {
            e.stopPropagation();
            const path = node.dataset.pePath;
            if (actionBtn.dataset.peAction === 'rename') renameProjectEditTfFile(path);
            else if (actionBtn.dataset.peAction === 'delete') deleteProjectEditTfFile(path);
            return;
        }
        if (node) {
            const path = node.dataset.pePath;
            if (path.endsWith('/')) return; // folders are not selectable
            selectProjectEditTfFile(path);
        }
    });
    function positionProjectEditDropdown(dropdown, trigger) {
        const rect = trigger.getBoundingClientRect();
        dropdown.style.top = `${rect.bottom + 4}px`;
        dropdown.style.right = `${window.innerWidth - rect.right}px`;
        dropdown.style.left = 'auto';
        dropdown.style.minWidth = `${Math.max(150, rect.width)}px`;
    }
    el('project-edit-tf-open-trigger').addEventListener('click', (e) => {
        e.stopPropagation();
        const menu = el('project-edit-tf-open-menu');
        const wasOpen = menu.classList.contains('open');
        menu.classList.toggle('open');
        if (!wasOpen) {
            positionProjectEditDropdown(el('project-edit-tf-open-dropdown'), el('project-edit-tf-open-trigger'));
        }
    });
    el('project-edit-tf-open-dropdown').addEventListener('click', (e) => {
        const folderItem = e.target.closest('#project-edit-open-folder-item');
        const fileLabel = e.target.closest('label.tf-open-item');
        if (folderItem) {
            el('project-edit-tf-open-menu').classList.remove('open');
            el('project-edit-upload-template-dir').click();
        } else if (fileLabel) {
            el('project-edit-tf-open-menu').classList.remove('open');
        }
    });
    el('project-edit-upload-template-file').addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => {
            setProjectEditTemplateTab('terraform');
            state.projectEditTfFiles = { [file.name]: ev.target.result };
            state.projectEditTfActiveFile = null;
            selectProjectEditTfFile(file.name);
        };
        reader.readAsText(file);
        e.target.value = '';
    });
    el('project-edit-upload-template-dir').addEventListener('change', (e) => {
        loadProjectEditLocalTfFiles(Array.from(e.target.files || []));
        e.target.value = '';
    });
    el('project-edit-tf-add-trigger').addEventListener('click', (e) => {
        e.stopPropagation();
        const menu = el('project-edit-tf-add-menu');
        const wasOpen = menu.classList.contains('open');
        menu.classList.toggle('open');
        if (!wasOpen) {
            positionProjectEditDropdown(el('project-edit-tf-add-dropdown'), el('project-edit-tf-add-trigger'));
        }
    });
    el('project-edit-tf-add-dropdown').addEventListener('click', (e) => {
        const item = e.target.closest('[data-pe-tf-action]');
        if (!item) return;
        el('project-edit-tf-add-menu').classList.remove('open');
        if (item.dataset.peTfAction === 'file') addProjectEditTfFile();
        else if (item.dataset.peTfAction === 'folder') addProjectEditTfFolder();
    });
    el('project-edit-tf-clear').addEventListener('click', async () => {
        if (!Object.keys(state.projectEditTfFiles).length) return;
        if (!await showConfirm(t('clearTfConfirm') || 'Clear all Terraform files?', { danger: true })) return;
        state.projectEditTfFiles = {};
        state.projectEditTfActiveFile = null;
        renderProjectEditTfFileList();
        el('project-edit-tf-template').value = '';
    });
    el('project-edit-tf-template').addEventListener('input', () => {
        if (state.projectEditTfActiveFile) {
            state.projectEditTfFiles[state.projectEditTfActiveFile] = el('project-edit-tf-template').value;
        }
    });
    window.addEventListener('resize', () => {
        el('project-edit-tf-open-menu').classList.remove('open');
        el('project-edit-tf-add-menu').classList.remove('open');
    });
    document.addEventListener('click', (e) => {
        if (!e.target.closest('#project-edit-tf-open-menu')) {
            el('project-edit-tf-open-menu').classList.remove('open');
        }
        if (!e.target.closest('#project-edit-tf-add-menu')) {
            el('project-edit-tf-add-menu').classList.remove('open');
        }
        if (!e.target.closest('.custom-select')) {
            closeAllCustomSelects();
        }
    });
    el('btn-new-project').addEventListener('click', openNewProject);
    el('project-edit-version-select').addEventListener('change', () => {
        const name = el('project-edit-modal').dataset.name;
        if (name) onEditVersionChange(name);
    });
    el('btn-batch-delete-project').addEventListener('click', batchDeleteProjects);
    const selectAllHandler = (e) => {
        state.projects.forEach(p => {
            if (e.target.checked) state.selectedProjects.add(p.name);
            else state.selectedProjects.delete(p.name);
        });
        renderProjects();
    };
    el('project-select-all').addEventListener('change', selectAllHandler);
    el('project-select-all-header').addEventListener('change', selectAllHandler);
    el('project-search').addEventListener('input', debounceProjectSearch);
}

let _projectSearchTimer = null;
function debounceProjectSearch() {
    clearTimeout(_projectSearchTimer);
    _projectSearchTimer = setTimeout(() => {
        state.projectSearch = el('project-search').value.trim();
        state.projectPage = 1;
        state.selectedProjects.clear();
        loadProjects();
    }, 300);
}

/* ============== Shared Stack Utilities ============== */

function isStackFailed(s) {
    const st = (s.status || '').toLowerCase();
    return st.includes('fail') || st.includes('rollback');
}

function calcStackStats(stacks) {
    const total = stacks.length;
    const succeeded = stacks.filter(s => s.launch_succeeded && !isStackFailed(s)).length;
    const ratio = total > 0 ? Math.round(succeeded / total * 100) : 0;
    let ratioColor = '';
    if (ratio === 100) ratioColor = 'pd-stack-stat-succeeded';
    else if (ratio === 0) ratioColor = 'pd-stack-stat-failed';
    return { total, succeeded, ratio, ratioColor };
}

/* ============== Tasks ============== */
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled']);

function isTerminalStatus(status) {
    return TERMINAL_STATUSES.has(status);
}

function startTaskPolling() {
    if (state.taskTimer) return;
    state.taskTimer = setInterval(async () => {
        if (state.page === 'tasks') {
            await loadTasks();
        } else if (state.page === 'detail' && state.currentRunId) {
            // On detail page, only fetch the current run instead of the full task list
            await loadDetail(state.currentRunId);
        }
        if (state.page === 'project-detail' && state.currentProjectName) {
            await pollProjectRuns(state.currentProjectName);
        }
        checkStopTaskPolling();
    }, 5000);
}

function stopTaskPolling() {
    if (!state.taskTimer) return;
    clearInterval(state.taskTimer);
    state.taskTimer = null;
}

function checkStopTaskPolling() {
    if (state.page === 'tasks') {
        if (state.tasks.length === 0 || state.tasks.every(r => isTerminalStatus(r.status))) {
            stopTaskPolling();
        }
    } else if (state.page === 'detail' && state.currentRun) {
        if (isTerminalStatus(state.currentRun.status)) {
            stopTaskPolling();
        }
    } else if (state.page === 'project-detail') {
        const runs = state.currentProjectRuns || [];
        if (runs.length === 0 || runs.every(r => isTerminalStatus(r.status))) {
            stopTaskPolling();
        }
    }
}

async function loadTasks() {
    const reqId = ++state.taskRequestId;
    try {
        const params = new URLSearchParams();
        params.set('page', String(state.taskPage));
        params.set('per_page', String(state.taskPerPage));
        if (state.taskSearch) params.set('search', state.taskSearch);
        if (state.taskStatusFilter) params.set('status', state.taskStatusFilter);
        const data = await api('GET', `/api/runs?${params.toString()}`);
        if (reqId !== state.taskRequestId) return;
        const runs = data.runs || [];
        logTaskCompletion(runs);
        state.tasks = runs;
        state.taskTotal = data.total || 0;
        const taskTotalPages = Math.max(1, Math.ceil(state.taskTotal / state.taskPerPage));
        if (state.taskTotal > 0 && state.taskPage > taskTotalPages) {
            state.taskPage = taskTotalPages;
            return loadTasks();
        }
        state.taskStatusMap = Object.fromEntries(runs.map(r => [r.id, r.status]));
        if (state.page === 'tasks') {
            renderTasks();
            checkStopTaskPolling();
        }
        if (state.page === 'detail' && state.currentRunId) loadDetail(state.currentRunId);
    } catch (e) {
        console.warn('load tasks failed', e.message);
    }
}

function logTaskCompletion(runs) {
    runs.forEach(r => {
        const prev = state.taskStatusMap[r.id];
        if (!prev || prev === r.status) return;
        if (isTerminalStatus(r.status)) {
            const statusLabel = t('status' + r.status.charAt(0).toUpperCase() + r.status.slice(1));
            const dur = duration(r.created_at, r.completed_at);
            consoleLog(t('runFinished', { name: r.name, status: statusLabel, duration: dur }), { type: r.status === 'completed' ? 'success' : 'error', action: 'run' });
        }
    });
}

function renderTasks() {
    const tbody = el('tasks-list');
    if (!state.tasks.length) {
        tbody.innerHTML = `<tr><td colspan="8" class="empty-state">${t('taskEmpty')}</td></tr>`;
        el('task-select-all-header').checked = false;
        updateTaskSelectionUI();
        renderTaskPagination();
        return;
    }
    tbody.innerHTML = state.tasks.map(r => {
        const statusClass = `status-${r.status}`;
        const progressClass = r.status === 'completed' ? 'completed' : (r.status === 'failed' ? 'failed' : '');
        const checked = state.selectedTasks.has(r.id) ? 'checked' : '';
        return `
        <tr class="clickable" data-id="${r.id}">
            <td><input type="checkbox" class="task-row-checkbox" data-id="${r.id}" ${checked}></td>
            <td><strong class="task-name-link">${escapeHtml(r.name)}</strong><br><code style="font-size:11px;color:var(--text-muted)">${r.id}</code></td>
            <td><span class="status-badge ${statusClass}">${t('status' + r.status.charAt(0).toUpperCase() + r.status.slice(1))}</span></td>
            <td>
                <div style="display:flex;align-items:center;gap:8px">
                    <div class="progress-bar"><div class="progress-fill ${progressClass}" style="width:${r.progress || 0}%"></div></div>
                    <span style="font-size:12px;color:var(--text-muted)">${r.progress || 0}%</span>
                </div>
            </td>
            <td>${formatTime(r.created_at)}</td>
            <td>${duration(r.created_at, r.completed_at)}</td>
            <td class="actions-cell" style="text-align:center">
                <div class="actions-group">
                    ${r.report_url ? `<a href="${escapeHtml(authUrl(r.report_url))}" target="_blank" class="btn btn-sm btn-view-report" data-id="${r.id}">${t('viewReportBtn')}</a>` : ''}
                    ${r.status === 'running' ? `<button class="btn btn-sm btn-cancel-task" data-id="${r.id}">${t('cancelBtn')}</button>` : ''}
                    <button class="btn btn-sm btn-danger btn-delete-task" data-id="${r.id}" data-name="${escapeHtml(r.name)}">${t('deleteBtn')}</button>
                </div>
            </td>
        </tr>`;
    }).join('');

    $$('.task-row-checkbox', tbody).forEach(cb => cb.addEventListener('change', (e) => {
        if (e.target.checked) state.selectedTasks.add(e.target.dataset.id);
        else state.selectedTasks.delete(e.target.dataset.id);
        updateTaskSelectionUI();
    }));
    $$('tr.clickable', tbody).forEach(tr => tr.addEventListener('click', (e) => {
        if (e.target.tagName === 'BUTTON' || e.target.tagName === 'A' || e.target.type === 'checkbox') return;
        navigate('detail', { runId: tr.dataset.id });
    }));
    $$('.btn-view-task', tbody).forEach(b => b.addEventListener('click', () => navigate('detail', { runId: b.dataset.id })));
    $$('.btn-cancel-task', tbody).forEach(b => b.addEventListener('click', () => cancelTask(b.dataset.id)));
    $$('.btn-delete-task', tbody).forEach(b => b.addEventListener('click', () => deleteTask(b.dataset.id, b.dataset.name)));
    updateTaskSelectionUI();
    renderTaskPagination();
}

function updateTaskSelectionUI() {
    const headerCheckbox = el('task-select-all-header');
    const batchBtn = el('btn-batch-delete-task');
    const countEl = el('task-selected-count');
    const visibleIds = new Set(state.tasks.map(r => r.id));
    const selectedVisible = state.tasks.filter(r => state.selectedTasks.has(r.id));
    const allChecked = visibleIds.size > 0 && selectedVisible.length === visibleIds.size;
    headerCheckbox.checked = allChecked;
    batchBtn.disabled = state.selectedTasks.size === 0;
    if (state.selectedTasks.size > 0) {
        countEl.textContent = t('selectedCount', { count: state.selectedTasks.size });
    } else {
        countEl.textContent = '';
    }
}

function renderTaskPagination() {
    const container = el('task-pagination');
    const total = state.taskTotal;
    const perPage = state.taskPerPage;
    const totalPages = Math.max(1, Math.ceil(total / perPage));
    const current = Math.min(state.taskPage, totalPages);
    const perPageOptions = [10, 20, 50, 100];
    container.innerHTML = buildPaginationHTML(current, totalPages, total, perPage, perPageOptions, 'task');
    bindPaginationEvents(container, totalPages,
        (page) => { state.taskPage = page; loadTasks(); },
        (newPerPage) => { state.taskPerPage = newPerPage; state.taskPage = 1; loadTasks(); }
    );
}

async function cancelTask(id) {
    const run = state.tasks.find(t => t.id === id);
    if (run && !await showConfirm(t('confirmCancelTask', { name: run.name }))) return;
    try {
        await api('POST', `/api/runs/${id}/cancel`);
        toast(t('cancelled'), 'success');
        loadTasks();
    } catch (e) {
        toast(e.message, 'error');
    }
}

async function deleteTask(id, name) {
    if (!await showConfirm(t('confirmDeleteTask', { name }), { danger: true })) return;
    try {
        await api('DELETE', `/api/runs/${id}`);
        toast(t('deleted'), 'success');
        if (state.currentRunId === id && state.page === 'detail') navigate('tasks');
        state.selectedTasks.delete(id);
        loadTasks();
    } catch (e) {
        toast(e.message, 'error');
    }
}

async function batchDeleteTasks() {
    const ids = Array.from(state.selectedTasks);
    if (!ids.length) return;
    if (!await showConfirm(t('confirmBatchDeleteTask', { count: ids.length }), { danger: true })) return;
    try {
        const res = await api('POST', '/api/runs/batch-delete', { ids });
        state.selectedTasks.clear();
        toast(t('batchDeleted', { count: res.deleted?.length || 0 }), 'success');
        loadTasks();
    } catch (e) {
        toast(e.message, 'error');
    }
}

let _taskSearchTimer = null;
function debounceTaskSearch() {
    clearTimeout(_taskSearchTimer);
    _taskSearchTimer = setTimeout(() => {
        state.taskSearch = el('task-search').value.trim();
        state.taskPage = 1;
        state.selectedTasks.clear();
        loadTasks();
    }, 300);
}

function getTaskStatusOptions() {
    return [
        { value: '', label: t('allStatuses') },
        { value: 'pending', label: t('statusPending') },
        { value: 'running', label: t('statusRunning') },
        { value: 'completed', label: t('statusCompleted') },
        { value: 'failed', label: t('statusFailed') },
        { value: 'cancelled', label: t('statusCancelled') },
    ];
}

function initTaskStatusSelect() {
    state.taskStatusSelect = new CustomSelect('task-status-filter', (value) => {
        state.taskStatusFilter = value;
        state.taskPage = 1;
        state.selectedTasks.clear();
        loadTasks();
    });
    state.taskStatusSelect.setData(getTaskStatusOptions(), state.taskStatusFilter);
}

function bindTasks() {
    el('btn-batch-delete-task').addEventListener('click', batchDeleteTasks);
    const toggleAll = (checked) => {
        state.tasks.forEach(r => {
            if (checked) state.selectedTasks.add(r.id);
            else state.selectedTasks.delete(r.id);
        });
        renderTasks();
    };
    el('task-select-all-header').addEventListener('change', (e) => toggleAll(e.target.checked));
    el('task-search').addEventListener('input', debounceTaskSearch);
    initTaskStatusSelect();
}

/* ============== Task Detail ============== */
async function loadDetail(id) {
    try {
        const run = await api('GET', `/api/runs/${id}`);
        state.currentRunId = id;
        state.currentRun = run;
        // Reset to overview only on initial navigation, not on polling refresh
        if (state._detailNeedsTabReset) {
            state._detailNeedsTabReset = false;
            switchTaskDetailTab('overview');
        }
        renderDetail(run);
        checkStopTaskPolling();
    } catch (e) {
        toast(e.message, 'error');
    }
}

function renderDetail(run) {
    const statusLabel = t('status' + run.status.charAt(0).toUpperCase() + run.status.slice(1));
    const stacks = Array.isArray(run.stacks) ? run.stacks : [];

    // Calculate stack statistics
    const { total: totalStacks, succeeded: succeededStacks, ratio: successRatio, ratioColor } = calcStackStats(stacks);
    const failedStacks = stacks.filter(s => isStackFailed(s) || !s.launch_succeeded).length;

    const stackStatsItems = totalStacks > 0 ? `
                    <div class="pd-kv-item"><span class="pd-kv-label">${t('stackTotal')}</span><span class="pd-kv-value">${totalStacks}</span></div>
                    <div class="pd-kv-item"><span class="pd-kv-label">${t('stackSuccessRatio')}</span><span class="pd-kv-value ${ratioColor}">${succeededStacks}/${totalStacks} (${successRatio}%)</span></div>` : '';

    el('detail-overview').innerHTML = `
        <div class="pd-section" id="td-section-basic">
            <div class="pd-section-title">${t('basicInfo')}</div>
            <div class="pd-section-body">
                <div class="pd-kv-grid">
                    <div class="pd-kv-item"><span class="pd-kv-label" data-i18n="detailName">Name</span><span class="pd-kv-value">${escapeHtml(run.name)}</span></div>
                    <div class="pd-kv-item"><span class="pd-kv-label" data-i18n="detailStatus">Status</span><span class="pd-kv-value"><span class="status-badge status-${run.status}">${statusLabel}</span></span></div>
                    <div class="pd-kv-item"><span class="pd-kv-label" data-i18n="detailProgress">Progress</span><span class="pd-kv-value">${run.progress || 0}%</span></div>
                    <div class="pd-kv-item"><span class="pd-kv-label" data-i18n="detailCreated">Created</span><span class="pd-kv-value">${formatTime(run.created_at)}</span></div>
                    <div class="pd-kv-item"><span class="pd-kv-label" data-i18n="detailDuration">Duration</span><span class="pd-kv-value">${duration(run.created_at, run.completed_at)}</span></div>
                    ${run.report_url ? `<div class="pd-kv-item"><span class="pd-kv-label" data-i18n="detailReport">Report</span><span class="pd-kv-value"><a href="${escapeHtml(authUrl(run.report_url))}" target="_blank" class="btn btn-sm btn-view-report">${t('viewReportBtn')}</a></span></div>` : ''}
                    ${stackStatsItems}
                </div>
            </div>
        </div>
    `;

    // Stacks tab
    renderDetailStacks(run);

    // Header actions
    const headerActions = el('detail-header-actions');
    headerActions.innerHTML = `
        ${run.status === 'running' ? `<button class="btn btn-sm btn-cancel-task" data-id="${run.id}">${t('cancelBtn')}</button>` : ''}
        ${stacks.some(s => s.stack_id && !String(s.status).startsWith('DELETE')) ? `<button class="btn btn-sm btn-danger btn-delete-stacks" data-id="${run.id}">${t('deleteStacksBtn')}</button>` : ''}
    `;

    // Template, Params & Logs tabs
    renderRunTemplate(run);
    renderRunConfig(run);
    renderCliLogs(run.id);
    renderAll();

    // Bind header actions
    $$('.btn-cancel-task', headerActions).forEach(b => b.addEventListener('click', () => cancelTask(b.dataset.id)));
    $$('.btn-delete-stacks', headerActions).forEach(b => b.addEventListener('click', () => deleteRunStacks(b.dataset.id)));

    // Bind report button
    const overviewEl = el('detail-overview');
    $$('.btn-view-report', overviewEl).forEach(b => b.addEventListener('click', (e) => {
        e.preventDefault();
        openReportModal(b.closest('a')?.href || b.dataset.url);
    }));
}

function renderDetailStacks(run) {
    const stacks = Array.isArray(run.stacks) ? run.stacks : [];
    const stacksEl = el('detail-stacks');
    if (!stacksEl) return;

    if (!stacks.length) {
        stacksEl.innerHTML = `<div class="empty-state">${t('noStacks')}</div>`;
        return;
    }

    // Pagination
    const perPage = state._stacksPerPage || 10;
    const totalPages = Math.max(1, Math.ceil(stacks.length / perPage));
    const currentPage = Math.min(state._stacksPage || 1, totalPages);
    state._stacksPage = currentPage;
    const startIdx = (currentPage - 1) * perPage;
    const pageStacks = stacks.slice(startIdx, startIdx + perPage);

    // List header
    let html = `<div class="pd-stack-list">
        <div class="pd-stack-list-header">
            <span class="pd-stack-col-arrow"></span>
            <span class="pd-stack-col-id">${t('stackNameOrId')}</span>
            <span class="pd-stack-col-region">${t('stackRegion')}</span>
            <span class="pd-stack-col-status">${t('stackStatus')}</span>
            <span class="pd-stack-col-succeeded">${t('launchSucceeded')}</span>
        </div>`;

    // Stack rows
    html += pageStacks.map((s, i) => {
        const globalIdx = startIdx + i;
        const failed = isStackFailed(s);
        const regionId = typeof s.region === 'object' ? (s.region?.id || '') : (s.region || '');
        const rosUrl = s.stack_id && regionId
            ? `https://ros.console.aliyun.com/${encodeURIComponent(regionId)}/stacks/${encodeURIComponent(s.stack_id)}`
            : '';

        const nameText = escapeHtml(s.stack_name || s.test_name || '-');
        const idText = s.stack_id || '';
        const nameHtml = `<span class="res-name">${nameText}</span>`;
        const idHtml = idText
            ? (rosUrl
                ? `<a class="stack-id-text stack-link" href="${rosUrl}" target="_blank" rel="noopener">${escapeHtml(idText)}</a>`
                : `<span class="stack-id-text">${escapeHtml(idText)}</span>`)
            : '';
        const idCellHtml = `<div class="stack-name-cell">${nameHtml}${idHtml}</div>`;

        const statusHtml = `<span class="status-badge status-${(s.status || '').toLowerCase().replace(/_/g, '-')}">${escapeHtml(tStackStatus(s.status) || 'Unknown')}</span>`;
        const succeededHtml = s.launch_succeeded !== undefined
            ? `<span class="${s.launch_succeeded ? 'pd-stack-stat-succeeded' : 'pd-stack-stat-failed'}">${s.launch_succeeded ? t('yes') : t('no')}</span>`
            : '-';

        // Expanded detail items
        const detailItems = [];
        if (s.test_name) detailItems.push(`<div class="pd-kv-item"><span class="pd-kv-label">${t('testName')}</span><span class="pd-kv-value">${escapeHtml(s.test_name)}</span></div>`);
        if (s.stack_name) detailItems.push(`<div class="pd-kv-item"><span class="pd-kv-label">${t('stackName')}</span><span class="pd-kv-value">${escapeHtml(s.stack_name)}</span></div>`);
        detailItems.push(
            `<div class="pd-kv-item"><span class="pd-kv-label">${t('stackStatus')}</span><span class="pd-kv-value"><span class="status-badge status-${(s.status || '').toLowerCase().replace(/_/g, '-')}">${escapeHtml(tStackStatus(s.status) || 'Unknown')}</span></span></div>`,
        );
        if (s.create_time) detailItems.push(`<div class="pd-kv-item"><span class="pd-kv-label">${t('createTime')}</span><span class="pd-kv-value">${formatTime(s.create_time)}</span></div>`);
        if (s.status_time) {
            const isDelete = (s.status || '').startsWith('DELETE');
            const timeLabel = isDelete ? t('deleteTime') : t('updateTime');
            detailItems.push(`<div class="pd-kv-item"><span class="pd-kv-label">${timeLabel}</span><span class="pd-kv-value">${formatTime(s.status_time)}</span></div>`);
        }
        if (s.create_time && s.status_time) {
            detailItems.push(`<div class="pd-kv-item"><span class="pd-kv-label">${t('duration')}</span><span class="pd-kv-value">${duration(s.create_time, s.status_time)}</span></div>`);
        }
        // Show failure info when stack failed or launch not succeeded
        const isFailure = failed || s.launch_succeeded === false;
        if (isFailure) {
            const failureMsg = s.status_reason || s.error || '';
            if (failureMsg) {
                detailItems.push(`<div class="pd-kv-item pd-kv-status-reason"><span class="pd-kv-label">${t('failureReason')}</span><span class="pd-kv-value pd-status-reason">${escapeHtml(extractErrorMessage(failureMsg))}</span></div>`);
            }
        }

        return `<div class="pd-stack-row collapsed" id="td-stack-${globalIdx}">
            <button type="button" class="pd-stack-row-header" data-td-section="stack-${globalIdx}">
                <span class="pd-stack-col-arrow"><span class="pd-stack-arrow-icon">▼</span></span>
                <span class="pd-stack-col-id">${idCellHtml}</span>
                <span class="pd-stack-col-region">${escapeHtml(regionName(s.region) || '')}</span>
                <span class="pd-stack-col-status">${statusHtml}</span>
                <span class="pd-stack-col-succeeded">${succeededHtml}</span>
            </button>
            <div class="pd-stack-row-body">
                <div class="pd-kv-grid">${detailItems.join('')}</div>
            </div>
        </div>`;
    }).join('');

    html += '</div>';

    // Only show pagination when multiple pages exist
    if (totalPages > 1) {
        html += `<div class="pd-stacks-pagination">${buildPaginationHTML(currentPage, totalPages, stacks.length, perPage, [10, 20, 50], 'stacks')}</div>`;
    }

    stacksEl.innerHTML = html;

    // Bind expand/collapse
    $$('.pd-stack-row-header', stacksEl).forEach(header => {
        header.addEventListener('click', (e) => {
            // Don't toggle when clicking a link inside the header
            if (e.target.closest('a')) return;
            header.closest('.pd-stack-row').classList.toggle('collapsed');
        });
    });

    // Bind pagination events
    if (totalPages > 1) {
        bindPaginationEvents(stacksEl, totalPages,
            (page) => { state._stacksPage = page; renderDetailStacks(run); },
            (newPerPage) => { state._stacksPerPage = newPerPage; state._stacksPage = 1; renderDetailStacks(run); }
        );
    }
}

function renderRunTemplate(run) {
    const container = el('detail-template');
    const params = run.params || {};
    const templateFiles = params.raw_template_files || {};
    const isTf = hasValidTfFiles(templateFiles);
    const templateContent = params.raw_template_content || '';

    let html = '';
    if (isTf) {
        const fileEntries = Object.entries(templateFiles).filter(([p]) => !p.endsWith('/'));
        const firstFile = fileEntries[0] ? fileEntries[0][0] : '';
        state._runTfFiles = templateFiles;
        state._runTfActive = firstFile;
        html += `<div class="pd-template-toolbar">
            <div class="tf-tabs-bar" id="run-tf-tabs-bar">${fileEntries.map(([p]) => {
                const name = p.split('/').pop();
                return `<div class="tf-tab ${p === firstFile ? 'active' : ''}" data-path="${escapeHtml(p)}"><span class="tf-tab-name">${escapeHtml(name)}</span></div>`;
            }).join('')}</div>
            <button type="button" class="btn btn-xs run-tf-copy-btn">${t('copyBtn')}</button>
        </div>`;
        html += `<pre class="log-pre pd-template-pre" id="run-tf-content"></pre>`;
    } else {
        // ROS: format bar (JSON/YAML) + content with copy button
        const autoFormat = templateContent.trim().startsWith('{') ? 'json' : 'yaml';
        state._runTemplateRaw = templateContent;
        state._runTemplateFormat = autoFormat;
        html += `<div class="pd-template-toolbar">
            <div class="template-format-tabs">
                <button type="button" class="format-btn ${autoFormat === 'json' ? 'active' : ''}" data-run-format="json">${t('jsonTab')}</button>
                <button type="button" class="format-btn ${autoFormat === 'yaml' ? 'active' : ''}" data-run-format="yaml">${t('yamlTab')}</button>
            </div>
            <button type="button" class="btn btn-xs run-template-copy-btn">${t('copyBtn')}</button>
        </div>
        <pre class="log-pre pd-template-pre" id="run-template-content"></pre>`;
    }
    container.innerHTML = html;

    // Apply syntax highlighting to template content
    if (isTf && state._runTfActive) {
        const contentEl = el('run-tf-content');
        if (contentEl) highlightPre(contentEl, state._runTfFiles[state._runTfActive] || '', 'hcl');
        $$('.tf-tab', el('run-tf-tabs-bar')).forEach(tab => {
            tab.addEventListener('click', () => {
                state._runTfActive = tab.dataset.path;
                $$('.tf-tab', el('run-tf-tabs-bar')).forEach(t => t.classList.toggle('active', t === tab));
                const pre = el('run-tf-content');
                if (pre) highlightPre(pre, state._runTfFiles[tab.dataset.path] || '', 'hcl');
            });
        });
    } else if (!isTf) {
        const pre = el('run-template-content');
        if (pre) highlightPre(pre, templateContent, state._runTemplateFormat || detectLanguage(templateContent));
        // Bind format toggle (JSON / YAML)
        $$('.template-format-tabs .format-btn', container).forEach(btn => {
            btn.addEventListener('click', () => {
                const fmt = btn.dataset.runFormat;
                if (fmt === state._runTemplateFormat) return;
                const raw = state._runTemplateRaw || '';
                let converted = raw;
                if (typeof jsyaml !== 'undefined') {
                    try {
                        const schema = ROS_SCHEMA || jsyaml.DEFAULT_SCHEMA;
                        const parsed = jsyaml.load(raw, { schema });
                        if (fmt === 'json') {
                            converted = JSON.stringify(parsed, null, 2);
                        } else {
                            converted = jsyaml.dump(parsed, { schema, lineWidth: -1, noRefs: true });
                        }
                    } catch (e) {
                        toast((t('formatConvertFailed') || 'Format conversion failed') + ': ' + e.message, 'error');
                        return;
                    }
                }
                state._runTemplateFormat = fmt;
                $$('.template-format-tabs .format-btn', container).forEach(b => {
                    b.classList.toggle('active', b.dataset.runFormat === fmt);
                });
                const preEl = el('run-template-content');
                if (preEl) highlightPre(preEl, converted, fmt);
            });
        });
    }
    // Bind TF copy button
    if (isTf) {
        const tfCopyBtn = container.querySelector('.run-tf-copy-btn');
        if (tfCopyBtn) {
            tfCopyBtn.addEventListener('click', () => {
                const content = (state._runTfFiles && state._runTfActive)
                    ? (state._runTfFiles[state._runTfActive] || '')
                    : '';
                copyToClipboard(content).then(() => {
                    tfCopyBtn.textContent = t('copied') || 'Copied';
                    setTimeout(() => tfCopyBtn.textContent = t('copyBtn'), 1500);
                });
            });
        }
    }
    // Bind ROS copy button
    if (!isTf) {
        const copyBtn = container.querySelector('.run-template-copy-btn');
        if (copyBtn) {
            copyBtn.addEventListener('click', () => {
                const pre = el('run-template-content');
                if (pre) copyToClipboard(pre.textContent).then(() => {
                    copyBtn.textContent = t('copied') || 'Copied';
                    setTimeout(() => copyBtn.textContent = t('copyBtn'), 1500);
                });
            });
        }
    }
}

function renderRunConfig(run) {
    const container = el('detail-params');
    const params = run.params || {};
    const configContent = params.raw_config_content || '';
    container.innerHTML = renderParamsTable(configContent);
}


async function renderCliLogs(runId) {
    const container = el('detail-logs');
    container.innerHTML = `<div class="empty-state">${t('loading') || 'Loading...'}</div>`;
    try {
        const text = await api('GET', `/api/runs/${runId}/logs`);
        if (!text || !text.trim()) {
            container.innerHTML = `<div class="empty-state">${t('noLogs')}</div>`;
            return;
        }
        // Build terminal-style output with colorized log levels + ANSI support
        const lines = text.split('\n');
        const bodyHtml = lines.map(line => {
            // Match: timestamp [LEVEL] : message (on raw line, before escaping)
            const m = line.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) \[\s*(\w+)\s*\] : (.*)$/);
            if (m) {
                const ts = escapeHtml(m[1]);
                const level = m[2].trim();
                const msg = ansiToHtml(m[3]);
                const levelClass = level === 'ERROR' ? 'term-error' : level === 'WARNING' ? 'term-warning' : level === 'INFO' ? 'term-info' : 'term-debug';
                return `<span class="term-ts">${ts}</span> <span class="term-level ${levelClass}">[${escapeHtml(level)}]</span> <span class="term-msg">${msg}</span>`;
            }
            return ansiToHtml(line);
        }).join('\n');

        container.innerHTML = `<div class="terminal-output">
            <div class="terminal-header">
                <span class="terminal-dot terminal-dot-red"></span>
                <span class="terminal-dot terminal-dot-yellow"></span>
                <span class="terminal-dot terminal-dot-green"></span>
                <span class="terminal-title">iact3 — CLI Logs</span>
            </div>
            <pre class="terminal-body">${bodyHtml}</pre>
        </div>`;

        // Auto-scroll to bottom
        const termBody = container.querySelector('.terminal-body');
        if (termBody) termBody.scrollTop = termBody.scrollHeight;
    } catch (e) {
        container.innerHTML = `<div class="empty-state">${t('noLogs')}</div>`;
    }
}

function renderReport(run) {
    const container = el('detail-report');
    const logs = run.logs || [];
    if (!logs.length) {
        container.innerHTML = `<div class="empty-state">${t('noReport')}</div>`;
        return;
    }
    container.innerHTML = logs.map((log, idx) => `
        <div class="log-card">
            <div class="log-title">
                <span>${escapeHtml(log.name)}</span>
                <button type="button" class="log-copy" data-report-idx="${idx}" data-i18n="copyBtn">Copy</button>
            </div>
            <pre>${escapeHtml(log.content)}</pre>
        </div>
    `).join('');

    $$('.log-copy', container).forEach(btn => {
        btn.addEventListener('click', () => {
            const idx = parseInt(btn.dataset.reportIdx, 10);
            const content = logs[idx]?.content || '';
            copyToClipboard(content).then(() => {
                const original = btn.textContent;
                btn.textContent = t('copied') || 'Copied';
                setTimeout(() => btn.textContent = original, 1500);
            });
        });
    });
}

async function deleteRunStacks(id) {
    if (!await showConfirm(t('confirmDeleteStacks'), { danger: true })) return;
    try {
        const res = await api('POST', `/api/runs/${id}/delete-stacks`);
        toast(t('deletedStacks', { count: res.deleted || 0 }), 'success');
        loadDetail(id);
    } catch (e) {
        toast(e.message, 'error');
    }
}

function openReportModal(url) {
    el('report-iframe').src = url;
    el('report-modal-open').href = url;
    el('report-modal').classList.add('open');
}

function closeReportModal() {
    el('report-modal').classList.remove('open');
    el('report-iframe').src = '';
}

function bindDetail() {
    el('btn-detail-back').addEventListener('click', () => {
        if (state.detailSource && state.detailSource.page === 'project-detail') {
            const pn = state.detailSource.projectName;
            state.detailSource = null;
            state._switchToRunsTab = true;
            navigate('project-detail', { projectName: pn });
        } else {
            state.detailSource = null;
            navigate('tasks');
        }
    });
    // Tab switching
    $$('.project-detail-tab', el('task-detail-tabs-bar')).forEach(btn => {
        btn.addEventListener('click', () => switchTaskDetailTab(btn.dataset.tdTab));
    });
    el('report-modal-close').addEventListener('click', closeReportModal);
    el('report-modal').addEventListener('click', (e) => {
        if (e.target === el('report-modal')) closeReportModal();
    });
}

function switchTaskDetailTab(tabName) {
    $$('.project-detail-tab', el('task-detail-tabs-bar')).forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tdTab === tabName);
    });
    $$('#page-detail .project-detail-tab-pane').forEach(pane => {
        const id = pane.id.replace('task-detail-pane-', '');
        pane.classList.toggle('active', id === tabName);
    });
}

/* ============== Project Detail ============== */
function renderPdRegionSelect() {
    const sel = el('pd-region-select');
    if (!sel) return;
    const previousValue = sel.value;
    sel.innerHTML = '';
    let defaultIndex = -1;
    state.regions.forEach((r, idx) => {
        const opt = document.createElement('option');
        opt.value = r.id;
        opt.textContent = r.name || r.id;
        opt.title = `${r.name || r.id} (${r.id})`;
        sel.appendChild(opt);
        if (r.id === 'cn-hangzhou') defaultIndex = idx;
    });
    let targetValue = '';
    if (previousValue && state.regions.some(r => r.id === previousValue)) {
        targetValue = previousValue;
    } else if (defaultIndex >= 0) {
        targetValue = state.regions[defaultIndex].id;
    } else if (state.regions.length) {
        targetValue = state.regions[0].id;
    }
    sel.value = targetValue;
    if (!sel.value && state.regions.length) {
        sel.selectedIndex = 0;
    }
}

async function loadProjectDetail(name) {
    try {
        const [project, runsData] = await Promise.all([
            api('GET', `/api/projects/${encodeURIComponent(name)}`),
            api('GET', `/api/projects/${encodeURIComponent(name)}/runs`),
        ]);
        state.currentProject = project;
        state.currentProjectName = name;
        state.currentProjectRuns = runsData.runs || [];
        state.runHistoryPage = 1;
        renderProjectDetail(project, state.currentProjectRuns);
        if (state._switchToRunsTab) {
            state._switchToRunsTab = false;
            switchProjectDetailTab('runs');
        }
    } catch (e) {
        toast(e.message, 'error');
    }
}

function renderProjectRunHistory(runsEl, runs, project) {
    if (!runs.length) {
        runsEl.innerHTML = `<div class="empty-state">${t('projectNoRuns')}</div>`;
        const pagEl = el('run-history-pagination');
        if (pagEl) pagEl.innerHTML = '';
        return;
    }

    // Client-side pagination
    const perPage = state.runHistoryPerPage;
    const totalPages = Math.max(1, Math.ceil(runs.length / perPage));
    const current = Math.min(state.runHistoryPage, totalPages);
    state.runHistoryPage = current;
    const startIdx = (current - 1) * perPage;
    const pageRuns = runs.slice(startIdx, startIdx + perPage);

    // Table header
    const tableHeader = `<div class="pd-run-table-header">
        <span class="th-expand"></span>
        <span class="th-time">${t('detailCreated')}</span>
        <span class="th-name">${t('detailName')}</span>
        <span class="th-status">${t('detailStatus')}</span>
        <span class="th-duration">${t('detailDuration')}</span>
    </div>`;

    runsEl.innerHTML = tableHeader + '<div class="pd-run-table">' + pageRuns.map(r => {
        const statusClass = `status-${r.status}`;
        const statusLabel = t('status' + r.status.charAt(0).toUpperCase() + r.status.slice(1));
        const stacks = Array.isArray(r.stacks) ? r.stacks : [];
        const regions = [...new Set(stacks.map(s => s.region).filter(Boolean))].map(regionName).join(', ') || '-';
        // Only consider actual failures, not success status_reason messages
        const hasRealError = r.status === 'failed' || r.error || stacks.some(s => isStackFailed(s) && s.status_reason);

        // Summary items
        const summaryItems = [
            { label: t('runId'), value: `<code>${escapeHtml(r.id || '')}</code>` },
            { label: t('costRegion'), value: escapeHtml(regions) },
            { label: t('runProgress'), value: `${r.progress || 0}%` },
            { label: t('detailDuration'), value: escapeHtml(duration(r.created_at, r.completed_at)) },
        ];
        // Merge stack info directly into summary
        stacks.forEach((s, idx) => {
            const stLabel = tStackStatus(s.status) || s.status || '-';
            const stClass = (s.status || '').toLowerCase().includes('complete') ? 'completed' : (s.status || '').toLowerCase().includes('fail') ? 'failed' : 'running';
            const name = s.stack_name || s.test_name || '';
            const prefix = stacks.length > 1 ? `${t('runStacks')}${idx + 1}` : t('runStacks');
            summaryItems.push({ label: prefix + t('detailName'), value: escapeHtml(name) });
            summaryItems.push({ label: prefix + t('stackStatus'), value: `<span class="status-badge status-${stClass}">${escapeHtml(stLabel)}</span>` });
        });

        // Error section - only show for actual failures
        let errorHtml = '';
        if (hasRealError) {
            const errorItems = [];
            if (r.error) {
                errorItems.push(`<div class="pd-run-error-item"><span class="pd-run-error-label">${t('runError')}</span><div class="pd-run-error-msg">${escapeHtml(r.error)}</div></div>`);
            }
            // Only show status_reason for actually failed stacks
            const failedStacks = stacks.filter(s => isStackFailed(s) && s.status_reason);
            failedStacks.forEach(s => {
                errorItems.push(`<div class="pd-run-error-item"><span class="pd-run-error-label">${escapeHtml(s.stack_name || s.test_name || '')}</span><div class="pd-run-error-msg">${escapeHtml(extractErrorMessage(s.status_reason))}</div></div>`);
            });
            if (errorItems.length) {
                errorHtml = `<div class="pd-run-analysis">
                    <div class="pd-run-detail-title">${t('runAnalysis')}</div>
                    ${errorItems.join('')}
                </div>`;
            }
        }

        return `<div class="pd-run-card" data-id="${r.id}">
            <div class="pd-run-header">
                <span class="pd-run-expand-icon">▼</span>
                <span class="pd-run-time">${escapeHtml(formatTime(r.created_at))}</span>
                <span class="pd-run-name">${escapeHtml(r.name)}</span>
                <span class="pd-run-status-cell"><span class="status-badge ${statusClass}">${escapeHtml(statusLabel)}</span></span>
                <span class="pd-run-duration">${escapeHtml(duration(r.created_at, r.completed_at))}</span>
            </div>
            <div class="pd-run-detail">
                <div class="pd-run-detail-body">
                    <div class="pd-run-summary">
                        <div class="pd-run-detail-title">${t('runSummary')}</div>
                        <div class="pd-run-summary-grid">
                            ${summaryItems.map(i => `<div class="pd-run-summary-item"><span class="pd-run-detail-label">${i.label}：</span><span class="pd-run-detail-value">${i.value}</span></div>`).join('')}
                        </div>
                    </div>
                    ${errorHtml}
                    <div class="pd-run-detail-actions">
                        <button class="btn btn-sm btn-view-task" data-id="${r.id}">${t('viewTaskDetailBtn')}</button>
                        ${r.report_url ? `<a href="${escapeHtml(authUrl(r.report_url))}" target="_blank" class="btn btn-sm">${t('viewReportBtn')}</a>` : ''}
                    </div>
                </div>
            </div>
        </div>`;
    }).join('') + '</div>';

    // Bind expand/collapse
    $$('.pd-run-header', runsEl).forEach(header => {
        header.addEventListener('click', (e) => {
            if (e.target.closest('button') || e.target.closest('a')) return;
            const card = header.closest('.pd-run-card');
            card.classList.toggle('expanded');
        });
    });
    $$('.btn-view-task', runsEl).forEach(b => b.addEventListener('click', (e) => {
        e.stopPropagation();
        state.detailSource = { page: 'project-detail', projectName: project.name };
        navigate('detail', { runId: b.dataset.id });
    }));

    // Render pagination
    renderRunHistoryPagination(runs.length);
}

function renderRunHistoryPagination(total) {
    const container = el('run-history-pagination');
    if (!container) return;
    const perPage = state.runHistoryPerPage;
    const totalPages = Math.max(1, Math.ceil(total / perPage));
    const current = Math.min(state.runHistoryPage, totalPages);
    const perPageOptions = [10, 20, 50, 100];

    if (total <= perPageOptions[0] && totalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = buildPaginationHTML(current, totalPages, total, perPage, perPageOptions, 'runHistory');
    const refreshRuns = () => {
        const runsEl = el('project-detail-runs');
        if (runsEl && state.currentProject) {
            renderProjectRunHistory(runsEl, state.currentProjectRuns, state.currentProject);
        }
    };
    bindPaginationEvents(container, totalPages,
        (page) => { state.runHistoryPage = page; refreshRuns(); },
        (newPerPage) => { state.runHistoryPerPage = newPerPage; state.runHistoryPage = 1; refreshRuns(); }
    );
}

async function pollProjectRuns(name) {
    try {
        const runsData = await api('GET', `/api/projects/${encodeURIComponent(name)}/runs`);
        const runs = runsData.runs || [];
        // Check if any run status changed
        const prevMap = Object.fromEntries((state.currentProjectRuns || []).map(r => [r.id, r.status]));
        const changed = runs.some(r => prevMap[r.id] !== r.status) || runs.length !== (state.currentProjectRuns || []).length;
        if (changed) {
            state.currentProjectRuns = runs;
            const runsEl = el('project-detail-runs');
            if (runsEl && state.currentProject) {
                renderProjectRunHistory(runsEl, runs, state.currentProject);
            }
        }
    } catch (e) {
        // silent
    }
}

function renderProjectDetail(project, runs) {
    // Reset to overview tab when loading a new project
    switchProjectDetailTab('overview');
    const isTf = isTerraformProject(project);
    const typeLabel = isTf ? t('terraformTab') : t('rosTab');
    const createdAt = project.created_at ? Number(project.created_at) * 1000 : null;
    const updatedAt = project.updated_at ? Number(project.updated_at) * 1000 : null;
    const projectConfig = project.config || '';

    el('project-detail-overview').innerHTML = `
        <div class="pd-section" id="pd-section-basic">
            <button type="button" class="pd-section-header" data-pd-section="basic">
                <span class="pd-section-arrow">▼</span>
                <span>${t('basicInfo')}</span>
            </button>
            <div class="pd-section-body">
                <div class="pd-kv-grid">
                    <div class="pd-kv-item"><span class="pd-kv-label">${t('detailName')}</span><span class="pd-kv-value">${escapeHtml(project.name || '')}</span></div>
                    <div class="pd-kv-item"><span class="pd-kv-label">${t('projectType')}</span><span class="pd-kv-value"><span class="pd-type-tag ${isTf ? 'terraform' : 'ros'}">${typeLabel}</span></span></div>
                    <div class="pd-kv-item"><span class="pd-kv-label">${t('detailCreated')}</span><span class="pd-kv-value">${createdAt ? new Date(createdAt).toLocaleString() : '-'}</span></div>
                    <div class="pd-kv-item"><span class="pd-kv-label">${t('projectUpdated')}</span><span class="pd-kv-value">${updatedAt ? new Date(updatedAt).toLocaleString() : '-'}</span></div>
                    <div class="pd-kv-item"><span class="pd-kv-label">${t('currentVersion')}</span><span class="pd-kv-value">${project.current_version ? 'v' + project.current_version : '-'}</span></div>
                </div>
            </div>
        </div>
        <div class="pd-section" id="pd-section-options">
            <button type="button" class="pd-section-header" data-pd-section="options">
                <span class="pd-section-arrow">▼</span>
                <span>${t('runOptions')}</span>
            </button>
            <div class="pd-section-body">
                <div class="pd-kv-grid">
                    <div class="pd-kv-item"><span class="pd-kv-label">${t('optNoDelete')}</span><span class="pd-kv-value">${project.no_delete ? t('yes') : t('no')}</span></div>
                    <div class="pd-kv-item"><span class="pd-kv-label">${t('optKeepFailed')}</span><span class="pd-kv-value">${project.keep_failed ? t('yes') : t('no')}</span></div>
                    <div class="pd-kv-item"><span class="pd-kv-label">${t('optDontWait')}</span><span class="pd-kv-value">${project.dont_wait_for_delete ? t('yes') : t('no')}</span></div>
                </div>
            </div>
        </div>
    `;

    // Bind collapsible section toggles
    $$('.pd-section-header', el('project-detail-overview')).forEach(btn => {
        btn.addEventListener('click', () => {
            btn.closest('.pd-section').classList.toggle('collapsed');
        });
    });

    const templateEl = el('project-detail-template');
    let templateHtml = '';
    if (isTf) {
        const fileEntries = Object.entries(project.template_files || {}).filter(([p]) => !p.endsWith('/'));
        const firstFile = fileEntries[0] ? fileEntries[0][0] : '';
        state._pdTfFiles = project.template_files || {};
        state._pdTfActive = firstFile;
        templateHtml += `<div class="tf-tabs-bar" id="pd-tf-tabs-bar">${fileEntries.map(([p]) => {
            const name = p.split('/').pop();
            return `<div class="tf-tab ${p === firstFile ? 'active' : ''}" data-path="${escapeHtml(p)}"><span class="tf-tab-name">${escapeHtml(name)}</span></div>`;
        }).join('')}</div>`;
        templateHtml += `<pre class="log-pre pd-template-pre" id="pd-tf-content"></pre>`;
        templateEl.innerHTML = templateHtml;
        // Render initial file content
        const pdTfPre = el('pd-tf-content');
        if (pdTfPre) highlightPre(pdTfPre, state._pdTfFiles[firstFile] || '', 'hcl');
        // Bind tab switching
        $$('.tf-tab', el('pd-tf-tabs-bar')).forEach(tab => {
            tab.addEventListener('click', () => {
                state._pdTfActive = tab.dataset.path;
                $$('.tf-tab', el('pd-tf-tabs-bar')).forEach(t => t.classList.toggle('active', t === tab));
                const pre = el('pd-tf-content');
                if (pre) highlightPre(pre, state._pdTfFiles[tab.dataset.path] || '', 'hcl');
            });
        });
    } else {
        // ROS template: format bar + content area
        const rawTemplate = project.template || '';
        state._pdTemplateRaw = rawTemplate;
        // Auto-detect format: if it starts with '{', treat as JSON
        const autoFormat = rawTemplate.trim().startsWith('{') ? 'json' : 'yaml';
        state.pdTemplateFormat = autoFormat;
        templateHtml += `<div class="pd-template-toolbar">
            <div class="template-format-tabs">
                <button type="button" class="format-btn ${autoFormat === 'json' ? 'active' : ''}" data-pd-format="json">${t('jsonTab')}</button>
                <button type="button" class="format-btn ${autoFormat === 'yaml' ? 'active' : ''}" data-pd-format="yaml">${t('yamlTab')}</button>
            </div>
            <button type="button" class="btn btn-xs pd-template-copy-btn">${t('copyBtn')}</button>
        </div>
        <pre class="log-pre pd-template-pre" id="pd-template-content"></pre>`;
        templateEl.innerHTML = templateHtml;
        // Render initial content
        renderPdTemplateContent(rawTemplate, autoFormat);
        // Bind format toggle
        $$('.template-format-tabs .format-btn', templateEl).forEach(btn => {
            btn.addEventListener('click', () => {
                const fmt = btn.dataset.pdFormat;
                if (fmt === state.pdTemplateFormat) return;
                state.pdTemplateFormat = fmt;
                $$('.template-format-tabs .format-btn', templateEl).forEach(b => {
                    b.classList.toggle('active', b.dataset.pdFormat === fmt);
                });
                renderPdTemplateContent(state._pdTemplateRaw, fmt);
            });
        });
        // Bind copy
        const copyBtn = $('.pd-template-copy-btn', templateEl);
        if (copyBtn) {
            copyBtn.addEventListener('click', async () => {
                const pre = el('pd-template-content');
                if (pre) {
                    await copyToClipboard(pre.textContent);
                    toast(t('copied') || 'Copied', 'success');
                }
            });
        }
    }

    const configsEl = el('project-detail-configs');
    configsEl.innerHTML = renderParamsTable(projectConfig);

    const runsEl = el('project-detail-runs');
    renderProjectRunHistory(runsEl, runs, project);

    el('btn-project-detail-load').dataset.name = project.name;
    el('btn-project-detail-run').dataset.name = project.name;
    el('btn-project-detail-edit').dataset.name = project.name;
    // Populate region select for project detail
    renderPdRegionSelect();
    renderVersionHistory(project.name);
    renderAll();
}

async function runProjectFromDetail(name) {
    const btn = el('btn-project-detail-run');
    try {
        const project = await api('GET', `/api/projects/${encodeURIComponent(name)}`);
        let config = project.config || '';
        if (!config && project.configs && project.configs.length) {
            config = project.configs[0].config || '';
        }
        const isTf = isTerraformProject(project);
        const pdRegionSel = el('pd-region-select');
        const regions = pdRegionSel && pdRegionSel.value ? pdRegionSel.value : (state.pgRegionSelect ? state.pgRegionSelect.getSelected().join(',') : '');
        const payload = {
            project_name: name,
            name: `${name}-${Date.now()}`,
            regions: regions,
            no_delete: Boolean(project.no_delete),
            keep_failed: Boolean(project.keep_failed),
            dont_wait_for_delete: Boolean(project.dont_wait_for_delete),
            config_content: buildFullConfigYaml(config, regions, name),
        };
        if (isTf) {
            payload.template_files = project.template_files;
        } else {
            payload.template_content = project.template || '';
        }

        // Step 1: Validate before run
        toast(t('preValidating', { action: t('runBtn') }) || 'Validating...', 'info');
        setBtnLoading(btn, true);
        const valRes = await api('POST', '/api/validate', payload);
        if (valRes.result !== 'valid') {
            setBtnLoading(btn, false);
            if (valRes.logs) {
                consoleLog(valRes.logs, { type: 'info', action: 'validate', level: 'INFO', raw: true });
            } else {
                const summary = JSON.stringify(valRes, null, 2);
                consoleLog(`Validate result: ${valRes.result}\n${summary}`, { type: 'warn', action: 'validate', level: 'WARN' });
            }
            toast(t('validateFailedBeforeAction', { action: t('runBtn') }) || 'Validation failed before Run', 'error');
            return;
        }

        // Step 2: Run test
        const run = await api('POST', '/api/runs', payload);
        setBtnLoading(btn, false);
        toast(t('runStarted', { id: run.id }), 'success');
        loadProjectDetail(name);
    } catch (e) {
        setBtnLoading(btn, false);
        toast(e.message, 'error');
    }
}

function switchProjectDetailTab(tabName) {
    $$('.project-detail-tab', el('project-detail-tabs-bar')).forEach(btn => {
        btn.classList.toggle('active', btn.dataset.pdTab === tabName);
    });
    $$('.project-detail-tab-pane').forEach(pane => {
        const id = pane.id.replace('project-detail-pane-', '');
        pane.classList.toggle('active', id === tabName);
    });
}

function renderParamsTable(configYaml) {
    // Parse YAML config and render parameters as a key-value table
    if (!configYaml || !configYaml.trim()) {
        return `<div class="empty-state">${t('configLabel')}: (empty)</div>`;
    }
    const stripped = stripProjectSection(configYaml);
    let parsed = null;
    try {
        if (typeof jsyaml !== 'undefined') {
            parsed = jsyaml.load(stripped);
        }
    } catch (e) {
        // fallback to raw display
    }
    if (!parsed || typeof parsed !== 'object') {
        return `<pre class="log-pre">${escapeHtml(stripped)}</pre>`;
    }

    // Extract parameters from tests.<test_name>.parameters or top-level parameters
    let params = null;
    if (parsed.tests && typeof parsed.tests === 'object') {
        const testEntries = Object.entries(parsed.tests).filter(([, v]) => v && v.parameters);
        if (testEntries.length === 1) {
            params = testEntries[0][1].parameters;
        } else if (testEntries.length > 1) {
            // Multiple test cases: render each as a sub-section
            let html = '';
            for (const [testName, testConfig] of testEntries) {
                html += `<div class="pd-params-group">
                    <div class="pd-params-group-title">${escapeHtml(testName)}</div>
                    ${_renderParamsRows(testConfig.parameters)}
                </div>`;
            }
            return html;
        }
    }
    if (!params && parsed.parameters && typeof parsed.parameters === 'object') {
        params = parsed.parameters;
    }
    if (!params || typeof params !== 'object') {
        return `<pre class="log-pre">${escapeHtml(stripped)}</pre>`;
    }
    return _renderParamsRows(params);
}

function _renderParamsRows(params) {
    const entries = Object.entries(params);
    if (!entries.length) {
        return `<div class="empty-state">${t('configLabel')}: (empty)</div>`;
    }
    let html = `<table class="pd-params-table"><thead><tr>
        <th>${t('paramKey')}</th><th>${t('paramValue')}</th>
    </tr></thead><tbody>`;
    for (const [key, val] of entries) {
        const displayVal = val === null || val === undefined ? '' : String(val);
        html += `<tr><td class="pd-param-key">${escapeHtml(key)}</td><td class="pd-param-val">${escapeHtml(displayVal)}</td></tr>`;
    }
    html += '</tbody></table>';
    return html;
}

function renderPdTemplateContent(raw, format) {
    const pre = el('pd-template-content');
    if (!pre) return;
    if (!raw) { pre.textContent = ''; return; }
    // Show raw content with syntax highlighting
    highlightPre(pre, raw, format || detectLanguage(raw));
}

function bindProjectDetail() {
    el('btn-project-detail-back').addEventListener('click', () => navigate('projects'));
    el('btn-project-detail-load').addEventListener('click', () => {
        loadProjectIntoPlayground(el('btn-project-detail-load').dataset.name);
    });
    el('btn-project-detail-edit').addEventListener('click', () => openEditProject(el('btn-project-detail-edit').dataset.name));
    el('btn-project-detail-run').addEventListener('click', () => runProjectFromDetail(el('btn-project-detail-run').dataset.name));
    // Tab switching
    $$('.project-detail-tab', el('project-detail-tabs-bar')).forEach(btn => {
        btn.addEventListener('click', () => switchProjectDetailTab(btn.dataset.pdTab));
    });
    // Version modal close
    const vmClose = el('version-modal-close');
    if (vmClose) vmClose.addEventListener('click', closeVersionModal);
    const vmOverlay = el('version-modal');
    if (vmOverlay) vmOverlay.addEventListener('click', (e) => { if (e.target === vmOverlay) closeVersionModal(); });
}

/* ============== Settings ============== */
async function loadSettings(showToastMsg = true) {
    try {
        const data = await api('GET', '/api/settings');
        state.settings = data.settings || {};
        renderSettings();
        if (showToastMsg) toast(t('settingsLoaded'));
    } catch (e) {
        toast(e.message, 'error');
    }
}

function renderSettings() {
    // Settings are loaded into state.settings; no UI to update
    // (credential status is only shown on demand via ensureCredentials)
}

function bindSettings() {}

/* ============== Version Management ============== */

// Simple LCS-based line diff algorithm
function computeLineDiff(oldText, newText) {
    const oldLines = (oldText || '').split('\n');
    const newLines = (newText || '').split('\n');
    const m = oldLines.length, n = newLines.length;
    // Build LCS table
    const dp = Array.from({length: m + 1}, () => new Uint16Array(n + 1));
    for (let i = 1; i <= m; i++) {
        for (let j = 1; j <= n; j++) {
            dp[i][j] = oldLines[i-1] === newLines[j-1]
                ? dp[i-1][j-1] + 1
                : Math.max(dp[i-1][j], dp[i][j-1]);
        }
    }
    // Backtrack to produce diff
    const result = [];
    let i = m, j = n;
    while (i > 0 || j > 0) {
        if (i > 0 && j > 0 && oldLines[i-1] === newLines[j-1]) {
            result.push({type: 'unchanged', oldLine: i, newLine: j, text: oldLines[i-1]});
            i--; j--;
        } else if (j > 0 && (i === 0 || dp[i][j-1] >= dp[i-1][j])) {
            result.push({type: 'added', newLine: j, text: newLines[j-1]});
            j--;
        } else {
            result.push({type: 'removed', oldLine: i, text: oldLines[i-1]});
            i--;
        }
    }
    result.reverse();
    return result;
}

// Render a side-by-side diff view into a container element
function renderDiffView(container, oldText, newText, oldLabel, newLabel) {
    const diff = computeLineDiff(oldText, newText);
    // Build aligned rows: pair removed/added lines, pad with placeholders
    const leftRows = [], rightRows = [];
    let idx = 0;
    while (idx < diff.length) {
        const d = diff[idx];
        if (d.type === 'unchanged') {
            leftRows.push({type: 'unchanged', num: d.oldLine, text: d.text});
            rightRows.push({type: 'unchanged', num: d.newLine, text: d.text});
            idx++;
        } else if (d.type === 'removed') {
            // Collect consecutive removes
            const removes = [];
            while (idx < diff.length && diff[idx].type === 'removed') {
                removes.push(diff[idx]); idx++;
            }
            // Collect consecutive adds
            const adds = [];
            while (idx < diff.length && diff[idx].type === 'added') {
                adds.push(diff[idx]); idx++;
            }
            const maxLen = Math.max(removes.length, adds.length);
            for (let k = 0; k < maxLen; k++) {
                if (k < removes.length) {
                    leftRows.push({type: 'removed', num: removes[k].oldLine, text: removes[k].text});
                } else {
                    leftRows.push({type: 'placeholder', num: '', text: ''});
                }
                if (k < adds.length) {
                    rightRows.push({type: 'added', num: adds[k].newLine, text: adds[k].text});
                } else {
                    rightRows.push({type: 'placeholder', num: '', text: ''});
                }
            }
        } else { // added
            const adds = [];
            while (idx < diff.length && diff[idx].type === 'added') {
                adds.push(diff[idx]); idx++;
            }
            for (const a of adds) {
                leftRows.push({type: 'placeholder', num: '', text: ''});
                rightRows.push({type: 'added', num: a.newLine, text: a.text});
            }
        }
    }

    const buildPane = (rows, label) => {
        const pane = document.createElement('div');
        pane.className = 'diff-pane';
        const header = document.createElement('div');
        header.className = 'diff-pane-header';
        header.textContent = label;
        pane.appendChild(header);
        const body = document.createElement('div');
        for (const r of rows) {
            const line = document.createElement('div');
            line.className = 'diff-line' + (r.type === 'added' ? ' diff-added' : r.type === 'removed' ? ' diff-removed' : r.type === 'placeholder' ? ' diff-placeholder' : '');
            const numEl = document.createElement('span');
            numEl.className = 'diff-line-num';
            numEl.textContent = r.num;
            const textEl = document.createElement('span');
            textEl.className = 'diff-line-text';
            textEl.textContent = r.text;
            line.appendChild(numEl);
            line.appendChild(textEl);
            body.appendChild(line);
        }
        pane.appendChild(body);
        return pane;
    };

    container.innerHTML = '';
    const viewer = document.createElement('div');
    viewer.className = 'diff-viewer';
    viewer.appendChild(buildPane(leftRows, oldLabel));
    viewer.appendChild(buildPane(rightRows, newLabel));
    container.appendChild(viewer);
}

// ── Version Modal ──
function openVersionModal(title, contentHtml) {
    el('version-modal-title').textContent = title;
    const body = el('version-modal-body');
    if (typeof contentHtml === 'string') {
        body.innerHTML = contentHtml;
    } else {
        body.innerHTML = '';
        body.appendChild(contentHtml);
    }
    el('version-modal').classList.add('open');
}
function closeVersionModal() {
    el('version-modal').classList.remove('open');
}

// ── Version History in Project Detail ──
async function renderVersionHistory(projectName) {
    const container = el('project-detail-versions');
    container.innerHTML = `<div class="empty-state">${t('loading')}</div>`;
    try {
        const data = await api('GET', `/api/projects/${encodeURIComponent(projectName)}/versions`);
        const versions = data.versions || [];
        const currentVersion = data.current_version || 0;
        if (!versions.length) {
            container.innerHTML = `<div class="empty-state">${t('versionEmpty')}</div>`;
            return;
        }
        // If currentVersion doesn't match any version (phantom), treat the latest as "current"
        const hasValidCurrent = versions.some(v => v.version === currentVersion);
        const effectiveCurrent = hasValidCurrent ? currentVersion : Math.max(...versions.map(v => v.version));
        const isLastVersion = versions.length <= 1;
        let html = `<table class="version-table"><thead><tr>
            <th class="col-version">${t('versionCol')}</th>
            <th class="col-status">${t('versionStatusCol')}</th>
            <th class="col-created">${t('versionCreatedAt')}</th>
            <th class="col-actions">${t('versionActions')}</th>
        </tr></thead><tbody>`;
        for (const v of versions) {
            const isCurrent = v.version === effectiveCurrent;
            const createdAt = v.created_at ? new Date(Number(v.created_at) * 1000).toLocaleString() : '-';
            html += `<tr class="${isCurrent ? 'is-current' : ''}">
                <td class="col-version"><span class="version-badge">v${v.version}</span></td>
                <td class="col-status">${isCurrent ? `<span class="version-badge-current">${t('versionCurrent')}</span>` : '<span style="color:var(--text-muted)">—</span>'}</td>
                <td class="col-created">${createdAt}</td>
                <td class="col-actions"><div class="version-actions">
                    <button class="btn btn-xs btn-version-view" data-ver="${v.version}">${t('viewVersion')}</button>
                    ${!isCurrent ? `<button class="btn btn-xs btn-version-diff" data-ver="${v.version}">${t('compareVersion')}</button>` : ''}
                    ${!isCurrent ? `<button class="btn btn-xs btn-version-activate" data-ver="${v.version}">${t('setAsCurrent')}</button>` : ''}
                    ${isLastVersion
                        ? `<button class="btn btn-xs btn-danger btn-version-delete" data-ver="${v.version}" disabled title="${t('cannotDeleteLastVersion')}">${t('deleteVersion')}</button>`
                        : `<button class="btn btn-xs btn-danger btn-version-delete" data-ver="${v.version}">${t('deleteVersion')}</button>`
                    }
                </div></td>
            </tr>`;
        }
        html += '</tbody></table>';
        container.innerHTML = html;

        // Bind buttons
        $$('.btn-version-view', container).forEach(btn => {
            btn.addEventListener('click', () => viewVersionContent(projectName, Number(btn.dataset.ver)));
        });
        $$('.btn-version-diff', container).forEach(btn => {
            btn.addEventListener('click', () => viewVersionDiff(projectName, Number(btn.dataset.ver)));
        });
        $$('.btn-version-activate', container).forEach(btn => {
            btn.addEventListener('click', () => activateVersion(projectName, Number(btn.dataset.ver)));
        });
        $$('.btn-version-delete', container).forEach(btn => {
            btn.addEventListener('click', () => deleteVersion(projectName, Number(btn.dataset.ver)));
        });
    } catch (e) {
        container.innerHTML = `<div class="empty-state">${e.message}</div>`;
    }
}

async function viewVersionContent(projectName, ver) {
    try {
        const v = await api('GET', `/api/projects/${encodeURIComponent(projectName)}/versions/${ver}`);
        const config = v.config || '';
        const templateFiles = v.template_files || {};
        const isTf = hasValidTfFiles(templateFiles);
        let html = '<div class="version-viewer">';
        // Template section
        if (isTf) {
            const fileEntries = Object.entries(templateFiles).filter(([p]) => !p.endsWith('/'));
            const firstFile = fileEntries[0] ? fileEntries[0][0] : '';
            html += `<div class="version-viewer-section">
                <div class="version-viewer-section-header">${t('templateLabel')}</div>
                <div class="tf-tabs-bar" id="ver-tf-tabs-bar">${fileEntries.map(([p]) => {
                    const name = p.split('/').pop();
                    return `<div class="tf-tab ${p === firstFile ? 'active' : ''}" data-path="${escapeHtml(p)}"><span class="tf-tab-name">${escapeHtml(name)}</span></div>`;
                }).join('')}</div>
                <pre class="version-viewer-content" id="ver-tf-content">${escapeHtml(firstFile ? templateFiles[firstFile] : '(empty)')}</pre>
            </div>`;
        } else {
            html += `<div class="version-viewer-section">
                <div class="version-viewer-section-header">${t('templateLabel')}</div>
                <pre class="version-viewer-content">${escapeHtml(v.template || '(empty)')}</pre>
            </div>`;
        }
        // Config section
        html += `<div class="version-viewer-section">
            <div class="version-viewer-section-header">${t('configLabel')}</div>
            <pre class="version-viewer-content">${escapeHtml(stripProjectSection(config))}</pre>
        </div>`;
        html += '</div>';
        openVersionModal(t('versionViewTitle', {ver: ver}), html);
        // Bind TF tab switching
        if (isTf) {
            const tabBar = el('ver-tf-tabs-bar');
            if (tabBar) {
                $$('.tf-tab', tabBar).forEach(tab => {
                    tab.addEventListener('click', () => {
                        $$('.tf-tab', tabBar).forEach(t => t.classList.toggle('active', t === tab));
                        const pre = el('ver-tf-content');
                        if (pre) pre.textContent = templateFiles[tab.dataset.path] || '';
                    });
                });
            }
        }
    } catch (e) {
        toast(t('versionLoadFailed'), 'error');
    }
}

async function viewVersionDiff(projectName, ver) {
    try {
        const [v, project] = await Promise.all([
            api('GET', `/api/projects/${encodeURIComponent(projectName)}/versions/${ver}`),
            api('GET', `/api/projects/${encodeURIComponent(projectName)}`),
        ]);

        // Helper: build a combined template string from template_files (for TF projects)
        const buildTfText = (files) => {
            if (!files || !Object.keys(files).length) return '';
            return Object.entries(files)
                .filter(([p]) => !p.endsWith('/'))
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([path, content]) => `# ── ${path} ──\n${content}`)
                .join('\n\n');
        };

        const oldTpl = hasValidTfFiles(v.template_files) ? buildTfText(v.template_files) : (v.template || '');
        const newTpl = hasValidTfFiles(project.template_files) ? buildTfText(project.template_files) : (project.template || '');

        const container = document.createElement('div');

        // Template diff
        const tplSection = document.createElement('div');
        tplSection.className = 'version-viewer-section';
        tplSection.innerHTML = `<div class="version-viewer-section-header">${t('templateLabel')}</div>`;
        const tplDiffContainer = document.createElement('div');
        tplSection.appendChild(tplDiffContainer);
        container.appendChild(tplSection);

        // Config diff
        const oldConfig = v.config || '';
        const newConfig = project.config || '';
        const cfgSection = document.createElement('div');
        cfgSection.className = 'version-viewer-section';
        cfgSection.innerHTML = `<div class="version-viewer-section-header">${t('configLabel')}</div>`;
        const cfgDiffContainer = document.createElement('div');
        cfgSection.appendChild(cfgDiffContainer);
        container.appendChild(cfgSection);
        renderDiffView(cfgDiffContainer,
            stripProjectSection(oldConfig),
            stripProjectSection(newConfig),
            t('versionOldLabel', {ver: ver}),
            t('versionNewLabel')
        );

        renderDiffView(tplDiffContainer, oldTpl, newTpl,
            t('versionOldLabel', {ver: ver}), t('versionNewLabel'));

        openVersionModal(t('versionDiffTitle', {ver: ver}), container);
    } catch (e) {
        toast(t('versionLoadFailed'), 'error');
    }
}

async function activateVersion(projectName, ver) {
    if (!await showConfirm(t('confirmSetVersion', {ver: ver}))) return;
    try {
        await api('POST', `/api/projects/${encodeURIComponent(projectName)}/versions/${ver}/activate`);
        toast(t('versionSet', {ver: ver}), 'success');
        loadProjectDetail(projectName);
    } catch (e) {
        toast(t('versionActivateFailed'), 'error');
    }
}

async function deleteVersion(projectName, ver) {
    if (!await showConfirm(t('confirmDeleteVersion', {ver: ver}))) return;
    try {
        const res = await api('DELETE', `/api/projects/${encodeURIComponent(projectName)}/versions/${ver}`);
        if (res.auto_switched) {
            toast(t('versionDeletedAndSwitched', {ver: ver, newVer: res.current_version}), 'success');
        } else {
            toast(t('versionDeleted', {ver: ver}), 'success');
        }
        loadProjectDetail(projectName);
    } catch (e) {
        toast(e.message || t('versionDeleteFailed'), 'error');
    }
}

// ── Version selector in project edit modal ──
let _editVersionCache = null; // {versions: [], current_version: 0}
let _editOriginalContent = null; // cached current-version editor content before switching

function _captureEditContent() {
    // Sync active TF file from editor into state before capturing
    if (state.projectEditTfMode && state.projectEditTfActiveFile) {
        state.projectEditTfFiles[state.projectEditTfActiveFile] = el('project-edit-tf-template').value;
    }
    return {
        isTf: state.projectEditTfMode,
        tfFiles: { ...state.projectEditTfFiles },
        tfActiveFile: state.projectEditTfActiveFile,
        template: el('project-edit-template').value,
        config: el('project-edit-config').value,
    };
}

function _restoreEditContent(saved) {
    if (!saved) return;
    state.projectEditTfMode = saved.isTf;
    state.projectEditTfFiles = { ...saved.tfFiles };
    state.projectEditTfActiveFile = saved.tfActiveFile;
    el('project-edit-template').value = saved.template;
    el('project-edit-config').value = saved.config;
    state.projectEditConfig = saved.config;
    if (saved.isTf) {
        setProjectEditTemplateTab('terraform');
        if (saved.tfActiveFile) {
            el('project-edit-tf-template').value = saved.tfFiles[saved.tfActiveFile] || '';
        }
        renderProjectEditTfFileList();
    } else {
        setProjectEditTemplateTab('ros');
    }
    refreshPeHighlight();
}

async function loadEditVersions(projectName) {
    const wrap = el('project-edit-version-wrap');
    const sel = el('project-edit-version-select');
    if (!projectName) { wrap.style.display = 'none'; return; }
    try {
        const data = await api('GET', `/api/projects/${encodeURIComponent(projectName)}/versions`);
        _editVersionCache = data;
        const versions = data.versions || [];
        if (!versions.length) { wrap.style.display = 'none'; return; }
        wrap.style.display = '';
        sel.innerHTML = '';
        // Add "current" option
        const curOpt = document.createElement('option');
        curOpt.value = 'current';
        curOpt.textContent = `v${data.current_version} (${t('versionCurrent')})`;
        sel.appendChild(curOpt);
        for (const v of versions) {
            if (v.version === data.current_version) continue;
            const opt = document.createElement('option');
            opt.value = v.version;
            opt.textContent = `v${v.version}`;
            sel.appendChild(opt);
        }
        sel.value = 'current';
    } catch (e) {
        wrap.style.display = 'none';
    }
}

async function onEditVersionChange(projectName) {
    const sel = el('project-edit-version-select');
    const ver = sel.value;
    if (ver === 'current') {
        // Restore the original current-version content that was cached before switching
        if (_editOriginalContent) {
            _restoreEditContent(_editOriginalContent);
            _editOriginalContent = null;
            toast(t('versionRestoredCurrent'), 'info');
        }
        return;
    }
    // First time switching away from current: save current editor content
    if (!_editOriginalContent) {
        _editOriginalContent = _captureEditContent();
    }
    try {
        const v = await api('GET', `/api/projects/${encodeURIComponent(projectName)}/versions/${ver}`);
        // Replace template editor content
        if (state.projectEditTfMode) {
            state.projectEditTfFiles = { ...(v.template_files || {}) };
            const firstFile = Object.keys(state.projectEditTfFiles).filter(p => !p.endsWith('/')).sort()[0];
            state.projectEditTfActiveFile = firstFile || null;
            el('project-edit-tf-template').value = firstFile ? state.projectEditTfFiles[firstFile] : '';
            renderProjectEditTfFileList();
            highlightPeTf();
        } else {
            el('project-edit-template').value = v.template || '';
            highlightPeTemplate();
        }
        // Replace config editor content
        let config = v.config || '';
        if (!config && v.configs && v.configs.length) {
            config = v.configs[0].config || '';
        }
        state.projectEditConfig = stripProjectSection(config);
        el('project-edit-config').value = state.projectEditConfig;
        highlightPeConfig();
        toast(t('versionLoadedHint', {ver: ver}), 'info');
    } catch (e) {
        toast(t('versionLoadFailed'), 'error');
    }
}

/* ============== Start ============== */
document.addEventListener('DOMContentLoaded', init);
