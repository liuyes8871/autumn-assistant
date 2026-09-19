from __future__ import annotations

"""Deterministic audience gate for the public humanities/social-science/business catalog.

The collector intentionally keeps this policy separate from source adapters. A
source adapter is responsible for finding and mapping a public campus job;
this module decides whether that job belongs in the current public audience.
It never calls an LLM and it does not infer eligibility from the employer's
industry.
"""

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Iterable

from .schema import RawJob


AUDIENCE_POLICY_VERSION = "humanities-social-business-v1"


class AudienceDecision(StrEnum):
    TARGET_GENERALIST = "TARGET_GENERALIST"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


@dataclass(frozen=True)
class AudienceAssessment:
    decision: AudienceDecision
    reason_codes: tuple[str, ...]
    matched_terms: tuple[str, ...] = ()

    @property
    def publishable(self) -> bool:
        return self.decision == AudienceDecision.TARGET_GENERALIST

    def as_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision.value,
            "reasonCodes": list(self.reason_codes),
            "matchedTerms": list(self.matched_terms),
        }


# These categories describe a specialized function even when a feed labels the
# specific position as "other". Data and product remain possible target
# categories; title/major checks below catch technical variants within them.
BLOCKED_ROLE_CATEGORIES = frozenset(
    {
        "软件研发",
        "算法/AI",
        "硬件/芯片",
        "技术",
        "生产制造/质量",
        "医药/研发",
        "法务/合规",
        "设计",
    }
)

GENERALIST_ROLE_CATEGORIES = frozenset(
    {
        "产品",
        "运营",
        "市场/品牌",
        "公关",
        "销售/商务",
        "供应链/采购/物流",
        "项目管理",
        "咨询",
        "金融/投研",
        "财务/审计",
        "人力资源",
        "游戏策划/发行",
        "职能综合",
        "销售、服务与支持",
        "营销与公关",
        "财务",
        "战略与投资",
    }
)

