# firestore_db.py
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import datetime

# Ensure we only initialize once
if not firebase_admin._apps:
    # Use your service account json
    cred = credentials.Certificate("credentials.json") 
    firebase_admin.initialize_app(cred)

db = firestore.client()

def fs_update_response(project_code, session_id, prompt_index, audio_url, is_additional=False):
    """
    Writes the audio URL to Firestore.
    Note: We do NOT write transcript_url here because your Cloud Function handles that.
    """
    try:
        # 1. Point to the specific project and session
        # Collection: projects -> Doc: {project_code} -> Sub-Col: sessions -> Doc: {session_id}
        session_ref = db.collection('projects').document(project_code).collection('sessions').document(session_id)
        
        # 2. Determine the key (e.g., "1" or "AQ_1")
        key = str(prompt_index)
        if is_additional:
             # If prompt_index is complex for additional Qs, ensure it's a valid string key
             key = f"AQ_{prompt_index}"

        # 3. Prepare data
        # We use dot notation "responses.1.audio_url" to update nested fields
        field_path = f"responses.{key}"
        
        data_to_update = {
            f"{field_path}.audio_url": audio_url,
            f"{field_path}.updated_at": datetime.datetime.utcnow(),
            "last_interaction": datetime.datetime.utcnow(),
            "status": "in_progress" # Ensure status is set
        }
        
        # Only update index if it's a normal question
        if not is_additional:
            data_to_update["current_question_index"] = int(prompt_index)

        # 4. Write to DB (Merge = upsert)
        session_ref.set(data_to_update, merge=True)
        print(f"✅ Firestore: Saved {key} for {session_id} in {project_code}")

    except Exception as e:
        print(f"❌ Firestore Error: {e}")

        
def fs_log_activity(project_code, session_id, timestamp, details, client_ip):
    """
    Writes log activity to Firestore matching the structure of the CSV/Sheet.
    """
    try:
        # Handle the IP set/list conversion just like your sheets.py does
        # If it's a set like {ip}, convert to list and get first item, or join them
        if isinstance(client_ip, (set, list, tuple)):
            ip_str = ", ".join(str(x) for x in client_ip)
        else:
            ip_str = str(client_ip)

        # Construct the data dictionary matching your CSV columns
        # Session_id, TimeStamp, OS, OS Version, Browser, Browser version, Device, client IP
        log_entry = {
            "session_id": session_id,
            "timestamp": timestamp,  # Firestore handles datetime objects or strings automatically
            "os": details.get("os", ""),
            "os_version": details.get("os_version", ""),
            "browser": details.get("browser", ""),
            "browser_version": details.get("browser_version", ""),
            "device": details.get("device", ""),
            "client_ip": ip_str,
            "created_at": firestore.SERVER_TIMESTAMP # Helper for sorting by exact server time
        }

        # Use .add() because we want a new document for every single log event (auto-generated ID)
        db.collection('projects').document(project_code).collection('logs').add(log_entry)
        print(f"✅ Firestore Log Written for {session_id}")

    except Exception as e:
        print(f"❌ Firestore Log Error: {e}")