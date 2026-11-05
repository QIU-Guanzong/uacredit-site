import { Capacitor } from '@capacitor/core';
import { Browser } from '@capacitor/browser';
import { Share } from '@capacitor/share';
import { Network } from '@capacitor/network';
import { App } from '@capacitor/app';

const config = __APP_CONFIG__;
const publicPaths = new Set(__PUBLIC_PATHS__.filter(path => path !== '/404.html'));
const siteURL = new URL(config.publicOrigin);
const localURL = new URL(location.href);
const sameAddress = (left, right) => !left.username && !left.password
  && left.protocol === right.protocol && left.host === right.host;
const isLocalURL = url => sameAddress(url, localURL);
const isCompanyURL = url => sameAddress(url, siteURL);
const keys = { saved: 'uacredit.saved-public-pages.v1', tabs: 'uacredit.reader-tabs.v1',
  navigation: 'uacredit.reader-navigation.v1', undo: 'uacredit.bookmark-undo.v1' };
const historyKey = 'uacreditReader';
const definitions = [
  ['home', '首頁', '/index.html'], ['loans', '貸款', '/car-loan/index.html'],
  ['news', '消息', '/updates/index.html'], ['contact', '聯絡', '/contact/index.html'],
  ['my', '我的', '/mobile/index.html'],
];
const roots = Object.fromEntries(definitions.map(([id, , path]) => [id, path]));
function publicPath(value) {
  try {
    const url = new URL(value, location.href);
    if (!isLocalURL(url) && !isCompanyURL(url)) return null;
    let path = url.pathname;
    if (path === '/') path = '/index.html';
    else if (path.endsWith('/')) path += 'index.html';
    else if (!path.split('/').slice(-1)[0].includes('.')) path += '/index.html';
    return publicPaths.has(path) ? path : null;
  } catch { return null; }
}
function tabFor(path) {
  if (path === roots.my) return 'my';
  if (path === roots.contact) return 'contact';
  if (/^\/(car-loan|property-loan)(-application)?\/|^\/free-car-valuation\//.test(path)) return 'loans';
  if (['/index.html', '/about-us/index.html', '/faq/index.html', '/privacy/index.html',
    '/privacy-policy/index.html', '/disclaimer/index.html', '/money-lenders-ordinance/index.html',
    '/all-pages/index.html', '/cooperative-merchant/index.html'].includes(path)) return 'home';
  return 'news';
}
const localPath = publicPath(location.href) || roots.home;
const active = tabFor(localPath);
const personal = active === 'my';
const title = document.title.split('｜')[0];
function readSession(key) {
  try { return JSON.parse(sessionStorage.getItem(key) || 'null'); } catch { return undefined; }
}
function writeSession(key, value) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, JSON.stringify(value));
  } catch { /* Storage failure must not block public navigation. */ }
}
function validSaved(value) {
  const seen = new Set();
  return Array.isArray(value) ? value.filter(item => {
    if (!item || typeof item.title !== 'string' || !publicPaths.has(item.path) || seen.has(item.path)) return false;
    seen.add(item.path); return true;
  }).slice(0, 100) : [];
}
function savedPages() {
  try { return validSaved(JSON.parse(localStorage.getItem(keys.saved) || '[]')); } catch { return []; }
}
function storeSaved(value) {
  try { localStorage.setItem(keys.saved, JSON.stringify(value)); return true; }
  catch { toast('未能儲存收藏，請確認裝置尚有可用空間。', true); return false; }
}
function tabStates() {
  const value = readSession(keys.tabs);
  return Object.fromEntries(definitions.flatMap(([id]) => {
    const state = value?.[id];
    return state && publicPath(state.path) === state.path && tabFor(state.path) === id
      && Number.isFinite(state.scrollY) && state.scrollY >= 0
      ? [[id, { path: state.path, scrollY: Math.min(state.scrollY, 10000000) }]] : [];
  }));
}
const pending = readSession(keys.navigation);
writeSession(keys.navigation, null);
const previous = history.state?.[historyKey];
let entry = {
  depth: Number.isInteger(previous?.depth) && previous.depth >= 0 ? Math.min(previous.depth, 10000)
    : pending?.path === localPath && Number.isInteger(pending.depth) ? Math.max(0, Math.min(pending.depth, 10000)) : 0,
  scrollY: Number.isFinite(previous?.scrollY) ? Math.max(0, previous.scrollY)
    : pending?.path === localPath && Number.isFinite(pending.scrollY) ? Math.max(0, pending.scrollY) : 0,
};
let restoring = true, interacted = false, lifecycle = null, generation = 0;
let handles = [], toastTimer, scrollTimer, restoreFrame;
let sharing = false, openingExternal = false, undo = readSession(keys.undo);
document.documentElement.classList.add('native-app');
try { history.scrollRestoration = 'manual'; } catch { /* Preserve the WebView default if unavailable. */ }

