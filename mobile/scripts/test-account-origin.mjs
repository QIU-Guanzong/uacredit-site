import test from 'node:test';
import assert from 'node:assert/strict';
import { validateAccountOrigin } from './account-origin.mjs';

const approved = { accountOrigin: 'https://account.uacredit.hk', publisherConfirmed: true, privacyAndDeletionUrlsConfirmed: true };
test('guest mode and an approved configured origin are accepted', () => {
  assert.doesNotThrow(() => validateAccountOrigin({ accountOrigin: null }));
  assert.doesNotThrow(() => validateAccountOrigin(approved));
});
test('account origin cannot carry credentials or an unapproved destination', () => {
  for (const accountOrigin of ['http://account.uacredit.hk', 'https://user:secret@account.uacredit.hk',
    'https://account.uacredit.hk.evil.example', 'https://account.uacredit.hk/path',
    'https://account.uacredit.hk/?token=fixture', 'https://account.uacredit.hk/#x',
    'https://account.uacredit.hk:8443', 'https://127.0.0.1', '', undefined]) {
    assert.throws(() => validateAccountOrigin({ ...approved, accountOrigin }));
  }
});
test('publisher and privacy confirmations are required before enabling accounts', () => {
  assert.throws(() => validateAccountOrigin({ ...approved, publisherConfirmed: false }));
  assert.throws(() => validateAccountOrigin({ ...approved, privacyAndDeletionUrlsConfirmed: false }));
});
