from google.cloud import storage
import gspread
import smtplib
from email.message import EmailMessage
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import time

# Constants
# source_bucket = "userrecordings"
# destination_bucket_name = "trans_dest"
# google_sheet_id = "1ZlO_YQyFV6HsZH6hWIEtCw4VHxa7NXKlRULG_2Dkyao"  
# sheet_name = "URLs"
# SHEET_URL = "https://docs.google.com/spreadsheets/d/1ZlO_YQyFV6HsZH6hWIEtCw4VHxa7NXKlRULG_2Dkyao/edit"

# Email configuration
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "storylegacyresponses@gmail.com"
SENDER_PASSWORD = 'axya atyw akur szpm' # Use environment variable for security

gc = gspread.service_account(filename="credentials.json")
# sh = gc.open_by_url(SHEET_URL)

# worksheet = sh.worksheet(sheet_name)


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
    creds = Credentials.from_service_account_file("credentials.json")
    service = build("sheets", "v4", credentials=creds)

    RANGE_NAME = "ProjectInfo!A4:B4"  # Assuming Project Code is in column A and Emails are in column D
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=google_sheet_id, range=RANGE_NAME).execute()
    values = result.get("values", [])
    # print(values)
    # print(values[0][1])
    recipient_emails = values[0][1].split(',')
    print(recipient_emails)
    
    return recipient_emails

def fetch_response_links(session_id, google_sheet_id, initial_wait=120, max_wait_time=600, check_interval=30):
    """Fetches response and transcript URLs for a session_id from the Google Sheet.  
       Waits for 120 seconds initially before first retry, then checks every 30s for up to 10 minutes.
    """
    creds = Credentials.from_service_account_file("credentials.json")
    service = build("sheets", "v4", credentials=creds)

    RANGE_NAME = "URLs!C:Y"  # Fetch only relevant columns (C to Y)
    sheet = service.spreadsheets()

    # Initial wait before checking
    print(f"Waiting for {initial_wait} seconds before first check...")
    time.sleep(initial_wait)

    elapsed_time = initial_wait
    while elapsed_time < max_wait_time:
        result = sheet.values().get(spreadsheetId=google_sheet_id, range=RANGE_NAME).execute()
        values = result.get("values", [])

        # Create a dictionary for quick lookup: { session_id -> [responses, transcripts] }
        session_data = {row[0]: row[3:] for row in values if row and row[0] == session_id}
        print("session_data is:", session_data)

        if session_id in session_data:
            row_data = session_data[session_id]

            # Check if any response or transcript is missing
            for i in range(1, len(row_data), 2):
                if i + 1 < len(row_data):
                    response = row_data[i].strip() if row_data[i] else ""
                    transcript = row_data[i + 1].strip() if row_data[i + 1] else ""

                    if not response or not transcript:  # If either is empty, return immediately
                        print(f"Missing response or transcript at index {i}: ({response}, {transcript})")
                        return []  

            # If all responses and transcripts are present, return them
            return [(row_data[i], row_data[i + 1]) for i in range(1, len(row_data), 2) if i + 1 < len(row_data)]

        # Wait before retrying
        print(f"Waiting for transcript data... {elapsed_time}/{max_wait_time} seconds elapsed.")
        time.sleep(check_interval)
        elapsed_time += check_interval

    print("Timed out waiting for complete response and transcript data.")
    return []  # Return empty list if not all values are filled within the wait time

def send_email_with_links(project_code,session_id,sheet_id):
    """Fetches response & transcript links, grants access, and sends them via email."""
    project_code =  project_code
    session_id = session_id
    # print("sid",session_id)
    SHEET_URL = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    sh = gc.open_by_url(SHEET_URL)
    worksheet = sh.worksheet(sheet_name)
    recipient_emails = fetch_recipient_emails(project_code,sheet_id)
    session_links = fetch_response_links(session_id,sheet_id)
    print("sl",session_links)
    if session_links==[]:
        print("Email is not sent since some links are missing.")
        return
    grant_access_to_files(recipient_emails)  # Grant access before sending email
    
    email_content = f"Dear User,\n\nHere are the response and transcript links for the session {session_id} and Project {project_code}:\n\n"
    i=1
    for idx, (response_url, transcript_url) in enumerate(session_links,start=1):
        if idx <= 4:
            email_content += f"Prompt {idx}:\n"
            email_content += f"- Audio Response: {response_url}\n"
            email_content += f"- Transcript: {transcript_url}\n\n"
        else:
            email_content += f"Question {i}:\n"
            email_content += f"- Audio Response: {response_url}\n"
            email_content += f"- Transcript: {transcript_url}\n\n" 
            i=i+1

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