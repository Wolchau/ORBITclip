"""A narrow, inspectable read-only SQL planner built from trusted metadata.

No database queries or raw SQL from a language model are executed. Only
structured, validated operations are compiled to a SELECT. Ollama is called
only on explicit demand from the UI; no sample rows or credentials are shared.
"""
from __future__ import annotations
import datetime
import json
import math
import re
from decimal import Decimal, InvalidOperation

from orbit_sql_semantics import BusinessSemantics, quote_ident, split_name

OPS={"eq":"=","neq":"<>","gt":">","gte":">=","lt":"<","lte":"<=",
     "like":"LIKE","in":"IN","is_null":"IS NULL","not_null":"IS NOT NULL"}
JOIN_TYPES={"INNER","LEFT"}
MAX_QUERY=2000
MAX_TABLES=16
MAX_COLUMNS=100
MAX_JOINS=12
MAX_FILTERS=24
MAX_OUTPUTS=24

class PlanError(ValueError):
    pass


def _obj(value,required,optional=()):
    if not isinstance(value,dict):
        raise PlanError("Ожидался структурированный JSON-объект")
    if not set(required).issubset(value) or set(value)-set(required)-set(optional):
        raise PlanError("Некорректные ключи структурированного плана")
    return value


def _list(value,cap):
    if not isinstance(value,list) or len(value)>cap:
        raise PlanError("Превышен допустимый объём плана")
    return value


def _str(value,max_length=150):
    if not isinstance(value,str) or not 0<len(value)<=max_length:
        raise PlanError("Некорректное значение в плане")
    return value


def _sql_value(value,column_type):
    if value is None or isinstance(value,(list,dict)):
        raise PlanError("Пустые и составные значения требуют отдельных операторов")
    if isinstance(value,bool):
        return "TRUE" if value else "FALSE"
    value=str(value)
    if len(value)>300 or "\0" in value:
        raise PlanError("Недопустимая длина или управляющий символ в фильтре")
    t=column_type.casefold()
    numeric=any(x in t for x in ("int","numeric","decimal","double","real","money","float"))
    if numeric:
        try:
            decimal=Decimal(value)
            if not decimal.is_finite():raise ValueError
        except (ValueError,InvalidOperation) as exc:
            raise PlanError("Числовой фильтр должен содержать число") from exc
        return str(decimal)
    if "date" in t or "timestamp" in t:
        try: datetime.datetime.fromisoformat(value)
        except ValueError:
            try:datetime.date.fromisoformat(value)
            except ValueError as exc:raise PlanError("Для дат используй ISO 8601") from exc
    return "'"+value.replace("'","''")+"'"


def _relation(model,from_t,from_c,to_t,to_c):
    """Verify one actual FK or user-approved manual join, with direction."""
    for fk in model._fks:
        source=f"{fk['source_schema']}.{fk['source_table']}"
        target=f"{fk['target_schema']}.{fk['target_table']}"
        left=(source,fk["source_column"],target,fk["target_column"])
        right=(target,fk["target_column"],source,fk["source_column"])
        if (from_t,from_c,to_t,to_c)==left:return "N:1"
        if (from_t,from_c,to_t,to_c)==right:return "1:N"
    for edge in model.business.project.data.get("joins",[]):
        a=(edge["left"],edge["left_column"],edge["right"],edge["right_column"])
        b=(edge["right"],edge["right_column"],edge["left"],edge["left_column"])
        if (from_t,from_c,to_t,to_c) not in (a,b):continue
        import json as _json
        key=_json.dumps(list(a),ensure_ascii=False,separators=(",",":"))
        alt=_json.dumps(list(b),ensure_ascii=False,separators=(",",":"))
        semantics=model.business.data["relations"]
        relation=semantics.get(key) or semantics.get(alt) or {}
        cardinality=relation.get("cardinality","не задана")
        if cardinality in ("N:1","1:N") and (from_t,from_c,to_t,to_c)==b:
            cardinality={"N:1":"1:N","1:N":"N:1"}[cardinality]
        return cardinality
    raise PlanError(f"Связь {from_t}.{from_c} → {to_t}.{to_c} отсутствует в схеме")


