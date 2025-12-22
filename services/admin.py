import asyncio
import logging
import re

from aiogram import types
from aiogram.exceptions import TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

import config
from callbacks import AdminAnnouncementCallback, AnnouncementType, AdminInventoryManagementCallback, InventoryAction, \
    AddType, UserManagementCallback, UserManagementOperation, StatisticsCallback, StatisticsEntity, StatisticsTimeDelta, \
    WalletCallback
from crypto_api.CryptoApiWrapper import CryptoApiWrapper
from db import session_commit
from enums.bot_entity import BotEntity
from enums.cryptocurrency import Cryptocurrency
from handlers.admin.constants import AdminConstants, AdminInventoryManagementStates, UserManagementStates, WalletStates
from handlers.common.common import add_pagination_buttons
from models.withdrawal import WithdrawalDTO
from repositories.buy import BuyRepository
from repositories.category import CategoryRepository
from repositories.deposit import DepositRepository
from repositories.item import ItemRepository
from repositories.user import UserRepository
from utils.localizator import Localizator


class AdminService:

    @staticmethod
    async def get_announcement_menu() -> tuple[str, InlineKeyboardBuilder]:
        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "send_everyone"),
                          callback_data=AdminAnnouncementCallback.create(1))
        kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "restocking"),
                          callback_data=AdminAnnouncementCallback.create(2, AnnouncementType.RESTOCKING))
        kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "stock"),
                          callback_data=AdminAnnouncementCallback.create(2, AnnouncementType.CURRENT_STOCK))
        kb_builder.row(AdminConstants.back_to_main_button)
        kb_builder.adjust(1)
        return Localizator.get_text(BotEntity.ADMIN, "announcements"), kb_builder

    @staticmethod
    async def send_announcement(callback: CallbackQuery, session: AsyncSession | Session):
        unpacked_cb = AdminAnnouncementCallback.unpack(callback.data)
        await callback.message.edit_reply_markup()
        active_users = await UserRepository.get_active(session)
        all_users_count = await UserRepository.get_all_count(session)
        counter = 0
        for user in active_users:
            try:
                await callback.message.copy_to(user.telegram_id, reply_markup=None)
                counter += 1
                await asyncio.sleep(1.5)
            except TelegramForbiddenError as e:
                logging.error(f"TelegramForbiddenError: {e.message}")
                if "user is deactivated" in e.message.lower():
                    user.can_receive_messages = False
                elif "bot was blocked by the user" in e.message.lower():
                    user.can_receive_messages = False
                    await UserRepository.update(user, session)
            except Exception as e:
                logging.error(e)
            finally:
                if unpacked_cb.announcement_type == AnnouncementType.RESTOCKING:
                    await ItemRepository.set_not_new(session)
                await session_commit(session)
        return Localizator.get_text(BotEntity.ADMIN, "sending_result").format(counter=counter,
                                                                              len=len(active_users),
                                                                              users_count=all_users_count)

    @staticmethod
    async def get_inventory_management_menu() -> tuple[str, InlineKeyboardBuilder]:
        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(
            text=Localizator.get_text(BotEntity.ADMIN, "browse_catalog"),
            callback_data=AdminInventoryManagementCallback.create(level=1, category_id=-1)
        )
        kb_builder.button(
            text=Localizator.get_text(BotEntity.ADMIN, "quick_add_items"),
            callback_data=AdminInventoryManagementCallback.create(level=3, action=InventoryAction.ADD_ITEMS)
        )
        kb_builder.adjust(1)
        kb_builder.row(AdminConstants.back_to_main_button)
        return Localizator.get_text(BotEntity.ADMIN, "inventory_management"), kb_builder

    @staticmethod
    async def get_category_browser(
        callback: CallbackQuery,
        session: AsyncSession | Session
    ) -> tuple[str, InlineKeyboardBuilder]:
        unpacked_cb = AdminInventoryManagementCallback.unpack(callback.data)
        category_id = unpacked_cb.category_id
        page = unpacked_cb.page
        show_archived = unpacked_cb.show_archived
        kb_builder = InlineKeyboardBuilder()

        if category_id == -1:
            categories = await CategoryRepository.get_all_roots_filtered(page, session, show_archived)
            breadcrumb_str = Localizator.get_text(BotEntity.ADMIN, "root_level")
            parent_id_for_back = None
        else:
            categories = await CategoryRepository.get_all_children_filtered(category_id, page, session, show_archived)
            current_cat = await CategoryRepository.get_by_id(category_id, session)
            breadcrumb = await CategoryRepository.get_breadcrumb(category_id, session)
            breadcrumb_str = " > ".join([c.name for c in breadcrumb])
            parent_id_for_back = current_cat.parent_id if current_cat else None

        for cat in categories:
            archived_indicator = "🗄️ " if not cat.is_active else ""
            if cat.is_product:
                qty = await CategoryRepository.get_available_qty(cat.id, session)
                button_text = f"{archived_indicator}📦 {cat.name} ({qty} items)"
                next_level = 2
            else:
                child_count = await CategoryRepository.count_children(cat.id, session)
                button_text = f"{archived_indicator}📁 {cat.name} ({child_count})"
                next_level = 1

            kb_builder.button(
                text=button_text,
                callback_data=AdminInventoryManagementCallback.create(
                    level=next_level,
                    category_id=cat.id,
                    page=0,
                    show_archived=show_archived
                )
            )

        kb_builder.adjust(1)

        # Action buttons (only for active view)
        if not show_archived:
            action_buttons = []
            action_buttons.append(types.InlineKeyboardButton(
                text=Localizator.get_text(BotEntity.ADMIN, "add_category_btn"),
                callback_data=AdminInventoryManagementCallback.create(
                    level=3,
                    category_id=category_id,
                    action=InventoryAction.ADD_CATEGORY
                ).pack()
            ))
            action_buttons.append(types.InlineKeyboardButton(
                text=Localizator.get_text(BotEntity.ADMIN, "add_product_btn"),
                callback_data=AdminInventoryManagementCallback.create(
                    level=3,
                    category_id=category_id,
                    action=InventoryAction.ADD_PRODUCT
                ).pack()
            ))
            kb_builder.row(*action_buttons)

        # Archive toggle button
        toggle_text = Localizator.get_text(BotEntity.ADMIN, "show_active") if show_archived else Localizator.get_text(BotEntity.ADMIN, "show_archived")
        kb_builder.row(types.InlineKeyboardButton(
            text=toggle_text,
            callback_data=AdminInventoryManagementCallback.create(
                level=1,
                category_id=category_id,
                page=0,
                show_archived=not show_archived
            ).pack()
        ))

        if category_id == -1:
            kb_builder.row(AdminConstants.back_to_main_button)
        else:
            back_cat_id = parent_id_for_back if parent_id_for_back is not None else -1
            kb_builder.row(types.InlineKeyboardButton(
                text=Localizator.get_text(BotEntity.COMMON, "back_button"),
                callback_data=AdminInventoryManagementCallback.create(
                    level=1,
                    category_id=back_cat_id,
                    page=0,
                    show_archived=show_archived
                ).pack()
            ))

        archive_indicator = " [ARCHIVED]" if show_archived else ""
        msg = f"📂 {breadcrumb_str}{archive_indicator}\n\n"
        if len(categories) == 0:
            msg += Localizator.get_text(BotEntity.ADMIN, "no_items_here")
        else:
            msg += Localizator.get_text(BotEntity.ADMIN, "select_or_add")

        return msg, kb_builder

    @staticmethod
    async def get_product_management_menu(
        callback: CallbackQuery,
        session: AsyncSession | Session
    ) -> tuple[str, InlineKeyboardBuilder]:
        unpacked_cb = AdminInventoryManagementCallback.unpack(callback.data)
        category_id = unpacked_cb.category_id
        show_archived = unpacked_cb.show_archived
        kb_builder = InlineKeyboardBuilder()

        product = await CategoryRepository.get_by_id(category_id, session)
        if not product or not product.is_product:
            kb_builder.row(AdminConstants.back_to_main_button)
            return Localizator.get_text(BotEntity.ADMIN, "product_not_found"), kb_builder

        qty = await CategoryRepository.get_available_qty(category_id, session)
        breadcrumb = await CategoryRepository.get_breadcrumb(category_id, session)
        breadcrumb_str = " > ".join([c.name for c in breadcrumb])

        if product.is_active:
            # Active product - show normal management options
            kb_builder.button(
                text=Localizator.get_text(BotEntity.ADMIN, "add_items_to_product"),
                callback_data=AdminInventoryManagementCallback.create(
                    level=3, category_id=category_id, action=InventoryAction.ADD_ITEMS
                )
            )
            kb_builder.button(
                text=Localizator.get_text(BotEntity.ADMIN, "edit_price"),
                callback_data=AdminInventoryManagementCallback.create(
                    level=3, category_id=category_id, action=InventoryAction.EDIT_PRICE
                )
            )
            kb_builder.button(
                text=Localizator.get_text(BotEntity.ADMIN, "edit_description"),
                callback_data=AdminInventoryManagementCallback.create(
                    level=3, category_id=category_id, action=InventoryAction.EDIT_DESCRIPTION
                )
            )
            kb_builder.button(
                text=Localizator.get_text(BotEntity.ADMIN, "edit_image"),
                callback_data=AdminInventoryManagementCallback.create(
                    level=3, category_id=category_id, action=InventoryAction.EDIT_IMAGE
                )
            )
            kb_builder.button(
                text=Localizator.get_text(BotEntity.ADMIN, "delete_product"),
                callback_data=AdminInventoryManagementCallback.create(
                    level=4, category_id=category_id, action=InventoryAction.DELETE
                )
            )
        else:
            # Archived product - show reactivate option
            kb_builder.button(
                text=Localizator.get_text(BotEntity.ADMIN, "reactivate_category"),
                callback_data=AdminInventoryManagementCallback.create(
                    level=3, category_id=category_id, action=InventoryAction.REACTIVATE,
                    show_archived=show_archived
                )
            )
        kb_builder.adjust(1)

        back_cat_id = product.parent_id if product.parent_id is not None else -1
        kb_builder.row(types.InlineKeyboardButton(
            text=Localizator.get_text(BotEntity.COMMON, "back_button"),
            callback_data=AdminInventoryManagementCallback.create(
                level=1,
                category_id=back_cat_id,
                page=0,
                show_archived=show_archived
            ).pack()
        ))

        archived_indicator = " [ARCHIVED]" if not product.is_active else ""
        msg = Localizator.get_text(BotEntity.ADMIN, "product_info").format(
            breadcrumb=breadcrumb_str,
            name=product.name + archived_indicator,
            price=product.price or 0,
            currency_sym=Localizator.get_currency_symbol(),
            description=product.description or "-",
            qty=qty,
            has_image="✅" if product.image_file_id else "❌"
        )

        return msg, kb_builder

    @staticmethod
    async def get_action_prompt(
        callback: CallbackQuery,
        state: FSMContext,
        session: AsyncSession | Session
    ) -> tuple[str, InlineKeyboardBuilder]:
        unpacked_cb = AdminInventoryManagementCallback.unpack(callback.data)
        action = unpacked_cb.action
        category_id = unpacked_cb.category_id
        show_archived = unpacked_cb.show_archived
        kb_builder = InlineKeyboardBuilder()

        cancel_cb = AdminInventoryManagementCallback.create(
            level=1 if category_id == -1 else (2 if (await CategoryRepository.get_by_id(category_id, session) or type('', (), {'is_product': False})).is_product else 1),
            category_id=category_id,
            show_archived=show_archived
        )
        kb_builder.button(
            text=Localizator.get_text(BotEntity.COMMON, "cancel"),
            callback_data=cancel_cb
        )

        await state.update_data(category_id=category_id, action=action.value if action else 0)

        match action:
            case InventoryAction.ADD_CATEGORY:
                await state.set_state(AdminInventoryManagementStates.category_name)
                if category_id == -1:
                    msg = Localizator.get_text(BotEntity.ADMIN, "enter_category_name_root")
                else:
                    parent = await CategoryRepository.get_by_id(category_id, session)
                    msg = Localizator.get_text(BotEntity.ADMIN, "enter_category_name").format(
                        parent_name=parent.name if parent else "Root"
                    )
                return msg, kb_builder

            case InventoryAction.ADD_PRODUCT:
                await state.set_state(AdminInventoryManagementStates.product_name)
                if category_id == -1:
                    msg = Localizator.get_text(BotEntity.ADMIN, "enter_product_name_root")
                else:
                    parent = await CategoryRepository.get_by_id(category_id, session)
                    msg = Localizator.get_text(BotEntity.ADMIN, "enter_product_name").format(
                        parent_name=parent.name if parent else "Root"
                    )
                return msg, kb_builder

            case InventoryAction.ADD_ITEMS:
                if unpacked_cb.add_type is None:
                    kb_builder = InlineKeyboardBuilder()
                    kb_builder.button(
                        text=Localizator.get_text(BotEntity.ADMIN, "add_items_json"),
                        callback_data=AdminInventoryManagementCallback.create(
                            level=3, category_id=category_id,
                            action=InventoryAction.ADD_ITEMS, add_type=AddType.JSON
                        )
                    )
                    kb_builder.button(
                        text=Localizator.get_text(BotEntity.ADMIN, "add_items_txt"),
                        callback_data=AdminInventoryManagementCallback.create(
                            level=3, category_id=category_id,
                            action=InventoryAction.ADD_ITEMS, add_type=AddType.TXT
                        )
                    )
                    kb_builder.adjust(1)
                    kb_builder.row(types.InlineKeyboardButton(
                        text=Localizator.get_text(BotEntity.COMMON, "cancel"),
                        callback_data=cancel_cb.pack()
                    ))
                    return Localizator.get_text(BotEntity.ADMIN, "add_items_msg"), kb_builder
                else:
                    await state.update_data(add_type=unpacked_cb.add_type.value)
                    await state.set_state(AdminInventoryManagementStates.document)
                    if unpacked_cb.add_type == AddType.JSON:
                        return Localizator.get_text(BotEntity.ADMIN, "add_items_json_msg"), kb_builder
                    else:
                        return Localizator.get_text(BotEntity.ADMIN, "add_items_txt_msg"), kb_builder

            case InventoryAction.EDIT_PRICE:
                await state.set_state(AdminInventoryManagementStates.edit_price)
                product = await CategoryRepository.get_by_id(category_id, session)
                msg = Localizator.get_text(BotEntity.ADMIN, "enter_new_price").format(
                    product_name=product.name if product else "",
                    current_price=product.price if product else 0,
                    currency_sym=Localizator.get_currency_symbol()
                )
                return msg, kb_builder

            case InventoryAction.EDIT_DESCRIPTION:
                await state.set_state(AdminInventoryManagementStates.edit_description)
                product = await CategoryRepository.get_by_id(category_id, session)
                msg = Localizator.get_text(BotEntity.ADMIN, "enter_new_description").format(
                    product_name=product.name if product else "",
                    current_description=product.description if product else "-"
                )
                return msg, kb_builder

            case InventoryAction.EDIT_IMAGE:
                await state.set_state(AdminInventoryManagementStates.document)
                await state.update_data(edit_image=True)
                product = await CategoryRepository.get_by_id(category_id, session)
                msg = Localizator.get_text(BotEntity.ADMIN, "send_new_image").format(
                    product_name=product.name if product else ""
                )
                return msg, kb_builder

            case InventoryAction.REACTIVATE:
                # Reactivate archived category
                category = await CategoryRepository.get_by_id(category_id, session)
                if category:
                    await CategoryRepository.set_active(category_id, session)
                    await session_commit(session)
                    msg = Localizator.get_text(BotEntity.ADMIN, "category_reactivated").format(
                        name=category.name
                    )
                else:
                    msg = Localizator.get_text(BotEntity.ADMIN, "category_not_found")
                
                kb_builder = InlineKeyboardBuilder()
                kb_builder.row(types.InlineKeyboardButton(
                    text=Localizator.get_text(BotEntity.COMMON, "back_button"),
                    callback_data=AdminInventoryManagementCallback.create(
                        level=1,
                        category_id=-1,
                        show_archived=False
                    ).pack()
                ))
                return msg, kb_builder

            case _:
                return Localizator.get_text(BotEntity.ADMIN, "unknown_action"), kb_builder

    @staticmethod
    async def get_delete_confirmation(
        callback: CallbackQuery,
        session: AsyncSession | Session
    ) -> tuple[str, InlineKeyboardBuilder]:
        unpacked_cb = AdminInventoryManagementCallback.unpack(callback.data)
        category_id = unpacked_cb.category_id
        kb_builder = InlineKeyboardBuilder()

        category = await CategoryRepository.get_by_id(category_id, session)
        if not category:
            kb_builder.row(AdminConstants.back_to_main_button)
            return Localizator.get_text(BotEntity.ADMIN, "category_not_found"), kb_builder

        qty = await CategoryRepository.get_available_qty(category_id, session)
        sold_count = await CategoryRepository.count_sold_in_subtree(category_id, session)

        kb_builder.button(
            text=Localizator.get_text(BotEntity.COMMON, "confirm"),
            callback_data=AdminInventoryManagementCallback.create(
                level=5, category_id=category_id, action=InventoryAction.DELETE, confirmation=True
            )
        )
        kb_builder.button(
            text=Localizator.get_text(BotEntity.COMMON, "cancel"),
            callback_data=AdminInventoryManagementCallback.create(
                level=2, category_id=category_id
            )
        )

        if sold_count > 0:
            # Will archive
            msg = Localizator.get_text(BotEntity.ADMIN, "confirm_archive_category").format(
                name=category.name,
                qty=qty,
                sold_count=sold_count
            )
        else:
            # Will fully delete
            msg = Localizator.get_text(BotEntity.ADMIN, "confirm_delete_category").format(
                name=category.name,
                qty=qty
            )

        return msg, kb_builder

    @staticmethod
    async def execute_delete(
        callback: CallbackQuery,
        session: AsyncSession | Session
    ) -> tuple[str, InlineKeyboardBuilder]:
        """
        Smart delete: archives if sold items exist, otherwise fully deletes.
        """
        unpacked_cb = AdminInventoryManagementCallback.unpack(callback.data)
        category_id = unpacked_cb.category_id
        kb_builder = InlineKeyboardBuilder()

        category = await CategoryRepository.get_by_id(category_id, session)
        if not category:
            kb_builder.row(AdminConstants.back_to_main_button)
            return Localizator.get_text(BotEntity.ADMIN, "category_not_found"), kb_builder

        category_name = category.name
        parent_id = category.parent_id

        # Check for sold items in subtree
        sold_count = await CategoryRepository.count_sold_in_subtree(category_id, session)

        if sold_count > 0:
            # Archive: set inactive (preserves purchase history)
            await CategoryRepository.set_inactive(category_id, session)
            await session_commit(session)
            msg = Localizator.get_text(BotEntity.ADMIN, "category_archived").format(
                name=category_name,
                sold_count=sold_count
            )
        else:
            # Full delete: no sold items, safe to remove entirely
            await CategoryRepository.delete_by_id(category_id, session)
            await session_commit(session)
            msg = Localizator.get_text(BotEntity.ADMIN, "category_deleted").format(name=category_name)

        back_cat_id = parent_id if parent_id is not None else -1
        kb_builder.row(types.InlineKeyboardButton(
            text=Localizator.get_text(BotEntity.COMMON, "back_button"),
            callback_data=AdminInventoryManagementCallback.create(
                level=1,
                category_id=back_cat_id
            ).pack()
        ))

        return msg, kb_builder

    @staticmethod
    async def get_user_management_menu() -> tuple[str, InlineKeyboardBuilder]:
        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "credit_management"),
                          callback_data=UserManagementCallback.create(1))
        kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "make_refund"),
                          callback_data=UserManagementCallback.create(2))
        kb_builder.adjust(1)
        kb_builder.row(AdminConstants.back_to_main_button)
        return Localizator.get_text(BotEntity.ADMIN, "user_management"), kb_builder

    @staticmethod
    async def get_credit_management_menu(callback: CallbackQuery) -> tuple[str, InlineKeyboardBuilder]:
        unpacked_cb = UserManagementCallback.unpack(callback.data)
        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "credit_management_add_balance"),
                          callback_data=UserManagementCallback.create(1, UserManagementOperation.ADD_BALANCE))
        kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "credit_management_reduce_balance"),
                          callback_data=UserManagementCallback.create(1, UserManagementOperation.REDUCE_BALANCE))
        kb_builder.row(unpacked_cb.get_back_button())
        return Localizator.get_text(BotEntity.ADMIN, "credit_management"), kb_builder

    @staticmethod
    async def request_user_entity(callback: CallbackQuery, state: FSMContext):
        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(text=Localizator.get_text(BotEntity.COMMON, "cancel"),
                          callback_data=UserManagementCallback.create(0))
        await state.set_state(UserManagementStates.user_entity)
        unpacked_cb = UserManagementCallback.unpack(callback.data)
        await state.update_data(operation=unpacked_cb.operation.value)
        return Localizator.get_text(BotEntity.ADMIN, "credit_management_request_user_entity"), kb_builder

    @staticmethod
    async def request_balance_amount(message: Message, state: FSMContext) -> tuple[str, InlineKeyboardBuilder]:
        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(text=Localizator.get_text(BotEntity.COMMON, "cancel"),
                          callback_data=UserManagementCallback.create(0))
        await state.update_data(user_entity=message.text)
        await state.set_state(UserManagementStates.balance_amount)
        data = await state.get_data()
        operation = UserManagementOperation(int(data['operation']))
        match operation:
            case UserManagementOperation.ADD_BALANCE:
                return Localizator.get_text(BotEntity.ADMIN, "credit_management_plus_operation").format(
                    currency_text=Localizator.get_currency_text()), kb_builder
            case UserManagementOperation.REDUCE_BALANCE:
                return Localizator.get_text(BotEntity.ADMIN, "credit_management_minus_operation").format(
                    currency_text=Localizator.get_currency_text()), kb_builder

    @staticmethod
    async def balance_management(message: Message, state: FSMContext, session: AsyncSession | Session) -> str:
        data = await state.get_data()
        await state.clear()
        user = await UserRepository.get_user_entity(data['user_entity'], session)
        operation = UserManagementOperation(int(data['operation']))
        if user is None:
            return Localizator.get_text(BotEntity.ADMIN, "credit_management_user_not_found")
        elif operation == UserManagementOperation.ADD_BALANCE:
            user.top_up_amount += float(message.text)
            await UserRepository.update(user, session)
            await session_commit(session)
            return Localizator.get_text(BotEntity.ADMIN, "credit_management_added_success").format(
                amount=message.text,
                telegram_id=user.telegram_id,
                currency_text=Localizator.get_currency_text())
        else:
            user.consume_records += float(message.text)
            await UserRepository.update(user, session)
            await session_commit(session)
            return Localizator.get_text(BotEntity.ADMIN, "credit_management_reduced_success").format(
                amount=message.text,
                telegram_id=user.telegram_id,
                currency_text=Localizator.get_currency_text())

    @staticmethod
    async def get_refund_menu(callback: CallbackQuery, session: AsyncSession | Session) -> tuple[
        str, InlineKeyboardBuilder]:
        unpacked_cb = UserManagementCallback.unpack(callback.data)
        kb_builder = InlineKeyboardBuilder()
        refund_data = await BuyRepository.get_refund_data(unpacked_cb.page, session)
        for refund_item in refund_data:
            callback = UserManagementCallback.create(
                unpacked_cb.level + 1,
                UserManagementOperation.REFUND,
                buy_id=refund_item.buy_id)
            if refund_item.telegram_username:
                kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "refund_by_username").format(
                    telegram_username=refund_item.telegram_username,
                    total_price=refund_item.total_price,
                    subcategory=refund_item.subcategory_name,
                    currency_sym=Localizator.get_currency_symbol()),
                    callback_data=callback)
            else:
                kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "refund_by_tgid").format(
                    telegram_id=refund_item.telegram_id,
                    total_price=refund_item.total_price,
                    subcategory=refund_item.subcategory_name,
                    currency_sym=Localizator.get_currency_symbol()),
                    callback_data=callback)
        kb_builder.adjust(1)
        kb_builder = await add_pagination_buttons(kb_builder, unpacked_cb,
                                                  BuyRepository.get_max_refund_page(session),
                                                  unpacked_cb.get_back_button(0))
        return Localizator.get_text(BotEntity.ADMIN, "refund_menu"), kb_builder

    @staticmethod
    async def refund_confirmation(callback: CallbackQuery, session: AsyncSession | Session):
        unpacked_cb = UserManagementCallback.unpack(callback.data)
        unpacked_cb.confirmation = True
        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(text=Localizator.get_text(BotEntity.COMMON, "confirm"),
                          callback_data=unpacked_cb)
        kb_builder.button(text=Localizator.get_text(BotEntity.COMMON, "cancel"),
                          callback_data=UserManagementCallback.create(0))
        refund_data = await BuyRepository.get_refund_data_single(unpacked_cb.buy_id, session)
        if refund_data.telegram_username:
            return Localizator.get_text(BotEntity.ADMIN, "refund_confirmation_by_username").format(
                telegram_username=refund_data.telegram_username,
                quantity=refund_data.quantity,
                subcategory=refund_data.subcategory_name,
                total_price=refund_data.total_price,
                currency_sym=Localizator.get_currency_symbol()), kb_builder
        else:
            return Localizator.get_text(BotEntity.ADMIN, "refund_confirmation_by_tgid").format(
                telegram_id=refund_data.telegram_id,
                quantity=refund_data.quantity,
                subcategory=refund_data.subcategory_name,
                total_price=refund_data.total_price,
                currency_sym=Localizator.get_currency_symbol()), kb_builder

    @staticmethod
    async def get_statistics_menu() -> tuple[str, InlineKeyboardBuilder]:
        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "users_statistics"),
                          callback_data=StatisticsCallback.create(1, StatisticsEntity.USERS))
        kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "buys_statistics"),
                          callback_data=StatisticsCallback.create(1, StatisticsEntity.BUYS))
        kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "deposits_statistics"),
                          callback_data=StatisticsCallback.create(1, StatisticsEntity.DEPOSITS))
        kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "get_database_file"),
                          callback_data=StatisticsCallback.create(3))
        kb_builder.adjust(1)
        kb_builder.row(AdminConstants.back_to_main_button)
        return Localizator.get_text(BotEntity.ADMIN, "pick_statistics_entity"), kb_builder

    @staticmethod
    async def get_timedelta_menu(callback: CallbackQuery) -> tuple[str, InlineKeyboardBuilder]:
        kb_builder = InlineKeyboardBuilder()
        unpacked_cb = StatisticsCallback.unpack(callback.data)
        kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "1_day"),
                          callback_data=StatisticsCallback.create(unpacked_cb.level + 1,
                                                                  unpacked_cb.statistics_entity,
                                                                  StatisticsTimeDelta.DAY))
        kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "7_day"),
                          callback_data=StatisticsCallback.create(unpacked_cb.level + 1,
                                                                  unpacked_cb.statistics_entity,
                                                                  StatisticsTimeDelta.WEEK))
        kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "30_day"),
                          callback_data=StatisticsCallback.create(unpacked_cb.level + 1,
                                                                  unpacked_cb.statistics_entity,
                                                                  StatisticsTimeDelta.MONTH))
        kb_builder.row(unpacked_cb.get_back_button(0))
        return Localizator.get_text(BotEntity.ADMIN, "statistics_timedelta"), kb_builder

    @staticmethod
    async def get_statistics(callback: CallbackQuery, session: AsyncSession | Session):
        unpacked_cb = StatisticsCallback.unpack(callback.data)
        kb_builder = InlineKeyboardBuilder()
        match unpacked_cb.statistics_entity:
            case StatisticsEntity.USERS:
                users, users_count = await UserRepository.get_by_timedelta(unpacked_cb.timedelta, unpacked_cb.page,
                                                                           session)
                [kb_builder.button(text=user.telegram_username, url=f't.me/{user.telegram_username}') for user in
                 users
                 if user.telegram_username]
                kb_builder.adjust(1)
                kb_builder = await add_pagination_buttons(
                    kb_builder,
                    unpacked_cb,
                    UserRepository.get_max_page_by_timedelta(unpacked_cb.timedelta, session),
                    None)
                kb_builder.row(AdminConstants.back_to_main_button, unpacked_cb.get_back_button())
                return Localizator.get_text(BotEntity.ADMIN, "new_users_msg").format(
                    users_count=users_count,
                    timedelta=unpacked_cb.timedelta.value
                ), kb_builder
            case StatisticsEntity.BUYS:
                buys = await BuyRepository.get_by_timedelta(unpacked_cb.timedelta, session)
                total_profit = 0.0
                items_sold = 0
                for buy in buys:
                    total_profit += buy.total_price
                    items_sold += buy.quantity
                kb_builder.row(AdminConstants.back_to_main_button, unpacked_cb.get_back_button())
                return Localizator.get_text(BotEntity.ADMIN, "sales_statistics").format(
                    timedelta=unpacked_cb.timedelta,
                    total_profit=total_profit, items_sold=items_sold,
                    buys_count=len(buys), currency_sym=Localizator.get_currency_symbol()), kb_builder
            case StatisticsEntity.DEPOSITS:
                deposits = await DepositRepository.get_by_timedelta(unpacked_cb.timedelta, session)
                fiat_amount = 0.0
                btc_amount = 0.0
                ltc_amount = 0.0
                sol_amount = 0.0
                eth_amount = 0.0
                bnb_amount = 0.0
                for deposit in deposits:
                    match deposit.network:
                        case "BTC":
                            btc_amount += deposit.amount / pow(10, deposit.network.get_divider())
                        case "LTC":
                            ltc_amount += deposit.amount / pow(10, deposit.network.get_divider())
                        case "SOL":
                            sol_amount += deposit.amount / pow(10, deposit.network.get_divider())
                        case "ETH":
                            eth_amount += deposit.amount / pow(10, deposit.network.get_divider())
                        case "BNB":
                            bnb_amount += deposit.amount / pow(10, deposit.network.get_divider())
                prices = await CryptoApiWrapper.get_crypto_prices()
                btc_price = prices[Cryptocurrency.BTC.get_coingecko_name()][config.CURRENCY.value.lower()]
                ltc_price = prices[Cryptocurrency.LTC.get_coingecko_name()][config.CURRENCY.value.lower()]
                sol_price = prices[Cryptocurrency.SOL.get_coingecko_name()][config.CURRENCY.value.lower()]
                eth_price = prices[Cryptocurrency.ETH.get_coingecko_name()][config.CURRENCY.value.lower()]
                bnb_price = prices[Cryptocurrency.BNB.get_coingecko_name()][config.CURRENCY.value.lower()]
                fiat_amount += ((btc_amount * btc_price) + (ltc_amount * ltc_price) + (sol_amount * sol_price)
                                + (eth_amount * eth_price) + (bnb_amount * bnb_price))
                kb_builder.row(AdminConstants.back_to_main_button, unpacked_cb.get_back_button())
                return Localizator.get_text(BotEntity.ADMIN, "deposits_statistics_msg").format(
                    timedelta=unpacked_cb.timedelta, deposits_count=len(deposits),
                    btc_amount=btc_amount, ltc_amount=ltc_amount,
                    sol_amount=sol_amount, eth_amount=eth_amount,
                    bnb_amount=bnb_amount,
                    fiat_amount=fiat_amount, currency_text=Localizator.get_currency_text()), kb_builder

    @staticmethod
    async def get_wallet_menu() -> tuple[str, InlineKeyboardBuilder]:
        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "withdraw_funds"),
                          callback_data=WalletCallback.create(1))
        kb_builder.row(AdminConstants.back_to_main_button)
        return Localizator.get_text(BotEntity.ADMIN, "crypto_withdraw"), kb_builder

    @staticmethod
    async def get_withdraw_menu() -> tuple[str, InlineKeyboardBuilder]:
        kb_builder = InlineKeyboardBuilder()
        wallet_balance = await CryptoApiWrapper.get_wallet_balance()
        [kb_builder.button(
            text=Localizator.get_text(BotEntity.COMMON, f"{key.lower()}_top_up"),
            callback_data=WalletCallback.create(1, Cryptocurrency(key))
        ) for key in wallet_balance.keys()]
        kb_builder.adjust(1)
        kb_builder.row(AdminConstants.back_to_main_button)
        msg_text = Localizator.get_text(BotEntity.ADMIN, "crypto_wallet").format(
            btc_balance=wallet_balance.get('BTC') or 0.0,
            ltc_balance=wallet_balance.get('LTC') or 0.0,
            sol_balance=wallet_balance.get('SOL') or 0.0,
            eth_balance=wallet_balance.get('ETH') or 0.0,
            bnb_balance=wallet_balance.get('BNB') or 0.0
        )
        if sum(wallet_balance.values()) > 0:
            msg_text += Localizator.get_text(BotEntity.ADMIN, "choose_crypto_to_withdraw")
        return msg_text, kb_builder

    @staticmethod
    async def request_crypto_address(callback: CallbackQuery, state: FSMContext) -> tuple[str, InlineKeyboardBuilder]:
        unpacked_cb = WalletCallback.unpack(callback.data)
        kb_builder = InlineKeyboardBuilder()
        kb_builder.row(AdminConstants.back_to_main_button)
        await state.update_data(cryptocurrency=unpacked_cb.cryptocurrency)
        await state.set_state(WalletStates.crypto_address)
        return Localizator.get_text(BotEntity.ADMIN, "send_addr_request").format(
            crypto_name=unpacked_cb.cryptocurrency.value), kb_builder

    @staticmethod
    async def calculate_withdrawal(message: Message, state: FSMContext) -> tuple[str, InlineKeyboardBuilder]:
        kb_builder = InlineKeyboardBuilder()
        if message.text and message.text.lower() == "cancel":
            await state.clear()
            return Localizator.get_text(BotEntity.COMMON, "cancelled"), kb_builder
        to_address = message.text
        state_data = await state.get_data()
        await state.update_data(to_address=to_address)
        cryptocurrency = Cryptocurrency(state_data['cryptocurrency'])
        prices = await CryptoApiWrapper.get_crypto_prices()
        price = prices[cryptocurrency.get_coingecko_name()][config.CURRENCY.value.lower()]

        withdraw_dto = await CryptoApiWrapper.withdrawal(
            cryptocurrency,
            to_address,
            True
        )
        withdraw_dto: WithdrawalDTO = WithdrawalDTO.model_validate(withdraw_dto, from_attributes=True)
        if withdraw_dto.receivingAmount > 0:
            kb_builder.button(text=Localizator.get_text(BotEntity.COMMON, "confirm"),
                              callback_data=WalletCallback.create(2, cryptocurrency))
        kb_builder.button(text=Localizator.get_text(BotEntity.COMMON, "cancel"),
                          callback_data=WalletCallback.create(0))
        return Localizator.get_text(BotEntity.ADMIN, "crypto_withdrawal_info").format(
            address=withdraw_dto.toAddress,
            crypto_name=cryptocurrency.value,
            withdrawal_amount=withdraw_dto.totalWithdrawalAmount,
            withdrawal_amount_fiat=withdraw_dto.totalWithdrawalAmount * price,
            currency_text=Localizator.get_currency_text(),
            blockchain_fee_amount=withdraw_dto.blockchainFeeAmount,
            blockchain_fee_fiat=withdraw_dto.blockchainFeeAmount * price,
            service_fee_amount=withdraw_dto.serviceFeeAmount,
            service_fee_fiat=withdraw_dto.serviceFeeAmount * price,
            receiving_amount=withdraw_dto.receivingAmount,
            receiving_amount_fiat=withdraw_dto.receivingAmount * price,
        ), kb_builder

    @staticmethod
    async def withdraw_transaction(callback: CallbackQuery, state: FSMContext) -> tuple[str, InlineKeyboardBuilder]:
        unpacked_cb = WalletCallback.unpack(callback.data)
        state_data = await state.get_data()
        kb_builder = InlineKeyboardBuilder()
        withdraw_dto = await CryptoApiWrapper.withdrawal(
            unpacked_cb.cryptocurrency,
            state_data['to_address'],
            False
        )
        withdraw_dto = WithdrawalDTO.model_validate(withdraw_dto, from_attributes=True)
        match unpacked_cb.cryptocurrency:
            case Cryptocurrency.LTC:
                [kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "transaction"),
                                   url=f"{CryptoApiWrapper.LTC_API_BASENAME_TX}{tx_id}") for tx_id in
                 withdraw_dto.txIdList]
            case Cryptocurrency.BTC:
                [kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "transaction"),
                                   url=f"{CryptoApiWrapper.BTC_API_BASENAME_TX}{tx_id}") for tx_id in
                 withdraw_dto.txIdList]
            case Cryptocurrency.SOL:
                [kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "transaction"),
                                   url=f"{CryptoApiWrapper.SOL_API_BASENAME_TX}{tx_id}") for tx_id in
                 withdraw_dto.txIdList]
            case Cryptocurrency.ETH:
                [kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "transaction"),
                                   url=f"{CryptoApiWrapper.ETH_API_BASENAME_TX}{tx_id}") for tx_id in
                 withdraw_dto.txIdList]
            case Cryptocurrency.BNB:
                [kb_builder.button(text=Localizator.get_text(BotEntity.ADMIN, "transaction"),
                                   url=f"{CryptoApiWrapper.BNB_API_BASENAME_TX}{tx_id}") for tx_id in
                 withdraw_dto.txIdList]
        kb_builder.adjust(1)
        await state.clear()
        return Localizator.get_text(BotEntity.ADMIN, "transaction_broadcasted"), kb_builder

    @staticmethod
    async def validate_withdrawal_address(message: Message, state: FSMContext) -> bool:
        address_regex = {
            Cryptocurrency.BTC: re.compile(r'^bc1[a-zA-HJ-NP-Z0-9]{25,39}$'),
            Cryptocurrency.LTC: re.compile(r'^ltc1[a-zA-HJ-NP-Z0-9]{26,}$'),
            Cryptocurrency.ETH: re.compile(r'^0x[a-fA-F0-9]{40}$'),
            Cryptocurrency.BNB: re.compile(r'^0x[a-fA-F0-9]{40}$'),
            Cryptocurrency.SOL: re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$'),
        }
        state_data = await state.get_data()
        cryptocurrency = Cryptocurrency(state_data['cryptocurrency'])
        regex = address_regex[cryptocurrency]
        return bool(regex.match(message.text))
