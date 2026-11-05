#!/usr/bin/env python3
"""Create an encrypted, consistent loan database backup or verify/restore one.

Keys and destinations must already exist and be selected by the operator. The
database snapshot and restored database are temporary, local-only files; only
the GPG ciphertext is suitable for copying to a different machine.
"""
import argparse
from contextlib import closing
import hashlib
import hmac
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile


class BackupError(Exception):
    pass


REQUIRED = {
    'loan_applications': {'reference', 'created_at', 'updated_at', 'service', 'name',
                          'phone', 'amount', 'details', 'consent_version', 'status',
                          'revision', 'idempotency_digest', 'payload_digest'},
    'loan_application_audit': {'id', 'at', 'reference', 'actor', 'action',
                               'old_status', 'new_status'},
}


def digest(path):
    result = hashlib.sha256()
    with open(path, 'rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            result.update(part)
    return result.hexdigest()


def database(path):
    # mode=ro must not create an empty database, and must include live WAL data.
    return sqlite3.connect(Path(path).resolve(strict=True).as_uri() + '?mode=ro', uri=True, timeout=15)


def check_database(path):
    try:
        with closing(database(path)) as conn:
            rows = conn.execute('PRAGMA integrity_check').fetchall()
            if len(rows) != 1 or rows[0][0] != 'ok':
                raise BackupError('資料庫完整性檢查未通過。')
            for table, columns in REQUIRED.items():
                # Both table names are hard-coded above, never operator input.
                actual = {row[1] for row in conn.execute('PRAGMA table_info(' + table + ')')}
                if not columns.issubset(actual):
                    raise BackupError('備份不符合貸款申請資料庫格式。')
    except sqlite3.Error as exc:
        raise BackupError('資料庫讀取或完整性檢查失敗。') from exc


def private_directory(path):
    p = Path(path).expanduser().resolve(strict=True)
    if not p.is_dir() or p.stat().st_mode & 0o077:
        raise BackupError('GPG 密鑰目錄必須存在，並且只可由擁有人存取。')
    return p


def check_destination(path):
    p = Path(path).expanduser().absolute()
    if not p.parent.is_dir() or os.path.lexists(p):
        raise BackupError('目標目錄必須存在，目標檔案不可已存在。')
    return p


def run_gpg(gpg_home, args, infile, outfile):
    command = ['gpg', '--no-options', '--homedir', str(gpg_home), '--batch', '--no-tty',
               '--pinentry-mode', 'error', *args]
    try:
        result = subprocess.run(command, stdin=infile, stdout=outfile, stderr=subprocess.DEVNULL, check=False)
    except OSError as exc:
        raise BackupError('無法啟動 GPG。') from exc
    if result.returncode:
        raise BackupError('加密或解密失敗；請檢查所選密鑰及其解鎖狀態。')


def install_noreplace(source, target):
    # Both files are on the same filesystem; link refuses to replace any target,
    # including a symlink planted between the existence check and installation.
    try:
        os.link(source, target)
        fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise BackupError('無法安全建立目標檔案；現有檔案不會被覆蓋。') from exc


def create_backup(source, output, recipient, home, temp_root=None):
    if not re.fullmatch(r'[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64}', recipient):
        raise BackupError('請提供完整的收件者公鑰指紋。')
    home = private_directory(home)
    output = check_destination(output)
    with tempfile.TemporaryDirectory(prefix='uacredit-loan-', dir=temp_root) as scratch:
        os.chmod(scratch, 0o700)
        snapshot = Path(scratch) / 'snapshot.sqlite3'
        fd = os.open(snapshot, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            with closing(database(source)) as src, closing(sqlite3.connect(snapshot)) as dst:
                src.backup(dst)
                dst.commit()
        except (sqlite3.Error, OSError) as exc:
            raise BackupError('無法建立一致性資料庫快照。') from exc
        check_database(snapshot)
        fd, staging_name = tempfile.mkstemp(prefix='.uacredit-encrypted-', dir=output.parent)
        staging = Path(staging_name)
        try:
            with os.fdopen(fd, 'wb') as ciphertext, open(snapshot, 'rb') as plaintext:
                run_gpg(home, ['--trust-model', 'always', '--recipient', recipient, '--encrypt'], plaintext, ciphertext)
                ciphertext.flush()
                os.fsync(ciphertext.fileno())
            if not staging.stat().st_size:
                raise BackupError('加密輸出為空。')
            checksum = digest(staging)
            install_noreplace(staging, output)
        finally:
            staging.unlink(missing_ok=True)
    return checksum


def restore_backup(archive, expected, home, output=None, temp_root=None):
    if not re.fullmatch(r'[A-Fa-f0-9]{64}', expected):
        raise BackupError('請提供由可信位置取得的完整 SHA-256。')
    home = private_directory(home)
    archive = Path(archive).expanduser().resolve(strict=True)
    output = check_destination(output) if output is not None else None
    if not archive.is_file():
        raise BackupError('備份檔案不可用。')
    # For restore, stage in the target directory so installation is atomic and
    # cannot overwrite an existing database. Verification-only uses temp_root.
    scratch_parent = output.parent if output else temp_root
    with tempfile.TemporaryDirectory(prefix='.uacredit-restore-', dir=scratch_parent) as scratch:
        os.chmod(scratch, 0o700)
        copied = Path(scratch) / 'archive.gpg'
        cipher_hash = hashlib.sha256()
        fd = os.open(copied, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as safe_copy, open(archive, 'rb') as source:
            for part in iter(lambda: source.read(1024 * 1024), b''):
                cipher_hash.update(part)
                safe_copy.write(part)
        if not hmac.compare_digest(cipher_hash.hexdigest(), expected.lower()):
            raise BackupError('備份檔案雜湊不符。')
        restored = Path(scratch) / 'restore.sqlite3'
        fd = os.open(restored, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as plaintext, open(copied, 'rb') as ciphertext:
            run_gpg(home, ['--decrypt'], ciphertext, plaintext)
            plaintext.flush()
            os.fsync(plaintext.fileno())
        check_database(restored)
        if output:
            install_noreplace(restored, output)
    return expected.lower()


def main(argv=None):
    parser = argparse.ArgumentParser(description='加密備份及驗證貸款申請資料庫；不會建立密鑰或覆蓋現有檔案。')
    actions = parser.add_subparsers(dest='action', required=True)
    backup = actions.add_parser('backup')
    backup.add_argument('--source', required=True)
    backup.add_argument('--output', required=True)
    backup.add_argument('--recipient-fingerprint', required=True)
    backup.add_argument('--gpg-home', required=True)
    backup.add_argument('--temp-root')
    for action in ('verify', 'restore'):
        sub = actions.add_parser(action)
        sub.add_argument('--archive', required=True)
        sub.add_argument('--expected-sha256', required=True)
        sub.add_argument('--gpg-home', required=True)
        sub.add_argument('--temp-root')
        if action == 'restore':
            sub.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'backup':
            checksum = create_backup(args.source, args.output, args.recipient_fingerprint, args.gpg_home, args.temp_root)
            print('加密備份已建立。SHA-256:', checksum)
        else:
            checksum = restore_backup(args.archive, args.expected_sha256, args.gpg_home,
                                      getattr(args, 'output', None), args.temp_root)
            print(('恢復資料庫已建立。' if args.action == 'restore' else '備份解密及資料庫完整性驗證通過。') + ' SHA-256: ' + checksum)
    except (BackupError, OSError, sqlite3.Error) as exc:
        # Error text deliberately excludes GPG diagnostics, database rows and paths.
        print(str(exc) if isinstance(exc, BackupError) else '備份操作失敗，請檢查檔案與權限。', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
