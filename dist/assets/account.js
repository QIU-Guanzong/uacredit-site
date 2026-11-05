// Account form enhancements keep the server's native POST and validation rules.
// Contact drafts live only in this page's memory; no account data is stored here.
document.querySelectorAll('[data-password]').forEach(button => {
  const input = document.getElementById(button.dataset.password);
  if (!input) return;
  button.hidden = false;
  button.setAttribute('aria-label', '顯示密碼');
  button.addEventListener('click', () => {
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    button.textContent = show ? '隱藏' : '顯示';
    button.setAttribute('aria-label', show ? '隱藏密碼' : '顯示密碼');
    button.setAttribute('aria-pressed', String(show));
  });
});

const contactInput = document.querySelector('#contact-input');
const contactChoices = [...document.querySelectorAll('[name=kind][type=radio]')];
if (contactInput && contactChoices.length) {
  const label = document.querySelector('#contact-field-label');
  const hint = document.querySelector('#contact-hint');
  const selected = () => contactChoices.find(radio => radio.checked)?.value || 'phone';
  const drafts = { phone: '', email: '' };
  if (!contactChoices.some(radio => radio.checked)) contactChoices[0].checked = true;
  let previous = selected();
  drafts[previous] = contactInput.value;
  function renderContactKind(kind) {
    const phone = kind === 'phone';
    contactInput.type = phone ? 'tel' : 'email';
    contactInput.inputMode = phone ? 'tel' : 'email';
    contactInput.autocomplete = phone ? 'tel' : 'email';
    contactInput.placeholder = phone ? '例如 6123 4567' : '例如 name@example.com';
    contactInput.autocapitalize = 'none';
    contactInput.spellcheck = false;
    contactInput.setAttribute('autocorrect', 'off');
    if (label) label.textContent = phone ? '香港手機號碼' : '電郵地址';
    if (hint) hint.textContent = phone ? '請填寫可接收 WhatsApp 的8位香港手機號碼，亦可加上 +852。' : '請填寫你的完整電郵地址。';
    for (const radio of contactChoices) radio.closest('label')?.classList.toggle('is-selected', radio.checked);
  }
  for (const radio of contactChoices) radio.addEventListener('change', () => {
    const kind = selected();
    if (kind === previous) return;
    drafts[previous] = contactInput.value;
    contactInput.value = drafts[kind] || '';
    previous = kind;
    renderContactKind(kind);
  });
  renderContactKind(previous);
}

const announcement = document.createElement('p');
announcement.className = 'account-live';
announcement.setAttribute('role', 'status');
announcement.setAttribute('aria-live', 'polite');
announcement.setAttribute('aria-atomic', 'true');
document.body.append(announcement);
const resetPendingForms = [];

for (const [index, form] of [...document.querySelectorAll('.account form')].entries()) {
  if (form.method.toLowerCase() !== 'post') continue;
  const password = form.querySelector('input[name=password]');
  const confirmation = form.querySelector('input[name=confirm]');
  let checkConfirmation = () => true;
  if (password && confirmation) {
    let feedback = form.querySelector('[data-password-confirmation]');
    if (!feedback) {
      feedback = document.createElement('p');
      feedback.className = 'field-feedback';
      (confirmation.closest('label') || confirmation).after(feedback);
    }
    feedback.id ||= `account-confirmation-${index}`;
    feedback.setAttribute('role', 'status');
    feedback.setAttribute('aria-live', 'polite');
    feedback.setAttribute('aria-atomic', 'true');
    const descriptions = new Set((confirmation.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean));
    descriptions.add(feedback.id);
    confirmation.setAttribute('aria-describedby', [...descriptions].join(' '));
    let touched = false;
    checkConfirmation = (reveal = false) => {
      const hasBoth = Boolean(password.value && confirmation.value);
      const mismatch = hasBoth && password.value !== confirmation.value;
      confirmation.setCustomValidity(mismatch ? '兩次密碼不同，請再確認。' : '');
      if (reveal) touched = true;
      const state = !confirmation.value ? '' : !hasBoth ? 'hint' : !mismatch ? 'match' : touched ? 'error' : 'hint';
      const message = state === 'match' ? '兩次密碼一致。' : state === 'error' ? '兩次密碼不同，請再確認。' : state === 'hint' ? '請再次輸入相同密碼。' : '';
      if (feedback.textContent !== message) feedback.textContent = message;
      feedback.dataset.state = state;
      if (state === 'error') confirmation.setAttribute('aria-invalid', 'true');
      else confirmation.removeAttribute('aria-invalid');
      if (state === 'match') touched = true;
      return !mismatch;
    };
    confirmation.addEventListener('input', () => checkConfirmation());
    confirmation.addEventListener('blur', () => checkConfirmation(true));
    confirmation.addEventListener('invalid', () => checkConfirmation(true));
    password.addEventListener('input', () => checkConfirmation());
    checkConfirmation();
  }

  let pending = false;
  let restoreButtons = [];
  const originalBusy = form.getAttribute('aria-busy');
  function resetPending() {
    pending = false;
    if (originalBusy === null) form.removeAttribute('aria-busy');
    else form.setAttribute('aria-busy', originalBusy);
    for (const restore of restoreButtons) restore();
    restoreButtons = [];
    checkConfirmation();
  }
  resetPendingForms.push(resetPending);
  form.addEventListener('submit', event => {
    if (pending) { event.preventDefault(); return; }
    if (event.defaultPrevented) return;
    checkConfirmation(true);
    if (!form.checkValidity()) {
      event.preventDefault();
      form.reportValidity();
      return;
    }
    pending = true;
    form.setAttribute('aria-busy', 'true');
    const pendingLabel = form.dataset.pendingLabel || '正在送出…';
    for (const button of [...form.elements].filter(element => (element.tagName === 'BUTTON' || element.tagName === 'INPUT') && element.type === 'submit')) {
      const disabled = button.disabled;
      const content = [...button.childNodes];
      const value = button.value;
      button.disabled = true;
      button.setAttribute('data-account-pending', '');
      if (button.tagName === 'INPUT') button.value = pendingLabel;
      else button.replaceChildren(document.createTextNode(pendingLabel));
      restoreButtons.push(() => {
        button.disabled = disabled;
        button.removeAttribute('data-account-pending');
        if (button.tagName === 'INPUT') button.value = value;
        else button.replaceChildren(...content);
      });
    }
    announcement.textContent = `${pendingLabel.replace(/…$/, '')}，請稍候。`;
  });
}

// Browser back/forward cache can restore a page while its old request was pending.
// Restore the controls without changing fields, focus or the user's scroll position.
window.addEventListener('pageshow', event => {
  if (!event.persisted) return;
  for (const reset of resetPendingForms) reset();
  announcement.textContent = '';
});