# A negative title signal wins over a broad function word such as 产品 or
# 运营. Keep this list focused on role nature, not ordinary tools such as
# Excel, SQL, Python or BI (which the product deliberately does not use as an
# automatic exclusion criterion).
BLOCKED_TITLE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"算法|机器学习|深度学习|大模型|人工智能|自然语言处理|计算机视觉|机器视觉|数据科学|数据科学家|数据工程|数据工程师|分析工程师|信息安全|网络安全|computer[- ]?science|computer[- ]?engineering|software[- ]?engineering|information[- ]?technology|electrical[- ]?engineering|electronic[- ]?engineering|mechanical[- ]?engineering|civil[- ]?engineering|materials?[- ]?engineering|chemical[- ]?engineering|machine[- ]?learning|deep[- ]?learning|artificial[- ]?intelligence|computer[- ]?vision|machine[- ]?vision|natural[- ]?language|data[- ]?science|data[- ]?scientist|data[- ]?engineering|information[- ]?security|network[- ]?security|large[- ]?language[- ]?models?|multimodal(?:ity)?|multi[- ]?modal|reinforcement[- ]?learning|world[- ]?model|speech[- ]?synthesis|video[- ]?generation|algorithm|(?<![a-z])AI(?![a-z])|(?<![a-z])NLP(?![a-z])|(?<![a-z])LLM(?:s)?(?![a-z])|(?<![a-z])ML(?![a-z])|(?<![a-z])RL(?![a-z])", "BLOCKED_TECHNICAL_ROLE"),
    (r"软件开发|系统开发|应用开发|平台开发|开发工程师|研发|后端|前端|客户端|安卓|Android|iOS|测试开发|测试工程师|软件测试|测试岗|运维|运维工程师|IT运维|DevOps|SRE|数据库管理员|数据库管理|系统管理员|网络管理员|网络工程师|云计算|云平台|平台运维|信息技术|系统架构|架构师|back[- ]?end|front[- ]?end|full[- ]?stack|softwaredevelopment|applicationdevelopment|platformdevelopment", "BLOCKED_TECHNICAL_ROLE"),
    (r"工程师|工程技术|工程研发|工程项目|工程管理|技术开发|技术研发|技术岗|技术专员|技术经理|嵌入式|芯片|硬件|电路|FPGA|结构工程|机械工程|电子工程|自动化工程|车辆工程|工艺工程|电网|电力|输电|变电|配电|电力建设|工程建设|系统设计|结构设计|电驱|动力系统|BMS|机器人|技术运营|技术产品|技术项目|技术支持|技术岗位|技术策划|工程研发|架构师|系统工程|engineer|developer|software|technical|embedded|systemdesign|structuraldesign|powertrain|datascientist|dataengineer|backend|frontend|fullstack|softwaredevelopment|applicationdevelopment|platformdevelopment|database(?:administrator|admin)?|databasemanager|it\s+operations?|itoperations?|researchanddevelopment|research\s*[&+]\s*development|research&development|r&d|engineeringresearch|engineresearch|researchscientist|modelresearcher|technicalresearch|codingllms?|agenticrl|cloudinfrastructure|infrastructureengineer|networkengineer|systems?administrator", "BLOCKED_TECHNICAL_ROLE"),
    (r"量化|精算|实验室|实验研究|科研|quantitative|actuary|scientist|laboratory|researchscientist", "BLOCKED_TECHNICAL_ROLE"),
    (r"医学|临床|药物研发|药理|药剂|医师|护士|clinical|medical|pharma|physician|nurse", "BLOCKED_LEGAL_OR_MEDICAL_ROLE"),
    (r"法务|律师|法律|合规|专利|legal|lawyer|compliance|patent", "BLOCKED_LEGAL_OR_MEDICAL_ROLE"),
    (r"制造工程|生产工艺|质量工程|工艺技术", "BLOCKED_TECHNICAL_ROLE"),
    (r"工业设计|建筑设计|建筑师|视觉设计|UI设计|UX设计|交互设计|产品设计|运营设计|品牌创意设计|设计师|设计岗|设计类|设计方向|美术|原画|插画|体育教练|industrialdesign|architect|visualdesigner|uidesigner|uxdesigner|designer|design", "BLOCKED_SPECIALIST_PORTFOLIO"),
)

# Professional families that are currently outside the target audience. The
# patterns are intentionally broad in order to cover common Chinese naming
# variants, but are only applied to hard requirement language below.
NON_TARGET_MAJOR_PATTERNS: tuple[str, ...] = (
    r"计算机(?:科学与技术|类|相关)?|理工科|工科|理科|工学|理学|computerscience|computerengineering|engineering",
    r"软件工程|softwareengineering",
    r"信息(?:与计算机|安全|工程)?|informationtechnology|informationengineering",
    r"电子(?:信息|工程)?|electricalengineering|electronicengineering",
    r"通信工程?|telecommunication",
    r"自动化",
    r"电气工程|电气",
    r"机械(?:工程)?|mechanicalengineering",
    r"车辆工程|汽车工程|automotiveengineering",
    r"材料(?:科学与工程|工程)?|materialsengineering",
    r"化学(?:工程|类)?|chemicalengineering",
    r"物理(?:学|类)?|physics",
    r"数学(?:与应用数学|类)?|mathematics",
    r"土木(?:工程)?|civilengineering",
    r"建筑(?:学|工程)?|architecture",
    r"测绘|surveying",
    r"能源(?:动力|工程)?|energyengineering",
    r"控制科学|控制工程|controlengineering",
    r"生物(?:工程|医学|科学)?|biologicalengineering|biology",
    r"医学|临床医学|药学|药物制剂|护理|medicine|clinicalmedicine|pharmacy|nursing",
    r"法学|法律|law",
    r"工业设计|艺术设计|视觉传达|产品设计|建筑设计|设计(?:学|类|专业)?|美术(?:学|类|专业)?|建筑(?:学|类|专业)?|industrialdesign|graphicdesign|design",
    r"体育教育|运动训练|体育(?:学|类|专业)?|sportseducation|sportstraining|sports?",
)

