"""Installer rejection tests stop before any installation or service operation."""
from pathlib import Path
import os,stat,subprocess,unittest
ROOT=Path(__file__).parent
class DeploymentInputTest(unittest.TestCase):
    def test_system_device_is_rejected_as_bootstrap_before_mutation(self):
        before=os.stat('/dev/null')
        r=subprocess.run(['sh',str(ROOT/'deploy/install.sh'),'test-rejected','/tmp/uacredit-test-rejected.tar.gz','/dev/null'],capture_output=True,text=True)
        self.assertEqual(r.returncode,2)
        after=os.stat('/dev/null');self.assertTrue(stat.S_ISCHR(after.st_mode));self.assertEqual(before.st_rdev,after.st_rdev)
        self.assertIn('Bootstrap must be empty',r.stdout)
    def test_unowned_archive_and_parent_traversal_rejected(self):
        for archive in ['/dev/null','/tmp/someone-elses.tar.gz','/tmp/uacredit-x/../../dev/null.tar.gz']:
            r=subprocess.run(['sh',str(ROOT/'deploy/install.sh'),'test-rejected',archive,''],capture_output=True,text=True)
            self.assertEqual(r.returncode,2)
if __name__=='__main__':unittest.main()
