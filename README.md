# COMP3334 Secure IM Prototype with E2EE V1

This repository contains a runnable client-server instant messaging prototype for the COMP3334 secure IM project.

Current scope:

- 1:1 private messaging only
- CLI client (`client/cli.py`)
- FastAPI server (`server/main.py`)
- SQLite storage (`data/im_phase1.db`)
- single-device end-to-end encrypted messaging for the default CLI flow

The current CLI encrypts message bodies locally before upload and decrypts them locally after pull/push.
For `e2ee_text` messages the server stores ciphertext envelopes, not plaintext.

This is still a prototype, not a full modern messaging protocol.
It now includes TLS transport for client-server connections, but it does not yet implement encrypted local storage or multi-device secure sessions.

## Companion documents

- `USER_MENU.md`: command-by-command CLI usage guide
- `E2EE_IMPLEMENTATION.md`: detailed notes about the current E2EE V1 design
- `Tech_Doc/TTL_SELF_DESTRUCT_IMPLEMENTATION.md`: TTL / self-destruct design and validation notes
- `Tech_Doc/FINGERPRINT_VERIFICATION_IMPLEMENTATION.md`: manual fingerprint verification design and validation notes
- `Tech_Doc/TRUST_RESET_IMPLEMENTATION.md`: key-change trust reset design and validation notes
- `Tech_Doc/BLOCK_CONTACT_MANAGEMENT_IMPLEMENTATION.md`: block / unblock / remove-contact design and validation notes
- `Tech_Doc/CLI_PAGINATION_IMPLEMENTATION.md`: CLI paging / incremental loading design and validation notes
- `Tech_Doc/TLS_IMPLEMENTATION.md`: TLS transport design, local certificate workflow, and validation notes

## Repository layout

```text
Code/
|-- client/
|   |-- api_client.py
|   |-- cli.py
|   |-- client_state.json
|   |-- e2ee_client.py
|   |-- otp.py
|   |-- state.py
|   |-- tls.py
|   `-- ws_client.py
|-- data/
|   `-- im_phase1.db
|-- server/
|   |-- config.py
|   |-- db.py
|   |-- main.py
|   |-- rate_limit.py
|   |-- run_tls.py
|   |-- schemas.py
|   |-- security.py
|   |-- tls.py
|   `-- ws_manager.py
|-- shared/
|   `-- e2ee.py
|-- E2EE_IMPLEMENTATION.md
|-- README.md
|-- Tech_Doc/
|   `-- TLS_IMPLEMENTATION.md
|-- USER_MENU.md
`-- requirements.txt
```

## What the current code actually implements

### Accounts and authentication

- user registration with unique usernames
- Argon2 password hashing
- TOTP-based second factor
- two-step login: `/login/password` -> `/login/otp`
- bearer-token sessions with a 12-hour TTL
- logout by revoking the current token

Important demo behavior:

- `/register` returns the OTP secret and OTP URI
- the CLI stores OTP secrets locally in `client/client_state.json`
- on later `login`, the CLI auto-generates the OTP code from the stored secret if it exists

### Contacts and requests

- send friend request
- list incoming and outgoing pending requests
- accept or decline a received request
- cancel a sent pending request
- contacts list after acceptance
- block a user
- unblock a user
- remove a contact
- list blocked users
- contacts-only messaging by default

### Messaging and conversation flow

- send a 1:1 message to a contact
- WebSocket push for online recipients
- offline store-and-forward through the database
- explicit `delivered` acknowledgement from the recipient client
- conversation list ordered by recent activity
- unread counters per conversation
- pull message history with paging support
- mark messages as read

Additional implemented behavior:

- self-messaging is rejected
- message history includes `status`, `delivered_at`, `is_read`, and `read_at`
- encrypted conversation previews are shown as `[encrypted]`
- plaintext previews are truncated to 60 characters in `/conversations`

### E2EE V1

The default CLI `send` flow is end-to-end encrypted.

Implemented pieces:

- each local user gets a long-term X25519 identity keypair
- private keys stay in the local client state file
- public keys are uploaded to the server through `/identity-key`
- the client fetches peer public keys through `/identity-key/{username}`
- the client encrypts locally before `/messages/send`
- the client decrypts locally when handling WebSocket pushes or `open`
- the client stores trusted peer keys locally using TOFU (Trust On First Use)
- if a trusted peer key changes, sending is refused and decryption can be blocked

Important boundary:

- the server still knows sender, receiver, timestamps, contact graph, delivery/read status, and message sizes
- only the message body moves to ciphertext for `e2ee_text`

## E2EE V1 technical details

### Cryptographic choices

The shared E2EE implementation lives in `shared/e2ee.py`.

- key agreement: X25519
- KDF: HKDF-SHA256
- content encryption: AES-GCM
- public-key fingerprint: SHA-256 of the raw public key bytes
- message type for encrypted chat: `e2ee_text`
- default device id used by the prototype: `cli-device-1`
- new encrypted messages include a client-generated replay token for duplicate detection

