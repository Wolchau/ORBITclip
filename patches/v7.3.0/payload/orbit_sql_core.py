"""ORBITclip SQL Explorer core: read-only PostgreSQL metadata and local annotations.

Database passwords are never persisted. All untrusted names are values, not SQL.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

PROJECT_DIR = Path.home() / '.orbitclip_sql_projects'
SSL_MODES = ('verify-full', 'verify-ca', 'require', 'prefer', 'disable')


def profile_key(host: str, port: int, database: str, user: str) -> str:
    parts = [str(host).strip().lower(), str(int(port)), str(database).strip(), str(user).strip()]
    if not parts[0] or not parts[2] or not parts[3]:
        raise ValueError('Укажи сервер, базу и пользователя')
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:24]


def table_id(schema: str, name: str) -> str:
    return json.dumps([schema, name], ensure_ascii=False, separators=(',', ':'))


def split_table_id(identity: str) -> tuple[str, str]:
    data = json.loads(identity)
    if not isinstance(data, list) or len(data) != 2 or not all(isinstance(s, str) and s for s in data):
        raise ValueError('Некорректный идентификатор таблицы')
    return data[0], data[1]


def new_project() -> dict:
    return {'schema_version': 1, 'selected': [], 'notes': {}, 'joins': [], 'positions': {}}


def validate_project(project: dict) -> dict:
    if not isinstance(project, dict) or project.get('schema_version') != 1:
        raise ValueError('Неподдерживаемый формат проекта SQL')
    selected = project.get('selected', [])
    if not isinstance(selected, list) or len(selected) > 10000:
        raise ValueError('Некорректный список таблиц')
    selected = list(dict.fromkeys(s for s in selected if isinstance(s, str) and _valid_table(s)))
    notes = project.get('notes', {})
    joins = project.get('joins', [])
    positions = project.get('positions', {})
    if not isinstance(notes, dict) or not isinstance(joins, list) or not isinstance(positions, dict):
        raise ValueError('Некорректные метаданные')
    # Limit file size and restrict notes to strings; never store connection credentials.
    clean_notes = {str(k)[:500]: v[:2000] for k, v in notes.items()
                   if isinstance(k, str) and isinstance(v, str)}
    clean_joins = []
    for j in joins[:2000]:
        if not isinstance(j, dict):
            continue
        keys = ('left', 'left_column', 'right', 'right_column')
        if all(isinstance(j.get(k), str) and j.get(k) for k in keys) and _valid_table(j['left']) and _valid_table(j['right']):
            clean_joins.append({k: j[k][:300] for k in keys})
    clean_positions = {}
    for key, val in positions.items():
        if _valid_table(key) and isinstance(val, list) and len(val) == 2 and all(isinstance(p, (int, float)) and not isinstance(p, bool) and abs(p) <= 1_000_000 for p in val):
            clean_positions[key] = [float(val[0]), float(val[1])]
    return {'schema_version': 1, 'selected': selected, 'notes': clean_notes,
            'joins': clean_joins, 'positions': clean_positions}


def _valid_table(v):
    try:
        split_table_id(v)
        return True
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def load_project(key: str, directory: Path = PROJECT_DIR) -> dict:
    path = directory / (key + '.json')
    if not path.exists():
        return new_project()
    if path.stat().st_size > 4_000_000:
        raise ValueError('Проект SQL слишком большой')
    return validate_project(json.loads(path.read_text(encoding='utf-8')))


def save_project(key: str, project: dict, directory: Path = PROJECT_DIR) -> None:
    if not isinstance(key, str) or len(key) != 24 or any(c not in '0123456789abcdef' for c in key):
        raise ValueError('Неверный ключ профиля')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = json.dumps(validate_project(project), ensure_ascii=False, indent=2).encode('utf-8')
    handle, tmp = tempfile.mkstemp(prefix='.orbit-sql-', dir=directory)
    try:
        with os.fdopen(handle, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, directory / (key + '.json'))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def field_note_key(identity: str, column: str) -> str:
    return identity + '::' + column


def manual_join(left: str, left_column: str, right: str, right_column: str) -> dict:
    split_table_id(left)
    split_table_id(right)
    if not left_column.strip() or not right_column.strip():
        raise ValueError('Выбери поля соединения')
    return {'left': left, 'left_column': left_column, 'right': right, 'right_column': right_column}


TABLES_SQL = '''
SELECT n.nspname, c.relname, c.relkind, COALESCE(obj_description(c.oid, 'pg_class'), '')
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r','p','v','m','f')
  AND n.nspname NOT IN ('pg_catalog','information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND has_schema_privilege(n.oid,'USAGE')
  AND (has_table_privilege(c.oid,'SELECT') OR has_any_column_privilege(c.oid,'SELECT'))
ORDER BY n.nspname, c.relname
LIMIT 10001
'''

COLUMNS_SQL = '''
SELECT a.attname, pg_catalog.format_type(a.atttypid,a.atttypmod),
       NOT a.attnotnull, COALESCE(pg_catalog.col_description(a.attrelid,a.attnum),''),
       a.attnum
FROM pg_catalog.pg_attribute a
JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname=%s AND c.relname=%s AND c.relkind IN ('r','p','v','m','f')
  AND a.attnum > 0 AND NOT a.attisdropped
  AND has_schema_privilege(n.oid,'USAGE')
  AND (has_table_privilege(c.oid,'SELECT') OR has_column_privilege(c.oid,a.attnum,'SELECT'))
ORDER BY a.attnum
'''

CONSTRAINTS_SQL = '''
SELECT co.contype, co.conname,
       ARRAY(SELECT a.attname FROM unnest(co.conkey) WITH ORDINALITY k(attnum, ord)
             JOIN pg_catalog.pg_attribute a ON a.attrelid=co.conrelid AND a.attnum=k.attnum
             ORDER BY k.ord),
       rn.nspname, rc.relname,
       ARRAY(SELECT a.attname FROM unnest(co.confkey) WITH ORDINALITY k(attnum, ord)
             JOIN pg_catalog.pg_attribute a ON a.attrelid=co.confrelid AND a.attnum=k.attnum
             ORDER BY k.ord)
FROM pg_catalog.pg_constraint co
JOIN pg_catalog.pg_class c ON c.oid=co.conrelid
JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
LEFT JOIN pg_catalog.pg_class rc ON rc.oid=co.confrelid
LEFT JOIN pg_catalog.pg_namespace rn ON rn.oid=rc.relnamespace
WHERE n.nspname=%s AND c.relname=%s AND co.contype IN ('p','u','f')
ORDER BY co.contype, co.conname
'''


def pg_connect(config: dict):
    """Return a PostgreSQL connection restricted to read-only transactions."""
    try:
        import psycopg
    except ImportError as e:
        raise RuntimeError('Для PostgreSQL установи: python -m pip install "psycopg[binary]>=3.2,<4"') from e
    sslmode = config.get('sslmode', 'verify-full')
    if sslmode not in SSL_MODES:
        raise ValueError('Недопустимый режим TLS')
    conn = psycopg.connect(
        host=config['host'], port=int(config['port']), dbname=config['database'],
        user=config['user'], password=config['password'], sslmode=sslmode,
        connect_timeout=8, application_name='ORBITclip SQL Explorer',
        options='-c default_transaction_read_only=on -c statement_timeout=12000')
    conn.read_only = True
    return conn


def discover_tables(config: dict) -> list[dict]:
    with pg_connect(config) as conn:
        with conn.cursor() as cursor:
            cursor.execute(TABLES_SQL)
            rows = cursor.fetchall()
    if len(rows) > 10000:
        raise ValueError('Более 10 000 таблиц: сузь права пользователя БД')
    return [{'id': table_id(schema, table), 'schema': schema, 'name': table,
             'kind': kind, 'comment': comment} for schema, table, kind, comment in rows]


def inspect_tables(config: dict, selected: list[str]) -> dict:
    if len(selected) > 150:
        raise ValueError('В одной схеме допускается до 150 рабочих таблиц')
    details = {}
    with pg_connect(config) as conn:
        with conn.cursor() as cursor:
            for identity in selected:
                schema, name = split_table_id(identity)
                cursor.execute(COLUMNS_SQL, (schema, name))
                cols = cursor.fetchall()
                if not cols:
                    continue
                cursor.execute(CONSTRAINTS_SQL, (schema, name))
                rows = cursor.fetchall()
                pk = {col for typ, _, names, _, _, _ in rows if typ == 'p' for col in names}
                unique = {col for typ, _, names, _, _, _ in rows if typ == 'u' and len(names) == 1 for col in names}
                foreign = {col for typ, _, names, _, _, _ in rows if typ == 'f' for col in names}
                columns = [{'name': col, 'type': typ, 'nullable': nullable, 'db_comment': comment,
                            'pk': col in pk, 'fk': col in foreign, 'unique': col in unique}
                           for col, typ, nullable, comment, _ in cols]
                edges = [{'name': cname, 'left': identity, 'left_columns': list(names),
                          'right': table_id(rs, rn), 'right_columns': list(ref)}
                         for ct, cname, names, rs, rn, ref in rows if ct == 'f' and rs and rn]
                details[identity] = {'columns': columns, 'foreign_keys': edges}
    return details


def visible_links(details: dict, project: dict) -> list[dict]:
    selected = set(project['selected'])
    result = []
    for src, item in details.items():
        if src not in selected:
            continue
        for fk in item['foreign_keys']:
            if fk['right'] in selected:
                for left_col, right_col in zip(fk['left_columns'], fk['right_columns']):
                    result.append({'left': src, 'left_column': left_col, 'right': fk['right'],
                                   'right_column': right_col, 'kind': 'FK'})
    for j in project['joins']:
        if j['left'] in selected and j['right'] in selected:
            result.append(dict(j, kind='manual'))
    return result
