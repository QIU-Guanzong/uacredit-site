import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

// Read-only checks of the prepared guest bundle. This does not sign, upload,
// contact a service, or establish store approval or publisher ownership.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const site = path.dirname(root);
const target = path.join(root, 'www');
const failures = [];
const warnings = new Set();
let checks = 0;
function check(condition, message) {
  checks++;
  if (!condition) failures.push(message);
}
async function json(file) {
  return JSON.parse(await fs.readFile(path.join(root, file), 'utf8'));
}
async function files(folder, prefix = '') {
  const result = [];
  for (const entry of await fs.readdir(folder, { withFileTypes: true })) {
    const relative = path.posix.join(prefix, entry.name);
    check(!entry.isSymbolicLink(), `${relative}: bundle inputs must not contain symbolic links`);
    if (entry.isDirectory()) result.push(...await files(path.join(folder, entry.name), relative));
    else if (entry.isFile()) result.push(relative);
  }
  return result.sort();
}
function sameSet(actual, expected, label) {
  const a = new Set(actual), b = new Set(expected);
  check(a.size === actual.length, `${label}: duplicate paths`);
  for (const item of b) check(a.has(item), `${label}: missing ${item}`);
  for (const item of a) check(b.has(item), `${label}: unexpected ${item}`);
}
function origin(value, label, approvedHosts) {
  try {
    const u = new URL(value);
    check(u.protocol === 'https:' && !u.username && !u.password && u.pathname === '/' && !u.search && !u.hash && !u.port,
      `${label}: must be a plain HTTPS origin without credentials, port, path, query or fragment`);
    check(approvedHosts.includes(u.hostname), `${label}: company hostname must be explicitly approved in this verifier`);
  } catch {
    check(false, `${label}: invalid origin`);
  }
}
const decode = value => value.replace(/&(?:amp|quot|apos|lt|gt|#(\d+)|#x([\da-f]+));/gi,
  (all, decimal, hex) => {
    if (decimal || hex) {
      const codepoint = Number.parseInt(decimal || hex, decimal ? 10 : 16);
      return codepoint <= 0x10ffff ? String.fromCodePoint(codepoint) : all;
    }
    return ({ '&amp;': '&', '&quot;': '"', '&apos;': "'", '&lt;': '<', '&gt;': '>' })[all.toLowerCase()] || all;
  });
function attributes(html) {
  const result = [];
  // Consume entire tags and every attribute in order: a legacy form's escaped
  // HTML inside an input value is text, not another navigable link.
  for (const tag of html.matchAll(/<[a-z][\w:-]*\b(?:[^<>"']|"[^"]*"|'[^']*')*>/gi)) {
    for (const match of tag[0].matchAll(/\s+([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g)) {
      const kind = match[1].toLowerCase();
      if (kind === 'href' || kind === 'src') result.push({ kind, value: decode(match[2] ?? match[3] ?? match[4] ?? '') });
    }
  }
  return result;
}
const dynamic = pathname => /^\/(?:account|admin)(?:\/|$)/.test(pathname);
const publicTabs = ['/index.html', '/car-loan/index.html', '/updates/index.html', '/contact/index.html', '/mobile/index.html'];

try {
  const [pkg, config, cap, lock] = await Promise.all([
    json('package.json'), json('app-config.json'), json('capacitor.config.json'), json('package-lock.json'),
  ]);
  check(/^\d+\.\d+\.\d+$/.test(config.version), 'app-config: semantic version required');
  check(Number.isSafeInteger(config.build) && config.build > 0, 'app-config: positive integer build required');
  check(pkg.version === config.version, 'package version differs from app-config');
  check(pkg.private === true, 'mobile package must remain private');
  check(Number(process.versions.node.split('.')[0]) >= 22, 'Node 22 or later is required by the mobile package');
  check(lock.version === pkg.version && lock.packages?.['']?.version === pkg.version, 'package lock version differs');
  for (const [name, version] of Object.entries({ ...pkg.dependencies, ...pkg.devDependencies })) {
    check(/^\d+\.\d+\.\d+$/.test(version), `${name}: dependency must be pinned`);
    check(lock.packages?.[`node_modules/${name}`]?.version === version, `${name}: lock differs from pinned dependency`);
  }
  check(cap.appId === 'hk.uacredit.app' && cap.appName === '環聯信貸' && cap.webDir === 'www', 'Capacitor package identity or webDir differs');
  check(!Object.hasOwn(cap.server || {}, 'url'), 'Capacitor server.url would replace the bundled guest site');
  check(!cap.server?.cleartext && !cap.server?.allowNavigation?.length, 'Capacitor must not allow cleartext or unrestricted navigation');
  check(cap.android?.allowMixedContent === false && cap.android?.webContentsDebuggingEnabled === false,
    'Android mixed content and WebView debugging must be disabled');
  origin(config.publicOrigin, 'publicOrigin', ['uacredit.hk', 'www.uacredit.hk']);
  if (config.accountOrigin !== null) {
    origin(config.accountOrigin, 'accountOrigin', ['uacredit.hk', 'www.uacredit.hk', 'account.uacredit.hk', 'accounts.uacredit.hk']);
    check(config.publisherConfirmed && config.privacyAndDeletionUrlsConfirmed,
      'Account service requires confirmed publisher and public privacy/deletion endpoints');
  }

  const [sourceFiles, bundleFiles] = await Promise.all([files(path.join(site, 'dist')), files(target)]);
  const omittedAssets = new Set(['assets/admin.css', 'assets/editor.js', 'assets/account.css', 'assets/account.js']);
  const expectedFiles = [...sourceFiles.filter(file => !omittedAssets.has(file)), 'mobile/index.html', 'assets/mobile.css', 'assets/mobile.js', 'assets/public-pages.json'];
  sameSet(bundleFiles, expectedFiles, 'bundled files');
  const bundleSet = new Set(bundleFiles);
  const htmlFiles = bundleFiles.filter(file => file.endsWith('.html'));
  const pages = htmlFiles.filter(file => file.endsWith('index.html'));
  check(pages.length === 53, `Expected 53 public pages; found ${pages.length}`);
  check(htmlFiles.length === 54 && bundleSet.has('404.html'), 'Expected only 53 public pages and one 404 page');
  const manifest = await json('www/assets/public-pages.json');
  check(Array.isArray(manifest) && manifest.every(item => typeof item === 'string'), 'Public-page manifest must be a string array');
  if (Array.isArray(manifest)) sameSet(manifest, htmlFiles.map(file => '/' + file), 'public-page manifest');

  let localReferences = 0;
  let dynamicReferences = 0;
  let externalDocuments = 0;
  const htmlContents = new Map();
  const publicGraph = new Map();
  for (const file of bundleFiles) {
    const segments = file.toLowerCase().split('/');
    check(!segments.some(part => /^(?:\.git|\.env(?:\..*)?|accounts?|admin|instance|templates|work|node_modules|__pycache__|backups?|credentials?)$/.test(part)),
      `${file}: private/source directory or hidden configuration in bundle`);
    check(!/\.(?:db|db3|sqlite|sqlite3|sql|pem|key|p12|pfx|jks|keystore|mobileprovision|py|pyc|map|log|toml|yaml|yml|zip|tar|gz)$/i.test(file),
      `${file}: private data, source or archive file in bundle`);
    const bytes = await fs.readFile(path.join(target, file));
    check(!bytes.subarray(0, 16).equals(Buffer.from('SQLite format 3\0')), `${file}: database payload in bundle`);
    if (!/\.(?:html|js|css|json|txt)$/i.test(file)) continue;
    const content = bytes.toString('utf8');
    check(!/-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----/.test(content), `${file}: private key payload in bundle`);
    check(!/(?:scrypt|pbkdf2:sha256):[^\s<]{10,}\$|\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}/.test(content), `${file}: password hash payload in bundle`);
    if (!file.endsWith('.html')) continue;
    htmlContents.set(file, content);
    publicGraph.set(file, new Set());
    check(!dynamic('/' + file), `${file}: account or staff HTML must not be bundled`);
    check(!/<input\b[^>]*\btype\s*=\s*["']?password\b/i.test(content), `${file}: account credential form in public bundle`);
    check(!/\b(?:password_hash|auth_version|customer_id|identity_events)\b/.test(content), `${file}: account-data marker in public HTML`);
    check(!/<base\b|http-equiv\s*=\s*["']?refresh\b/i.test(content), `${file}: guest document must not redirect or replace its base URL`);
    if (file !== '404.html') {
      check((content.match(/href="\/assets\/mobile\.css"/g) || []).length === 1, `${file}: mobile stylesheet must be included once`);
      check((content.match(/src="\/assets\/mobile\.js"/g) || []).length === 1, `${file}: mobile script must be included once`);
    }
    check((content.match(/viewport-fit=cover/g) || []).length === 1, `${file}: exactly one safe-area viewport setting required`);
    for (const { kind, value } of attributes(content)) {
      if (!value || value.startsWith('#')) continue;
      if (value.startsWith('//')) {
        check(false, `${file}: protocol-relative ${kind} can escape the bundled app`);
        continue;
      }
      let u;
      try { u = new URL(value, `https://bundled.invalid/${file}`); }
      catch { check(false, `${file}: invalid ${kind}`); continue; }
      if (u.origin !== 'https://bundled.invalid') {
        check(['https:', 'http:', 'tel:', 'mailto:', 'data:'].includes(u.protocol), `${file}: unsupported ${kind} scheme`);
        if (u.protocol === 'http:') warnings.add('An inherited external HTTP link remains; it opens outside the bundled app.');
        if (kind === 'src' && !value.startsWith('data:')) {
          externalDocuments++;
          warnings.add('External embedded content needs a connection; only bundled public information is available offline.');
        }
        continue;
      }
      let pathname;
      try { pathname = decodeURIComponent(u.pathname); }
      catch { check(false, `${file}: invalid encoded local path`); continue; }
      if (dynamic(pathname)) {
        check(kind === 'href', `${file}: account/admin resources must not load inside the guest WebView`);
        dynamicReferences++;
        continue;
      }
      localReferences++;
      let relative = pathname.replace(/^\//, '');
      if (!relative || relative.endsWith('/')) relative += 'index.html';
      check(bundleSet.has(relative), `${file}: missing local ${kind} target ${relative}`);
      if (kind === 'href' && relative.endsWith('.html')) {
        check(pathname.endsWith('.html'), `${file}: local page links must use explicit HTML asset paths`);
        publicGraph.get(file).add(relative);
      }
    }
  }

  const bundle = await fs.readFile(path.join(target, 'assets/mobile.js'), 'utf8');
  check(!bundle.includes('__APP_CONFIG__') && !bundle.includes('__PUBLIC_PATHS__'), 'Mobile configuration/allowlist was not injected');
  for (const route of publicTabs) {
    check(bundleSet.has(route.slice(1)), `Public navigation: missing ${route}`);
    check(bundle.includes(JSON.stringify(route)), `Public navigation: ${route} is not in the mobile bundle`);
  }
  for (const [file, content] of htmlContents) {
    if (['mobile/index.html', '404.html'].includes(file)) continue;
    for (const route of ['/car-loan/index.html', '/property-loan/index.html', '/updates/index.html', '/contact/index.html']) {
      check(content.includes(`href="${route}"`), `${file}: missing public navigation ${route}`);
    }
  }
  // The native tab bar is added to each regular document by mobile.js. Follow
  // only public local destinations: reaching a page must never need an account.
  for (const [file, edges] of publicGraph) {
    if (file !== '404.html') for (const route of publicTabs) edges.add(route.slice(1));
  }
  const reachable = new Set();
  const queue = ['index.html'];
  while (queue.length) {
    const file = queue.pop();
    if (reachable.has(file)) continue;
    reachable.add(file);
    for (const next of publicGraph.get(file) || []) if (!reachable.has(next)) queue.push(next);
  }
  for (const file of pages) check(reachable.has(file), `${file}: cannot be reached through guest navigation`);
  const shell = htmlContents.get('mobile/index.html') || '';
  check(shell.includes('以訪客身份瀏覽') && shell.includes('不會自動建立訪客帳戶'), 'Guest shell must explain account-free use');
  check(shell.includes('id="account-info"') && shell.includes('刪除帳戶說明'), 'Guest shell must provide deletion instructions');
  check(shell.includes('id="saved-list"') && shell.includes('clear-saved'), 'Guest shell must provide saved-page list and clearing');

  // Inspect synchronized native configuration without changing platform files.
  for (const platformFile of ['android/app/src/main/assets/capacitor.config.json', 'ios/App/App/capacitor.config.json']) {
    const native = await json(platformFile);
    check(native.appId === cap.appId && native.appName === cap.appName && native.webDir === cap.webDir, `${platformFile}: package identity differs`);
    check(!Object.hasOwn(native.server || {}, 'url'), `${platformFile}: server.url would bypass bundled guest pages`);
    check(native.android?.allowMixedContent === false && native.android?.webContentsDebuggingEnabled === false, `${platformFile}: WebView safety flags differ`);
  }
  const gradle = await fs.readFile(path.join(root, 'android/app/build.gradle'), 'utf8');
  const project = await fs.readFile(path.join(root, 'ios/App/App.xcodeproj/project.pbxproj'), 'utf8');
  check(gradle.match(/applicationId\s+["']([^"']+)/)?.[1] === cap.appId, 'Android applicationId differs');
  check(gradle.match(/versionName\s+["']([^"']+)/)?.[1] === config.version, 'Android versionName differs');
  check(Number(gradle.match(/versionCode\s+(\d+)/)?.[1]) === config.build, 'Android versionCode differs');
  for (const [field, expected] of [['MARKETING_VERSION', config.version], ['CURRENT_PROJECT_VERSION', String(config.build)], ['PRODUCT_BUNDLE_IDENTIFIER', cap.appId]]) {
    const values = [...project.matchAll(new RegExp(`\\b${field}\\s*=\\s*([^;]+);`, 'g'))].map(match => match[1].trim().replace(/^"|"$/g, ''));
    check(values.length >= 2 && values.every(value => value === expected), `iOS ${field} differs between configurations`);
  }
  const gates = Object.entries({
    publisherConfirmed: config.publisherConfirmed,
    currentProductTermsConfirmed: config.currentProductTermsConfirmed,
    privacyAndDeletionUrlsConfirmed: config.privacyAndDeletionUrlsConfirmed,
  }).filter(([, value]) => !value).map(([name]) => name);
  console.log(JSON.stringify({
    status: failures.length ? 'failed' : 'passed',
    checks, publicPages: pages.length, additional404Page: bundleSet.has('404.html'), bundledFiles: bundleFiles.length,
    localReferences, guestReachablePages: pages.filter(file => reachable.has(file)).length,
    dynamicAccountOrAdminLinks: dynamicReferences, externalEmbeddedContent: externalDocuments,
    version: config.version, build: config.build, accountService: config.accountOrigin ? 'configured' : 'disabled',
    mobileBundleSha256: createHash('sha256').update(bundle).digest('hex'),
    pendingReleaseGates: gates, warnings: [...warnings], failures,
  }, null, 2));
  process.exitCode = failures.length ? 1 : 0;
} catch (error) {
  // Do not print input contents or arbitrary environment values on failure.
  console.error(JSON.stringify({ status: 'failed', checks, failures: [...failures, `Verification could not finish (${error.code || error.name}). Build and sync the mobile project first.`] }, null, 2));
  process.exitCode = 1;
}
