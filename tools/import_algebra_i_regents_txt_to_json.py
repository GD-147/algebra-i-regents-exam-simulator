#!/usr/bin/env python3
from pathlib import Path
import json
import re
import sys

SRC_DIR = Path("imports/algebra_i_regents_exams/txt")
OUT_DIR = Path("packs/algebra-i-regents/data")

ID_RE = re.compile(r"^AI(\d+)-(\d{3})$")
CHOICE_RE = re.compile(r"^([A-D])\)\s*(.*)$")
MCQ_KEY_RE = re.compile(
    r"^(AI\d+-\d{3})\s+[—-]\s+Correct:\s+([A-D])\s+[—-]\s+Correct Answer:\s+(.*?)\s+[—-]\s+Explanation:\s+(.*)$"
)
CR_KEY_RE = re.compile(
    r"^(AI\d+-\d{3})\s+[—-]\s+Model Answer:\s+(.*?)\s+[—-]\s+Scoring Guidance:\s+(.*?)\s+[—-]\s+Rubric:\s+(.*)$"
)

EXPECTED = {}
for n in range(1, 25):
    EXPECTED[f"{n:03d}"] = ("I", "mcq", 2)
for n in range(25, 31):
    EXPECTED[f"{n:03d}"] = ("II", "constructed_response", 2)
for n in range(31, 35):
    EXPECTED[f"{n:03d}"] = ("III", "constructed_response", 4)
EXPECTED["035"] = ("IV", "constructed_response", 6)


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def read_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def split_sections(text: str):
    marker = "PART B — ANSWER KEY + EXPLANATIONS"
    if marker not in text:
        marker = "PART B - ANSWER KEY + EXPLANATIONS"
    if marker not in text:
        raise ValueError("Missing PART B — ANSWER KEY + EXPLANATIONS section.")
    q_text, k_text = text.split(marker, 1)
    return q_text, k_text


def parse_key(key_text: str):
    mcq = {}
    constructed = {}

    for raw in key_text.splitlines():
        line = raw.strip()
        if not line:
            continue

        m = MCQ_KEY_RE.match(line)
        if m:
            qid, letter, correct_text, explanation = m.groups()
            mcq[qid] = {
                "correct": letter,
                "correctAnswerText": clean(correct_text),
                "explanation": clean(explanation),
            }
            continue

        m = CR_KEY_RE.match(line)
        if m:
            qid, model, guidance, rubric = m.groups()
            constructed[qid] = {
                "modelAnswer": clean(model),
                "scoringGuidance": clean(guidance),
                "rubric": clean(rubric),
            }

    return mcq, constructed


def parse_question_block(qid: str, block_lines):
    item = {
        "id": qid,
        "part": "",
        "type": "",
        "credits": 0,
        "prompt": "",
        "choices": {},
        "correct": "",
        "explanation": "",
        "modelAnswer": "",
        "scoringGuidance": "",
        "rubric": "",
    }

    current_field = None
    current_choice = None

    for raw in block_lines:
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            if current_field in {"prompt", "modelAnswer", "scoringGuidance", "rubric"}:
                item[current_field] += "\n"
            elif current_choice:
                item["choices"][current_choice] += "\n"
            continue

        if stripped.startswith("Part:"):
            item["part"] = stripped.split(":", 1)[1].strip()
            current_field = None
            current_choice = None
            continue

        if stripped.startswith("Type:"):
            item["type"] = stripped.split(":", 1)[1].strip()
            current_field = None
            current_choice = None
            continue

        if stripped.startswith("Credits:"):
            value = stripped.split(":", 1)[1].strip()
            try:
                item["credits"] = int(value)
            except ValueError:
                raise ValueError(f"{qid}: invalid Credits value: {value}")
            current_field = None
            current_choice = None
            continue

        if stripped == "Prompt:":
            current_field = "prompt"
            current_choice = None
            continue

        for label, field in [
            ("Model Answer:", "modelAnswer"),
            ("Scoring Guidance:", "scoringGuidance"),
            ("Rubric:", "rubric"),
        ]:
            if stripped.startswith(label):
                item[field] = stripped.split(":", 1)[1].strip()
                current_field = field
                current_choice = None
                break
        else:
            cm = CHOICE_RE.match(stripped)
            if cm:
                letter, value = cm.groups()
                item["choices"][letter] = value.strip()
                current_choice = letter
                current_field = None
            elif current_choice:
                item["choices"][current_choice] += "\n" + stripped
            elif current_field:
                if item[current_field]:
                    item[current_field] += "\n" + stripped
                else:
                    item[current_field] = stripped
            else:
                # Ignore stray headings inside PART A.
                pass

    for k in ["prompt", "modelAnswer", "scoringGuidance", "rubric", "explanation"]:
        item[k] = clean(item.get(k, ""))

    item["choices"] = {k: clean(v) for k, v in item["choices"].items()}

    return item


