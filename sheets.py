import os
import re
import json
import pickle
import google.auth
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import gspread
from google.oauth2.service_account import Credentials

from googleapiclient.discovery import build
from google.oauth2 import service_account
import os
# import pandas as pd
from helperfunctions import find_session_row, get_prompt_column_index, get_aqg_column_index, get_question_column_index, convert_to_column_letter

SCOPES = ["https://www.googleapis.com/auth/spreadsheets","https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# Load credentials from env var (Cloud Run passes secret content as env var value)
creds_data = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if creds_data and creds_data.startswith('{'):
    # Parse JSON string from env var
    creds = Credentials.from_service_account_info(json.loads(creds_data), scopes=SCOPES)
else:
    # Fallback: try loading from file path
    creds = Credentials.from_service_account_file(creds_data, scopes=SCOPES)
# SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
# creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
client = gspread.authorize(creds)

def get_sheet_id_from_master(master_sheet_id, project_code):
    service = get_sheets_service()

    result = service.spreadsheets().values().get(
        spreadsheetId=master_sheet_id,
        range="Sheet1"   # your tab name (confirmed)
    ).execute()

    rows = result.get("values", [])
    if not rows:
        print("DEBUG: MASTER sheet is empty")
        return None

    headers = rows[0]

    # Match EXACT headers from your sheet
    project_code_idx = headers.index("Project Code")
    sheet_id_idx = headers.index("SheetId")

    for row in rows[1:]:
        if len(row) <= max(project_code_idx, sheet_id_idx):
            continue

        if row[project_code_idx].strip().lower() == project_code.strip().lower():
            print("DEBUG: MATCH FOUND →", row[sheet_id_idx])
            return row[sheet_id_idx]

    print("DEBUG: NO MATCH FOUND FOR", project_code)
    return None



# Load Google Sheets API credentials
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_sheets_service():
    creds_data = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if creds_data and creds_data.startswith('{'):
        # Parse JSON string from env var
        creds = service_account.Credentials.from_service_account_info(
            json.loads(creds_data),
            scopes=SCOPES
        )
    else:
        # Fallback: try loading from file path
        creds = service_account.Credentials.from_service_account_file(
            creds_data,
            scopes=SCOPES
        )
    return build("sheets", "v4", credentials=creds)

def ensure_language_column(spreadsheet_id, sheet_name, lang):
    """
    Ensures PromptID_HTML_<lang> column exists.
    If not, creates it and returns False.
    """
    service = get_sheets_service()
    sheet = service.spreadsheets()

    

    headers = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!1:1"
    ).execute().get("values", [[]])[0]

    if lang == "en":
        return "Questions", True

    lang_col = f"Questions_{lang}"

    if lang_col in headers:
        return lang_col, True

    headers.append(lang_col)

    # Update header row
    sheet.values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!1:1",
        valueInputOption="RAW",
        body={"values": [headers]}
    ).execute()

    # FORCE reload the updated header row
    new_header = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!1:1"
    ).execute().get("values", [[]])[0]

    return lang_col, False





from google.cloud import translate_v2 as translate

def get_translate_client():
    """Lazy-load translate client to avoid credential issues at import time."""
    return translate.Client()

def get_all_questions_from_sheet(
    spreadsheet_id,
    sheet_name="AllQuestions",
    lang="en"
):
    service = get_sheets_service()
    sheet = service.spreadsheets()

    # Get full sheet
    result = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range=sheet_name
    ).execute()

    values = result.get("values", [])
    if not values:
        return []

    headers = values[0]
    rows = values[1:]

    # Ensure language column
    lang_col, exists = ensure_language_column(spreadsheet_id, sheet_name, lang)

    # 🔴 RELOAD headers (this was missing)
    headers = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!1:1"
    ).execute().get("values", [[]])[0]

    base_idx = headers.index("Questions")
    lang_idx = headers.index(lang_col)


    updated_rows = []
    data = []

    for i, row in enumerate(rows):
        row += [""] * (len(headers) - len(row))
        base_text = row[base_idx]
        lang_text = row[lang_idx]

        # 🔹 Translate only if needed
        if lang != "en" and not lang_text.strip():
            translated = get_translate_client().translate(
                base_text,
                source_language="en",
                target_language=lang,
                format_="text"
            )
            lang_text = translated["translatedText"]
            row[lang_idx] = lang_text
            updated_rows.append((i + 2, row))  # sheet row index

        row_dict = dict(zip(headers, row))
        row_dict["Questions"] = lang_text if lang != "en" else base_text
        data.append(row_dict)

    # 🔹 Persist translations back to sheet (ONLY ONCE)
    if updated_rows:
        for row_num, row_vals in updated_rows:
            sheet.values().update(
                spreadsheetId=spreadsheet_id,
                range=f"{sheet_name}!A{row_num}",
                valueInputOption="RAW",
                body={"values": [row_vals]}
            ).execute()

    return data

    
