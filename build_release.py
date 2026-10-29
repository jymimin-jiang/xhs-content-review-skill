"""Build a fixed-name latest ZIP and immutable version ZIP; standard library."""
import argparse, hashlib, json, re, zipfile
from datetime import date
from pathlib import Path

base=Path(__file__).resolve().parent
root=base/'xhs-content-review'
p=argparse.ArgumentParser();p.add_argument('--version',required=True);args=p.parse_args()
if not re.fullmatch(r'\d+\.\d+\.\d+',args.version):p.error('版本格式必须为 major.minor.patch')
files={}
for f in sorted(root.rglob('*')):
 if f.is_symlink():raise ValueError('发布内容不能是符号链接')
 if not f.is_file() or '__pycache__' in f.relative_to(root).parts:continue
 key=f.relative_to(root).as_posix()
 if key in ('release.json','installation.json'):continue
 files[key]=f.read_bytes()
meta={'name':'xhs-content-review','version':args.version,'data_schema':1,'released_on':date.today().isoformat(),'files':{k:hashlib.sha256(v).hexdigest() for k,v in files.items()}}
files['release.json']=(json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode()
archive=base/('xhs-content-review-v'+args.version+'.zip')
# Build reproducibly so repeated same-version builds can be compared byte-for-byte.
import io
buf=io.BytesIO()
with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED) as z:
 for name,body in sorted(files.items()):
  item=zipfile.ZipInfo('xhs-content-review/'+name,(2026,1,1,0,0,0));item.compress_type=zipfile.ZIP_DEFLATED;item.external_attr=0o100644<<16
  z.writestr(item,body)
content=buf.getvalue()
if archive.exists() and archive.read_bytes()!=content:raise ValueError('历史版本已存在且内容不同；必须增加版本号')
archive.write_bytes(content)
(root/'release.json').write_bytes(files['release.json'])
latest=base/'xhs-content-review.zip';latest.write_bytes(content)
for f in (archive,latest):
 f.with_name(f.name+'.sha256').write_text(hashlib.sha256(content).hexdigest()+'  '+f.name+'\n')
(base/'文件校验清单.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'version':args.version,'files':len(files),'archive':str(archive),'latest':str(latest)},ensure_ascii=False))
