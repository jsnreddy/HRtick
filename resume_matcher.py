import sys, json, json5
import logging, requests, io
import constants
from pathlib import Path
from PIL import Image
from fastapi import HTTPException
from pathlib import Path
from llm import *
# Initialize logging with more detailed format
logging.basicConfig(level=logging.CRITICAL, format='%(asctime)s - %(levelname)s - %(message)s')


#1 is the biggest redflag - they have high weightage but low score
red_flags = {
    '1': [],
    '2': [],
    '3': []
}
from urllib.parse import urlparse
from os.path import exists
import pytesseract
from pdf2image import convert_from_path
from PyPDF2 import PdfReader

def is_local_file(url):
    url_parsed = urlparse(url)
    if url_parsed.scheme in ('file', ''): # Possibly a local file
        return exists(url_parsed.path)
    return False

def extract_text_and_image_from_pdf(url):
    
    try:
        if is_local_file(url):
            file_path = urlparse(url).path
        else:
            response = requests.get(url)
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to download PDF")
            
            file_path = "./src/temp.pdf"
            with open(file_path, "wb") as f:
                f.write(response.content)
        text = ""
        images = []

        # Extract text from all pages of the PDF using PyPDF2
        reader = PdfReader(file_path)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"

        # Extract images from all pages
        # images = convert_from_path(file_path)
        # for i, img in enumerate(images):
        #     # Convert to grayscale and compress image
        #     img_gray = img.convert('L')
        #     img_buffer = io.BytesIO()
        #     img_gray.save(img_buffer, format='JPEG', quality=51)
        #     img_buffer.seek(0)

        #     # Add image data to images list
        #     images.append(img_buffer.getvalue())

        #     # If text extraction is insufficient, perform OCR
        #     if not text or len(text.strip()) < 500:
        #         ocr_text = pytesseract.image_to_string(Image.open(img_buffer))
        #         text += ocr_text + "\n"

        # if not images:
        #     logging.error(f"No images found in PDF {file_path}")

        return text.strip(), images

    except Exception as e:
        logging.error(f"Error extracting text and image from PDF {file_path}: {str(e)}")
        return "", []

#job description functions
def extract_job_requirements(job_desc, client=None):
    prompt = f"""
    Extract the key requirements from the following job description.

    Job Description:
    {job_desc}

    Provide the output in the following JSON format:
    {{
      "required_experience_years": integer,
      "required_education_level": string,
      "required_skills": [list of strings],
      "optional_skills": [list of strings],
      "certifications_preferred": [list of strings],
      "soft_skills": [list of strings],
      "keywords_to_match": [list of strings],
      "location": {{
        "country": string,
        "city": string
      }},
      "emphasis": {{
        "technical_skills_weight": integer,
        "soft_skills_weight": integer,
        "experience_weight": integer,
        "education_weight": integer,
        "language_proficiency_weight": integer,
        "certifications_weight": integer
      }}
    }}

    Only output valid JSON. 
    You can only speak JSON. You can only output valid JSON. Strictly No explanation, no comments, no intro. No \`\`\`json\`\`\` wrapper.
    """
    response = talk_to_ai(prompt, max_tokens=2000, client=client)
    try:
        if isinstance(response, dict):
            job_requirements = response
        else:
            job_requirements = json.loads(response)
        return job_requirements
    except json.JSONDecodeError as e:
        logging.error(f"Error parsing job requirements: {str(e)}")
        logging.error(f"Response: {response}")
        return None

