import os

from datetime import datetime
from typing import Optional
from google.cloud import firestore
from fireo.typedmodels import TypedModel
from fireo.database import connection


LOCAL_FIRESTORE = os.environ.get('LOCAL_FIRESTORE', 'OFF') == 'ON'
LOCAL_FIRESTORE_PORT = int(os.environ.get('LOCAL_FIRESTORE_PORT', '5001'))


if LOCAL_FIRESTORE:
    os.environ["FIRESTORE_EMULATOR_HOST"] = f"127.0.0.1:{LOCAL_FIRESTORE_PORT}"


connection(client=firestore.Client(database="shipodimapps"))


class Client(TypedModel):
    name: str
    spare_time_minutes: int
    status: str # "active", "dead"
    parent_name: str
    parent_contact: str
    issue_date: datetime
    valid_till: datetime
    comments: str

    class Meta:
        collection_name = "kidzyway_clients"


class ClientEvent(TypedModel):
    client_id: str
    event_timestamp_utc: datetime
    event: str # "enter", "leave", "package"
    event_spare_time_minutes: int
    comments: Optional[str]
    finalized: bool
    
    class Meta:
        collection_name = "kidzyway_client_events" 