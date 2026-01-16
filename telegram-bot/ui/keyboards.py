from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from ui.labels import (
    BTN_DOG,
    BTN_CAT,
    BTN_OTHER,
    BTN_MY_PET,
    BTN_HOW_IT_WORKS,
    BTN_HOME,
    BTN_EMERGENCY,
    BTN_CARE,
    BTN_VACCINES,
    BTN_ASK_QUESTION,
    BTN_UPDATE_PROFILE,
    BTN_SHOW_PROFILE,
    BTN_HIDE_PROFILE,
    BTN_SKIP,
)


def kb_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_DOG, callback_data="pet_dog")],
            [InlineKeyboardButton(BTN_CAT, callback_data="pet_cat")],
            [InlineKeyboardButton(BTN_OTHER, callback_data="pet_other")],
            [InlineKeyboardButton(BTN_MY_PET, callback_data="my_pet")],
            [InlineKeyboardButton(BTN_HOW_IT_WORKS, callback_data="how_it_works")],
        ]
    )


def kb_home_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_HOME, callback_data="back_to_main")],
        ]
    )


def kb_how_it_works() -> InlineKeyboardMarkup:
    return kb_home_only()


def kb_pet_selection() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_DOG, callback_data="pet_dog")],
            [InlineKeyboardButton(BTN_CAT, callback_data="pet_cat")],
            [InlineKeyboardButton(BTN_OTHER, callback_data="pet_other")],
        ]
    )


def kb_mode_selection(pet_type: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_EMERGENCY, callback_data=f"{pet_type}_emergency")],
            [InlineKeyboardButton(BTN_CARE, callback_data=f"{pet_type}_care")],
            [InlineKeyboardButton(BTN_VACCINES, callback_data=f"{pet_type}_vaccines")],
            [InlineKeyboardButton(BTN_HOME, callback_data="back_to_main")],
        ]
    )


def kb_my_pet_short() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_ASK_QUESTION, callback_data="pet_profile_ask")],
            [InlineKeyboardButton(BTN_UPDATE_PROFILE, callback_data="pet_profile_update")],
            [InlineKeyboardButton(BTN_SHOW_PROFILE, callback_data="pet_profile_show")],
            [InlineKeyboardButton(BTN_HOME, callback_data="back_to_main")],
        ]
    )


def kb_my_pet_full() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(BTN_HIDE_PROFILE, callback_data="pet_profile_hide")],
            [InlineKeyboardButton(BTN_ASK_QUESTION, callback_data="pet_profile_ask")],
            [InlineKeyboardButton(BTN_UPDATE_PROFILE, callback_data="pet_profile_update")],
            [InlineKeyboardButton(BTN_HOME, callback_data="back_to_main")],
        ]
    )


def kb_life_housing() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Квартира", callback_data="pro_life_housing_apartment")],
            [InlineKeyboardButton("Дом", callback_data="pro_life_housing_house")],
            [InlineKeyboardButton("Двор", callback_data="pro_life_housing_yard")],
            [InlineKeyboardButton("На улице", callback_data="pro_life_housing_outdoor")],
            [InlineKeyboardButton(BTN_SKIP, callback_data="pro_life_housing_skip")],
        ]
    )


def kb_life_outdoor() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Нет", callback_data="pro_life_outdoor_no")],
            [InlineKeyboardButton("Иногда", callback_data="pro_life_outdoor_sometimes")],
            [InlineKeyboardButton("Регулярно", callback_data="pro_life_outdoor_regular")],
            [InlineKeyboardButton(BTN_SKIP, callback_data="pro_life_outdoor_skip")],
        ]
    )


def kb_life_diet() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Сухой корм", callback_data="pro_life_diet_dry")],
            [InlineKeyboardButton("Влажный", callback_data="pro_life_diet_wet")],
            [InlineKeyboardButton("Натуральный", callback_data="pro_life_diet_natural")],
            [InlineKeyboardButton("Смешанный", callback_data="pro_life_diet_mixed")],
            [InlineKeyboardButton(BTN_SKIP, callback_data="pro_life_diet_skip")],
        ]
    )


def kb_life_activity() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Низкий", callback_data="pro_life_activity_low")],
            [InlineKeyboardButton("Средний", callback_data="pro_life_activity_medium")],
            [InlineKeyboardButton("Высокий", callback_data="pro_life_activity_high")],
            [InlineKeyboardButton(BTN_SKIP, callback_data="pro_life_activity_skip")],
        ]
    )


def kb_life_walks(pet_type: str) -> InlineKeyboardMarkup:
    rows = []
    if pet_type == "dog":
        rows.append(
            [InlineKeyboardButton("Ввести прогулки/день", callback_data="pro_life_walks_ask")]
        )
    rows.append([InlineKeyboardButton(BTN_SKIP, callback_data="pro_life_walks_skip")])
    return InlineKeyboardMarkup(rows)
