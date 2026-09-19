from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from urllib.parse import urlparse

from .schema import JobLocation, LocationScope, NormalizedJob, RawJob, SourceConfig


SOCIAL_TERMS = ("社招", "社会招聘", "experienced hire", "experienced", "senior hire")
CAMPUS_TERMS = ("校招", "校园招聘", "应届", "届毕业生", "campus", "graduate", "trainee", "管培")
DATE_RE = re.compile(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})")

MAINLAND_CITIES: dict[str, tuple[str, str, str]] = {
    "北京": ("CN", "BJ", "北京"), "上海": ("CN", "SH", "上海"), "天津": ("CN", "TJ", "天津"), "重庆": ("CN", "CQ", "重庆"),
    "武汉": ("CN", "HB", "武汉"), "广州": ("CN", "GD", "广州"), "深圳": ("CN", "GD", "深圳"), "东莞": ("CN", "GD", "东莞"),
    "佛山": ("CN", "GD", "佛山"), "珠海": ("CN", "GD", "珠海"), "杭州": ("CN", "ZJ", "杭州"), "宁波": ("CN", "ZJ", "宁波"),
    "南京": ("CN", "JS", "南京"), "苏州": ("CN", "JS", "苏州"), "合肥": ("CN", "AH", "合肥"), "成都": ("CN", "SC", "成都"),
    "西安": ("CN", "SN", "西安"), "郑州": ("CN", "HA", "郑州"), "长沙": ("CN", "HN", "长沙"), "青岛": ("CN", "SD", "青岛"),
    "济南": ("CN", "SD", "济南"), "厦门": ("CN", "FJ", "厦门"), "福州": ("CN", "FJ", "福州"), "沈阳": ("CN", "LN", "沈阳"),
    "大连": ("CN", "LN", "大连"), "哈尔滨": ("CN", "HLJ", "哈尔滨"), "南昌": ("CN", "JX", "南昌"), "昆明": ("CN", "YN", "昆明"),
}
PROVINCE_NAMES: dict[str, str] = {
    "北京": "BJ", "上海": "SH", "天津": "TJ", "重庆": "CQ", "湖北": "HB", "广东": "GD", "浙江": "ZJ", "江苏": "JS",
    "安徽": "AH", "四川": "SC", "陕西": "SN", "河南": "HA", "湖南": "HN", "山东": "SD", "福建": "FJ", "辽宁": "LN",
    "黑龙江": "HLJ", "江西": "JX", "云南": "YN", "河北": "HEB", "广西": "GX", "贵州": "GZ", "吉林": "JL", "山西": "SX",
    "内蒙古": "NMG", "新疆": "XJ", "甘肃": "GS", "海南": "HI", "宁夏": "NX", "青海": "QH", "西藏": "XZ",
}
MAINLAND_DISTRICTS: dict[str, tuple[str, str, str]] = {
    "嘉定区": ("SH", "上海", "嘉定区"), "浦东新区": ("SH", "上海", "浦东新区"), "黄浦区": ("SH", "上海", "黄浦区"),
    "海淀区": ("BJ", "北京", "海淀区"), "朝阳区": ("BJ", "北京", "朝阳区"), "天河区": ("GD", "广州", "天河区"),
    "南山区": ("GD", "深圳", "南山区"), "福田区": ("GD", "深圳", "福田区"), "洪山区": ("HB", "武汉", "洪山区"),
}
OVERSEAS_COUNTRIES: dict[str, tuple[str, str]] = {
    "新加坡": ("SG", "新加坡"), "东京": ("JP", "日本"), "日本": ("JP", "日本"), "首尔": ("KR", "韩国"), "韩国": ("KR", "韩国"),
    "吉隆坡": ("MY", "马来西亚"), "马来西亚": ("MY", "马来西亚"), "墨尔本": ("AU", "澳大利亚"), "悉尼": ("AU", "澳大利亚"),
    "巴黎": ("FR", "法国"), "伦敦": ("GB", "英国"), "美国": ("US", "美国"), "纽约": ("US", "美国"), "旧金山": ("US", "美国"),
}

