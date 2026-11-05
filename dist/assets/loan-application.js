/* Submit only to UACredit's application service; never infer success from a request alone. */
(() => {
  const form = document.querySelector('#loan-application');
  if (!form) return;
  const button = document.querySelector('#loan-submit');
  const status = document.querySelector('#loan-status');
  const result = document.querySelector('#loan-result');
  const reference = document.querySelector('#loan-reference');
  let key = null;
  let submitted = null;
  let uncertain = false;
  let ready = false;
  let sending = false;

  function message(text, contact = false) {
    status.textContent = text;
    if (contact) {
      const link = document.createElement('a');
      link.href = '/contact/';
      link.textContent = '聯絡環聯';
      status.append(' ', link, '。');
    }
  }
  function freshKey() {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
  }
  function currentPayload() {
    return {
      service: form.dataset.service,
      name: form.elements.name.value.trim(),
      phone: form.elements.phone.value.trim(),
      amount: form.elements.amount.value.trim(),
      details: form.elements.details.value.trim(),
      consent: form.elements.consent.checked
    };
  }
  function restoreLink() {
    const restore = document.createElement('button');
    restore.type = 'button';
    restore.className = 'loan-restore';
    restore.textContent = '還原上次資料';
    restore.addEventListener('click', () => {
      const payload = JSON.parse(submitted);
      for (const field of ['name', 'phone', 'amount', 'details']) form.elements[field].value = payload[field];
      form.elements.consent.checked = payload.consent;
      message('資料已還原。請再次提交，或聯絡環聯查詢。');
      button.focus();
    });
    status.append(' ', restore);
  }
  if (!window.isSecureContext || !window.crypto?.getRandomValues || !window.fetch) {
    message('暫時無法在此瀏覽器提交申請，請', true);
    return;
  }
  message('正在確認申請服務。');
  fetch('/loan-applications/status', {credentials: 'same-origin', cache: 'no-store'})
    .then(response => {
      if (!response.ok) throw new Error('unavailable');
      return response.json();
    })
    .then(data => {
      if (data.enabled !== true) throw new Error('unavailable');
      ready = true;
      button.disabled = false;
      status.textContent = '';
    })
    .catch(() => message('網上申請暫時未能使用，請', true));

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!ready || sending || !form.reportValidity()) return;
    const payload = JSON.stringify(currentPayload());
    if (uncertain && submitted !== payload) {
      message('上次提交結果未能確認，請還原上次資料再重試，或聯絡環聯查詢。');
      restoreLink();
      return;
    }
    if (submitted !== payload || !key) key = freshKey();
    submitted = payload;
    const wasUncertain = uncertain;
    sending = true;
    button.disabled = true;
    button.textContent = '正在提交…';
    message('正在提交申請，請稍候。');
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch('/loan-applications/', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: {'Content-Type': 'application/json', 'Idempotency-Key': key},
        body: payload, signal: controller.signal
      });
      let data = null;
      try { data = await response.json(); } catch (_) { /* An unreadable response is not confirmation. */ }
      if (response.ok && data?.success === true && typeof data.reference === 'string' && data.reference) {
        reference.textContent = data.reference;
        form.reset();
        form.hidden = true;
        result.hidden = false;
        result.focus();
        return;
      }
      uncertain = wasUncertain || response.ok || response.status >= 500 || response.status === 408 || response.status === 409 || response.status === 429 || !data;
      if (!uncertain && response.status >= 400 && response.status < 500) {
        key = null;
        submitted = null;
        message(typeof data.error === 'string' ? data.error.slice(0, 200) : '資料未能提交，請檢查後再試。');
      } else {
        message('提交結果未能確認，請保留此頁並用原有資料再次提交，或', true);
      }
    } catch (_) {
      uncertain = true;
      message('提交結果未能確認，請保留此頁並用原有資料再次提交，或', true);
    } finally {
      window.clearTimeout(timeout);
      sending = false;
      button.textContent = uncertain ? '再次提交' : '提交申請 →';
      button.disabled = !ready;
    }
  });
})();