def parse_questions(q_text: str):
    lines = q_text.splitlines()

    starts = []
    for i, line in enumerate(lines):
        s = line.strip()
        if ID_RE.match(s):
            starts.append((i, s))

    items = []
    for idx, (start_i, qid) in enumerate(starts):
        end_i = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        block = lines[start_i + 1:end_i]
        items.append(parse_question_block(qid, block))

    return items


def validate_items(items, mcq_key, cr_key):
    errors = []

    if len(items) != 35:
        errors.append(f"Expected 35 questions, found {len(items)}.")

    expected_ids = [f"AI1-{n:03d}" for n in range(1, 36)]
    found_ids = [x["id"] for x in items]
    if found_ids != expected_ids:
        errors.append(f"IDs must run exactly AI1-001 through AI1-035. Found: {found_ids}")

    total_credits = sum(int(x.get("credits", 0)) for x in items)
    if total_credits != 82:
        errors.append(f"Expected 82 total credits, found {total_credits}.")

    for item in items:
        qid = item["id"]
        num = qid.split("-")[1]
        expected = EXPECTED.get(num)

        if expected:
            exp_part, exp_type, exp_credits = expected
            got = (item.get("part"), item.get("type"), item.get("credits"))
            if got != expected:
                errors.append(f"{qid}: got Part/Type/Credits {got}, expected {expected}.")

        if item["type"] == "mcq":
            if set(item["choices"].keys()) != {"A", "B", "C", "D"}:
                errors.append(f"{qid}: MCQ must have exactly A, B, C, D choices.")

            if qid not in mcq_key:
                errors.append(f"{qid}: missing MCQ answer-key line.")
            else:
                key = mcq_key[qid]
                letter = key["correct"]
                answer_text = key["correctAnswerText"]

                if letter not in item["choices"]:
                    errors.append(f"{qid}: correct letter {letter} is not a valid choice.")
                elif clean(item["choices"][letter]) != answer_text:
                    errors.append(
                        f"{qid}: Correct Answer text does not match choice {letter}. "
                        f"Choice='{item['choices'][letter]}', Key='{answer_text}'"
                    )

                item["correct"] = letter
                item["explanation"] = key["explanation"]

            item.pop("modelAnswer", None)
            item.pop("scoringGuidance", None)
            item.pop("rubric", None)

        elif item["type"] == "constructed_response":
            if qid not in cr_key:
                errors.append(f"{qid}: missing constructed-response key/rubric line.")

            # Prefer the detailed block content, but fill from key if needed.
            key = cr_key.get(qid, {})
            item["modelAnswer"] = item.get("modelAnswer") or key.get("modelAnswer", "")
            item["scoringGuidance"] = item.get("scoringGuidance") or key.get("scoringGuidance", "")
            item["rubric"] = item.get("rubric") or key.get("rubric", "")

            for field in ["modelAnswer", "scoringGuidance", "rubric"]:
                if not item.get(field):
                    errors.append(f"{qid}: missing {field}.")

            item.pop("choices", None)
            item.pop("correct", None)
            item.pop("explanation", None)

        else:
            errors.append(f"{qid}: unknown Type '{item['type']}'.")

    if len(mcq_key) != 24:
        errors.append(f"Expected 24 MCQ answer-key lines, found {len(mcq_key)}.")

    if len(cr_key) != 11:
        errors.append(f"Expected 11 constructed-response key lines, found {len(cr_key)}.")

    if errors:
        raise ValueError("\n".join(errors))

    return items


def import_file(path: Path):
    text = read_text(path)
    q_text, k_text = split_sections(text)
    mcq_key, cr_key = parse_key(k_text)
    items = parse_questions(q_text)
    items = validate_items(items, mcq_key, cr_key)

    out_name = path.stem + ".json"
    out_path = OUT_DIR / out_name
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"OK: wrote {len(items)} questions to {out_path}")


def main():
    if len(sys.argv) > 1:
        files = [Path(x) for x in sys.argv[1:]]
    else:
        files = sorted(SRC_DIR.glob("*.txt"))

    if not files:
        raise SystemExit(f"No .txt files found in {SRC_DIR}")

    for f in files:
        import_file(f)


if __name__ == "__main__":
    main()
