import csv
import io
import json
import re
from decimal import Decimal
from html.parser import HTMLParser

from defusedxml import ElementTree

from .ollama_client import AIError

MAX_ROWS = 5000


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.rows, self.cells = [], [], []
        self.text, self.cell, self.title = [], None, []
        self.in_title, self.hidden, self.depth = False, 0, 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if tag == "title":
            self.in_title = True
        if tag == "table":
            if self.depth == 0:
                self.rows = []
            self.depth += 1
        if self.depth and tag == "tr":
            self.cells = []
        if self.depth and tag in {"td", "th"}:
            self.cell = []

    def handle_data(self, value):
        if self.hidden:
            return
        if self.in_title:
            self.title.append(value)
        if self.cell is not None:
            self.cell.append(value)
        if value.strip():
            self.text.append(value.strip())

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False
        if self.depth and tag in {"td", "th"} and self.cell is not None:
            self.cells.append(re.sub(r"\s+", " ", " ".join(self.cell)).strip())
            self.cell = None
        if self.depth and tag == "tr" and self.cells:
            self.rows.append(self.cells)
            self.cells = []
        if tag == "table":
            self.depth = max(0, self.depth - 1)
            if not self.depth and self.rows:
                self.tables.append(self.rows)


def unique_headers(values):
    seen, result = {}, []
    for index, value in enumerate(values):
        label = str(value).strip() or f"列{index + 1}"
        seen[label] = seen.get(label, 0) + 1
        result.append(label if seen[label] == 1 else f"{label}_{seen[label]}")
    return result


def clean(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)[:16000]
    return value if not isinstance(value, str) else value[:16000]


def extract(content: bytes, content_type: str, url: str) -> dict:
    encoding = re.search(r"charset=([\w-]+)", content_type, re.I)
    try:
        text = content.decode(encoding.group(1) if encoding else "utf-8-sig")
    except (UnicodeError, LookupError):
        text = content.decode("gb18030", errors="replace")
    kind, rows, title, warnings = "", [], "", []
    lower = content_type.lower()
    if "json" in lower or url.split("?")[0].endswith(".json"):
        kind = "JSON"
        value = json.loads(text, parse_float=Decimal)
        if isinstance(value, dict):
            candidates = [v for v in value.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
            value = candidates[0] if len(candidates) == 1 else [value]
        if not isinstance(value, list):
            value = [{"值": value}]
        for i, item in enumerate(value[:MAX_ROWS]):
            data = item if isinstance(item, dict) else {"值": item}
            rows.append({"data": {str(k): clean(v) for k, v in data.items()}, "locator": f"json:row:{i}"})
    elif "csv" in lower or url.split("?")[0].endswith(".csv"):
        kind = "CSV"
        for i, row in enumerate(csv.DictReader(io.StringIO(text))):
            if i >= MAX_ROWS:
                warnings.append("已达到每个来源5000行的采集上限")
                break
            rows.append({"data": {str(k): clean(v) for k, v in row.items() if k is not None},
                         "locator": f"csv:line:{i + 2}"})
    elif "xml" in lower or url.split("?")[0].endswith(".xml"):
        kind = "XML"
        root = ElementTree.fromstring(text)
        for i, child in enumerate(list(root)[:MAX_ROWS]):
            data = {n.tag.split("}")[-1]: clean("".join(n.itertext()).strip()) for n in list(child)}
            if not data:
                data = {child.tag.split("}")[-1]: "".join(child.itertext()).strip()}
            rows.append({"data": data, "locator": f"xml:child:{i}"})
    elif "html" in lower or "<html" in text[:1000].lower() or "<table" in text[:1000].lower():
        kind = "HTML"
        parser = TableParser()
        parser.feed(text)
        title = " ".join(parser.title).strip()
        for table_index, table in enumerate(parser.tables):
            headers = unique_headers(table[0])
            for row_index, row in enumerate(table[1:], 2):
                data = {headers[i] if i < len(headers) else f"列{i+1}": value for i, value in enumerate(row)}
                rows.append({"data": data, "locator": f"html:table:{table_index+1}/row:{row_index}"})
                if len(rows) >= MAX_ROWS:
                    break
            if len(rows) >= MAX_ROWS:
                warnings.append("已达到每个来源5000行的采集上限")
                break
        if not rows:
            rows = [{"data": {"标题": title, "正文": "\n".join(parser.text)[:16000]}, "locator": "html:document"}]
            warnings.append("未检测到规则HTML表格，已保存标题与正文；动态渲染页面尚不支持")
        warnings.append("复杂合并单元格与多级表头需人工检查")
    else:
        raise AIError("unsupported_format", "本阶段支持静态HTML、JSON、CSV、XML；PDF/OCR及动态页面尚未接入")
    fields = list(dict.fromkeys(key for row in rows for key in row["data"]))
    if len(fields) > 100:
        raise AIError("too_many_fields", "来源超过100列，请拆分数据")
    return {"kind": kind, "title": title, "fields": fields, "rows": rows, "warnings": warnings}