def get_instruction_from_sheet(spreadsheet_id, sheet_name="AllQuestions", lang="en"):
    """
    Returns the first row with Type == 'Instruction', or None if not found.
    """
    all_questions = get_all_questions_from_sheet(spreadsheet_id, sheet_name, lang)
    for q in all_questions:
        if q.get("Type", "").strip().lower() == "instruction":
            return q
    return None

# Fetch only main prompts
def get_prompts_from_sheet(spreadsheet_id, sheet_name="AllQuestions", lang="en"):
    all_questions = get_all_questions_from_sheet(spreadsheet_id, sheet_name, lang)
    return [q for q in all_questions if q.get("Type", "").strip().lower() == "prompt"]

# Fetch only follow-up questions (Type == 'FollowUp')
def get_questions_from_sheet(spreadsheet_id, sheet_name="AllQuestions", lang="en"):
    all_questions = get_all_questions_from_sheet(spreadsheet_id, sheet_name, lang)
    return [q for q in all_questions if q.get("Type", "").strip().lower() == "followup"]


# Fetch additional questions, grouped by PromptID
def get_additional_questions_from_sheet(spreadsheet_id, sheet_name="AllQuestions", lang="en"):
    all_questions = get_all_questions_from_sheet(spreadsheet_id, sheet_name, lang)
    additional_q_map = {}
    for q in all_questions:
        if q.get("Type", "").strip().lower() == "additional":
            try:
                prompt_id = int(q.get("PromptID", "").strip())
            except Exception:
                continue
            if prompt_id not in additional_q_map:
                additional_q_map[prompt_id] = []
            additional_q_map[prompt_id].append(q)
    return additional_q_map





def check_session_exists(spreadsheet_id, sheet_name, session_id):
    """
    Check if the session ID exists in the given Google Sheet.
    """
    try:
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        # creds = Credentials.from_service_account_file("credentials.json", scopes=["https://www.googleapis.com/auth/spreadsheets"])
        client = gspread.authorize(creds)
        worksheet = client.open_by_key(spreadsheet_id).worksheet(sheet_name)

        # Get all records as a list of dictionaries
        records = worksheet.get_all_records()

        # Find the "Session Key" column index dynamically
        headers = worksheet.row_values(1)
        session_col_index = headers.index("Session Key") + 1  # 1-based index

        # Search for the session_id in the "Session Key" column
        cell = worksheet.find(str(session_id), in_column=session_col_index)

        return bool(cell)  # Returns True if found, False otherwise

    except Exception as e:
        print(f"Error checking session ID: {e}")
        return False


def get_total_prompts(spreadsheet_id, sheet_name):
    """
    Returns the total number of prompts available in the given sheet.
    """
    service = get_sheets_service()
    sheet = service.spreadsheets()
    
    # Get all rows from the sheet
    if(sheet_name == "AdditionalQuestions"):
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=sheet_name).execute()
        rows = result.get("values", [])
        rows = rows[1:]
    else:
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=sheet_name).execute()
        rows = result.get("values", [])

    # Subtract 1 to exclude the header row (assuming first row is headers)
    return max(0, len(rows))

