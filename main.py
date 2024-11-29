from fastapi import FastAPI
from pydantic import BaseModel

import uvicorn
import resume_matcher
import logging
logging.basicConfig(level=logging.CRITICAL, format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI()

class ResumeJobMatch(BaseModel):
    resume_url: str
    jd: str

class Resume(BaseModel):
    url: str

class JD(BaseModel):
    jd_text: str


@app.post("/match_resume_to_job")
async def match_resume_to_job(resumeJobMatch: ResumeJobMatch):
    match = resume_matcher.process_single_resume(job_desc=resumeJobMatch.jd, resume_url=resumeJobMatch.resume_url)
    return match

@app.post("/extract_candidate_profile")
async def extract_candidate_profile(resume: Resume):
    text, images = resume_matcher.extract_text_and_image_from_pdf(resume.url)
    candidate_profile = resume_matcher.extract_candidate_profile(text)
    return candidate_profile

@app.post("/extract_job_requirements")
async def extract_job_requirements(jd: JD):
    job_requirements = resume_matcher.extract_job_requirements(jd.jd_text)
    return job_requirements


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=5050)