def rank_job_description(job_desc, client=None):
    criteria = [
        {
            'name': 'Language Proficiency',
            'key': 'language_proficiency',
            'weight': job_desc['emphasis'].get('language_proficiency_weight', 5),
            'description': 'Assign points based on the candidate\'s proficiency in languages relevant to the job.',
            'factors': [
                'Proficiency in required languages',
                'Multilingual abilities relevant to the job'
            ]
        },
        {
            'name': 'Education Level',
            'key': 'education_level',
            'weight': job_desc['emphasis'].get('education_weight', 10),
            'description': 'Assign points based on the candidate\'s highest level of education or equivalent experience.',
            'factors': [
                'Highest education level attained',
                'Relevance of degree to the job',
                'Alternative education paths (certifications, bootcamps, self-learning)'
            ]
        },
        {
            'name': 'Years of Experience',
            'key': 'experience_years',
            'weight': job_desc['emphasis'].get('experience_weight', 20),
            'description': 'Assign points based on the relevance and quality of experience.',
            'factors': [
                'Total years of relevant experience',
                'Quality and relevance of previous roles',
                'Significant achievements in previous positions'
            ]
        },
        {
            'name': 'Technical Skills',
            'key': 'technical_skills',
            'weight': job_desc['emphasis'].get('technical_skills_weight', 50),
            'description': 'Assign points for each required and optional skill, considering proficiency level.',
            'factors': [
                'Proficiency in required technical skills',
                'Proficiency in optional technical skills',
                'Transferable skills and learning ability',
                'Keywords matched in resume'
            ]
        },
        {
            'name': 'Certifications',
            'key': 'certifications',
            'weight': job_desc['emphasis'].get('certifications_weight', 5),
            'description': 'Assign points for each relevant certification.',
            'factors': [
                'Possession of preferred certifications',
                'Equivalent practical experience',
                'Self-learning projects demonstrating expertise'
            ]
        },
        {
            'name': 'Soft Skills',
            'key': 'soft_skills',
            'weight': job_desc['emphasis'].get('soft_skills_weight', 20),
            'description': 'Assign points for each soft skill demonstrated through examples or achievements.',
            'factors': [
                'Demonstrated soft skills in resume',
                'Examples of teamwork, leadership, problem-solving, etc.'
            ]
        },
        {
            'name': 'Location',
            'key': 'location',
            'weight': job_desc['emphasis'].get('location_weight', 50),
            'description': 'Assign points based on the candidate\'s location relative to the job requirements.',
            'factors': [
                'Country match with job location',
                'City match with job location',
                'Willingness to relocate (if mentioned)',
                '0 if specifically requirements prohibit specific locations'
            ]
        }
    ]
    scores = {}
    total_weight = sum(criterion['weight'] for criterion in criteria)
    total_score = 0

    for criterion in criteria:
        prompt = f"""
        Evaluate the job description based on the criterion: "{criterion['name']}".

        Criterion Description:
        {criterion['description']}

        Factors to consider:
        {', '.join(criterion['factors'])}

        Job Description:
        {job_desc}

        Provide your evaluation as an integer score from 0 to 100, where 0 is the lowest and 100 is the highest.
        Only return the integer score, nothing else.
        """

        # Initialize 'score' to 0 before accessing it
        criterion['score'] = 0

        response = talk_fast(prompt, client=client)
        
        if criterion['score'] < 10 and criterion['weight'] >= 20:
            if criterion['weight'] >= 40:
                red_flags['🚩'].append(criterion['name'])
            elif criterion['weight'] >= 30:
                red_flags['📍'].append(criterion['name'])
            else:
                red_flags['⛳'].append(criterion['name'])

        try:
            score = int(str(response).strip())
            criterion['score'] = score
            scores[criterion['key']] = score
            weighted_score = (score * criterion['weight']) / 100
            total_score += weighted_score
            
        except Exception as e:
            criterion['score'] = 0
            scores[criterion['key']] = 0

    overall_score = int((total_score / total_weight) * 100)  # Normalize to 0-100 scale

    # Collect improvement tips
    tips_prompt = f"""
    Based on your evaluation of the job description, provide 3-5 tips for improvement.

    Job Description:
    {job_desc}

    Focus on areas that can be enhanced according to modern best practices.

    Output your response as a JSON array of strings, e.g.:

    [
        "Tip 1",
        "Tip 2",
        "Tip 3"
    ]
    """
    tips_text = talk_fast(tips_prompt, max_tokens=150, client=client)
    try:
        improvement_tips = json5.loads(tips_text)
        if not isinstance(improvement_tips, list):
            raise ValueError("Improvement tips should be a list.")
        # Ensure tips are strings
        improvement_tips = [str(tip) for tip in improvement_tips]
    except Exception as e:
        logging.error(f"Error parsing improvement tips: {str(e)}")
        improvement_tips = []

    result = {
        "scores": scores,
        "overall_score": overall_score,
        "improvement_tips": improvement_tips[:5]  # Limit to 5 tips
    }

    return result

def improve_job_description(job_desc, ranking, client=None):
    prompt = f"""
As a hiring consultant, improve the following job description based on the ranking and improvement tips provided. Maintain the overall structure and key information while addressing the areas for improvement.

Original Job Description:
{job_desc}

Ranking:
{json.dumps(ranking, indent=2)}

Please provide an improved version of the job description that addresses the improvement tips and enhances the areas with lower scores. Output the improved job description as plain text, ready to be saved to a file.
"""

    try:
        improved_desc = talk_to_ai(prompt, max_tokens=1000, client=client)
        return improved_desc.strip() if improved_desc else None
    except Exception as e:
        logging.error(f"Error improving job description: {str(e)}")
        return None

