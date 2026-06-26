#!/usr/bin/env python3
"""Select 필기 mock exam questions from problem bank (parts_clean + agent_extract answers)."""
from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
import sys

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from config import ROOT, SUBJECT_CATALOG  # noqa: E402

CLEAN = ROOT / "output/problem_book_final"
EXTRACT = ROOT / "output/agent_extract"

SOURCE_RE = re.compile(r"<!--\s*source:\s*(.+?)\s*-->")
QUESTION_START = re.compile(r"^(\d+)\.\s+(.+)")
ANSWER_SECTION_RE = re.compile(r"^#{2,3}\s+(?:\[)?CHAPTER?\s+(\d+)", re.I)
SECTION_RE = re.compile(r"^#{2,3}\s+(?:\[)?CHAPTER?\s+(\d+)\s+(.+)$", re.I)
PART_HEAD = re.compile(r"^## Part (\d+)", re.M)
ANSWER_HEAD = re.compile(r"^## Part \d+ 정답", re.M)
CHOICE_LINE = re.compile(r"^\s*[①②③④⑤]")

SUBJECT_NAMES = {
    "1": "공공조달과 법제도 이해",
    "2": "공공조달계획 수립 및 분석",
    "3": "공공계약관리",
}

# 출제기준·Q-Net·수험 빈출 키워드 (인터넷 검색 상위 주제 반영)
# 동일 회차 내 주제별 최대 문항 수 (유사·쌍둥이 지문 방지)
TOPIC_MAX: dict[str, int] = {
    "pareto": 1,
    "mas_2stage_threshold": 1,
    "mas_2stage": 2,
    "해제_해지": 2,
    "지체상금": 2,
    "물가변동": 2,
    "입찰보증금": 1,
    "계약보증금": 1,
    "포터": 1,
}

TOPIC_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"파레토"), "pareto"),
    (re.compile(r"MAS.*2단계.*기준금액|2단계\s*경쟁.*기준금액"), "mas_2stage_threshold"),
    (
        re.compile(
            r"(?:MAS|다수공급자계약).*(?:2단계|경쟁)|"
            r"(?:2단계|경쟁).*(?:MAS|다수공급자계약)"
        ),
        "mas_2stage",
    ),
    (re.compile(r"해제.*해지|해지.*해제"), "해제_해지"),
    (re.compile(r"지체상금"), "지체상금"),
    (re.compile(r"물가변동"), "물가변동"),
    (re.compile(r"입찰보증금"), "입찰보증금"),
    (re.compile(r"계약보증금"), "계약보증금"),
    (re.compile(r"포터"), "포터"),
]

DEDUP_NOTE = (
    "동일 주제·동일 원본페이지 중복 금지 "
    "(파레토·MAS기준금액 등 회차당 1문항)"
)

