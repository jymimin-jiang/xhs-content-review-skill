#!/usr/bin/env python3
"""Local release manager. No network calls; Python 3.9+ standard library."""
import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

NAME = 'xhs-content-review'
SCHEMA = 1

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def version(value):
    if not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise ValueError('版本必须为 major.minor.patch')
    return tuple(map(int, value.split('.')))

def inventory(root, managed=False):
    result = {}
    for p in sorted(Path(root).rglob('*')):
        if p.is_symlink():
            raise ValueError('不接受符号链接: '+str(p))
        if not p.is_file():
            continue
        key = p.relative_to(root).as_posix()
        if managed and (key in ('release.json', 'installation.json') or '__pycache__' in p.relative_to(root).parts):
            continue
        result[key] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result

def validate(root):
    meta = read(root/'release.json')
    if meta.get('name') != NAME or meta.get('data_schema') != SCHEMA:
        raise ValueError('包名或用户数据结构不兼容')
    version(meta['version'])
    if not (root/'SKILL.md').is_file() or inventory(root, True) != meta.get('files'):
        raise ValueError('文件清单或校验值不一致；不得直接覆盖本地修改')
    return meta

def unpack(package, root):
    with zipfile.ZipFile(package) as archive:
        infos = archive.infolist()
        if len(infos) > 5000 or sum(i.file_size for i in infos) > 100*1024*1024:
            raise ValueError('安装包过大')
        seen = set()
        for info in infos:
            raw = info.filename
            parts = PurePosixPath(raw).parts
            if ('\\' in raw or ':' in raw or raw.startswith('/') or '..' in parts or
                not parts or parts[0] != NAME or raw in seen or
                (info.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('安装包路径不安全或重复')
            seen.add(raw)
            if info.is_dir():
                continue
            rel = PurePosixPath(*parts[1:])
            if str(rel) in ('.', 'installation.json') or '__pycache__' in rel.parts:
                raise ValueError('发布包包含运行时文件')
            dest = root.joinpath(*rel.parts)
            if dest.exists():
                raise ValueError('安装包包含重复文件')
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(archive.read(info))
    return validate(root)

def paths(target, data):
    target, data = Path(target).expanduser().absolute(), Path(data).expanduser().absolute()
    for p in (target, data):
        if p.is_symlink():
            raise ValueError('安装与数据目录本身不得为符号链接')
    target, data = target.resolve(), data.resolve()
    if target == data or target in data.parents or data in target.parents:
        raise ValueError('Skill 与用户数据目录不能重叠')
    if (target/'installation.json').exists():
        if Path(read(target/'installation.json')['data_dir']).resolve() != data:
            raise ValueError('数据目录与安装记录不符，请使用原数据目录')
    if (data/'config.json').exists() and read(data/'config.json').get('data_schema') != SCHEMA:
        raise ValueError('用户数据版本不兼容；未执行迁移')
    return target, data

@contextmanager
def locked(data):
    data.mkdir(parents=True, exist_ok=True)
    for p in data.iterdir():
        if p.is_symlink():
            raise ValueError('用户数据顶层不得包含符号链接')
    lock = data/'.update.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError('已有更新锁；确认无更新进程后才可手动移除 .update.lock')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)

def init_data(data):
    defaults = {
        '用户敏感词.md': '# 用户敏感词\n\n用户自定义，非平台官方规定。仅启用的记录参与审查；命中后仍需结合语境。\n\n| ID | 状态 | 词语 | 适用行业/场景 | 触发条件 | 排除条件 | 等级 | 原因/来源 | 修改日期 | 引用内置ID（可选） |\n|---|---|---|---|---|---|---|---|---|---|\n',
        '用户自定义规则.md': '# 用户自定义规则\n\n仅状态为“启用”的规则生效，不得伪装为官方规则。\n\n新增时逐条填写：ID（XHS-USER-R-开头）、状态（草稿/启用/停用）、标题、适用范围、要求、语义触发条件、排除条件、原因、更新时间。\n',
    }
    for name, text in defaults.items():
        p = data/name
        if not p.exists():
            p.write_text(text, encoding='utf-8')
    if not (data/'config.json').exists():
        write(data/'config.json', {'data_schema':SCHEMA})
    for folder in ('reports', 'backups'):
        (data/folder).mkdir(exist_ok=True)

def snapshot(target, data):
    """Back up code and all user files except the recursive backup tree and lock."""
    backup_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    dest = data/'backups'/backup_id
    dest.mkdir(parents=True)
    # Refuse symlinks before copytree can follow them.
    code_hashes = inventory(target)
    shutil.copytree(target, dest/'skill')
    user = dest/'user-data'
    user.mkdir()
    for p in data.iterdir():
        if p.name in ('backups', '.update.lock'):
            continue
        if p.is_symlink():
            raise ValueError('用户目录中存在符号链接，备份已停止')
        if p.is_dir():
            inventory(p)
            shutil.copytree(p, user/p.name)
        else:
            shutil.copy2(p, user/p.name)
    write(dest/'backup.json', {'backup_id':backup_id, 'target':str(target),
        'data_schema':SCHEMA, 'files':code_hashes, 'user_files':inventory(user)})
    return backup_id

def switch(incoming, target):
    hold = incoming.parent/'previous'
    existed = target.exists()
    if existed:
        os.replace(target, hold)
    try:
        os.replace(incoming, target)
    except BaseException:
        if existed:
            os.replace(hold, target)
        raise

def install(package, target, data, migrate_legacy=False):
    target, data = paths(target, data)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.xhs-stage-', dir=target.parent) as temp:
        incoming = Path(temp)/'incoming'
        incoming.mkdir()
        meta = unpack(package, incoming)
        with locked(data):
            init_data(data)
            backup_id = None
            legacy = False
            if target.exists():
                if not (target/'SKILL.md').is_file():
                    raise ValueError('目标不是 Skill 目录，拒绝替换')
                legacy = not (target/'release.json').exists()
                if legacy and not migrate_legacy:
                    raise ValueError('旧版无发布清单，请使用 --migrate-legacy 显式迁移')
                if legacy and not re.search(r'^name:\s*xhs-content-review\s*$', (target/'SKILL.md').read_text(), re.M):
                    raise ValueError('旧版包名不符')
                backup_id = snapshot(target, data)
                if not legacy:
                    old = validate(target)
                    if version(meta['version']) < version(old['version']):
                        raise ValueError('不允许安装较旧版本；请使用 rollback')
                    if meta['version'] == old['version'] and meta['files'] != old['files']:
                        raise ValueError('同一版本号不能对应不同文件')
            if legacy:
                write(data/('迁移待处理-'+backup_id+'.json'), {
                    'backup_id':backup_id, 'status':'待人工合并',
                    'instruction':'旧版包内用户词库和规则已完整存档。请比较后把用户新增内容合并到包外文件；不要导入整个作者词库。尚未合并的旧设置不会自动生效。'})
            write(incoming/'installation.json', {'data_dir':str(data), 'data_schema':SCHEMA})
            switch(incoming, target)
            return {'version':meta['version'], 'backup_id':backup_id, 'data_dir':str(data), 'legacy_migration_pending':legacy}

def rollback(target, data, backup_id):
    target, data = paths(target, data)
    if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}', backup_id):
        raise ValueError('无效备份编号')
    with locked(data):
        source = data/'backups'/backup_id
        if source.is_symlink():
            raise ValueError('备份不能是符号链接')
        meta = read(source/'backup.json')
        if meta['target'] != str(target) or meta['data_schema'] != SCHEMA or inventory(source/'skill') != meta['files']:
            raise ValueError('备份损坏或属于其他安装目录')
        if (source/'skill/release.json').exists():
            # Local modifications deliberately backed up can be restored exactly.
            if read(source/'skill/release.json').get('data_schema') != SCHEMA:
                raise ValueError('回退版本不支持当前数据结构')
        backup_current = snapshot(target, data) if target.exists() else None
        with tempfile.TemporaryDirectory(prefix='.xhs-stage-', dir=target.parent) as temp:
            incoming = Path(temp)/'incoming'
            shutil.copytree(source/'skill', incoming)
            write(incoming/'installation.json', {'data_dir':str(data), 'data_schema':SCHEMA})
            switch(incoming, target)
        return {'restored':backup_id, 'backup_id':backup_current, 'user_data':'保持不变'}

def status(target, data):
    target, data = paths(target, data)
    return {'target':str(target), 'data_dir':str(data),
        'release':read(target/'release.json') if (target/'release.json').exists() else None,
        'backups':[p.parent.name for p in sorted((data/'backups').glob('*/backup.json'))],
        'locked':(data/'.update.lock').exists(),
        'migration_records':[p.name for p in data.glob('迁移待处理-*.json')]}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['install','update','status','backup','rollback','init-data'])
    parser.add_argument('--target', type=Path, required=True, help='Skill 的最终目录，包含 xhs-content-review')
    parser.add_argument('--data-dir', type=Path, help='默认沿用安装记录，否则 ~/.xhs-content-review')
    parser.add_argument('--package', type=Path)
    parser.add_argument('--backup-id')
    parser.add_argument('--migrate-legacy', action='store_true')
    args = parser.parse_args()
    record = args.target.expanduser()/'installation.json'
    data = args.data_dir or (Path(read(record)['data_dir']) if record.exists() else Path.home()/'.xhs-content-review')
    try:
        if args.command in ('install','update'):
            if not args.package:
                parser.error('--package 必填')
            if args.command == 'update' and not args.target.expanduser().exists():
                raise ValueError('尚未安装，请使用 install')
            result = install(args.package,args.target,data,args.migrate_legacy)
        elif args.command == 'rollback':
            if not args.backup_id:
                parser.error('--backup-id 必填')
            result = rollback(args.target,data,args.backup_id)
        elif args.command in ('backup','init-data'):
            target,data = paths(args.target,data)
            with locked(data):
                init_data(data)
                result = {'backup_id':snapshot(target,data)} if args.command=='backup' else {'data_dir':str(data)}
        else:
            result = status(args.target,data)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,OSError,KeyError,zipfile.BadZipFile) as error:
        parser.exit(1,'操作未完成：'+str(error)+'\n')

if __name__ == '__main__':
    main()
