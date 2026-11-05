"""Offline backup tests. All keys and records below are disposable test data."""
import os
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

from scripts import loan_backup


@unittest.skipUnless(shutil.which('gpg'), 'GPG is required for the backup round-trip test')
class LoanBackupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Keep the GPG agent socket path short enough on macOS.
        cls.temp = tempfile.TemporaryDirectory(prefix='ua-test-', dir='/tmp')
        cls.root = Path(cls.temp.name)
        cls.home = cls.root / 'gnupg'
        cls.home.mkdir(mode=0o700)
        # Also runs if key generation or setup fails. This home contains only
        # the temporary test key and is never a user's configured keyring.
        cls.addClassCleanup(cls.cleanup_test_gpg)
        subprocess.run(['gpg', '--no-options', '--homedir', str(cls.home), '--batch', '--no-tty',
                        '--pinentry-mode', 'loopback', '--passphrase', '', '--quick-generate-key',
                        'Disposable UACredit Backup Test <test@example.invalid>', 'rsa2048', 'default', '0'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        listing = subprocess.check_output(['gpg', '--no-options', '--homedir', str(cls.home), '--batch',
                                           '--with-colons', '--fingerprint', '--list-keys'], stderr=subprocess.DEVNULL, text=True)
        cls.fingerprint = next(line.split(':')[9] for line in listing.splitlines() if line.startswith('fpr:'))
        subprocess.run(['gpg', '--no-options', '--homedir', str(cls.home), '--batch', '--no-tty',
                        '--pinentry-mode', 'loopback', '--passphrase', '', '--quick-add-key',
                        cls.fingerprint, 'rsa2048', 'encrypt', '0'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @classmethod
    def cleanup_test_gpg(cls):
        subprocess.run(['gpgconf', '--homedir', str(cls.home), '--kill', 'all'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        cls.temp.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='case-', dir=self.root)
        self.case = Path(self.tmp.name)
        self.db_path = self.case / 'loan.sqlite3'
        self.conn = sqlite3.connect(self.db_path)
        # The only customer-like strings are unmistakable synthetic markers.
        cols = ', '.join('"' + col + '" TEXT' for col in sorted(loan_backup.REQUIRED['loan_applications']))
        audit = ', '.join('"' + col + '" TEXT' for col in sorted(loan_backup.REQUIRED['loan_application_audit']))
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('CREATE TABLE loan_applications (' + cols + ')')
        self.conn.execute('CREATE TABLE loan_application_audit (' + audit + ')')
        self.conn.execute('INSERT INTO loan_applications (name,reference) VALUES (?,?)', ('SYNTHETIC-TEST-ONLY', 'UA-TEST'))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_consistent_encrypted_backup_and_verified_restore(self):
        archive = self.case/'backup.gpg'
        checksum = loan_backup.create_backup(self.db_path, archive, self.fingerprint, self.home)
        self.assertEqual(checksum, loan_backup.digest(archive))
        self.assertNotIn(b'SYNTHETIC-TEST-ONLY', archive.read_bytes())
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        self.assertEqual(loan_backup.restore_backup(archive, checksum, self.home), checksum)
        restored = self.case/'restored.sqlite3'
        loan_backup.restore_backup(archive, checksum, self.home, restored)
        self.assertEqual(restored.stat().st_mode & 0o777, 0o600)
        with closing(sqlite3.connect(restored)) as db:
            self.assertEqual(db.execute('SELECT name FROM loan_applications').fetchone()[0], 'SYNTHETIC-TEST-ONLY')
        self.assertFalse(list(self.case.glob('.uacredit-*')))

    def test_never_overwrites_and_rejects_wrong_hash_and_key(self):
        archive = self.case/'backup.gpg'
        checksum = loan_backup.create_backup(self.db_path, archive, self.fingerprint, self.home)
        before = archive.read_bytes()
        with self.assertRaises(loan_backup.BackupError):
            loan_backup.create_backup(self.db_path, archive, self.fingerprint, self.home)
        self.assertEqual(archive.read_bytes(), before)
        target = self.case/'target.sqlite3'
        with self.assertRaises(loan_backup.BackupError):
            loan_backup.restore_backup(archive, '0'*64, self.home, target)
        self.assertFalse(target.exists())
        empty_home = self.case/'empty-keyring'; empty_home.mkdir(mode=0o700)
        with self.assertRaises(loan_backup.BackupError):
            loan_backup.restore_backup(archive, checksum, empty_home, target)
        self.assertFalse(target.exists())
        target.write_bytes(b'untouched')
        with self.assertRaises(loan_backup.BackupError):
            loan_backup.restore_backup(archive, checksum, self.home, target)
        self.assertEqual(target.read_bytes(), b'untouched')
        self.assertFalse(list(self.case.glob('.uacredit-*')))

    def test_bad_source_and_invalid_public_key_leave_no_archive(self):
        target = self.case/'not-created.gpg'
        with self.assertRaises(loan_backup.BackupError):
            loan_backup.create_backup(self.db_path, target, 'bad', self.home)
        self.assertFalse(target.exists())
        bad = self.case/'wrong.sqlite3'
        with closing(sqlite3.connect(bad)) as db:
            db.execute('CREATE TABLE wrong (id TEXT)')
            db.commit()
        with self.assertRaises(loan_backup.BackupError):
            loan_backup.create_backup(bad, target, self.fingerprint, self.home)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.case.glob('.uacredit-*')))


if __name__ == '__main__':
    unittest.main()
