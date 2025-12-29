from fastapi import FastAPI, HTTPException, Request, File, UploadFile, Form, Query
from sheets import get_all_questions_from_sheet, update_status_to_responded,check_session_exists,update_response_in_sheet,get_last_answered_index,update_logs, get_sheet_id_from_master,get_additional_questions_from_sheet, update_response_count_in_sheet,get_instruction_from_sheet
from fastapi.responses import HTMLResponse
from firestore_db import fs_update_response, fs_log_activity
from fastapi.staticfiles import StaticFiles 
from google.cloud import storage
import os
from pydub import AudioSegment
from mail import send_email_with_links
import time
from user_agents import parse
import datetime
# import pandas as pd
import json

app = FastAPI()


# Replace with your Google Sheets ID and new unified sheet
MASTER_SPREADSHEET_ID = '1MlINOHXhzluNczH5Sk_7tIGiaWEnW50sxFdl7iRBxag'
ALL_QUESTIONS_SHEET = 'AllQuestions'
RESPONSE_RANGE = 'URLs!A1:ZZ'

# GCP Storage Bucket Name
BUCKET_NAME = "userrecordings"
# Initialize Google Cloud Storage Client
storage_client = storage.Client(project="story-legacy-442314")

PROJECT_CACHE = {}
CACHE_TTL = 300  # 5 minutes

def get_cached_sheet_id(project_code):
    now = time.time()

    if project_code in PROJECT_CACHE:
        sheet_id, timestamp = PROJECT_CACHE[project_code]
        if now - timestamp < CACHE_TTL:
            return sheet_id

    sheet_id = get_sheet_id_from_master(MASTER_SPREADSHEET_ID, project_code)
    if sheet_id:
        PROJECT_CACHE[project_code] = (sheet_id, now)
    return sheet_id

def get_device_type(user_agent):
    # user_agent = parse(user_agent_string)
    
    if user_agent.is_mobile:
        return "Mobile"
    elif user_agent.is_tablet:
        return "Tablet"
    elif user_agent.is_pc:
        return "PC"  # Ensure "PC" is correctly classified
    else:
        return "Other" 

@app.get("/", response_class=HTMLResponse)
async def serve_home(request: Request):
    project_code = request.query_params.get("pc")
    session_id = request.query_params.get("id")
    user_agent_str = request.headers.get("user-agent", "")
    user_agent = parse(user_agent_str)
    print(user_agent)
    
    details = {
        "os": user_agent.os.family,  # e.g., Windows, macOS, Linux
        "os_version": user_agent.os.version_string,  # e.g., 10, 11, Ventura
        "browser": user_agent.browser.family,  # e.g., Chrome, Firefox, Safari
        "browser_version": user_agent.browser.version_string,  # e.g., 110.0.0
        "device": get_device_type(user_agent),  # e.g., iPhone, Desktop
    }
    print(details)
    if not project_code or not session_id:
        return HTMLResponse(content="<h2>⚠️ Incorrect URL. Please check your URL</h2>", status_code=400)
    
    SPREADSHEET_ID = get_cached_sheet_id(project_code)
    if not SPREADSHEET_ID:
        return HTMLResponse(content="<h2>⚠️ Project not found. Please check your project code.</h2>", status_code=400)
    print(f"Updated Global SHEET_ID: {SPREADSHEET_ID}")  # Debugging print

    # Check if OS is iOS and browser is Firefox
    if details["os"] == "iOS" and "Firefox" in details["browser"] :
        return HTMLResponse(
            content="<script>alert('⚠️ Browser not supported. Please use Chrome or Safari.');</script>",
            status_code=400
        )
    timestamp = datetime.datetime.utcnow().isoformat()  # Get current UTC timestamp
    ip = f"User accessed home page from {request.client.host}"
    print(ip)
    # Call update_logs function to store the log
    log_response = update_logs(SPREADSHEET_ID,session_id, timestamp, details,{request.client.host})
    try:
        fs_log_activity(
            project_code=project_code,
            session_id=session_id,
            timestamp=timestamp,
            details=details,
            client_ip={request.client.host} # Passing the set just like you do for sheets
        )
    except Exception as e:
        print(f"⚠️ Parallel Log Failed: {e}")

    print("Inside Home Function")
    if not project_code or not session_id:
        return HTMLResponse(content="<h2>⚠️ Incorrect URL. Please check your URL</h2>", status_code=400)

    if not check_session_exists(SPREADSHEET_ID, "URLs", session_id):
        return HTMLResponse(content="<h2>⚠️ Incorrect URL. Please check your URL</h2>", status_code=400)  

    resume_state = get_last_answered_index(SPREADSHEET_ID, "URLs", session_id)
    print("LAI",resume_state)
    if resume_state["phase"] == "complete":
        update_status_to_responded(SPREADSHEET_ID, session_id)
        return HTMLResponse(content="<h2>✅ You have answered all prompts and questions. Thank you!</h2>")

    with open("templates/prompts.html", "r") as file:
        html_content = file.read()

    js_state_injection = f"""
    const resumeState = {json.dumps(resume_state)};
    """

    html_content = html_content.replace("// {{INJECT_START_STATE}}", js_state_injection)
    return HTMLResponse(content=html_content)

