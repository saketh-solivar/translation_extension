from fastapi import FastAPI, HTTPException, Request, File, UploadFile, Form, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles


from sheets import (
    get_all_questions_from_sheet,
    update_status_to_responded,
    check_session_exists,
    update_response_in_sheet,
    get_last_answered_index,
    update_logs,
    get_sheet_id_from_master,
    get_additional_questions_from_sheet,
    update_status_to_responded,
    get_instruction_from_sheet,
    get_sheets_service,
    get_prompts_from_sheet,
    get_questions_from_sheet,
    get_available_languages
)

from firestore_db import fs_update_response, fs_log_activity
from google.cloud import storage
from google.cloud import translate_v2 as translate
from bs4 import BeautifulSoup

from mail import send_email_with_links
from user_agents import parse
from pydub import AudioSegment

import os
import time
import datetime
import json
import html


app = FastAPI()

# ---------------- CONFIG ----------------
MASTER_SPREADSHEET_ID = '1t0bzj8EAYi_5VNfUmv9lonSa8VxD1UU8c-Z3jlfXJ3c'
ALL_QUESTIONS_SHEET = 'AllQuestions'
RESPONSE_RANGE = 'URLs!A1:ZZ'

BUCKET_NAME = "userrecordings"
storage_client = storage.Client(project="story-legacy-442314")
translate_client = translate.Client()

PROJECT_CACHE = {}
CACHE_TTL = 300  # 5 minutes

# ---------------- HELPERS ----------------
def get_cached_sheet_id(project_code):
    now = time.time()
    if project_code in PROJECT_CACHE:
        sheet_id, ts = PROJECT_CACHE[project_code]
        if now - ts < CACHE_TTL:
            return sheet_id

    sheet_id = get_sheet_id_from_master(MASTER_SPREADSHEET_ID, project_code)
    if sheet_id:
        PROJECT_CACHE[project_code] = (sheet_id, now)
    return sheet_id


def get_device_type(user_agent):
    if user_agent.is_mobile:
        return "Mobile"
    elif user_agent.is_tablet:
        return "Tablet"
    elif user_agent.is_pc:
        return "PC"
    return "Other"


def translate_html(html_content: str, target_lang: str):
    soup = BeautifulSoup(html_content, "html.parser")

    for node in soup.find_all(string=True):
        parent = node.parent.name
        if parent in ["script", "style"]:
            continue

        text = node.strip()
        if not text:
            continue

        translated = translate_client.translate(
            text,
            source_language="en",
            target_language=target_lang,
            format_="text"
        )

        # ✅ Decode HTML entities
        clean_text = html.unescape(translated["translatedText"])

        node.replace_with(clean_text)

    return str(soup)


# ---------------- ROUTES ----------------
@app.get("/", response_class=HTMLResponse)
async def serve_home(request: Request):
    project_code = request.query_params.get("pc")
    session_id = request.query_params.get("id")
    lang = request.query_params.get("lang", "en")

    user_agent = parse(request.headers.get("user-agent", ""))

    details = {
        "os": user_agent.os.family,
        "os_version": user_agent.os.version_string,
        "browser": user_agent.browser.family,
        "browser_version": user_agent.browser.version_string,
        "device": get_device_type(user_agent),
    }

    if not project_code or not session_id:
        return HTMLResponse("<h2>⚠️ Incorrect URL</h2>", status_code=400)

    SPREADSHEET_ID = get_cached_sheet_id(project_code)
    if not SPREADSHEET_ID:
        return HTMLResponse("<h2>⚠️ Project not found</h2>", status_code=400)

    if details["os"] == "iOS" and "Firefox" in details["browser"]:
        return HTMLResponse(
            "<script>alert('⚠️ Please use Chrome or Safari');</script>",
            status_code=400
        )

    timestamp = datetime.datetime.utcnow().isoformat()
    update_logs(SPREADSHEET_ID, session_id, timestamp, details, {request.client.host})

    try:
        fs_log_activity(project_code, session_id, timestamp, details, {request.client.host})
    except Exception as e:
        print("Firestore log failed:", e)

    if not check_session_exists(SPREADSHEET_ID, "URLs", session_id):
        return HTMLResponse("<h2>⚠️ Invalid session</h2>", status_code=400)

    resume_state = get_last_answered_index(SPREADSHEET_ID, "URLs", session_id)

    if resume_state["phase"] == "complete":
        update_status_to_responded(SPREADSHEET_ID, session_id)
        return HTMLResponse("<h2>✅ All questions completed. Thank you!</h2>")





    # ---- LOAD HTML ----
    with open("templates/prompts.html", "r", encoding="utf-8") as f:
        html_content = f.read()

    # ---- INJECT JS STATE (IMPORTANT) ----
    js_state = f"const resumeState = {json.dumps(resume_state)};"
    html_content = html_content.replace("// {{INJECT_START_STATE}}", js_state)

    # ---- TRANSLATE IF REQUIRED ----
    

    return HTMLResponse(content=html_content)

