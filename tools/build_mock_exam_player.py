#!/usr/bin/env python3
"""Build one-question-at-a-time HTML player from mock exam markdown."""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
import sys

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from config import ROOT  # noqa: E402
from mock_exam_common import open_mock_exam_html  # noqa: E402

CHOICE_RE = re.compile(r"^\s*([①②③④⑤])\s*(.+)$")
SECTION_RE = re.compile(r"^##\s+(\d)과목")
QUESTION_START = re.compile(r"^(\d+)\.\s+(.+)")
SOURCE_RE = re.compile(r"<!--\s*source:\s*(.+?)\s*-->")


def parse_questions(md_path: Path) -> tuple[str, list[dict]]:
    text = md_path.read_text(encoding="utf-8")
    title_m = re.search(r"^#\s+(.+)$", text, re.M)
    title = title_m.group(1).strip() if title_m else md_path.parent.name

    questions: list[dict] = []
    current_subject = ""
    block_lines: list[str] = []
    block_num = 0

    def flush_block() -> None:
        nonlocal block_lines, block_num
        if not block_lines:
            return
        first = block_lines[0]
        qm = QUESTION_START.match(first)
        if not qm:
            block_lines = []
            return
        num = int(qm.group(1))
        stem_parts = [qm.group(2).strip()]
        choices: list[dict] = []
        source = ""
        for line in block_lines[1:]:
            sm = SOURCE_RE.search(line)
            if sm:
                source = sm.group(1).strip()
                continue
            cm = CHOICE_RE.match(line)
            if cm:
                choices.append({"label": cm.group(1), "text": cm.group(2).strip()})
            elif line.strip() and not line.strip().startswith("<!--"):
                stem_parts.append(line.strip())
        if len(choices) >= 4:
            questions.append(
                {
                    "num": num,
                    "subject": current_subject,
                    "stem": "\n".join(stem_parts),
                    "choices": choices[:4],
                    "source": source,
                }
            )
        block_lines = []

    for line in text.splitlines():
        sm = SECTION_RE.match(line.strip())
        if sm:
            flush_block()
            current_subject = sm.group(1)
            continue
        qm = QUESTION_START.match(line)
        if qm:
            flush_block()
            block_num = int(qm.group(1))
            block_lines = [line]
            continue
        if block_lines:
            block_lines.append(line)
    flush_block()
    questions.sort(key=lambda q: q["num"])
    return title, questions