const icons = {
  home: '<path d="m3 10 9-7 9 7v10H3z"/><path d="M9 20v-7h6v7"/>',
  loans: '<path d="M4 6h16v14H4zM8 3v6M16 3v6M8 13h8M8 16h5"/>',
  news: '<path d="M4 4h16v16H4zM8 8h8M8 12h8M8 16h5"/>',
  contact: '<path d="M5 4h4l2 5-3 2a15 15 0 0 0 5 5l2-3 5 2v4c-8 4-20-8-15-15Z"/>',
  my: '<circle cx="12" cy="7" r="4"/><path d="M4 21v-3a8 8 0 0 1 16 0v3"/>',
};
const tabs = document.createElement('nav');
tabs.className = 'native-tabs'; tabs.setAttribute('aria-label', 'App 主要導覽');
for (const [id, label, path] of definitions) {
  const link = document.createElement('a');
  link.href = path; link.dataset.tab = id;
  if (id === active) link.setAttribute('aria-current', 'page');
  link.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + icons[id] + '</svg><span>' + label + '</span>';
  tabs.append(link);
}
document.body.append(tabs);
const back = document.createElement('button');
back.type = 'button'; back.className = 'native-back';
back.setAttribute('aria-label', entry.depth > 0 ? '返回上一頁' : localPath !== roots[active]
  ? '返回' + definitions.find(([id]) => id === active)[1] : '返回首頁');
back.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 5-7 7 7 7"/></svg><span>返回</span>';
back.hidden = localPath === roots.home && entry.depth === 0;
document.querySelector('header .header-inner')?.prepend(back);
const tools = document.createElement('div'); tools.className = 'native-tools';
const network = document.createElement('span'); network.className = 'native-network';
network.textContent = '公開資料可離線閱讀'; tools.append(network);
const bookmark = document.createElement('button'); bookmark.type = 'button'; bookmark.className = 'native-bookmark';
const share = document.createElement('button'); share.type = 'button'; share.className = 'native-share'; share.textContent = '分享';
if (!personal) tools.append(bookmark, share);
else tools.classList.add('native-tools-personal');
document.querySelector('header')?.after(tools);
const toastBox = document.createElement('div');
toastBox.className = 'native-toast'; toastBox.hidden = true;
toastBox.setAttribute('role', 'status'); toastBox.setAttribute('aria-live', 'polite');
const toastMessage = document.createElement('span');
const undoButton = document.createElement('button');
undoButton.type = 'button'; undoButton.className = 'toast-undo'; undoButton.textContent = '復原';
undoButton.setAttribute('aria-label', '復原剛才移除的收藏'); undoButton.hidden = true;
toastBox.append(toastMessage, undoButton); document.body.append(toastBox);
const savedList = document.querySelector('#saved-list');
const savedHeading = document.querySelector('#saved-heading');
const clearSaved = document.querySelector('.clear-saved');
const accountButton = document.querySelector('#open-account');
if (accountButton) {
  accountButton.disabled = !config.accountOrigin;
  document.querySelector('#account-availability').textContent = config.accountOrigin
    ? '你仍可不登入，繼續瀏覽所有公開資料。' : '客戶中心準備中，公開內容仍可瀏覽。';
}