# ---------------- API ROUTES (UNCHANGED) ----------------
@app.get("/prompts_and_questions")
def get_prompts(
    project_code: str = Query(...),
    lang: str = Query("en")
):
    SPREADSHEET_ID = get_cached_sheet_id(project_code)
    if not SPREADSHEET_ID:
        raise HTTPException(status_code=400, detail="Spreadsheet not found")

    all_questions = get_all_questions_from_sheet(SPREADSHEET_ID, ALL_QUESTIONS_SHEET, lang)

    prompts, questions = [], []
    prompt_idx = question_idx = 0
    current = prompts

    for q in all_questions:
        q = q.copy()  # IMPORTANT: avoid mutating original

        t = q.get("Type", "").lower()

        
        

        if t == "prompt":
            q["data_index"] = prompt_idx
            prompt_idx += 1
            current = prompts

        elif t == "followup":
            q["data_index"] = question_idx
            question_idx += 1
            current = questions

        elif t == "pagebreak":
            q["data_index"] = -1

        current.append(q)

    # -------- ADDITIONAL QUESTIONS --------
    additional_raw = get_additional_questions_from_sheet(SPREADSHEET_ID, ALL_QUESTIONS_SHEET, lang)
    additional = {}

    for pid, qs in additional_raw.items():
        translated_qs = []
        for q in qs:
            text = q.get("Questions", "")
            
            translated_qs.append(text)
        additional[pid] = translated_qs

    # -------- INSTRUCTIONS --------
    instruction = get_instruction_from_sheet(SPREADSHEET_ID, ALL_QUESTIONS_SHEET, lang)
    instruction_text = instruction.get("Questions", "") if instruction else ""

    

    return {
        "prompts": prompts,
        "questions": questions,
        "instructions": instruction_text,
        "additional_questions": additional
    }






