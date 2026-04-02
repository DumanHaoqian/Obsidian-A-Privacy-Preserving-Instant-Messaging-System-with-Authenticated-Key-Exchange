from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from shared.e2ee import EnvelopeError, extract_ttl_seconds, parse_envelope

from .config import (
    DEFAULT_MESSAGE_PAGE_SIZE,
    FRIEND_REQUEST_RATE_LIMIT,
    LOGIN_CHALLENGE_TTL_SECONDS,
    LOGIN_RATE_LIMIT,
    MAX_PLAINTEXT_MESSAGE_LENGTH,
    MAX_MESSAGE_LENGTH,
    MAX_MESSAGE_PAGE_SIZE,
    REGISTER_RATE_LIMIT,
    SESSION_TTL_SECONDS,
)
from .db import db_cursor, future_ts, init_db, parse_ts, utcnow
from .rate_limit import InMemoryRateLimiter
from .schemas import (
    BasicResponse,
    FriendRequestCancelRequest,
    FriendRequestRespondRequest,
    FriendRequestSendRequest,
    FriendRequestSendResponse,
    IdentityKeyUpsertRequest,
    LoginOtpRequest,
    LoginOtpResponse,
    LoginPasswordRequest,
    LoginPasswordResponse,
    MarkReadResponse,
    MessageAckRequest,
    MessageSendRequest,
    RegisterRequest,
    RegisterResponse,
)
from .security import (
    generate_otp_secret,
    generate_token,
    hash_password,
    otp_uri,
    verify_password,
    verify_totp,
)
from .ws_manager import ConnectionManager

app = FastAPI(title='COMP3334 IM Phase 1 Prototype', version='1.0.0')
manager = ConnectionManager()
rate_limiter = InMemoryRateLimiter()
EXPIRY_CLEANUP_INTERVAL_SECONDS = 2.0
_expiry_cleanup_lock = threading.Lock()
_last_expiry_cleanup_monotonic = 0.0

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.on_event('startup')
def startup_event() -> None:
    init_db()
    cleanup_expired_messages(force=True)


# ------------------------------
# Helpers
# ------------------------------

def get_bearer_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith('bearer '):
        raise HTTPException(status_code=401, detail='missing bearer token')
    return authorization.split(' ', 1)[1].strip()


def fetch_user_by_username(cur: sqlite3.Cursor, username: str) -> Optional[sqlite3.Row]:
    cur.execute('SELECT * FROM users WHERE username = ? AND is_active = 1', (username.lower(),))
    return cur.fetchone()


def fetch_user_by_id(cur: sqlite3.Cursor, user_id: int) -> Optional[sqlite3.Row]:
    cur.execute('SELECT * FROM users WHERE id = ? AND is_active = 1', (user_id,))
    return cur.fetchone()