PUBLIC_ROLE_CATEGORIES = frozenset({
    "软件研发", "算法/AI", "数据", "硬件/芯片", "产品", "运营", "市场/品牌", "公关",
    "销售/商务", "供应链/采购/物流", "项目管理", "咨询", "金融/投研", "财务/审计", "人力资源",
    "法务/合规", "设计", "游戏策划/发行", "生产制造/质量", "医药/研发", "职能综合", "其他",
})


def normalize_role_category(value: str) -> str:
    """Map source-specific function labels into the stable web taxonomy.

    Source feeds frequently use labels such as “战略与投资” or
    “销售、服务与支持”. Keeping those aliases in one deterministic mapper
    means the UI can offer the same filters for every adapter. Unknown labels
    intentionally fall back to ``其他``; the audience gate still checks the
    original title and requirements before publication.
    """

    text = clean_text(value or "", 80)
    if text in PUBLIC_ROLE_CATEGORIES:
        return text
    compact = re.sub(r"\s+", "", text).casefold()
    aliases = (
        (("算法", "机器学习", "大模型", "人工智能"), "算法/AI"),
        (("软件", "开发", "研发", "后端", "前端", "客户端", "测试开发", "工程师"), "软件研发"),
        (("芯片", "硬件", "电子", "射频", "嵌入式"), "硬件/芯片"),
        (("生产", "制造", "质量", "工艺"), "生产制造/质量"),
        (("医药", "临床", "药物"), "医药/研发"),
        (("法务", "法律", "合规", "专利"), "法务/合规"),
        (("设计", "美术", "建筑"), "设计"),
        (("市场", "品牌", "营销", "创意"), "市场/品牌"),
        (("公关", "媒介", "传播"), "公关"),
        (("销售", "商务", "客户成功", "客户服务", "服务与支持"), "销售/商务"),
        (("供应链", "采购", "物流", "采销", "仓储"), "供应链/采购/物流"),
        (("财务", "会计", "审计", "税务"), "财务/审计"),
        (("投资", "投研", "证券", "战略"), "金融/投研"),
        (("人力", "招聘", "人才", "hr"), "人力资源"),
        (("咨询",), "咨询"),
        (("项目管理", "项目经理"), "项目管理"),
        (("产品",), "产品"),
        (("运营", "增长", "内容", "社区"), "运营"),
        (("策划", "发行"), "游戏策划/发行"),
        (("管理培训", "管培", "综合", "职能"), "职能综合"),
        (("数据",), "数据"),
    )
    for words, category in aliases:
        if any(word.casefold() in compact for word in words):
            return category
    return "其他"


def host_matches(host: str, allowed_domain: str) -> bool:
    """Match an exact domain or its subdomain, never a substring lookalike."""

    normalized_host = host.lower().rstrip(".")
    normalized_allowed = allowed_domain.lower().strip().lstrip("*.").rstrip(".")
    return bool(normalized_host and normalized_allowed and (normalized_host == normalized_allowed or normalized_host.endswith("." + normalized_allowed)))


class PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "template", "svg"}:
            self._skip_depth += 1
        elif not self._skip_depth and tag.lower() in {"p", "li", "br", "div", "section", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "template", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        elif not self._skip_depth and tag.lower() in {"p", "li", "div", "section", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def clean_text(value: str, limit: int = 12_000) -> str:
    parser = PlainTextParser()
    parser.feed(value or "")
    text = re.sub(r"\s+", " ", "".join(parser.parts)).strip()
    return text[:limit]


def clean_list(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        item = clean_text(value, 600)
        if item and item not in output:
            output.append(item)
    return output[:40]


def normalize_city(value: str) -> str:
    city = clean_text(value, 50).replace("市", "")
    aliases = {"武汉市": "武汉", "上海市": "上海", "北京市": "北京", "深圳市": "深圳"}
    return aliases.get(city, city or "未知")


def normalize_locations(value: str, locations: list[JobLocation] | None = None) -> list[JobLocation]:
    """Normalize visible source locations without guessing unknown geography."""
    if locations:
        # Adapters may already provide a structured object, but its scope or
        # hierarchy is not trusted until the same deterministic dictionary has
        # seen the raw visible text. This keeps JSON and DOM adapters on one
        # normalization path while preserving an explicit source value when it
        # is more specific than the fallback parser.
        normalized: list[JobLocation] = []
        for item in locations:
            raw = item.raw or item.display_name
            parsed = normalize_locations(raw, None) if raw else []
            if parsed and item.scope == LocationScope.UNKNOWN:
                normalized.append(parsed[0])
                continue
            if parsed:
                base = parsed[0]
                normalized.append(item.model_copy(update={
                    "country_code": item.country_code or base.country_code,
                    "province_code": item.province_code or base.province_code,
                    "city_code": item.city_code or base.city_code,
                    "district_code": item.district_code or base.district_code,
                    "display_name": item.display_name or base.display_name,
                    "raw": item.raw or base.raw,
                }))
            else:
                normalized.append(item)
        unique: dict[tuple[str, str, str], JobLocation] = {}
        for item in normalized:
            unique[(item.scope.value, item.display_name, item.raw)] = item
        return list(unique.values())
    raw_values = [item for item in re.split(r"[、/,，;；|]", value or "") if item.strip()]
    output: list[JobLocation] = []
    for raw in raw_values or ["未知"]:
        text = clean_text(raw, 80).strip()
        compact = text.replace("市", "").strip()
        if any(token in compact.lower() for token in ("remote", "work from home", "远程", "居家")):
            output.append(JobLocation(scope=LocationScope.REMOTE, display_name="远程", raw=text))
            continue
        overseas = OVERSEAS_COUNTRIES.get(compact) or next((value for key, value in OVERSEAS_COUNTRIES.items() if key in compact), None)
        if overseas:
            country_code, country_name = overseas
            display = compact if compact != country_name else country_name
            output.append(JobLocation(scope=LocationScope.OVERSEAS, country_code=country_code, display_name=f"{country_name} · {display}", raw=text))
            continue
        hmt = {"香港": ("HK", "香港"), "澳门": ("MO", "澳门"), "台湾": ("TW", "台湾")}
        if compact in hmt:
            code, name = hmt[compact]
            output.append(JobLocation(scope=LocationScope.HONG_KONG_MACAU_TAIWAN, country_code=code, display_name=name, raw=text))
            continue
        district = next((value for name, value in MAINLAND_DISTRICTS.items() if name in compact), None)
        if district:
            province, city, district_name = district
            output.append(JobLocation(scope=LocationScope.MAINLAND_CHINA, country_code="CN", province_code=province, city_code=f"{province}-{city}", district_code=f"{province}-{district_name}", display_name=f"{city} · {district_name}", raw=text))
            continue
        city = normalize_city(compact)
        city_key = city.replace("区", "").replace("县", "")
        if city_key in MAINLAND_CITIES:
            country, province, canonical_city = MAINLAND_CITIES[city_key]
            output.append(JobLocation(scope=LocationScope.MAINLAND_CHINA, country_code=country, province_code=province, city_code=f"{province}-{canonical_city}", display_name=canonical_city, raw=text))
            continue
        province = next((code for name, code in PROVINCE_NAMES.items() if name in compact), None)
        if province:
            output.append(JobLocation(scope=LocationScope.MAINLAND_CHINA, country_code="CN", province_code=province, display_name=compact, raw=text))
            continue
        if compact in {"全国", "中国大陆", "大陆"}:
            output.append(JobLocation(scope=LocationScope.MAINLAND_CHINA, country_code="CN", display_name="全国", raw=text))
            continue
        output.append(JobLocation(scope=LocationScope.UNKNOWN, display_name=city or "未知", raw=text))
    unique: dict[tuple[str, str, str], JobLocation] = {}
    for location in output:
        unique[(location.scope.value, location.display_name, location.raw)] = location
    return list(unique.values())


def infer_campus(job: RawJob) -> bool:
    explicit_scope = " ".join([job.title, job.batch, job.cohort]).lower()
    if job.is_campus is False:
        return False
    # A reviewed ATS filter is stronger evidence than words such as
    # "experience" inside requirements. Explicit social-hire wording in the
    # title/scope still wins and is always rejected.
    if any(term in explicit_scope for term in SOCIAL_TERMS):
        return False
    if job.is_campus is True:
        return True
    haystack = " ".join(
        # The source registry is not evidence that every result is campus
        # hiring. Public portals often mix campus and experienced roles behind
        # the same endpoint, so only job-level fields may prove campus scope.
        [job.title, job.description, *job.requirements, job.batch, job.cohort]
    ).lower()
    if any(term in haystack for term in SOCIAL_TERMS):
        return False
    return any(term in haystack for term in CAMPUS_TERMS)


def stable_job_id(job: RawJob) -> str:
    if job.source_job_id:
        return f"{job.company_id}:{job.source_job_id.strip()}"
    canonical = "|".join(
        [job.company_id, job.title, normalize_city(job.city), job.cohort, job.apply_url.rstrip("/")]
    ).lower()
    return f"{job.company_id}:{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"


def content_hash(job: RawJob) -> str:
    text = "\n".join([job.title, clean_text(job.description), *clean_list(job.requirements), str(job.deadline or "")])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_job(job: RawJob, source: SourceConfig, now: datetime | None = None) -> NormalizedJob:
    now = now or datetime.now(UTC)
    if not infer_campus(job):
        raise ValueError(f"social_or_unverified_job:{job.title}")
    source_page = urlparse(str(job.source_url))
    reviewed_page = urlparse(str(source.source_url))
    source_host = (source_page.hostname or "").lower()
    reviewed_host = (reviewed_page.hostname or "").lower()
    if source_page.scheme != "https" or not source_host or not reviewed_host:
        raise ValueError(f"unverified_source_url:{job.source_url}")
    # A parser may expose a campaign/detail URL, but it must remain on the
    # reviewed company domain (or the separately reviewed ATS domain). This
    # prevents arbitrary third-party links from becoming public evidence.
    allowed_domains = [source.apply_domain, *source.apply_domains, *([source.ats_host] if source.ats_host else [])]
    if not (host_matches(source_host, reviewed_host) or any(host_matches(source_host, domain) for domain in allowed_domains)):
        raise ValueError(f"unverified_source_domain:{source_host}")
    apply_host = (urlparse(str(job.apply_url)).hostname or "").lower()
    # The official campaign page and the official ATS may use different
    # subdomains (for example join.qq.com → careers.tencent.com). Validate the
    # actual application destination against the reviewed allow-list instead of
    # requiring both URLs to share one host.
    apply_page = urlparse(str(job.apply_url))
    if apply_page.scheme != "https" or not any(host_matches(apply_host, domain) for domain in allowed_domains):
        raise ValueError(f"unverified_apply_domain:{apply_host}")
    payload = job.model_dump()
    payload.update(
        {
            "id": stable_job_id(job),
            "source_id": job.source_id or source.source_id,
            "city": normalize_city(job.city),
            "locations": normalize_locations(job.city, job.locations),
            "role_category": normalize_role_category(job.role_category),
            "description": clean_text(job.description),
            "requirements": clean_list(job.requirements),
            "major_tags": clean_list(job.major_tags),
            "skills": clean_list(job.skills),
            "source_level": source.source_level,
            "first_seen_at": now,
            "last_verified_at": now,
            "content_hash": content_hash(job),
        }
    )
    return NormalizedJob(**payload)
