"""标题门:哪些列表项值得抓。

2026-09-07 起国家级用文体门,其余用能源关键词门——理由见 step2_scan.DOC_FORMS。
"""
from scripts.l1_collect.channel_catalog import Channel, ChannelStatus
from scripts.l1_collect.step2_scan import _title_gate

# 发改委意见征求页 2026-09-04 的真实条目
SHOUDIAN = "国家发展改革委关于向社会公开征求《售电公司管理办法（公开征求意见稿）》意见的公告"


def _ch(level: str) -> Channel:
    return Channel(city="X", province="Y", level=level, city_code="000000",
                   channel_type="发改委", root_domain="ndrc.gov.cn",
                   list_url="https://example.gov.cn/l", source="manual",
                   status=ChannelStatus.验证)


def test_售电公司管理办法能过国家级门():
    assert _title_gate(SHOUDIAN, _ch("国家")) is True


def test_国家级按文体收_不含能源词也放行():
    """部委文件名经常一个能源词都没有;按能源词收等于把最该收的挡在门外。"""
    assert _title_gate("关于印发《输配电定价成本监审办法》的通知", _ch("国家")) is True
    assert _title_gate("关于更高水平更高质量做好节能降碳工作的意见", _ch("国家")) is True


def test_国家级仍然挡掉导航与页脚():
    """免关键词不等于不设门,否则导航栏会被当成条目抓取。"""
    for junk in ("国家发展和改革委员会", "关于我们联系方式", "网站地图无障碍浏览"):
        assert _title_gate(junk, _ch("国家")) is False


def test_市级仍走关键词门():
    """市级条目多、噪音大,继续靠能源词收窄以控成本。"""
    assert _title_gate("关于印发人民防空工程建设管理规定的通知", _ch("市")) is False
    assert _title_gate("关于调整我市峰谷分时电价政策的通知", _ch("市")) is True


def test_补进关键词表的盲词生效():
    """这几个词是拿「解读文章反查库存」量出来的:命中它们的政策此前会被静默丢掉。"""
    for t in ("关于印发售电公司管理办法的通知",
              "关于做好2026年全国碳排放权交易市场有关工作的通知",
              "关于开展重点行业节能降碳改造攻坚三年行动的通知"):
        assert _title_gate(t, _ch("市")) is True, t
