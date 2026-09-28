#!/usr/bin/env python3
"""Build a print-styled HTML from docs/requirements.md (PRD markdown), for headless-Chrome PDF export.

Usage: python3 build_pdf.py
Output: docs/requirements.html  (then Chrome -> docs/requirements.pdf)
"""
from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD = ROOT / "docs" / "requirements.md"
OUT = ROOT / "docs" / "requirements.html"

CSS = """
:root{
  --ink:#1a2233; --sub:#5b6577; --line:#dde3ee; --bg:#ffffff;
  --accent:#1a5fb4; --accent-soft:#eaf1fb; --tag:#0f766e; --tag-bg:#e6f6f4;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  font-family:"PingFang SC","Hiragino Sans GB","STHeiti","Microsoft YaHei",sans-serif;
  color:var(--ink); background:var(--bg); font-size:11.5pt; line-height:1.75;
}
@page{ size:A4; margin:13mm 14mm 15mm 14mm; }

/* ---- page control ---- */
.page{page-break-after:always;}
.page:last-child{page-break-after:auto;}

/* ---- cover ---- */
.cover{display:flex;flex-direction:column;justify-content:center;align-items:center;
       text-align:center;height:100vh;min-height:700px;page-break-after:always;}
.cover .kicker{letter-spacing:.35em;color:var(--sub);font-size:12pt;margin-bottom:18px;}
.cover h1{font-size:30pt;margin:0 0 8px;letter-spacing:.05em;}
.cover .subtitle{color:var(--sub);font-size:13pt;margin-bottom:46px;}
.cover .meta{color:var(--sub);font-size:10.5pt;line-height:2;}
.cover .counts{display:flex;gap:16px;margin-top:40px;flex-wrap:wrap;justify-content:center;}
.cover .counts div{border:1px solid var(--line);border-radius:10px;padding:12px 20px;font-size:11pt;color:var(--sub);}
.cover .counts b{display:block;font-size:17pt;color:var(--ink);}

/* ---- toc ---- */
.toc h2{font-size:18pt;margin:0 0 14px;}
.toc ol{margin:0;padding-left:0;list-style:none;}
.toc li{margin:5px 0;}
.toc a{display:flex;justify-content:space-between;align-items:baseline;text-decoration:none;
       color:var(--ink);border-bottom:1px dotted var(--line);padding:4px 2px;}
.toc a span.dots{flex:1;border-bottom:none;}
.toc .toc-num{color:var(--accent);font-family:Menlo,Consolas,monospace;font-size:10pt;margin-right:10px;}

/* ---- section header ---- */
h2.section{
  page-break-before:always; background:var(--accent);color:#fff;border-radius:8px;
  padding:10px 16px;font-size:15pt;margin:6px 0 14px;
}
h2.section:first-of-type{page-break-before:auto;}
h3.sub{font-size:12.5pt;margin:16px 0 6px;color:var(--accent);}
h4{font-size:11pt;margin:12px 0 4px;}

/* ---- tables ---- */
table{width:100%;border-collapse:collapse;font-size:9.3pt;margin:8px 0;}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top;}
th{background:#f5f7fb;}
tr{page-break-inside:avoid;}

/* ---- lists / text ---- */
ul,ol{margin:6px 0 10px;padding-left:22px;}
li{margin:3px 0;}
strong{color:#0d2a52;}
blockquote{background:var(--accent-soft);border-left:3px solid var(--accent);
  border-radius:6px;padding:8px 14px;margin:10px 0;font-size:10.5pt;color:#24364f;}
.todo{list-style:none;margin-left:-18px;color:#24364f;}
.todo::before{content:"☐ ";color:var(--accent);font-weight:700;}
hr{border:none;border-top:1px solid var(--line);margin:14px 0;}
.code{font-family:Menlo,Consolas,monospace;font-size:8.8pt;background:#f2f4f8;
      border-radius:5px;padding:1px 5px;color:#c0263c;}
.note{background:#fff8e6;border:1px solid #f0dca0;border-radius:8px;
      padding:8px 12px;font-size:9.8pt;color:#5c4a00;margin:8px 0;}
.footer{text-align:center;color:var(--sub);font-size:9pt;margin-top:24px;}
a{color:var(--accent);text-decoration:none;}
"""

CODE_RE = re.compile(r"`([^`]+)`")
BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
H2_RE = re.compile(r"^##\s+(.+)$")
H3_RE = re.compile(r"^###\s+(.+)$")
H4_RE = re.compile(r"^####\s+(.+)$")
TABLE_SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
LIST_RE = re.compile(r"^\s*[-*]\s+(.+)$")
TODO_RE = re.compile(r"^- \[([ xX])\]\s+(.+)$")  # before LIST_RE

# 目录展示名简化：去掉括号备注只留章节号+标题
TOC_TITLES = {
    "1. Problem Statement（问题陈述）": "问题陈述",
    "2. Goals & Success Metrics（目标与成功指标）": "目标与成功指标",
    "3. Non-Goals（不做的事）": "不做的事",
    "4. User Personas & Stories（用户画像与故事）": "用户画像与故事",
    "5. Solution Overview（方案概述）": "方案概述",
    "6. 功能需求（Feature Requirements）": "功能需求",
    "7. Technical Considerations（技术考量）": "技术考量",
    "8. Launch Plan（发布计划/当前状态）": "发布计划",
    "9. 数据模型（简）": "数据模型",
    "10. API 清单（已实现）": "API 清单",
    "11. 测试策略（现状）": "测试策略",
    "12. 已知局限（诚实清单）": "已知局限",
    "13. 附录": "附录",
}


