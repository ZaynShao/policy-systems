"""Step 2: 渠道扫描。

输入:channel_catalog status=验证 + 该 batch 的 cities
输出:state/T1_scan_raw/<city>__<channel_type>__<root_domain>.jsonl

⚠ ScanRow 含 city + city_code(原 plan review 标记的修复:让 city info 沿
Step 2→5 流水线透传,避免 Step 5 ingester id 标错 issuer_short)。
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from html import escape
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

from .channel_catalog import Channel, ChannelStatus, channel_label
# 与 probe 共用同一个 UA:实测 miit/samr 按 UA 拦(ZCE-Scan → 403,ZCE-Probe → 200),
# 两端不一致会造出「probe 说 ok、scan 一行扫不到」的静默失联渠道。
from .connectivity_probe import UA

TIMEOUT = 20
MAX_PAGES = 10
NEW_RATIO_THRESHOLD = 0.10
CST = timezone(timedelta(hours=8))

KEYWORDS = (
    "能源", "电力", "电网", "油气", "成品油", "充电", "储能",
    "新能源", "双碳", "光伏", "风电", "氢能", "天然气", "汽车以旧换新",
    "新型电力", "虚拟电厂", "需求响应", "碳达峰", "碳中和",
    # 召回偏向补漏(L1体检暴露的盲词)
    "换电", "现货市场", "绿证", "绿电", "车网互动", "V2G",
    "配电网", "分布式", "加氢", "抽水蓄能", "需求侧", "电价",
    # 加油线(商务厅):成品油零售/加油站
    "加油站", "成品油零售", "油品经营", "加油", "燃油",
    # 市场监管/平台(市监局·企业背景):
    "平台经济", "反垄断", "反不正当竞争", "市场监管", "网络交易",
    "互联网平台", "经营者集中", "公平竞争审查", "价格监管",
    # 跨条线机关(税务/央行/市监/交通):对齐业务战略画像信号
    # F02 消费税稽查与发票票据 / F05 预付卡·加油卡·电子券·第三方支付 /
    # F03 站点经营与计量合规 / 油品与危化品运输
    "消费税", "发票", "开票", "税收征管", "涉税",
    "预付卡", "储值卡", "加油卡", "电子券",
    "支付机构", "非银行支付", "第三方支付",
    "成品油经营", "油品质量", "计量器具", "危险化学品", "危险货物运输",
    # 2026-09-07 补:用「解读文章反查库存」量出来的盲词。65 篇被反复引用却没采到的
    # 能源政策里,10 篇标题一个关键词都不命中——《售电公司管理办法》《关于更高水平
    # 更高质量做好节能降碳工作的意见》《输配电定价成本监审办法》都栽在这儿。
    "售电", "购电", "输配电", "用电", "电能", "发电",
    "降碳", "碳市场", "碳排放", "零碳", "低碳",
)

#: 国家级列表页改用「文体门」:标题像不像一份公文。
#:
#: 关键词门是给市级用的——那边条目多、噪音大,得靠能源词收窄。国家部委正相反:
#: 发文量小、单件价值高,而部委的文件名经常不带任何能源词(《售电公司管理办法》
#: 一个都不含),按能源词收等于把最该收的挡在门外。按「是不是公文」收更贴合。
#: 仍然要有门,否则导航栏、页脚、友情链接会被当成条目抓取。
DOC_FORMS = (
    "办法", "规定", "意见", "通知", "公告", "方案", "规划", "细则",
    "条例", "指南", "规则", "决定", "批复", "征求", "公示", "标准",
)

_DATE_RE = re.compile(r"((?:19|20)\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")


@dataclass
class ScanRow:
    title: str
    url: str
    date_hint: str
    source_channel: str    # root_domain
    city: str              # 透传:Step 5 ingester id 用
    city_code: str
    province: str
    channel_type: str
    scanned_at: str


LIST_MIN_TEXT = 500   # BS4 文本短于此视为空壳/JS页 → firecrawl 兜底
FIRECRAWL_WAIT_MS = 4000  # 兜底时等 JS 渲染完的毫秒数
#: 数据源 JSON 单次回 1000 条(能源局实测),按发布时间倒序。日增量只需要头部若干条,
#: 全量放行会让接上渠道的**第一晚**去抓上千篇历史件、每篇还要过一次 LLM 文体门,
#: 足以撑爆当晚的时间与成本预算。补历史应当是一次有意的回填,不是 cron 的副作用。
DATASOURCE_MAX_ITEMS = 120


def _bs4_get(url: str) -> str:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        if r.status_code >= 400:
            return ""
        # 政府站常发 GBK/GB2312 或谎报 charset,HTTP 头无/错 charset → requests 默认
        # ISO-8859-1 解码成乱码 → 标题全乱 → KEYWORD 匹配失败 → scan=0。头未明确指定
        # 时用 chardet 探测(apparent_encoding)纠正中文编码。
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding or r.encoding
        return r.text or ""
    except Exception:
        return ""


def _firecrawl_get_html(url: str) -> str:
    import os
    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        return ""
    try:
        resp = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            # waitFor:兜底的对象就是"HTML 里没有条目、条目由 JS 填"的页面,不等渲染
            # 等于把空壳原样拿回来。2026-09-07 实测国家能源局 policy/zxwj.htm:
            # 不等 → 1958 字 7 链接 0 条目(Vue 挂载前的骨架),整条能源局口子因此空转。
            json={"url": url, "formats": ["html"], "waitFor": FIRECRAWL_WAIT_MS},
            headers={"Authorization": f"Bearer {key}"}, timeout=60,
        )
        if resp.status_code != 200:
            return ""
        d = resp.json().get("data") or {}
        return d.get("html") or d.get("rawHtml") or ""
    except Exception:
        return ""


#: 新华云 CMS 列表页的数据源标记。容器上挂 data="datasource:<id>" datatype="ds",
#: 条目由 JS 从同目录的 <preview><id>.json 拉回来填进去。
_DS_ID_RE = re.compile(r"datasource:([0-9A-Za-z]{16,40})")


def _xinhua_datasource_html(page_url: str, html: str) -> str:
    """新华云 CMS 空壳页 → 直接取它的 JSON 数据源,拼回最小 HTML。

    国家能源局的 policy/zxwj.htm、tz.htm、gg.htm 都是这种页:HTML 里只有一个空
    <ul id="showData0">,条目全靠 JS 填。firecrawl 也渲不出来——2026-09-07 实测
    带 waitFor 4 秒拿回来的仍是挂载前的骨架(1958 字、7 个链接、0 条目),
    于是国家能源局整条口子空转。

    但那个 JSON 是同目录下的**静态文件**,直接取更稳也更全:单次 1000 条、带
    publishTime。取回后拼成最小 HTML 交回主流程,下游的标题门、日期解析、
    去重、翻页判定全部不用改。

    URL 规则出自页面加载器 nyjcb_dw_es5_2023.js:
        sourceUrl = "./" + preview + datasource + ".json"
    """
    soup = BeautifulSoup(html, "html.parser")
    seeds = []
    for el in soup.find_all(attrs={"datatype": "ds"}):
        # <a> 上的 datasource 是导航项(如"首页"),不是列表数据
        if el.name == "a":
            continue
        m = _DS_ID_RE.search(el.get("data") or "")
        if m:
            seeds.append((m.group(1), el.get("preview") or "ds_"))
    parts = []
    seen = set()
    for ds_id, preview in seeds[:3]:
        try:
            r = requests.get(urljoin(page_url, f"./{preview}{ds_id}.json"),
                             headers={"User-Agent": UA}, timeout=TIMEOUT)
            if r.status_code >= 400:
                continue
            items = ((r.json() or {}).get("datasource") or [])[:DATASOURCE_MAX_ITEMS]
        except Exception:
            continue
        for it in items:
            href = (it.get("publishUrl") or "").strip()
            if not href:
                continue
            link = urljoin(page_url, href)
            if link in seen:
                continue
            seen.add(link)
            # showTitle 里可能嵌着整个 <a> 标签(CMS 的 Link 型条目),剥干净再用
            title = BeautifulSoup(it.get("showTitle") or it.get("title") or "",
                                  "html.parser").get_text(strip=True)
            if not title:
                continue
            date = (it.get("publishTime") or "")[:10]
            parts.append(
                f"<li><a href=\"{escape(link, quote=True)}\">{escape(title)}</a>"
                f"<span>{escape(date)}</span></li>"
            )
    if not parts:
        return ""
    return "<html><body><ul>" + "".join(parts) + "</ul></body></html>"


def _fetch_list_html(url: str) -> str:
    """分层:BS4 免费先试;空壳 → 数据源 JSON;再不行 → firecrawl 渲染兜底。

    数据源排在 firecrawl 前面:它免费、更全(1000 条 vs 一页),而且 firecrawl
    对这类页本来就渲不出来。
    """
    html = _bs4_get(url)
    soup = BeautifulSoup(html, "html.parser") if html else None
    text_len = len(soup.get_text(strip=True)) if soup else 0
    if text_len >= LIST_MIN_TEXT:
        return html
    if html:
        ds = _xinhua_datasource_html(url, html)
        if ds:
            return ds
    fc = _firecrawl_get_html(url)
    return fc or html


def _page_urls(list_url: str, max_pages: int = MAX_PAGES) -> list:
    """政府站常见翻页:index.html / index_1.html / index_2.html ... + ?page= 兜底。"""
    urls = [list_url]
    if list_url.endswith("index.html"):
        base = list_url[: -len("index.html")]
        for n in range(1, max_pages):
            urls.append(f"{base}index_{n}.html")
    else:
        for n in range(2, max_pages + 1):
            sep = "&" if "?" in list_url else "?"
            urls.append(f"{list_url}{sep}page={n}")
    return urls


def _title_gate(title: str, ch: Channel) -> bool:
    """这条链接的标题值不值得抓。国家级看文体,其余看能源关键词(理由见 DOC_FORMS)。"""
    if ch.level == "国家":
        return any(f in title for f in DOC_FORMS) or any(kw in title for kw in KEYWORDS)
    return any(kw in title for kw in KEYWORDS)


def _extract_list_items(html: str, base_url: str, ch: Channel) -> list[ScanRow]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[ScanRow] = []
    now = datetime.now(CST).isoformat(timespec="seconds")
    seen_urls: set = set()
    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or len(title) > 200:
            continue
        if not _title_gate(title, ch):
            continue
        href = a["href"]
        if href.startswith("javascript:") or href.startswith("#") or href.startswith("mailto:"):
            continue
        url = urljoin(base_url, href)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        ctx = (a.parent.get_text(" ", strip=True) if a.parent else "")[:200]
        m = _DATE_RE.search(ctx)
        date_hint = ""
        if m:
            y, mo, d = m.groups()
            try:
                date_hint = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
            except Exception:
                pass
        rows.append(ScanRow(
            title=title, url=url, date_hint=date_hint,
            source_channel=ch.root_domain,
            city=ch.city, city_code=ch.city_code,
            province=ch.province, channel_type=ch.channel_type,
            scanned_at=now,
        ))
    return rows


def scan_channel(ch: Channel, out_dir: Path) -> int:
    """扫单渠道,翻页直至 max_pages 或新增比 < threshold。返回入库行数。"""
    if ch.status != ChannelStatus.验证:
        return 0
    all_rows: list[ScanRow] = []
    seen_urls: set = set()
    for page_url in _page_urls(ch.list_url):
        html = _fetch_list_html(page_url)
        if not html:
            break
        rows = _extract_list_items(html, page_url, ch)
        new_rows = [x for x in rows if x.url not in seen_urls]
        for x in new_rows:
            seen_urls.add(x.url)
        all_rows.extend(new_rows)
        if rows and (len(new_rows) / max(1, len(rows))) < NEW_RATIO_THRESHOLD:
            break

    out_dir.mkdir(parents=True, exist_ok=True)
    fn = out_dir / f"{channel_label(ch)}.jsonl"
    fn.write_text(
        "\n".join(json.dumps(asdict(x), ensure_ascii=False) for x in all_rows),
        encoding="utf-8",
    )
    return len(all_rows)
