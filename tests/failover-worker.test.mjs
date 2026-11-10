import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import worker, {isStaticPath} from '../edge/failover-worker.mjs';

test('published backup contains presentation files and offline scripts only', () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'habang-pages-test-'));
  const output = path.join(tempRoot, 'site');
  try {
    const siteRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
    execFileSync(process.execPath, [path.join(siteRoot, 'edge/build-fallback.mjs'), output], {cwd: siteRoot});
    for (const name of ['downloads', 'server', 'CNAME', '.env']) {
      assert.equal(fs.existsSync(path.join(output, name)), false, name);
    }
    const html = fs.readFileSync(path.join(output, 'index.html'), 'utf8');
    assert.match(html, /hb-fallback-notice/);
    assert.match(html, /src="community\.js\?/);
    assert.doesNotMatch(fs.readFileSync(path.join(output, 'community.js'), 'utf8'), /\/api\/session/);
    assert.doesNotMatch(fs.readFileSync(path.join(output, 'portal.js'), 'utf8'), /fetch\(/);
  } finally {
    assert.equal(path.dirname(path.resolve(tempRoot)), path.resolve(os.tmpdir()));
    fs.rmSync(tempRoot, {recursive: true, force: true});
  }
});

test('only presentation assets can use the static fallback', () => {
  for (const path of ['/', '/index.html', '/api.html', '/community.js', '/images/home/hero.png']) {
    assert.equal(isStaticPath(path), true, path);
  }
  for (const path of ['/api/session', '/auth/google', '/downloads/PhotoSorter.apk', '/server/app.py', '/.env']) {
    assert.equal(isStaticPath(path), false, path);
  }
});

test('healthy origin stays authoritative', async () => {
  const prior = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response('live', {status: 200}); };
  try {
    const result = await worker.fetch(new Request('https://habang222.pro/'));
    assert.equal(await result.text(), 'live');
    assert.equal(calls, 1);
  } finally { globalThis.fetch = prior; }
});

test('offline HTML comes from GitHub Pages without visitor credentials', async () => {
  const prior = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async request => {
    calls.push(request);
    if (calls.length === 1) throw new Error('origin offline');
    return new Response('<html><head></head><body><main>Portfolio</main></body></html>', {
      status: 200, headers: {'content-type': 'text/html'},
    });
  };
  try {
    const result = await worker.fetch(new Request('https://habang222.pro/guide.html?token=secret', {
      headers: {cookie: 'session=secret', authorization: 'Bearer secret'},
    }));
    const html = await result.text();
    assert.match(html, /서버가 일시적으로 연결되지/);
    assert.match(html, /Portfolio/);
    assert.equal(result.headers.get('x-habang-fallback'), 'github-pages');
    assert.equal(calls[1].url, 'https://habang2222.github.io/habage222.pro/guide.html');
    assert.equal(calls[1].headers.get('cookie'), null);
    assert.equal(calls[1].headers.get('authorization'), null);
  } finally { globalThis.fetch = prior; }
});

test('offline API and downloads never use public Pages', async () => {
  const prior = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response('offline', {status: 530}); };
  try {
    const api = await worker.fetch(new Request('https://habang222.pro/api/session'));
    assert.equal(api.status, 503);
    assert.match(api.headers.get('content-type'), /json/);
    const file = await worker.fetch(new Request('https://habang222.pro/downloads/PhotoSorter.apk'));
    assert.equal(file.status, 503);
    assert.equal(calls, 2);
  } finally { globalThis.fetch = prior; }
});

test('ordinary authorization and missing-file responses do not fail over', async () => {
  const prior = globalThis.fetch;
  globalThis.fetch = async () => new Response('denied', {status: 401});
  try {
    const result = await worker.fetch(new Request('https://habang222.pro/api/keys'));
    assert.equal(result.status, 401);
  } finally { globalThis.fetch = prior; }
});