@app.post("/save_audio")
async def save_audio(
    file: UploadFile = File(...),
    project_code: str = Form(...),
    session_id: str = Form(...),
    prompt_index: int = Form(...),
    file_extension: str = Form(...),
    is_prompt: bool = Form(False), 
    is_additional: bool = Form(False),
    additional_index: int = Form(...),
    duration_seconds: float = Form(0.0),
):
    """
    Save the uploaded audio file to GCP Storage.
    """
    try:
        print("In save_Audio function")
        print("Audio type is", file_extension)
        print(f"Is prompt: {is_prompt}")
        SPREADSHEET_ID = get_cached_sheet_id(project_code)
        if not SPREADSHEET_ID:
            raise HTTPException(status_code=400, detail="Spreadsheet ID not set.")

        print("SPREADSHEET_ID is:",SPREADSHEET_ID)

        # Define the file path in GCP Storage, now different for prompts and questions
        if is_prompt:
            file_path = f"{project_code}/{session_id}/prompts/presponse{prompt_index}.{file_extension}"
            response_type = "prompt"
        elif is_additional:
            file_path = f"{project_code}/{session_id}/additionalquestion/aqgresponse-P{prompt_index}_{additional_index}.{file_extension}"
            response_type = "aqg"
        else:
            file_path = f"{project_code}/{session_id}/questions/qresponse{prompt_index}.{file_extension}"
            response_type = "question"

            
        print(f"Uploading to: {file_path}")

        # Upload to GCP Storage
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(file_path)
        blob.upload_from_file(file.file, content_type=f"audio/{file_extension}")

        # Verify if the file exists in GCP Storage
        if blob.exists(storage_client):
            print(f"File successfully uploaded and exists at {file_path}")
        else:
            print(f"File upload failed: {file_path}")
            return {"error": "File upload failed"}

        # Generate GCS URL
        response_url = f"https://storage.cloud.google.com/{BUCKET_NAME}/{file_path}"
        print("response url", response_url)
        
        try:
            fs_update_response(
                project_code=project_code, 
                session_id=session_id,
                index=prompt_index,     
                audio_url=response_url,
                response_type=response_type,
                additional_index=additional_index,     
                duration_seconds=duration_seconds
            )
            firestore_success = True
        except Exception as e:
            firestore_success = False
            print("❌ Firestore failed:", e)

        try:
            updated = update_response_in_sheet(
                spreadsheet_id=SPREADSHEET_ID,
                sheet_name="URLs",
                session_id=session_id,
                response_type=response_type,
                prompt_index=prompt_index,
                new_value=response_url,
                additional_index=additional_index if is_additional else None
            )
        except Exception as e:
            print("❌ Sheet update failed:", e)

        if firestore_success:
            return {"message": "Audio uploaded successfully"}
        else:
            return {"error": "Failed to save audio"}
    except Exception as e:
        print(str(e))
        return {"error": str(e)}

@app.delete("/erase_audio")
async def erase_audio(
    project_code: str = Query(...),
    session_id: str = Query(...),
    prompt_index: int = Query(...),
    is_prompt: bool = Query(...),
    is_additional: bool = Query(False),
    additional_index: int = Query(0),
):
    """
    Deletes the last recorded audio response from the cloud bucket and removes its entry from the spreadsheet.
    """
    try:
        print("In erase_audio")
        print(f"is_prompt: {is_prompt}, is_additional: {is_additional}, prompt_index: {prompt_index}, additional_index: {additional_index}")
        
        SPREADSHEET_ID = get_cached_sheet_id(project_code)
        if not SPREADSHEET_ID:
            raise HTTPException(status_code=400, detail="Spreadsheet ID not set.")

        # Determine response type
        if is_additional:
            response_type = "aqg"
        elif is_prompt:
            response_type = "prompt"
        else:
            response_type = "question"

        # Erase from sheet
        updated = update_response_in_sheet(
            spreadsheet_id=SPREADSHEET_ID,
            sheet_name="URLs",
            session_id=session_id,
            response_type=response_type,
            prompt_index=prompt_index,
            new_value=" ",
            additional_index=additional_index if is_additional else None
        )
        # Now update the response count
        # update_response_count_in_sheet(SPREADSHEET_ID, session_id)
        if not updated:
            return {"error": "Session ID not found in the sheet"}
        
        return {"message": "Audio response erased successfully!"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/send_mail")
async def send_mail( project_code: str = Form(...),session_id: str = Form(...),):
    
    SPREADSHEET_ID = get_cached_sheet_id(project_code)
    if not SPREADSHEET_ID:
        raise HTTPException(status_code=400, detail="Spreadsheet ID not set.")
    print("SPREADSHEET_ID is:",SPREADSHEET_ID)
    send_email_with_links(project_code, session_id, SPREADSHEET_ID)

    return


@app.get("/available_languages")
def available_languages(project_code: str):
    spreadsheet_id = get_sheet_id_from_master(
        MASTER_SPREADSHEET_ID, project_code
    )

    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="Project not found")

    return {
        "languages": get_available_languages(spreadsheet_id)
    }

