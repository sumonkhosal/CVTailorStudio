# CVTailorStudio
AI CV Tailor Tool (Local App – BYO API Key)

A lightweight Python application that helps you **analyze, improve, and tailor your CV** based on a job description using AI.

This tool supports multiple AI providers and follows a **Bring Your Own API Key (BYO-Key)** approach, meaning **you stay in control of your usage and costs**.

---

## What This App Does

- 📄 Reads your CV (PDF / DOCX / Text)
- 🧾 Takes a job description as input
- 🔍 Analyzes gaps between your CV and the job requirements
- 🧠 Uses AI to:
  - Improve your CV content
  - Align it with the job description
  - Generate a tailored version
  - Create a cover letter
- 🌍 Supports bilingual output (English / German)

---

## BYO API Key (Important)

This app **does NOT include or store any API keys**.

You must provide your own key for:
- OpenAI
- Google Gemini
- Anthropic Claude

👉 Your key is:
- Used only during runtime
- Not stored anywhere
- Not shared

This makes the tool:
- ✅ Safe
- ✅ Cost-efficient
- ✅ Fully user-controlled

---

## How It Works (Behind the Scenes)

1. **Input Processing**
   - CV is parsed using:
     - `pdfplumber` (PDF)
     - `python-docx` (DOCX)
   - Job description is taken as raw text

2. **Analysis**
   - The app compares CV content with job requirements
   - Identifies missing keywords and skills

3. **AI Generation**
   - Sends structured prompts to the selected AI model
   - Generates:
     - Improved CV
     - Tailored CV
     - Cover letter

4. **Output**
   - Structured text output
   - Optional export (PDF/DOCX depending on setup)

---

## 🛠 Requirements

Install dependencies:

```bash
pip install -r requirements.txt
