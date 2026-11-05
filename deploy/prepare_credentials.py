"""Generate a local initial credential. Never print its value."""
from pathlib import Path
import json,os,secrets
from werkzeug.security import generate_password_hash
root=Path(__file__).resolve().parent.parent
private=root/'work/private';private.mkdir(parents=True,exist_ok=True);private.chmod(0o700)
saved=Path.home()/'.local/share/uacredit';saved.mkdir(parents=True,exist_ok=True);saved.chmod(0o700)
credential=saved/'initial-admin.json'
if credential.exists():raise SystemExit('A local credential already exists; inspect its deployment before generating a replacement.')
password=secrets.token_urlsafe(30)
def write_private(path,data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f,ensure_ascii=False,indent=2)
write_private(credential,{'username':'uacredit-admin','password':password,'admin_url':'http://127.0.0.1:8744/admin/'})
write_private(private/'uacredit-bootstrap-config.json',{'username':'uacredit-admin','password_hash':generate_password_hash(password),'secret_key':secrets.token_hex(48),'secure_cookie':True})
print('Initial credential saved in the protected local application-data directory; bootstrap configuration prepared without plaintext password.')
