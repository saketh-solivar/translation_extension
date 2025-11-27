# firestore_db.py
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import datetime
import time 

# Ensure we only initialize once
if not firebase_admin._apps:
    # Use your service account json
    cred = credentials.Certificate("credentials.json") 
    firebase_admin.initialize_app(cred)

db = firestore.client()

def fs_update_response(project_code, session_id, index, audio_url, response_type="prompt", additional_index=None):
    try:
        session_ref = db.collection('projects').document(project_code).collection('sessions').document(session_id)
        
        if response_type == "aqg":
            key = f"AQ_{index}_{additional_index}"
        elif response_type == "question":
            key = f"Q_{index}"
        else:
            key = f"P_{index}"

        field_path = f"responses.{key}"
        
        data_to_update = {
            f"{field_path}.audio_url": audio_url,
            f"{field_path}.updated_at": datetime.datetime.utcnow(),
            "last_interaction": datetime.datetime.utcnow(),
            "status": "in_progress"
        }

        if response_type == "prompt":
             data_to_update["current_prompt_index"] = int(index)
        elif response_type == "question":
             data_to_update["current_question_index"] = int(index)

        session_ref.set(data_to_update, merge=True)
        print(f"✅ Firestore: Saved {key} for {session_id}")

    except Exception as e:
        print(f"❌ Firestore Error: {e}")

def fs_log_activity(project_code, session_id, timestamp, details, client_ip):
    try:
        if isinstance(client_ip, (set, list, tuple)):
            ip_str = ", ".join(str(x) for x in client_ip)
        else:
            ip_str = str(client_ip)

        log_entry = {
            "session_id": session_id,
            "timestamp": timestamp,
            "os": details.get("os", ""),
            "os_version": details.get("os_version", ""),
            "browser": details.get("browser", ""),
            "browser_version": details.get("browser_version", ""),
            "device": details.get("device", ""),
            "client_ip": ip_str,
            "created_at": firestore.SERVER_TIMESTAMP
        }

        unique_id = f"{session_id}_{int(time.time()*1000)}"
        db.collection('projects').document(project_code).collection('logs').document(unique_id).set(log_entry)
        
        print(f"✅ Firestore Log Written: {unique_id}")

    except Exception as e:
        print(f"❌ Firestore Log Error: {e}")