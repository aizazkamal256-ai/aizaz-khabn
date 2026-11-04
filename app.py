"""
ATS Resume Analyzer
-------------------
Upload a resume (PDF, DOCX or TXT) and get:
  * an ATS score out of 100
  * a score breakdown, strengths and weaknesses
  * missing keywords and concrete improvements
  * a rewritten, ATS-friendly resume you can download

Built with Streamlit + Groq (default model: openai/gpt-oss-120b).
"""

import io
import json
import os
import re

import streamlit as st
from docx import Document
from groq import BadRequestError, Groq
from pypdf import PdfReader

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
# Groq retired llama-3.3-70b-versatile on 16 Aug 2026. You can override the model
# with a GROQ_MODEL secret / environment variable if Groq changes its lineup again.
DEFAULT_MODEL = "openai/gpt-oss-120b"
MAX_RESUME_CHARS = 12000  # keeps the prompt well within the model's limits
MAX_JD_CHARS = 6000
MIN_RESUME_CHARS = 100

SCORE_CATEGORIES = {
    "keywords_match": "Keywords & Relevance",
    "formatting": "Formatting & Structure",
    "experience_impact": "Experience & Impact",
    "skills": "Skills Section",
    "readability": "Readability & Clarity",
}

SYSTEM_PROMPT = """You are an expert ATS (Applicant Tracking System) analyst and professional resume writer.
You will be given a resume and, optionally, a target job description.

Evaluate the resume honestly and strictly, the way a real ATS and a recruiter would.
Do NOT inflate scores. Typical resumes score between 45 and 80.

Respond with ONE valid JSON object only (no markdown, no commentary) using exactly this schema:
{
  "ats_score": <integer 0-100>,
  "score_breakdown": {
    "keywords_match": <integer 0-100>,
    "formatting": <integer 0-100>,
    "experience_impact": <integer 0-100>,
    "skills": <integer 0-100>,
    "readability": <integer 0-100>
  },
  "summary": "<2-3 sentence overall assessment>",
  "strengths": ["<string>", ...],
  "weaknesses": ["<string>", ...],
  "missing_keywords": ["<string>", ...],
  "improvements": ["<specific, actionable suggestion>", ...],
  "improved_resume": "<full rewritten resume as plain text>"
}

Rules for "improved_resume":
- Plain text only. Section headings in UPPERCASE on their own line (e.g. SUMMARY, SKILLS, EXPERIENCE, EDUCATION, PROJECTS).
- Use "- " at the start of each bullet point.
- First line: the candidate's name. Second line: contact details exactly as given in the original.
- Use strong action verbs, keep a clean single-column structure, and weave in relevant keywords naturally.
- NEVER invent employers, job titles, dates, degrees, certifications, or metrics that are not in the original.
  If a bullet would benefit from a number you do not have, use a placeholder such as [add metric].
- Keep all facts from the original resume; only improve wording, ordering and structure.
"""


# ----------------------------------------------------------------------------
# Text extraction
# ----------------------------------------------------------------------------
def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("This PDF is password-protected. Please upload an unlocked copy.")
    pages = [(page.extract_text() or "") for page in reader.pages]
    return "\n".join(pages)


def extract_text_from_docx(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    # Also read tables, since many resume templates put content in tables
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text.strip())
    return "\n".join(parts)


def extract_resume_text(uploaded_file) -> str:
    """Return clean text from an uploaded PDF / DOCX / TXT file."""
    name = uploaded_file.name.lower()
    data = uploaded_file.getvalue()

    if name.endswith(".pdf"):
        text = extract_text_from_pdf(data)
    elif name.endswith(".docx"):
        text = extract_text_from_docx(data)
    elif name.endswith(".txt"):
        text = data.decode("utf-8", errors="ignore")
    else:
        raise ValueError("Unsupported file type. Please upload a PDF, DOCX or TXT file.")

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


# ----------------------------------------------------------------------------
# Groq / LLM
# ----------------------------------------------------------------------------
def get_api_key() -> str:
    """Look for the key in Streamlit secrets, then env vars, then the sidebar."""
    try:
        key = st.secrets.get("GROQ_API_KEY", "")
        if key:
            return key
    except Exception:
        pass  # no secrets.toml present - that's fine
    return os.environ.get("GROQ_API_KEY", "")