TARGET_MAJOR_PATTERNS: tuple[str, ...] = (
    r"文科|人文|中文|汉语言|历史|哲学|语言文学|外语|英语|日语|翻译|humanities|english|languages?",
    r"新闻传播|广告学|传播学|新闻学|公共关系|communications?|journalism|publicrelations|advertising",
    r"社会学|社会工作|心理学|政治学|公共管理|行政管理|教育学|社会科学|社科|socialsciences?|psychology|publicadministration|education",
    r"经济学|金融学|财务管理|会计学|审计学|工商管理|企业管理|市场营销|国际商务|电子商务|物流管理|供应链管理|经济管理|business|economics|finance|accounting|businessadministration|marketing|management",
    r"商科|管理类|经管类|不限专业|专业不限|无专业限制|anymajor|allmajors|nomajorrestriction",
)

HARD_REQUIREMENT_MARKERS = (
    "仅限",
    "限招",
    "限专业",
    "必须为",
    "须为",
    "要求专业",
    "专业要求",
    "相关专业",
    "专业背景",
    "本科专业为",
    "学历专业",
    "专业:",
    "专业：",
    "所学专业",
)

UNRESTRICTED_MAJOR_PATTERN = re.compile(
    r"不限专业|专业不限|无专业限制|any\s+major|all\s+majors?|no\s+major\s+restriction|open\s+to\s+all\s+majors?",
    re.IGNORECASE,
)

FORCED_PORTFOLIO_PATTERN = re.compile(
    r"(?:必须|须|要求|需要|需|提交|提供|附上|附带).{0,16}(?:作品集|portfolio)|(?:作品集|portfolio).{0,16}(?:必须|required|must|mandatory)",
    re.IGNORECASE,
)


def _major_context(sentence: str, match: re.Match[str]) -> bool:
    """Whether a major-name match is used as a qualification, not prose.

    Requirements often mention a product's technical domain (for example
    “计算机办公软件”) without restricting the applicant's major. A match is
    treated as a professional-major signal only when nearby text says
    专业/学历/背景 or an English equivalent, or when the sentence is itself a
    short structured major value.
    """

    compact = _compact(sentence)
    start, end = match.span()
    term_length = max(1, end - start)
    if term_length >= max(2, int(len(compact) * 0.45)):
        return True
    window = compact[max(0, start - 12) : min(len(compact), end + 20)]
    return bool(
        re.search(
            r"专业|相关|背景|学历|学位|本科|硕士|博士|major|degree|discipline|field|background|stud(?:y|ying)|graduate|require",
            window,
            re.IGNORECASE,
        )
    )

STRONG_HARD_REQUIREMENT_MARKERS = (
    "仅限",
    "限招",
    "限专业",
    "必须",
    "须为",
    "要求专业",
    "专业要求",
    "本科专业为",
    "学历专业",
    "required",
    "requires",
    "must",
    "mandatory",
    "needto",
)

SOFT_REQUIREMENT_MARKERS = (
    "优先",
    "加分",
    "优先考虑",
    "熟悉",
    "了解",
    "有经验者",
    "preferred",
    "preferably",
    "nicetohave",
    "aplus",
)

GENERALIST_TITLE_PATTERNS: tuple[str, ...] = (
    r"运营|用户增长|内容|社区|活动|市场|品牌|公关|媒介|商务|销售|客户成功|客户服务|operations?|marketing|brand|communications?|sales|businessdevelopment|customersuccess|customerservice|content|community",
    r"人力|招聘|培训|行政|综合管理|管培|管理培训|humanresources?|recruiting|talent|training|administration|managementtrainee",
    r"财务|会计|审计|税务|咨询|投研|投资|采购|供应链|物流|finance|accounting|audit|tax|consulting|investment|procurement|supplychain|logistics",
    r"产品经理|产品运营|项目管理|项目专员|游戏策划|发行|productmanager|productoperations?|projectmanagement|projectcoordinator|gameplanner|gameproducer",
)


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def _joined_text(job: RawJob) -> str:
    values: list[str] = [job.title, job.role_category, job.description]
    values.extend(job.requirements)
    values.extend(job.major_tags)
    return " ".join(value for value in values if value)


