from enum import IntEnum

from aiogram import types
from aiogram.filters.callback_data import CallbackData

from enums.bot_entity import BotEntity
from enums.cryptocurrency import Cryptocurrency
from utils.localizator import Localizator


class BaseCallback(CallbackData, prefix="base"):
    level: int

    def get_back_button(self, lvl: int | None = None):
        cb_copy = self.__copy__()
        if lvl is None:
            cb_copy.level = cb_copy.level - 1
        else:
            cb_copy.level = lvl
        return types.InlineKeyboardButton(
            text=Localizator.get_text(BotEntity.COMMON, "back_button"),
            callback_data=cb_copy.create(**cb_copy.model_dump()).pack())


class AllCategoriesCallback(BaseCallback, prefix="all_categories"):
    """
    Callback for category navigation.
    category_id: Current category being viewed (-1 for root)
    quantity: Selected quantity for purchase (products only)
    confirmation: Whether user has confirmed the purchase
    page: Current pagination page
    """
    category_id: int
    quantity: int
    confirmation: bool
    page: int

    @staticmethod
    def create(level: int,
               category_id: int = -1,
               quantity: int = 0,
               confirmation: bool = False,
               page: int = 0) -> 'AllCategoriesCallback':
        return AllCategoriesCallback(
            level=level,
            category_id=category_id,
            quantity=quantity,
            confirmation=confirmation,
            page=page
        )


class MyProfileCallback(BaseCallback, prefix="my_profile"):
    action: str
    args_for_action: int | str
    page: int

    @staticmethod
    def create(level: int, action: str = "", args_for_action="", page=0) -> 'MyProfileCallback':
        return MyProfileCallback(level=level, action=action, args_for_action=args_for_action, page=page)


class CartCallback(BaseCallback, prefix="cart"):
    page: int
    cart_id: int
    cart_item_id: int
    confirmation: bool

    @staticmethod
    def create(level: int = 0, page: int = 0, cart_id: int = -1, cart_item_id: int = -1,
               confirmation=False):
        return CartCallback(level=level, page=page, cart_id=cart_id, cart_item_id=cart_item_id,
                            confirmation=confirmation)


class AdminMenuCallback(BaseCallback, prefix="admin_menu"):
    action: str
    args_to_action: str | int
    page: int

    @staticmethod
    def create(level: int, action: str = "", args_to_action: str = "", page: int = 0):
        return AdminMenuCallback(level=level, action=action, args_to_action=args_to_action, page=page)


class AnnouncementType(IntEnum):
    RESTOCKING = 1
    CURRENT_STOCK = 2
    FROM_RECEIVING_MESSAGE = 3


class AdminAnnouncementCallback(BaseCallback, prefix="announcement"):
    announcement_type: AnnouncementType | None

    @staticmethod
    def create(level: int, announcement_type: AnnouncementType | None = None):
        return AdminAnnouncementCallback(level=level, announcement_type=announcement_type)


class AddType(IntEnum):
    JSON = 1
    TXT = 2


class InventoryAction(IntEnum):
    BROWSE = 0
    ADD_CATEGORY = 1
    ADD_PRODUCT = 2
    ADD_ITEMS = 3
    EDIT_PRICE = 4
    EDIT_DESCRIPTION = 5
    EDIT_IMAGE = 6
    DELETE = 7


class AdminInventoryManagementCallback(BaseCallback, prefix="inv"):
    category_id: int
    action: InventoryAction | None
    add_type: AddType | None
    page: int
    confirmation: bool

    @staticmethod
    def create(
        level: int,
        category_id: int = -1,
        action: InventoryAction | None = None,
        add_type: AddType | None = None,
        page: int = 0,
        confirmation: bool = False
    ):
        return AdminInventoryManagementCallback(
            level=level,
            category_id=category_id,
            action=action,
            add_type=add_type,
            page=page,
            confirmation=confirmation
        )


class UserManagementOperation(IntEnum):
    REFUND = 1
    ADD_BALANCE = 2
    REDUCE_BALANCE = 3


class UserManagementCallback(BaseCallback, prefix="user_management"):
    operation: UserManagementOperation | None
    page: int
    confirmation: bool
    buy_id: int | None

    @staticmethod
    def create(level: int, operation: UserManagementOperation | None = None, page: int = 0, confirmation: bool = False,
               buy_id: int | None = None):
        return UserManagementCallback(level=level, operation=operation, page=page, confirmation=confirmation,
                                      buy_id=buy_id)


class StatisticsEntity(IntEnum):
    USERS = 1
    BUYS = 2
    DEPOSITS = 3


class StatisticsTimeDelta(IntEnum):
    DAY = 1
    WEEK = 7
    MONTH = 30


class StatisticsCallback(BaseCallback, prefix="statistics"):
    statistics_entity: StatisticsEntity | None
    timedelta: StatisticsTimeDelta | None
    page: int

    @staticmethod
    def create(level: int, statistics_entity: StatisticsEntity | None = None,
               timedelta: StatisticsTimeDelta | None = None, page: int = 0):
        return StatisticsCallback(level=level, statistics_entity=statistics_entity, timedelta=timedelta, page=page)


class WalletCallback(BaseCallback, prefix="wallet"):
    cryptocurrency: Cryptocurrency | None

    @staticmethod
    def create(level: int, cryptocurrency: Cryptocurrency | None = None):
        return WalletCallback(level=level, cryptocurrency=cryptocurrency)