def update_status_to_responded(spreadsheet_id, session_id):
    service = get_sheets_service()
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range="URLs").execute()
    rows = result.get("values", [])
    if not rows:
        return False

    headers = rows[0]
    try:
        session_col_index = headers.index("Session Key")
        status_col_index = headers.index("Status")
    except ValueError:
        print("Session Key or Status column not found")
        return False

    # Find the row for the session_id
    session_row_index = None
    for idx, row in enumerate(rows[1:], start=2):  # Google Sheets is 1-indexed, skip header
        if len(row) > session_col_index and row[session_col_index] == session_id:
            session_row_index = idx
            break

    if session_row_index is None:
        print("Session ID not found")
        return False

    # Convert column index to letter
    col_letter = convert_to_column_letter(status_col_index)
    update_range = f"URLs!{col_letter}{session_row_index}"

    sheet.values().update(
        spreadsheetId=spreadsheet_id,
        range=update_range,
        valueInputOption="RAW",
        body={"values": [["responded"]]}
    ).execute()
    print(f"Status updated for session {session_id}")
    return True
    # Subtract 1 to exclude the header row (assuming first row is headers)
    return max(0, len(rows))

def update_response_count_in_sheet(spreadsheet_id, session_id):
    """
    Counts and updates the Number of Responses & Transcripts for a specific session
    """
    try:
        service = get_sheets_service()
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range="URLs").execute()
        rows = result.get("values", [])
        if not rows:
            print("No rows found in sheet.")
            return False

        headers = rows[0]
        try:
            session_col_index = headers.index("Session Key")
            count_col_index = headers.index("Number of Responses & Transcripts")
        except ValueError as e:
            print(f"Required column not found: {e}")
            return False

        # Find the row for the session_id
        session_row_index = None
        session_row_data = None
        for idx, row in enumerate(rows[1:], start=2):
            if len(row) > session_col_index and row[session_col_index] == session_id:
                session_row_index = idx
                session_row_data = row
                break

        if session_row_index is None:
            print("Session ID not found")
            return False

        # Pad row to match header length
        if session_row_data is not None and len(session_row_data) < len(headers):
            session_row_data += [""] * (len(headers) - len(session_row_data))

        response_count = 0
        transcript_count = 0
        for col_idx, header in enumerate(headers):
            cell_value = session_row_data[col_idx] if session_row_data and col_idx < len(session_row_data) else ""
            if cell_value and str(cell_value).strip():
                if "Response" in header and not "AQG" in header:
                    response_count += 1
                elif "Transcript" in header and not "AQG" in header:
                    transcript_count += 1
                elif "AQGResponse" in header:
                    response_count += 1
                elif "AQGTranscript" in header:
                    transcript_count += 1

        total_count = response_count + transcript_count
        count_text = f"{total_count} "

        count_col_letter = convert_to_column_letter(count_col_index)
        count_range = f"URLs!{count_col_letter}{session_row_index}"

        try:
            sheet.values().update(
                spreadsheetId=spreadsheet_id,
                range=count_range,
                valueInputOption="RAW",
                body={"values": [[count_text]]}
            ).execute()
            print(f"Response count updated for session {session_id}: {count_text}")
            return True
        except Exception as e:
            print(f"Error updating sheet cell: {e}")
            return False

    except Exception as e:
        import traceback
        print(f"Error updating response count: {e}")
        traceback.print_exc()
        return False
          
def get_last_answered_index(spreadsheet_id, sheet_name, session_id):
    """
    Finds the exact resume state (phase, index) for a given session_id.
    """
    service = get_sheets_service()
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=spreadsheet_id, range=sheet_name).execute()
    rows = result.get("values", [])
    if not rows:
        return {"flat_index": 0, "phase": "prompt", "prompt_index": 0, "additional_index": 0}

    headers = rows[0]
    try:
        session_col_index = headers.index("Session Key")
    except ValueError:
        raise ValueError("Session Key column not found")

    session_row = next((row for row in rows if len(row) > session_col_index and row[session_col_index] == session_id), None)
    if not session_row:
        return {"flat_index": 0, "phase": "prompt", "prompt_index": 0, "additional_index": 0}

    flat_index = 0
    prompt_index = -1
    additional_map = {}
    question_index = 0

    for i, header in enumerate(headers):
        h = header.strip()

        # Skip transcript columns
        if "Transcript" in h:
            continue

        col_value = session_row[i] if i < len(session_row) else ""
        filled = bool(col_value.strip())

        if h.startswith("Response"):
            prompt_index += 1
            if not filled:
                return {
                    "flat_index": flat_index,
                    "phase": "prompt",
                    "prompt_index": prompt_index,
                    "additional_index": 0
                }

        elif h.startswith("AQGResponse"):
            parts = h.split("_")
            if len(parts) >= 3 and parts[1].startswith("P") and parts[1][1:].isdigit() and parts[2].isdigit():
                prompt_num = int(parts[1][1:]) - 1  # "P1" → 0
                aqg_index = int(parts[2]) - 1       # "1" → 0

                if prompt_num not in additional_map:
                    additional_map[prompt_num] = 0

                if not filled:
                    return {
                        "flat_index": flat_index,
                        "phase": "aqg",
                        "prompt_index": prompt_num,
                        "additional_index": additional_map[prompt_num]
                    }

                additional_map[prompt_num] += 1


        elif h.startswith("QResponse"):
            if not filled:
                return {
                    "flat_index": flat_index,
                    "phase": "followup",
                    "prompt_index": 0,
                    "additional_index": 0,
                    "question_index": question_index
                }
            question_index += 1

        flat_index += 1

    # If everything answered
    return {
        "flat_index": flat_index,
        "phase": "complete",
        "prompt_index": 0,
        "additional_index": 0
    }


