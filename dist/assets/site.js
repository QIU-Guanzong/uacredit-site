document.documentElement.classList.add('js');
const menu = document.querySelector('.menu');
const nav = document.querySelector('#navigation');
const compactNav = matchMedia('(max-width: 980px)');
function setMenu(open, restoreFocus = false) {
  if (!menu || !nav) return;
  nav.hidden = compactNav.matches && !open;
  menu.setAttribute('aria-expanded', String(open));
  menu.textContent = open ? '關閉 −' : '選單 +';
  if (restoreFocus) menu.focus();
}
if (menu && nav) {
  setMenu(false);
  menu.addEventListener('click', () => setMenu(menu.getAttribute('aria-expanded') !== 'true'));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu.getAttribute('aria-expanded') === 'true') setMenu(false, true);
  });
  document.addEventListener('click', event => {
    if (menu.getAttribute('aria-expanded') === 'true' && !nav.contains(event.target) && !menu.contains(event.target)) setMenu(false);
  });
  nav.addEventListener('click', event => { if (event.target.closest('a')) setMenu(false); });
  compactNav.addEventListener('change', () => setMenu(false));
  addEventListener('pageshow', () => setMenu(false));
}

const filter = document.querySelector('.content-filter');
if (filter) {
  const query = filter.querySelector('input');
  const clear = filter.querySelector('.filter-clear');
  const status = filter.querySelector('.filter-status');
  const empty = document.querySelector('.filter-empty');
  const rows = [...document.querySelectorAll('.editorial-list > a')];
  const normal = value => value.normalize('NFKC').toLocaleLowerCase().replace(/\s+/g, ' ').trim();
  function applyFilter() {
    const words = normal(query.value).split(' ').filter(Boolean);
    let count = 0;
    rows.forEach(row => { row.hidden = !words.every(word => normal(row.textContent).includes(word)); if (!row.hidden) count++; });
    clear.hidden = !query.value;
    empty.hidden = count !== 0;
    status.textContent = words.length ? `找到 ${count} 項相符資料` : `共 ${rows.length} 項資料`;
  }
  filter.hidden = false;
  query.addEventListener('input', applyFilter);
  query.addEventListener('keydown', event => { if (event.key === 'Escape') { query.value = ''; applyFilter(); } });
  clear.addEventListener('click', () => { query.value = ''; applyFilter(); query.focus(); });
  addEventListener('pageshow', applyFilter);
  applyFilter();
}

const form = document.querySelector('#enquiry');
if (form) {
  const draftKey = 'uacredit.enquiry-options.v1';
  const output = document.querySelector('#enquiry-output');
  const message = document.querySelector('#message');
  const status = document.querySelector('#copy-status');
  const copy = document.querySelector('#copy');
  const open = document.querySelector('#open-enquiry');
  const service = new URLSearchParams(location.search).get('service');
  const selects = [...form.querySelectorAll('select')];
  function restoreDraft() {
    try {
      const draft = JSON.parse(sessionStorage.getItem(draftKey) || '{}');
      selects.forEach(select => { if ([...select.options].some(option => option.value === draft[select.name])) select.value = draft[select.name]; });
    } catch { /* Reading public pages remains available when storage is blocked. */ }
    if (!history.state?.enquiryServiceApplied) {
      if (service === 'property') form.elements.service.value = '物業貸款';
      if (service === 'car') form.elements.service.value = '汽車貸款';
      history.replaceState({ ...history.state, enquiryServiceApplied: true }, '');
    }
  }
  function saveDraft() {
    try { sessionStorage.setItem(draftKey, JSON.stringify(Object.fromEntries(selects.map(select => [select.name, select.value])))); } catch { /* No personal details are stored. */ }
  }
  function clearOutput() { output.hidden = true; message.value = ''; status.textContent = ''; copy.textContent = '複製文字'; }
  restoreDraft();
  form.addEventListener('submit', event => {
    event.preventDefault();
    saveDraft();
    message.value = `你好，我想查詢${form.elements.service.value}。\n我想了解${form.elements.topic.value}，請問可以怎樣安排？`;
    const contact = document.querySelector('.contact-list a[href*="wa.me/"]');
    const target = new URL(contact?.href || open.href);
    target.searchParams.set('text', message.value);
    open.href = target.href;
    output.hidden = false;
    status.textContent = '內容已整理，尚未發送。';
    copy.focus();
  });
  form.addEventListener('change', () => { saveDraft(); clearOutput(); });
  form.addEventListener('reset', () => {
    try { sessionStorage.removeItem(draftKey); } catch {}
    clearOutput();
    status.textContent = '查詢選項已重設。';
  });
  copy.addEventListener('click', async () => {
    if (copy.disabled) return;
    copy.disabled = true;
    try { await navigator.clipboard.writeText(message.value); copy.textContent = '已複製'; status.textContent = '已複製。你可以貼到對話，再自行發送。'; }
    catch { message.focus(); message.select(); status.textContent = '請複製已選取的文字。'; }
    finally { copy.disabled = false; }
  });
  addEventListener('pageshow', () => { copy.disabled = false; });
}
