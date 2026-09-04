"""Minimal S3 event handler used by the optional CDK lab."""

from datetime import datetime, timezone
from urllib.parse import unquote_plus
import json


def handler(event, context):
    objects = []
    for record in event.get("Records", []):
        s3_payload = record.get("s3", {})
        bucket = s3_payload.get("bucket", {}).get("name")
        key = unquote_plus(s3_payload.get("object", {}).get("key", ""))
        objects.append({"bucket": bucket, "key": key})

    print(
        json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "INFO",
                "message": "bronze objects received",
                "record_count": len(objects),
                "request_id": getattr(context, "aws_request_id", None),
                "objects": objects,
            }
        )
    )
    return {"processed": len(objects), "objects": objects}