class SQLPlanner:
    def __init__(self,business,fks=()):
        self.business=business
        self._fks=list(fks)
        self.tables={t["schema"]+"."+t["name"]:t
                     for t in business.catalog}
        self.allowed=set(business.project.data.get("selected",[]))

    def context(self):
        """No rows, credentials or raw data; context bound to selected tables."""
        if len(self.allowed)>MAX_TABLES:
            raise PlanError("Для Ollama выбери не более 16 таблиц в рабочем наборе")
        if not self.allowed:
            raise PlanError("Сначала выбери рабочие таблицы")
        ctx=self.business.context()
        result=[]
        for table in ctx["tables"]:
            if len(table["fields"])>MAX_COLUMNS:
                raise PlanError("Слишком много полей; сократи рабочий набор")
            result.append(table)
        if len(result)!=len(self.allowed):
            raise PlanError("Метаданные выбранных таблиц не загружены")
        fks=[{"from":f"{x['source_schema']}.{x['source_table']}",
              "from_column":x["source_column"],
              "to":f"{x['target_schema']}.{x['target_table']}",
              "to_column":x["target_column"]}
             for x in self._fks
             if f"{x['source_schema']}.{x['source_table']}" in self.allowed
             and f"{x['target_schema']}.{x['target_table']}" in self.allowed]
        manual=[dict(x) for x in self.business.project.data.get("joins",[])
                if x.get("left") in self.allowed and x.get("right") in self.allowed]
        ctx["tables"]=result
        ctx["fks"]=fks
        ctx["manual_joins"]=manual
        ctx["metrics"]={k:v for k,v in ctx["metrics"].items()
                        if isinstance(v,dict) and v.get("table") in self.allowed}
        ctx["relations"]={k:v for k,v in ctx["relations"].items()
                          if isinstance(v,dict)}
        return ctx

    def _column(self,table,column):
        if table not in self.allowed or table not in self.tables:
            raise PlanError("Таблица вне выбранной рабочей схемы: "+str(table))
        try:self.business._column(table,column)
        except ValueError as exc:raise PlanError(str(exc)) from exc
        return next(x for x in self.business.columns[table] if x["name"]==column)

    def compile(self,plan):
        _obj(plan,("status",),("question","assumptions","base_table","joins","dimensions",
                            "metrics","filters","having","order_by","limit"))
        if plan["status"]=="clarify":
            return {"status":"clarify","question":_str(plan.get("question",""),1200)}
        if plan["status"]!="ready":
            raise PlanError("Ожидается ready либо clarify")
        for required in ("base_table","joins","dimensions","metrics","filters",
                         "having","order_by","limit"):
            if required not in plan:
                raise PlanError("Отсутствует обязательный раздел плана: "+required)
        base=_str(plan["base_table"])
        if base not in self.allowed:raise PlanError("Не выбрана таблица "+base)
        joins=_list(plan["joins"],MAX_JOINS)
        dimensions=_list(plan["dimensions"],MAX_OUTPUTS)
        metrics=_list(plan["metrics"],MAX_OUTPUTS)
        if not dimensions and not metrics:raise PlanError("Не выбран ни один показатель или разрез")
        if len(dimensions)+len(metrics)>MAX_OUTPUTS:raise PlanError("Слишком много столбцов")
        aliases={base:"t0"}
        clauses=[]
        fanout=[]
        for i,j in enumerate(joins,1):
            _obj(j,("from_table","from_column","to_table","to_column","join_type"))
            frm=_str(j["from_table"]);to=_str(j["to_table"])
            fc=_str(j["from_column"]);tc=_str(j["to_column"])
            join_type=j["join_type"]
            if join_type not in JOIN_TYPES:raise PlanError("Только INNER/LEFT JOIN")
            if frm not in aliases or to in aliases or to not in self.allowed:
                raise PlanError("JOIN должен вести из уже присоединённой таблицы")
            self._column(frm,fc);self._column(to,tc)
            cardinality=_relation(self,frm,fc,to,tc)
            if cardinality not in ("N:1","1:1"):fanout.append((frm,to,cardinality))
            alias="t"+str(i)
            aliases[to]=alias
            schema,table=split_name(to)
            clauses.append(
                f'{join_type} JOIN {quote_ident(schema)}.{quote_ident(table)} AS {quote_ident(alias)}'
                f'\n    ON {quote_ident(aliases[frm])}.{quote_ident(fc)}'
                f' = {quote_ident(alias)}.{quote_ident(tc)}')
        if metrics and fanout:
            paths=", ".join(f"{a} → {b} ({c})" for a,b,c in fanout)
            raise PlanError("Агрегация может дублировать строки из-за JOIN: "+paths+
                            ". Проверь зерно таблиц и скорректируй запрос вручную.")
        def col(table,column):
            self._column(table,column)
            if table not in aliases:raise PlanError("Таблица не подключена: "+table)
            return quote_ident(aliases[table])+"."+quote_ident(column)

        selected=[];group=[];outputs={}
        for item in dimensions:
            _obj(item,("table","column"),("alias",))
            raw=col(item["table"],item["column"])
            label=_str(item.get("alias") or item["column"])
            if label in outputs:raise PlanError("Повторяется имя выходного столбца")
            outputs[label]=raw
            selected.append(raw+" AS "+quote_ident(label))
            group.append(raw)

        saved=self.business.data["metrics"]
        metric_sql={}
        for item in metrics:
            _obj(item,("name",))
            name=_str(item["name"])
            definition=saved.get(name)
            if not isinstance(definition,dict):
                raise PlanError("Неизвестная сохранённая метрика: "+name)
            table=definition["table"]
            if table not in aliases:raise PlanError("Источник метрики не подключён: "+table)
            # v7.8.6 metric definitions contain explanatory prose, not a
            # structured WHERE formula. Refuse silently ignoring exclusions.
            description=str(definition.get("description") or "")
            if re.search(r"(?i)\\b(?:только|исключая|исключить|исключение|без|статус|фильтр|если|where|except|exclude|only)\\b",description):
                raise PlanError("Определение метрики «"+name+
                    "» содержит условие/исключение, которое пока не формализовано. "
                    "Нельзя безопасно строить SUM/COUNT без этого фильтра.")
            agg=definition["aggregation"]
            if agg=="COUNT_ROWS":expression="COUNT(*)"
            else:
                ref=col(table,definition["column"])
                if agg=="COUNT_DISTINCT":expression=f"COUNT(DISTINCT {ref})"
                elif agg in ("SUM","AVG","MIN","MAX","COUNT"):
                    expression=f"{agg}({ref})"
                else:raise PlanError("Неизвестный тип агрегации")
            if name in outputs:raise PlanError("Повторяется имя выходного столбца")
            outputs[name]=expression
            metric_sql[name]=expression
            selected.append(expression+" AS "+quote_ident(name))

        def condition(item,reference,column_type):
            op=item.get("op")
            if op not in OPS:raise PlanError("Неподдерживаемое сравнение")
            if op in ("is_null","not_null"):
                if "value" in item:raise PlanError("NULL-сравнение не принимает значение")
                return reference+" "+OPS[op]
            if "value" not in item:raise PlanError("Не указано значение фильтра")
            if op=="in":
                values=_list(item["value"],25)
                if not values:raise PlanError("Пустой список IN")
                return reference+" IN ("+", ".join(_sql_value(v,column_type) for v in values)+")"
            if op=="like":
                if not any(x in column_type.lower() for x in ("text","char","varchar")):
                    raise PlanError("LIKE допустим только для текстового поля")
            return reference+" "+OPS[op]+" "+_sql_value(item["value"],column_type)

        where=[]
        for f in _list(plan["filters"],MAX_FILTERS):
            _obj(f,("table","column","op"),("value",))
            col_type=self._column(f["table"],f["column"])["type"]
            where.append(condition(f,col(f["table"],f["column"]),col_type))
        having=[]
        for h in _list(plan["having"],MAX_FILTERS):
            _obj(h,("metric","op"),("value",))
            label=h["metric"]
            if label not in metric_sql:raise PlanError("HAVING ссылается на невыбранную метрику")
            definition=saved[label]
            typ="numeric" if definition["aggregation"]!="COUNT_ROWS" else "bigint"
            having.append(condition(h,metric_sql[label],typ))
        order=[]
        for item in _list(plan["order_by"],MAX_OUTPUTS):
            _obj(item,("by","direction"))
            if item["by"] not in outputs:
                raise PlanError("Сортировка только по выбранным результатам")
            if item["direction"] not in ("ASC","DESC"):
                raise PlanError("Сортировка должна быть ASC или DESC")
            order.append(quote_ident(item["by"])+" "+item["direction"])
        limit=plan["limit"]
        if not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=5000:
            raise PlanError("LIMIT допускается только 1–5000")
        schema,table_name=split_name(base)
        chunks=["SELECT\n    "+",\n    ".join(selected),
                "FROM "+quote_ident(schema)+"."+quote_ident(table_name)+" AS "+quote_ident("t0")]
        chunks+=clauses
        if where:chunks.append("WHERE "+" AND ".join(where))
        if group:chunks.append("GROUP BY "+", ".join(group))
        if having:chunks.append("HAVING "+" AND ".join(having))
        if order:chunks.append("ORDER BY "+", ".join(order))
        chunks.append("LIMIT "+str(limit))
        assumptions=_list(plan.get("assumptions",[]),12)
        if not all(isinstance(a,str) and len(a)<=500 for a in assumptions):
            raise PlanError("Некорректное описание допущений")
        return {"status":"ready","sql":"\n".join(chunks)+";",
                "assumptions":assumptions, "joined_tables":list(aliases),
                "warnings":["Черновик SQL необходимо проверить до выполнения."]}
