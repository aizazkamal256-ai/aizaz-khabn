# 📄 ATS Resume Analyzer

Upload your resume and get an **ATS score out of 100**, a score breakdown, missing keywords,
concrete improvements, and an **AI-rewritten ATS-friendly resume** you can download as DOCX or TXT.

Built with [Streamlit](https://streamlit.io) and the [Groq API](https://console.groq.com).

## Features

- Upload **PDF, DOCX or TXT** resumes
- Optional **job description** input for a tailored keyword match
- ATS score + 5-category breakdown (keywords, formatting, impact, skills, readability)
- Strengths, weaknesses, missing keywords and actionable fixes
- Improved resume (editable in the app) with DOCX / TXT download
- The rewrite never invents facts; unknown numbers appear as `[add metric]` placeholders

## Project structure

```
.
├── app.py             # Streamlit app
├── requirements.txt   # Python dependencies
└── README.md
```

## Run locally

1. Install Python 3.10 or newer.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Get a free API key at <https://console.groq.com/keys>.
4. Provide the key in **one** of these ways:
   - Paste it into the sidebar when the app opens, **or**
   - Create `.streamlit/secrets.toml`:
     ```toml
     GROQ_API_KEY = "your_key_here"
     ```
   - or set an environment variable: `export GROQ_API_KEY=your_key_here`
5. Start the app:
   ```bash
   streamlit run app.py
   ```

## Choosing the Groq model

The default model is `openai/gpt-oss-120b`. Groq retires models from time to time
(for example `llama-3.3-70b-versatile` was retired on 16 Aug 2026), so you can change the model
without editing code by adding a `GROQ_MODEL` secret or environment variable.
See the current list at <https://console.groq.com/docs/models>.

## Push to GitHub (using the website, no command line)

1. Sign in at <https://github.com> and click **+ → New repository**.
2. Name it (e.g. `ats-resume-analyzer`), choose **Public**, and click **Create repository**.
3. On the new repo page click **uploading an existing file**.
4. Drag in `app.py`, `requirements.txt` and `README.md`, then click **Commit changes**.
5. **Never upload your API key or `.streamlit/secrets.toml`.**

## Deploy on Streamlit Community Cloud

1. Go to <https://share.streamlit.io> and sign in with GitHub.
2. Click **Create app** → **Deploy a public app from GitHub**.
3. Select your repository, branch `main`, and main file path `app.py`.
4. Click **Advanced settings → Secrets** and paste:
   ```toml
   GROQ_API_KEY = "your_groq_api_key_here"
   ```
5. Click **Deploy**. After a minute or two you get a public URL like
   `https://your-app-name.streamlit.app`.

To update the app later, edit a file on GitHub and commit. Streamlit redeploys automatically.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Very little text could be extracted" | Your PDF is probably a scanned image. Export a text-based PDF or use DOCX. |
| `model_decommissioned` / model not found | Set `GROQ_MODEL` to a current model from the Groq docs. |
| Invalid API key | Re-create the key in the Groq console and update your secret. |
| `ModuleNotFoundError` on deploy | Make sure `requirements.txt` is in the repo root. |

## Disclaimer

The ATS score is an AI-based estimate, not the output of any specific employer's ATS.
Always review the rewritten resume for accuracy before sending it.