def get_current_user(authorization: Optional[str] = Header(default=None)) -> sqlite3.Row:
    token = get_bearer_token(authorization)
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT users.*
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ?
              AND sessions.revoked_at IS NULL
              AND sessions.expires_at > ?
              AND users.is_active = 1
            """,
            (token, utcnow()),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail='invalid or expired token')
        return row


def require_rate_limit(request: Request, key_prefix: str, limit: tuple[int, int], identity: str = '') -> None:
    ip = request.client.host if request.client else 'unknown'
    key = f'{key_prefix}:{ip}:{identity}'
    allowed = rate_limiter.allow(key, limit[0], limit[1])
    if not allowed:
        raise HTTPException(status_code=429, detail='rate limit exceeded, please try again later')


def are_friends(cur: sqlite3.Cursor, user_a: int, user_b: int) -> bool:
    cur.execute(
        "SELECT 1 FROM contacts WHERE user_id = ? AND contact_user_id = ? AND status = 'active'",
        (user_a, user_b),
    )
    return cur.fetchone() is not None


def is_blocked(cur: sqlite3.Cursor, by_user: int, target_user: int) -> bool:
    cur.execute('SELECT 1 FROM blocks WHERE user_id = ? AND blocked_user_id = ?', (by_user, target_user))
    return cur.fetchone() is not None


def get_or_create_conversation(cur: sqlite3.Cursor, user_a: int, user_b: int) -> int:
    low, high = sorted((user_a, user_b))
    cur.execute('SELECT id FROM conversations WHERE user_low_id = ? AND user_high_id = ?', (low, high))
    row = cur.fetchone()
    if row:
        return row['id']
    cur.execute(
        'INSERT INTO conversations (user_low_id, user_high_id, created_at) VALUES (?, ?, ?)',
        (low, high, utcnow()),
    )
    return int(cur.lastrowid)


def build_message_payload(cur: sqlite3.Cursor, message_id: int) -> dict[str, Any]:
    cur.execute(
        """
        SELECT m.*, su.username AS sender_username, ru.username AS receiver_username
        FROM messages m
        JOIN users su ON su.id = m.sender_id
        JOIN users ru ON ru.id = m.receiver_id
        WHERE m.id = ?
        """,
        (message_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='message not found')
    return {
        'message_id': row['id'],
        'conversation_id': row['conversation_id'],
        'from_username': row['sender_username'],
        'to_username': row['receiver_username'],
        'content': row['content'],
        'message_type': row['message_type'],
        'ttl_seconds': row['ttl_seconds'],
        'expires_at': row['expires_at'],
        'status': row['status'],
        'is_offline_queued': bool(row['is_offline_queued']),
        'is_read': bool(row['is_read']),
        'created_at': row['created_at'],
        'delivered_at': row['delivered_at'],
        'read_at': row['read_at'],
    }


def notify_friend_request_change(request_id: int) -> None:
    # Helper retained for future expansion; notification is emitted inline in the endpoints.
    return None


def cleanup_expired_messages(force: bool = False) -> int:
    global _last_expiry_cleanup_monotonic
    now_monotonic = time.monotonic()
    if not force and now_monotonic - _last_expiry_cleanup_monotonic < EXPIRY_CLEANUP_INTERVAL_SECONDS:
        return 0

    with _expiry_cleanup_lock:
        now_monotonic = time.monotonic()
        if not force and now_monotonic - _last_expiry_cleanup_monotonic < EXPIRY_CLEANUP_INTERVAL_SECONDS:
            return 0

        now_iso = utcnow()
        with db_cursor(commit=True) as cur:
            cur.execute(
                'SELECT id, conversation_id FROM messages WHERE expires_at IS NOT NULL AND expires_at <= ?',
                (now_iso,),
            )
            expired_rows = cur.fetchall()
            if not expired_rows:
                _last_expiry_cleanup_monotonic = time.monotonic()
                return 0

            message_ids = [int(row['id']) for row in expired_rows]
            conversation_ids = sorted({int(row['conversation_id']) for row in expired_rows})
            cur.execute(
                f"DELETE FROM messages WHERE id IN ({','.join(['?'] * len(message_ids))})",
                tuple(message_ids),
            )
            for conversation_id in conversation_ids:
                cur.execute(
                    'SELECT id, created_at FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1',
                    (conversation_id,),
                )
                latest = cur.fetchone()
                if latest:
                    cur.execute(
                        'UPDATE conversations SET last_message_id = ?, last_message_at = ? WHERE id = ?',
                        (latest['id'], latest['created_at'], conversation_id),
                    )
                else:
                    cur.execute(
                        'UPDATE conversations SET last_message_id = NULL, last_message_at = NULL WHERE id = ?',
                        (conversation_id,),
                    )

        _last_expiry_cleanup_monotonic = time.monotonic()
        return len(expired_rows)


# ------------------------------
# Auth routes
# ------------------------------
@app.post('/register', response_model=RegisterResponse)
def register(payload: RegisterRequest, request: Request) -> RegisterResponse:
    require_rate_limit(request, 'register', REGISTER_RATE_LIMIT, payload.username)
    with db_cursor(commit=True) as cur:
        existing = fetch_user_by_username(cur, payload.username)
        if existing:
            raise HTTPException(status_code=400, detail='username already exists')
        cur.execute(
            'INSERT INTO users (username, password_hash, created_at, is_active) VALUES (?, ?, ?, 1)',
            (payload.username, hash_password(payload.password), utcnow()),
        )
        user_id = int(cur.lastrowid)
        secret = generate_otp_secret()
        cur.execute(
            'INSERT INTO otp_secrets (user_id, otp_secret, is_enabled, created_at) VALUES (?, ?, 1, ?)',
            (user_id, secret, utcnow()),
        )
        uri = otp_uri(secret, payload.username)
        return RegisterResponse(
            user_id=user_id,
            username=payload.username,
            otp_secret=secret,
            otp_uri=uri,
            message='registration successful; save the OTP secret in your authenticator app',
        )


@app.post('/login/password', response_model=LoginPasswordResponse)
def login_password(payload: LoginPasswordRequest, request: Request) -> LoginPasswordResponse:
    username = payload.username.lower().strip()
    require_rate_limit(request, 'login_password', LOGIN_RATE_LIMIT, username)
    with db_cursor(commit=True) as cur:
        user = fetch_user_by_username(cur, username)
        if not user or not verify_password(payload.password, user['password_hash']):
            raise HTTPException(status_code=401, detail='invalid username or password')
        challenge_token = generate_token(24)
        cur.execute(
            'INSERT INTO login_challenges (user_id, challenge_token, expires_at, created_at) VALUES (?, ?, ?, ?)',
            (user['id'], challenge_token, future_ts(LOGIN_CHALLENGE_TTL_SECONDS), utcnow()),
        )
        return LoginPasswordResponse(challenge_token=challenge_token)


@app.post('/login/otp', response_model=LoginOtpResponse)
def login_otp(payload: LoginOtpRequest, request: Request) -> LoginOtpResponse:
    require_rate_limit(request, 'login_otp', LOGIN_RATE_LIMIT, payload.challenge_token)
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            SELECT login_challenges.*, otp_secrets.otp_secret, users.id AS user_id
            FROM login_challenges
            JOIN users ON users.id = login_challenges.user_id
            JOIN otp_secrets ON otp_secrets.user_id = users.id
            WHERE login_challenges.challenge_token = ?
              AND login_challenges.used_at IS NULL
              AND login_challenges.expires_at > ?
            """,
            (payload.challenge_token, utcnow()),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail='invalid or expired challenge token')
        if not verify_totp(row['otp_secret'], payload.otp_code):
            raise HTTPException(status_code=401, detail='invalid OTP code')
        cur.execute('UPDATE login_challenges SET used_at = ? WHERE id = ?', (utcnow(), row['id']))
        access_token = generate_token(32)
        expires_at = future_ts(SESSION_TTL_SECONDS)
        cur.execute(
            'INSERT INTO sessions (user_id, token, expires_at, created_at) VALUES (?, ?, ?, ?)',
            (row['user_id'], access_token, expires_at, utcnow()),
        )
        return LoginOtpResponse(access_token=access_token, expires_at=expires_at)


