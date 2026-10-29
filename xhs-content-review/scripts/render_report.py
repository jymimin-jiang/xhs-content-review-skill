"""Render an already reviewed JSON record; no network, OCR or compliance classification."""
import argparse, base64, html, json, re
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def esc(x):
    return html.escape(str(x), quote=True)
def validate(d):
    mids = {m['id']: m for m in d['materials']}
    assert len(mids) == len(d['materials']), 'Duplicate material ID'
    source = json.loads((ROOT/'references/source-index.json').read_text(encoding='utf-8'))
    ids = set(mids)  # HTML IDs must be unique across materials and issues.
    for m in d['materials']:
        assert re.fullmatch(r'[A-Za-z0-9_-]+', m['id']), 'Unsafe material ID'
        assert m['type'] in ('text','image_ocr','image_visual')
        assert m['status'] in ('read','partial','unread')
        for key in ('label','text','location'): assert isinstance(m[key],str)
    for issue in d['issues']:
        assert re.fullmatch(r'[A-Za-z0-9_-]+',issue['id']) and issue['id'] not in ids
        ids.add(issue['id'])
        assert issue['level'] in ('必须禁用','高危')
        assert issue['action'] in ('建议删除','建议改写')
        for k in ('title','reason','suggestion','conditions'): assert isinstance(issue[k],str) and issue[k].strip()
        assert issue['evidence'] and issue['sources']
        for e in issue['evidence']:
            m=mids[e['material_id']]
            assert m['status'] != 'unread', 'Unread material cannot support a risk'
            if m['type']=='image_visual':
                assert not e.get('quote'), 'Do not invent OCR for visual-only evidence'
                assert e.get('location')
            else:
                assert e['quote'] and e['quote'] in m['text'], 'Evidence quote must match exact source text'
        for s in issue['sources']:
            assert s['kind'] in ('platform','user')
            if s['kind']=='platform':
                assert s['id'] in source, 'Unknown platform source ID'
                if s['id'].startswith('XHS-AD-'):
                    assert d.get('ad_scope') in ('confirmed','conditional'), 'Ad rule needs declared applicability'
                    if d.get('ad_scope')=='conditional':
                        assert issue['level']!='必须禁用', 'Unknown ad scope cannot justify must-ban'
                        assert any('广告' in str(x) for x in d.get('pending',[])), 'Record ad-scope uncertainty'
            else: assert s['id'].startswith('XHS-USER-') and s.get('rule_text'), 'Custom restriction must be explicit'
            for k in ('title','location','status','excerpt'): assert isinstance(s[k],str) and s[k].strip()
    assert isinstance(d.get('pending',[]),list)
    return mids

def highlighted(m,issues):
    spans=[]
    for i in issues:
        for e in i['evidence']:
            if e['material_id']!=m['id'] or not e.get('quote'):continue
            for hit in re.finditer(re.escape(e['quote']),m['text']):spans.append((hit.start(),hit.end(),i['id']))
    # Use all boundaries so overlapping quotes retain both issue links without broken markup.
    bounds=sorted({0,len(m['text'])}|{v for a,b,_ in spans for v in (a,b)})
    result=[]
    for a,b in zip(bounds,bounds[1:]):
        ids=sorted({i for x,y,i in spans if x<=a and b<=y})
        value=esc(m['text'][a:b]).replace('\n','<br>')
        if ids:value='<span class="hit">'+value+'</span>'+''.join(f'<a href="#{esc(i)}"><sup>{esc(i)}</sup></a>' for i in ids)
        result.append(value)
    return ''.join(result)