#resume functions
def extract_candidate_profile(resume_text, client=None):
    prompt = f"""
    Analyze the resume and provide the following key information and if any information not available  mark as “NA”

    Resume text :
    {resume_text}

    Provide the output in the following JSON format:
    {{
        “Personal Information”:{{
            “Name”:String,
            “Phone Number ”: integer,
            “Email”: String,
            “location”:String,
            “linkedin”:String,
            “github”:String,
        }}      
        “Work History”:{{
            "TotalWork Experience": integer,
            “Work Experience”: [list of strings]{{
                “Company Name”: String,
                “Role “: String,
                “ Duration”: String,
            }}
        }}
        Projects:{{
            “Total No of Projects:integer,
            Project details”:[list of strings]{{
                "Project Name”:String
                "Project Description”:String,
            }}
        }}
        "Education": String,
        “Skills”: String, 
    }}

    Only output valid JSON. 
    You can only speak JSON. You can only output valid JSON. Strictly No explanation, no comments, no intro. No \`\`\`json\`\`\` wrapper.
    """
    response = talk_to_ai(prompt, max_tokens=2000, client=client)
    try:
        if isinstance(response, dict):
            candidate_profile = response
        else:
            candidate_profile = json.loads(response)
        return candidate_profile
    except json.JSONDecodeError as e:
        logging.error(f"Error parsing job requirements: {str(e)}")
        logging.error(f"Response: {response}")
        return {}

def assess_resume_quality(resume_images, client=None):
    # Ensure resume_images is a list of base64 encoded strings
    if not isinstance(resume_images, list) or not resume_images:
        logging.error("Invalid resume_images format")
        return 0

    # Use only the first image (front page)
    front_page_image = resume_images[0]

    criteria = [
        {
            'name': 'Formatting and Layout',
            'key': 'formatting_layout',
            'weight': 10,
            'description': 'Assess the overall formatting and layout of the resume.',
            'factors': [
                'Consistent font styles and sizes',
                'Proper alignment of text and sections',
                'Effective use of white space to enhance readability',
                'Appropriate margins and spacing'
            ]
        },
        {
            'name': 'Section Organization and Headings',
            'key': 'section_organization',
            'weight': 15,
            'description': 'Evaluate the organization of content into clear sections with appropriate headings.',
            'factors': [
                'Clear and descriptive section headings',
                'Logical sequence of sections (e.g., summary, experience, education)',
                'Use of subheadings where appropriate',
                'Ease of locating key information'
            ]
        },
        {
            'name': 'Clarity and Conciseness of Content',
            'key': 'content_clarity',
            'weight': 25,
            'description': 'Assess the clarity and conciseness of the information presented.',
            'factors': [
                'Use of clear and straightforward language',
                'Concise bullet points',
                'Avoidance of unnecessary jargon or buzzwords',
                'Focus on relevant information'
            ]
        },
        {
            'name': 'Visual Elements and Design',
            'key': 'visual_design',
            'weight': 20,
            'description': 'Evaluate the visual appeal of the resume, including the use of visual elements.',
            'factors': [
                'Appropriate use of color accents',
                'Inclusion of relevant visual elements (e.g., icons, charts)',
                'Consistency in design elements',
                'Professional appearance suitable for the industry'
            ]
        },
        {
            'name': 'Grammar and Spelling',
            'key': 'grammar_spelling',
            'weight': 20,
            'description': 'Assess the resume for grammatical correctness and spelling accuracy.',
            'factors': [
                'Correct grammar usage',
                'Accurate spelling throughout',
                'Proper punctuation',
                'Professional tone and language'
            ]
        },
        {
            'name': 'Length and Completeness',
            'key': 'length_completeness',
            'weight': 10,
            'description': 'Evaluate whether the resume is of appropriate length and includes all necessary sections.',
            'factors': [
                'Resume length appropriate for experience level (typically 1-2 pages)',
                'Inclusion of all relevant sections',
                'Absence of irrelevant or redundant information'
            ]
        }
    ]

    scores = {}
    total_weight = sum(criterion['weight'] for criterion in criteria)
    total_score = 0

    for criterion in criteria:
        prompt = f"""
        Evaluate the resume image based on the criterion: "{criterion['name']}".

        Criterion Description:
        {criterion['description']}

        Factors to consider:
        {', '.join(criterion['factors'])}

        Provide your evaluation as an integer score from 0 to 100, where 0 is the lowest and 100 is the highest.
        Only return the integer score, nothing else.
        """
        response = talk_fast(prompt, max_tokens=200, image_data=front_page_image, client=client)
        try:
            if isinstance(response, dict) and 'content' in response and 'value' in response['content']:
                score = response['content']['value']
            else:
                raise ValueError("Unexpected response format")
            
            if 0 <= score <= 100:
                scores[criterion['key']] = score
            else:
                raise ValueError("Score out of range")
        except Exception as e:
            logging.error(f"Error parsing score for criterion {criterion['name']}: {str(e)}")
            scores[criterion['key']] = 0

        weighted_score = (score * criterion['weight']) / 100
        total_score += weighted_score

    overall_score = int((total_score / total_weight) * 100)  # Normalize to 0-100 scale

    return overall_score