@app.post('/logout', response_model=BasicResponse)
def logout(current_user: sqlite3.Row = Depends(get_current_user), authorization: Optional[str] = Header(default=None)) -> BasicResponse:
    token = get_bearer_token(authorization)
    with db_cursor(commit=True) as cur:
        cur.execute('UPDATE sessions SET revoked_at = ? WHERE token = ? AND user_id = ?', (utcnow(), token, current_user['id']))
    return BasicResponse(message='logged out successfully')


@app.get('/me')
def me(current_user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
    return {
        'id': current_user['id'],
        'username': current_user['username'],
        'created_at': current_user['created_at'],
    }


# ------------------------------
# Identity key placeholder routes (for later phases)
# ------------------------------
@app.post('/identity-key', response_model=BasicResponse)
def upsert_identity_key(payload: IdentityKeyUpsertRequest, current_user: sqlite3.Row = Depends(get_current_user)) -> BasicResponse:
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO identity_public_keys (user_id, device_id, public_key, created_at, is_active)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(user_id, device_id) DO UPDATE SET public_key = excluded.public_key, is_active = 1
            """,
            (current_user['id'], payload.device_id, payload.public_key, utcnow()),
        )
    return BasicResponse(message='identity public key stored')


@app.get('/identity-key/{username}')
def get_identity_key(username: str, current_user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
    with db_cursor() as cur:
        user = fetch_user_by_username(cur, username.lower())
        if not user:
            raise HTTPException(status_code=404, detail='user not found')
        cur.execute(
            'SELECT device_id, public_key, created_at, is_active FROM identity_public_keys WHERE user_id = ? AND is_active = 1',
            (user['id'],),
        )
        rows = [dict(row) for row in cur.fetchall()]
        return {'username': user['username'], 'keys': rows}


# ------------------------------
# Friend / contact routes
# ------------------------------
@app.post('/friend-request/send', response_model=FriendRequestSendResponse)
async def friend_request_send(
    payload: FriendRequestSendRequest, request: Request, current_user: sqlite3.Row = Depends(get_current_user)
) -> FriendRequestSendResponse:
    target_username = payload.target_username.lower().strip()
    require_rate_limit(request, 'friend_request', FRIEND_REQUEST_RATE_LIMIT, f'{current_user["username"]}->{target_username}')
    with db_cursor(commit=True) as cur:
        target = fetch_user_by_username(cur, target_username)
        if not target:
            raise HTTPException(status_code=404, detail='target user not found')
        if target['id'] == current_user['id']:
            raise HTTPException(status_code=400, detail='cannot send a friend request to yourself')
        if is_blocked(cur, target['id'], current_user['id']) or is_blocked(cur, current_user['id'], target['id']):
            raise HTTPException(status_code=403, detail='friend request blocked by user policy')
        if are_friends(cur, current_user['id'], target['id']):
            raise HTTPException(status_code=400, detail='you are already contacts')
        cur.execute(
            """
            SELECT 1 FROM friend_requests
            WHERE status = 'pending'
              AND (
                (from_user_id = ? AND to_user_id = ?)
                OR
                (from_user_id = ? AND to_user_id = ?)
              )
            """,
            (current_user['id'], target['id'], target['id'], current_user['id']),
        )
        if cur.fetchone():
            raise HTTPException(status_code=400, detail='friend request already pending')
        cur.execute(
            """
            INSERT INTO friend_requests (from_user_id, to_user_id, status, created_at)
            VALUES (?, ?, 'pending', ?)
            """,
            (current_user['id'], target['id'], utcnow()),
        )
        request_id = int(cur.lastrowid)

    await manager.send_to_user(
        target['id'],
        {
            'event': 'friend_request_update',
            'data': {
                'request_id': request_id,
                'from_username': current_user['username'],
                'status': 'pending',
            },
        },
    )
    return FriendRequestSendResponse(
        message='friend request sent',
        request_id=request_id,
        target_username=target['username'],
        target_user_id=int(target['id']),
    )


@app.get('/friend-request/pending')
def friend_request_pending(current_user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT fr.id, fr.from_user_id, fr.to_user_id, fr.status, fr.created_at, fr.responded_at,
                   fu.username AS from_username, tu.username AS to_username
            FROM friend_requests fr
            JOIN users fu ON fu.id = fr.from_user_id
            JOIN users tu ON tu.id = fr.to_user_id
            WHERE (fr.to_user_id = ? OR fr.from_user_id = ?)
              AND fr.status = 'pending'
            ORDER BY fr.created_at DESC
            """,
            (current_user['id'], current_user['id']),
        )
        incoming, outgoing = [], []
        uid = int(current_user['id'])
        for row in cur.fetchall():
            item = {
                'request_id': row['id'],
                'status': row['status'],
                'created_at': row['created_at'],
                'responded_at': row['responded_at'],
                'from_username': row['from_username'],
                'to_username': row['to_username'],
            }
            if int(row['to_user_id']) == uid:
                incoming.append(item)
            else:
                outgoing.append(item)
        return {'incoming': incoming, 'outgoing': outgoing}