### Envelope format

Encrypted messages are stored and transmitted as a JSON string with this shape:

```json
{
  "alg": "x25519-hkdf-sha256-aesgcm",
  "ciphertext": "...",
  "nonce": "...",
  "replay_token": "...",
  "salt": "...",
  "sender_device_id": "cli-device-1",
  "v": 2
}
```

The authenticated associated data (AAD) currently binds:

- `from_username`
- `to_username`
- `sender_device_id`
- `message_type`
- `replay_token` for V2 envelopes

This means tampering with those fields is detected during decryption.

### Trust model in the current client

The current CLI uses TOFU:

- on first send to a peer, it fetches that peer's active public key and saves it under `trusted_peer_keys`
- on first decrypt from an unseen peer, it does the same
- later sends compare the server's current key against the stored trusted key
- if the key has changed, the client raises a trust error and refuses to continue

What exists today:

- fingerprints are computed and printed in some CLI flows
- `fingerprint <username>` shows the peer's current fingerprint, trusted fingerprint, and verification state
- `verify <username>` marks the current trusted fingerprint as manually verified in local state
- key changes are detected
- `reset-trust <username>` adopts the peer's current server key as the new trusted candidate and blocks messaging until the user verifies again
- the client refuses to silently continue after a key mismatch

What does not exist yet:

- no multi-device trust management

### How the current encrypted flow works

1. User logs in.
2. The CLI ensures a local identity keypair exists for that username.
3. The CLI republishes the local public key through `/identity-key`.
4. On `send <username> <message>`, the CLI fetches or checks the trusted peer key.
5. The CLI encrypts the plaintext locally and uploads the JSON envelope as `message_type=e2ee_text`.
6. The server stores the envelope in `messages.content`.
7. The recipient CLI decrypts locally when it receives a push or opens history.

Important implementation detail:

- the server API still accepts plaintext `message_type='text'`
- the current CLI `send` command always sends `e2ee_text`

## Local state and stored data

### Client state

The CLI persists local state in `client/client_state.json`.

Current keys in that file:

- `known_otp_secrets`
- `access_token`
- `username`
- `device_keys`
- `trusted_peer_keys`
- `verified_peer_keys`
- `reverify_required_peer_keys`
- `replay_cache`

This means the local state file currently holds sensitive data in plaintext JSON, including:

- OTP secrets
- bearer tokens
- private identity keys
- trusted peer public keys
- locally stored peer verification records
- locally stored pending re-verification records after trust reset
- replay tokens for duplicate detection

Logging out clears the current `access_token` and `username`, but it does not delete stored OTP secrets, device keys, or trusted peer keys.

All CLI processes launched from the same checkout read and write the same `client/client_state.json`.

### Database

The server uses SQLite at `data/im_phase1.db`.

Current tables:

- `users`
- `otp_secrets`
- `sessions`
- `login_challenges`
- `identity_public_keys`
- `friend_requests`
- `contacts`
- `blocks`
- `conversations`
- `messages`
- `delivery_receipts`

Important storage facts:

- encrypted message envelopes are stored in `messages.content`
- plaintext API messages, if used, are also stored in `messages.content`
- `blocks` exists in the schema and is enforced by message/request checks
- the current CLI and API expose `block`, `unblock`, `remove-contact`, and blocked-user listing

## Limits and defaults

- session TTL: 12 hours
- login challenge TTL: 5 minutes
- default message page size: 20
- max message page size: 100
- max plaintext message length in the CLI: 4000 characters
- max encrypted message payload length on the server: 16000 characters
- registration rate limit: 10 requests / 60 seconds
- login rate limit: 20 requests / 60 seconds
- friend-request rate limit: 10 requests / 60 seconds

## How to run

### 1. Create a virtual environment

#### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

#### Ubuntu / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Optional: reset local demo state

If you want a clean run, remove the database and client state first:

#### Windows PowerShell

```powershell
Remove-Item .\data\im_phase1.db -Force -ErrorAction SilentlyContinue
Remove-Item .\client\client_state.json -Force -ErrorAction SilentlyContinue
```

#### Ubuntu / macOS

```bash
rm -f data/im_phase1.db client/client_state.json
```

### 3. Start the HTTPS/WSS server

```bash
python -m server.run_tls
```

Default server URL:

```text
https://127.0.0.1:8443
```

The local development CA certificate is generated automatically at:

```text
certs/dev/ca_cert.pem
```

### 4. Start the CLI

```bash
python client/cli.py https://127.0.0.1:8443 --ca-cert certs/dev/ca_cert.pem
```

If you keep the default certificate location created by `server.run_tls`, the CLI can also auto-discover it and you may omit `--ca-cert`.

## Basic demo flow

Terminal A:

```text
register alice StrongPass123
login alice StrongPass123
```

Terminal B:

```text
register bob StrongPass123
login bob StrongPass123
```

Terminal A:

```text
send-request bob
```

Terminal B:

```text
pending
respond 1 accept
```

Terminal A:

```text
send bob hello bob
conversations
```

Terminal B:

```text
conversations
open 1
```

Expected high-level result:

- Alice's CLI prints local/peer fingerprint info after send
- Bob sees plaintext after local decryption
- the server stores the encrypted envelope for the chat message
- the conversation list shows `[encrypted]` as the preview for the last encrypted message

## CLI commands

```text
help
register <username> <password>
login <username> <password>
logout
me
contacts
blocked
pending
send-request <username>
respond <request_id> <accept|decline>
cancel-request <request_id>
remove-contact <username>
block <username>
unblock <username>
conversations
open <conversation_id> [limit]
more <conversation_id> [limit]
send <username> <message text>
send-ttl <username> <ttl_seconds> <message text>
fingerprint <username>
verify <username>
reset-trust <username>
mark-read <conversation_id>
store-dev-key
exit
```

Notes:

- `login` also ensures and republishes the local identity key
- `send` always encrypts locally first
- `open` pulls the newest page of messages and saves the next paging cursor
- `more` uses the saved cursor to load older messages for the same conversation
- `store-dev-key` republishes the current local public key and prints the local fingerprint

## HTTP API summary

### Auth

- `POST /register`
- `POST /login/password`
- `POST /login/otp`
- `POST /logout`
- `GET /me`

### Identity keys

- `POST /identity-key`
- `GET /identity-key/{username}`

### Friend requests and contacts

- `POST /friend-request/send`
- `GET /friend-request/pending`
- `POST /friend-request/respond`
- `POST /friend-request/cancel`
- `GET /contacts`
- `POST /contacts/remove`
- `GET /blocks`
- `POST /blocks/block`
- `POST /blocks/unblock`

### Messages and conversations

- `POST /messages/send`
- `POST /messages/ack`
- `GET /messages/pull`
- `POST /conversations/{conversation_id}/mark-read`
- `GET /conversations`

Useful API details:

- `/messages/send` accepts `message_type` of `text` or `e2ee_text`
- `/messages/pull` supports `conversation_id`, `limit`, `before_id`, and `mark_read`

### WebSocket

- `GET /ws?token=<access_token>`

Server-side pushed events currently used by the system:

- `system`
- `new_message`
- `message_ack`
- `friend_request_update`
- `pong` (reply to client `ping`)

## Status against the current course requirements

### Implemented

- registration with password hashing and basic input validation
- password + OTP login
- logout / token revocation
- long-term per-user local identity keypair generation
- public identity key upload and lookup
- single-device E2EE message encryption/decryption for the CLI flow
- authenticated encryption with metadata binding
- basic replay protection / duplicate detection for new encrypted messages
- friend request send / accept / decline / cancel
- block / unblock / remove contact management
- contacts-only messaging by default
- HTTPS / WSS transport with certificate verification for the client-server channel
- sent / delivered status, with delivered triggered by recipient client acknowledgement
- offline store-and-forward for the current encrypted CLI flow
- conversation list, unread counters, and basic paging
- basic timed self-destruct messages with server-timed expiry and best-effort expiry cleanup

### Partially implemented

- replay protection: new encrypted messages carry a replay token and duplicate deliveries are detected locally, but legacy V1 messages remain unprotected

### Not implemented yet

- retention cleanup based on `MESSAGE_RETENTION_DAYS`
- encrypted local storage / OS keychain integration
- prekeys, double ratchet, forward secrecy, or post-compromise recovery
- multi-device session support

## Current limitations and important facts

- The current E2EE design is static-key, TOFU-based, and single-device.
- If a peer has multiple active identity keys and none matches `cli-device-1`, the client refuses because the prototype only supports one device.
- New encrypted messages use a client-generated replay token. The client suppresses duplicate delivery of the same message id and blocks the same replay token if it reappears under a different server message id.
- Legacy V1 encrypted messages created before replay tokens were added remain readable, but they do not gain replay protection retroactively.
- `delivered` means the recipient client called `/messages/ack` after receipt. It is not a read receipt.
- delivery acknowledgements are server-visible control messages; they are not E2EE payloads
- In the current CLI, delivery ack is still attempted after duplicate/replay detection or decryption error placeholders so the server stops resending the message.
- Blocking a user removes the bidirectional contact relationship, deletes pending friend requests between the pair, and drops undelivered incoming messages from that blocked user.
- `open` marks returned unread messages as read by default.
- The WebSocket listener retries on connection errors and clears the local session if reconnect fails with authentication errors.
- `MESSAGE_RETENTION_DAYS = 7` exists in config but is not currently enforced as a general max-age retention rule in the server logic.
- Local development TLS uses a generated CA plus a leaf certificate for `localhost` / `127.0.0.1`; production deployment would still need a properly managed certificate chain.

## What to build next

The most important missing items for the course project are:

1. secure local storage for client secrets and private keys
2. stronger forward-secrecy-oriented session design
3. richer multi-device key management