IMPORTANCE_KEYWORDS: dict[str, list[str]] = {
    "1": [
        "국가계약법",
        "지방계약법",
        "경쟁입찰",
        "수의계약",
        "입찰보증금",
        "계약보증금",
        "부정당업자",
        "이의신청",
        "재심청구",
        "해제",
        "해지",
        "낙성",
        "요물",
        "일반경쟁",
        "제한경쟁",
        "지명경쟁",
        "협상",
        "적격심사",
        "종합심사",
        "전자조달",
        "나라장터",
        "MAS",
        "2단계",
        "중소기업",
        "녹색",
        "혁신",
        "전략적",
        "공개경쟁",
        "붙임",
        "공고문",
        "참가자격",
        "기준일",
    ],
    "2": [
        "발주계획",
        "발주",
        "구매결의",
        "사전규격",
        "수요",
        "RFP",
        "원가",
        "비용",
        "적정",
        "협상",
        "가격",
        "분석",
        "계획",
        "입찰공고",
        "추정",
        "원가상환",
        "인센티브",
    ],
    "3": [
        "하도급",
        "검사",
        "검수",
        "설계변경",
        "이행보증",
        "계약보증금",
        "15%",
        "적격심사",
        "협상",
        "Turn-Key",
        "설계서",
        "시방서",
        "MAS",
        "이의제기",
        "변동",
        "준공",
        "대금",
        "지급",
        "보증",
        "해제",
        "해지",
    ],
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def stem_key(s: str) -> str:
    """지문 핵심만 비교 (㉠㉡ 보기·번호 제외)."""
    s = norm(s)
    s = re.split(r"\s*㉠", s)[0].strip()
    return re.sub(r"^\d+\.\s+", "", s)


def classify_section(name: str) -> tuple[str, int]:
    if "OX" in name.upper() or "O/X" in name:
        return "ox", -1
    if "단원별 출제예상" in name:
        return "exam", 3
    if "Check" in name or "Q&A" in name or "O&A" in name:
        return "check", 1
    if any(x in name for x in ["㉠", "복수", "빈칸", "조합", "ㄱ", "ㄴ"]):
        return "multi", 2
    return "other", 2


def parse_answers_from_extract(text: str, part_num: int) -> dict[tuple[int, int, str, int], tuple[str, str]]:
    """(part, chapter, stype, qnum) -> (answer, keyword)"""
    acut = ANSWER_HEAD.search(text)
    if not acut:
        return {}
    out: dict[tuple[int, int, str, int], tuple[str, str]] = {}
    chapter = 0
    stype = ""
    for line in text[acut.start() :].splitlines():
        sm = ANSWER_SECTION_RE.match(line.strip())
        if sm:
            chapter = int(sm.group(1))
            stype, _ = classify_section(line)
            continue
        if not chapter or stype == "ox":
            continue
        m = re.match(r"^(\d+)\.\s+([①②③④])\s*(?:—\s*(.+))?$", line.strip())
        if m:
            out[(part_num, chapter, stype, int(m.group(1)))] = (
                m.group(2),
                (m.group(3) or "").strip(),
            )
            continue
        for im in re.finditer(r"(\d+)\.\s+([①②③④])", line):
            out[(part_num, chapter, stype, int(im.group(1)))] = (im.group(2), "")
    return out


def split_giyeok_items(stem: str) -> str:
    """Split inline ㉠㉡ sub-items onto separate lines (extraction_guide)."""
    if "㉠" not in stem or "\n   ㉠" in stem:
        return stem
    # split after question mark / before first ㉠
    m = re.search(r"([?？])\s*(㉠.+)$", stem)
    if not m:
        return stem
    head, tail = stem[: m.end(1)], stem[m.start(2) :]
    parts = re.split(r"(?=㉠)", tail)
    return head + "\n   " + "\n   ".join(p.strip() for p in parts if p.strip())


@dataclass
class Question:
    stem: str
    lines: list[str]
    source: str
    part: int
    chapter: int
    stype: str
    pri: int
    qn: int
    ans: str = ""
    kw: str = ""


def topic_tags(q: Question) -> list[str]:
    """회차 내 중복 제한용 주제 태그."""
    text = q.stem + " " + " ".join(q.lines)
    return [tag for pat, tag in TOPIC_RULES if pat.search(text)]


def topic_at_limit(tags: list[str], counts: Counter[str]) -> bool:
    return any(counts.get(tag, 0) >= TOPIC_MAX[tag] for tag in tags if tag in TOPIC_MAX)


def strict_source_dedup(q: Question) -> bool:
    """동일 원본 페이지 금지는 회차 1문항 주제(파레토 등)에만 적용."""
    tags = topic_tags(q)
    return any(TOPIC_MAX.get(tag, 99) == 1 for tag in tags)


def source_key(source: str) -> str:
    """원본 교재 페이지 단위 키 (동일 페이지 중복 방지)."""
    if not source:
        return ""
    m = re.search(r"Part\s*\d+/[^\s),]+", source)
    return norm(m.group(0)) if m else norm(source)


def validate_round(selected: dict[str, list[Question]]) -> list[str]:
    """회차 선별 결과 중복 검증. 위반 메시지 목록 반환."""
    errors: list[str] = []
    topic_counts: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    stems: set[str] = set()
    num = 0
    for sn in ("1", "2", "3"):
        for q in selected[sn]:
            num += 1
            if q.stem in stems:
                errors.append(f"{num}번: 동일 지문 stem 중복")
            stems.add(q.stem)
            for tag in topic_tags(q):
                topic_counts[tag] += 1
                if topic_counts[tag] > TOPIC_MAX.get(tag, 99):
                    errors.append(
                        f"{num}번: 주제 '{tag}' 상한 초과 "
                        f"({topic_counts[tag]}/{TOPIC_MAX[tag]})"
                    )
            sk = source_key(q.source)
            if sk and strict_source_dedup(q):
                scoped = f"{sn}:{sk}"
                sources[scoped] += 1
                if sources[scoped] > 1:
                    errors.append(f"{num}번: 원본 페이지 중복 ({scoped})")
    return errors


def parse_questions_from_clean(
    clean_file: Path, answers: dict[tuple[int, int, str, int], tuple[str, str]]
) -> list[Question]:
    text = clean_file.read_text(encoding="utf-8")
    pm = PART_HEAD.search(text)
    part = int(pm.group(1)) if pm else 0
    qs: list[Question] = []
    chapter = 0
    stype, pri = "other", 1
    lines = text.splitlines()
    i = 0
    section_batch: list[Question] = []

    def trailing_source_before(idx: int) -> str:
        j = idx - 1
        while j >= 0 and not lines[j].strip():
            j -= 1
        if j >= 0:
            m = SOURCE_RE.search(lines[j])
            if m and not QUESTION_START.match(lines[j]):
                return m.group(1).strip()
        return ""

    def flush_batch(trailing_source: str = "") -> None:
        nonlocal section_batch
        if not section_batch:
            return
        if trailing_source:
            for q in section_batch:
                if not q.source:
                    q.source = trailing_source
        qs.extend(section_batch)
        section_batch = []

    while i < len(lines):
        line = lines[i]
        sm = SECTION_RE.match(line)
        if sm:
            flush_batch(trailing_source=trailing_source_before(i))
            chapter = int(sm.group(1))
            stype, pri = classify_section(sm.group(2))
            i += 1
            continue
        if SOURCE_RE.search(line) and not QUESTION_START.match(line):
            src = SOURCE_RE.search(line).group(1).strip()
            flush_batch(trailing_source=src)
            i += 1
            continue
        qm = QUESTION_START.match(line)
        if qm and stype != "ox":
            qn = int(qm.group(1))
            stem_raw = qm.group(2).strip()
            if "(O/X)" in stem_raw:
                i += 1
                continue
            block = [line]
            i += 1
            source = ""
            while i < len(lines):
                if SECTION_RE.match(lines[i]) or QUESTION_START.match(lines[i]):
                    break
                if SOURCE_RE.search(lines[i]):
                    source = SOURCE_RE.search(lines[i]).group(1).strip()
                    block.append(lines[i])
                    i += 1
                    break
                block.append(lines[i])
                i += 1
            choice_lines = [l for l in block if CHOICE_LINE.match(l)]
            if len(choice_lines) < 4:
                continue
            ans, kw = answers.get((part, chapter, stype, qn), ("", ""))
            stem = stem_key(stem_raw.split("\n")[0])
            section_batch.append(
                Question(
                    stem=stem,
                    lines=block,
                    source=source,
                    part=part,
                    chapter=chapter,
                    stype=stype,
                    pri=pri,
                    qn=qn,
                    ans=ans,
                    kw=kw,
                )
            )
            continue
        i += 1
    flush_batch()
    return qs


def load_used_stems(round_dir: Path) -> set[str]:
    prob = round_dir / "필기_모의_문제.md"
    if not prob.is_file():
        return set()
    stems: set[str] = set()
    for block in re.split(r"\n(?=\d+\. )", prob.read_text(encoding="utf-8")):
        m = re.match(r"\d+\.\s+(.+)", block)
        if m:
            stems.add(stem_key(m.group(1).split("\n")[0]))
    return stems


def _complexity(q: Question) -> int:
    stem = q.stem
    score = len(stem)
    if any(x in stem for x in ("㉠", "빈칸", "( )", "ㄱ", "ㄴ", "조합", "복수")):
        score += 80
    if any(x in stem for x in ("설명으로", "비교", "차이", "절차", "순서", "적용")):
        score += 30
    return score


def _keyword_score(q: Question, subject_no: str) -> int:
    """빈출·출제기준 키워드 매칭 점수."""
    text = q.stem + " " + " ".join(q.lines)
    score = 0
    for kw in IMPORTANCE_KEYWORDS.get(subject_no, []):
        if kw in text:
            score += 12
    for kw in (q.kw or "").split():
        if len(kw) >= 2:
            score += 3
    return score


def _sort_key(q: Question, harder: bool, *, importance: bool = False, subject_no: str = "") -> tuple:
    if importance:
        type_rank = {"exam": 4, "multi": 3, "other": 2, "check": 1}.get(q.stype, 1)
        return (
            -_keyword_score(q, subject_no),
            -type_rank,
            -_complexity(q),
            q.part,
            q.chapter,
            q.qn,
        )
    if harder:
        type_rank = {"multi": 4, "exam": 3, "other": 2, "check": 0}.get(q.stype, 1)
        return (-type_rank, -_complexity(q), q.part, q.chapter, q.qn)
    return (-q.pri, q.chapter, q.qn)


def select(
    pool: list[Question],
    count: int,
    used_stems: set[str],
    *,
    harder: bool = False,
    importance: bool = False,
    subject_no: str = "",
    topic_counts: Counter[str] | None = None,
    used_sources: set[str] | None = None,
) -> list[Question]:
    max_check = 0 if harder else max(1, int(count * 0.2))
    elig = [q for q in pool if q.ans and q.stem not in used_stems]
    by_part: dict[int, list[Question]] = defaultdict(list)
    for q in elig:
        by_part[q.part].append(q)
    for p in by_part:
        by_part[p].sort(
            key=lambda x, sn=subject_no: _sort_key(
                x, harder, importance=importance, subject_no=sn
            )
        )
    selected: list[Question] = []
    check_n = 0
    if topic_counts is None:
        topic_counts = Counter()
    if used_sources is None:
        used_sources = set()
    idx = {p: 0 for p in by_part}
    parts = sorted(by_part)

    def would_duplicate(q: Question) -> bool:
        if topic_at_limit(topic_tags(q), topic_counts):
            return True
        if strict_source_dedup(q):
            sk = source_key(q.source)
            if sk and f"{subject_no}:{sk}" in used_sources:
                return True
        return False

    def accept(q: Question, *, enforce_dedup: bool) -> bool:
        if enforce_dedup and would_duplicate(q):
            return False
        selected.append(q)
        used_stems.add(q.stem)
        for tag in topic_tags(q):
            topic_counts[tag] += 1
        if strict_source_dedup(q):
            sk = source_key(q.source)
            if sk:
                used_sources.add(f"{subject_no}:{sk}")
        return True

    while len(selected) < count:
        progressed = False
        for p in parts:
            if len(selected) >= count:
                break
            while idx[p] < len(by_part[p]):
                q = by_part[p][idx[p]]
                idx[p] += 1
                if q.stype == "check" and check_n >= max_check:
                    continue
                if accept(q, enforce_dedup=True):
                    if q.stype == "check":
                        check_n += 1
                    progressed = True
                    break
        if not progressed:
            for p in parts:
                if len(selected) >= count:
                    break
                while idx[p] < len(by_part[p]):
                    q = by_part[p][idx[p]]
                    idx[p] += 1
                    if accept(q, enforce_dedup=False):
                        break
            if not progressed:
                break
    return selected[:count]


def format_question(num: int, q: Question) -> str:
    stem = re.sub(r"^\d+\.\s+", "", q.lines[0])
    stem = split_giyeok_items(stem)
    out = [f"{num}. {stem}"]
    for ln in q.lines[1:]:
        if SOURCE_RE.search(ln):
            continue
        out.append(ln)
    out.append(f"<!-- source: {q.source} -->")
    return "\n".join(out)


def keyword_line(q: Question) -> str:
    if q.kw:
        t = q.kw.strip()
        return t[:50] + ("…" if len(t) > 50 else "")
    return q.stem[:35] + ("…" if len(q.stem) > 35 else "")


def collect_prior_stems(mock_root: Path, exclude_round: int) -> set[str]:
    stems: set[str] = set()
    for d in sorted(mock_root.glob("*회차")):
        m = re.match(r"(\d+)회차", d.name)
        if m and int(m.group(1)) < exclude_round:
            stems |= load_used_stems(d)
    return stems


def build_round(
    round_num: int,
    mock_root: Path | None = None,
    *,
    harder: bool = False,
    importance: bool = False,
) -> tuple[dict[str, list[Question]], dict[str, dict]]:
    mock_root = mock_root or ROOT / "output/mock_exam"
    used_stems = collect_prior_stems(mock_root, round_num)
    topic_counts: Counter[str] = Counter()
    used_sources: set[str] = set()
    counts = {"1": 30, "2": 20, "3": 30}
    selected: dict[str, list[Question]] = {}
    stats: dict[str, dict] = {}

    for sn, slug_info in SUBJECT_CATALOG.items():
        if slug_info["exam_type"] != "필기":
            continue
        slug = str(slug_info["slug"])
        cnt = counts[sn]
        clean_dir = CLEAN / slug / "parts_clean"
        extract_dir = EXTRACT / slug
        all_answers: dict[tuple[int, int, str, int], tuple[str, str]] = {}
        for ef in sorted(extract_dir.glob("part*.md")):
            pm = PART_HEAD.search(ef.read_text(encoding="utf-8"))
            part = int(pm.group(1)) if pm else 0
            all_answers.update(parse_answers_from_extract(ef.read_text(encoding="utf-8"), part))
        pool: list[Question] = []
        for cf in sorted(clean_dir.glob("part*.md")):
            pool.extend(parse_questions_from_clean(cf, all_answers))
        sel = select(
            pool,
            cnt,
            used_stems,
            harder=harder,
            importance=importance,
            subject_no=sn,
            topic_counts=topic_counts,
            used_sources=used_sources,
        )
        if len(sel) < cnt:
            raise RuntimeError(
                f"{sn}과목: {len(sel)}/{cnt}문항만 선별됨 (풀 {len(pool)}, "
                f"정답매칭 {sum(1 for q in pool if q.ans)}, 미출제 {len([q for q in pool if q.ans and q.stem not in used_stems])})"
            )
        selected[sn] = sel
        stats[sn] = {
            "pool": len(pool),
            "with_ans": sum(1 for q in pool if q.ans),
            "parts": dict(sorted(Counter(q.part for q in sel).items())),
            "types": dict(Counter(q.stype for q in sel)),
            "keyword_hits": sum(1 for q in sel if _keyword_score(q, sn) > 0),
        }
    violations = validate_round(selected)
    if violations:
        raise RuntimeError("회차 중복 검증 실패:\n" + "\n".join(violations))
    return selected, stats


def coverage_report(selected: dict[str, list[Question]]) -> str:
    """Part·Chapter 분포 요약 (출제자 검수용)."""
    lines = ["## Part·Chapter 분포"]
    for sn in ("1", "2", "3"):
        cnt: Counter[tuple[int, int]] = Counter()
        for q in selected[sn]:
            cnt[(q.part, q.chapter)] += 1
        parts = ", ".join(f"P{p}Ch{c}:{n}" for (p, c), n in sorted(cnt.items()))
        lines.append(f"- {sn}과목 ({len(selected[sn])}문항): {parts}")
    return "\n".join(lines)


def write_round(
    round_num: int,
    selected: dict[str, list[Question]],
    mock_root: Path | None = None,
    *,
    harder: bool = False,
    importance: bool = False,
) -> Path:
    mock_root = mock_root or ROOT / "output/mock_exam"
    out = mock_root / f"{round_num}회차"
    out.mkdir(parents=True, exist_ok=True)

    prob = [
        f"# 공공조달관리사 1회 필기 모의 {round_num}회차 — 문제",
        "",
        "> 필기 합계 80문항 · 2시간 · CBT 4지 택일형",
        "> 1과목 30문항 · 2과목 20문항 · 3과목 30문항",
        "",
        "> 출제 기준: docs/시험_안내.md, docs/문제집_프롬프트/시험모의_선별.md",
        "",
        (
            f"> 선별 기준: OX 제외, 출제기준·빈출 키워드 가중, 단원별 출제예상·㉠㉡형 우선, "
            f"{DEDUP_NOTE}, {round_num - 1}회차 이전 미출제 지문"
            if importance
            else (
                f"> 선별 기준: OX 제외, ㉠㉡·빈칸·복수선택 우선, "
                f"{DEDUP_NOTE}, {round_num - 1}회차 이전 미출제 지문"
                if harder
                else (
                    f"> 선별 기준: OX 제외, 단원별 출제예상문제 중심, "
                    f"{DEDUP_NOTE}, {round_num - 1}회차 이전 미출제 지문 우선"
                )
            )
        ),
        "",
    ]
    ans = [
        f"# 공공조달관리사 1회 필기 모의 {round_num}회차 — 정답",
        "",
        "> 1과목 1~30 · 2과목 31~50 · 3과목 51~80",
        "",
    ]
    offsets = {"1": 0, "2": 30, "3": 50}
    ends = {"1": 30, "2": 50, "3": 80}
    for sn in ("1", "2", "3"):
        start = offsets[sn] + 1
        end = ends[sn]
        ename = SUBJECT_NAMES[sn]
        prob += [f"## {sn}과목 {ename} ({start}~{end})", ""]
        ans += [f"## {sn}과목 ({start}~{end})", ""]
        for i, q in enumerate(selected[sn], start):
            prob.append(format_question(i, q))
            prob.append("")
            src = f" ({q.source})" if q.source else ""
            ans.append(f"{i}. {q.ans} — {keyword_line(q)}{src}")
        ans.append("")

    (out / "필기_모의_문제.md").write_text("\n".join(prob).rstrip() + "\n", encoding="utf-8")
    (out / "필기_모의_정답.md").write_text("\n".join(ans).rstrip() + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Select mock exam from problem bank")
    parser.add_argument("round", type=int, help="Mock round number (e.g. 2)")
    parser.add_argument(
        "--mock-root",
        type=Path,
        default=ROOT / "output/mock_exam",
        help="Mock exam root directory (default: output/mock_exam)",
    )
    parser.add_argument(
        "--harder",
        action="store_true",
        help="Raise difficulty: prefer ㉠㉡·빈칸형, exclude Check Q&A",
    )
    parser.add_argument(
        "--importance",
        action="store_true",
        help="Prioritize exam-criteria & high-frequency keywords, balanced difficulty",
    )
    args = parser.parse_args()
    importance = args.importance or (args.round >= 3 and not args.harder)
    selected, stats = build_round(
        args.round, mock_root=args.mock_root, harder=args.harder, importance=importance
    )
    out = write_round(
        args.round,
        selected,
        mock_root=args.mock_root,
        harder=args.harder,
        importance=importance,
    )
    for sn, st in stats.items():
        print(
            f"{sn}과목: pool={st['pool']} parts={st['parts']} "
            f"types={st['types']} keyword_hits={st['keyword_hits']}"
        )
    print(coverage_report(selected))
    print(f"Wrote {out}/필기_모의_문제.md, 필기_모의_정답.md")


if __name__ == "__main__":
    main()
