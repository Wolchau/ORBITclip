"""Business semantics for ORBITclip SQL Explorer.

Local, profile-scoped documentation with a deliberately narrow, audited SQL
compiler for one-table business metrics. Never infers joins, executes queries,
or treats prose descriptions as executable expressions.
"""
from __future__ import annotations

import copy
import re

AGGREGATIONS = ("SUM", "AVG", "MIN", "MAX", "COUNT", "COUNT_DISTINCT", "COUNT_ROWS")
FIELD_ROLES = ("", "dimension", "measure", "identifier", "date", "currency", "status")
CARDINALITIES = ("не задана", "1:1", "1:N", "N:1", "N:N")
MAX_TEXT = 3000
MAX_METRICS = 200
MAX_TERMS = 400


def _string(value, *, limit=MAX_TEXT):
    if not isinstance(value, str):
        raise ValueError("Текстовое значение должно быть строкой")
    if len(value) > limit:
        raise ValueError(f"Текст не может быть длиннее {limit} символов")
    return value.strip()


def quote_ident(name):
    """PostgreSQL identifier quoting, not interpolation of SQL expressions."""
    if not isinstance(name, str) or not name or "\0" in name or len(name) > 128:
        raise ValueError("Некорректный SQL-идентификатор")
    return '"' + name.replace('"', '""') + '"'


def split_name(table):
    parts = table.split(".", 1) if isinstance(table, str) else []
    if len(parts) != 2 or not all(parts):
        raise ValueError("Ожидается имя schema.table")
    return parts


