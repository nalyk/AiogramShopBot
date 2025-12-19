from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from callbacks import AdminInventoryManagementCallback, AddType, InventoryAction
from db import session_commit
from enums.bot_entity import BotEntity
from handlers.admin.constants import AdminInventoryManagementStates
from repositories.category import CategoryRepository
from services.admin import AdminService
from services.item import ItemService
from utils.custom_filters import AdminIdFilter
from utils.localizator import Localizator

inventory_management = Router()


async def inventory_management_menu(callback: CallbackQuery, state: FSMContext, **kwargs):
    await state.clear()
    msg, kb_builder = await AdminService.get_inventory_management_menu()
    await callback.message.edit_text(text=msg, reply_markup=kb_builder.as_markup())


async def category_browser(callback: CallbackQuery, session: AsyncSession | Session, state: FSMContext, **kwargs):
    await state.clear()
    msg, kb_builder = await AdminService.get_category_browser(callback, session)
    await callback.message.edit_text(text=msg, reply_markup=kb_builder.as_markup())


async def product_management(callback: CallbackQuery, session: AsyncSession | Session, state: FSMContext, **kwargs):
    await state.clear()
    msg, kb_builder = await AdminService.get_product_management_menu(callback, session)
    await callback.message.edit_text(text=msg, reply_markup=kb_builder.as_markup())


async def action_prompt(callback: CallbackQuery, state: FSMContext, session: AsyncSession | Session, **kwargs):
    msg, kb_builder = await AdminService.get_action_prompt(callback, state, session)
    await callback.message.edit_text(text=msg, reply_markup=kb_builder.as_markup())


async def delete_confirmation(callback: CallbackQuery, session: AsyncSession | Session, **kwargs):
    msg, kb_builder = await AdminService.get_delete_confirmation(callback, session)
    await callback.message.edit_text(text=msg, reply_markup=kb_builder.as_markup())


async def execute_delete(callback: CallbackQuery, session: AsyncSession | Session, **kwargs):
    msg, kb_builder = await AdminService.execute_delete(callback, session)
    await callback.message.edit_text(text=msg, reply_markup=kb_builder.as_markup())


@inventory_management.message(AdminIdFilter(), StateFilter(AdminInventoryManagementStates.category_name))
async def handle_category_name(message: Message, state: FSMContext, session: AsyncSession | Session):
    if message.text and message.text.lower() == 'cancel':
        await state.clear()
        await message.answer(Localizator.get_text(BotEntity.COMMON, "cancelled"))
        return

    state_data = await state.get_data()
    parent_id = state_data.get('category_id')
    if parent_id == -1:
        parent_id = None

    category_name = message.text.strip()

    exists = await CategoryRepository.exists_at_level(category_name, parent_id, session)
    if exists:
        await message.answer(Localizator.get_text(BotEntity.ADMIN, "category_exists"))
        return

    await CategoryRepository.create_category(
        name=category_name,
        parent_id=parent_id,
        is_product=False,
        price=None,
        description=None,
        session=session
    )
    await session_commit(session)
    await state.clear()

    await message.answer(Localizator.get_text(BotEntity.ADMIN, "category_created").format(name=category_name))


@inventory_management.message(AdminIdFilter(), StateFilter(AdminInventoryManagementStates.product_name))
async def handle_product_name(message: Message, state: FSMContext, session: AsyncSession | Session):
    if message.text and message.text.lower() == 'cancel':
        await state.clear()
        await message.answer(Localizator.get_text(BotEntity.COMMON, "cancelled"))
        return

    await state.update_data(product_name=message.text.strip())
    await state.set_state(AdminInventoryManagementStates.product_price)
    await message.answer(Localizator.get_text(BotEntity.ADMIN, "enter_product_price").format(
        currency_text=Localizator.get_currency_text()
    ))


@inventory_management.message(AdminIdFilter(), StateFilter(AdminInventoryManagementStates.product_price))
async def handle_product_price(message: Message, state: FSMContext, session: AsyncSession | Session):
    if message.text and message.text.lower() == 'cancel':
        await state.clear()
        await message.answer(Localizator.get_text(BotEntity.COMMON, "cancelled"))
        return

    try:
        price = float(message.text.strip())
        if price <= 0:
            raise ValueError()
    except ValueError:
        await message.answer(Localizator.get_text(BotEntity.ADMIN, "invalid_price"))
        return

    await state.update_data(product_price=price)
    await state.set_state(AdminInventoryManagementStates.product_description)
    await message.answer(Localizator.get_text(BotEntity.ADMIN, "enter_product_description"))


