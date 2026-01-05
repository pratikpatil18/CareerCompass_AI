import os
import json
import fitz
import pandas as pd
import requests
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import re

# ================= CONFIG ==================
API_KEY = "AIzaSyC3V6H8Fx8MjmJ25UhZaOJvMoCdtdoqrqI"
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ================= FASTAPI =================
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ================= LOAD EXCEL =================
def load_company_data(filepath="company_data_no_duplicates.xlsx"):
    try:
        df = pd.read_excel(filepath).fillna("")
        return df.to_dict("records")
    except:
        return []

COMPANIES = load_company_data()

COURSE_LINKS = {
    "Python": "https://www.coursera.org/specializations/python",
    "Java": "https://www.coursera.org/specializations/java-programming",
    "C++": "https://www.coursera.org/learn/c-plus-plus-introduction",
    "Cloud": "https://www.coursera.org/professional-certificates/google-cloud-computing",
    "Data Science": "https://www.coursera.org/professional-certificates/ibm-data-science",
    "Machine Learning": "https://www.coursera.org/specializations/machine-learning-introduction",
    "AWS": "https://www.coursera.org/learn/aws-fundamentals",
    "Azure": "https://www.coursera.org/learn/microsoft-azure-fundamentals",
    "React": "https://www.coursera.org/learn/react-basics",
    "SQL": "https://www.coursera.org/learn/sql-for-data-science"
}

# ================= CORE FUNCTIONS =================


def extract_json(text):
    try:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group())
        return None
    except:
        return None


def extract_text_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        return "".join(page.get_text() for page in doc)
    except:
        return None

def call_generative_api(prompt):
    url = "https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent"

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": API_KEY
    }

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ]
    }

    r = requests.post(url, headers=headers, json=payload)

    try:
        raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        raw = raw.replace("```json", "").replace("```", "").replace("`", "").strip()

        # Extract first valid JSON object from response
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == -1:
            raise ValueError("No JSON found")

        json_text = raw[start:end]
        return json.loads(json_text)

    except Exception as e:
        print("Gemini RAW OUTPUT:\n", r.text)
        return None


def parse_resume(resume_text):
    prompt = f"""
    Extract the following as STRICT JSON:
    name (string),
    skills (object of category -> list),
    projects (list of objects with title and description),
    education (list of objects with degree, institution, year)

    Resume text:
    {resume_text}
    """
    return call_generative_api(prompt)


def calculate_match_score(resume, company):
    if not resume or "skills" not in resume:
        return 0

    resume_skills = {s.lower() for v in resume["skills"].values() for s in v}
    tech = {s.lower() for s in company.get("Major_Tech_Stack", "").split(",")}
    keywords = {s.lower() for s in company.get("Essential_Keywords", "").split(",")}

    return len(resume_skills & tech) * 5 + len(resume_skills & keywords) * 2

def generate_report(resume, company):
    prompt = f"""
    You are a career counselor. Generate JSON with:
    match_summary, strengths, improvement_areas (text, skill), interview_tips.

    Resume: {json.dumps(resume)}
    Company: {json.dumps(company)}
    """
    return call_generative_api(prompt)


# ================= ROUTES =================

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "error": None})

@app.post("/", response_class=HTMLResponse)
async def analyze(request: Request, resumeFile: UploadFile = File(...)):
    path = f"{UPLOAD_FOLDER}/{resumeFile.filename}"
    with open(path, "wb") as f:
        f.write(await resumeFile.read())

    resume_text = extract_text_from_pdf(path)
    if not resume_text:
        return templates.TemplateResponse("index.html", {"request": request, "error": "PDF could not be read"})

    parsed = parse_resume(resume_text)
    if not parsed or "skills" not in parsed:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "error": "AI could not understand this resume. Try a different PDF."
        })

    results = []
    for company in COMPANIES:
        results.append({
            "company_name": company.get("Company Name"),
            "match_score": calculate_match_score(parsed, company),
            "website_url": company.get("Website_URL", "#")
        })

    results = sorted(results, key=lambda x: x["match_score"], reverse=True)

    report = None
    if results and results[0]["match_score"] > 0:
        top_company = next(c for c in COMPANIES if c["Company Name"] == results[0]["company_name"])
        report = generate_report(parsed, top_company)

    os.remove(path)

    return templates.TemplateResponse("results.html", {
        "request": request,
        "candidate_name": parsed.get("name", "Candidate"),
        "top_matches": results[:6],
        "report": report,
        "top_company_name": results[0]["company_name"] if results else "N/A",
        "course_links": COURSE_LINKS
    })
