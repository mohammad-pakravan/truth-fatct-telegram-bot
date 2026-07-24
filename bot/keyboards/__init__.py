from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from bot.texts import fa as T


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(T.BTN_ADVANCED)],
            [KeyboardButton(T.BTN_NEARBY), KeyboardButton(T.BTN_ANON)],
            [KeyboardButton(T.BTN_HUB_PROFILE)],
            [KeyboardButton(T.BTN_HUB_FRIENDS)],
            [KeyboardButton(T.BTN_HELP), KeyboardButton(T.BTN_CONTACT)],
        ],
        resize_keyboard=True,
    )


def back_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(T.BTN_BACK)]], resize_keyboard=True)


def hub_profile_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(T.BTN_SHOW_PROFILE), KeyboardButton(T.BTN_PROFILE)],
            [KeyboardButton(T.BTN_RUN_WIZARD)],
            [KeyboardButton(T.BTN_HISTORY), KeyboardButton(T.BTN_GAME_SETTINGS)],
            [KeyboardButton(T.BTN_FAKE)],
            [KeyboardButton(T.BTN_BACK)],
        ],
        resize_keyboard=True,
    )


def hub_friends_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(T.BTN_FRIENDS)],
            [KeyboardButton(T.BTN_GROUP_CHANNEL)],
            [KeyboardButton(T.BTN_BACK)],
        ],
        resize_keyboard=True,
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
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(T.BTN_TRUTH, callback_data=f"td:{session_id}:{chooser_id}:truth"),
                InlineKeyboardButton(T.BTN_DARE, callback_data=f"td:{session_id}:{chooser_id}:dare"),
            ]
        ]
    )


def skip_answer(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(T.BTN_SKIP, callback_data=f"skip:{session_id}")]]
    )


def group_channel_help() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(T.BTN_GROUP_HELP, callback_data="gc:group")],
            [InlineKeyboardButton(T.BTN_CHANNEL_HELP, callback_data="gc:channel")],
        ]
    )


def join_group_game(session_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(T.JOIN_GAME, callback_data=f"gjoin:{session_id}")],
            [InlineKeyboardButton(T.START_GROUP_GAME, callback_data=f"gstart:{session_id}")],
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


def identity_pref() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(T.IDENTITY_VISIBLE, callback_data="str_id:visible"),
                InlineKeyboardButton(T.IDENTITY_HIDDEN, callback_data="str_id:hidden"),
            ]
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


def fake_continue(session_token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(T.CONTINUE_FAKE, callback_data=f"fake_go:{session_token}:fake")],
            [InlineKeyboardButton(T.CONTINUE_REAL, callback_data=f"fake_go:{session_token}:real")],
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


def channel_truth_dare_vote(session_id: int, round_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(T.BTN_TRUTH, callback_data=f"ch_vote:{session_id}:{round_id}:truth"),
                InlineKeyboardButton(T.BTN_DARE, callback_data=f"ch_vote:{session_id}:{round_id}:dare"),
            ]
        ]
    )


def channel_option_votes(session_id: int, round_id: int, options: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for i, opt in enumerate(options):
        rows.append(
            [
                InlineKeyboardButton(
                    opt[:60], callback_data=f"ch_opt:{session_id}:{round_id}:{i}"
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def cancel_match() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(T.LEAVE_QUEUE, callback_data="str_cancel")]]
    )


def settings_keyboard(user) -> InlineKeyboardMarkup:
    def flag(v: bool) -> str:
        return T.ON if v else T.OFF

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
                    f"نمایش هویت: {flag(user.show_identity)}",
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
                    f"نمایش عکس: {flag(user.show_photo)}",
                    callback_data="set:show_photo",
                )
            ],
            [
                InlineKeyboardButton(
                    f"نمایش آیدی خصوصی: {flag(user.show_private_id)}",
                    callback_data="set:show_private_id",
                )
            ],
        ]
    )
