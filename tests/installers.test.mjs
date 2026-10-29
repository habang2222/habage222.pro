import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import os from 'node:os';
const root = fileURLToPath(new URL('../', import.meta.url));
const task = fileURLToPath(new URL('./', import.meta.url));
const outputRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'habang-helper-tests-'));
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'downloads/manifest.json')));
for (const [name, expected] of Object.entries(manifest.sha256)) {
  const content = fs.readFileSync(path.join(root, 'downloads', name));
  assert.equal(crypto.createHash('sha256').update(content).digest('hex'), expected, name);
  if (name.endsWith('.cmd')) assert(!/(?<!\r)\n/.test(content.toString()), `CRLF required: ${name}`);
  if (name.endsWith('.sh')) assert(!content.includes(13), 'Shell script must use LF');
}
let internalLinks = 0;
for (const name of ['index.html', 'mglogwh.html', 'lecture-alarm.html', 'random-backspace.html']) {
  const html = fs.readFileSync(path.join(root, name), 'utf8');
  assert(html.includes('<html lang="ko">'));
  assert.equal((html.match(/<h1[ >]/g) || []).length, 1);
  for (const match of html.matchAll(/(?:href|src)="([^"?#]+)(?:[?#][^"]*)?"/g)) {
    const link = match[1];
    if (/^https?:/.test(link)) continue;
    if (link === '/') continue;
    assert(fs.existsSync(path.join(root, link)), `${name}: missing ${link}`);
    internalLinks++;
  }
}
const scenarios = [
  ['LectureAlarm-Setup.cmd', 'success', 0],
  ['LectureAlarm-Setup.cmd', 'repeat', 0],
  ['LectureAlarm-Setup.cmd', 'modified', 1],
  ['LectureAlarm-Setup.cmd', 'native-failure', 1],
  ['LectureAlarm-Setup.cmd', 'corrupt', 1],
  ['LectureAlarm-Setup.cmd', 'missing-chrome', 1],
  ['RandomBackspace-Setup.cmd', 'success', 0],
  ['RandomBackspace-Setup.cmd', 'repeat', 0],
  ['RandomBackspace-Setup.cmd', 'modified', 1],
  ['RandomBackspace-Setup.cmd', 'corrupt', 1],
  ['RandomBackspace-Setup.cmd', 'missing-chrome', 1],
  ['MGlogWH-Setup.cmd', 'success', 0],
  ['MGlogWH-Setup.cmd', 'corrupt', 1],
  ['MGlogWH-Setup.cmd', 'missing-wsl-distro', 1],
  ['MGlogWH-Setup.cmd', 'linux-failure', 1]
];
const run = (file, scenario, testRoot) => spawnSync('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', path.join(task, 'mock-helper.ps1'), '-Helper', path.join(root, 'downloads', file), '-Scenario', scenario, '-TestRoot', testRoot], { encoding: 'utf8', timeout: 30000 });
for (const [index, [file, scenario, expected]] of scenarios.entries()) {
  const testRoot = path.join(outputRoot, `case-${index}`);
  fs.mkdirSync(testRoot, { recursive: true });
  if (['repeat', 'modified'].includes(scenario)) {
    const first = run(file, 'success', testRoot);
    assert.equal(first.status, 0, first.stdout + first.stderr);
    fs.writeFileSync(path.join(testRoot, 'calls.txt'), '');
    if (scenario === 'modified') {
      const app = file.startsWith('Lecture') ? 'lecture-alarm/v2.2.0' : 'random-backspace/f64bdb1';
      fs.appendFileSync(path.join(testRoot, 'localappdata/HabangTools', app, 'manifest.json'), '\nchanged');
    }
  }
  const result = run(file, scenario, testRoot);
  assert.equal(result.status, expected, `${file} ${scenario}: ${result.stdout}\n${result.stderr}`);
  const callsPath = path.join(testRoot, 'calls.txt');
  const calls = fs.existsSync(callsPath) ? fs.readFileSync(callsPath, 'utf8') : '';
  if (expected !== 0) assert(!calls.includes('open '), `${file} ${scenario} must not open a success page`);
  if (expected === 0 && !file.startsWith('MG')) {
    assert(calls.includes('chrome://extensions/'));
    assert(calls.includes('clipboard '));
  }
  if (expected === 0 && file.startsWith('MG')) assert(calls.includes('open http://127.0.0.1:8765'));
  console.log(`PASS ${file}: ${scenario}`);
}
console.log(`Verified ${internalLinks} internal asset links, ${Object.keys(manifest.sha256).length} checksums, and ${scenarios.length} isolated helper cases. No installation, browser, clipboard or registry changes were performed.`);