@app.post('/friend-request/respond', response_model=BasicResponse)
async def friend_request_respond(payload: FriendRequestRespondRequest, current_user: sqlite3.Row = Depends(get_current_user)) -> BasicResponse:
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            SELECT fr.*, fu.username AS from_username, tu.username AS to_username
            FROM friend_requests fr
            JOIN users fu ON fu.id = fr.from_user_id
            JOIN users tu ON tu.id = fr.to_user_id
            WHERE fr.id = ?
            """,
            (payload.request_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='friend request not found')
        if row['to_user_id'] != current_user['id']:
            raise HTTPException(status_code=403, detail='you are not the recipient of this request')
        if row['status'] != 'pending':
            raise HTTPException(status_code=400, detail=f'request already {row["status"]}')
        new_status = 'accepted' if payload.action == 'accept' else 'declined'
        cur.execute(
            'UPDATE friend_requests SET status = ?, responded_at = ? WHERE id = ?',
            (new_status, utcnow(), payload.request_id),
        )
        if payload.action == 'accept':
            created_at = utcnow()
            cur.execute(
                "INSERT OR IGNORE INTO contacts (user_id, contact_user_id, status, created_at) VALUES (?, ?, 'active', ?)",
                (row['from_user_id'], row['to_user_id'], created_at),
            )
            cur.execute(
                "INSERT OR IGNORE INTO contacts (user_id, contact_user_id, status, created_at) VALUES (?, ?, 'active', ?)",
                (row['to_user_id'], row['from_user_id'], created_at),
            )
            # Clean up any reciprocal/duplicate pending requests left behind by older behavior.
            cur.execute(
                """
                UPDATE friend_requests
                SET status = 'cancelled', responded_at = ?
                WHERE status = 'pending'
                  AND id != ?
                  AND (
                    (from_user_id = ? AND to_user_id = ?)
                    OR
                    (from_user_id = ? AND to_user_id = ?)
                  )
                """,
                (
                    created_at,
                    payload.request_id,
                    row['from_user_id'],
                    row['to_user_id'],
                    row['to_user_id'],
                    row['from_user_id'],
                ),
            )
    await manager.send_to_user(
        row['from_user_id'],
        {
            'event': 'friend_request_update',
            'data': {
                'request_id': payload.request_id,
                'from_username': row['from_username'],
                'to_username': row['to_username'],
                'status': new_status,
            },
        },
    )
    return BasicResponse(message=f'friend request {new_status}')


@app.post('/friend-request/cancel', response_model=BasicResponse)
def friend_request_cancel(payload: FriendRequestCancelRequest, current_user: sqlite3.Row = Depends(get_current_user)) -> BasicResponse:
    with db_cursor(commit=True) as cur:
        cur.execute('SELECT * FROM friend_requests WHERE id = ?', (payload.request_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='friend request not found')
        if row['from_user_id'] != current_user['id']:
            raise HTTPException(status_code=403, detail='you are not the sender of this request')
        if row['status'] != 'pending':
            raise HTTPException(status_code=400, detail='only pending requests can be canceled')
        cur.execute('UPDATE friend_requests SET status = ?, responded_at = ? WHERE id = ?', ('cancelled', utcnow(), payload.request_id))
    return BasicResponse(message='friend request cancelled')


@app.get('/contacts')
def contacts(current_user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT u.id, u.username, c.created_at
            FROM contacts c
            JOIN users u ON u.id = c.contact_user_id
            WHERE c.user_id = ? AND c.status = 'active'
            ORDER BY u.username ASC
            """,
            (current_user['id'],),
        )
        return {'contacts': [dict(row) for row in cur.fetchall()]}


