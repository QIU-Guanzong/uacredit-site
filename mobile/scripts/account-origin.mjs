const approvedHosts = new Set(['uacredit.hk', 'www.uacredit.hk', 'account.uacredit.hk', 'accounts.uacredit.hk']);

// The account service is optional. A configured endpoint is bundled into the
// app, so credentials, unapproved hosts and unfinished privacy setup must fail
// before any output is written.
export function validateAccountOrigin(config) {
  if (config.accountOrigin === null) return;
  if (typeof config.accountOrigin !== 'string') throw new Error('Account origin must be null or an approved HTTPS origin.');
  let origin;
  try { origin = new URL(config.accountOrigin); } catch { throw new Error('Account origin is invalid.'); }
  if (origin.protocol !== 'https:' || origin.username || origin.password || origin.port ||
      origin.pathname !== '/' || origin.search || origin.hash || !approvedHosts.has(origin.hostname)) {
    throw new Error('Account origin must be an approved plain company HTTPS origin.');
  }
  if (config.publisherConfirmed !== true || config.privacyAndDeletionUrlsConfirmed !== true) {
    throw new Error('Account origin requires confirmed publisher and privacy/deletion URLs.');
  }
}
