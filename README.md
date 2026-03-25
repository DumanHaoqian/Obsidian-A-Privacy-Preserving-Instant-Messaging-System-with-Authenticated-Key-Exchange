# COMP3334 Secure IM - Phase 1 Runnable Prototype

This project gives you a **working client-server IM skeleton** for the first implementation milestone:

- registration
- password + OTP login
- session tokens
- friend requests (send / accept / decline / cancel)
- contacts list
- online message forwarding through WebSocket
- offline message queue + replay on reconnect
- conversation list ordered by recent activity
- unread counters
- explicit `delivered` acknowledgement from recipient client

It is intentionally a **Phase 1 prototype**.
It does **not yet** implement full E2EE, AAD, replay resistance, fingerprint verification, key change warnings, or self-destruct TTL.
Those are the next layers you will build on top of this skeleton.

## Folder layout

```text
im_phase1_system/
├── client/
│   ├── api_client.py
│   ├── cli.py
│   ├── otp.py
│   ├── state.py
│   └── ws_client.py
├── server/
│   ├── config.py
│   ├── db.py
│   ├── main.py
│   ├── rate_limit.py
│   ├── schemas.py
│   ├── security.py
│   └── ws_manager.py
├── data/
│   └── im_phase1.db         # created automatically
├── requirements.txt
└── README.md
```

## Design choices in this prototype

### Delivered semantics
This prototype uses **Option B semantics** for delivery status:

- `sent` means the sender successfully submitted the message to the server.
- `delivered` means the **recipient client** explicitly called `/messages/ack` after receiving the message.

This is stronger than “server queued it”.

### OTP
To keep the demo usable from one laptop, the register response returns the OTP secret and the CLI stores it locally in `client/client_state.json`.
That is convenient for demonstration, but for a production build you would provision the secret into an authenticator app and avoid storing it like this.

### Identity keys
The database already contains an `identity_public_keys` table and the server exposes placeholder routes:

- `POST /identity-key`
- `GET /identity-key/{username}`

That prepares the skeleton for the later E2EE phase.

## How to run

### 1. Create a virtual environment

#### Ubuntu / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

#### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Start the server

From the project root:

```bash
uvicorn server.main:app --reload
```

The server runs at:

```text
http://127.0.0.1:8000
```

### 3. Start one or more CLI clients

Open a new terminal for each client:

```bash
python client/cli.py http://127.0.0.1:8000
```

## Demo flow

In terminal A:

```text
register alice StrongPass123
login alice StrongPass123
store-dev-key
```

In terminal B:

```text
register bob StrongPass123
login bob StrongPass123
store-dev-key
```

Then in terminal A:

```text
send-request bob
```

In terminal B:

```text
pending
respond 1 accept
```

Then in terminal A:

```text
send bob hello bob
conversations
```

In terminal B:

```text
conversations
open 1
```

If Bob is online, Bob will receive a WebSocket push immediately.
If Bob is offline, the server will queue the message and replay it when Bob reconnects.

## Useful CLI commands

```text
help
register <username> <password>
login <username> <password>
logout
me
contacts
pending
send-request <username>
respond <request_id> <accept|decline>
cancel-request <request_id>
conversations
open <conversation_id> [limit]
send <username> <message text>
mark-read <conversation_id>
store-dev-key
exit
```

## API summary

### Auth
- `POST /register`
- `POST /login/password`
- `POST /login/otp`
- `POST /logout`
- `GET /me`

### Identity placeholder
- `POST /identity-key`
- `GET /identity-key/{username}`

### Friends / contacts
- `POST /friend-request/send`
- `GET /friend-request/pending`
- `POST /friend-request/respond`
- `POST /friend-request/cancel`
- `GET /contacts`

### Messages / conversations
- `POST /messages/send`
- `POST /messages/ack`
- `GET /messages/pull`
- `GET /conversations`
- `POST /conversations/{conversation_id}/mark-read`

### Realtime
- `GET /ws?token=<access_token>` using WebSocket

## What is already good enough for your report

You can already claim and demonstrate:

- client-server split
- session management
- password hashing with Argon2
- OTP second factor
- friend request lifecycle
- default anti-spam: only contacts can send chat messages
- explicit delivery acknowledgements
- offline store-and-forward behavior
- conversation list and unread counters
- basic abuse controls via in-memory rate limiting

## What you should build next

1. Replace `content` with ciphertext.
2. Add client-side identity keypair generation and persistent private-key storage.
3. Implement secure session establishment.
4. Add AEAD with authenticated metadata.
5. Add replay protection and duplicate detection.
6. Add key change warning and verification UI.
7. Add TTL/self-destruct messages and cleanup.
8. Add TLS for deployment.

## Notes and limitations

- This prototype is for local development and coursework demonstration.
- The server currently stores message plaintext because E2EE is not added yet.
- The OTP bootstrap flow is demo-friendly, not production-grade.
- The rate limiter is in-memory and process-local.
- TLS is not configured in this local prototype.

