from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from bot.texts import fa as T


def main_menu(telegram_id: int | None = None, *, is_admin: bool | None = None) -> ReplyKeyboardMarkup:
    """Main reply keyboard. Admins get an extra «پنل ادمین» row."""
    show_admin = is_admin
    if show_admin is None and telegram_id is not None:
        try:
            from bot.db import get_session
            from bot.services import admins as admin_svc

            with get_session() as session:
                show_admin = admin_svc.is_admin(session, int(telegram_id))
        except Exception:
            show_admin = False
    show_admin = bool(show_admin)

    rows = [
        [KeyboardButton(T.BTN_ADVANCED)],
        [KeyboardButton(T.BTN_ANON), KeyboardButton(T.BTN_NEARBY)],
        [KeyboardButton(T.BTN_HUB_PROFILE)],
        [KeyboardButton(T.BTN_HUB_FRIENDS)],
    ]
    if show_admin:
        rows.append([KeyboardButton(T.BTN_ADMIN)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def hub_play_menu() -> ReplyKeyboardMarkup:
    """Modes under «شروع بازی»."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(T.BTN_PLAY_NORMAL), KeyboardButton(T.BTN_NEARBY)],
            [KeyboardButton(T.BTN_ANON), KeyboardButton(T.BTN_FAKE)],
            [KeyboardButton(T.BTN_PLAY_FRIEND_LINK), KeyboardButton(T.BTN_GROUP_CHANNEL)],
            [KeyboardButton(T.BTN_BACK)],
        ],
        resize_keyboard=True,
    )


def in_game_menu(
    is_chooser: bool = False, *, awaiting_answer: bool = False
) -> ReplyKeyboardMarkup:
    """In-game reply keyboard: profile / end / private chat (+ skip)."""
    rows = [
        [KeyboardButton(T.BTN_GAME_PROFILE), KeyboardButton(T.BTN_GAME_END)],
        [KeyboardButton(T.BTN_PRIVATE_CHAT)],
    ]
    if awaiting_answer:
        rows.append([KeyboardButton(T.BTN_SKIP)])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def private_chat_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(T.BTN_PRIVATE_CHAT_EXIT)],
            [KeyboardButton(T.BTN_GAME_PROFILE), KeyboardButton(T.BTN_GAME_END)],
        ],
        resize_keyboard=True,
    )


def post_game_actions_keyboard(game_id: int, target_user_id: int) -> InlineKeyboardMarkup:
    """Glass actions after a match ends: like / contact / report."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    T.BTN_LIKE_USER, callback_data=f"pgact:like:{game_id}:{target_user_id}"
                ),
                InlineKeyboardButton(
                    T.BTN_ADD_CONTACT,
                    callback_data=f"pgact:contact:{game_id}:{target_user_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    T.BTN_REPORT_USER,
                    callback_data=f"pgact:report:{game_id}:{target_user_id}",
                )
            ],
        ]
    )


def contacts_list_keyboard(rows: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """rows: (contact_user_id, label)."""
    buttons = []
    for cid, label in rows:
        buttons.append(
            [
                InlineKeyboardButton(label[:40], callback_data=f"contact:view:{cid}"),
                InlineKeyboardButton("🗑", callback_data=f"contact:del:{cid}"),
            ]
        )
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="contact:back")])
    return InlineKeyboardMarkup(buttons)

def report_reason_keyboard(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    T.REPORT_REASON_ABUSE, callback_data=f"ureport:abuse:{game_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    T.REPORT_REASON_SEXUAL, callback_data=f"ureport:sexual:{game_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    T.REPORT_REASON_SPAM, callback_data=f"ureport:spam:{game_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    T.REPORT_REASON_OTHER, callback_data=f"ureport:other:{game_id}"
                )
            ],
        ]
    )


def back_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(T.BTN_BACK)]], resize_keyboard=True)


def hub_profile_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(T.BTN_SHOW_PROFILE), KeyboardButton(T.BTN_PROFILE)],
            [KeyboardButton(T.BTN_GAME_SETTINGS), KeyboardButton(T.BTN_HISTORY)],
            [KeyboardButton(T.BTN_RUN_WIZARD), KeyboardButton(T.BTN_HELP)],
            [KeyboardButton(T.BTN_BACK)],
        ],
        resize_keyboard=True,
    )


