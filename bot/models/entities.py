from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    nickname: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    province: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    gender: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # male/female
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    profile_photo_file_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    profile_photo_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    location_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Privacy / game settings
    allow_stranger_requests: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_anonymous_requests: Mapped[bool] = mapped_column(Boolean, default=True)
    show_identity: Mapped[bool] = mapped_column(Boolean, default=True)
    show_age: Mapped[bool] = mapped_column(Boolean, default=True)
    show_photo: Mapped[bool] = mapped_column(Boolean, default=False)
    show_private_id: Mapped[bool] = mapped_column(Boolean, default=False)  # default OFF

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    invite_links: Mapped[list["InviteLink"]] = relationship(back_populates="owner")
    game_players: Mapped[list["GamePlayer"]] = relationship(back_populates="user")


class InviteLink(Base):
    __tablename__ = "invite_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # real | anonymous | nickname
    display_mode: Mapped[str] = mapped_column(String(16), default="real")
    custom_label: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped["User"] = relationship(back_populates="invite_links")


class GameSession(Base):
    __tablename__ = "game_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # friends | group | channel | stranger | fake_identity
    game_type: Mapped[str] = mapped_column(String(32), index=True)
    # waiting | registering | playing | guessing | finished | cancelled
    status: Mapped[str] = mapped_column(String(32), default="waiting", index=True)
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    discussion_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    starter_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    current_turn_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    current_target_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    round_number: Mapped[int] = mapped_column(Integer, default=0)
    max_rounds: Mapped[int] = mapped_column(Integer, default=5)
    # channel answer mode: buttons | comments
    channel_answer_mode: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    channel_options_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    players: Mapped[list["GamePlayer"]] = relationship(back_populates="session")
    rounds: Mapped[list["Round"]] = relationship(back_populates="session")


class GamePlayer(Base):
    __tablename__ = "game_players"
    __table_args__ = (UniqueConstraint("session_id", "user_id", name="uq_session_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("game_sessions.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # real | fake
    identity_mode: Mapped[str] = mapped_column(String(8), default="real")
    fake_identity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("fake_identities.id"), nullable=True
    )
    # guess at end: fake | real | None
    final_guess: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    guess_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["GameSession"] = relationship(back_populates="players")
    user: Mapped["User"] = relationship(back_populates="game_players")
    fake_identity: Mapped[Optional["FakeIdentity"]] = relationship()


class Round(Base):
    __tablename__ = "rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("game_sessions.id"), index=True)
    round_no: Mapped[int] = mapped_column(Integer)
    chooser_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    target_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # truth | dare | pending
    choice: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    prompt_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answer_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # open | answered | skipped
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["GameSession"] = relationship(back_populates="rounds")
    votes: Mapped[list["Vote"]] = relationship(back_populates="round")


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("round_id", "voter_telegram_id", name="uq_round_voter"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id"), index=True)
    voter_telegram_id: Mapped[int] = mapped_column(BigInteger)
    # truth | dare | or option index as string
    value: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    round: Mapped["Round"] = relationship(back_populates="votes")


class MatchQueue(Base):
    __tablename__ = "match_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    # waiting | matched | cancelled | expired
    status: Mapped[str] = mapped_column(String(16), default="waiting", index=True)
    # stranger | anonymous | nearby | advanced | fake
    queue_mode: Mapped[str] = mapped_column(String(16), default="stranger", index=True)
    same_city_only: Mapped[bool] = mapped_column(Boolean, default=False)
    preferred_gender: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # male/female/any
    age_from: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    age_to: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # max distance for nearby matching (km); None = not used
    radius_km: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # JSON list of province names for advanced search; empty = any
    provinces_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    require_identity: Mapped[bool] = mapped_column(Boolean, default=True)
    play_anonymous: Mapped[bool] = mapped_column(Boolean, default=False)
    # for fake-identity mode queue
    use_fake_identity: Mapped[bool] = mapped_column(Boolean, default=False)
    fake_identity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("fake_identities.id"), nullable=True
    )
    identity_mode: Mapped[str] = mapped_column(String(8), default="real")
    matched_game_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("game_sessions.id"), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class FakeIdentity(Base):
    __tablename__ = "fake_identities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    gender: Mapped[str] = mapped_column(String(16), index=True)
    age: Mapped[int] = mapped_column(Integer)
    city: Mapped[str] = mapped_column(String(64))
    job: Mapped[str] = mapped_column(String(64))
    bio: Mapped[str] = mapped_column(Text)
    personality: Mapped[str] = mapped_column(Text)
    dislikes: Mapped[str] = mapped_column(Text)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
