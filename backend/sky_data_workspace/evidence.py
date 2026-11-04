import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation, localcontext
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ollama_client import AIError


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EvidenceCell(StrictModel):
    cell_id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    raw_value: str = Field(max_length=200)
    unit: str | None = Field(default=None, max_length=20)
    period: str | None = Field(default=None, max_length=40)
    reporting_scope: str | None = Field(default=None, max_length=40)
    locator: str = Field(min_length=1, max_length=200)


class FieldSpec(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=12)
    kind: Literal["decimal", "text", "integer", "percentage"] = "decimal"
    target_unit: str | None = Field(default=None, max_length=20)
    period: str | None = Field(default=None, max_length=40)
    reporting_scope: str | None = Field(default=None, max_length=40)


class MappingRequest(StrictModel):
    source_id: str = Field(min_length=1, max_length=80)
    source_url: str = Field(min_length=1, max_length=2048)
    cells: list[EvidenceCell] = Field(min_length=1, max_length=100)
    fields: list[FieldSpec] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({c.cell_id for c in self.cells}) != len(self.cells):
            raise ValueError("证据 cell_id 重复")
        if len({f.name for f in self.fields}) != len(self.fields):
            raise ValueError("字段名称重复")
        return self

    def document_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"fields"})
        content = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


class FieldAssignment(StrictModel):
    field_name: str
    cell_id: str | None
    reason: str = Field(max_length=300)


class MappingProposal(StrictModel):
    assignments: list[FieldAssignment] = Field(max_length=20)


class CellSelections(StrictModel):
    selections: dict[str, str | None] = Field(max_length=20)


def selection_schema(request: MappingRequest) -> dict:
    """固定全部目标键和可选证据 ID，缺失值仍必须显式填写 null。"""
    schema = CellSelections.model_json_schema()
    schema["properties"]["selections"] = {
        "type": "object",
        "properties": {
            field.name: {
                "type": ["string", "null"],
                "enum": [c.cell_id for c in request.cells if compatible(field, c)] + [None],
            } for field in request.fields
        },
        "required": [field.name for field in request.fields],
        "additionalProperties": False,
    }
    return schema


def parse_decimal(raw: str) -> Decimal:
    """严格解析原文；不使用 float，不猜测省略的数字或单位。"""
    text = unicodedata.normalize("NFKC", raw).strip().replace("−", "-")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
        if text.startswith(("+", "-")):
            raise ValueError("括号与正负号含义冲突")
    text = re.sub(r"^[¥￥]", "", text).strip()
    if len(text) > 64 or not re.fullmatch(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", text):
        raise ValueError("原始数值格式不明确")
    try:
        number = Decimal(text.replace(",", ""))
        if negative:
            number = number.copy_negate()
        return number
    except InvalidOperation as exc:
        raise ValueError("原始数值无效") from exc


def compatible(field: FieldSpec, cell: EvidenceCell) -> bool:
    return ((not field.period or field.period == cell.period)
            and (not field.reporting_scope or field.reporting_scope == cell.reporting_scope))


def rule_proposal(request: MappingRequest) -> MappingProposal:
    assignments = []
    for field in request.fields:
        names = {field.label, *field.aliases}
        matches = [c for c in request.cells if c.label in names and compatible(field, c)]
        assignments.append(FieldAssignment(
            field_name=field.name, cell_id=matches[0].cell_id if len(matches) == 1 else None,
            reason="唯一精确字段与口径匹配" if len(matches) == 1 else "缺失或候选冲突",
        ))
    return MappingProposal(assignments=assignments)


def validate_mapping(request: MappingRequest, proposal: MappingProposal) -> list[dict]:
    """模型只能选择已存在的单元格；数值、来源及定位均由宿主生成。"""
    expected = {f.name for f in request.fields}
    assigned = [a.field_name for a in proposal.assignments]
    if len(set(assigned)) != len(assigned) or set(assigned) != expected:
        raise AIError("invalid_mapping", "字段映射存在遗漏、重复或未知字段")
    cells = {c.cell_id: c for c in request.cells}
    assignments = {a.field_name: a for a in proposal.assignments}
    digest, records = request.document_hash(), []
    factors = {"元": Decimal(1), "千元": Decimal(1000), "万元": Decimal(10000), "亿元": Decimal(100000000)}
    for field in request.fields:
        assignment = assignments[field.name]
        if assignment.cell_id is not None and assignment.cell_id not in cells:
            raise AIError("fabricated_evidence", "模型引用了来源中不存在的单元格")
        cell = cells.get(assignment.cell_id)
        row = {
            "field_name": field.name, "value": None, "original_value": cell.raw_value if cell else None,
            "source_id": request.source_id, "source_url": request.source_url, "document_hash": digest,
            "hash_basis": "registered_evidence_payload",
            "evidence_locator": cell.locator if cell else None, "cell_id": cell.cell_id if cell else None,
            "unit": cell.unit if cell else None, "period": cell.period if cell else None,
            "reporting_scope": cell.reporting_scope if cell else None,
            "validation_status": "missing", "review_status": "pending", "notes": [],
        }
        if cell is None:
            row["notes"].append("来源中缺失或有多个冲突候选")
        elif not compatible(field, cell):
            row["validation_status"] = "needs_review"
            row["notes"].append("报告期或报表口径不匹配")
        else:
            # 没有精确定义的别名，或多个同口径候选，都不允许自动验证。
            labels = {field.label, *field.aliases}
            duplicates = [c for c in request.cells if c.label in labels and compatible(field, c)]
            label_proven = cell.label in labels and len(duplicates) == 1
            try:
                if field.kind == "text":
                    value = cell.raw_value or None
                else:
                    raw = cell.raw_value.strip()
                    is_percent = field.kind == "percentage" and raw.endswith(("%", "％"))
                    if field.kind == "percentage" and not is_percent and cell.unit != "%":
                        raise ValueError("百分比单位不明确")
                    number = parse_decimal(raw[:-1] if is_percent else raw)
                    with localcontext() as context:
                        context.prec = 80
                        if is_percent or (field.kind == "percentage" and cell.unit == "%"):
                            number /= Decimal(100)
                        if field.target_unit:
                            if cell.unit not in factors or field.target_unit not in factors:
                                raise ValueError("单位不明确，不能自动换算")
                            number = number * factors[cell.unit] / factors[field.target_unit]
                            row["unit"] = field.target_unit
                    if field.kind == "integer" and number != number.to_integral_value():
                        raise ValueError("数值不是整数")
                    value = format(number, "f")
                row["value"] = value
                row["validation_status"] = "rule_verified" if label_proven and value is not None else "needs_review"
                if not label_proven:
                    row["notes"].append("模型语义映射或冲突候选需要人工审核")
            except ValueError as exc:
                row["validation_status"] = "needs_review"
                row["notes"].append(str(exc))
        records.append(row)
    return records
