"""Consumes incident events; replace the log sink with Slack/email adapters."""
import json
import os
import time
from urllib.request import Request, urlopen

import redis

client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
group, stream, consumer = "notifications", "incident-events", "worker-1"


def notify_slack(event_type: str, payload: dict[str, str]) -> None:
    webhook = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook:
        return
    message = {"text": f":rotating_light: OpsPulse `{event_type}`\n*{payload['title']}* · {payload['severity']} · {payload['status']}"}
    request = Request(webhook, data=json.dumps(message).encode(), headers={"Content-Type": "application/json"})
    try:
        urlopen(request, timeout=5).read()
    except OSError as error:
        print(f"slack notification failed: {error}", flush=True)

try:
    client.xgroup_create(stream, group, id="0", mkstream=True)
except redis.ResponseError as error:
    if "BUSYGROUP" not in str(error):
        raise

while True:
    events = client.xreadgroup(group, consumer, {stream: ">"}, count=10, block=5000)
    for _, messages in events:
        for message_id, fields in messages:
            payload = json.loads(fields["payload"])
            print(f"notification event={fields['type']} severity={payload['severity']} incident={payload['id']}", flush=True)
            notify_slack(fields["type"], payload)
            client.xack(stream, group, message_id)
    time.sleep(0.1)
