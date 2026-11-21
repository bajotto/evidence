from __future__ import annotations

import re
import unittest
from pathlib import Path

from method.service.markdown_view import render

ROOT = Path(__file__).resolve().parents[2]


class MarkdownTests(unittest.TestCase):
    def test_everything_is_escaped_so_html_in_a_protocol_cannot_inject(self):
        hostile = ("# Title <script>alert(1)</script>\n\n<img src=x onerror=alert(1)> text\n\n"
                   "| a | <b>b</b> |\n|---|---|\n| <i>1</i> | `<u>2</u>` |\n\n```\n<script>alert(2)</script>\n```\n\n"
                   "- <svg onload=alert(3)>\n> <iframe src=javascript:alert(4)>\n")
        html = render(hostile)
        for raw in ("<script", "<img", "<svg", "<iframe", "<b>", "<i>", "<u>"):
            self.assertNotIn(raw, html, raw)
        self.assertIn("&lt;script&gt;", html)

    def test_only_safe_link_schemes_become_links(self):
        html = render("[ok](https://example.test/a?x=1&y=2) [mail](mailto:a@b.test) [jump](#phase-4) "
                      "[bad](javascript:alert(1)) [data](data:text/html;base64,AAA) [quote](https://x.test/\"onmouseover=\"y)")
        self.assertIn("<a href='https://example.test/a?x=1&amp;y=2' target='_blank' rel='noopener noreferrer'>ok</a>", html)
        self.assertIn("<a href='#phase-4'>jump</a>", html)
        self.assertNotIn("href='javascript", html)
        self.assertNotIn("href='data:", html)
        self.assertNotIn("onmouseover=\"", html)  # quotes stay escaped, no attribute breakout

    def test_structure_headings_lists_tables_quotes_rules_and_emphasis(self):
        html = render("# One\n## Two\n\nSome **bold** and *italic* and `code <x>`.\n\n"
                      "- a\n  - nested\n- b\n\n1. first\n2. second\n\n> quoted\n\n---\n\n"
                      "| h1 | h2 |\n|:--|--:|\n| x | y |\n")
        self.assertIn("<h2 id='one'>One</h2>", html)
        self.assertIn("<h3 id='two'>Two</h3>", html)
        self.assertIn("<strong>bold</strong>", html)
        self.assertIn("<em>italic</em>", html)
        self.assertIn("<code>code &lt;x&gt;</code>", html)
        self.assertIn("<ul><li>a<ul><li>nested</li></ul></li><li>b</li></ul>", html)
        self.assertIn("<ol><li>first</li><li>second</li></ol>", html)
        self.assertIn("<blockquote><p>quoted</p></blockquote>", html)
        self.assertIn("<hr>", html)
        self.assertIn("<th>h1</th>", html)
        self.assertIn("<td>y</td>", html)

    def test_header_markers_are_hidden_and_duplicate_headings_get_unique_ids(self):
        html = render("<!-- PROTOCOL-HEADER:START -->\n# Same\n<!-- PROTOCOL-HEADER:END -->\n\n# Same\n")
        self.assertNotIn("PROTOCOL-HEADER", html)
        self.assertEqual(re.findall(r"id='([^']+)'", html), ["same", "same-1"])

    def test_bold_label_lines_keep_their_own_line_but_wrapped_prose_still_flows(self):
        html = render("**Project:** evidence\n**Phase:** 4\n**Status:** ok\n\nA long sentence that was hard\nwrapped by the editor and\nshould flow as one.\n")
        self.assertIn("<strong>Project:</strong> evidence<br><strong>Phase:</strong> 4<br><strong>Status:</strong> ok", html)
        self.assertIn("A long sentence that was hard wrapped by the editor and should flow as one.", html)
        self.assertEqual(html.count("<br>"), 2)

    def test_snake_case_and_stars_in_code_are_left_alone(self):
        html = render("keep_my_snake_case and 2*3*4 stay, `*not em*` too")
        self.assertNotIn("<em>", html)

    def test_the_real_protocol_document_renders_without_raw_html(self):
        text = (ROOT / "EVIDENCE_PROTOCOL.md").read_text(encoding="utf-8")
        html = render(text)
        self.assertGreater(len(html), 1000)
        self.assertIn("<h2", html)
        self.assertNotIn("<script", html)
        self.assertNotRegex(html, r"<(?!/?(?:p|br|h[2-6]|ul|ol|li|a|em|strong|code|pre|blockquote|hr|div|table|thead|tbody|tr|th|td)\b)[a-z]")


if __name__ == "__main__":
    unittest.main()
