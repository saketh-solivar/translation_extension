from google.cloud import storage
import gspread
import smtplib
from email.message import EmailMessage
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import time
import os

sheet_name = "URLs"
# gc = gspread.service_account(filename="/code/credentials.json")
gc = gspread.service_account(filename=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))

# Email configuration
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "storylegacyresponses@gmail.com"
SENDER_PASSWORD = 'axya atyw akur szpm' # Use environment variable for security

def update_status(session_id,worksheet):
    cell = worksheet.find(str(session_id), in_column=worksheet.find("Session Key").col)

    if cell:
        row_num = cell.row  # Get row number
        col_num = worksheet.find("Email Status").col
    status_col_num = worksheet.find("Status").col
    worksheet.update_cell(row_num,col_num,"Sent")
    print("✅ Status updated to 'Sent'")

def grant_access_to_files(recipient_emails):
    """Grants read access to recipient emails for all objects in both buckets using IAM."""
    storage_client = storage.Client(project="story-legacy-442314")
    bucket_names = ["userrecordings", "trans_dest"]  # List of bucket names
    role = "roles/storage.objectViewer"

    for bucket_name in bucket_names:
        bucket = storage_client.bucket(bucket_name)
        policy = bucket.get_iam_policy(requested_policy_version=3)  # Fetch IAM policy

        for email in recipient_emails:
            member = f"user:{email}"
            role = "roles/storage.objectViewer"

            # Check if the role already exists in the policy
            if role in policy:
                if member not in policy[role]:
                    policy[role].add(member)
            else:
                policy[role] = {member}
        # Apply the updated IAM policy to the bucket
        bucket.set_iam_policy(policy)
        print(f"Granted read access to {recipient_emails} for bucket {bucket_name}")

def fetch_recipient_emails(project_code,google_sheet_id):
    """Fetches emails from the project info sheet where the ProjectCode matches."""
    # creds = Credentials.from_service_account_file("credentials.json")
    creds = Credentials.from_service_account_file(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
    service = build("sheets", "v4", credentials=creds)

    RANGE_NAME = "ProjectInfo!A4:B4"  # Assuming Project Code is in column A and Emails are in column D
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=google_sheet_id, range=RANGE_NAME).execute()
    values = result.get("values", [])
    recipient_emails = values[0][1].split(',')
    print(recipient_emails)
    
    return recipient_emails

def col_index_to_letter(index):
    """Converts 1-based column index to Excel-style column letter."""
    result = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result

