import os
import json
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient
from datetime import datetime, timezone

load_dotenv()  # reads variables from .env into environment

CONTAINER_NAME = 'assignment-reports'


def _get_blob_service_client():
    connection_string = os.environ['AZURE_STORAGE_CONNECTION_STRING']
    return BlobServiceClient.from_connection_string(connection_string)


def upload_summary_to_blob(summary_data: dict):
    """Uploads a run summary JSON to Azure Blob Storage.
    Returns a dict describing the outcome so callers can record pipeline status
    without needing to catch exceptions themselves.
    """
    try:
        blob_service_client = _get_blob_service_client()

        try:
            container_client = blob_service_client.create_container(CONTAINER_NAME)
            print(f"Container '{CONTAINER_NAME}' created.")
        except Exception:
            container_client = blob_service_client.get_container_client(CONTAINER_NAME)
            print(f"Container '{CONTAINER_NAME}' already exists, using it.")

        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        blob_name = f"summary_{timestamp}.json"

        blob_client = container_client.get_blob_client(blob_name)
        blob_client.upload_blob(json.dumps(summary_data, indent=2), overwrite=True)

        print(f"Uploaded '{blob_name}' to Azure Blob Storage.")
        return {"status": "ok", "blob_name": blob_name, "container": CONTAINER_NAME}

    except Exception as e:
        print(f"[AZURE UPLOAD FAILED] {e}")
        return {"status": "error", "detail": str(e)}


def fetch_recent_summaries(limit=10):
    """Reads the most recent run summaries back from Azure Blob Storage, oldest first.
    Blob names contain a timestamp, so sorting by name is the same as sorting by time.
    Returns an empty list on any failure so the pipeline keeps running.
    """
    try:
        container_client = _get_blob_service_client().get_container_client(CONTAINER_NAME)

        blob_names = sorted(
            b.name for b in container_client.list_blobs()
            if b.name.startswith('summary_') and b.name.endswith('.json')
        )

        history = []
        for name in blob_names[-limit:]:
            raw = container_client.get_blob_client(name).download_blob().readall()
            entry = json.loads(raw)
            entry['blob_name'] = name
            history.append(entry)

        print(f"Read {len(history)} past run summaries back from Azure Blob Storage.")
        return history

    except Exception as e:
        print(f"[AZURE HISTORY READ FAILED] {e}")
        return []


# Quick standalone test
if __name__ == '__main__':
    result = upload_summary_to_blob({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_assignments": 8,
        "submitted_count": 7,
        "reminders_sent": 0,
        "overdue_count": 0,
        "upcoming_count": 1
    })
    print(result)
    print(fetch_recent_summaries())