def extract_website_info(resume_text, client=None):
    # Extract website from resume (simple extraction)
    website = ''
    website_prompt = f"""
    Extract the candidate's personal website URL from the resume if available.

    Resume:
    {resume_text}

    Only output the URL or an empty string.
    You can only speak URL. You can only output valid URL. Strictly No explanation, no comments, no intro. No \`\`\`json\`\`\` wrapper.
    """
    website_response = talk_fast(website_prompt, max_tokens=150, client=client)
    
    if isinstance(website_response, dict) and 'content' in website_response:
        website = website_response['content'].get('value', '')
    else:
        logging.error(f"Unexpected format for website response: {website_response}")
        website = ''

    return website

#match functions
def match_resume_to_job(resume_text, job_desc, resume_images, client=None):
    # Extract job requirements and wait for completion
    job_requirements = extract_job_requirements(job_desc, client)
    if not job_requirements:
        logging.error("Failed to extract job requirements")
        # print(colored("Error: Failed to extract job requirements. Exiting program.", 'red'))
        sys.exit(1)  # Exit the script with an error code

    # Check if job_requirements contains expected keys
    if 'emphasis' not in job_requirements:
        logging.error("Job requirements missing 'emphasis' key")
        # print(colored("Error: Invalid job requirements format. Exiting program.", 'red'))
        sys.exit(1)  # Exit the script with an error code

    criteria = [
        {
            'name': 'Language Proficiency',
            'key': 'language_proficiency',
            'weight': job_requirements['emphasis'].get('language_proficiency_weight', 5),
            'description': 'Assign points based on the candidate\'s proficiency in languages relevant to the job.',
            'factors': [
                'Proficiency in required languages',
                'Multilingual abilities relevant to the job'
            ]
        },
        {
            'name': 'Education Level',
            'key': 'education_level',
            'weight': job_requirements['emphasis'].get('education_weight', 10),
            'description': 'Assign points based on the candidate\'s highest level of education or equivalent experience.',
            'factors': [
                'Highest education level attained',
                'Relevance of degree to the job',
                'Alternative education paths (certifications, bootcamps, self-learning)'
            ]
        },
        {
            'name': 'Years of Experience',
            'key': 'experience_years',
            'weight': job_requirements['emphasis'].get('experience_weight', 20),
            'description': 'Assign points based on the relevance and quality of experience.',
            'factors': [
                'Total years of relevant experience',
                'Quality and relevance of previous roles',
                'Significant achievements in previous positions'
            ]
        },
        {
            'name': 'Technical Skills',
            'key': 'technical_skills',
            'weight': job_requirements['emphasis'].get('technical_skills_weight', 50),
            'description': 'Assign points for each required and optional skill, considering proficiency level.',
            'factors': [
                'Proficiency in required technical skills',
                'Proficiency in optional technical skills',
                'Transferable skills and learning ability',
                'Keywords matched in resume'
            ]
        },
        {
            'name': 'Certifications',
            'key': 'certifications',
            'weight': job_requirements['emphasis'].get('certifications_weight', 5),
            'description': 'Assign points for each relevant certification.',
            'factors': [
                'Possession of preferred certifications',
                'Equivalent practical experience',
                'Self-learning projects demonstrating expertise'
            ]
        },
        {
            'name': 'Soft Skills',
            'key': 'soft_skills',
            'weight': job_requirements['emphasis'].get('soft_skills_weight', 9),
            'description': 'Assign points for each soft skill demonstrated through examples or achievements.',
            'factors': [
                'Demonstrated soft skills in resume',
                'Examples of teamwork, leadership, problem-solving, etc.'
            ]
        },
        {
            'name': 'Location',
            'key': 'location',
            'weight': job_requirements['emphasis'].get('location_weight', 50),
            'description': 'Assign points based on the candidate\'s location relative to the job requirements.',
            'factors': [
                'Country match with job location',
                'City match with job location',
                'Willingness to relocate (if mentioned)'
            ]
        }
    ]

    scores = {}
    total_weight = sum(criterion['weight'] for criterion in criteria)
    #1 is the biggest redflag - they have high weightage but low score
    red_flags = {
        '1': [],
        '2': [],
        '3': []
    }
    
    if total_weight == 0:
        logging.error("Total weight of criteria is zero")
        return {'score': 0, 'match_reasons': "Error: Invalid criteria weights", 'website': '', 'red_flags': []}

    total_score = 0

    for criterion in criteria:
        prompt = f"""
        Evaluate the candidate's resume based on the criterion: "{criterion['name']}".

        Criterion Description:
        {criterion['description']}

        Factors to consider:
        {', '.join(criterion['factors'])}

        Job Requirements:
        {json.dumps(job_requirements, indent=2)}

        Pay special attention to negative selection: score criterion as 0 if total miss. Example: 
            Criteria: Location
            Job description: "No candidates from North Korea."
            Resume: "Location: Pyongyang"
            Score: 0

        Resume:
        {resume_text}

        Provide your evaluation as an integer score from 0 to 100, where 0 is the lowest and 100 is the highest.
        Only return the integer score, nothing else. No explanation, no comments, no intro. No \`\`\`json\`\`\` wrapper.
        """

        response = talk_fast(prompt, client=client)
        try:
            if isinstance(response, dict) and 'content' in response and 'value' in response['content']:
                score = response['content']['value']
            elif isinstance(response, str):
                try:
                    score = int(response)
                except ValueError as e:
                    raise ValueError("Unexpected response format")
            else:
                raise ValueError("Unexpected response format")
            
            if 0 <= score <= 100:
                criterion['score'] = score
                if score < 10:
                    if criterion['weight'] >= 30:
                        red_flags['1'].append(criterion['name'])
                    elif criterion['weight'] >= 20:
                        red_flags['2'].append(criterion['name'])
                    else:
                        red_flags['3'].append(criterion['name'])
            else:
                raise ValueError("Score out of range")
        except ValueError as ve:
            logging.error(f"Error parsing score for criterion {criterion['name']}: {ve}")
            criterion['score'] = 0
        except Exception as e:
            logging.error(f"Unexpected error for criterion {criterion['name']}: {e}")
            criterion['score'] = 0

        scores[criterion['key']] = criterion['score']
        weighted_score = (criterion['score'] * criterion['weight']) / 100
        total_score += weighted_score

    # Normalize total score to 0 - 100 scale
    final_score = int((total_score / total_weight) * 100)

    match_reasons = generate_match_reasons(resume_text, job_requirements, client)

    website = extract_website_info(resume_text, client)

    email_response = generate_email_response(final_score, client)
    
    return {'score': final_score, 'match_reasons': match_reasons, 'website': website, 'red_flags': red_flags, 'email_response': email_response}

