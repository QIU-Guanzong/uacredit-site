#!/bin/sh
set -eu
release="$1"
archive="$2"
bootstrap="$3"
base="${4:-}"
case "$archive" in /tmp/uacredit-*.tar.gz) ;; *) echo 'Archive must be a task-owned /tmp/uacredit archive.'; exit 2;; esac
[ "$(dirname "$archive")" = /tmp ] || exit 2
case "$bootstrap" in /tmp/uacredit-*.json|'') ;; *) echo 'Bootstrap must be empty or a task-owned /tmp/uacredit JSON file.'; exit 2;; esac
if [ -n "$bootstrap" ]; then [ "$(dirname "$bootstrap")" = /tmp ] || exit 2; fi
if [ ! -f /etc/uacredit/config.json ] && [ -z "$bootstrap" ]; then echo 'Initial bootstrap configuration is required.'; exit 2; fi
case "$release" in *[!a-zA-Z0-9-]*|'') exit 2;; esac
if ! id uacredit >/dev/null 2>&1; then useradd --system --home-dir /var/lib/uacredit --shell /usr/sbin/nologin uacredit; fi
install -d -o root -g uacredit -m 750 /opt/uacredit /opt/uacredit/releases /etc/uacredit
install -d -o uacredit -g uacredit -m 700 /var/lib/uacredit
target="/opt/uacredit/releases/$release"
previous="$(readlink -f /opt/uacredit/current 2>/dev/null || true)"
if [ -e "$target" ]; then echo 'Release already exists; refusing to overwrite.'; exit 3; fi
install -d -o root -g uacredit -m 750 "$target"
if [ -n "$base" ]; then
    current="$(readlink -f /opt/uacredit/current)"
    if [ "$(basename "$current")" != "$base" ]; then echo 'Current release does not match the delta base.'; exit 4; fi
    cp -al "$current/." "$target/"
fi
tar --unlink-first -xzf "$archive" -C "$target"
chown -R root:uacredit "$target"
chmod -R g+rX,o-rwx "$target"
if [ ! -x /opt/uacredit/venv/bin/python ]; then python3 -m venv /opt/uacredit/venv; fi
/opt/uacredit/venv/bin/pip install --disable-pip-version-check -q -r "$target/requirements.lock"
chown -R root:uacredit /opt/uacredit/venv
chmod -R g+rX,o-rwx /opt/uacredit/venv
if [ ! -f /etc/uacredit/config.json ]; then install -o root -g uacredit -m 640 "$bootstrap" /etc/uacredit/config.json; fi
ln -s "$target" /opt/uacredit/current.new
mv -Tf /opt/uacredit/current.new /opt/uacredit/current
install -o root -g root -m 644 "$target/deploy/uacredit.service" /etc/systemd/system/uacredit.service
systemctl daemon-reload
systemctl enable --now uacredit.service
systemctl restart uacredit.service
ready=0
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    if curl -fsS http://127.0.0.1:8744/healthz >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
done
if [ "$ready" != 1 ]; then
    if [ -n "$previous" ]; then
        ln -s "$previous" /opt/uacredit/current.rollback
        mv -Tf /opt/uacredit/current.rollback /opt/uacredit/current
        systemctl restart uacredit.service
    fi
    echo 'New service failed readiness; previous code restored when available.'
    exit 5
fi
rm -f "$archive"
if [ -n "$bootstrap" ]; then rm -f "$bootstrap"; fi
echo 'Installed and verified isolated UACredit service; public nginx and domain DNS unchanged.'