def hub_friends_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(T.BTN_FRIENDS), KeyboardButton(T.BTN_GROUP_CHANNEL)],
            [KeyboardButton(T.BTN_BACK)],
        ],
        resize_keyboard=True,
    )


def hub_friends_inline() -> InlineKeyboardMarkup:
    """Friends hub: open chat picker with @bot game (group / private)."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    T.BTN_FRIENDS_START_INLINE,
                    switch_inline_query="game",
                )
            ],
            [
                InlineKeyboardButton(T.BTN_FRIENDS, callback_data="hubf:link"),
            ],
            [InlineKeyboardButton(T.BTN_BACK, callback_data="hubf:back")],
        ]
    )


def profile_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(T.BTN_SHOW_PROFILE)],
            [KeyboardButton(T.BTN_RUN_WIZARD)],
            [KeyboardButton(T.BTN_EDIT_NAME), KeyboardButton(T.BTN_EDIT_PHOTO)],
            [KeyboardButton(T.BTN_EDIT_PROVINCE), KeyboardButton(T.BTN_EDIT_CITY)],
            [KeyboardButton(T.BTN_EDIT_AGE), KeyboardButton(T.BTN_EDIT_GENDER)],
            [KeyboardButton(T.BTN_GAME_SETTINGS)],
            [KeyboardButton(T.BTN_BACK)],
        ],
        resize_keyboard=True,
    )


def skip_photo_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(T.BTN_SKIP_PHOTO)]],
        resize_keyboard=True,
    )


def wizard_cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(T.BTN_CANCEL)]],
        resize_keyboard=True,
    )


def provinces_pick_one(prefix: str = "pprov") -> InlineKeyboardMarkup:
    """Single-select province keyboard for profile."""
    from bot.provinces import PROVINCES, PROVINCE_SHORT

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i, name in enumerate(PROVINCES):
        label = PROVINCE_SHORT.get(name, name)[:64]
        row.append(InlineKeyboardButton(label, callback_data=f"{prefix}:{i}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def gender_inline(prefix: str = "gender") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(T.GENDER_MALE, callback_data=f"{prefix}:male"),
                InlineKeyboardButton(T.GENDER_FEMALE, callback_data=f"{prefix}:female"),
            ]
        ]
    )


def partner_gender_inline(prefix: str = "adv_partner") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(T.BTN_ONLY_MALE, callback_data=f"{prefix}:male"),
                InlineKeyboardButton(T.BTN_ONLY_FEMALE, callback_data=f"{prefix}:female"),
            ]
        ]
    )


def provinces_keyboard(selected: set[str] | None = None) -> InlineKeyboardMarkup:
    from bot.provinces import PROVINCES, PROVINCE_SHORT

    selected = selected or set()
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i, name in enumerate(PROVINCES):
        mark = "✅ " if name in selected else ""
        label = PROVINCE_SHORT.get(name, name)
        # keep button text short for Telegram
        text = f"{mark}{label}"[:64]
        row.append(InlineKeyboardButton(text, callback_data=f"adv_prov:{i}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(T.BTN_ALL_PROVINCES, callback_data="adv_prov_all"),
            InlineKeyboardButton(T.BTN_CLEAR_PROVINCES, callback_data="adv_prov_clear"),
        ]
    )
    rows.append(
        [InlineKeyboardButton(T.BTN_CONFIRM_PROVINCES, callback_data="adv_prov_ok")]
    )
    return InlineKeyboardMarkup(rows)


def age_min_keyboard() -> InlineKeyboardMarkup:
    opts = [
        (T.BTN_AGE_UNDER_15, "min:0"),
        ("۱۵ سال", "min:15"),
        ("۲۰ سال", "min:20"),
        ("۲۵ سال", "min:25"),
        ("۳۰ سال", "min:30"),
        ("۳۵ سال", "min:35"),
        ("۴۰ سال", "min:40"),
        ("۴۵ سال", "min:45"),
        ("۵۰ سال", "min:50"),
        (T.BTN_AGE_OVER_50, "min:51"),
        (T.BTN_AGE_ANY, "min:any"),
    ]
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for label, data in opts:
        row.append(InlineKeyboardButton(label, callback_data=f"adv_age:{data}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def age_max_keyboard(age_from: int | None) -> InlineKeyboardMarkup:
    floors = age_from or 0
    candidates = [15, 20, 25, 30, 35, 40, 45, 50, 60, 100]
    opts = [(f"{a} سال", f"max:{a}") for a in candidates if a >= floors]
    opts.append((T.BTN_AGE_ANY, "max:any"))
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for label, data in opts:
        row.append(InlineKeyboardButton(label, callback_data=f"adv_age:{data}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def last_seen_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(T.BTN_SEEN_1H, callback_data="adv_seen:1"),
                InlineKeyboardButton(T.BTN_SEEN_6H, callback_data="adv_seen:6"),
            ],
            [
                InlineKeyboardButton(T.BTN_SEEN_1D, callback_data="adv_seen:24"),
                InlineKeyboardButton(T.BTN_SEEN_2D, callback_data="adv_seen:48"),
            ],
            [
                InlineKeyboardButton(T.BTN_SEEN_3D, callback_data="adv_seen:72"),
                InlineKeyboardButton(T.BTN_SEEN_1W, callback_data="adv_seen:168"),
            ],
        ]
    )


def sort_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(T.BTN_SORT_ONLINE, callback_data="adv_sort:online"),
                InlineKeyboardButton(T.BTN_SORT_NEAR, callback_data="adv_sort:near"),
            ],
            [
                InlineKeyboardButton(T.BTN_SORT_AGE_DESC, callback_data="adv_sort:age_desc"),
                InlineKeyboardButton(T.BTN_SORT_AGE_ASC, callback_data="adv_sort:age_asc"),
            ],
        ]
    )


def search_results_keyboard(user_ids: list[int], page: int = 0, page_size: int = 5) -> InlineKeyboardMarkup:
    start = page * page_size
    chunk = user_ids[start : start + page_size]
    rows = [
        [InlineKeyboardButton(f"{T.BTN_PLAY_WITH} #{uid}", callback_data=f"adv_play:{uid}")]
        for uid in chunk
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(T.BTN_PREV_PAGE, callback_data=f"adv_page:{page-1}"))
    if start + page_size < len(user_ids):
        nav.append(InlineKeyboardButton(T.BTN_NEXT_PAGE, callback_data=f"adv_page:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(T.BTN_NEW_SEARCH, callback_data="adv_research"),
            InlineKeyboardButton(T.BTN_WAIT_QUEUE, callback_data="adv_queue"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def gender_any_inline(prefix: str = "pref_gender") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(T.GENDER_MALE, callback_data=f"{prefix}:male"),
                InlineKeyboardButton(T.GENDER_FEMALE, callback_data=f"{prefix}:female"),
            ],
            [InlineKeyboardButton(T.GENDER_ANY, callback_data=f"{prefix}:any")],
        ]
    )


def invite_display_mode() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(T.DISPLAY_REAL, callback_data="inv_disp:real")],
            [InlineKeyboardButton(T.DISPLAY_ANON, callback_data="inv_disp:anonymous")],
            [InlineKeyboardButton(T.DISPLAY_NICK, callback_data="inv_disp:nickname")],
        ]
    )


def truth_dare(session_id: int, chooser_id: int) -> InlineKeyboardMarkup:
    """Glass buttons: truth / dare only. Profile/end stay on reply keyboard."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    T.BTN_TRUTH, callback_data=f"td:{session_id}:{chooser_id}:truth"
                ),
                InlineKeyboardButton(
                    T.BTN_DARE, callback_data=f"td:{session_id}:{chooser_id}:dare"
                ),
            ],
        ]
    )