function focusAfter(target) {
  let control;
  if (target?.page === localPath && target.type === 'bookmark') control = bookmark;
  if (target?.page === localPath && target.type === 'clear' && clearSaved && !clearSaved.disabled) control = clearSaved;
  if (target?.page === localPath && target.type === 'remove') {
    control = [...(savedList?.querySelectorAll('[data-remove-path]') || [])].find(button => button.dataset.removePath === target.path);
  }
  (control || savedHeading || (!personal ? bookmark : back))?.focus({ preventScroll: true });
}
function dismissToast() {
  clearTimeout(toastTimer);
  if (document.activeElement === undoButton) focusAfter(undo?.focus);
  toastBox.hidden = true; undoButton.hidden = true;
}
function validUndo(value) {
  const before = validSaved(value?.before), removed = validSaved(value?.removed);
  return value && Number.isFinite(value.expiresAt) && value.expiresAt > Date.now()
    && value.expiresAt <= Date.now() + 5000 && removed.length > 0
    && removed.every(item => before.some(previous => previous.path === item.path));
}
function showUndo() {
  if (!validUndo(undo)) {
    if (document.activeElement === undoButton) focusAfter(undo?.focus);
    undo = null; writeSession(keys.undo, null); dismissToast(); return false;
  }
  clearTimeout(toastTimer);
  toastMessage.textContent = typeof undo.message === 'string' ? undo.message : '已移除收藏，5 秒內可復原。';
  undoButton.hidden = false; toastBox.hidden = false;
  toastTimer = setTimeout(() => {
    if (document.activeElement === undoButton) focusAfter(undo?.focus);
    undo = null; writeSession(keys.undo, null); dismissToast();
  }, Math.max(0, undo.expiresAt - Date.now()));
  return true;
}
function toast(message, important = false) {
  if (validUndo(undo)) {
    if (important) toastMessage.textContent = message + ' 仍可復原上一項操作。';
    return;
  }
  dismissToast(); toastMessage.textContent = message; toastBox.hidden = false;
  toastTimer = setTimeout(dismissToast, 2800);
}
function updateBookmark() {
  const saved = savedPages().some(item => item.path === localPath);
  bookmark.setAttribute('aria-pressed', String(saved)); bookmark.textContent = saved ? '已收藏' : '收藏';
}
function renderSaved(focusIndex = null) {
  updateBookmark();
  if (!savedList) return;
  const saved = savedPages(); if (clearSaved) clearSaved.disabled = saved.length === 0;
  savedList.replaceChildren();
  if (!saved.length) {
    const empty = document.createElement('p'); empty.className = 'saved-empty';
    empty.textContent = '尚未收藏資料。閱讀時點選「收藏」，便可在這裡找到。'; savedList.append(empty);
  }
  for (const item of saved) {
    const row = document.createElement('div'); row.className = 'saved-row'; row.setAttribute('role', 'listitem');
    const link = document.createElement('a'); link.href = item.path; link.textContent = item.title;
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '移除';
    remove.dataset.removePath = item.path; remove.setAttribute('aria-label', '移除收藏：' + item.title);
    row.append(link, remove); savedList.append(row);
  }
  if (focusIndex !== null) {
    const controls = [...savedList.querySelectorAll('[data-remove-path]')];
    (controls[Math.min(focusIndex, controls.length - 1)] || savedHeading)?.focus({ preventScroll: true });
  }
}
function removeSaved(paths, focus, message) {
  const before = savedPages(), removed = before.filter(item => paths.includes(item.path));
  if (!removed.length || !storeSaved(before.filter(item => !paths.includes(item.path)))) return false;
  undo = { before, removed, focus, message, expiresAt: Date.now() + 5000 };
  writeSession(keys.undo, undo); showUndo(); return true;
}
function restoreSaved() {
  if (!validUndo(undo)) { showUndo(); return; }
  const current = savedPages(), existing = new Set(current.map(item => item.path));
  const removed = new Set(validSaved(undo.removed).map(item => item.path));
  const restored = validSaved(undo.before).filter(item => existing.has(item.path) || removed.has(item.path));
  const restoredPaths = new Set(restored.map(item => item.path));
  const next = [...restored, ...current.filter(item => !restoredPaths.has(item.path))].slice(0, 100);
  if (!storeSaved(next)) return;
  const focus = undo.focus; undo = null; writeSession(keys.undo, null); dismissToast();
  renderSaved(); focusAfter(focus); toast('收藏已復原。');
}
function refreshTabs() {
  const states = tabStates();
  for (const link of tabs.querySelectorAll('a')) link.href = states[link.dataset.tab]?.path || roots[link.dataset.tab];
}
function savePosition() {
  if (restoring && !interacted) return;
  entry.scrollY = Math.max(0, Math.round(window.scrollY));
  try { history.replaceState({ ...history.state, [historyKey]: entry }, ''); } catch { /* Navigation still works. */ }
  const states = tabStates(); states[active] = { path: localPath, scrollY: entry.scrollY }; writeSession(keys.tabs, states);
}
function prepareNavigation(url, kind = 'link', replace = false) {
  const path = publicPath(url.href); if (!path) return false;
  savePosition();
  const state = kind === 'tab' ? tabStates()[tabFor(path)] : null;
  writeSession(keys.navigation, { path, depth: replace ? entry.depth : entry.depth + 1,
    scrollY: !url.hash && state?.path === path ? state.scrollY : 0 });
  return true;
}
function goBack(canGoBack = true) {
  savePosition();
  if (entry.depth > 0 && canGoBack) { history.back(); return; }
  const fallback = localPath !== roots[active] ? roots[active] : roots.home;
  if (fallback === localPath) return;
  const target = new URL(fallback, location.href); prepareNavigation(target, 'fallback', true); location.replace(target.href);
}
function restorePosition() {
  if (interacted) { restoring = false; savePosition(); return; }
  if (location.hash) {
    try { document.getElementById(decodeURIComponent(location.hash.slice(1)))?.scrollIntoView(); } catch { /* Ignore invalid fragments. */ }
  } else window.scrollTo(0, Math.max(0, entry.scrollY));
  cancelAnimationFrame(restoreFrame);
  restoreFrame = requestAnimationFrame(() => { restoring = false; savePosition(); });
}
function cancelledShare(error) {
  return error?.name === 'AbortError' || String(error?.message || '').trim().toLowerCase() === 'share canceled';
}
async function sharePage() {
  if (sharing || personal) return;
  const token = generation; sharing = true; share.disabled = true; share.setAttribute('aria-busy', 'true');
  try {
    const url = new URL(localPath.replace(/index\.html$/, ''), config.publicOrigin).href;
    if (Capacitor.isNativePlatform()) await Share.share({ title, url });
    else if (navigator.share) await navigator.share({ title, url });
    else { await navigator.clipboard.writeText(url); if (token === generation) toast('連結已複製。'); }
    // Closing a system share panel does not prove that a recipient received anything.
  } catch (error) {
    if (token === generation) toast(cancelledShare(error) ? '已取消分享。' : '未能開啟分享，請稍後再試。');
  } finally {
    if (token === generation && lifecycle) {
      sharing = false; share.disabled = false; share.removeAttribute('aria-busy'); share.focus({ preventScroll: true });
    }
  }
}
async function openExternal(url, account = false) {
  if (openingExternal) return;
  const token = generation; openingExternal = true;
  try { await Browser.open({ url, presentationStyle: 'fullscreen' }); }
  catch { if (token === generation) toast(account ? '未能連接客戶中心，請檢查網絡後再試。' : '未能開啟連結，請稍後再試。'); }
  finally { if (token === generation) openingExternal = false; }
}
function openAccount(path = '/account/') {
  if (!config.accountOrigin) { toast('客戶中心連線尚未開通，公開資料仍可直接瀏覽。'); return; }
  return openExternal(new URL(path, config.accountOrigin).href, true);
}
function handleLink(event) {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const link = event.target.closest('a[href]'); if (!link) return;
  const url = new URL(link.href, location.href), companyOrigin = isLocalURL(url) || isCompanyURL(url);
  if (companyOrigin && url.pathname.startsWith('/account')) {
    event.preventDefault();
    if (url.pathname.startsWith('/account/delete-info') && !config.accountOrigin) {
      const target = new URL('/mobile/index.html#account-info', location.href); prepareNavigation(target); location.assign(target.href);
    } else openAccount(url.pathname);
    return;
  }
  if (companyOrigin && url.pathname.startsWith('/admin')) {
    event.preventDefault(); toast('網站管理請使用獲授權的管理入口。'); return;
  }
  const path = publicPath(url.href);
  if (path) {
    if (link.dataset.tab) {
      event.preventDefault();
      if (link.dataset.tab === active) {
        if (localPath !== roots[active]) {
          const root = new URL(roots[active], location.href);
          prepareNavigation(root, 'reselect', true); location.replace(root.href);
        } else {
          try { history.replaceState({ ...history.state, [historyKey]: entry }, '', location.pathname + location.search); } catch {}
          interacted = true; restoring = false; window.scrollTo(0, 0); savePosition();
        }
        return;
      }
      const target = new URL(path, location.href); prepareNavigation(target, 'tab'); location.assign(target.href);
    } else if (path === localPath && url.search === location.search && url.hash) {
      event.preventDefault();
      savePosition();
      try {
        history.replaceState({ ...history.state, [historyKey]: entry }, '', url.pathname + url.search + url.hash);
        const target = document.getElementById(decodeURIComponent(url.hash.slice(1)));
        if (target) {
          target.scrollIntoView();
          if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
          target.focus({ preventScroll: true });
        }
      } catch { /* Invalid fragments do not block the public page. */ }
    } else if (path !== localPath || url.search !== location.search) {
      prepareNavigation(url);
      if (!isLocalURL(url) || link.target === '_blank') { event.preventDefault(); location.assign(path + url.search + url.hash); }
    }
    return;
  }
  if (!isLocalURL(url) && url.protocol === 'https:' && Capacitor.isNativePlatform()) {
    event.preventDefault(); openExternal(url.href);
  }
}
function mount() {
  if (lifecycle) return;
  lifecycle = new AbortController(); const token = ++generation, signal = lifecycle.signal;
  const on = (target, name, handler, options = {}) => target?.addEventListener(name, handler, { ...options, signal });
  refreshTabs(); renderSaved();
  const pendingUndo = readSession(keys.undo); if (pendingUndo !== undefined) undo = pendingUndo; showUndo();
  on(back, 'click', () => goBack()); on(share, 'click', sharePage); on(undoButton, 'click', restoreSaved);
  on(accountButton, 'click', () => openAccount());
  on(bookmark, 'click', event => {
    const saved = savedPages();
    if (saved.some(item => item.path === localPath)) {
      if (removeSaved([localPath], { type: 'bookmark', page: localPath }, '已移除收藏，5 秒內可復原。')) {
        updateBookmark(); if (event.detail === 0) undoButton.focus({ preventScroll: true });
      }
    } else if (storeSaved([...saved, { path: localPath, title }].slice(0, 100))) {
      updateBookmark(); toast('已加入這部裝置的收藏。');
    }
  });
  on(savedList, 'click', event => {
    const button = event.target.closest('[data-remove-path]'); if (!button) return;
    const index = [...savedList.querySelectorAll('[data-remove-path]')].indexOf(button);
    if (removeSaved([button.dataset.removePath], { type: 'remove', page: localPath, path: button.dataset.removePath }, '已移除收藏，5 秒內可復原。')) {
      renderSaved(index); if (event.detail === 0) undoButton.focus({ preventScroll: true });
    }
  });
  on(clearSaved, 'click', event => {
    if (removeSaved(savedPages().map(item => item.path), { type: 'clear', page: localPath }, '已清除收藏，5 秒內可復原。')) {
      renderSaved();
      if (event.detail === 0) undoButton.focus({ preventScroll: true });
      else savedHeading?.focus({ preventScroll: true });
    }
  });
  on(document, 'click', handleLink);
  on(window, 'scroll', () => { clearTimeout(scrollTimer); scrollTimer = setTimeout(savePosition, 120); }, { passive: true });
  for (const name of ['pointerdown', 'wheel', 'touchstart', 'keydown']) {
    on(window, name, () => { interacted = true; restoring = false; }, { passive: true });
  }
  on(window, 'storage', event => { if (event.key === keys.saved) renderSaved(); });
  if (Capacitor.isNativePlatform()) {
    const track = factory => Promise.resolve().then(factory).then(handle => {
      if (token === generation && lifecycle) handles.push(handle);
      else return Promise.resolve().then(() => handle.remove());
    }).catch(() => {});
    const updateNetwork = state => {
      if (token === generation && lifecycle) network.textContent = state.connected ? '公開資料可離線閱讀' : '目前離線 · 公開資料仍可閱讀';
    };
    Promise.resolve().then(() => Network.getStatus()).then(updateNetwork).catch(() => {});
    track(() => Network.addListener('networkStatusChange', updateNetwork));
    if (Capacitor.getPlatform() === 'android') track(() => App.addListener('backButton', ({ canGoBack }) => {
      if (localPath === roots.home && entry.depth === 0) App.exitApp(); else goBack(canGoBack);
    }));
  }
}
function unmount() {
  savePosition(); lifecycle?.abort(); lifecycle = null; generation++;
  clearTimeout(scrollTimer); clearTimeout(toastTimer); cancelAnimationFrame(restoreFrame);
  for (const handle of handles) Promise.resolve().then(() => handle.remove()).catch(() => {});
  handles = []; toastBox.hidden = true; sharing = false; openingExternal = false;
  share.disabled = false; share.removeAttribute('aria-busy');
}
window.addEventListener('pagehide', unmount);
window.addEventListener('pageshow', event => {
  const restored = history.state?.[historyKey]; if (restored && Number.isFinite(restored.scrollY)) entry = restored;
  if (event.persisted) { interacted = false; restoring = true; }
  mount(); restorePosition();
});
mount();
if (document.readyState === 'complete') restorePosition();