def render(d,base):
    mids=validate(d); issues=d['issues']; pending=list(d.get('pending',[]))
    report_date=date.fromisoformat(d['date'])
    subject=d.get('content_title') or d['title']
    report_title=report_date.strftime('%Y%m%d')+subject+'敏感词审查报告'
    sections={'text':[],'images':[]}
    for m in d['materials']:
        thumb=''
        if m.get('image_path'):
            p=Path(m['image_path']);p=p if p.is_absolute() else base/p
            if p.exists():
                data=p.read_bytes();mime=('image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if data.startswith(b'\xff\xd8\xff') else 'image/webp' if data[:4]==b'RIFF' and data[8:12]==b'WEBP' else None)
                if mime and len(data)<=20*1024*1024:thumb=f'<img alt="{esc(m["label"])}" src="data:{mime};base64,{base64.b64encode(data).decode()}">'
                else:pending.append(m['label']+'：缩略图格式不支持或大于20MB，未嵌入。')
            else:pending.append(m['label']+'：原图路径不可访问，未嵌入。')
        if m['status']!='read':pending.append(m['label']+'：'+m['status']+'；未确认部分不计作已检查。')
        block=f'<div class="material note" id="{esc(m["id"])}"><h3>{esc(m["label"])}</h3><p class="meta">{esc(m["location"])} · {esc(m["status"])}</p>{thumb}<p>{highlighted(m,issues)}</p></div>'
        sections['text' if m['type']=='text' else 'images'].append(block)
    cards=[]
    for i in issues:
        ev=''.join(f'<p class="location"><a href="#{esc(e["material_id"])}">{esc(mids[e["material_id"]]["label"])} · {esc(e.get("location",mids[e["material_id"]]["location"]))}</a></p>'+ (f'<blockquote>{esc(e["quote"])}</blockquote>' if e.get('quote') else '') for e in i['evidence'])
        sources=''.join(f'<div class="source"><b>{"参考来源" if s["kind"]=="platform" else "用户自定义要求"} · {esc(s["title"])}</b><p>{esc(s["excerpt"])}</p></div>' for s in i['sources'])
        cards.append(f'<article class="issue" id="{esc(i["id"])}"><div class="issuehead"><span class="id">{esc(i["id"])}</span><span class="level {"must" if i["level"]=="必须禁用" else "high"}">{esc(i["level"])}</span></div><h3>{esc(i["title"])}</h3>{ev}<div class="detail-label">敏感原因</div><p>{esc(i["reason"])}</p>{sources}<div class="detail-label">{esc(i["action"])}</div><p>{esc(i["suggestion"])}</p><p class="suggest"><b>适用前提 / 待确认：</b>{esc(i["conditions"])}</p></article>')
    pending=list(dict.fromkeys(pending))
    notice='<div class="pending-list"><b>检查完整性与待确认事项（不计入风险等级）</b><ul>'+''.join('<li>'+esc(x)+'</li>' for x in pending)+'</ul></div>' if pending else '<p class="muted">本次未记录待确认事项；结论仅覆盖列明的提交材料。</p>'
    disclaimer=(ROOT/'assets/免责声明.md').read_text(encoding='utf-8').split('\n\n')[1:]
    css=(ROOT/'assets/report.css').read_text(encoding='utf-8')
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{esc(report_title)}</title><style>{css}</style></head><body>
<header class="appbar"><div class="bar"><span class="brand">图文内容审查 <span>非官方参考报告</span></span><button onclick="window.print()">打印 / 导出 PDF</button></div></header>
<main><section class="report-heading"><div class="eyebrow">审查报告</div><h1>{esc(report_title)}</h1><p class="meta">生成日期：{esc(d['date'])}<span>内容场景：{esc(d['scenario'])}</span></p></section>
{'<div class="demo">演示数据 · 本页用于验证报告格式，不是真实审核结论。</div>' if d.get('demo') else ''}
<section class="overview" aria-label="风险概览"><div class="overview-label">审查结果<small>按独立问题统计</small></div><div class="metric red"><b>{sum(i['level']=='必须禁用' for i in issues)}</b><div>必须禁用<small>建议优先处理</small></div></div><div class="metric amber"><b>{sum(i['level']=='高危' for i in issues)}</b><div>高危<small>结合条件调整</small></div></div><div class="overview-note">原文标红对应下方问题详情。<br>待确认事项不计入风险数量。</div></section>
{notice}
<div class="layout"><section class="panel original"><div class="panelhead"><div><span class="section-no">01</span><h2>原文与图片</h2></div><small>点击红色编号查看问题</small></div><div class="content"><h3 class="subheading">笔记文本</h3>{''.join(sections['text']) or '<p class="empty">未提供笔记文本。</p>'}<h3 class="subheading separated">图片 OCR 与画面证据</h3>{''.join(sections['images']) or '<p class="empty">未提供图片，未进行图片检查。</p>'}</div></section>
<section class="findings"><div class="panelhead"><div><span class="section-no">02</span><h2>问题明细</h2></div><small>原因、依据与处理建议</small></div>{''.join(cards) or '<div class="issue empty">在已检查范围内未发现有依据的风险问题；不等于平台保证通过。</div>'}</section></div>
<section class="review-notes"><h2>补充说明</h2><div><h3>已排除的命中</h3><p>{esc(d.get('excluded','无额外排除说明。'))}</p></div><div><h3>运营建议</h3><p>{esc(d.get('advice','无额外运营建议。'))}</p></div></section>
<footer class="disclaimer"><h2>免责声明</h2>{''.join('<p>'+esc(x)+'</p>' for x in disclaimer)}</footer></main></body></html>'''

def main():
    parser=argparse.ArgumentParser();parser.add_argument('data');parser.add_argument('output');args=parser.parse_args()
    src=Path(args.data);dest=Path(args.output)
    if dest.exists():parser.error('Output exists; choose a new report filename to preserve prior version')
    d=json.loads(src.read_text(encoding='utf-8'));body=render(d,src.resolve().parent)
    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(body,encoding='utf-8');print(dest)
if __name__=='__main__':main()