def skip_answer(session_id: int) -> InlineKeyboardMarkup:
    """Glass skip for group chats."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(T.BTN_SKIP, callback_data=f"skip:{session_id}")]]
    )


def group_channel_help() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    T.BTN_FRIENDS_START_INLINE,
                    switch_inline_query="game",
                )
            ],
            [
                InlineKeyboardButton(
                    T.BTN_INLINE_HERE,
                    switch_inline_query_current_chat="game",
                )
            ],
            [InlineKeyboardButton(T.BTN_GROUP_HELP, callback_data="gc:group")],
            [InlineKeyboardButton(T.BTN_CHANNEL_HELP, callback_data="gc:channel")],
        ]
    )


def join_group_game(
    session_id: int,
    *,
    sponsor_buttons: list[tuple[str, str]] | None = None,
) -> InlineKeyboardMarkup:
    """Lobby: optional sponsor URL rows + join/start + anon deep-link."""
    from bot.config import BOT_USERNAME

    rows: list[list[InlineKeyboardButton]] = []
    for label, url in sponsor_buttons or []:
        if url:
            rows.append([InlineKeyboardButton(f"{label} ↗️", url=url)])
    rows.append(
        [
            InlineKeyboardButton(T.JOIN_GAME, callback_data=f"gjoin:{session_id}"),
            InlineKeyboardButton(T.START_GROUP_GAME, callback_data=f"gstart:{session_id}"),
        ]
    )
    if BOT_USERNAME:
        rows.append(
            [
                InlineKeyboardButton(
                    T.BTN_GROUP_ANON,
                    url=f"https://t.me/{BOT_USERNAME}?start=anon",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def group_question_keyboard(session_id: int, cat: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    T.BTN_GROUP_RESHUFFLE,
                    callback_data=f"greshuf:{session_id}:{cat}",
                )
            ],
            [
                InlineKeyboardButton(T.BTN_GROUP_NEXT, callback_data=f"gnext:{session_id}"),
            ],
            [
                InlineKeyboardButton(
                    T.BTN_GROUP_ANSWERED,
                    callback_data=f"gdone:{session_id}",
                )
            ],
            [InlineKeyboardButton(T.BTN_GROUP_END, callback_data=f"gend:{session_id}")],
            [
                InlineKeyboardButton(
                    T.BTN_GROUP_BUMP,
                    switch_inline_query_current_chat=f"go {session_id}",
                )
            ],
        ]
    )


def group_category_keyboard(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(T.CAT_TF18, callback_data=f"gcat:{session_id}:tf18"),
                InlineKeyboardButton(T.CAT_TM18, callback_data=f"gcat:{session_id}:tm18"),
            ],
            [
                InlineKeyboardButton(T.CAT_DF18, callback_data=f"gcat:{session_id}:df18"),
                InlineKeyboardButton(T.CAT_DM18, callback_data=f"gcat:{session_id}:dm18"),
            ],
            [
                InlineKeyboardButton(T.CAT_TN, callback_data=f"gcat:{session_id}:tn"),
                InlineKeyboardButton(T.CAT_LUCKY, callback_data=f"gcat:{session_id}:lucky"),
                InlineKeyboardButton(T.CAT_DN, callback_data=f"gcat:{session_id}:dn"),
            ],
            [
                InlineKeyboardButton(T.BTN_GROUP_NEXT, callback_data=f"gnext:{session_id}"),
                InlineKeyboardButton(T.JOIN_GAME_MID, callback_data=f"grejoin:{session_id}"),
            ],
            [InlineKeyboardButton(T.BTN_GROUP_END, callback_data=f"gend:{session_id}")],
            [
                InlineKeyboardButton(
                    T.BTN_GROUP_BUMP,
                    switch_inline_query_current_chat=f"go {session_id}",
                )
            ],
        ]
    )


def city_pref() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(T.SAME_CITY, callback_data="str_city:same"),
                InlineKeyboardButton(T.ANYWHERE, callback_data="str_city:any"),
            ]
        ]
    )


def request_location_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(T.BTN_SHARE_LOCATION, request_location=True)],
            [KeyboardButton(T.BTN_CANCEL)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def radius_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("۱ کیلومتر", callback_data="near_r:1"),
                InlineKeyboardButton("۱۰ کیلومتر", callback_data="near_r:10"),
            ],
            [
                InlineKeyboardButton("۲۵ کیلومتر", callback_data="near_r:25"),
                InlineKeyboardButton("۵۰ کیلومتر", callback_data="near_r:50"),
            ],
            [InlineKeyboardButton("۱۰۰ کیلومتر", callback_data="near_r:100")],
        ]
    )


def identity_pref() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(T.IDENTITY_VISIBLE, callback_data="str_id:visible"),
                InlineKeyboardButton(T.IDENTITY_HIDDEN, callback_data="str_id:hidden"),
            ]
        ]
    )


def allow_anon_pref() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(T.STRANGER_ALLOW_ANON_YES, callback_data="str_allow:yes")],
            [InlineKeyboardButton(T.STRANGER_ALLOW_ANON_NO, callback_data="str_allow:no")],
        ]
    )


def age_options(prefix: str, ages: list[int]) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for i, age in enumerate(ages):
        row.append(InlineKeyboardButton(str(age), callback_data=f"{prefix}:{age}"))
        if len(row) == 3 or i == len(ages) - 1:
            rows.append(row)
            row = []
    return InlineKeyboardMarkup(rows)


def fake_gender_pick() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(T.FAKE_GENDER_MALE, callback_data="fake_gender:male"),
                InlineKeyboardButton(T.FAKE_GENDER_FEMALE, callback_data="fake_gender:female"),
            ],
            [InlineKeyboardButton(T.FAKE_GENDER_ANY, callback_data="fake_gender:any")],
        ]
    )


def fake_continue(session_token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(T.CONTINUE_FAKE, callback_data=f"fake_go:{session_token}:fake")],
            [InlineKeyboardButton(T.CONTINUE_REAL, callback_data=f"fake_go:{session_token}:real")],
            [InlineKeyboardButton(T.FAKE_REROLL, callback_data=f"fake_reroll:{session_token}")],
        ]
    )


def final_guess(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(T.GUESS_FAKE, callback_data=f"fguess:{session_id}:fake"),
                InlineKeyboardButton(T.GUESS_REAL, callback_data=f"fguess:{session_id}:real"),
            ]
        ]
    )


def channel_answer_mode() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(T.CHANNEL_MODE_BUTTONS, callback_data="ch_mode:buttons")],
            [InlineKeyboardButton(T.CHANNEL_MODE_COMMENTS, callback_data="ch_mode:comments")],
        ]
    )


def channel_owner_truth_dare() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(T.BTN_TRUTH, callback_data="ch_ask:truth"),
                InlineKeyboardButton(T.BTN_DARE, callback_data="ch_ask:dare"),
            ]
        ]
    )


def channel_option_votes(
    session_id: int, round_id: int, options: list[str]
) -> InlineKeyboardMarkup:
    rows = []
    for i, opt in enumerate(options):
        rows.append(
            [
                InlineKeyboardButton(
                    opt[:60], callback_data=f"ch_opt:{session_id}:{round_id}:{i}"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                T.CHANNEL_CLOSE_VOTING,
                callback_data=f"ch_close:{session_id}:{round_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def channel_close_only(session_id: int, round_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    T.CHANNEL_CLOSE_VOTING,
                    callback_data=f"ch_close:{session_id}:{round_id}",
                )
            ]
        ]
    )


def channel_after_round(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(T.CHANNEL_NEXT, callback_data=f"ch_next:{session_id}")],
            [InlineKeyboardButton(T.CHANNEL_END, callback_data=f"ch_end:{session_id}")],
        ]
    )


def cancel_match() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(T.BTN_LEAVE_QUEUE, callback_data="str_cancel")]]
    )


def sponsor_join_keyboard(channels) -> InlineKeyboardMarkup:
    """Join buttons use callbacks so clicks can be counted in admin reports."""
    rows = []
    for ch in channels:
        title = (getattr(ch, "title", None) or "کانال اسپانسری").strip()[:40]
        if ch.invite_link:
            rows.append(
                [
                    InlineKeyboardButton(
                        T.SPONSOR_BTN_JOIN.format(title=title),
                        callback_data=f"mem_join:{ch.id}",
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        f"📢 «{title}» — لینک نداره",
                        callback_data="mem_noop",
                    )
                ]
            )
    rows.append(
        [InlineKeyboardButton(T.SPONSOR_BTN_CHECK, callback_data="mem_check")]
    )
    return InlineKeyboardMarkup(rows)


def admin_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(T.ADMIN_BTN_REPORTS, callback_data="admin:reports")],
            [InlineKeyboardButton(T.ADMIN_BTN_USER_SEARCH, callback_data="admin:usearch")],
            [InlineKeyboardButton(T.ADMIN_BTN_MODERATION, callback_data="admin:mod")],
            [InlineKeyboardButton(T.ADMIN_BTN_BROADCAST, callback_data="admin:broadcast")],
            [InlineKeyboardButton(T.ADMIN_BTN_QUESTIONS, callback_data="admin:qbank")],
            [InlineKeyboardButton(T.ADMIN_BTN_CHANNELS, callback_data="admin:channels")],
            [InlineKeyboardButton(T.ADMIN_BTN_ADMINS, callback_data="admin:admins")],
            [InlineKeyboardButton(T.ADMIN_BTN_REFRESH, callback_data="admin:home")],
        ]
    )


def admin_question_bank_keyboard(counts: dict[str, int] | None = None) -> InlineKeyboardMarkup:
    counts = counts or {}
    from bot.services.questions import BUCKET_LABELS, BUCKETS

    rows = []
    for key in BUCKETS:
        n = int(counts.get(key, 0) or 0)
        rows.append(
            [
                InlineKeyboardButton(
                    f"{BUCKET_LABELS[key]} ({n})",
                    callback_data=f"admin:qbank:b:{key}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


def admin_question_bucket_keyboard(bucket: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ افزودن سوالات", callback_data=f"admin:qbank:add:{bucket}")],
            [InlineKeyboardButton("👁 نمونه سوالات", callback_data=f"admin:qbank:list:{bucket}")],
            [InlineKeyboardButton("🗑 پاک کردن این دسته", callback_data=f"admin:qbank:clear:{bucket}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin:qbank")],
        ]
    )


def admin_user_search_results_keyboard(user_ids: list[int]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"👤 #{uid}", callback_data=f"admin:usearch:u:{uid}")]
        for uid in user_ids[:20]
    ]
    rows.append([InlineKeyboardButton("🔎 جستجوی جدید", callback_data="admin:usearch")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


def admin_user_detail_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(T.ADMIN_BTN_BAN_1H, callback_data=f"admin:usearch:ban:{user_id}:1h"),
                InlineKeyboardButton(T.ADMIN_BTN_BAN_24H, callback_data=f"admin:usearch:ban:{user_id}:24h"),
            ],
            [
                InlineKeyboardButton(T.ADMIN_BTN_BAN_7D, callback_data=f"admin:usearch:ban:{user_id}:7d"),
                InlineKeyboardButton(T.ADMIN_BTN_BAN_PERM, callback_data=f"admin:usearch:ban:{user_id}:perm"),
            ],
            [InlineKeyboardButton("🔎 جستجوی جدید", callback_data="admin:usearch")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")],
        ]
    )


def admin_mod_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(T.ADMIN_BTN_MOD_OPEN, callback_data="admin:mod:open")],
            [InlineKeyboardButton(T.ADMIN_BTN_MOD_BANS, callback_data="admin:mod:bans")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")],
        ]
    )


def admin_mod_reports_keyboard(reports) -> InlineKeyboardMarkup:
    rows = []
    for r in reports:
        label = f"#{r.id} · {r.reason_code}"
        rows.append([InlineKeyboardButton(label, callback_data=f"admin:mod:r:{r.id}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin:mod")])
    return InlineKeyboardMarkup(rows)


def admin_mod_bans_keyboard(rows_data: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """rows_data: (restriction_id, button_label)."""
    rows = []
    for rid, label in rows_data:
        rows.append(
            [
                InlineKeyboardButton(label[:60], callback_data=f"admin:mod:b:{rid}"),
                InlineKeyboardButton(T.ADMIN_BTN_MOD_LIFT, callback_data=f"admin:mod:lift:{rid}"),
            ]
        )
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin:mod")])
    return InlineKeyboardMarkup(rows)


def admin_mod_report_actions_keyboard(report_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(T.ADMIN_BTN_BAN_1H, callback_data=f"admin:mod:ban:{report_id}:1h"),
                InlineKeyboardButton(T.ADMIN_BTN_BAN_6H, callback_data=f"admin:mod:ban:{report_id}:6h"),
            ],
            [
                InlineKeyboardButton(T.ADMIN_BTN_BAN_24H, callback_data=f"admin:mod:ban:{report_id}:24h"),
                InlineKeyboardButton(T.ADMIN_BTN_BAN_7D, callback_data=f"admin:mod:ban:{report_id}:7d"),
            ],
            [
                InlineKeyboardButton(T.ADMIN_BTN_BAN_30D, callback_data=f"admin:mod:ban:{report_id}:30d"),
                InlineKeyboardButton(T.ADMIN_BTN_BAN_PERM, callback_data=f"admin:mod:ban:{report_id}:perm"),
            ],
            [InlineKeyboardButton(T.ADMIN_BTN_MOD_DISMISS, callback_data=f"admin:mod:dismiss:{report_id}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin:mod:open")],
        ]
    )


def admin_broadcast_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(T.ADMIN_BTN_BC_ALL, callback_data="admin:bc:all")],
            [InlineKeyboardButton(T.ADMIN_BTN_BC_ONE, callback_data="admin:bc:one")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")],
        ]
    )


def admin_broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(T.ADMIN_BTN_BC_GO, callback_data="admin:bc:go")],
            [InlineKeyboardButton(T.ADMIN_BTN_BC_ABORT, callback_data="admin:broadcast")],
        ]
    )


def admin_reports_keyboard(period: str = "day") -> InlineKeyboardMarkup:
    def mark(key: str, label: str) -> str:
        return f"• {label}" if key == period else label

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(mark("day", "امروز"), callback_data="admin:rep:overview:day"),
                InlineKeyboardButton(mark("week", "هفته"), callback_data="admin:rep:overview:week"),
                InlineKeyboardButton(mark("month", "ماه"), callback_data="admin:rep:overview:month"),
            ],
            [InlineKeyboardButton(T.ADMIN_BTN_REP_USERS, callback_data="admin:rep:users")],
            [InlineKeyboardButton(T.ADMIN_BTN_REP_PROVINCES, callback_data="admin:rep:provinces")],
            [
                InlineKeyboardButton(
                    T.ADMIN_BTN_REP_SPONSORS, callback_data=f"admin:rep:sponsors:{period}"
                )
            ],
            [
                InlineKeyboardButton(
                    T.ADMIN_BTN_REP_GAMES, callback_data=f"admin:rep:games:{period}"
                )
            ],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")],
        ]
    )


def admin_channels_keyboard(channels) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(T.ADMIN_BTN_ADD_CHANNEL, callback_data="admin:ch_add")]]
    for ch in channels:
        flag = "✅" if ch.active else "⏸"
        prov = (ch.province or "?")[:12]
        rows.append(
            [
                InlineKeyboardButton(
                    f"{flag} #{ch.id} {prov}",
                    callback_data=f"admin:ch_toggle:{ch.id}",
                ),
                InlineKeyboardButton(
                    T.ADMIN_BTN_DEL_CHANNEL.format(id=ch.id),
                    callback_data=f"admin:ch_del:{ch.id}",
                ),
            ]
        )
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


def admin_admins_keyboard(admin_rows: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """admin_rows: list of (telegram_id, tag) where tag is env/db."""
    rows = [[InlineKeyboardButton(T.ADMIN_BTN_ADD_ADMIN, callback_data="admin:ad_add")]]
    for tid, tag in admin_rows:
        if tag == "env":
            rows.append(
                [
                    InlineKeyboardButton(
                        f"🔒 {tid} {T.ADMIN_ENV_TAG}",
                        callback_data="admin:noop",
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        T.ADMIN_BTN_DEL_ADMIN.format(tid=tid),
                        callback_data=f"admin:ad_del:{tid}",
                    )
                ]
            )
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


def play_invite_keyboard(invite_id: int, *, for_target: bool) -> InlineKeyboardMarkup:
    if for_target:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        T.INVITE_ACCEPT, callback_data=f"invite:accept:{invite_id}"
                    ),
                    InlineKeyboardButton(
                        T.INVITE_REJECT, callback_data=f"invite:reject:{invite_id}"
                    ),
                ]
            ]
        )
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    T.INVITE_CANCEL, callback_data=f"invite:cancel:{invite_id}"
                )
            ]
        ]
    )


def queue_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(T.BTN_LEAVE_QUEUE)]],
        resize_keyboard=True,
    )


def settings_keyboard(user) -> InlineKeyboardMarkup:
    def flag(v: bool) -> str:
        return T.ON if v else T.OFF

    nick = user.nickname or T.SETTINGS_NICK_EMPTY
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"درخواست غریبه: {flag(user.allow_stranger_requests)}",
                    callback_data="set:allow_stranger_requests",
                )
            ],
            [
                InlineKeyboardButton(
                    f"درخواست بدون هویت: {flag(user.allow_anonymous_requests)}",
                    callback_data="set:allow_anonymous_requests",
                )
            ],
            [
                InlineKeyboardButton(
                    f"نمایش هویت به طرف: {flag(user.show_identity)}",
                    callback_data="set:show_identity",
                )
            ],
            [
                InlineKeyboardButton(
                    f"نمایش سن: {flag(user.show_age)}",
                    callback_data="set:show_age",
                )
            ],
            [
                InlineKeyboardButton(
                    f"نمایش عکس پروفایل: {flag(user.show_photo)}",
                    callback_data="set:show_photo",
                )
            ],
            [
                InlineKeyboardButton(
                    f"نمایش آیدی خصوصی: {flag(user.show_private_id)}",
                    callback_data="set:show_private_id",
                )
            ],
            [
                InlineKeyboardButton(
                    T.SETTINGS_NICK_BTN.format(nick=nick[:24]),
                    callback_data="pedit:nickname",
                )
            ],
        ]
    )
