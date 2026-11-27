import sys
import time
import uuid
import requests

texto = " ".join(sys.argv[1:]) or "Entregué 2 grandes a Perez, pagó 8000 en efectivo"

payload = {
    "event": "messages.upsert",
    "data": {
        "key": {
            "remoteJid": "5491176361030@s.whatsapp.net",
            "fromMe": False,
            "id": uuid.uuid4().hex,
        },
        "messageTimestamp": int(time.time()),
        "message": {"conversation": texto},
    },
}

r = requests.post("http://localhost:5000/webhook", json=payload, timeout=60)
print(r.status_code, r.text)