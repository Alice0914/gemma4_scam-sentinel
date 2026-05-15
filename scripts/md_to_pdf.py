"""
Convert docs/conversation-summary.md to a styled PDF.

Usage:
    python scripts/md_to_pdf.py
    python scripts/md_to_pdf.py --input <path> --output <path>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from markdown_pdf import MarkdownPdf, Section  # noqa: E402

DEFAULT_INPUT  = Path("docs/conversation-summary.md")
DEFAULT_OUTPUT = Path("docs/conversation-summary.pdf")

# Lightweight CSS — readable serif body, mono blocks, soft tables.
CSS = """
@page { size: A4; margin: 2cm 1.6cm; }

body {
  font-family: "Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo",
               Helvetica, Arial, sans-serif;
  font-size: 10.5pt;
  line-height: 1.55;
  color: #1f2937;
}

h1 {
  font-size: 22pt;
  color: #111827;
  border-bottom: 3px solid #2563eb;
  padding-bottom: 6px;
  margin-top: 24pt;
}
h2 {
  font-size: 16pt;
  color: #1e3a8a;
  border-bottom: 1px solid #cbd5e1;
  padding-bottom: 4px;
  margin-top: 20pt;
}
h3 {
  font-size: 13pt;
  color: #1e40af;
  margin-top: 16pt;
}
h4 { font-size: 11.5pt; color: #1f2937; margin-top: 12pt; }

p, li { font-size: 10.5pt; }

blockquote {
  border-left: 4px solid #2563eb;
  background: #eff6ff;
  margin: 12pt 0;
  padding: 8pt 12pt;
  color: #1e3a8a;
  font-style: italic;
}

code {
  font-family: "Cascadia Code", Consolas, "Courier New", monospace;
  background: #f1f5f9;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 9.5pt;
  color: #be123c;
}

pre {
  background: #0f172a;
  color: #f1f5f9;
  padding: 10pt 12pt;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 9pt;
  line-height: 1.4;
}
pre code { background: transparent; color: inherit; padding: 0; }

table {
  border-collapse: collapse;
  width: 100%;
  margin: 10pt 0;
  font-size: 9.5pt;
}
th {
  background: #1e3a8a;
  color: white;
  padding: 6pt 8pt;
  text-align: left;
  border: 1px solid #1e3a8a;
}
td {
  padding: 5pt 8pt;
  border: 1px solid #e5e7eb;
  vertical-align: top;
}
tr:nth-child(even) td { background: #f8fafc; }

a { color: #2563eb; text-decoration: none; }
a:hover { text-decoration: underline; }

hr { border: none; border-top: 2px dashed #cbd5e1; margin: 18pt 0; }

ul, ol { padding-left: 24pt; }
li { margin-bottom: 3pt; }

strong { color: #111827; }
em { color: #1e40af; }
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert markdown to PDF")
    parser.add_argument("--input",  type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--toc-level", type=int, default=2,
                        help="Heading depth to include in table of contents (default 2)")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"[md->pdf] input not found: {args.input}")
        return 1

    print(f"[md->pdf] reading {args.input}")
    md_text = args.input.read_text(encoding="utf-8")

    pdf = MarkdownPdf(toc_level=args.toc_level, optimize=True)
    pdf.add_section(Section(md_text, toc=True), user_css=CSS)
    pdf.meta["title"]  = "Scam Sentinel — Full Design & Work Log"
    pdf.meta["author"] = "Scam Sentinel team"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(str(args.output))
    print(f"[md->pdf] wrote {args.output} ({args.output.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