class BusinessSemantics:
    """Stores only business documentation, referencing verified DB metadata."""

    def __init__(self, project, catalog, columns):
        self.project = project
        self.catalog = catalog
        self.columns = columns

    @property
    def data(self):
        d = self.project.data.setdefault("business", {})
        for name in ("tables", "metrics", "relations", "glossary"):
            if not isinstance(d.get(name), dict):
                d[name] = {}
        return d

    def _tables(self):
        return {r["schema"] + "." + r["name"]: r for r in self.catalog}

    def _table(self, name):
        if name not in self._tables():
            raise ValueError("Таблица не найдена в подключённой базе")
        return name

    def _column(self, table, name):
        self._table(table)
        if name not in {c["name"] for c in self.columns.get(table, [])}:
            raise ValueError(f"Столбец {name!r} отсутствует в метаданных {table}")
        return name

    def get_table(self, table):
        self._table(table)
        return copy.deepcopy(self.data["tables"].get(table, {}))

    def save_table(self, table, title, description, grain):
        self._table(table)
        current = self.data["tables"].setdefault(table, {})
        current.update({"title": _string(title, limit=160),
                        "description": _string(description),
                        "grain": _string(grain, limit=500)})
        self.project.save()
        return copy.deepcopy(current)

    def get_field(self, table, column):
        self._column(table, column)
        return copy.deepcopy(self.data["tables"].get(table, {})
                             .get("fields", {}).get(column, {}))

    def save_field(self, table, column, title, description, role="", unit=""):
        self._column(table, column)
        if role not in FIELD_ROLES:
            raise ValueError("Неизвестная бизнес-роль поля")
        record = {"title": _string(title, limit=160),
                  "description": _string(description),
                  "role": role, "unit": _string(unit, limit=80)}
        self.data["tables"].setdefault(table, {}).setdefault("fields", {})[column] = record
        self.project.save()
        return copy.deepcopy(record)

    def save_metric(self, name, table, column, aggregation, description="", unit=""):
        name = _string(name, limit=160)
        if not name:
            raise ValueError("Укажи название метрики")
        self._table(table)
        if aggregation not in AGGREGATIONS:
            raise ValueError("Недопустимая агрегация")
        if aggregation != "COUNT_ROWS":
            self._column(table, column)
        else:
            column = ""
        metrics = self.data["metrics"]
        if name not in metrics and len(metrics) >= MAX_METRICS:
            raise ValueError("Слишком много метрик")
        result = {"table": table, "column": column, "aggregation": aggregation,
                  "description": _string(description), "unit": _string(unit, limit=80)}
        metrics[name] = result
        self.project.save()
        return copy.deepcopy(result)

    def delete_metric(self, name):
        if name in self.data["metrics"]:
            del self.data["metrics"][name]
            self.project.save()
            return True
        return False

    def save_glossary(self, term, description):
        term = _string(term, limit=160)
        if not term:
            raise ValueError("Термин не может быть пустым")
        glossary = self.data["glossary"]
        if term not in glossary and len(glossary) >= MAX_TERMS:
            raise ValueError("Превышен лимит терминов")
        glossary[term] = _string(description)
        self.project.save()

    def delete_glossary(self, term):
        if term in self.data["glossary"]:
            del self.data["glossary"][term]
            self.project.save()
            return True
        return False

    def relation_key(self, left, left_column, right, right_column):
        self._column(left, left_column)
        self._column(right, right_column)
        # JSON-like canonical key; no collision when names contain ".".
        import json
        return json.dumps([left, left_column, right, right_column],
                          ensure_ascii=False, separators=(",", ":"))

    def save_relation(self, left, left_column, right, right_column,
                      description, cardinality="не задана"):
        if cardinality not in CARDINALITIES:
            raise ValueError("Недопустимая кардинальность")
        key = self.relation_key(left, left_column, right, right_column)
        self.data["relations"][key] = {
            "description": _string(description),
            "cardinality": cardinality,
        }
        self.project.save()
        return key

    def compile_metric(self, name, group_column=None):
        """Safe and explicit SELECT; no inferred cross-table joins or filters."""
        metric = self.data["metrics"].get(name)
        if not isinstance(metric, dict):
            raise ValueError("Метрика не найдена")
        table = metric["table"]
        self._table(table)
        agg = metric["aggregation"]
        if agg not in AGGREGATIONS:
            raise ValueError("Недопустимая агрегация")
        if agg == "COUNT_ROWS":
            expression = "COUNT(*)"
        else:
            column = self._column(table, metric["column"])
            if agg == "COUNT_DISTINCT":
                expression = f"COUNT(DISTINCT {quote_ident(column)})"
            else:
                expression = f"{agg}({quote_ident(column)})"
        select = []
        if group_column:
            self._column(table, group_column)
            select.append(quote_ident(group_column))
        select.append(expression + " AS " + quote_ident(name))
        schema, table_name = split_name(table)
        sql = "SELECT\n    " + ",\n    ".join(select)
        sql += "\nFROM " + quote_ident(schema) + "." + quote_ident(table_name)
        if group_column:
            sql += "\nGROUP BY " + quote_ident(group_column)
            sql += "\nORDER BY " + quote_ident(group_column)
        return sql + ";"

    def context(self):
        """Documentation suitable for a future local semantic model (NO rows)."""
        tables = self._tables()
        result = {"tables": [], "metrics": copy.deepcopy(self.data["metrics"]),
                  "glossary": copy.deepcopy(self.data["glossary"]),
                  "relations": copy.deepcopy(self.data["relations"])}
        for name in self.project.data.get("selected", []):
            if name not in tables:
                continue
            t = self.data["tables"].get(name, {})
            fields = t.get("fields", {}) if isinstance(t.get("fields", {}), dict) else {}
            result["tables"].append({
                "name": name, "title": t.get("title", ""),
                "description": t.get("description", ""),
                "grain": t.get("grain", ""),
                "fields": [{"name": c["name"], "type": c["type"],
                            "title": fields.get(c["name"], {}).get("title", ""),
                            "description": fields.get(c["name"], {}).get("description", ""),
                            "unit": fields.get(c["name"], {}).get("unit", ""),
                            "role": fields.get(c["name"], {}).get("role", "")}
                           for c in self.columns.get(name, [])]
            })
        return result
