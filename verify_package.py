"""Portable standard-library checks; not a substitute for host/model evaluation."""
import sys, re, json, copy, importlib.util, base64, tempfile
from pathlib import Path
sys.dont_write_bytecode=True
root=Path(__file__).resolve().parent/'xhs-content-review'
spec=importlib.util.spec_from_file_location('renderer',root/'scripts/render_report.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
text=(root/'SKILL.md').read_text(encoding='utf-8')
head=re.match(r'^---\n(.*?)\n---',text,re.S);assert head
# Only this package's two single-line fields are checked; this is not a YAML parser.
fields=dict(line.split(': ',1) for line in head[1].splitlines())
assert set(fields)=={'name','description'} and fields['name']==root.name
assert re.fullmatch('[a-z0-9]+(?:-[a-z0-9]+)*',fields['name']) and len(fields['name'])<=64
assert 0<len(fields['description'])<=1024 and '[TODO:' not in text
for f in root.rglob('*.md'):
 for link in re.findall(r'\]\(([^)]+)\)',f.read_text(encoding='utf-8')):
  if not link.startswith(('http:','https:','#')):assert (f.parent/link).exists(),(f,link)
index=json.loads((root/'references/source-index.json').read_text(encoding='utf-8'));assert len(index)==139
assert len(list((root/'references/rules').glob('*.md')))==21
assert len((root/'references/改写候选.jsonl').read_text(encoding='utf-8').splitlines())==6
for sid in index:assert any(sid in f.read_text(encoding='utf-8') for f in (root/'references/rules').glob('*.md')),sid
fixture=json.loads((root/'examples/review.json').read_text(encoding='utf-8'))
h=r.render(fixture,root/'examples');assert 'href="#R01"' in h and 'href="#R02"' in h and '免责声明' in h
assert '笔记文本' in h and '图片 OCR 与画面证据' in h
x=copy.deepcopy(fixture);x['issues']=[];x['materials'][0]['text']='<img src=x onerror="alert(1)">';h=r.render(x,root)
assert '<img src=x' not in h and '&lt;img src=x' in h and '未发现有依据的风险' in h
cases=['bad-source','bad-quote','unread','duplicate','id-collision','ad-scope','conditional-must']
for name in cases:
 x=copy.deepcopy(fixture)
 if name=='bad-source':x['issues'][0]['sources'][0]['id']='NOT-REAL'
 if name=='bad-quote':x['issues'][0]['evidence'][0]['quote']='原文不存在'
 if name=='unread':x['materials'][1]['status']='unread'
 if name=='duplicate':x['issues'][1]['id']='R01'
 if name=='id-collision':x['issues'][0]['id']='title'
 if name=='ad-scope':x.pop('ad_scope')
 if name=='conditional-must':
  x['ad_scope']='conditional';x['issues'][1]['level']='必须禁用';x['pending'].append('广告场景待确认')
 try:r.render(x,root)
 except AssertionError:pass
 else:raise AssertionError('Should reject '+name)
x=copy.deepcopy(fixture);x['materials'][2]['image_path']='missing.png';assert '原图路径不可访问' in r.render(x,root)
with tempfile.TemporaryDirectory() as tmp:
 img=Path(tmp)/'one.png';img.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l1sAAAAASUVORK5CYII='))
 x=copy.deepcopy(fixture);x['materials'][2]['image_path']=str(img);assert 'data:image/png;base64,' in r.render(x,root)
# Quotes overlapping in a single region remain linked to both issues.
x=copy.deepcopy(fixture);x['issues'][1]['evidence']=[{'material_id':'body1','quote':'下注赚钱','location':'正文第1段'}]
h=r.render(x,root);assert 'href="#R01"' in h and 'href="#R02"' in h
# Validate zero-risk context fixture, without asserting an independent model produced it.
c=json.loads((root/'examples/context-check.json').read_text(encoding='utf-8'));h=r.render(c,root)
assert '未提交图片' in h and '不建议' in h and '未发现有依据的风险' in h
print('PASS: package structure, 139 source references, 21 topics, 6 rewrite candidates; report rendering, escaping, links, missing/embedded images, overlap, zero risks; 7 invalid input cases rejected.')

# Presentation contracts: metadata remains in JSON but not in rendered report.
h=r.render(fixture,root)
assert "20261029服装推广图文敏感词审查报告" in h
assert "XHS-COMM" not in h and "XHS-AD-" not in h
assert "用户复制正文" not in h and "规则快照" not in h
assert ".disclaimer p{font-size:12px" in h
print("PASS: report naming, simplified source display, hidden snapshot metadata, 12px disclaimer")

lex=(root/"references/敏感词库.md").read_text(encoding="utf-8")
assert "核验状态" not in lex and "待核验官方依据" not in lex
assert len(set(re.findall(r"XHS-MAT-\d+",lex)))==965
assert "作者二次加工数据" in lex and "未经授权请勿搬运" in lex
print("PASS: lexicon source labels, removed verification column, 965 IDs preserved")