# ------------------------------
# Message and conversation routes
# ------------------------------
@app.post('/messages/send')
async def messages_send(payload: MessageSendRequest, current_user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
    cleanup_expired_messages()
    message_size_limit = MAX_PLAINTEXT_MESSAGE_LENGTH if payload.message_type == 'text' else MAX_MESSAGE_LENGTH
    if len(payload.content) > message_size_limit:
        raise HTTPException(status_code=400, detail='message too large')
    ttl_seconds = payload.ttl_seconds
    if payload.message_type == 'e2ee_text':
        try:
            parse_envelope(payload.content)
            envelope_ttl_seconds = extract_ttl_seconds(payload.content)
        except EnvelopeError as exc:
            raise HTTPException(status_code=400, detail=f'invalid encrypted message envelope: {exc}') from exc
        if ttl_seconds is None:
            ttl_seconds = envelope_ttl_seconds
        elif envelope_ttl_seconds is None:
            raise HTTPException(status_code=400, detail='self-destruct encrypted messages must carry ttl_seconds in the envelope')
        elif envelope_ttl_seconds != ttl_seconds:
            raise HTTPException(status_code=400, detail='ttl_seconds mismatch between request and encrypted envelope')

    expires_at = future_ts(ttl_seconds) if ttl_seconds is not None else None

    with db_cursor(commit=True) as cur:
        target = fetch_user_by_username(cur, payload.to_username.lower().strip())
        if not target:
            raise HTTPException(status_code=404, detail='recipient not found')
        if target['id'] == current_user['id']:
            raise HTTPException(status_code=400, detail='self-messaging is not supported in this prototype')
        if is_blocked(cur, target['id'], current_user['id']) or is_blocked(cur, current_user['id'], target['id']):
            raise HTTPException(status_code=403, detail='message blocked by user policy')
        if not are_friends(cur, current_user['id'], target['id']):
            raise HTTPException(status_code=403, detail='you can only send chat messages to contacts')
        conversation_id = get_or_create_conversation(cur, current_user['id'], target['id'])
        cur.execute(
            """
            INSERT INTO messages (
                conversation_id, sender_id, receiver_id, content, message_type,
                status, is_offline_queued, is_read, ttl_seconds, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, 'sent', 0, 0, ?, ?, ?)
            """,
            (
                conversation_id,
                current_user['id'],
                target['id'],
                payload.content,
                payload.message_type,
                ttl_seconds,
                utcnow(),
                expires_at,
            ),
        )
        message_id = int(cur.lastrowid)
        cur.execute(
            'UPDATE conversations SET last_message_id = ?, last_message_at = ? WHERE id = ?',
            (message_id, utcnow(), conversation_id),
        )
        cur.execute(
            'INSERT INTO delivery_receipts (message_id, receipt_type, actor_user_id, created_at) VALUES (?, ?, ?, ?)',
            (message_id, 'sent', current_user['id'], utcnow()),
        )
        message_payload = build_message_payload(cur, message_id)

    delivered_to_socket = await manager.send_to_user(target['id'], {'event': 'new_message', 'data': message_payload})
    if not delivered_to_socket:
        with db_cursor(commit=True) as cur:
            cur.execute('UPDATE messages SET is_offline_queued = 1 WHERE id = ?', (message_id,))
        message_payload['is_offline_queued'] = True
    return {'ok': True, 'message': 'submitted', 'data': message_payload}


@app.post('/messages/ack', response_model=BasicResponse)
async def messages_ack(payload: MessageAckRequest, current_user: sqlite3.Row = Depends(get_current_user)) -> BasicResponse:
    cleanup_expired_messages()
    with db_cursor(commit=True) as cur:
        cur.execute(
            """
            SELECT m.*, su.username AS sender_username, ru.username AS receiver_username
            FROM messages m
            JOIN users su ON su.id = m.sender_id
            JOIN users ru ON ru.id = m.receiver_id
            WHERE m.id = ?
            """,
            (payload.message_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='message not found')
        if row['receiver_id'] != current_user['id']:
            raise HTTPException(status_code=403, detail='only the recipient can ack this message')
        if row['delivered_at'] is None:
            cur.execute(
                'UPDATE messages SET status = ?, delivered_at = ?, is_offline_queued = 0 WHERE id = ?',
                ('delivered', utcnow(), payload.message_id),
            )
            cur.execute(
                'INSERT INTO delivery_receipts (message_id, receipt_type, actor_user_id, created_at) VALUES (?, ?, ?, ?)',
                (payload.message_id, 'delivered', current_user['id'], utcnow()),
            )
        ack_payload = {
            'event': 'message_ack',
            'data': {
                'message_id': payload.message_id,
                'status': 'delivered',
                'from_username': current_user['username'],
                'delivered_at': utcnow(),
            },
        }
        sender_id = row['sender_id']
    await manager.send_to_user(sender_id, ack_payload)
    return BasicResponse(message='delivery ack recorded')


@app.get('/messages/pull')
def messages_pull(
    conversation_id: int = Query(..., ge=1),
    limit: int = Query(DEFAULT_MESSAGE_PAGE_SIZE, ge=1, le=MAX_MESSAGE_PAGE_SIZE),
    before_id: Optional[int] = Query(default=None, ge=1),
    mark_read: bool = Query(default=False),
    current_user: sqlite3.Row = Depends(get_current_user),
) -> dict[str, Any]:
    cleanup_expired_messages()
    with db_cursor(commit=True) as cur:
        cur.execute('SELECT * FROM conversations WHERE id = ?', (conversation_id,))
        conversation = cur.fetchone()
        if not conversation:
            raise HTTPException(status_code=404, detail='conversation not found')
        if current_user['id'] not in (conversation['user_low_id'], conversation['user_high_id']):
            raise HTTPException(status_code=403, detail='not a member of this conversation')

        sql = (
            """
            SELECT m.*, su.username AS sender_username, ru.username AS receiver_username
            FROM messages m
            JOIN users su ON su.id = m.sender_id
            JOIN users ru ON ru.id = m.receiver_id
            WHERE m.conversation_id = ?
            """
        )
        params: list[Any] = [conversation_id]
        if before_id is not None:
            sql += ' AND m.id < ?'
            params.append(before_id)
        sql += ' ORDER BY m.id DESC LIMIT ?'
        params.append(limit)
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()

        marked_message_ids: set[int] = set()
        mark_read_ts: Optional[str] = None
        if mark_read:
            message_ids = [row['id'] for row in rows if row['receiver_id'] == current_user['id'] and not row['is_read']]
            if message_ids:
                mark_read_ts = utcnow()
                marked_message_ids = set(message_ids)
                cur.execute(
                    f"UPDATE messages SET is_read = 1, read_at = ? WHERE id IN ({','.join(['?'] * len(message_ids))})",
                    (mark_read_ts, *message_ids),
                )

        messages = []
        for row in reversed(rows):
            was_marked_now = row['id'] in marked_message_ids
            messages.append(
                {
                    'message_id': row['id'],
                    'conversation_id': row['conversation_id'],
                    'from_username': row['sender_username'],
                    'to_username': row['receiver_username'],
                    'content': row['content'],
                    'message_type': row['message_type'],
                    'ttl_seconds': row['ttl_seconds'],
                    'expires_at': row['expires_at'],
                    'status': row['status'],
                    'is_offline_queued': bool(row['is_offline_queued']),
                    'is_read': bool(row['is_read']) or was_marked_now,
                    'created_at': row['created_at'],
                    'delivered_at': row['delivered_at'],
                    'read_at': mark_read_ts if was_marked_now else row['read_at'],
                }
            )
        next_before_id = rows[-1]['id'] if rows else None
        return {'messages': messages, 'next_before_id': next_before_id}


@app.post('/conversations/{conversation_id}/mark-read', response_model=MarkReadResponse)
def mark_read(conversation_id: int, current_user: sqlite3.Row = Depends(get_current_user)) -> MarkReadResponse:
    cleanup_expired_messages()
    with db_cursor(commit=True) as cur:
        cur.execute('SELECT * FROM conversations WHERE id = ?', (conversation_id,))
        conversation = cur.fetchone()
        if not conversation:
            raise HTTPException(status_code=404, detail='conversation not found')
        if current_user['id'] not in (conversation['user_low_id'], conversation['user_high_id']):
            raise HTTPException(status_code=403, detail='not a member of this conversation')
        cur.execute(
            """
            SELECT id FROM messages
            WHERE conversation_id = ? AND receiver_id = ? AND is_read = 0
            """,
            (conversation_id, current_user['id']),
        )
        ids = [row['id'] for row in cur.fetchall()]
        if ids:
            cur.execute(
                f"UPDATE messages SET is_read = 1, read_at = ? WHERE id IN ({','.join(['?'] * len(ids))})",
                (utcnow(), *ids),
            )
        return MarkReadResponse(marked_count=len(ids))


@app.get('/conversations')
def conversations(current_user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
    cleanup_expired_messages()
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.last_message_at, c.last_message_id,
                   CASE WHEN c.user_low_id = ? THEN c.user_high_id ELSE c.user_low_id END AS peer_id
            FROM conversations c
            WHERE c.user_low_id = ? OR c.user_high_id = ?
            ORDER BY COALESCE(c.last_message_at, c.created_at) DESC
            """,
            (current_user['id'], current_user['id'], current_user['id']),
        )
        items = []
        for row in cur.fetchall():
            peer = fetch_user_by_id(cur, row['peer_id'])
            last_message_preview = ''
            if row['last_message_id']:
                cur.execute('SELECT content, message_type FROM messages WHERE id = ?', (row['last_message_id'],))
                msg = cur.fetchone()
                if msg:
                    last_message_preview = '[encrypted]' if msg['message_type'] == 'e2ee_text' else msg['content'][:60]
            cur.execute(
                'SELECT COUNT(*) AS unread_count FROM messages WHERE conversation_id = ? AND receiver_id = ? AND is_read = 0',
                (row['id'], current_user['id']),
            )
            unread = cur.fetchone()['unread_count']
            items.append(
                {
                    'conversation_id': row['id'],
                    'peer_username': peer['username'] if peer else 'unknown',
                    'last_message_time': row['last_message_at'],
                    'last_message_preview': last_message_preview,
                    'unread_count': unread,
                }
            )
        return {'conversations': items}


# ------------------------------
# WebSocket route
# ------------------------------
@app.websocket('/ws')
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)) -> None:
    # Authenticate the same bearer token over the WebSocket query string.
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT users.*
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ?
              AND sessions.revoked_at IS NULL
              AND sessions.expires_at > ?
              AND users.is_active = 1
            """,
            (token, utcnow()),
        )
        user = cur.fetchone()
    if not user:
        await websocket.close(code=4401)
        return

    await manager.connect(user['id'], websocket)
    try:
        # Flush offline messages as soon as the user comes online.
        cleanup_expired_messages()
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                SELECT m.id
                FROM messages m
                WHERE m.receiver_id = ? AND m.delivered_at IS NULL
                ORDER BY m.created_at ASC
                """,
                (user['id'],),
            )
            pending_ids = [row['id'] for row in cur.fetchall()]
        for message_id in pending_ids:
            with db_cursor() as cur:
                payload = build_message_payload(cur, message_id)
            await websocket.send_json({'event': 'new_message', 'data': payload})

        await websocket.send_json({'event': 'system', 'data': {'message': f'connected as {user["username"]}'}})
        while True:
            # Keep the socket alive and allow future client-originated control frames if needed.
            message = await websocket.receive_text()
            if message.strip().lower() == 'ping':
                await websocket.send_json({'event': 'pong', 'data': {'ts': utcnow()}})
    except WebSocketDisconnect:
        await manager.disconnect(user['id'], websocket)
    except Exception:
        await manager.disconnect(user['id'], websocket)
        try:
            await websocket.close()
        except Exception:
            pass