def update_response_in_sheet(
    spreadsheet_id,
    sheet_name,
    session_id,
    response_type,
    prompt_index,
    new_value,
    additional_index=None
):
    try:
        print(f"➡️ Update Type: {response_type} | Prompt: {prompt_index} | AQG: {additional_index}")
        service = get_sheets_service()
        sheet = service.spreadsheets()

        # Read sheet data
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=sheet_name).execute()
        rows = result.get("values", [])
        if not rows:
            return False

        headers = rows[0]
        session_row_index = find_session_row(rows, session_id)
        if session_row_index is None:
            print("❌ Session ID not found.")
            return False

        # Get column index
        if response_type == "prompt":
            col_index = get_prompt_column_index(headers, prompt_index)
        elif response_type == "aqg":
            col_index = get_aqg_column_index(headers, prompt_index, additional_index)
        elif response_type == "question":
            col_index = get_question_column_index(headers, prompt_index)
        else:
            raise ValueError("Invalid response_type")

        # Convert to A1 notation
        col_letter = convert_to_column_letter(col_index)
        update_range = f"{sheet_name}!{col_letter}{session_row_index}"

        print(f"✅ Updating cell: {update_range}")
        sheet.values().update(
            spreadsheetId=spreadsheet_id,
            range=update_range,
            valueInputOption="RAW",
            body={"values": [[new_value]]}
        ).execute()

        return True

    except Exception as e:
        print(f"❌ Error updating sheet: {e}")
        return False



def update_logs(spreadsheet_id,session_id, timestamp, details,client_IP):
    sheet_name = "logs"  # Sheet where logs are stored
    
    try:
        # Open the spreadsheet and the specific sheet
        sheet = client.open_by_key(spreadsheet_id).worksheet(sheet_name)
        if isinstance(details, dict):
            details = [details.get("os", ""), details.get("os_version", ""),details.get("browser", ""), details.get("browser_version", ""),
                       details.get("device", "") ]

        # Append log entry as a new row
        sheet.append_row([session_id, timestamp] + details + list(client_IP))
        # Append the log entry as a new row
        # sheet.append_row([session_id, timestamp, os,os_version,browser,browser_version,device,client_IP])
        print("success")
        return {"status": "success", "message": "Log updated successfully"}
    except Exception as e:
        print("error",str(e))
        return {"status": "error", "message": str(e)}

import gspread
from google.oauth2.service_account import Credentials
import os


def get_available_languages(spreadsheet_id: str):
    creds_data = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if creds_data and creds_data.startswith('{'):
        creds = Credentials.from_service_account_info(
            json.loads(creds_data),
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
    else:
        creds = Credentials.from_service_account_file(
            creds_data,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )

    client = gspread.authorize(creds)
    worksheet = client.open_by_key(spreadsheet_id).worksheet("AllQuestions")

    headers = worksheet.row_values(1)

    languages = [
        {"code": "en", "label": "English"}
    ]

    for col in headers:
        if col.startswith("Questions_"):
            lang_code = col.replace("Questions_", "").lower()

            # ❌ skip HTML column explicitly
            if lang_code == "html":
                continue

            languages.append({
                "code": lang_code,
                "label": lang_code.upper()
            })

    return languages



    
