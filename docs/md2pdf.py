"""
Markdown → スタイル付きHTML 変換（Mermaid対応）。
基本設計書（コード解説版）を PDF 化するための前段。

使い方:
    python docs/md2pdf.py docs/design/orchestrator.md docs/design/orchestrator.html
そのあと Chrome 無頭印刷で PDF にする（PowerShell 推奨, 別途）:
    chrome --headless=new --no-sandbox --print-to-pdf=out.pdf
           --virtual-time-budget=20000 --user-data-dir=<新temp> file:///...html

ポイント（CLAUDE.md のメモ通り）:
- ```mermaid ブロックは markdown 処理前に <div class="mermaid"> へ退避（コード扱いされないように）。
- mermaid@11 を CDN 読み込み。Tailwind CDN は使わない（プレビューが固まる問題回避）。
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

import markdown

CSS = """
@page { size: A4; margin: 16mm 14mm; }
* { box-sizing: border-box; }
body {
  font-family: "Yu Gothic","Meiryo","Hiragino Kaku Gothic Pro","Noto Sans CJK JP",sans-serif;
  color: #1f2933; line-height: 1.7; font-size: 10.5pt; margin: 0;
}
.doc { max-width: 900px; margin: 0 auto; }
h1 { font-size: 19pt; border-bottom: 3px solid #4f46e5; padding-bottom: 6px; margin-top: 4px; }
h2 { font-size: 14.5pt; background: #eef2ff; border-left: 6px solid #4f46e5;
     padding: 5px 10px; margin-top: 26px; border-radius: 0 4px 4px 0; }
h3 { font-size: 12pt; color: #3730a3; border-bottom: 1px solid #c7d2fe; padding-bottom: 3px; margin-top: 20px; }
h4 { font-size: 11pt; color: #4338ca; margin: 14px 0 4px; }
p, li { font-size: 10.5pt; }
code { font-family: "Consolas","Courier New",monospace; background: #f1f5f9;
       padding: 1px 5px; border-radius: 4px; font-size: 9.5pt; color: #be123c; }
pre { background: #0f172a; color: #e2e8f0; padding: 12px 14px; border-radius: 8px;
      overflow-x: auto; font-size: 9pt; line-height: 1.5; }
pre code { background: transparent; color: #e2e8f0; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 9.5pt; }
th, td { border: 1px solid #cbd5e1; padding: 6px 9px; text-align: left; vertical-align: top; }
th { background: #4f46e5; color: #fff; font-weight: 600; }
tr:nth-child(even) td { background: #f8fafc; }
blockquote { border-left: 4px solid #f59e0b; background: #fffbeb; margin: 10px 0;
             padding: 6px 14px; color: #78350f; border-radius: 0 4px 4px 0; }
.mermaid { background: #fff; text-align: center; margin: 14px 0; page-break-inside: avoid; }
hr { border: none; border-top: 1px dashed #cbd5e1; margin: 22px 0; }
h2, h3, table, pre { page-break-inside: avoid; }
.tag { display:inline-block; background:#e0e7ff; color:#3730a3; border-radius:4px;
       padding:0 6px; font-size:9pt; font-weight:600; }
"""

HTML_TMPL = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<style>{css}</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script>
  window.addEventListener('load', function() {{
    if (window.mermaid) mermaid.initialize({{ startOnLoad: true, theme: 'neutral' }});
  }});
</script>
</head><body><div class="doc">{body}</div></body></html>
"""


def convert(md_path: str, html_path: str) -> None:
    text = Path(md_path).read_text(encoding="utf-8")

    # 1) mermaid ブロックを退避
    blocks: list[str] = []

    def _stash(m: re.Match) -> str:
        blocks.append(m.group(1))
        return f"\n@@MERMAID{len(blocks) - 1}@@\n"

    text = re.sub(r"```mermaid\n(.*?)```", _stash, text, flags=re.DOTALL)

    # 2) markdown → HTML
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "toc", "sane_lists"])

    # 3) mermaid を <div class="mermaid"> として戻す（<p>で包まれてもOKなように両対応）
    for i, b in enumerate(blocks):
        div = f'<div class="mermaid">\n{html.escape(b.strip())}\n</div>'
        body = body.replace(f"<p>@@MERMAID{i}@@</p>", div).replace(f"@@MERMAID{i}@@", div)

    Path(html_path).write_text(HTML_TMPL.format(css=CSS, body=body), encoding="utf-8")
    print(f"OK -> {html_path}")


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2])
