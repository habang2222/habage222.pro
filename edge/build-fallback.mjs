import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';

const source = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const destination = path.resolve(process.argv[2] || '');
if (!process.argv[2] || destination === source || destination.startsWith(source + path.sep)) {
  throw new Error('Use a separate output directory for the static fallback');
}
fs.mkdirSync(destination, {recursive: true});
const notice = '<div class="hb-fallback-notice" role="status" aria-live="polite">서버가 일시적으로 연결되지 않아 정적 화면을 보여 드립니다. 로그인, 댓글, 다운로드, API 키, 서버 대여 및 원격 접속은 복구 후 이용할 수 있습니다.</div>';
const style = '<link rel="stylesheet" href="offline.css">';
function assetVersion(name) {
  return createHash('sha256').update(fs.readFileSync(path.join(source, name))).digest('hex').slice(0, 12);
}
for (const entry of fs.readdirSync(source, {withFileTypes: true})) {
  if (!entry.isFile() || !/\.(?:html|css|js)$/.test(entry.name)) continue;
  if (['community.js', 'portal.js', 'support.js', 'host-desktop.js', 'remote-desktop.js'].includes(entry.name)) continue;
  const input = path.join(source, entry.name);
  const output = path.join(destination, entry.name);
  if (!entry.name.endsWith('.html')) {
    fs.copyFileSync(input, output);
    continue;
  }
  let html = fs.readFileSync(input, 'utf8');
  html = html.replace(/<\/head>/i, style + '</head>');
  if (entry.name === 'index.html') {
    html = html.replace(/\bsrc="(\/?)((?:links|home)\.js)(?:\?[^"]*)?"/gi,
      (_match, slash, name) => `src="${slash}${name}?v=${assetVersion(name)}"`);
    html = html.replace(/(<header class="home-hero"[^>]*>[\s\S]*?<\/header>)/i, match => match + notice);
  } else {
    html = html.replace(/<body(?:\s[^>]*)?>/i, match => match + notice);
  }
  // Relative static paths also work when someone opens the independent
  // github.io project URL directly, outside the Cloudflare route.
  html = html.replace(/(\b(?:href|src)=")\/(?!\/)([a-z0-9-]+\.(?:html|css|js)(?:\?[^"#]*)?|images\/[^"#]+)(")/gi, '$1$2$3');
  html = html.replace(/(\bhref=")\/("|#[^\"]*")/gi, '$1.$2');
  fs.writeFileSync(output, html, 'utf8');
}
fs.cpSync(path.join(source, 'images'), path.join(destination, 'images'), {recursive: true});
for (const [name, origin] of [
  ['community.js', 'offline-community.js'],
  ['portal.js', 'offline-portal.js'],
  ['support.js', 'offline-support.js'],
  ['host-desktop.js', 'offline-host-desktop.js'],
  ['remote-desktop.js', 'offline-remote-desktop.js'],
  ['offline.css', 'offline.css'],
]) fs.copyFileSync(path.join(source, 'edge', origin), path.join(destination, name));
fs.writeFileSync(path.join(destination, '.nojekyll'), '');
for (const forbidden of ['downloads', 'server', 'data', 'config', '.env']) {
  if (fs.existsSync(path.join(destination, forbidden))) throw new Error(`Forbidden output: ${forbidden}`);
}
console.log(`Prepared ${fs.readdirSync(destination).length} static entries`);