def fetch_response_links(session_id, google_sheet_id, initial_wait=120, max_wait_time=600, check_interval=30):
    """Fetches response and transcript URLs for a session_id from the Google Sheet dynamically."""

    # creds = Credentials.from_service_account_file("credentials.json")
    creds = Credentials.from_service_account_file(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
    service = build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()

    print(f"Waiting for {initial_wait} seconds before first check...")
    time.sleep(initial_wait)

    elapsed_time = initial_wait
    while elapsed_time < max_wait_time:
        # Step 1: Fetch headers from row 1, starting from column C
        header_range = "URLs!C1:1"
        header_result = sheet.values().get(spreadsheetId=google_sheet_id, range=header_range).execute()
        headers = header_result.get("values", [[]])[0]
        total_cols = len(headers)

        if total_cols < 3:
            print("Not enough columns to parse.")
            return []

        # Step 2: Exclude last 2 columns
        usable_cols = total_cols - 2
        start_col_index = 3  # Column C = 3
        end_col_index = start_col_index + usable_cols - 1
        end_col_letter = col_index_to_letter(end_col_index)

        # Step 3: Fetch data range dynamically from C to computed last usable column
        data_range = f"URLs!C:{end_col_letter}"
        result = sheet.values().get(spreadsheetId=google_sheet_id, range=data_range).execute()
        values = result.get("values", [])

        if not values:
            print("No data rows found.")
            return []

        headers = values[0]
        data_rows = values[1:]

        # Step 4: Find the row that matches the session_id 
        session_row = next((r for r in data_rows if r and r[0].strip() == session_id), None)
        if not session_row:
            print(f"Session ID '{session_id}' not found.")
            return []

        # Step 5: Clean up the row data
        session_data = [(headers[i], session_row[i].strip() if i < len(session_row) and session_row[i] else "")
                        for i in range(len(headers))]

        # Step 6: Group and return (label, response_url, transcript_url)
        links = []
        temp = {}
        for header, value in session_data:
            header_lower = header.lower()
            if "response" in header_lower:
                temp["response"] = value
                temp["label"] = header
            elif "transcript" in header_lower:
                temp["transcript"] = value

            if "response" in temp and "transcript" in temp:
                if not temp["response"] or not temp["transcript"]:
                    print(f"Missing data for: {temp}")
                    return []
                links.append((temp["label"], temp["response"], temp["transcript"]))
                temp = {}

        if links:
            return links

        print(f"Waiting for transcript data... {elapsed_time}/{max_wait_time} seconds elapsed.")
        time.sleep(check_interval)
        elapsed_time += check_interval

    print("Timed out waiting for complete response and transcript data.")
    return []

def send_email_with_links(project_code,session_id,sheet_id):
    """Fetches response & transcript links, grants access, and sends them via email."""
    SHEET_URL = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    sh = gc.open_by_url(SHEET_URL)
    worksheet = sh.worksheet(sheet_name)
    recipient_emails = fetch_recipient_emails(project_code,sheet_id)
    session_links = fetch_response_links(session_id, sheet_id)
    if not session_links:
        print("Email is not sent since some links are missing.")
        return

    grant_access_to_files(recipient_emails)

    # Prepare structured output
    prompts, aqgs, questions = [], [], []

    for label, response_url, transcript_url in session_links:
        label_clean = label.strip().lower()

        if label_clean.startswith("response") and "_" not in label_clean:
            prompts.append((label, response_url, transcript_url))
        elif label_clean.startswith("aqgresponse"):
            aqgs.append((label, response_url, transcript_url))
        elif label_clean.startswith("qresponse"):
            questions.append((label, response_url, transcript_url))

    # Build email content
    email_content = f"Dear User,\n\nHere are the response and transcript links for the session {session_id} and Project {project_code}:\n\n"

    # Add prompts
    for i, (label, response_url, transcript_url) in enumerate(prompts, 1):
        email_content += f"Prompt {i}:\n"
        email_content += f"- Audio Response: {response_url}\n"
        email_content += f"- Transcript: {transcript_url}\n\n"

        # Insert AQGs if available for this prompt
        p_key = f"_p{i}_"
        for aqg_label, aqg_resp, aqg_trans in aqgs:
            if p_key in aqg_label.lower():
                aqg_num = aqg_label.lower().split("_")[-1]
                email_content += f"Additional Question {aqg_num}:\n"
                email_content += f"- Audio Response: {aqg_resp}\n"
                email_content += f"- Transcript: {aqg_trans}\n\n"

    # Add questions
    for i, (label, response_url, transcript_url) in enumerate(questions, 1):
        email_content += f"Question {i}:\n"
        email_content += f"- Audio Response: {response_url}\n"
        email_content += f"- Transcript: {transcript_url}\n\n"

    email_content += "\nBest regards,\nStoryLegacy Team"

    # Send email
    msg = EmailMessage()
    msg["Subject"] = f"Responses & Transcripts for Session {session_id}"
    msg["From"] = SENDER_EMAIL
    msg["To"] = ", ".join(recipient_emails)
    msg.set_content(email_content)
    print(recipient_emails)
    print(email_content)
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()  # Secure connection
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"✅ Email sent successfully to {recipient_emails}!")
        update_status(session_id,worksheet)
    except Exception as e:
        print(f"❌ Failed to send email to {recipient_emails}: {e}")

# send_email_with_links("GP-QN-01-2025","je0i8uw1","1TJ5gs81ofy_YxWwi-sO3IdXHr51W7C2OR_ZgaiVdPCU")