def inline(text: str) -> str:
    """Inline markdown -> HTML: code spans, bold, links. Escape everything else."""
    codes: list[str] = []
    def stash(m):
        codes.append(m.group(1))
        return f"\x00{len(codes)-1}\x00"
    text = CODE_RE.sub(stash, text)
    text = html.escape(text, quote=False)
    text = LINK_RE.sub(r'<a href="\2">\1</a>', text)
    text = BOLD_RE.sub(r"<strong>\1</strong>", text)
    def restore(m):
        return f'<span class="code">{html.escape(codes[int(m.group(1))])}</span>'
    text = re.sub(r"\x00(\d+)\x00", restore, text)
    return text


def parse_blocks(lines: list[str]) -> list[str]:
    """Block-level parsing: headings, tables, lists, quotes, hr, paragraphs."""
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue

        m = H2_RE.match(line)
        if m:
            title = m.group(1).strip()
            slug = "sec-" + re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", title).strip("-")
            out.append(f'<h2 class="section" id="{slug}">{inline(title)}</h2>')
            i += 1
            continue
        m = H3_RE.match(line)
        if m:
            out.append(f'<h3 class="sub">{inline(m.group(1).strip())}</h3>')
            i += 1
            continue
        m = H4_RE.match(line)
        if m:
            out.append(f"<h4>{inline(m.group(1).strip())}</h4>")
            i += 1
            continue

        # table block: header row + separator + data rows
        if line.startswith("|") and i + 1 < n and TABLE_SEP_RE.match(lines[i + 1]):
            header = [c.strip() for c in line.strip("|").split("|")]
            j = i + 2
            rows = []
            while j < n and lines[j].strip().startswith("|"):
                cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                rows.append(cells)
                j += 1
            t = ["<table>", "<thead><tr>"]
            t += [f"<th>{inline(c)}</th>" for c in header]
            t += ["</tr></thead><tbody>"]
            for r in rows:
                t.append("<tr>")
                t += [f"<td>{inline(c)}</td>" for c in r]
                t.append("</tr>")
            t.append("</tbody></table>")
            out.append("".join(t))
            i = j
            continue

        m = TODO_RE.match(line)
        if m:
            out.append(f'<li class="todo">{inline(m.group(2).strip())}</li>')
            i += 1
            continue
        m = LIST_RE.match(line)
        if m:
            if out and not out[-1].endswith("</ul>"):
                out.append("<ul>")
            elif out and out[-1].endswith("</ul>"):
                pass
            else:
                out.append("<ul>")
            out.append(f"<li>{inline(m.group(1).strip())}</li>")
            i += 1
            continue
        if out and out[-1].endswith("</li>") and not out[-1].endswith("</ul>"):
            pass
        if line.strip() == "---":
            out.append("<hr>")
            i += 1
            continue
        if line.startswith(">"):
            out.append(f"<blockquote>{inline(line.lstrip('> ').strip())}</blockquote>")
            i += 1
            continue

        out.append(f"<p>{inline(line.strip())}</p>")
        i += 1

    # close stray lists
    res: list[str] = []
    for k, frag in enumerate(out):
        res.append(frag)
        if frag.startswith("<li") and (k + 1 == len(out) or not out[k + 1].startswith("<li")):
            res.append("</ul>")
    return res


def build() -> None:
    text = MD.read_text(encoding="utf-8")
    lines = text.splitlines()

    # collect h2 titles for TOC
    toc_entries: list[tuple[str, str]] = []
    for ln in lines:
        m = H2_RE.match(ln.strip())
        if m:
            title = m.group(1).strip()
            slug = "sec-" + re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", title).strip("-")
            toc_entries.append((slug, title))

    # split into sections: cover art data
    blocks = parse_blocks(lines)

    toc_html = ['<div class="page toc"><h2>目录</h2><ol>']
    for num, (slug, title) in enumerate(toc_entries, 1):
        show = TOC_TITLES.get(title, title)
        toc_html.append(
            f'<li><a href="#{slug}"><span class="toc-num">{num}</span>{inline(show)}<span class="dots"> </span></a></li>'
        )
    toc_html.append("</ol></div>")

    cover = """
<div class="cover">
  <div class="kicker">PRODUCT REQUIREMENTS DOCUMENT</div>
  <h1>智能旅行助手<br>my-trip-planner</h1>
  <div class="subtitle">多 Agent 协作 · 生产级工程 · 可验证 可回溯 可回滚</div>
  <div class="counts">
    <div><b>13</b>功能需求域</div>
    <div><b>40+</b>REST API</div>
    <div><b>127</b>离线测试用例</div>
    <div><b>4</b>协作 Agent</div>
  </div>
  <div class="meta">
    Status: In Development（功能梳理版）· Version 1.0<br>
    Author: Alex (PM) · Last Updated: 2026-09-25<br>
    关联: README.md · docs/articles/ · docs/night-build-todo.md
  </div>
</div>
"""

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>PRD · 智能旅行助手 my-trip-planner</title>
<style>{CSS}</style>
</head>
<body>
{cover}
{''.join(toc_html)}
{''.join(blocks)}
<div class="footer">PRD v1.0 · 智能旅行助手 my-trip-planner · 2026-09-25</div>
</body>
</html>
"""
    OUT.write_text(html_doc, encoding="utf-8")
    print(f"written {OUT} ({len(html_doc)} chars, {len(toc_entries)} TOC entries)")


if __name__ == "__main__":
    build()