def generate_match_reasons(resume_text, job_requirements, client=None):

    # Generate match reasons
    reasons_prompt = f"""
    Based on the evaluation, provide 3-4 key reasons for the match between the candidate's resume and the job requirements.

    Resume:
    {resume_text}

    Job Requirements:
    {json.dumps(job_requirements, indent=2)}

    Provide the reasons in telegraphic English, max 10 words per reason, separated by ' | '.

    Only output the reasons as a single string. No explanation, no comments, no intro. No \`\`\`json\`\`\` wrapper.
    """
    reasons_response = talk_fast(reasons_prompt, max_tokens=100, client=client)
    
    if isinstance(reasons_response, dict) and 'content' in reasons_response:
        match_reasons = reasons_response['content'].get('value', '')
    elif isinstance(reasons_response, str):
        match_reasons = reasons_response.split("|")
    else:
        logging.error(f"Unexpected format for reasons response: {reasons_response}")
        match_reasons = ''

    return match_reasons

def generate_email_response(final_score, client=None):
    # Generate email response and subject
    email_prompt = f"""
    Compose a professional email response to the candidate based on their match score.

    Score: {final_score}

    If the score is below 90, politely reject the person. If the score is 90 or above, invite them to the next stage. Use personal details and make it personalized. Omit signature and "best regards". Friendly concise business tone.

    Provide the output in the following JSON format:
    {{
      "email_response": "Email body",
      "subject_response": "Email subject"
    }}

    You can only speak JSON. You can only output valid JSON. Strictly No explanation, no comments, no intro. No \`\`\`json\`\`\` wrapper.
    """
    email_text = talk_to_ai(email_prompt, max_tokens=180, client=client)
    try:
        email_response = json5.loads(email_text)
    except ValueError as e:
        logging.error(f"Error parsing email response: {str(e)}")
        logging.error(f"Raw email text: {email_text}")
        email_response = json5.loads({"email_response": "","subject_response": ""})

    return email_response