def build_html(title: str, questions: list[dict], round_dir: Path) -> str:
    data = json.dumps(questions, ensure_ascii=False)
    storage_key = f"mock_exam_{round_dir.name}"
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title} — 응시</title>
<style>
:root {{
  --bg: #f4f6f9;
  --card: #fff;
  --text: #1a1d21;
  --muted: #5c6570;
  --accent: #1f6feb;
  --accent-soft: #e8f1ff;
  --border: #d8dee6;
  --ok: #1a7f37;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.55;
}}
.wrap {{
  max-width: 720px;
  margin: 0 auto;
  padding: 20px 16px 100px;
}}
header {{
  margin-bottom: 16px;
}}
h1 {{
  font-size: 1.15rem;
  margin: 0 0 8px;
}}
.meta {{
  color: var(--muted);
  font-size: 0.9rem;
}}
.progress-bar {{
  height: 8px;
  background: var(--border);
  border-radius: 999px;
  overflow: hidden;
  margin-top: 12px;
}}
.progress-fill {{
  height: 100%;
  background: var(--accent);
  width: 0%;
  transition: width 0.2s;
}}
.card {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px 18px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
}}
.q-num {{
  font-size: 0.85rem;
  color: var(--accent);
  font-weight: 700;
  margin-bottom: 8px;
}}
.stem {{
  font-size: 1.05rem;
  font-weight: 600;
  white-space: pre-wrap;
  margin-bottom: 18px;
}}
.choices {{
  display: flex;
  flex-direction: column;
  gap: 10px;
}}
.choice {{
  display: flex;
  gap: 10px;
  align-items: flex-start;
  width: 100%;
  text-align: left;
  padding: 12px 14px;
  border: 2px solid var(--border);
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  font: inherit;
  color: inherit;
  transition: border-color 0.15s, background 0.15s;
}}
.choice:hover {{ border-color: #a8c4f0; background: #fafcff; }}
.choice.selected {{
  border-color: var(--accent);
  background: var(--accent-soft);
}}
.choice .label {{
  font-weight: 700;
  min-width: 1.6em;
}}
.choice .text {{ flex: 1; }}
.toolbar {{
  position: fixed;
  left: 0; right: 0; bottom: 0;
  background: rgba(255,255,255,0.96);
  border-top: 1px solid var(--border);
  padding: 12px 16px;
  display: flex;
  gap: 10px;
  justify-content: center;
}}
.btn {{
  padding: 12px 20px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: #fff;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}}
.btn:disabled {{ opacity: 0.45; cursor: not-allowed; }}
.btn-primary {{
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
  min-width: 140px;
}}
#result {{
  display: none;
}}
#result.show {{ display: block; }}
.result-box {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
}}
.answer-preview {{
  font-family: ui-monospace, monospace;
  background: #f6f8fa;
  padding: 12px;
  border-radius: 8px;
  word-break: break-all;
  margin: 12px 0;
}}
.hint {{ color: var(--muted); font-size: 0.88rem; }}
@media (max-width: 480px) {{
  .stem {{ font-size: 1rem; }}
  .choice {{ padding: 10px 12px; }}
}}
</style>
</head>
<body>
<div class="wrap" id="exam-view">
  <header>
    <h1>{safe_title}</h1>
    <div class="meta" id="status">1 / {len(questions)} · 미응답 0</div>
    <div class="progress-bar"><div class="progress-fill" id="progress"></div></div>
  </header>
  <div class="card" id="question-card"></div>
</div>

<div class="wrap" id="result">
  <div class="result-box">
    <h2>응시 완료</h2>
    <p>80문항 답안이 저장되었습니다. 아래 문자열을 복사해 채팅에 붙여넣으면 채점할 수 있습니다.</p>
    <div class="answer-preview" id="answer-export"></div>
    <button class="btn btn-primary" type="button" id="copy-btn">답안 복사</button>
    <button class="btn" type="button" id="restart-btn">처음부터</button>
    <p class="hint">형식: 공백으로 구분한 선지 번호 (예: 4 3 4 4 2 = ①②③④)</p>
  </div>
</div>

<div class="toolbar" id="toolbar">
  <button class="btn" type="button" id="prev-btn">이전</button>
  <button class="btn btn-primary" type="button" id="next-btn" disabled>다음 문제</button>
</div>

<script>
const QUESTIONS = {data};
const STORAGE_KEY = {json.dumps(storage_key)};
const LABEL_TO_NUM = {{"①":1,"②":2,"③":3,"④":4}};

let index = 0;
let answers = {{}};

function loadState() {{
  try {{
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    if (saved.answers) answers = saved.answers;
    if (typeof saved.index === "number") index = saved.index;
  }} catch (e) {{}}
}}

function saveState() {{
  localStorage.setItem(STORAGE_KEY, JSON.stringify({{ index, answers }}));
}}

function answeredCount() {{
  return Object.keys(answers).length;
}}

function render() {{
  const q = QUESTIONS[index];
  const card = document.getElementById("question-card");
  const selected = answers[q.num];
  const choicesHtml = q.choices.map(c => `
    <button type="button" class="choice${{selected === c.label ? " selected" : ""}}" data-label="${{c.label}}">
      <span class="label">${{c.label}}</span>
      <span class="text">${{escapeHtml(c.text)}}</span>
    </button>`).join("");

  card.innerHTML = `
    <div class="q-num">${{q.subject ? q.subject + "과목 · " : ""}}${{q.num}}번</div>
    <div class="stem">${{escapeHtml(q.stem)}}</div>
    <div class="choices">${{choicesHtml}}</div>`;

  card.querySelectorAll(".choice").forEach(btn => {{
    btn.addEventListener("click", () => {{
      answers[q.num] = btn.dataset.label;
      saveState();
      render();
      document.getElementById("next-btn").disabled = false;
    }});
  }});

  const total = QUESTIONS.length;
  const unanswered = total - answeredCount();
  document.getElementById("status").textContent =
    `${{index + 1}} / ${{total}} · 응답 ${{answeredCount()}} · 미응답 ${{unanswered}}`;
  document.getElementById("progress").style.width = `${{((index + 1) / total) * 100}}%`;
  document.getElementById("prev-btn").disabled = index === 0;
  document.getElementById("next-btn").disabled = !answers[q.num];
  document.getElementById("next-btn").textContent =
    index === total - 1 ? "제출하기" : "다음 문제";
}}

function escapeHtml(s) {{
  return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}}

function exportAnswers() {{
  return QUESTIONS.map(q => {{
    const a = answers[q.num];
    return a ? String(LABEL_TO_NUM[a]) : "_";
  }}).join(" ");
}}

function showResult() {{
  document.getElementById("exam-view").style.display = "none";
  document.getElementById("toolbar").style.display = "none";
  document.getElementById("result").classList.add("show");
  document.getElementById("answer-export").textContent = exportAnswers();
  saveState();
}}

document.getElementById("prev-btn").addEventListener("click", () => {{
  if (index > 0) {{ index--; saveState(); render(); }}
}});

document.getElementById("next-btn").addEventListener("click", () => {{
  if (!answers[QUESTIONS[index].num]) return;
  if (index < QUESTIONS.length - 1) {{
    index++;
    saveState();
    render();
  }} else {{
    showResult();
  }}
}});

document.getElementById("copy-btn").addEventListener("click", async () => {{
  const text = exportAnswers();
  try {{
    await navigator.clipboard.writeText(text);
    document.getElementById("copy-btn").textContent = "복사됨!";
    setTimeout(() => {{ document.getElementById("copy-btn").textContent = "답안 복사"; }}, 1500);
  }} catch (e) {{
    prompt("답안을 복사하세요:", text);
  }}
}});

document.getElementById("restart-btn").addEventListener("click", () => {{
  if (!confirm("저장된 답안을 모두 지우고 처음부터 시작할까요?")) return;
  localStorage.removeItem(STORAGE_KEY);
  location.reload();
}});

loadState();
render();
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build interactive mock exam HTML player")
    parser.add_argument(
        "round_dir",
        type=Path,
        nargs="?",
        help="Mock round directory (e.g. output/mock_exam/1회차)",
    )
    parser.add_argument(
        "--mock-root",
        type=Path,
        default=ROOT / "output/mock_exam",
        help="Mock exam root (used with --round)",
    )
    parser.add_argument("--round", type=int, help="Round number (with --mock-root)")
    parser.add_argument(
        "--open",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="생성 후 기본 브라우저에서 필기_응시.html 열기 (기본: 열기)",
    )
    args = parser.parse_args()

    if args.round_dir:
        round_dir = args.round_dir if args.round_dir.is_absolute() else ROOT / args.round_dir
    elif args.round:
        round_dir = args.mock_root / f"{args.round}회차"
    else:
        parser.error("round_dir or --round required")

    prob = round_dir / "필기_모의_문제.md"
    if not prob.is_file():
        raise SystemExit(f"Not found: {prob}")

    title, questions = parse_questions(prob)
    if len(questions) != 80:
        print(f"Warning: parsed {len(questions)} questions (expected 80)")

    out = round_dir / "필기_응시.html"
    out.write_text(build_html(title, questions, round_dir), encoding="utf-8")
    print(f"Wrote {out} ({len(questions)} questions)")
    if args.open:
        if open_mock_exam_html(out):
            print(f"Opened {out} in default browser")
        else:
            print(f"Could not open {out}")


if __name__ == "__main__":
    main()
