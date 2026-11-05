"""Verify actual candidate packages contain the frozen public bundle; no credentials required."""
import hashlib,json,plistlib,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
CONFIG=json.loads((ROOT/'mobile/app-config.json').read_text())
VERSION=CONFIG['version'];BUILD=CONFIG['build'];DELIVERY=ROOT/f'artifacts/mobile/{VERSION}-{BUILD}'
PUBLIC=ROOT/'mobile/www'
def digest(data):return hashlib.sha256(data).hexdigest()
expected={str(p.relative_to(PUBLIC)):digest(p.read_bytes()) for p in PUBLIC.rglob('*') if p.is_file()}
archive=DELIVERY/f'UACredit-{VERSION}-{BUILD}-unsigned.xcarchive'
app=archive/'Products/Applications/App.app'
info=plistlib.loads((app/'Info.plist').read_bytes())
assert info['CFBundleIdentifier']=='hk.uacredit.app'
assert info['CFBundleShortVersionString']==VERSION and info['CFBundleVersion']==str(BUILD)
assert not (app/'embedded.mobileprovision').exists() and not (app/'_CodeSignature').exists(),'Expected unsigned application'
actual={str(p.relative_to(app/'public')):digest(p.read_bytes()) for p in (app/'public').rglob('*') if p.is_file()}
assert set(actual)-set(expected)<= {'cordova.js','cordova_plugins.js'},'Unexpected iOS asset'
assert all(actual.get(k)==v for k,v in expected.items()),'iOS bundled public assets are stale'
assert all((app/'public'/n).read_bytes()==b'' for n in set(actual)-set(expected)),'Unexpected Cordova placeholder contents'
archive_files={str(p.relative_to(archive)):digest(p.read_bytes()) for p in archive.rglob('*') if p.is_file()}
archive_manifest=json.dumps(archive_files,sort_keys=True,separators=(',',':')).encode()
report={'version':VERSION,'build':BUILD,'app_id':'hk.uacredit.app','account_origin':CONFIG['accountOrigin'],'public_files_verified':len(expected),'ios':{'archive':str(archive.relative_to(ROOT)),'app_signing':'unsigned','sdk':info.get('DTSDKName'),'minimum_os':info.get('MinimumOSVersion'),'bytes':sum(p.stat().st_size for p in archive.rglob('*') if p.is_file()),'file_tree_sha256':digest(archive_manifest),'public_assets_match':True},'android':[],'store_upload':'not_performed_developer_accounts_not_opened','physical_device_acceptance':'pending'}
for kind,prefix,name in [('local_debug_apk','assets/public/',f'uacredit-{VERSION}-{BUILD}-local-test-debug.apk'),('unsigned_release_aab','base/assets/public/',f'uacredit-{VERSION}-{BUILD}-release-unsigned.aab')]:
 p=DELIVERY/'android'/name
 with zipfile.ZipFile(p) as z:
  actual={n[len(prefix):]:digest(z.read(n)) for n in z.namelist() if n.startswith(prefix) and not n.endswith('/')}
  assert set(actual)-set(expected)<= {'cordova.js','cordova_plugins.js'}, f'{name}: unexpected asset'
  assert all(actual.get(k)==v for k,v in expected.items()), f'{name}: public bundle mismatch'
  assert all(z.read(prefix+n)==b'' for n in set(actual)-set(expected)), f'{name}: unexpected Cordova placeholder contents'
  assert not any(n.endswith('.so') for n in z.namelist()),'Native libraries need separate16KB review'
 report['android'].append({'kind':kind,'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':digest(p.read_bytes()),'public_assets_match':True})
(DELIVERY/'ios-file-manifest.json').write_bytes(archive_manifest+b'\n')
(DELIVERY/'build-verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