@app.get("/prompts_and_questions")
def get_prompts(project_code: str = Query(...)):
    try:
        print("In prompts function pc =", project_code)
        SPREADSHEET_ID = get_cached_sheet_id(project_code)
        if not SPREADSHEET_ID:
            raise HTTPException(status_code=400, detail="Spreadsheet ID not set.")
        print("SPREADSHEET_ID is:", SPREADSHEET_ID)

        # 1. Fetch ALL questions ONE time
        all_questions = get_all_questions_from_sheet(SPREADSHEET_ID, ALL_QUESTIONS_SHEET)

        # 2. Build the lists correctly
        prompts_list = []
        questions_list = []
        current_list = prompts_list

        prompt_data_index = 0    
        question_data_index = 0 

        for q in all_questions:
            item_type = q.get("Type", "").strip().lower()

            if item_type == "prompt":
                q['data_index'] = prompt_data_index
                current_list.append(q)
                prompt_data_index += 1
            
            elif item_type == "followup":
                current_list = questions_list  
                q['data_index'] = question_data_index 
                current_list.append(q)
                question_data_index += 1
            
            elif item_type == "pagebreak":
                q['data_index'] = -1 
                current_list.append(q)
        
        # 3. Get Additional/Instruction
        additional_questions_raw = get_additional_questions_from_sheet(SPREADSHEET_ID, ALL_QUESTIONS_SHEET)
        additional_questions = {pid: [q["Questions"] for q in qs if "Questions" in q] for pid, qs in additional_questions_raw.items()}
            
        instruction_row = get_instruction_from_sheet(SPREADSHEET_ID, ALL_QUESTIONS_SHEET)
        instructions = instruction_row["Questions"] if instruction_row and "Questions" in instruction_row else ""
        
        # 4. Return the new, correct lists
        return {
            "prompts": prompts_list, 
            "questions": questions_list, 
            "instructions": instructions, 
            "additional_questions": additional_questions
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        
        fs_update_response(
            project_code=project_code, 
            session_id=session_id,
            index=prompt_index,     
            audio_url=response_url,
            response_type=response_type,
            additional_index=additional_index,     
            duration_seconds=duration_seconds
        )

        SPREADSHEET_ID = get_sheet_id_from_master(MASTER_SPREADSHEET_ID, project_code)
        if not SPREADSHEET_ID:
            raise HTTPException(status_code=400, detail="Spreadsheet ID not set.")

        spreadsheet_config.set_spreadsheet_id(SPREADSHEET_ID) 
        print("SPREADSHEET_ID is:",SPREADSHEET_ID)

        updated = update_response_in_sheet(
            spreadsheet_id=SPREADSHEET_ID,
            sheet_name="URLs",
            session_id=session_id,
            response_type=response_type,
            prompt_index=prompt_index,
            new_value=response_url,
            additional_index=additional_index if is_additional else None
        )

        print("value of updated", updated)
        if not updated:
            print("Session ID not found in the sheet")
            return {"error": "Session ID not found in the sheet"}

        # update_response_count_in_sheet(spreadsheet_id=SPREADSHEET_ID, session_id=session_id)
        
        # resume_state = get_last_answered_index(SPREADSHEET_ID, "URLs", session_id)
        # print("🔎 Resume state after update:", resume_state)
        # if resume_state.get("phase") == "complete":
        #     update_status_to_responded(SPREADSHEET_ID, session_id)
        #     print(f"✅ Status instantly updated for session {session_id}")
        # else :
        #     print(f"Responses Not Completed for session {session_id}")

        return {"message": "Audio uploaded successfully", "response_url": response_url}


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
        
        SPREADSHEET_ID = get_sheet_id_from_master(MASTER_SPREADSHEET_ID, project_code)
        spreadsheet_config.set_spreadsheet_id(SPREADSHEET_ID)
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
        update_response_count_in_sheet(SPREADSHEET_ID, session_id)
        if not updated:
            return {"error": "Session ID not found in the sheet"}
        
        return {"message": "Audio response erased successfully!"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/send_mail")
async def send_mail( project_code: str = Form(...),session_id: str = Form(...),):
    
    SPREADSHEET_ID = spreadsheet_config.get_spreadsheet_id()
    if not SPREADSHEET_ID:
        raise HTTPException(status_code=400, detail="Spreadsheet ID not set.")
    print("SPREADSHEET_ID is:",SPREADSHEET_ID)
    send_email_with_links(project_code, session_id, SPREADSHEET_ID)

    return


