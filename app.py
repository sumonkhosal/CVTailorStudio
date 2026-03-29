import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

try:
    import pdfplumber
except Exception:
    pdfplumber = None

try:
    from docx import Document
except Exception:
    Document = None

try:
    import jinja2
except Exception:
    jinja2 = None

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
except Exception:
    A4 = None
    getSampleStyleSheet = None
    ParagraphStyle = None
    cm = None
    SimpleDocTemplate = None
    Paragraph = None
    Spacer = None
    PageBreak = None

# =============================
# APP CONFIG
# =============================
st.set_page_config(page_title="CV Tailor Studio", layout="wide")
OUTPUT_DIR = Path("output_cv_studio")
OUTPUT_DIR.mkdir(exist_ok=True)

DEFAULT_HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Tailored Application</title>
<style>
body { font-family: Arial, sans-serif; background:#f5f7fb; color:#1f2937; margin:0; }
.page { max-width:900px; margin:24px auto; background:#fff; padding:32px 40px; border-radius:16px; box-shadow:0 8px 24px rgba(0,0,0,0.08); }
h1,h2,h3 { margin-bottom:8px; }
h2 { border-bottom:2px solid #e5e7eb; padding-bottom:6px; margin-top:24px; }
.meta { color:#4b5563; margin-bottom:16px; }
ul { padding-left:20px; }
.entry { margin-bottom:14px; }
.entryhead { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; font-weight:700; }
.small { color:#4b5563; }
</style>
</head>
<body>
<div class="page">
<h1>{{ cv.header.name }}</h1>
<div class="meta">
{{ cv.header.email }}{% if cv.header.phone %} | {{ cv.header.phone }}{% endif %}{% if cv.header.location %} | {{ cv.header.location }}{% endif %}
</div>
{% if cv.summary %}<h2>{{ labels.profile }}</h2><div>{{ cv.summary }}</div>{% endif %}
{% if cv.skills %}<h2>{{ labels.skills }}</h2><div>{{ cv.skills | join(' • ') }}</div>{% endif %}
{% if cv.experience %}
<h2>{{ labels.experience }}</h2>
{% for job in cv.experience %}
<div class="entry">
<div class="entryhead"><span>{{ job.title }}{% if job.company %} — {{ job.company }}{% endif %}</span><span>{{ job.date }}</span></div>
{% if job.location %}<div class="small">{{ job.location }}</div>{% endif %}
{% if job.bullets %}<ul>{% for b in job.bullets %}<li>{{ b }}</li>{% endfor %}</ul>{% endif %}
</div>
{% endfor %}
{% endif %}
{% if cv.education %}
<h2>{{ labels.education }}</h2>
{% for edu in cv.education %}
<div class="entry"><div class="entryhead"><span>{{ edu.degree }}{% if edu.school %} — {{ edu.school }}{% endif %}</span><span>{{ edu.date }}</span></div>{% if edu.details %}<div class="small">{{ edu.details }}</div>{% endif %}</div>
{% endfor %}
{% endif %}
{% if cv.projects %}
<h2>{{ labels.projects }}</h2>
{% for p in cv.projects %}
<div class="entry"><div class="entryhead"><span>{{ p.name }}</span></div>{% if p.bullets %}<ul>{% for b in p.bullets %}<li>{{ b }}</li>{% endfor %}</ul>{% endif %}</div>
{% endfor %}
{% endif %}
</div>
</body>
</html>
"""

GERMAN_HINTS = {
    "und", "mit", "für", "auf", "der", "die", "das", "ein", "eine", "sie", "wir", "nicht", "von",
    "im", "ist", "sind", "bewerbung", "kenntnisse", "aufgaben", "profil", "studium", "erfahrung",
    "anschreiben", "berufserfahrung", "ausbildung", "fähigkeiten", "wünschenswert", "unterstützen"
}
ENGLISH_HINTS = {
    "the", "with", "for", "and", "you", "your", "experience", "skills", "responsibilities",
    "application", "cover", "letter", "profile", "job", "support", "preferred", "education", "projects"
}
STOPWORDS = ENGLISH_HINTS | GERMAN_HINTS | {
    "this", "that", "from", "into", "will", "have", "has", "our", "their", "they", "them", "about", "more", "than"
}


# =============================
# HELPERS
# =============================
def html_escape(text: Any) -> str:
    if text is None:
        return ""
    s = str(text)
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&#39;")
    )


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def sentence_split(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [normalize_space(p) for p in parts if normalize_space(p)]


def bulletize_lines(text: str) -> List[str]:
    lines = [normalize_space(x) for x in (text or "").splitlines() if normalize_space(x)]
    bullets = []
    for line in lines:
        cleaned = re.sub(r"^[\-•*]+\s*", "", line)
        if len(cleaned) > 2:
            bullets.append(cleaned)
    return bullets


def tokenize(text: str) -> List[str]:
    words = re.findall(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9+.#\-/]*", (text or "").lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 2]


def extract_keywords(text: str, top_k: int = 40) -> List[str]:
    counts: Dict[str, int] = {}
    for tok in tokenize(text):
        counts[tok] = counts.get(tok, 0) + 1
    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return [k for k, _ in ranked[:top_k]]


def safe_json_loads(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"```json\s*(.*?)```", text or "", flags=re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            return None
    return None


def ensure_list_of_strings(value: Any) -> List[str]:
    if isinstance(value, list):
        return [normalize_space(str(x)) for x in value if normalize_space(str(x))]
    if normalize_space(str(value)):
        return [normalize_space(str(value))]
    return []


def detect_language_simple(text: str) -> str:
    toks = tokenize(text)
    de = sum(1 for t in toks if t in GERMAN_HINTS or any(ch in t for ch in "äöüß"))
    en = sum(1 for t in toks if t in ENGLISH_HINTS)
    return "de" if de > en else "en"


def read_pdf(file) -> str:
    if pdfplumber is None:
        raise RuntimeError("pdfplumber is not installed.")
    parts = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
    return "\n".join(parts)


def read_docx(file) -> str:
    if Document is None:
        raise RuntimeError("python-docx is not installed.")
    doc = Document(file)
    return "\n".join(p.text for p in doc.paragraphs)


def read_text_file(uploaded_file) -> str:
    name = uploaded_file.name.lower()
    if name.endswith(".pdf"):
        return read_pdf(uploaded_file)
    if name.endswith(".docx"):
        return read_docx(uploaded_file)
    if name.endswith(".txt"):
        return uploaded_file.read().decode("utf-8", errors="ignore")
    raise ValueError("Unsupported file type. Use PDF, DOCX, or TXT.")


# =============================
# AI PROVIDERS
# =============================
class BaseProvider:
    name = "base"

    def generate_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        raise NotImplementedError


class MockProvider(BaseProvider):
    name = "mock"

    def generate_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        return {"mock": True}


class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def generate_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        from openai import OpenAI
        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        content = response.choices[0].message.content
        data = safe_json_loads(content)
        if data is None:
            raise RuntimeError(f"Provider returned non-JSON response:\n{content}")
        return data


class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def generate_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(self.model)
        result = model.generate_content(system_prompt + "\n\n" + user_prompt + "\n\nReturn only valid JSON object.")
        text = getattr(result, "text", "")
        data = safe_json_loads(text)
        if data is None:
            raise RuntimeError(f"Provider returned non-JSON response:\n{text}")
        return data


class ClaudeProvider(BaseProvider):
    name = "claude"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def generate_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        msg = client.messages.create(
            model=self.model,
            max_tokens=4000,
            temperature=0.2,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt + "\n\nReturn only valid JSON object."}],
        )
        text = "".join(block.text for block in msg.content if getattr(block, "type", None) == "text")
        data = safe_json_loads(text)
        if data is None:
            raise RuntimeError(f"Provider returned non-JSON response:\n{text}")
        return data


def make_provider(provider_name: str, api_key: str, model: str) -> BaseProvider:
    n = (provider_name or "").lower()
    if n == "openai" and api_key:
        return OpenAIProvider(api_key, model)
    if n == "gemini" and api_key:
        return GeminiProvider(api_key, model)
    if n == "claude" and api_key:
        return ClaudeProvider(api_key, model)
    return MockProvider()


# =============================
# PARSING
# =============================
def split_sections(text: str) -> Dict[str, str]:
    headers = [
        "summary", "profile", "about", "profil", "zusammenfassung",
        "experience", "work experience", "professional experience", "berufserfahrung", "erfahrung",
        "education", "ausbildung", "studium",
        "skills", "technical skills", "kenntnisse", "fähigkeiten",
        "projects", "projekte",
    ]
    current = "_top"
    data: Dict[str, List[str]] = {current: []}
    for line in (text or "").splitlines():
        stripped = normalize_space(line)
        lowered = stripped.lower().rstrip(":")
        if lowered in headers:
            current = lowered
            data.setdefault(current, [])
        else:
            data.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip() for k, v in data.items()}


def parse_skills(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"[,;|\n]", text)
    out = []
    for p in parts:
        p = normalize_space(p)
        if p and p not in out:
            out.append(p)
    return out[:40]


def parse_experience(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    out = []
    for block in blocks:
        lines = [normalize_space(x) for x in block.splitlines() if normalize_space(x)]
        title = lines[0] if lines else ""
        company = lines[1] if len(lines) > 1 else ""
        date = ""
        bullets = []
        for line in lines[2:]:
            if re.search(r"\b(20\d{2}|19\d{2}|present|current|heute|jan|feb|mär|mar|apr|may|mai|jun|jul|aug|sep|oct|okt|nov|dec|dez)\b", line.lower()) and not date:
                date = line
            else:
                bullets.append(re.sub(r"^[\-•*]+\s*", "", line))
        if not bullets:
            bullets = [re.sub(r"^[\-•*]+\s*", "", x) for x in lines[2:]]
        out.append({
            "company": company,
            "title": title,
            "date": date,
            "location": "",
            "bullets": bullets[:8],
        })
    return out[:10]


def parse_education(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    out = []
    for block in blocks:
        lines = [normalize_space(x) for x in block.splitlines() if normalize_space(x)]
        out.append({
            "degree": lines[0] if len(lines) > 0 else "",
            "school": lines[1] if len(lines) > 1 else "",
            "date": lines[2] if len(lines) > 2 else "",
            "details": "; ".join(lines[3:]) if len(lines) > 3 else "",
        })
    return out[:6]


def parse_projects(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    out = []
    for block in blocks:
        lines = [normalize_space(x) for x in block.splitlines() if normalize_space(x)]
        out.append({
            "name": lines[0] if lines else "Project",
            "bullets": [re.sub(r"^[\-•*]+\s*", "", x) for x in lines[1:]][:6],
        })
    return out[:8]


def parse_cv_heuristic(cv_text: str) -> Dict[str, Any]:
    lines = [normalize_space(x) for x in (cv_text or "").splitlines() if normalize_space(x)]
    top = lines[:8]
    email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", cv_text or "")
    phone_match = re.search(r"(\+?\d[\d\s\-()]{7,}\d)", cv_text or "")
    sections = split_sections(cv_text or "")
    cv_lang = detect_language_simple(cv_text or "")
    cv = {
        "header": {
            "name": top[0] if top else "Candidate Name",
            "email": email_match.group(0) if email_match else "",
            "phone": normalize_space(phone_match.group(1)) if phone_match else "",
            "location": "",
            "links": [],
        },
        "summary": normalize_space(
            (
                sections.get("summary", "") or sections.get("profile", "") or sections.get("about", "") or
                sections.get("profil", "") or sections.get("zusammenfassung", "")
            )[:700]
        ),
        "skills": parse_skills(
            sections.get("skills", "") or sections.get("technical skills", "") or
            sections.get("kenntnisse", "") or sections.get("fähigkeiten", "")
        ),
        "experience": parse_experience(
            sections.get("experience", "") or sections.get("work experience", "") or
            sections.get("professional experience", "") or sections.get("berufserfahrung", "") or
            sections.get("erfahrung", "")
        ),
        "education": parse_education(
            sections.get("education", "") or sections.get("ausbildung", "") or sections.get("studium", "")
        ),
        "projects": parse_projects(sections.get("projects", "") or sections.get("projekte", "")),
        "language": cv_lang,
        "raw_text": cv_text or "",
    }
    if not cv["skills"]:
        cv["skills"] = extract_keywords(cv_text or "", top_k=20)
    if not cv["experience"]:
        bullets = bulletize_lines(cv_text or "")
        if bullets:
            cv["experience"] = [{
                "company": "",
                "title": "Experience Highlights",
                "date": "",
                "location": "",
                "bullets": bullets[:8],
            }]
    return cv


def parse_job_description(jd_text: str) -> Dict[str, Any]:
    jd_lang = detect_language_simple(jd_text or "")
    keywords = extract_keywords(jd_text or "", top_k=50)
    sentences = sentence_split(jd_text or "")
    must_have: List[str] = []
    nice_to_have: List[str] = []
    responsibilities: List[str] = []
    for s in sentences:
        sl = s.lower()
        if any(x in sl for x in ["must", "required", "requirement", "mandatory", "muss", "erforderlich", "voraussetzung"]):
            must_have.append(s)
        elif any(x in sl for x in ["preferred", "nice to have", "plus", "bonus", "wünschenswert"]):
            nice_to_have.append(s)
        elif any(x in sl for x in ["responsible", "you will", "tasks", "duties", "support", "design", "develop", "analyze", "manage", "create", "aufgaben", "sie unterstützen", "sie werden"]):
            responsibilities.append(s)
    return {
        "language": jd_lang,
        "keywords": keywords,
        "must_have": must_have[:15],
        "nice_to_have": nice_to_have[:15],
        "responsibilities": responsibilities[:20],
        "raw_text": jd_text or "",
    }


# =============================
# SCORING
# =============================
def keyword_match_score(cv_text: str, jd_keywords: List[str]) -> Tuple[float, List[str], List[str]]:
    cv_lower = (cv_text or "").lower()
    found = [kw for kw in jd_keywords if kw.lower() in cv_lower]
    missing = [kw for kw in jd_keywords if kw.lower() not in cv_lower]
    score = 100.0 * len(found) / max(len(jd_keywords), 1)
    return round(score, 1), found[:25], missing[:25]


def semantic_relevance_score(cv_text: str, jd_text: str) -> float:
    cv_tokens = set(tokenize(cv_text or ""))
    jd_tokens = set(tokenize(jd_text or ""))
    inter = len(cv_tokens.intersection(jd_tokens))
    union = max(len(cv_tokens.union(jd_tokens)), 1)
    return round(100.0 * inter / union, 1)


def structure_score(cv: Dict[str, Any]) -> Tuple[float, List[str]]:
    checks: List[str] = []
    score = 0.0
    if cv.get("header", {}).get("name"):
        score += 10
    else:
        checks.append("Add your full name in the header.")
    if cv.get("header", {}).get("email"):
        score += 10
    else:
        checks.append("Add a professional email address.")
    if cv.get("summary"):
        score += 10
    else:
        checks.append("Add a short profile summary tailored to the job.")
    if cv.get("skills"):
        score += 15
    else:
        checks.append("Add a dedicated skills section.")
    if cv.get("experience"):
        score += 20
    else:
        checks.append("Add work experience or project experience.")
    if cv.get("education"):
        score += 10
    else:
        checks.append("Add your education section.")
    if cv.get("projects"):
        score += 10
    quantified = 0
    total = 0
    for job in cv.get("experience", []):
        if not isinstance(job, dict):
            continue
        for b in ensure_list_of_strings(job.get("bullets", [])):
            total += 1
            if re.search(r"\b\d+(?:[.,]\d+)?\b|%|hours|weeks|months|years|mm|cm|m\b|kg|€|eur|bar\b", b.lower()):
                quantified += 1
    if total:
        score += min(15, (quantified / total) * 15)
    else:
        checks.append("Use bullet points under each experience entry.")
    return round(min(score, 100), 1), checks


def composite_scores(cv: Dict[str, Any], jd: Dict[str, Any]) -> Dict[str, Any]:
    kw, found, missing = keyword_match_score(cv.get("raw_text", ""), jd.get("keywords", []))
    sem = semantic_relevance_score(cv.get("raw_text", ""), jd.get("raw_text", ""))
    struct, notes = structure_score(cv)
    ats1 = round(0.70 * kw + 0.30 * struct, 1)
    ats2 = round(0.55 * sem + 0.45 * kw, 1)
    ats3 = round(0.60 * struct + 0.40 * sem, 1)
    workday = round(0.50 * struct + 0.35 * kw + 0.15 * sem, 1)
    greenhouse = round(0.45 * sem + 0.30 * struct + 0.25 * kw, 1)
    final = round((ats1 + ats2 + ats3 + workday + greenhouse) / 5.0, 1)
    return {
        "keyword_score": kw,
        "semantic_score": sem,
        "structure_score": struct,
        "ats_source_1": ats1,
        "ats_source_2": ats2,
        "ats_source_3": ats3,
        "workday_style_score": workday,
        "greenhouse_style_score": greenhouse,
        "final_score": final,
        "found_keywords": found,
        "missing_keywords": missing,
        "structure_notes": notes,
    }


# =============================
# SUGGESTIONS
# =============================
def build_bilingual_suggestion_prompt(cv: Dict[str, Any], jd: Dict[str, Any], truth_mode: str) -> Tuple[str, str]:
    system_prompt = (
        "You are a multilingual CV optimization assistant. Suggestion quality is extremely important. "
        "The CV may be in German or English. The job description may be in German or English. "
        "Internally understand both languages. Never invent experience, dates, tools, degrees, or achievements. "
        "Return only JSON. Suggestions must be natural, concise, typo-free, and recruiter-friendly in both English and German."
    )
    user_prompt = f"""
Generate bilingual CV suggestions.

Truth mode: {truth_mode}
Rules:
1. Do not fabricate facts.
2. Only rewrite, reorder, clarify, or highlight existing evidence.
3. Add job-description keywords only if supported by the CV.
4. Rewrite only summary text, skill entries, or bullet points.
5. Produce both English and German suggestion text.
6. Keep each suggestion high quality.

Return JSON with this exact structure:
{{
  "suggestions": [
    {{
      "id": "unique_id",
      "type": "rewrite|add_summary|add_skill|project_highlight",
      "section": "summary|skills|experience|projects",
      "target_path": "example: experience.0.bullets.1",
      "reason_en": "why this helps",
      "reason_de": "warum das hilft",
      "old_text": "old text or empty",
      "suggested_text_en": "English version",
      "suggested_text_de": "German version",
      "tags": ["keyword", "clarity", "structure"]
    }}
  ]
}}

CURRENT CV JSON:
{json.dumps(cv, ensure_ascii=False, indent=2)}

JOB DESCRIPTION JSON:
{json.dumps(jd, ensure_ascii=False, indent=2)}
"""
    return system_prompt, user_prompt


def heuristic_suggestions(cv: Dict[str, Any], jd: Dict[str, Any], scores: Dict[str, Any]) -> List[Dict[str, Any]]:
    suggestions: List[Dict[str, Any]] = []
    missing = scores.get("missing_keywords", [])[:8]
    if not cv.get("summary"):
        suggestions.append({
            "id": str(uuid.uuid4()),
            "type": "add_summary",
            "section": "summary",
            "target_path": "summary",
            "reason_en": "Adds a targeted profile summary.",
            "reason_de": "Ergänzt ein zielgerichtetes Kurzprofil.",
            "old_text": "",
            "suggested_text_en": "Candidate with hands-on project and technical documentation experience, aligned with the target role.",
            "suggested_text_de": "Kandidat mit praktischer Projekt- und technischer Dokumentationserfahrung, passend zur Zielposition.",
            "tags": ["structure"],
        })
    existing = {x.lower() for x in ensure_list_of_strings(cv.get("skills", []))}
    for kw in missing[:5]:
        if kw.lower() not in existing:
            suggestions.append({
                "id": str(uuid.uuid4()),
                "type": "add_skill",
                "section": "skills",
                "target_path": "skills",
                "reason_en": "This keyword appears in the job description and may improve matching if accurate.",
                "reason_de": "Dieses Stichwort kommt in der Stellenanzeige vor und kann die Passung verbessern, falls es zutrifft.",
                "old_text": "",
                "suggested_text_en": kw,
                "suggested_text_de": kw,
                "tags": ["keyword"],
            })
    return suggestions


def validate_suggestion_record(s: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(s, dict):
        return None
    target_path = str(s.get("target_path", "")).strip()
    allowed = (
        target_path == "summary" or
        target_path == "skills" or
        (target_path.startswith("experience.") and ".bullets." in target_path) or
        (target_path.startswith("projects.") and ".bullets." in target_path)
    )
    if not allowed:
        return None
    en = normalize_space(str(s.get("suggested_text_en", "")))
    de = normalize_space(str(s.get("suggested_text_de", "")))
    if not en or not de:
        return None
    out = dict(s)
    out["id"] = str(out.get("id") or uuid.uuid4())
    out["reason_en"] = normalize_space(str(out.get("reason_en", "")))
    out["reason_de"] = normalize_space(str(out.get("reason_de", "")))
    out["suggested_text_en"] = en
    out["suggested_text_de"] = de
    out["tags"] = [str(x) for x in out.get("tags", [])] if isinstance(out.get("tags", []), list) else []
    return out


def generate_suggestions(cv: Dict[str, Any], jd: Dict[str, Any], provider: BaseProvider, truth_mode: str, scores: Dict[str, Any]) -> List[Dict[str, Any]]:
    heuristic = heuristic_suggestions(cv, jd, scores)
    if isinstance(provider, MockProvider):
        return heuristic
    try:
        system_prompt, user_prompt = build_bilingual_suggestion_prompt(cv, jd, truth_mode)
        data = provider.generate_json(system_prompt, user_prompt)
        llm = data.get("suggestions", []) if isinstance(data, dict) else []
        merged: List[Dict[str, Any]] = []
        seen = set()
        for raw in llm + heuristic:
            v = validate_suggestion_record(raw)
            if not v:
                continue
            key = json.dumps(
                {"target_path": v["target_path"], "en": v["suggested_text_en"], "de": v["suggested_text_de"]},
                ensure_ascii=False,
                sort_keys=True,
            )
            if key not in seen:
                seen.add(key)
                merged.append(v)
        return merged[:35]
    except Exception as e:
        st.warning(f"AI provider failed, using heuristic suggestions. Details: {e}")
        return heuristic


# =============================
# APPLY SUGGESTIONS
# =============================
def set_path_value(data: Dict[str, Any], path: str, value: Any):
    parts = path.split(".")
    cur: Any = data
    for part in parts[:-1]:
        cur = cur[int(part)] if part.isdigit() else cur[part]
    last = parts[-1]
    if last.isdigit():
        cur[int(last)] = value
    else:
        cur[last] = value


def structured_cv_to_text(cv: Dict[str, Any]) -> str:
    parts: List[str] = []
    hdr = cv.get("header", {}) if isinstance(cv.get("header", {}), dict) else {}
    parts.extend([
        str(hdr.get("name", "")),
        str(hdr.get("email", "")),
        str(hdr.get("phone", "")),
        str(hdr.get("location", "")),
    ])
    if cv.get("summary"):
        parts.extend(["Summary", str(cv.get("summary", ""))])
    if cv.get("skills"):
        parts.extend(["Skills", ", ".join(ensure_list_of_strings(cv.get("skills", [])))])
    if cv.get("experience"):
        parts.append("Experience")
        for job in cv.get("experience", []):
            if isinstance(job, dict):
                parts.extend([
                    str(job.get("title", "")),
                    str(job.get("company", "")),
                    str(job.get("date", "")),
                    str(job.get("location", "")),
                ])
                parts.extend(ensure_list_of_strings(job.get("bullets", [])))
            else:
                parts.append(str(job))
    if cv.get("education"):
        parts.append("Education")
        for edu in cv.get("education", []):
            if isinstance(edu, dict):
                parts.extend([
                    str(edu.get("degree", "")),
                    str(edu.get("school", "")),
                    str(edu.get("date", "")),
                    str(edu.get("details", "")),
                ])
            else:
                parts.append(str(edu))
    if cv.get("projects"):
        parts.append("Projects")
        for p in cv.get("projects", []):
            if isinstance(p, dict):
                parts.append(str(p.get("name", "")))
                parts.extend(ensure_list_of_strings(p.get("bullets", [])))
            else:
                parts.append(str(p))
    return "\n".join(normalize_space(x) for x in parts if normalize_space(x))


def apply_suggestions(cv: Dict[str, Any], suggestions: List[Dict[str, Any]], accepted_ids: List[str], language: str = "en") -> Dict[str, Any]:
    new_cv = json.loads(json.dumps(cv))
    accepted = [s for s in suggestions if isinstance(s, dict) and s.get("id") in accepted_ids]
    text_key = "suggested_text_de" if language == "de" else "suggested_text_en"
    for s in accepted:
        tp = s.get("type")
        path = str(s.get("target_path", "")).strip()
        text = s.get(text_key, "")
        try:
            if tp == "rewrite" and path.startswith("experience.") and ".bullets." in path:
                set_path_value(new_cv, path, text)
            elif tp == "rewrite" and path.startswith("projects.") and ".bullets." in path:
                set_path_value(new_cv, path, text)
            elif tp == "project_highlight" and path.startswith("projects.") and ".bullets." in path:
                set_path_value(new_cv, path, text)
            elif tp == "add_summary" and path == "summary":
                new_cv["summary"] = text
            elif tp == "add_skill" and path == "skills":
                if text and text not in new_cv.get("skills", []):
                    new_cv.setdefault("skills", []).append(text)
        except Exception:
            continue
    new_cv["raw_text"] = structured_cv_to_text(new_cv)
    return new_cv


# =============================
# FINAL PACKAGE GENERATION
# =============================
def build_bilingual_application_prompt(
    cv_text: str,
    jd_text: str,
    cv_lang: str,
    jd_lang: str,
    suggestions: List[Dict[str, Any]],
    accepted_ids: List[str],
    cover_inputs: Dict[str, str],
) -> Tuple[str, str]:
    accepted = [s for s in suggestions if isinstance(s, dict) and s.get("id") in accepted_ids]
    system_prompt = (
        "You are a senior multilingual CV and cover-letter editor. The CV may be in German or English. The job description may be in German or English. "
        "Internally understand both languages. Never invent facts. Generate polished output in BOTH English and German. Return only JSON."
    )
    user_prompt = f"""
Create final bilingual application materials.

Rules:
1. Detect the language of the CV and the job description.
2. Internally translate as needed for analysis.
3. Preserve all facts from the original CV.
4. Apply the accepted suggestions naturally.
5. Produce final CV text in English and German.
6. Produce final cover letter in English and German.
7. Cover letters must use the user inputs naturally.
8. Also create one long reusable external prompt for OpenAI/Gemini/Claude.

Return JSON with this exact structure:
{{
  "detected": {{"cv_language": "en|de", "jd_language": "en|de"}},
  "cv_en": {{"header": {{}}, "summary": "", "skills": [], "experience": [], "education": [], "projects": []}},
  "cv_de": {{"header": {{}}, "summary": "", "skills": [], "experience": [], "education": [], "projects": []}},
  "cover_letter_en": "full letter",
  "cover_letter_de": "full letter",
  "external_prompt": "long reusable prompt"
}}

Current CV text:
{cv_text}

Job description text:
{jd_text}

Known detected languages:
CV language: {cv_lang}
JD language: {jd_lang}

Accepted suggestions:
{json.dumps(accepted, ensure_ascii=False, indent=2)}

Cover-letter user inputs:
{json.dumps(cover_inputs, ensure_ascii=False, indent=2)}
"""
    return system_prompt, user_prompt

def call_provider_text(provider: BaseProvider, system_prompt: str, user_prompt: str) -> str:
    """
    Ask the provider for plain text instead of JSON.
    """
    if isinstance(provider, MockProvider):
        return ""

    try:
        if isinstance(provider, OpenAIProvider):
            from openai import OpenAI
            client = OpenAI(api_key=provider.api_key)
            response = client.chat.completions.create(
                model=provider.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
            return response.choices[0].message.content or ""

        if isinstance(provider, GeminiProvider):
            import google.generativeai as genai
            genai.configure(api_key=provider.api_key)
            model = genai.GenerativeModel(provider.model)
            result = model.generate_content(system_prompt + "\n\n" + user_prompt)
            return getattr(result, "text", "") or ""

        if isinstance(provider, ClaudeProvider):
            import anthropic
            client = anthropic.Anthropic(api_key=provider.api_key)
            msg = client.messages.create(
                model=provider.model,
                max_tokens=4000,
                temperature=0.2,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return "".join(
                block.text for block in msg.content if getattr(block, "type", None) == "text"
            )

    except Exception as e:
        raise RuntimeError(str(e))

    return ""


def build_final_cv_text_prompt(
    cv_text: str,
    jd_text: str,
    accepted_suggestions: List[Dict[str, Any]],
) -> Tuple[str, str]:
    system_prompt = (
        "You are a senior multilingual CV writer. "
        "The CV may be in German or English. The job description may be in German or English. "
        "Understand both languages. Never invent facts. "
        "Write polished final CVs in English and German. "
        "Return plain text only, no JSON, no markdown code fences."
    )

    user_prompt = f"""
Create final CV versions in BOTH English and German.

Rules:
1. Do not invent any experience, dates, skills, metrics, or achievements.
2. Only use facts already present in the CV and accepted suggestions.
3. Improve wording, clarity, ATS alignment, and professionalism.
4. Keep the writing natural and recruiter-friendly.
5. Output plain text only.

Original CV:
{cv_text}

Job Description:
{jd_text}

Accepted Suggestions:
{json.dumps(accepted_suggestions, ensure_ascii=False, indent=2)}

Return in this exact format:

=== FINAL CV ENGLISH ===
<final CV in English>

=== FINAL CV GERMAN ===
<final CV in German>
"""
    return system_prompt, user_prompt


def build_cover_letter_text_prompt(
    cv_text: str,
    jd_text: str,
    accepted_suggestions: List[Dict[str, Any]],
    cover_inputs: Dict[str, str],
) -> Tuple[str, str]:
    system_prompt = (
        "You are a senior multilingual cover-letter writer. "
        "The CV may be in German or English. The job description may be in German or English. "
        "Understand both languages. Never invent facts. "
        "Write polished final cover letters in English and German. "
        "Return plain text only, no JSON, no markdown code fences."
    )

    user_prompt = f"""
Create final cover letters in BOTH English and German.

Rules:
1. Do not invent experience, achievements, tools, or claims not supported by the CV.
2. Use the user inputs naturally.
3. Tailor both letters to the job description.
4. Make the German version proper business German, not literal translation.
5. Output plain text only.

Original CV:
{cv_text}

Job Description:
{jd_text}

Accepted Suggestions:
{json.dumps(accepted_suggestions, ensure_ascii=False, indent=2)}

Cover Letter Inputs:
{json.dumps(cover_inputs, ensure_ascii=False, indent=2)}

Return in this exact format:

=== COVER LETTER ENGLISH ===
<cover letter in English>

=== COVER LETTER GERMAN ===
<cover letter in German>
"""
    return system_prompt, user_prompt


def build_external_prompt_text_prompt(
    cv_text: str,
    jd_text: str,
    accepted_suggestions: List[Dict[str, Any]],
    cover_inputs: Dict[str, str],
    scores: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    system_prompt = (
        "You are an expert prompt engineer for multilingual CV and cover-letter editing. "
        "Create one long, precise reusable prompt for another LLM. "
        "The prompt must help the external LLM generate highly tailored application documents. "
        "Return plain text only."
    )

    score_block = ""
    if isinstance(scores, dict):
        score_block = f"""
ATS-style evaluation summary:
- ATS Source 1 (Keyword & Parser Fit): {scores.get('ats_source_1', '')}
- ATS Source 2 (Semantic Relevance): {scores.get('ats_source_2', '')}
- ATS Source 3 (Structure & Readability): {scores.get('ats_source_3', '')}
- Workday-style ATS Score: {scores.get('workday_style_score', '')}
- Greenhouse-style ATS Score: {scores.get('greenhouse_style_score', '')}
- Combined ATS Score: {scores.get('final_score', '')}

Found keywords:
{", ".join(scores.get("found_keywords", [])) if scores.get("found_keywords") else "None"}

Missing keywords:
{", ".join(scores.get("missing_keywords", [])) if scores.get("missing_keywords") else "None"}

Structure notes:
{"; ".join(scores.get("structure_notes", [])) if scores.get("structure_notes") else "None"}
"""

    user_prompt = f"""
Write one reusable master prompt for OpenAI, Gemini, or Claude.

The prompt must instruct the external AI to:
- understand a CV in German or English
- understand a job description in German or English
- preserve facts only
- improve ATS alignment truthfully
- actively apply the accepted suggestions
- address weak ATS areas where possible without inventing facts
- write final CV in English
- write final CV in German
- write cover letter in English
- write cover letter in German
- use accepted suggestions and user inputs naturally
- avoid JSON
- output clean final application text only

Source CV:
{cv_text}

Source Job Description:
{jd_text}

Accepted Suggestions:
{json.dumps(accepted_suggestions, ensure_ascii=False, indent=2)}

Cover Letter Inputs:
{json.dumps(cover_inputs, ensure_ascii=False, indent=2)}

{score_block}

Return only the reusable master prompt text.
"""
    return system_prompt, user_prompt

def extract_between_markers(text: str, start_marker: str, end_marker: Optional[str] = None) -> str:
    if not text:
        return ""
    start_idx = text.find(start_marker)
    if start_idx == -1:
        return ""
    start_idx += len(start_marker)

    if end_marker:
        end_idx = text.find(end_marker, start_idx)
        if end_idx == -1:
            end_idx = len(text)
    else:
        end_idx = len(text)

    return text[start_idx:end_idx].strip()

def build_application_package(
    cv: Dict[str, Any],
    jd: Dict[str, Any],
    suggestions: List[Dict[str, Any]],
    accepted_ids: List[str],
    provider: BaseProvider,
    cover_inputs: Dict[str, str],
    scores: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    base_en = apply_suggestions(cv, suggestions, accepted_ids, language="en")
    base_de = apply_suggestions(cv, suggestions, accepted_ids, language="de")

    fallback = {
        "detected": {
            "cv_language": cv.get("language", "en"),
            "jd_language": jd.get("language", "en"),
        },
        "cv_en": base_en,
        "cv_de": base_de,
        "cv_en_text": structured_cv_to_text(base_en),
        "cv_de_text": structured_cv_to_text(base_de),
        "cover_letter_en": "",
        "cover_letter_de": "",
        "external_prompt": "",
    }

    if isinstance(provider, MockProvider):
        fallback["external_prompt"] = "Add your API key to generate bilingual final CVs and cover letters."
        return fallback

    accepted = [s for s in suggestions if isinstance(s, dict) and s.get("id") in accepted_ids]

    try:
        # STEP 1: FINAL CVS AS PLAIN TEXT
        cv_system, cv_user = build_final_cv_text_prompt(
            cv["raw_text"],
            jd["raw_text"],
            accepted,
        )
        cv_result = call_provider_text(provider, cv_system, cv_user)

        cv_en_text = extract_between_markers(
            cv_result,
            "=== FINAL CV ENGLISH ===",
            "=== FINAL CV GERMAN ===",
        )
        cv_de_text = extract_between_markers(
            cv_result,
            "=== FINAL CV GERMAN ===",
            None,
        )

        # STEP 2: FINAL COVER LETTERS AS PLAIN TEXT
        cl_system, cl_user = build_cover_letter_text_prompt(
            cv["raw_text"],
            jd["raw_text"],
            accepted,
            cover_inputs,
        )
        cl_result = call_provider_text(provider, cl_system, cl_user)

        cover_letter_en = extract_between_markers(
            cl_result,
            "=== COVER LETTER ENGLISH ===",
            "=== COVER LETTER GERMAN ===",
        )
        cover_letter_de = extract_between_markers(
            cl_result,
            "=== COVER LETTER GERMAN ===",
            None,
        )

        # STEP 3: EXTERNAL MASTER PROMPT
        ep_system, ep_user = build_external_prompt_text_prompt(
            cv["raw_text"],
            jd["raw_text"],
            accepted,
            cover_inputs,
            scores,
        )
        external_prompt = call_provider_text(provider, ep_system, ep_user).strip()

        result = {
            "detected": {
                "cv_language": cv.get("language", "en"),
                "jd_language": jd.get("language", "en"),
            },
            "cv_en": base_en,
            "cv_de": base_de,
            "cv_en_text": cv_en_text or structured_cv_to_text(base_en),
            "cv_de_text": cv_de_text or structured_cv_to_text(base_de),
            "cover_letter_en": cover_letter_en,
            "cover_letter_de": cover_letter_de,
            "external_prompt": external_prompt,
        }

        return result

    except Exception as e:
        st.warning(f"Final bilingual generation failed. Using fallback CVs only. Details: {e}")
        return fallback
# =============================
# RENDERING / EXPORT
# =============================
def render_html(cv: Dict[str, Any], labels: Dict[str, str]) -> str:
    if jinja2 is None:
        raise RuntimeError("jinja2 is not installed.")
    env = jinja2.Environment(autoescape=True)
    template = env.from_string(DEFAULT_HTML_TEMPLATE)
    return template.render(cv=cv, labels=labels)


def save_html_output(html_content: str, workdir: Path, filename: str) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / filename
    path.write_text(html_content, encoding="utf-8")
    return path


def build_pdf_package(package: Dict[str, Any], output_path: Path) -> Path:
    if SimpleDocTemplate is None:
        raise RuntimeError("reportlab is not installed.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
    )
    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    body.fontSize = 10
    body.leading = 13
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    small = ParagraphStyle("Small", parent=body, fontSize=9, leading=12)
    story = []
    for title, cv_key, cl_key in [
        ("CV (English)", "cv_en", "cover_letter_en"),
        ("CV (German)", "cv_de", "cover_letter_de"),
    ]:
        cv = package.get(cv_key, {}) if isinstance(package.get(cv_key, {}), dict) else {}
        hdr = cv.get("header", {}) if isinstance(cv.get("header", {}), dict) else {}
        story.append(Paragraph(title, h1))
        story.append(Paragraph(f"<b>{html_escape(hdr.get('name', ''))}</b>", body))
        meta = " | ".join([x for x in [hdr.get("email", ""), hdr.get("phone", ""), hdr.get("location", "")] if x])
        if meta:
            story.append(Paragraph(html_escape(meta), small))
        if cv.get("summary"):
            story.append(Paragraph("Summary / Profil", h2))
            story.append(Paragraph(html_escape(cv.get("summary", "")), body))
        if cv.get("skills"):
            story.append(Paragraph("Skills / Kenntnisse", h2))
            story.append(Paragraph(html_escape(" • ".join(ensure_list_of_strings(cv.get("skills", [])))), body))
        if cv.get("experience"):
            story.append(Paragraph("Experience / Erfahrung", h2))
            for job in cv.get("experience", []):
                if not isinstance(job, dict):
                    continue
                title_line = " — ".join([x for x in [str(job.get("title", "")), str(job.get("company", ""))] if x])
                date_line = str(job.get("date", ""))
                story.append(Paragraph(html_escape(f"{title_line}    {date_line}"), body))
                for b in ensure_list_of_strings(job.get("bullets", [])):
                    story.append(Paragraph(html_escape(f"• {b}"), small))
        if cv.get("education"):
            story.append(Paragraph("Education / Ausbildung", h2))
            for edu in cv.get("education", []):
                if not isinstance(edu, dict):
                    continue
                line = " — ".join([x for x in [str(edu.get("degree", "")), str(edu.get("school", ""))] if x])
                story.append(Paragraph(html_escape(f"{line}    {edu.get('date', '')}"), body))
                details = normalize_space(str(edu.get("details", "")))
                if details:
                    story.append(Paragraph(html_escape(details), small))
        if package.get(cl_key):
            story.append(Paragraph("Cover Letter / Anschreiben", h2))
            for para in str(package.get(cl_key, "")).split("\n\n"):
                if normalize_space(para):
                    story.append(Paragraph(html_escape(para), body))
        story.append(PageBreak())
    doc.build(story)
    return output_path


# =============================
# UI STATE
# =============================
def init_state():
    defaults = {
        "cv_text": "",
        "jd_text": "",
        "cv_struct": None,
        "jd_struct": None,
        "scores": None,
        "suggestions": [],
        "accepted_ids": [],
        "package": None,
        "html_en": "",
        "html_de": "",
        "pdf_bytes": None,
        "compile_log": "",
        "external_prompt": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def render_sidebar() -> Dict[str, Any]:
    with st.sidebar:
        st.header("Settings")
        provider_name = st.selectbox("AI provider", ["mock", "gemini", "openai", "claude"], index=1)
        api_key = st.text_input("API key", type="password", help="Use your own provider key. It stays in this session only.")
        model_defaults = {
            "mock": "none",
            "openai": "gpt-4.1-mini",
            "gemini": "gemini-2.5-flash",
            "claude": "claude-3-5-sonnet-latest",
        }
        model = st.text_input("Model", value=model_defaults.get(provider_name, ""))
        truth_mode = st.selectbox("Truth mode", ["Conservative", "Balanced", "Aggressive"], index=0)
        output_mode = st.selectbox("Output language", ["Both English and German", "English only", "German only"], index=0)
        st.markdown("### Cover Letter Inputs")
        motivation = st.text_area("Why this company / role?", height=100)
        availability = st.text_input("Availability")
        visa_status = st.text_input("Visa / work permit (optional)")
        tone = st.selectbox("Cover letter tone", ["Formal", "Confident", "Enthusiastic"], index=0)
        extra_notes = st.text_area("Extra notes for the cover letter", height=90)
        return {
            "provider_name": provider_name,
            "api_key": api_key,
            "model": model,
            "truth_mode": truth_mode,
            "output_mode": output_mode,
            "cover_inputs": {
                "motivation": motivation,
                "availability": availability,
                "visa_status": visa_status,
                "tone": tone,
                "extra_notes": extra_notes,
            },
        }
def render_workflow_indicator():
    steps = [
        ("Analyze CV + JD", st.session_state.get("scores") is not None),
        ("Build bilingual package", st.session_state.get("package") is not None),
        ("Render previews + PDF", bool(st.session_state.get("html_en") or st.session_state.get("html_de"))),
    ]

    completed = sum(1 for _, done in steps if done)
    progress_value = completed / len(steps)

    st.markdown("### Workflow Progress")
    st.progress(progress_value)

    cols = st.columns(len(steps))
    for col, (label, done) in zip(cols, steps):
        if done:
            col.success(label)
        else:
            col.info(label)

def build_external_llm_edit_prompt(
    current_cv_text: str,
    jd_text: str,
    suggestions: List[Dict[str, Any]],
    accepted_ids: List[str],
    final_package: Optional[Dict[str, Any]],
    cover_inputs: Dict[str, str],
    scores: Optional[Dict[str, Any]] = None,
) -> str:
    accepted = [s for s in suggestions if isinstance(s, dict) and s.get("id") in accepted_ids]

    accepted_lines = []
    for idx, s in enumerate(accepted, start=1):
        accepted_lines.append(
            f"{idx}. Section: {s.get('section', '')}\n"
            f"   Type: {s.get('type', '')}\n"
            f"   Reason EN: {s.get('reason_en', '')}\n"
            f"   Reason DE: {s.get('reason_de', '')}\n"
            f"   Old text: {s.get('old_text', '')}\n"
            f"   Suggested EN: {s.get('suggested_text_en', '')}\n"
            f"   Suggested DE: {s.get('suggested_text_de', '')}\n"
            f"   Target path: {s.get('target_path', '')}"
        )

    accepted_text = "\n\n".join(accepted_lines) if accepted_lines else "No accepted suggestions provided."

    score_block = ""
    if isinstance(scores, dict):
        score_block = f"""
ATS-style evaluation summary:
- ATS Source 1 (Keyword & Parser Fit): {scores.get('ats_source_1', '')}
- ATS Source 2 (Semantic Relevance): {scores.get('ats_source_2', '')}
- ATS Source 3 (Structure & Readability): {scores.get('ats_source_3', '')}
- Workday-style ATS Score: {scores.get('workday_style_score', '')}
- Greenhouse-style ATS Score: {scores.get('greenhouse_style_score', '')}
- Combined ATS Score: {scores.get('final_score', '')}

Found keywords:
{", ".join(scores.get("found_keywords", [])) if scores.get("found_keywords") else "None"}

Missing keywords:
{", ".join(scores.get("missing_keywords", [])) if scores.get("missing_keywords") else "None"}

Structure notes:
{"; ".join(scores.get("structure_notes", [])) if scores.get("structure_notes") else "None"}
"""

    return f"""You are an expert prompt engineer for multilingual CV and cover-letter editing, acting as an advanced LLM.

Your task is to create final polished application documents in BOTH English and German.

Critical rules:
1. Do not invent any experience, dates, achievements, tools, certifications, or metrics.
2. Only use facts already present in the original CV and the accepted suggestions.
3. Improve wording, clarity, ATS alignment, grammar, structure, and professionalism.
4. Keep the writing natural, concise, recruiter-friendly, and job-specific.
5. Avoid robotic wording, keyword stuffing, vague claims, and awkward phrasing.
6. Apply the accepted suggestions actively and faithfully, not passively.
7. Use the ATS-style evaluation summary to strengthen weak areas and preserve strong areas.
8. Prioritize the missing keywords and structure weaknesses where they can be addressed truthfully.
9. If a suggestion conflicts with the original CV facts, preserve the original facts.
10. Do NOT return JSON.
11. Do NOT wrap the answer in code fences.

Job Description:
{jd_text}

Original CV:
{current_cv_text}

{score_block}

Accepted suggestions that must be reflected where appropriate:
{accepted_text}

Cover Letter Inputs:
Motivation: {cover_inputs.get('motivation', '')}
Availability: {cover_inputs.get('availability', '')}
Visa / Work Permit: {cover_inputs.get('visa_status', '')}
Tone: {cover_inputs.get('tone', '')}
Extra Notes: {cover_inputs.get('extra_notes', '')}

Return the output in this exact order:

CV - English

<final CV in English>

CV - German

<final CV in German>

Cover Letter - English

<final cover letter in English>

Cover Letter - German

<final cover letter in German>

Important output constraints:
- Write complete, application-ready content
- Keep section structure clear in both CV versions
- Use polished bullet points in the CVs
- Tailor the cover letters to the job and company
- The German cover letter must read like proper business German, not literal translation
"""
# =============================
# MAIN UI
# =============================
def main():
    init_state()
    settings = render_sidebar()

    st.title("CV Tailor Studio")
    st.caption(
        "Upload a CV in English or German and paste a job description in English or German. "
        "The app detects both languages, generates bilingual suggestions, bilingual CV outputs, "
        "and bilingual cover letters. It can also generate a reusable external AI prompt."
    )

    top_left, top_right = st.columns(2)

    # =========================
    # TOP LEFT: INPUTS
    # =========================
    with top_left:
        st.subheader("Inputs")

        jd_text = st.text_area(
            "Job Description",
            value=st.session_state["jd_text"],
            height=260,
            placeholder="Paste the job description here...",
        )

        cv_file = st.file_uploader(
            "Current CV (PDF / DOCX / TXT)",
            type=["pdf", "docx", "txt"],
            key="cv_upload",
        )

        if cv_file is not None:
            try:
                st.session_state["cv_text"] = read_text_file(cv_file)
                st.success("CV loaded.")
            except Exception as e:
                st.error(f"Could not read CV: {e}")

        st.session_state["jd_text"] = jd_text

        st.markdown("### CV text")
        st.text_area(
            "",
            value=st.session_state["cv_text"],
            height=260,
            key="cv_text_view",
        )

        if st.button("1) Analyze CV + JD", use_container_width=True):
            if not st.session_state["cv_text"].strip() or not st.session_state["jd_text"].strip():
                st.error("Please provide both the CV and the job description.")
            else:
                cv_struct = parse_cv_heuristic(st.session_state["cv_text"])
                jd_struct = parse_job_description(st.session_state["jd_text"])
                scores = composite_scores(cv_struct, jd_struct)
                provider = make_provider(
                    settings["provider_name"],
                    settings["api_key"],
                    settings["model"],
                )
                suggestions = generate_suggestions(
                    cv_struct,
                    jd_struct,
                    provider,
                    settings["truth_mode"],
                    scores,
                )

                st.session_state.update({
                    "cv_struct": cv_struct,
                    "jd_struct": jd_struct,
                    "scores": scores,
                    "suggestions": suggestions,
                    "accepted_ids": [],
                    "package": None,
                    "html_en": "",
                    "html_de": "",
                    "pdf_bytes": None,
                    "compile_log": "",
                    "external_prompt": "",
                })
                st.success("Analysis complete.")

    # =========================
    # TOP RIGHT: WORKFLOW
    # =========================
    with top_right:
        st.subheader("Workflow")
        render_workflow_indicator()

        scores = st.session_state.get("scores")
        if scores:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("ATS 1", f"{scores['ats_source_1']}")
            c2.metric("ATS 2", f"{scores['ats_source_2']}")
            c3.metric("ATS 3", f"{scores['ats_source_3']}")
            c4.metric("Combined", f"{scores['final_score']}")

            st.caption(
                f"Workday-style: {scores['workday_style_score']} | "
                f"Greenhouse-style: {scores['greenhouse_style_score']}"
            )

            if st.session_state.get("cv_struct") and st.session_state.get("jd_struct"):
                st.caption(
                    f"Detected languages — CV: {st.session_state['cv_struct'].get('language', 'en').upper()} | "
                    f"JD: {st.session_state['jd_struct'].get('language', 'en').upper()}"
                )

            with st.expander("Keyword analysis", expanded=False):
                st.write("Found keywords:", ", ".join(scores.get("found_keywords", [])) or "None")
                st.write("Missing keywords:", ", ".join(scores.get("missing_keywords", [])) or "None")

            with st.expander("Structure notes", expanded=False):
                for note in scores.get("structure_notes", []):
                    st.write(f"- {note}")

        if st.button("2) Build final bilingual CV + cover letter", use_container_width=True):
            if not st.session_state.get("cv_struct"):
                st.error("Analyze first.")
            else:
                provider = make_provider(
                    settings["provider_name"],
                    settings["api_key"],
                    settings["model"],
                )

                package = build_application_package(
                    st.session_state["cv_struct"],
                    st.session_state["jd_struct"],
                    st.session_state.get("suggestions", []),
                    st.session_state.get("accepted_ids", []),
                    provider,
                    settings["cover_inputs"],
                    st.session_state.get("scores", {}),
                )
                st.session_state["package"] = package
                st.session_state["external_prompt"] = package.get("external_prompt", "")
                st.success("Bilingual application package created.")

        if st.button("3) Render previews + PDF", use_container_width=True):
            package = st.session_state.get("package")
            if not package:
                st.error("Build the bilingual application package first.")
            else:
                try:
                    run_dir = OUTPUT_DIR / f"run_{uuid.uuid4().hex[:8]}"

                    html_en = render_html(
                        package.get("cv_en", {}),
                        {
                            "profile": "Profile",
                            "skills": "Skills",
                            "experience": "Experience",
                            "education": "Education",
                            "projects": "Projects",
                        },
                    )

                    html_de = render_html(
                        package.get("cv_de", {}),
                        {
                            "profile": "Profil",
                            "skills": "Kenntnisse",
                            "experience": "Erfahrung",
                            "education": "Ausbildung",
                            "projects": "Projekte",
                        },
                    )

                    save_html_output(html_en, run_dir, "cv_en.html")
                    save_html_output(html_de, run_dir, "cv_de.html")

                    pdf_path = build_pdf_package(package, run_dir / "application_package.pdf")

                    st.session_state["html_en"] = html_en
                    st.session_state["html_de"] = html_de
                    st.session_state["pdf_bytes"] = pdf_path.read_bytes()
                    st.session_state["compile_log"] = f"HTML and PDF saved in {run_dir}"

                    st.success("Previews and PDF created.")
                except Exception as e:
                    st.error(f"Render failed: {e}")

        package = st.session_state.get("package")
        if package:
            with st.expander("Package JSON", expanded=False):
                st.json(package)

            if package.get("cv_en_text"):
                with st.expander("Final CV Text (English)", expanded=False):
                    st.text_area(
                        "",
                        value=package.get("cv_en_text", ""),
                        height=320,
                        key="final_cv_text_en",
                    )

            if package.get("cv_de_text"):
                with st.expander("Final CV Text (German)", expanded=False):
                    st.text_area(
                        "",
                        value=package.get("cv_de_text", ""),
                        height=320,
                        key="final_cv_text_de",
                    )

            if st.session_state.get("external_prompt"):
                with st.expander("Prompt to edit with external AI", expanded=True):
                    st.text_area(
                        "External AI prompt",
                        value=st.session_state["external_prompt"],
                        height=350,
                    )

            mode = settings["output_mode"]

            if mode in ["Both English and German", "English only"]:
                with st.expander("Cover Letter (English)", expanded=False):
                    st.text_area(
                        "",
                        value=package.get("cover_letter_en", ""),
                        height=220,
                        key="cl_en",
                    )

            if mode in ["Both English and German", "German only"]:
                with st.expander("Anschreiben (German)", expanded=False):
                    st.text_area(
                        "",
                        value=package.get("cover_letter_de", ""),
                        height=220,
                        key="cl_de",
                    )

        if st.session_state.get("compile_log"):
            with st.expander("Compile log", expanded=False):
                st.text(st.session_state["compile_log"])

    # =========================
    # FULL WIDTH: SUGGESTIONS
    # =========================
    st.markdown("---")
    st.subheader("Suggestions")

    suggestions = st.session_state.get("suggestions", [])
    accepted_ids = set(st.session_state.get("accepted_ids", []))

    select_all = st.toggle(
        "Select all suggestions",
        value=len(suggestions) > 0 and len(accepted_ids) == len(suggestions),
    )

    if suggestions:
        new_selected: List[str] = []

        for i, s in enumerate(suggestions):
            with st.container(border=True):
                st.write(f"**{i+1}. {s.get('type', 'suggestion')}**")
                st.write(f"Section: `{s.get('section', '')}`")
                st.write(f"Reason (EN): {s.get('reason_en', '')}")
                st.write(f"Reason (DE): {s.get('reason_de', '')}")

                if s.get("old_text"):
                    st.write("**Old:**")
                    st.code(s.get("old_text", ""), language="text")

                st.write("**Suggested (EN):**")
                s["suggested_text_en"] = st.text_area(
                    f"en_{s['id']}",
                    value=s.get("suggested_text_en", ""),
                    height=90,
                    label_visibility="collapsed",
                )

                st.write("**Suggested (DE):**")
                s["suggested_text_de"] = st.text_area(
                    f"de_{s['id']}",
                    value=s.get("suggested_text_de", ""),
                    height=90,
                    label_visibility="collapsed",
                )

                default_checked = True if select_all else (s.get("id") in accepted_ids)
                take = st.checkbox(
                    "Accept this suggestion",
                    key=f"chk_{s['id']}",
                    value=default_checked,
                )

                if take:
                    new_selected.append(s["id"])

                if s.get("tags"):
                    st.caption("Tags: " + ", ".join(s.get("tags", [])))

        st.session_state["accepted_ids"] = new_selected
    else:
        st.info("Suggestions will appear here after analysis.")

    # =========================
    # FULL WIDTH: PREVIEW / DOWNLOADS
    # =========================
    st.markdown("---")
    st.subheader("Preview / Downloads")

    package = st.session_state.get("package")
    if package:
        if st.session_state.get("pdf_bytes"):
            st.download_button(
                "Download PDF package",
                data=st.session_state["pdf_bytes"],
                file_name="application_package.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

        st.download_button(
            "Download package JSON",
            data=json.dumps(package, ensure_ascii=False, indent=2),
            file_name="application_package.json",
            mime="application/json",
            use_container_width=True,
        )

        if st.session_state.get("external_prompt"):
            st.download_button(
                "Download external AI prompt",
                data=st.session_state["external_prompt"],
                file_name="external_application_prompt.txt",
                mime="text/plain",
                use_container_width=True,
            )

        mode = settings["output_mode"]

        if mode in ["Both English and German", "English only"] and st.session_state.get("html_en"):
            st.markdown("#### CV Preview (English)")
            st.components.v1.html(st.session_state["html_en"], height=520, scrolling=True)

        if mode in ["Both English and German", "German only"] and st.session_state.get("html_de"):
            st.markdown("#### CV Preview (German)")
            st.components.v1.html(st.session_state["html_de"], height=520, scrolling=True)
    else:
        st.info("Build the bilingual package to view previews and downloads.")

    with st.expander("How to run this app", expanded=False):
        st.code(
            """
pip install streamlit pdfplumber python-docx jinja2 google-generativeai openai anthropic reportlab
streamlit run app.py
            """.strip(),
            language="bash",
        )

if __name__ == "__main__":
    main()
