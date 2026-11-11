const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function consoleContext() {
    const elements = new Map();
    const created = [];
    function element() {
        return {innerHTML: '', textContent: '', children: [], classList: {add() {}, remove() {}},
            addEventListener() {}, appendChild(child) { this.children.push(child); }};
    }
    const context = vm.createContext({
        document: {
            getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
            createElement() { const node = element(); created.push(node); return node; },
            addEventListener() {},
        },
        Headers, sessionStorage: {getItem() { return 'synthetic-token'; }},
        fetch: async (url, options) => ({ok: true, status: 200, url, options}),
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'app.js'), 'utf8'), context);
    return {context, created, elements};
}

test('gateway calls include the configured tab credential', async () => {
    const {context} = consoleContext();
    const response = await vm.runInContext('apiFetch("/api/users")', context);
    assert.equal(response.options.headers.get('Authorization'), 'Bearer synthetic-token');
});

test('log identities and model fields render as text', () => {
    const {context, created} = consoleContext();
    const payload = '<img src=x onerror="bad()">';
    context.input = {timestamp: '2026-11-09 12:00:00', latency_ms: 1, action: payload,
        conversation_type: 'personal', sender_user_id: payload, message_text: 'Hi', reason: 'Synthetic',
        message_type_pred: payload};
    vm.runInContext('logs = [input]; renderLogs()', context);
    assert.ok(!created[0].innerHTML.includes('<img'));
    assert.ok(created[0].innerHTML.includes('&lt;img'));
});

test('RAG metadata renders as text in the inspector', () => {
    const {context, created} = consoleContext();
    context.input = {action: 'digest', message_type_pred: 'personal', confidence: 0.9, latency_ms: 1,
        rag_matches: [{distance: 0.1, message_text: 'Hi', metadata: {sender_user_id: '<img src=x>'}}]};
    vm.runInContext('showInspector(input)', context);
    assert.ok(!created[0].innerHTML.includes('<img'));
    assert.ok(created[0].innerHTML.includes('&lt;img'));
});

test('missing data has explicit setup instructions', () => {
    const {context, elements} = consoleContext();
    vm.runInContext('renderDatasetStatus({ready: false, missing: ["users.csv"], errors: []})', context);
    const text = elements.get('dataset-status').textContent;
    assert.ok(text.includes('dataset_store.py bootstrap'));
    assert.ok(text.includes('never overwritten'));
});

test('CSV errors are displayed as text without HTML injection', () => {
    const {context, elements} = consoleContext();
    context.input = {ready: false, missing: [], errors: ['<img src=x> missing columns']};
    vm.runInContext('renderDatasetStatus(input)', context);
    assert.ok(elements.get('dataset-status').textContent.includes('<img src=x>'));
    assert.equal(elements.get('dataset-status').innerHTML, '');
});

test('dataset status is fetched through the authenticated API helper', async () => {
    const {context, elements} = consoleContext();
    let received;
    context.fetch = async (url, options) => {
        received = {url, options};
        return {ok: true, status: 200, json: async () => ({ready: true, offline_mode: true})};
    };
    await vm.runInContext('fetchDatasetStatus()', context);
    assert.equal(received.url, '/api/dataset/status');
    assert.equal(received.options.headers.get('Authorization'), 'Bearer synthetic-token');
    assert.ok(elements.get('dataset-status').textContent.includes('offline mode'));
});
