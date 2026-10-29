import unittest, tempfile, json, zipfile, hashlib, importlib.util
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent/'xhs-content-review'
spec=importlib.util.spec_from_file_location('mgr',ROOT/'scripts/manage_release.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def bundle(base,version,text='old',bad=False):
 files={'SKILL.md':b'---\nname: xhs-content-review\n---\n','content.txt':text.encode()}
 meta={'name':'xhs-content-review','version':version,'data_schema':1,'files':{k:hashlib.sha256(v).hexdigest() for k,v in files.items()}}
 p=base/(version+'.zip')
 with zipfile.ZipFile(p,'w') as z:
  for k,v in files.items():z.writestr('xhs-content-review/'+k,v)
  z.writestr('xhs-content-review/release.json',json.dumps(meta))
  if bad:z.writestr('xhs-content-review/../../escape','bad')
 return p
class ReleaseTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.b=Path(self.tmp.name).resolve();self.target=self.b/'skills/xhs-content-review';self.data=self.b/'data'
 def tearDown(self):self.tmp.cleanup()
 def test_install_update_rollback_keeps_data(self):
  m.install(bundle(self.b,'0.5.0'),self.target,self.data)
  (self.data/'用户敏感词.md').write_text('我的词库')
  (self.data/'reports/old.html').write_text('report')
  result=m.install(bundle(self.b,'0.6.0','new'),self.target,self.data)
  self.assertEqual((self.target/'content.txt').read_text(),'new')
  (self.data/'用户自定义规则.md').write_text('更新后新增')
  m.rollback(self.target,self.data,result['backup_id'])
  self.assertEqual((self.target/'content.txt').read_text(),'old')
  self.assertEqual((self.data/'用户敏感词.md').read_text(),'我的词库')
  self.assertEqual((self.data/'用户自定义规则.md').read_text(),'更新后新增')
  self.assertTrue((self.data/'reports/old.html').exists())
 def test_unsafe_archive_rejected(self):
  with self.assertRaises(ValueError):m.install(bundle(self.b,'0.5.0',bad=True),self.target,self.data)
  self.assertFalse(self.target.exists())
 def test_changed_core_aborts_with_backup(self):
  m.install(bundle(self.b,'0.5.0'),self.target,self.data);(self.target/'content.txt').write_text('local')
  with self.assertRaises(ValueError):m.install(bundle(self.b,'0.6.0'),self.target,self.data)
  self.assertEqual((self.target/'content.txt').read_text(),'local')
  self.assertTrue(list((self.data/'backups').glob('*/backup.json')))
 def test_failed_swap_restores_old(self):
  m.install(bundle(self.b,'0.5.0'),self.target,self.data)
  real=m.os.replace
  def failure(src,dst):
   if Path(src).name=='incoming' and Path(dst)==self.target:raise OSError('simulated failure')
   return real(src,dst)
  with patch.object(m.os,'replace',side_effect=failure):
   with self.assertRaises(OSError):m.install(bundle(self.b,'0.6.0'),self.target,self.data)
  self.assertEqual((self.target/'content.txt').read_text(),'old')
 def test_lock(self):
  m.install(bundle(self.b,'0.5.0'),self.target,self.data);(self.data/'.update.lock').write_text('other process')
  with self.assertRaises(ValueError):m.install(bundle(self.b,'0.6.0'),self.target,self.data)
 def test_corrupted_backup_refused(self):
  m.install(bundle(self.b,'0.5.0'),self.target,self.data)
  result=m.install(bundle(self.b,'0.6.0','new'),self.target,self.data)
  (self.data/'backups'/result['backup_id']/'skill/content.txt').write_text('tampered')
  with self.assertRaises(ValueError):m.rollback(self.target,self.data,result['backup_id'])
  self.assertEqual((self.target/'content.txt').read_text(),'new')
 def test_legacy_requires_opt_in_and_archives(self):
  self.target.mkdir(parents=True);(self.target/'SKILL.md').write_text('---\nname: xhs-content-review\n---\n')
  (self.target/'my-rules.md').write_text('old preferences')
  with self.assertRaises(ValueError):m.install(bundle(self.b,'0.5.0'),self.target,self.data)
  result=m.install(bundle(self.b,'0.5.0'),self.target,self.data,True)
  self.assertTrue(result['legacy_migration_pending'])
  self.assertEqual((self.data/'backups'/result['backup_id']/'skill/my-rules.md').read_text(),'old preferences')
 def test_bad_hash(self):
  package=bundle(self.b,'0.5.0');replacement=self.b/'tampered.zip'
  with zipfile.ZipFile(package) as old, zipfile.ZipFile(replacement,'w') as new:
   for i in old.infolist():new.writestr(i, b'tampered' if i.filename.endswith('/content.txt') else old.read(i))
  with self.assertRaises(ValueError):m.install(replacement,self.target,self.data)
  self.assertFalse(self.target.exists())
 def test_downgrade_and_wrong_data_path(self):
  m.install(bundle(self.b,'0.6.0'),self.target,self.data)
  with self.assertRaises(ValueError):m.install(bundle(self.b,'0.5.0'),self.target,self.data)
  with self.assertRaises(ValueError):m.install(bundle(self.b,'0.7.0'),self.target,self.b/'different')
  self.assertEqual(m.read(self.target/'release.json')['version'],'0.6.0')
 def test_user_data_snapshot(self):
  m.install(bundle(self.b,'0.5.0'),self.target,self.data)
  (self.data/'reports/test.html').write_text('historic report')
  result=m.install(bundle(self.b,'0.6.0'),self.target,self.data)
  self.assertEqual((self.data/'backups'/result['backup_id']/'user-data/reports/test.html').read_text(),'historic report')
 def test_schema_and_overlap(self):
  self.data.mkdir();m.write(self.data/'config.json',{'data_schema':2})
  with self.assertRaises(ValueError):m.install(bundle(self.b,'0.5.0'),self.target,self.data)
  with self.assertRaises(ValueError):m.install(bundle(self.b,'0.5.0'),self.target,self.target/'data')
if __name__=='__main__':unittest.main()
