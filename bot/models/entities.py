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
    likes_count: Mapped[int] = mapped_column(Integer, default=0)

    # Account privacy (settings hub)
    account_private: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_profile_visit: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_follow: Mapped[bool] = mapped_column(Boolean, default=False)

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
    # Telegram inline message id when game was started via @bot inline mode
    inline_message_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    discussion_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    starter_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    current_turn_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    current_target_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    round_number: Mapped[int] = mapped_column(Integer, default=0)
    max_rounds: Mapped[int] = mapped_column(Integer, default=0)
    # channel answer mode: buttons | comments
    channel_answer_mode: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    channel_options_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # discussion-group message id that audience should reply to (comments mode)
    channel_prompt_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
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
    # real | fake | anonymous | nickname
    identity_mode: Mapped[str] = mapped_column(String(16), default="real")
    fake_identity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("fake_identities.id"), nullable=True
    )
    # custom display for invite nickname / override label
    display_label: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
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
    prompt_source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # group category key e.g. tf18 | lucky (for reshuffle / resume)
    category_key: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    prompt_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # photo | voice | video | video_note
    prompt_media_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    prompt_file_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    answer_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answer_media_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    answer_file_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
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
    # option index "0"/"1"/… or free-text comment
    value: Mapped[str] = mapped_column(Text)
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
    # hash of core fields for per-user dedupe
    fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    generated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserFakeAssignment(Base):
    """Tracks which generated fakes a user has seen until reveal."""

    __tablename__ = "user_fake_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "fingerprint", name="uq_user_fake_fp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    fake_identity_id: Mapped[int] = mapped_column(ForeignKey("fake_identities.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    revealed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship()
    fake_identity: Mapped["FakeIdentity"] = relationship()


class BotAdmin(Base):
    """Extra bot admins (beyond ADMIN_IDS in .env)."""

    __tablename__ = "bot_admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    added_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SponsoredChannel(Base):
    """Channels/groups users must join for a specific province (bot should be admin)."""

    __tablename__ = "sponsored_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    # Province name from PROVINCES list — required for gating
    province: Mapped[str] = mapped_column(String(64), default="", index=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    invite_link: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AnalyticsEvent(Base):
    """Lightweight event log for admin reports (sponsor clicks, checks, …)."""

    __tablename__ = "analytics_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    channel_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    province: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class UserReport(Base):
    """Player-submitted report against another user."""

    __tablename__ = "user_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reported_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("game_sessions.id"), nullable=True, index=True
    )
    # abuse | sexual | spam | other
    reason_code: Mapped[str] = mapped_column(String(32), default="other")
    reason_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # open | reviewed | actioned | dismissed
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    admin_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    reporter: Mapped["User"] = relationship(foreign_keys=[reporter_id])
    reported: Mapped["User"] = relationship(foreign_keys=[reported_id])


class UserRestriction(Base):
    """Timed or permanent play restriction applied by admins."""

    __tablename__ = "user_restrictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # temp | permanent
    kind: Mapped[str] = mapped_column(String(16), default="temp")
    until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    lifted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    report_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_reports.id"), nullable=True, index=True
    )

    user: Mapped["User"] = relationship()


class UserLike(Base):
    """A like from one user to another (always on the real account)."""

    __tablename__ = "user_likes"
    __table_args__ = (UniqueConstraint("liker_id", "liked_id", name="uq_user_like"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    liker_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    liked_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("game_sessions.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserContact(Base):
    """Saved contact between two users."""

    __tablename__ = "user_contacts"
    __table_args__ = (UniqueConstraint("owner_id", "contact_id", name="uq_user_contact"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("game_sessions.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    contact: Mapped["User"] = relationship(foreign_keys=[contact_id])


class PlayInvite(Base):
    """Pending play request that must be accepted before a game starts."""

    __tablename__ = "play_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # pending | accepted | rejected | expired | cancelled
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    from_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    to_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    from_user: Mapped["User"] = relationship(foreign_keys=[from_user_id])
    to_user: Mapped["User"] = relationship(foreign_keys=[to_user_id])


class UserBlock(Base):
    """One-way block: blocker cannot be matched/messaged by blocked."""

    __tablename__ = "user_blocks"
    __table_args__ = (UniqueConstraint("blocker_id", "blocked_id", name="uq_user_block"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    blocker_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    blocked_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OnlineNotify(Base):
    """Watcher wants a ping when target comes online."""

    __tablename__ = "online_notifies"
    __table_args__ = (UniqueConstraint("watcher_id", "target_id", name="uq_online_notify"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watcher_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # After we notify once, clear or keep? Keep until toggled off; notify each offline→online.
    last_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

class QuestionBankItem(Base):
    """Admin-managed prompts keyed by gender bucket (+18)."""

    __tablename__ = "question_bank"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # female | female_18 | male | male_18
    bucket: Mapped[str] = mapped_column(String(32), index=True)
    # truth | dare | any
    kind: Mapped[str] = mapped_column(String(16), default="any", index=True)
    text: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


class UserSubmittedQuestion(Base):
    """Custom user-written prompts that admins can review/add to the bot bank."""

    __tablename__ = "user_submitted_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("game_sessions.id"), nullable=True, index=True
    )
    round_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("rounds.id"), nullable=True, index=True
    )
    submitter_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    target_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), index=True)  # truth | dare
    suggested_bucket: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    text: Mapped[str] = mapped_column(Text)
    added_to_bank: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    added_bucket: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    added_bank_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("question_bank.id"), nullable=True
    )
    reviewed_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

