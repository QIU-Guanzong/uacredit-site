import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const source = fs.readFileSync(path.join(repo, 'mobile/src/mobile.js'), 'utf8')
  .split('const pending =')[0].replace(/^import .*;\n/gm, '');
const manifest = path.join(repo, 'mobile/www/assets/public-pages.json');
if (!fs.existsSync(manifest)) throw new Error('Build the mobile public assets before running URL-scheme regression tests.');
const publicPaths = JSON.parse(fs.readFileSync(manifest, 'utf8')).filter(route => route !== '/404.html');
const checks = [];
for (const base of ['capacitor://localhost/index.html', 'https://localhost/index.html', 'http://127.0.0.1:8753/index.html']) {
  const context = { URL, location: { href: base }, document: { title: '測試｜環聯' } };
  const prepared = source.replace('__APP_CONFIG__', JSON.stringify({ publicOrigin: 'https://uacredit.hk' }))
    .replace('__PUBLIC_PATHS__', JSON.stringify(publicPaths));
  // Execute the actual helper prefix without booting a DOM or mocking URL semantics.
  vm.runInNewContext(prepared + '\nglobalThis.testAPI={publicPath,isLocalURL,roots};', context);
  const api = context.testAPI;
  for (const route of publicPaths) checks.push({ base, name: 'local public ' + route, passed: api.publicPath(route) === route });
  checks.push({ base, name: 'company public URL', passed: api.publicPath('https://uacredit.hk/car-loan/') === '/car-loan/index.html' });
  for (const value of ['alien://localhost/car-loan/', 'capacitor://foreign/car-loan/', 'https://foreign.example/car-loan/', '/404.html', '/account/login/', '/admin/']) {
    checks.push({ base, name: 'reject ' + value, passed: api.publicPath(value) === null });
  }
  for (const route of Object.values(api.roots)) {
    const url = new URL(route, base);
    checks.push({ base, name: 'local navigation URL ' + route,
      passed: api.isLocalURL(url) && url.href.startsWith(base.slice(0, base.lastIndexOf('/') + 1)) });
  }
}
const report = { scope: 'Actual source helper prefix with native/custom and HTTPS URL bases; not native GUI/plugin verification.',
  checks, passed: checks.filter(check => check.passed).length, failed: checks.filter(check => !check.passed) };
const out = path.join(repo, 'work/mobile/evidence');
fs.mkdirSync(out, { recursive: true });
fs.writeFileSync(path.join(out, 'v3-mobile-url-qa.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({ passed: report.passed, failed: report.failed }, null, 2));
if (report.failed.length) process.exitCode = 1;
