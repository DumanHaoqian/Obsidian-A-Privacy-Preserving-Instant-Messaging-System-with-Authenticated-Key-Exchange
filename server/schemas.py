from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)

    @field_validator('username')
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip()
        if not value.replace('_', '').replace('-', '').isalnum():
            raise ValueError('username may only contain letters, digits, underscore, hyphen')
        return value.lower()


class RegisterResponse(BaseModel):
    user_id: int
    username: str
    otp_secret: str
    otp_uri: str
    message: str


class LoginPasswordRequest(BaseModel):
    username: str
    password: str


class LoginPasswordResponse(BaseModel):
    challenge_token: str
    otp_required: bool = True


class LoginOtpRequest(BaseModel):
    challenge_token: str
    otp_code: str = Field(min_length=6, max_length=8)


class LoginOtpResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    expires_at: str


class MessageAckRequest(BaseModel):
    message_id: int
    status: Literal['delivered'] = 'delivered'


class FriendRequestSendRequest(BaseModel):
    target_username: str


class FriendRequestSendResponse(BaseModel):
    ok: bool = True
    message: str
    request_id: int
    target_username: str
    target_user_id: int


class FriendRequestRespondRequest(BaseModel):
    request_id: int
    action: Literal['accept', 'decline']


class FriendRequestCancelRequest(BaseModel):
    request_id: int


class MessageSendRequest(BaseModel):
    to_username: str
    content: str = Field(min_length=1, max_length=16000)
    message_type: Literal['text', 'e2ee_text'] = 'text'


class IdentityKeyUpsertRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    public_key: str = Field(min_length=16, max_length=8192)


class BasicResponse(BaseModel):
    ok: bool = True
    message: str


class MarkReadResponse(BaseModel):
    ok: bool = True
    marked_count: int