def unify_format(extracted_data, font_styles, generate_pdf=False):
    resume_text, resume_images = extracted_data
    
    prompt = """
    Given the following raw text extracted from a resume, convert it into a unified format following these guidelines:

Resume Object Model Definition (Markdown):
===
# Full legal name as it appears on official documents or as preferred professionally.        | First and last name; include middle name or initial if commonly used. | Use your professional or legal name.     |
## Specific position or role aimed for, aligned with the job you're applying for to showcase career focus. | Concise title, typically 2-5 words. | Be specific to highlight your career goals. |

Format: Email / Phone / Country / City
| Field      | Description                                                        | Expected Length                | Guidelines                                         |
|------------|--------------------------------------------------------------------|--------------------------------|----------------------------------------------------|
| **Email**  | Professional email address (e.g., name@example.com).               | Standard email format          | Use a professional email; avoid unprofessional addresses. |
| **Phone**  | Primary contact number, including country code if applicable.      | Include country code if applicable | Provide a reliable contact number.                  |
| **Country**| Full country name of current residence.                            | Full country name              | Specify for relocation considerations.             |
| **City**   | Full city name of current residence if available.                          | Full city name                 | Indicates proximity to job location.               |

## Summary

Format: plain text

| Field      | Description                                                                                                                | Expected Length                | Guidelines                           |
|------------|----------------------------------------------------------------------------------------------------------------------------|--------------------------------|--------------------------------------|
| **Summary**| Brief overview of qualifications and career goals, highlighting key skills, experiences, and achievements aligned with the desired job. | Mention quantifiable data. STAR format, approximately 5-6 sentences or bullet points | Keep it concise and impactful.       |

Format: _skill, skill, skill_   

| Field      | Description                                                                                                                | Expected Length                | Guidelines                           |
|------------|----------------------------------------------------------------------------------------------------------------------------|--------------------------------|--------------------------------------|
| **Skills**| List of skills (1-2 words each), separated by commas. | Mention technical skills, programming languages, frameworks, tools, and any other relevant skills. SCan the original data and find the skills. | 1-2 words each, 6-12 skills      |


## Employment History

**Description**: Chronological list of past employment experiences (**one or more** entries).
Format: Company / Job Title / Location

Start - End Date

Responsibilities (list or description)

| Field            | Description                                                           | Expected Length        | Guidelines                                           |
|------------------|-----------------------------------------------------------------------|------------------------|------------------------------------------------------|
| **Company**      | Name of employer; include brief descriptor if not well-known.         | Full official name     | Provide context for lesser-known companies.          |
| **Job Title**    | Official title held; accurately reflects roles and responsibilities.  | Standard job title     | Use accurate and professional titles.                |
| **Location**     | City, State/Province, Country.                                        | Full location          | Provides context about work environment.             |
| **Start - End Date** | Employment period (e.g., June 2015 - Present).                       | Format as 'Month Year' | Ensure accuracy and consistency in formatting.       |
| **Responsibilities** | Key duties, achievements, contributions (**one or more** bullet points). | ~3-6 bullet points     | Start with action verbs; quantify achievements when possible. |

## Education

**Description**: Academic qualifications and degrees obtained (**one or more** entries).
Format: Institution / Degree / Location

Start - End Date

Description (if any)

| Field            | Description                                                           | Expected Length        | Guidelines                                           |
|------------------|-----------------------------------------------------------------------|------------------------|------------------------------------------------------|
| **Institution**  | Name of educational institution; add location if not widely known.    | Full official name     | Provide context for lesser-known institutions.       |
| **Degree**       | Degree or certification earned; specify field of study.               | Full degree title      | Highlight relevance to desired job.                  |
| **Location**     | City, State/Province, Country.                                        | Full location          | Provides context about institution's setting.        |
| **Start - End Date** | Education period (e.g., August 2004 - May 2008).                     | Format as 'Month Year' | Use consistent formatting.                           |
| **Description**    | Additional information about the education (if any).                  | ~1-2 sentences         | Include if relevant; keep it concise.               |

## Courses (Optional)

**Description**: Relevant courses, certifications, or training programs completed (**one or more** entries).
Format: Course / Platform

Start - End Date

Description (if any)    

| Field            | Description                                                           | Expected Length        | Guidelines                                           |
|------------------|-----------------------------------------------------------------------|------------------------|------------------------------------------------------|
| **Platform**     | Provider or platform name (e.g., Coursera, Udemy).                    | Organization name      | List reputable providers.                            |
| **Title**        | Official course or certification name.                                | Full title             | Use exact title for verification.                    |
| **Start - End Date** | Course period; can omit if not available.                           | Format as 'Month Year' | Include for context if possible.                     |
| **Description**  | Additional information about the course (if any).                    | ~1-2 sentences         | Include if relevant; keep it concise.               |

## Languages

**Description**: Languages known and proficiency levels (**one or more** entries).
Format: Language / Proficiency

| Field            | Description                                | Expected Length    | Guidelines                                   |
|------------------|--------------------------------------------|--------------------|----------------------------------------------|
| **Language**     | Name of the language (e.g., Spanish).      | Full language name | List languages enhancing your profile.       |
| **Proficiency**  | Level of proficiency (e.g., Native, Fluent). | Standard levels    | Use recognized scales like CEFR.             |

## Links (Optional)

**Description**: Online profiles, portfolios, or relevant links (**one or more** entries).
Format: list of links

- [Title](URL)

| Field      | Description                                          | Expected Length | Guidelines                                     |
|------------|------------------------------------------------------|-----------------|------------------------------------------------|
| **Title**  | Descriptive title (e.g., "My GitHub Profile").       | Short phrase    | Make it clear and professional.                |
| **URL**    | Direct hyperlink to the resource.                    | Full URL        | Ensure links are active and professional.      |

## Hobbies (Optional)
Format: list of hobbies

| Field      | Description                          | Expected Length     | Guidelines                                       |
|------------|--------------------------------------|---------------------|--------------------------------------------------|
| **Hobbies**| Personal interests or activities.    | List of 3-5 hobbies | Showcase positive traits; avoid controversial topics. |

## Misc (Optional)
Format: list of misc

| Field      | Description                          | Expected Length     | Guidelines                                       |
|------------|--------------------------------------|---------------------|--------------------------------------------------|
| **Misc**| Any other information.    | List of any other information | Showcase positive traits; avoid controversial topics. |

===

# General Guidelines:

- **Repeatable Sections**: Employment History, Education, Courses, Languages, and Links can contain **one or more** entries.
- **Optional Sections**: Courses, Links, and Hobbies are **optional**. Omit sections not present in the original resume. **Do not add or invent information**.
- **No Invented Information**: The parser must strictly use only the information provided in the original resume. Do not create, infer, or embellish any details.

# Parser Rules:

To convert an original resume into the defined object model, a parser should follow these rules:

1. **Information Extraction**: Extract information exactly as it appears in the original document. Pay attention to details such as names, dates, job titles, and descriptions.

2. **Section Mapping**: Map the content of the resume to the corresponding sections in the object model:
   - **Name**: Extract from the top of the resume or personal details section.
   - **Desired Job Title**: Look for a stated objective or title near the beginning.
   - **Personal Details**: Extract email, phone, country, and city from the contact information.
   - **Summary**: Use the professional summary or objective section.
   - **Employment History**: Identify past job experiences, including company names, job titles, locations, dates, and responsibilities.
   - **Education**: Extract academic qualifications with institution names, degrees, locations, and dates.
   - **Courses**: Include any additional training or certifications listed.
   - **Languages**: Note any languages and proficiency levels mentioned.
   - **Links**: Extract URLs to professional profiles or portfolios.
   - **Hobbies**: Include personal interests if provided.
   - **Misc**: Include any other information if provided.

3. **Consistency and Formatting**:
   - Ensure dates are formatted consistently throughout (e.g., 'Month Year').
   - Use bullet points for lists where applicable.
   - Maintain the order of entries as they appear in the original resume unless a different order enhances clarity.

4. **Accuracy**:
   - Double-check all extracted information for correctness.
   - Preserve the original wording, especially in descriptions and responsibilities, unless minor adjustments are needed for clarity.

5. **Exclusion of Unavailable Information**:
   - If a section or specific detail is not present in the original resume, omit that section or field in the output.
   - Do not fill in default or placeholder values for missing information.

6. **Avoiding Invention or Assumption**:
   - Do not add any information that is not explicitly stated in the original document.
   - Do not infer skills, responsibilities, or qualifications from context or general knowledge.

7. **Enhancements**:
   - Minor rephrasing for grammar or clarity is acceptable but should not alter the original meaning.
   - Do NOT fix typos or grammar mistakes.
   - Quantify achievements where numbers are provided; do not estimate or create figures.

8. **Professional Language**:
   - Ensure all language used is professional and appropriate for a resume.
   - Remove any informal language or slang that may have been present.

9. **Confidentiality**:
   - Handle all personal data with confidentiality.
   - Do not expose sensitive information in the output that was not intended for inclusion.

10. **Validation**:
    - Validate all URLs to ensure they are correctly formatted.
    - Verify that contact information follows standard formats.

11. **Omit Empty Sections**:
    - Omit sections that contain no information from the original resume.

    Raw Resume Text:
~~~
    {resume_text}
~~~

    Please structure the resume information according to the provided format. Only include sections and details that are present in the original text. Do not invent or assume any information. No more then 4000 tokens.
    No intro, no explanations, no comments. 
    Use telegraphic english with no fluff. Keep all the information, do NOT invent data.
    No ```` or ```yaml or ```json or ```json5 or ``` or --- or any other formatting. Just clean text.
You can only speak in clean, concise, Markdown format.     
    """

    unified_resume = talk_to_ai(prompt.format(resume_text=resume_text), max_tokens=4092)
    
    # Create 'out' folder if it doesn't exist
    out_folder = Path('out')
    out_folder.mkdir(exist_ok=True)
    
    # Extract the name from the first line of the unified resume
    first_line = unified_resume.split('\n', 1)[0]
    if first_line.lower().startswith('# '):
        name = first_line[2:].strip()  # Remove '# ' and trim whitespace
    else:
        name = 'Unknown'  # Fallback if name is not found in expected format
    
    # Generate a filename based on the extracted name
    safe_filename = ''.join(c for c in name if c.isalnum() or c in (' ', '.', '_')).rstrip()
    safe_filename = safe_filename[:50]  # Limit filename length
    
    # Save as Markdown
    md_filename = out_folder / f"{safe_filename}_unified.md"
    with open(md_filename, 'w', encoding='utf-8') as md_file:
        md_file.write(unified_resume)
    logging.info(f"Markdown file created: {md_filename}")
    
    # if generate_pdf:
    #     # Convert Markdown to HTML (in memory)
    #     html_content = markdown.markdown(unified_resume)

    #     if font_styles.get('serif'):
    #         font_family = FONT_PRESETS['serif']
    #     elif font_styles.get('mono'):
    #         font_family = FONT_PRESETS['mono']
    #     else:
    #         font_family = FONT_PRESETS['sans-serif']  # Default to sans-serif

    #     html_with_style = f"""
    #     <html>
    #     <head>
    #         <meta charset="UTF-8">
    #         <meta name="viewport" content="width=device-width, initial-scale=1.0">
    #         <style>
    #         * {{
    #             color: #3A3F53;
    #             font-family: {font_family};
    #         }}
    #         body {{
    #             font-size: 0.67em;
    #             letter-spacing: -0.01em;
    #             line-height: 1.125;
    #             background-color: #fff;
    #             padding: 0;
    #             margin: 0;
    #         }}
    #         </style>
    #     </head>
    #     <body>
    #         {html_content}
    #     </body>
    #     </html>
    #     """

    #     # Convert HTML to PDF
    #     pdf_filename = out_folder / f"{safe_filename}_unified.pdf"
    #     try:
    #         HTML(string=html_with_style).write_pdf(pdf_filename)
    #         logging.info(f"PDF file created: {pdf_filename}")
    #     except Exception as e:
    #         logging.error(f"Error creating PDF: {str(e)}")
    
    return unified_resume, resume_images