def get_model() -> str:
    try:
        model = st.secrets.get("GROQ_MODEL", "")
        if model:
            return model
    except Exception:
        pass
    return os.environ.get("GROQ_MODEL", "") or DEFAULT_MODEL


def parse_json_response(raw: str) -> dict:
    """Parse the model output into a dict, tolerating stray markdown fences."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _clamp_score(value) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return 0


def _as_list(value) -> list:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_result(data: dict) -> dict:
    """Make sure every field exists and has the right type."""
    breakdown = data.get("score_breakdown") or {}
    return {
        "ats_score": _clamp_score(data.get("ats_score")),
        "score_breakdown": {k: _clamp_score(breakdown.get(k)) for k in SCORE_CATEGORIES},
        "summary": str(data.get("summary", "")).strip(),
        "strengths": _as_list(data.get("strengths")),
        "weaknesses": _as_list(data.get("weaknesses")),
        "missing_keywords": _as_list(data.get("missing_keywords")),
        "improvements": _as_list(data.get("improvements")),
        "improved_resume": str(data.get("improved_resume", "")).strip(),
    }


def analyze_resume(api_key: str, resume_text: str, job_description: str = "") -> dict:
    client = Groq(api_key=api_key)

    user_prompt = f"RESUME:\n\"\"\"\n{resume_text[:MAX_RESUME_CHARS]}\n\"\"\"\n\n"
    if job_description.strip():
        user_prompt += (
            f"TARGET JOB DESCRIPTION:\n\"\"\"\n{job_description.strip()[:MAX_JD_CHARS]}\n\"\"\"\n\n"
            "Score keyword relevance against this job description and list the important "
            "keywords from it that are missing from the resume."
        )
    else:
        user_prompt += (
            "No job description was provided. Evaluate the resume for general ATS "
            "compatibility and infer the most likely target role from its content."
        )

    request = dict(
        model=get_model(),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=8000,  # reasoning models spend part of this budget on thinking
    )
    try:
        completion = client.chat.completions.create(
            **request, response_format={"type": "json_object"}
        )
    except BadRequestError:
        # Some models reject JSON mode - retry; the prompt already demands JSON only.
        completion = client.chat.completions.create(**request)

    raw = completion.choices[0].message.content
    if not raw:
        raise ValueError("The model returned an empty response. Please try again.")
    return normalize_result(parse_json_response(raw))


# ----------------------------------------------------------------------------
# Download helpers
# ----------------------------------------------------------------------------
def _is_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return bool(letters) and line.upper() == line and len(line) <= 40 and not line.startswith(("-", "•"))


def resume_to_docx_bytes(resume_text: str) -> bytes:
    """Turn the improved plain-text resume into a simple, ATS-safe DOCX."""
    doc = Document()
    lines = [ln.rstrip() for ln in resume_text.splitlines()]
    first_content_seen = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("- ", "• ", "* ")):
            doc.add_paragraph(stripped[2:].strip(), style="List Bullet")
        elif not first_content_seen:
            doc.add_heading(stripped, level=0)  # candidate name
            first_content_seen = True
        elif _is_heading(stripped):
            doc.add_heading(stripped, level=2)
        else:
            doc.add_paragraph(stripped)
        first_content_seen = True

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------
def score_label(score: int) -> str:
    if score >= 80:
        return "🟢 Excellent"
    if score >= 65:
        return "🟡 Good - room to improve"
    if score >= 50:
        return "🟠 Needs work"
    return "🔴 Weak"


def render_results(result: dict) -> None:
    score = result["ats_score"]

    st.subheader("Your ATS Score")
    col1, col2 = st.columns([1, 2])
    with col1:
        st.metric("ATS Score", f"{score} / 100")
        st.write(score_label(score))
    with col2:
        st.progress(score / 100)
        if result["summary"]:
            st.write(result["summary"])

    st.markdown("#### Score breakdown")
    cols = st.columns(len(SCORE_CATEGORIES))
    for col, (key, label) in zip(cols, SCORE_CATEGORIES.items()):
        col.metric(label, result["score_breakdown"][key])

    tab1, tab2, tab3, tab4 = st.tabs(
        ["✅ Strengths & Weaknesses", "🔑 Missing Keywords", "🛠 Improvements", "📄 Improved Resume"]
    )

    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Strengths**")
            for item in result["strengths"] or ["No specific strengths returned."]:
                st.markdown(f"- {item}")
        with c2:
            st.markdown("**Weaknesses**")
            for item in result["weaknesses"] or ["No specific weaknesses returned."]:
                st.markdown(f"- {item}")

    with tab2:
        if result["missing_keywords"]:
            st.write("Consider adding these (only where they truthfully apply to you):")
            st.markdown(" ".join(f"`{k}`" for k in result["missing_keywords"]))
        else:
            st.success("No major missing keywords found.")

    with tab3:
        for i, item in enumerate(result["improvements"] or ["No suggestions returned."], 1):
            st.markdown(f"**{i}.** {item}")

    with tab4:
        improved = result["improved_resume"]
        if not improved:
            st.warning("The model did not return a rewritten resume. Try running the analysis again.")
        else:
            st.info(
                "Review carefully before sending. Replace any **[add metric]** placeholders "
                "with real numbers, and remove anything that isn't accurate."
            )
            st.text_area("Improved resume (editable)", improved, height=450, key="improved_text")
            edited = st.session_state.get("improved_text", improved)
            d1, d2 = st.columns(2)
            d1.download_button(
                "⬇️ Download as DOCX",
                data=resume_to_docx_bytes(edited),
                file_name="improved_resume.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            d2.download_button(
                "⬇️ Download as TXT",
                data=edited.encode("utf-8"),
                file_name="improved_resume.txt",
                mime="text/plain",
            )


def main() -> None:
    st.set_page_config(page_title="ATS Resume Analyzer", page_icon="📄", layout="wide")
    st.title("📄 ATS Resume Analyzer")
    st.caption("Upload your resume, get an ATS score, actionable fixes, and an improved version.")

    # ---- Sidebar: API key ----
    with st.sidebar:
        st.header("Settings")
        api_key = get_api_key()
        if api_key:
            st.success("Groq API key loaded.")
        else:
            api_key = st.text_input(
                "Groq API key",
                type="password",
                help="Get a free key at https://console.groq.com/keys",
            )
        st.markdown("---")
        st.markdown(
            "**Tips**\n"
            "- Use a text-based PDF or DOCX (not a scanned image).\n"
            "- Paste a job description for a much more accurate keyword score."
        )

    # ---- Inputs ----
    left, right = st.columns(2)
    with left:
        uploaded = st.file_uploader("Upload your resume", type=["pdf", "docx", "txt"])
    with right:
        job_description = st.text_area(
            "Job description (optional)",
            height=150,
            placeholder="Paste the job posting here to tailor the analysis...",
        )

    analyze_clicked = st.button("🔍 Analyze Resume", type="primary", disabled=uploaded is None)

    if analyze_clicked:
        if not api_key:
            st.error("Please enter your Groq API key in the sidebar.")
            return

        try:
            with st.spinner("Reading your resume..."):
                resume_text = extract_resume_text(uploaded)
        except Exception as exc:
            st.error(f"Could not read the file: {exc}")
            return

        if len(resume_text) < MIN_RESUME_CHARS:
            st.error(
                "Very little text could be extracted. If your resume is a scanned image, "
                "export it as a text-based PDF or DOCX and try again."
            )
            return

        try:
            with st.spinner("Analyzing with Groq... this takes a few seconds."):
                result = analyze_resume(api_key, resume_text, job_description)
        except json.JSONDecodeError:
            st.error("The AI returned an unreadable response. Please click Analyze again.")
            return
        except Exception as exc:
            st.error(f"Analysis failed: {exc}")
            return

        st.session_state["result"] = result
        st.session_state.pop("improved_text", None)  # reset editable text for the new analysis

    if "result" in st.session_state:
        render_results(st.session_state["result"])


if __name__ == "__main__":
    main()
