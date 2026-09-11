"""将 v2 案例事实组装为可验证的真实合同结构。"""
from __future__ import annotations

from dataclasses import dataclass

from .clauses import SCENARIO_TOPICS, STYLE_HEADINGS, STYLE_PARAGRAPHS
from .models import ContractCase


@dataclass(frozen=True)
class ContractSection:
    heading: str
    paragraphs: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...] = ()

    def as_text(self) -> str:
        return "\n".join((self.heading, *self.paragraphs, *("｜".join(row) for row in self.rows)))


@dataclass(frozen=True)
class ContractDocument:
    case_id: str
    title: str
    target_pages: int
    header_lines: tuple[str, ...]
    sections: tuple[ContractSection, ...]
    annexes: tuple[ContractSection, ...]

    @property
    def plain_text(self) -> str:
        return "\n".join((
            self.title,
            *self.header_lines,
            *(section.as_text() for section in (*self.sections, *self.annexes)),
        ))


def _party_section(case: ContractCase) -> ContractSection:
    return ContractSection(
        "签约主体",
        ("各方确认具有签署和履行本合同所需的主体资格及内部授权。",),
        tuple((case.primary_roles[index], party, "统一社会信用代码：合成样本不适用") for index, party in enumerate(case.parties)),
    )


def _commercial_sections(case: ContractCase) -> tuple[ContractSection, ...]:
    truth = case.truth
    payments = tuple((f"第{index}项", value) for index, value in enumerate(truth["payment_terms"], start=1))
    return (
        ContractSection("交易标的", (str(truth["subject"]),)),
        ContractSection("价款或计价", (str(truth["amount"] or "按有效订单、工单或实际使用量据实结算，不预设固定总额。"),)),
        ContractSection("履行期间", (str(truth["duration"] or "由后续有效订单或书面任务书确定。"),)),
        ContractSection("支付安排", ("付款以对应交付、验收、对账及合法发票条件成就为前提。",), payments),
    )


def _style_sections(case: ContractCase) -> tuple[ContractSection, ...]:
    paragraph = STYLE_PARAGRAPHS[case.drafting_style]
    return tuple(
        ContractSection(heading, (f"{paragraph} 本节针对{case.title}的{heading}作出约定。",))
        for heading in STYLE_HEADINGS[case.drafting_style]
    )


def _risk_sections(case: ContractCase) -> tuple[ContractSection, ...]:
    return tuple(
        ContractSection(
            f"特别约定 {risk.clause_id}",
            (risk.text,),
        )
        for risk in case.risk_clauses
    )


def _conflict_sections(case: ContractCase) -> tuple[ContractSection, ...]:
    sections = []
    for index, conflict in enumerate(case.conflicts, start=1):
        sections.extend((
            ContractSection(conflict.source_a, (conflict.text_a,)),
            ContractSection(conflict.source_b, (conflict.text_b, conflict.precedence_rule)),
        ))
    return tuple(sections)


def _business_annexes(case: ContractCase) -> tuple[ContractSection, ...]:
    annexes = [
        ContractSection(
            f"附件{index}：{annex.name}（{annex.version}）",
            (f"本附件用于细化{case.truth['subject']}的业务数据和交付口径。",),
            annex.rows,
        )
        for index, annex in enumerate(case.annexes, start=1)
    ]
    topics = SCENARIO_TOPICS[case.scenario]
    required_blocks = max(0, case.target_pages - 1 - (10 + len(annexes) + len(case.risk_clauses) + 2 * len(case.conflicts)))
    for offset in range(required_blocks):
        topic = topics[offset % len(topics)]
        annexes.append(ContractSection(
            f"业务附件：{topic}记录{offset + 1}",
            (f"围绕{case.title}的{topic}，双方按本表记录计划、实际完成情况及差异原因。",),
            (("记录项目", "责任方", "业务凭证"), (topic, case.primary_roles[offset % len(case.primary_roles)], f"{case.case_id}-{topic}-{offset + 1}")),
        ))
    return tuple(annexes)


def build_contract(case: ContractCase) -> ContractDocument:
    revision = case.revision_set
    revision_section = () if revision is None else (
        ContractSection("法务修订条款", (revision.deleted_text,)),
    )
    sections = (
        *_style_sections(case),
        _party_section(case),
        *_commercial_sections(case),
        *_risk_sections(case),
        *_conflict_sections(case),
        *revision_section,
        ContractSection("违约与救济", ("违约方应采取补救措施，并赔偿其违约行为直接造成且能够合理证明的损失。",)),
        ContractSection("签署", tuple(f"{case.primary_roles[index]}：{party}　授权代表：________" for index, party in enumerate(case.parties))),
    )
    return ContractDocument(
        case_id=case.case_id,
        title=case.title,
        target_pages=case.target_pages,
        header_lines=("合成测试样本，仅用于系统验收", f"案例编号：{case.case_id}", f"文本状态：{case.document_state}"),
        sections=sections,
        annexes=_business_annexes(case),
    )