def unify_single_resume(file, font_styles, generate_pdf):
    extracted_data = extract_text_and_image_from_pdf(file)
    return unify_format(extracted_data, font_styles, generate_pdf)

def match_single_resume(job_desc, file, unified_resume, resume_images):
    if not unified_resume:
        return {"status": "failed", "message": "Failure to unify the resume format"}
    
    result = match_resume_to_job(unified_resume, job_desc, resume_images)
    return result

def process_single_resume(job_desc, resume_url, font_styles=constants.FONT_PRESETS, generate_pdf=False):
    
    try:
        extracted_data = extract_text_and_image_from_pdf(resume_url)
        unified_resume, resume_images = unify_format(extracted_data, font_styles, generate_pdf)
        
        if not unified_resume:
            return {"status": "failed", "message": "Failure to unify the resume format"}
        
        result = match_resume_to_job(unified_resume, job_desc, resume_images)
        return result
    except Exception as e:
        return {"status": "failed", "message": "Exception occured - " + str(e)}

#analysis function
def analyze_overall_matches(job_desc, results):
    # Prepare data for analysis
    match_data = []
    for filename, score, _, _, _, match_reasons, _, _ in results:  # Add one more underscore
        match_data.append({
            "filename": filename,
            "score": score,
            "match_reasons": match_reasons
        })
    
    # Create a prompt for Claude AI
    prompt = f"""
As a hiring consultant, analyze the following resume match data and suggest adjustments to the job description to attract better candidates.

Job Description:
{job_desc}

Resume Match Data:
{json.dumps(match_data, indent=2)}

Provide a detailed analysis highlighting common strengths and weaknesses among the candidates. Suggest specific changes to the job description to improve candidate matches.

Output format, no more than 5 suggestions, 1-sentence long each:
- Observation or suggestion
...

Only output the suggestions, no intro, no explanations, no comments. 
"""
    
    try:
        suggestions = talk_to_ai(prompt, max_tokens=1000)
        if suggestions:
            print("\n\033[1mHow can I improve the job description?\033[0m")
            print(suggestions)
        else:
            print("\n\033[1mError: Unable to generate analysis and suggestions\033[0m")
    except Exception as e:
        logging.error(f"Error during overall match analysis: {str(e)}")
