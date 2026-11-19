import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "portal" / "industry-board"


class PolicyPredictIndustryBoardTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "portal" / "policy-predict.html").read_text(encoding="utf-8")

    def test_sidebar_tab_follows_mobility_and_is_not_internal_only(self):
        links = re.findall(r'<button class="side-link[^"]*" type="button" data-view="([^"]+)"([^>]*)>', self.html)
        views = [view for view, _ in links]
        self.assertIn("industryBoard", views)
        self.assertEqual(views.index("industryBoard"), views.index("mobility") + 1)
        attrs = dict(links)["industryBoard"]
        self.assertNotIn("data-policy-internal", attrs, "行业预判板面向 policy_predict.view 用户，不是内部管理页")

    def test_view_is_whitelisted_and_has_its_section(self):
        self.assertIn('<section class="module-view" id="industryBoardModule">', self.html)
        self.assertRegex(self.html, r"var valid = \{[^}]*industryBoard:true")
        self.assertNotIn('<section class="module-view active" id="industryBoardModule">', self.html)

    def test_iframe_is_lazy_like_training_and_reports_height_with_prefixed_type(self):
        match = re.search(r'<iframe id="industryBoardFrame"[^>]*>', self.html, flags=re.S)
        self.assertIsNotNone(match)
        self.assertNotIn(" src=", match.group(0), "src 必须懒加载，data.js 约 900 KB")
        self.assertIn("boardFrame.setAttribute('src', '/industry-board/index.html?embed=1')", self.html)
        self.assertIn("data.type === 'policy-embed:industry-board-height'", self.html)
        self.assertIn("ev.source === boardFrame.contentWindow", self.html)

    def test_board_page_is_a_full_document_with_embed_mode(self):
        html = (BOARD / "index.html").read_text(encoding="utf-8")
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn('<meta name="viewport"', html)
        self.assertRegex(html, r'<script src="\./data\.js\?v=\d+"></script>')
        self.assertIn(".page.embedded .policy-tab-bar{display:none}", html)
        self.assertIn("policy-embed:industry-board-height", html)
        for word in ["阳光厨房", "采买", "分拣", "备料", "掌勺", "出餐", "mock", "演示", "示例", "deepseek"]:
            self.assertNotIn(word, html)

    def test_data_bundle_covers_19_industries_with_frozen_t0(self):
        data = (BOARD / "data.js").read_text(encoding="utf-8")
        meta = json.loads(re.search(r"window\.BOARD_META=(\{.*?\});\n", data).group(1))
        rows = json.loads(re.search(r"window\.INDUSTRY_DATA=(\[.*\]);\n", data, re.S).group(1))
        self.assertTrue(meta["validated"])
        self.assertEqual(meta["missing"], [])
        self.assertEqual(len(rows), 19)
        self.assertEqual({row["id"] for row in rows}, set(meta["order"]))
        self.assertEqual({row["t0"] for row in rows}, {"2026-09-14"})
        for row in rows:
            self.assertEqual(row["process"]["kind"], "analyst_record")
            for node in row["timeline"]:
                self.assertNotEqual(node["tier"], "S5")
                if not node.get("pending"):
                    self.assertTrue(node["url"].startswith("http"), f"{row['id']} {node['id']} 缺 URL")


if __name__ == "__main__":
    unittest.main()