@inventory_management.message(AdminIdFilter(), StateFilter(AdminInventoryManagementStates.product_description))
async def handle_product_description(message: Message, state: FSMContext, session: AsyncSession | Session):
    if message.text and message.text.lower() == 'cancel':
        await state.clear()
        await message.answer(Localizator.get_text(BotEntity.COMMON, "cancelled"))
        return

    state_data = await state.get_data()
    parent_id = state_data.get('category_id')
    if parent_id == -1:
        parent_id = None

    product_name = state_data.get('product_name')
    price = state_data.get('product_price')
    description = message.text.strip()

    exists = await CategoryRepository.exists_at_level(product_name, parent_id, session)
    if exists:
        await message.answer(Localizator.get_text(BotEntity.ADMIN, "product_exists"))
        await state.clear()
        return

    await CategoryRepository.create_category(
        name=product_name,
        parent_id=parent_id,
        is_product=True,
        price=price,
        description=description,
        session=session
    )
    await session_commit(session)
    await state.clear()

    await message.answer(Localizator.get_text(BotEntity.ADMIN, "product_created").format(
        name=product_name,
        price=price,
        currency_sym=Localizator.get_currency_symbol()
    ))


@inventory_management.message(AdminIdFilter(), StateFilter(AdminInventoryManagementStates.edit_price))
async def handle_edit_price(message: Message, state: FSMContext, session: AsyncSession | Session):
    if message.text and message.text.lower() == 'cancel':
        await state.clear()
        await message.answer(Localizator.get_text(BotEntity.COMMON, "cancelled"))
        return

    try:
        price = float(message.text.strip())
        if price <= 0:
            raise ValueError()
    except ValueError:
        await message.answer(Localizator.get_text(BotEntity.ADMIN, "invalid_price"))
        return

    state_data = await state.get_data()
    category_id = state_data.get('category_id')

    await CategoryRepository.update_price(category_id, price, session)
    await session_commit(session)
    await state.clear()

    await message.answer(Localizator.get_text(BotEntity.ADMIN, "price_updated").format(
        price=price,
        currency_sym=Localizator.get_currency_symbol()
    ))


@inventory_management.message(AdminIdFilter(), StateFilter(AdminInventoryManagementStates.edit_description))
async def handle_edit_description(message: Message, state: FSMContext, session: AsyncSession | Session):
    if message.text and message.text.lower() == 'cancel':
        await state.clear()
        await message.answer(Localizator.get_text(BotEntity.COMMON, "cancelled"))
        return

    state_data = await state.get_data()
    category_id = state_data.get('category_id')
    description = message.text.strip()

    await CategoryRepository.update_description(category_id, description, session)
    await session_commit(session)
    await state.clear()

    await message.answer(Localizator.get_text(BotEntity.ADMIN, "description_updated"))


@inventory_management.message(AdminIdFilter(), F.photo, StateFilter(AdminInventoryManagementStates.document))
async def handle_image_upload(message: Message, state: FSMContext, session: AsyncSession | Session):
    state_data = await state.get_data()
    
    if state_data.get('edit_image'):
        category_id = state_data.get('category_id')
        file_id = message.photo[-1].file_id
        
        await CategoryRepository.update_image(category_id, file_id, session)
        await session_commit(session)
        await state.clear()
        
        await message.answer(Localizator.get_text(BotEntity.ADMIN, "image_updated"))
        return


@inventory_management.message(AdminIdFilter(), F.document, StateFilter(AdminInventoryManagementStates.document))
async def add_items_document(message: Message, state: FSMContext, session: AsyncSession | Session):
    if message.text and message.text.lower() == 'cancel':
        await state.clear()
        await message.answer(Localizator.get_text(BotEntity.COMMON, "cancelled"))
        return
        
    state_data = await state.get_data()
    
    if state_data.get('edit_image'):
        await message.answer(Localizator.get_text(BotEntity.ADMIN, "send_photo_not_file"))
        return
    
    add_type = AddType(int(state_data['add_type']))
    file_name = message.document.file_name
    file_id = message.document.file_id
    file = await message.bot.get_file(file_id)
    await message.bot.download_file(file.file_path, file_name)
    msg = await ItemService.add_items(file_name, add_type, session)
    await message.answer(text=msg)
    await state.clear()


@inventory_management.callback_query(AdminIdFilter(), AdminInventoryManagementCallback.filter())
async def inventory_management_navigation(
    callback: CallbackQuery,
    state: FSMContext,
    callback_data: AdminInventoryManagementCallback,
    session: AsyncSession | Session
):
    current_level = callback_data.level

    levels = {
        0: inventory_management_menu,
        1: category_browser,
        2: product_management,
        3: action_prompt,
        4: delete_confirmation,
        5: execute_delete,
    }

    current_level_function = levels.get(current_level, inventory_management_menu)

    await current_level_function(
        callback=callback,
        state=state,
        session=session
    )
