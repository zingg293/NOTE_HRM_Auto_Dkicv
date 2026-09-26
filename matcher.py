import re
import unicodedata
from rapidfuzz import fuzz, process

def norm(s: str) -> str:
    s = str(s or "").strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def choose_candidate(task_name, candidates, min_score=58, min_margin=8):
    """
    candidates: list[str]
    Return exact/best candidate or raise ValueError.
    """
    if not candidates:
        raise ValueError(f"Không có mã/công việc ứng viên cho '{task_name}'.")

    mapping = {norm(c): c for c in candidates if c}
    target = norm(task_name)

    if target in mapping:
        return mapping[target], 100.0, "exact"

    scored = process.extract(
        target,
        list(mapping.keys()),
        scorer=fuzz.token_set_ratio,
        limit=3
    )
    if not scored:
        raise ValueError(f"Không tìm thấy ứng viên cho '{task_name}'.")

    best_key, score, _ = scored[0]
    second = scored[1][1] if len(scored) > 1 else 0

    if score < min_score or (score - second) < min_margin:
        raise ValueError(
            f"Không đủ chắc chắn để chọn công việc cho '{task_name}'. "
            f"Ứng viên gần nhất: '{mapping[best_key]}' ({score:.1f}%), "
            f"ứng viên thứ 2: {second:.1f}%."
        )
    return mapping[best_key], score, "fuzzy"

def choose_catalog_candidate(task_name, rows, min_score=58, min_margin=8):
    """Pick an exact task name, otherwise the closest job detail.

    Each row is (code, name, detail). The catalogue's original order breaks
    ties. The optional thresholds remain in the signature for older callers,
    but the detail fallback always picks the highest available score.
    """
    target = norm(task_name)
    exact = [row for row in rows if norm(row[1]) == target]
    if exact:
        return exact[0], 100.0, "exact"

    best_row = None
    best_score = -1.0
    for row in rows:
        detail = norm(row[2])
        if not detail:
            continue
        score = fuzz.token_set_ratio(target, detail)
        if score > best_score:
            best_row, best_score = row, score
    if best_row is None:
        raise ValueError(f"Danh mục không có Công việc chi tiết để đối chiếu '{task_name}'.")
    return best_row, best_score, "công việc chi tiết"