def _sentences(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        output.extend(part for part in re.split(r"[。；;\n.!！?？]", value or "") if part.strip())
    return output


def _hard_major_assessment(job: RawJob) -> tuple[str | None, tuple[str, ...], tuple[str, ...]]:
    """Return (decision, reason codes, matched terms) for hard major wording.

    A target major anywhere in the same hard-requirement sentence means the
    role remains available to the target audience. A technical major mentioned
    only as a preference is deliberately ignored.
    """

    non_target = [re.compile(pattern, re.IGNORECASE) for pattern in NON_TARGET_MAJOR_PATTERNS]
    target = [re.compile(pattern, re.IGNORECASE) for pattern in TARGET_MAJOR_PATTERNS]

    # ATS feeds often expose accepted majors as a structured array rather than
    # a sentence such as “专业要求：…”. Treat those values as requirements,
    # while still respecting a soft qualifier like “计算机专业优先”.
    structured_non_target: list[str] = []
    structured_target: list[str] = []
    for value in job.major_tags:
        compact = _compact(value)
        if any(marker in compact for marker in SOFT_REQUIREMENT_MARKERS) and not any(
            marker in compact for marker in STRONG_HARD_REQUIREMENT_MARKERS
        ):
            continue
        for pattern in non_target:
            match = pattern.search(compact)
            if match:
                structured_non_target.append(match.group(0))
        for pattern in target:
            match = pattern.search(compact)
            if match:
                structured_target.append(match.group(0))
    if structured_target:
        return "allow", ("ALLOWED_TARGET_MAJOR",), tuple(dict.fromkeys(structured_target))
    if structured_non_target:
        return "block", ("BLOCKED_NON_TARGET_MAJOR",), tuple(dict.fromkeys(structured_non_target))

    sentences = _sentences([*job.requirements, job.description])
    hard_seen = False
    blocked_terms: list[str] = []
    target_terms: list[str] = []
    for sentence in sentences:
        compact = _compact(sentence)
        raw_non_target_matches = [match for pattern in non_target for match in pattern.finditer(compact)]
        raw_target_matches = [match for pattern in target for match in pattern.finditer(compact)]
        contextual_non_target = [match for match in raw_non_target_matches if _major_context(compact, match)]
        contextual_target = [match for match in raw_target_matches if _major_context(compact, match)]
        # Once one recognized major is clearly in a qualification context,
        # treat the other majors in the same sentence as part of that list.
        # This preserves “计算机或市场营销相关专业” as an allow case while
        # leaving ordinary JD prose with no contextual match untouched.
        if contextual_non_target or contextual_target:
            non_target_matches = raw_non_target_matches
            target_matches = raw_target_matches
        else:
            non_target_matches = []
            target_matches = []
        unrestricted = UNRESTRICTED_MAJOR_PATTERN.search(sentence)
        has_hard_marker = any(marker in compact for marker in HARD_REQUIREMENT_MARKERS)
        # A short structured requirement such as “Computer Science” or
        # “计算机专业” may not contain a prefix like “要求”，but still carries
        # a major restriction. Conversely, prose such as “熟悉计算机办公软件”
        # is not treated as a major requirement because its match has no major
        # context.
        if not has_hard_marker and not unrestricted and not non_target_matches and not target_matches:
            continue
        # "优先" and similar language does not form a hard exclusion unless a
        # sentence also contains an explicit mandatory marker.
        if (
            not any(marker in compact for marker in STRONG_HARD_REQUIREMENT_MARKERS)
            and any(marker in compact for marker in SOFT_REQUIREMENT_MARKERS)
        ):
            continue
        hard_seen = True
        if unrestricted:
            target_terms.append("不限专业")
            continue
        blocked_terms.extend(match.group(0) for match in non_target_matches)
        target_terms.extend(match.group(0) for match in target_matches)

    if not hard_seen:
        return None, (), ()
    if target_terms:
        return "allow", ("ALLOWED_TARGET_MAJOR",), tuple(dict.fromkeys(target_terms))
    if blocked_terms:
        return "block", ("BLOCKED_NON_TARGET_MAJOR",), tuple(dict.fromkeys(blocked_terms))
    return None, (), ()


def assess_job(job: RawJob) -> AudienceAssessment:
    """Classify one normalized-or-raw job for public publication."""

    title_raw = (job.title or "").casefold()
    title = _compact(job.title)
    category = job.role_category.strip()

    if category in BLOCKED_ROLE_CATEGORIES:
        reason = "BLOCKED_SPECIALIST_PORTFOLIO" if category == "设计" else (
            "BLOCKED_LEGAL_OR_MEDICAL_ROLE" if category in {"医药/研发", "法务/合规"} else "BLOCKED_TECHNICAL_ROLE"
        )
        return AudienceAssessment(AudienceDecision.OUT_OF_SCOPE, (reason,), (category,))

    for pattern, reason in BLOCKED_TITLE_PATTERNS:
        match = re.search(pattern, title_raw, re.IGNORECASE) or re.search(pattern, title, re.IGNORECASE)
        if match:
            return AudienceAssessment(AudienceDecision.OUT_OF_SCOPE, (reason,), (match.group(0),))

    for sentence in _sentences([*job.requirements, job.description]):
        portfolio_match = FORCED_PORTFOLIO_PATTERN.search(sentence)
        # In finance and sales copy, “portfolio management” or “client
        # portfolio” refers to a book of business rather than a design
        # portfolio. Only the latter (or Chinese 作品集) is a specialist
        # submission requirement.
        portfolio_context = re.search(
            r"portfolio\s+(?:management|strategy|analytics|optimization)|(?:investment|client|sales|product)\s+portfolio",
            sentence,
            re.IGNORECASE,
        )
        if portfolio_match and not portfolio_context:
            return AudienceAssessment(
                AudienceDecision.OUT_OF_SCOPE,
                ("BLOCKED_SPECIALIST_PORTFOLIO",),
                (portfolio_match.group(0),),
            )

    major_decision, major_reasons, major_terms = _hard_major_assessment(job)
    if major_decision == "block":
        return AudienceAssessment(AudienceDecision.OUT_OF_SCOPE, major_reasons, major_terms)
    if major_decision == "allow":
        return AudienceAssessment(AudienceDecision.TARGET_GENERALIST, major_reasons, major_terms)

    # An explicit target/unrestricted major statement is useful evidence even
    # when it does not use one of the hard markers (for example a structured
    # ATS field that only says “专业不限”). Restrict this fallback to
    # requirements and structured major fields; ordinary JD prose can mention
    # “business” or “marketing” without describing an applicant's major.
    major_text = " ".join([*job.requirements, *job.major_tags])
    if UNRESTRICTED_MAJOR_PATTERN.search(major_text):
        return AudienceAssessment(AudienceDecision.TARGET_GENERALIST, ("ALLOWED_UNRESTRICTED_MAJOR",), ("不限专业",))
    for sentence in _sentences([*job.requirements, *job.major_tags]):
        target_matches = [
            match
            for pattern in (re.compile(value, re.IGNORECASE) for value in TARGET_MAJOR_PATTERNS)
            for match in pattern.finditer(_compact(sentence))
            if _major_context(_compact(sentence), match)
        ]
        if target_matches:
            return AudienceAssessment(
                AudienceDecision.TARGET_GENERALIST,
                ("ALLOWED_TARGET_MAJOR",),
                tuple(dict.fromkeys(match.group(0) for match in target_matches)),
            )

    if any(re.search(pattern, title, re.IGNORECASE) for pattern in GENERALIST_TITLE_PATTERNS):
        return AudienceAssessment(AudienceDecision.TARGET_GENERALIST, ("ALLOWED_GENERALIST_TITLE",), ())

    return AudienceAssessment(AudienceDecision.NEEDS_REVIEW, ("REVIEW_INSUFFICIENT_REQUIREMENTS",), ())


def is_publishable(job: RawJob) -> bool:
    return assess_job(job).publishable
