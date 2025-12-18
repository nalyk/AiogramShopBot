# Implementation Plan: Universal Tree-Based Category System with Image Support

## Executive Summary

This plan converts the current rigid 2-level hierarchy (Category → Subcategory) into a **universal N-level tree structure** where any node can be marked as a "product" level. Products will support images (stored as Telegram `file_id`).

---

## Current vs New Architecture

### Current Architecture (Rigid 2-Level)

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────────────────────┐
│  Category   │     │  Subcategory │     │              Item               │
├─────────────┤     ├──────────────┤     ├─────────────────────────────────┤
│ id          │     │ id           │     │ id                              │
│ name        │     │ name         │     │ category_id (FK)                │
└─────────────┘     └──────────────┘     │ subcategory_id (FK)             │
      │                   │              │ price        ← DUPLICATED       │
      │                   │              │ description  ← DUPLICATED       │
      └─────── NO LINK ───┘              │ private_data ← UNIQUE           │
                                         │ is_sold, is_new                 │
                                         └─────────────────────────────────┘
```

**Problems:**
1. Fixed 2 levels only
2. No link between Category and Subcategory in DB
3. Price/description duplicated per Item (should be per product type)
4. No image support

### New Architecture (Universal Tree)

```
┌────────────────────────────────────────────────────────────────┐
│                          Category                               │
├────────────────────────────────────────────────────────────────┤
│ id            (PK)                                              │
│ parent_id     (FK → Category.id, NULL = root)                   │
│ name          (string)                                          │
│ is_product    (boolean) ← TRUE = this is a sellable product     │
│                                                                 │
│ ─── Product-specific fields (used when is_product=True) ───    │
│ photo_file_id (string, nullable) ← Telegram file_id             │
│ description   (string, nullable)                                │
│ price         (float, nullable)                                 │
└────────────────────────────────────────────────────────────────┘
                              │
                              │ parent_id FK
                              ▼
┌────────────────────────────────────────────────────────────────┐
│                            Item                                 │
├────────────────────────────────────────────────────────────────┤
│ id            (PK)                                              │
│ category_id   (FK → Category.id where is_product=True)          │
│ private_data  (string) ← The only unique data per item          │
│ is_sold       (boolean)                                         │
│ is_new        (boolean)                                         │
└────────────────────────────────────────────────────────────────┘
```

**Benefits:**
1. Unlimited nesting depth
2. Any level can be the product level (via `is_product` flag)
3. Price/description/photo stored ONCE per product type
4. Single unified Category table (no Subcategory)
5. Items only hold unique data (`private_data`)

---

## Example Data Structure

```
Tea (is_product=False)
├── Green (is_product=False)
│   ├── Tea Widow (is_product=TRUE) ← PRODUCT
│   │   ├── photo: "AgACAgIAAxk..."
│   │   ├── description: "Our signature blend..."
│   │   ├── price: 50.0
│   │   └── Items:
│   │       ├── Item 1: private_data="52.123, 13.456, photo_url..."
│   │       ├── Item 2: private_data="52.789, 13.012, photo_url..."
│   │       └── Item 3: private_data="52.456, 13.789, photo_url..."
│   │
│   └── Morning Dew (is_product=TRUE) ← PRODUCT
│       └── Items: [...]
│
└── Black (is_product=False)
    └── Dark Roast (is_product=TRUE) ← PRODUCT
        └── Items: [...]
```

---

## Implementation Steps

### Phase 1: Database Models

#### 1.1 New Category Model (`models/category.py`)

```python
from pydantic import BaseModel
from sqlalchemy import Integer, Column, String, Boolean, Float, ForeignKey, CheckConstraint
from sqlalchemy.orm import relationship, backref
from models.base import Base


class Category(Base):
    __tablename__ = 'categories'

    id = Column(Integer, primary_key=True, unique=True)
    parent_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=True)
    name = Column(String, nullable=False)
    is_product = Column(Boolean, nullable=False, default=False)

    # Product-specific fields (only used when is_product=True)
    photo_file_id = Column(String, nullable=True)  # Telegram file_id
    description = Column(String, nullable=True)
    price = Column(Float, nullable=True)

    # Self-referential relationship
    parent = relationship("Category", remote_side=[id], backref=backref("children", cascade="all, delete-orphan"))

    __table_args__ = (
        CheckConstraint(
            '(is_product = 0) OR (is_product = 1 AND price > 0)',
            name='check_product_has_price'
        ),
    )


class CategoryDTO(BaseModel):
    id: int | None = None
    parent_id: int | None = None
    name: str | None = None
    is_product: bool | None = None
    photo_file_id: str | None = None
    description: str | None = None
    price: float | None = None
```

#### 1.2 Simplified Item Model (`models/item.py`)

```python
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship, backref
from models.base import Base


class Item(Base):
    __tablename__ = 'items'

    id = Column(Integer, primary_key=True, unique=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    category = relationship("Category", backref=backref("items", cascade="all"), passive_deletes="all", lazy="joined")
    private_data = Column(String, nullable=False)
    is_sold = Column(Boolean, nullable=False, default=False)
    is_new = Column(Boolean, nullable=False, default=True)


class ItemDTO(BaseModel):
    id: int | None = None
    category_id: int | None = None  # Must reference a Category where is_product=True
    private_data: str | None = None
    is_sold: bool | None = None
    is_new: bool | None = None
```

#### 1.3 Updated CartItem Model (`models/cartItem.py`)

```python
from pydantic import BaseModel
from sqlalchemy import Column, Integer, ForeignKey, CheckConstraint
from models.base import Base


class CartItem(Base):
    __tablename__ = "cart_items"

    id = Column(Integer, primary_key=True)
    cart_id = Column(Integer, ForeignKey("carts.id"), nullable=False)
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=False)  # Product category
    quantity = Column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint('quantity > 0', name='check_quantity_positive'),
    )


class CartItemDTO(BaseModel):
    id: int | None = None
    cart_id: int | None = None
    category_id: int | None = None  # Product category (is_product=True)
    quantity: int | None = None
```

#### 1.4 Remove Subcategory Model

- Delete `models/subcategory.py`
- Remove from `db.py` imports
- Remove `repositories/subcategory.py`
- Remove `services/subcategory.py` (merge into category service)

---

### Phase 2: Repository Layer

#### 2.1 CategoryRepository (`repositories/category.py`)

```python
import math
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

import config
from db import session_execute, session_flush
from models.category import Category, CategoryDTO
from models.item import Item


class CategoryRepository:

    @staticmethod
    async def get_roots(page: int, session: Session | AsyncSession) -> list[CategoryDTO]:
        """Get root categories (parent_id IS NULL) that have unsold items in their subtree."""
        # Get root categories that have at least one unsold item in their subtree
        stmt = (
            select(Category)
            .where(Category.parent_id.is_(None))
            .limit(config.PAGE_ENTRIES)
            .offset(page * config.PAGE_ENTRIES)
        )
        result = await session_execute(stmt, session)
        categories = result.scalars().all()

        # Filter to only categories with available items
        valid_categories = []
        for cat in categories:
            if await CategoryRepository.has_available_items(cat.id, session):
                valid_categories.append(CategoryDTO.model_validate(cat, from_attributes=True))

        return valid_categories

    @staticmethod
    async def get_children(parent_id: int, page: int, session: Session | AsyncSession) -> list[CategoryDTO]:
        """Get child categories of a given parent that have unsold items."""
        stmt = (
            select(Category)
            .where(Category.parent_id == parent_id)
            .limit(config.PAGE_ENTRIES)
            .offset(page * config.PAGE_ENTRIES)
        )
        result = await session_execute(stmt, session)
        categories = result.scalars().all()

        valid_categories = []
        for cat in categories:
            if cat.is_product:
                # Product category - check if has unsold items directly
                count = await CategoryRepository.get_available_qty(cat.id, session)
                if count > 0:
                    valid_categories.append(CategoryDTO.model_validate(cat, from_attributes=True))
            else:
                # Non-product category - check subtree
                if await CategoryRepository.has_available_items(cat.id, session):
                    valid_categories.append(CategoryDTO.model_validate(cat, from_attributes=True))

        return valid_categories

    @staticmethod
    async def has_available_items(category_id: int, session: Session | AsyncSession) -> bool:
        """Check if a category or any of its descendants has unsold items."""
        # First check direct items (if this is a product category)
        cat = await CategoryRepository.get_by_id(category_id, session)
        if cat.is_product:
            count = await CategoryRepository.get_available_qty(category_id, session)
            return count > 0

        # Check children recursively
        stmt = select(Category).where(Category.parent_id == category_id)
        result = await session_execute(stmt, session)
        children = result.scalars().all()

        for child in children:
            if await CategoryRepository.has_available_items(child.id, session):
                return True

        return False

    @staticmethod
    async def get_available_qty(category_id: int, session: Session | AsyncSession) -> int:
        """Get count of unsold items for a product category."""
        stmt = (
            select(func.count())
            .select_from(Item)
            .where(and_(Item.category_id == category_id, Item.is_sold == False))
        )
        result = await session_execute(stmt, session)
        return result.scalar()

    @staticmethod
    async def get_by_id(category_id: int, session: Session | AsyncSession) -> CategoryDTO:
        stmt = select(Category).where(Category.id == category_id)
        result = await session_execute(stmt, session)
        category = result.scalar()
        return CategoryDTO.model_validate(category, from_attributes=True)

    @staticmethod
    async def get_breadcrumb(category_id: int, session: Session | AsyncSession) -> list[CategoryDTO]:
        """Get full path from root to this category."""
        breadcrumb = []
        current_id = category_id

        while current_id is not None:
            cat = await CategoryRepository.get_by_id(current_id, session)
            breadcrumb.insert(0, cat)
            current_id = cat.parent_id

        return breadcrumb

    @staticmethod
    async def get_or_create_path(path: list[str], is_last_product: bool,
                                  price: float | None, description: str | None,
                                  session: Session | AsyncSession) -> Category:
        """
        Get or create a category path.
        path: ["Tea", "Green", "Tea Widow"]
        is_last_product: True (marks last element as product)
        """
        parent_id = None
        category = None

        for i, name in enumerate(path):
            is_last = (i == len(path) - 1)
            is_product = is_last and is_last_product

            # Try to find existing
            stmt = select(Category).where(
                and_(
                    Category.name == name,
                    Category.parent_id == parent_id if parent_id else Category.parent_id.is_(None)
                )
            )
            result = await session_execute(stmt, session)
            category = result.scalar()

            if category is None:
                # Create new
                category = Category(
                    name=name,
                    parent_id=parent_id,
                    is_product=is_product,
                    price=price if is_product else None,
                    description=description if is_product else None
                )
                session.add(category)
                await session_flush(session)
            elif is_product and not category.is_product:
                # Update to product if needed
                category.is_product = True
                category.price = price
                category.description = description
                await session_flush(session)

            parent_id = category.id

        return category

    @staticmethod
    async def get_maximum_page_roots(session: Session | AsyncSession) -> int:
        """Get max page for root categories."""
        stmt = (
            select(func.count())
            .select_from(Category)
            .where(Category.parent_id.is_(None))
        )
        result = await session_execute(stmt, session)
        count = result.scalar()

        if count % config.PAGE_ENTRIES == 0:
            return max(0, count // config.PAGE_ENTRIES - 1)
        return count // config.PAGE_ENTRIES

    @staticmethod
    async def get_maximum_page_children(parent_id: int, session: Session | AsyncSession) -> int:
        """Get max page for children of a category."""
        stmt = (
            select(func.count())
            .select_from(Category)
            .where(Category.parent_id == parent_id)
        )
        result = await session_execute(stmt, session)
        count = result.scalar()

        if count % config.PAGE_ENTRIES == 0:
            return max(0, count // config.PAGE_ENTRIES - 1)
        return count // config.PAGE_ENTRIES

    @staticmethod
    async def update_photo(category_id: int, photo_file_id: str, session: Session | AsyncSession):
        """Update product photo."""
        stmt = select(Category).where(Category.id == category_id)
        result = await session_execute(stmt, session)
        category = result.scalar()
        category.photo_file_id = photo_file_id
        await session_flush(session)

    @staticmethod
    async def get_products_to_delete(page: int, session: Session | AsyncSession) -> list[CategoryDTO]:
        """Get product categories that have unsold items."""
        subquery = (
            select(Item.category_id)
            .where(Item.is_sold == False)
            .distinct()
        )
        stmt = (
            select(Category)
            .where(and_(Category.is_product == True, Category.id.in_(subquery)))
            .limit(config.PAGE_ENTRIES)
            .offset(page * config.PAGE_ENTRIES)
        )
        result = await session_execute(stmt, session)
        return [CategoryDTO.model_validate(c, from_attributes=True) for c in result.scalars().all()]
```

#### 2.2 Updated ItemRepository (`repositories/item.py`)

```python
from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from db import session_execute
from models.buyItem import BuyItem
from models.item import Item, ItemDTO


class ItemRepository:

    @staticmethod
    async def get_available_qty(category_id: int, session: Session | AsyncSession) -> int:
        """Get count of unsold items for a product category."""
        stmt = (
            select(func.count())
            .select_from(Item)
            .where(Item.category_id == category_id, Item.is_sold == False)
        )
        result = await session_execute(stmt, session)
        return result.scalar()

    @staticmethod
    async def get_purchased_items(category_id: int, quantity: int, session: Session | AsyncSession) -> list[ItemDTO]:
        """Get N unsold items from a product category."""
        stmt = (
            select(Item)
            .where(Item.category_id == category_id, Item.is_sold == False)
            .limit(quantity)
        )
        result = await session_execute(stmt, session)
        return [ItemDTO.model_validate(item, from_attributes=True) for item in result.scalars().all()]

    @staticmethod
    async def update(item_dto_list: list[ItemDTO], session: Session | AsyncSession):
        for item in item_dto_list:
            stmt = update(Item).where(Item.id == item.id).values(**item.model_dump(exclude_none=True))
            await session_execute(stmt, session)

    @staticmethod
    async def get_by_id(item_id: int, session: Session | AsyncSession) -> ItemDTO:
        stmt = select(Item).where(Item.id == item_id)
        result = await session_execute(stmt, session)
        return ItemDTO.model_validate(result.scalar(), from_attributes=True)

    @staticmethod
    async def get_by_buy_id(buy_id: int, session: Session | AsyncSession) -> list[ItemDTO]:
        stmt = (
            select(Item)
            .join(BuyItem, BuyItem.item_id == Item.id)
            .where(BuyItem.buy_id == buy_id)
        )
        result = await session_execute(stmt, session)
        return [ItemDTO.model_validate(item, from_attributes=True) for item in result.scalars().all()]

    @staticmethod
    async def set_not_new(session: Session | AsyncSession):
        stmt = update(Item).values(is_new=False)
        await session_execute(stmt, session)

    @staticmethod
    async def delete_unsold_by_category_id(category_id: int, session: Session | AsyncSession):
        stmt = delete(Item).where(Item.category_id == category_id, Item.is_sold == False)
        await session_execute(stmt, session)

    @staticmethod
    async def add_many(items: list[ItemDTO], session: Session | AsyncSession):
        items = [Item(**item.model_dump(exclude_none=True)) for item in items]
        session.add_all(items)

    @staticmethod
    async def get_new(session: Session | AsyncSession) -> list[ItemDTO]:
        stmt = select(Item).where(Item.is_new == True)
        result = await session_execute(stmt, session)
        return [ItemDTO.model_validate(item, from_attributes=True) for item in result.scalars().all()]

    @staticmethod
    async def get_in_stock(session: Session | AsyncSession) -> list[ItemDTO]:
        stmt = select(Item).where(Item.is_sold == False)
        result = await session_execute(stmt, session)
        return [ItemDTO.model_validate(item, from_attributes=True) for item in result.scalars().all()]
```

---

### Phase 3: Callbacks

#### 3.1 Updated AllCategoriesCallback (`callbacks.py`)

```python
class AllCategoriesCallback(BaseCallback, prefix="all_categories"):
    category_id: int      # Current category being viewed
    quantity: int         # Selected quantity (for products)
    confirmation: bool    # Purchase confirmation
    page: int             # Pagination

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
```

**Note:** Removed `subcategory_id` and `price` - no longer needed since:
- Navigation is now just `category_id` (which can be at any depth)
- Price comes from the product category itself

---

### Phase 4: Handler Rewrite

#### 4.1 Category Browsing Handler (`handlers/user/all_categories.py`)

The navigation becomes **dynamic based on `is_product` flag**:

```python
from aiogram import types, Router, F
from aiogram.types import Message, CallbackQuery, InputMediaPhoto
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from callbacks import AllCategoriesCallback
from enums.bot_entity import BotEntity
from services.cart import CartService
from services.category import CategoryService
from utils.custom_filters import IsUserExistFilter
from utils.localizator import Localizator

all_categories_router = Router()


@all_categories_router.message(F.text == Localizator.get_text(BotEntity.USER, "all_categories"),
                               IsUserExistFilter())
async def all_categories_text_message(message: types.message, session: AsyncSession | Session):
    await show_categories(message=message, session=session, parent_id=None, page=0)


async def show_categories(message: Message | CallbackQuery, session: AsyncSession | Session,
                          parent_id: int | None, page: int):
    """Show categories at given level (root if parent_id is None)."""
    msg, kb_builder, photo_file_id = await CategoryService.get_category_buttons(parent_id, page, session)

    if isinstance(message, Message):
        if photo_file_id:
            await message.answer_photo(photo=photo_file_id, caption=msg, reply_markup=kb_builder.as_markup())
        else:
            await message.answer(msg, reply_markup=kb_builder.as_markup())
    else:
        callback = message
        if photo_file_id:
            try:
                await callback.message.edit_media(
                    InputMediaPhoto(media=photo_file_id, caption=msg),
                    reply_markup=kb_builder.as_markup()
                )
            except:
                await callback.message.delete()
                await callback.message.answer_photo(photo=photo_file_id, caption=msg,
                                                     reply_markup=kb_builder.as_markup())
        else:
            try:
                await callback.message.edit_text(msg, reply_markup=kb_builder.as_markup())
            except:
                await callback.message.delete()
                await callback.message.answer(msg, reply_markup=kb_builder.as_markup())


async def show_product(callback: CallbackQuery, session: AsyncSession | Session, category_id: int):
    """Show product details with quantity selector."""
    msg, kb_builder, photo_file_id = await CategoryService.get_product_view(category_id, session)

    if photo_file_id:
        try:
            await callback.message.edit_media(
                InputMediaPhoto(media=photo_file_id, caption=msg),
                reply_markup=kb_builder.as_markup()
            )
        except:
            await callback.message.delete()
            await callback.message.answer_photo(photo=photo_file_id, caption=msg,
                                                 reply_markup=kb_builder.as_markup())
    else:
        await callback.message.edit_text(msg, reply_markup=kb_builder.as_markup())


async def add_to_cart_confirmation(callback: CallbackQuery, session: AsyncSession | Session):
    """Show cart confirmation."""
    msg, kb_builder = await CategoryService.get_add_to_cart_buttons(callback, session)
    await callback.message.edit_text(text=msg, reply_markup=kb_builder.as_markup())


async def add_to_cart(callback: CallbackQuery, session: AsyncSession | Session):
    """Add to cart."""
    await CartService.add_to_cart(callback, session)
    await callback.message.edit_text(text=Localizator.get_text(BotEntity.USER, "item_added_to_cart"))


@all_categories_router.callback_query(AllCategoriesCallback.filter(), IsUserExistFilter())
async def navigate_categories(callback: CallbackQuery, callback_data: AllCategoriesCallback,
                              session: AsyncSession | Session):
    """Dynamic navigation handler."""

    # Level 0: Show root categories or children
    if callback_data.level == 0:
        parent_id = callback_data.category_id if callback_data.category_id != -1 else None
        await show_categories(message=callback, session=session, parent_id=parent_id, page=callback_data.page)
        return

    # Check if selected category is a product
    category = await CategoryService.get_by_id(callback_data.category_id, session)

    if category.is_product:
        if callback_data.level == 1:
            # Show product details with quantity selector
            await show_product(callback, session, callback_data.category_id)
        elif callback_data.level == 2:
            # Quantity selected, show confirmation
            await add_to_cart_confirmation(callback, session)
        elif callback_data.level == 3:
            # Confirmed, add to cart
            await add_to_cart(callback, session)
    else:
        # Not a product, show children
        await show_categories(message=callback, session=session,
                              parent_id=callback_data.category_id, page=callback_data.page)
```

---

### Phase 5: Services Layer

#### 5.1 CategoryService (`services/category.py`)

```python
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from callbacks import AllCategoriesCallback
from enums.bot_entity import BotEntity
from handlers.common.common import add_pagination_buttons
from repositories.category import CategoryRepository
from utils.localizator import Localizator


class CategoryService:

    @staticmethod
    async def get_by_id(category_id: int, session: AsyncSession | Session):
        return await CategoryRepository.get_by_id(category_id, session)

    @staticmethod
    async def get_category_buttons(parent_id: int | None, page: int,
                                    session: AsyncSession | Session) -> tuple[str, InlineKeyboardBuilder, str | None]:
        """
        Get category buttons for browsing.
        Returns: (message_text, keyboard_builder, photo_file_id)
        """
        kb_builder = InlineKeyboardBuilder()
        photo_file_id = None

        if parent_id is None:
            # Root level
            categories = await CategoryRepository.get_roots(page, session)
            max_page_coro = CategoryRepository.get_maximum_page_roots(session)
            back_button = None
            title = Localizator.get_text(BotEntity.USER, "all_categories")
        else:
            # Child level
            categories = await CategoryRepository.get_children(parent_id, page, session)
            parent = await CategoryRepository.get_by_id(parent_id, session)
            max_page_coro = CategoryRepository.get_maximum_page_children(parent_id, session)

            # Back button goes to parent's parent
            if parent.parent_id is None:
                back_button = AllCategoriesCallback.create(level=0, category_id=-1)
            else:
                back_button = AllCategoriesCallback.create(level=0, category_id=parent.parent_id)

            # Get breadcrumb for title
            breadcrumb = await CategoryRepository.get_breadcrumb(parent_id, session)
            title = " > ".join([c.name for c in breadcrumb])

            # If parent has photo, show it
            photo_file_id = parent.photo_file_id

        for category in categories:
            if category.is_product:
                # Product - show price and quantity
                qty = await CategoryRepository.get_available_qty(category.id, session)
                btn_text = Localizator.get_text(BotEntity.USER, "product_button").format(
                    product_name=category.name,
                    price=category.price,
                    available_quantity=qty,
                    currency_sym=Localizator.get_currency_symbol()
                )
                cb = AllCategoriesCallback.create(level=1, category_id=category.id)
            else:
                # Category - just show name
                btn_text = category.name
                cb = AllCategoriesCallback.create(level=0, category_id=category.id)

            kb_builder.button(text=btn_text, callback_data=cb)

        kb_builder.adjust(1 if any(c.is_product for c in categories) else 2)

        # Add pagination
        current_cb = AllCategoriesCallback.create(level=0, category_id=parent_id or -1, page=page)
        kb_builder = await add_pagination_buttons(kb_builder, current_cb, max_page_coro,
                                                   back_button.pack() if back_button else None)

        if len(categories) == 0:
            return Localizator.get_text(BotEntity.USER, "no_categories"), kb_builder, None

        return title, kb_builder, photo_file_id

    @staticmethod
    async def get_product_view(category_id: int, session: AsyncSession | Session) -> tuple[str, InlineKeyboardBuilder, str | None]:
        """
        Get product view with quantity selector.
        """
        product = await CategoryRepository.get_by_id(category_id, session)
        available_qty = await CategoryRepository.get_available_qty(category_id, session)
        breadcrumb = await CategoryRepository.get_breadcrumb(category_id, session)

        message_text = Localizator.get_text(BotEntity.USER, "select_quantity_product").format(
            breadcrumb=" > ".join([c.name for c in breadcrumb]),
            price=product.price,
            description=product.description or "",
            quantity=available_qty,
            currency_sym=Localizator.get_currency_symbol()
        )

        kb_builder = InlineKeyboardBuilder()
        for i in range(1, min(11, available_qty + 1)):
            kb_builder.button(
                text=str(i),
                callback_data=AllCategoriesCallback.create(level=2, category_id=category_id, quantity=i)
            )
        kb_builder.adjust(3)

        # Back button
        back_cb = AllCategoriesCallback.create(level=0, category_id=product.parent_id or -1)
        kb_builder.row(back_cb.get_back_button())

        return message_text, kb_builder, product.photo_file_id

    @staticmethod
    async def get_add_to_cart_buttons(callback: CallbackQuery, session: AsyncSession | Session) -> tuple[str, InlineKeyboardBuilder]:
        """
        Get add to cart confirmation buttons.
        """
        unpacked_cb = AllCategoriesCallback.unpack(callback.data)
        product = await CategoryRepository.get_by_id(unpacked_cb.category_id, session)
        breadcrumb = await CategoryRepository.get_breadcrumb(unpacked_cb.category_id, session)

        message_text = Localizator.get_text(BotEntity.USER, "buy_confirmation_product").format(
            breadcrumb=" > ".join([c.name for c in breadcrumb]),
            price=product.price,
            description=product.description or "",
            quantity=unpacked_cb.quantity,
            total_price=product.price * unpacked_cb.quantity,
            currency_sym=Localizator.get_currency_symbol()
        )

        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(
            text=Localizator.get_text(BotEntity.COMMON, "confirm"),
            callback_data=AllCategoriesCallback.create(
                level=3,
                category_id=unpacked_cb.category_id,
                quantity=unpacked_cb.quantity,
                confirmation=True
            )
        )
        kb_builder.button(
            text=Localizator.get_text(BotEntity.COMMON, "cancel"),
            callback_data=AllCategoriesCallback.create(level=0, category_id=product.parent_id or -1)
        )

        back_cb = AllCategoriesCallback.create(level=1, category_id=unpacked_cb.category_id)
        kb_builder.row(back_cb.get_back_button())

        return message_text, kb_builder
```

---

### Phase 6: Item Import Update

#### 6.1 New Import Format

**TXT Format (using path separator `>`):**
```
Tea>Green>Tea Widow;Our signature blend;50.0;location_data_here
Tea>Green>Tea Widow;Our signature blend;50.0;another_location_data
Tea>Black>Dark Roast;Rich dark tea;75.0;location_data_here
```

**JSON Format:**
```json
[
  {
    "path": ["Tea", "Green", "Tea Widow"],
    "description": "Our signature blend",
    "price": 50.0,
    "private_data": "location_data_here"
  },
  {
    "path": ["Tea", "Green", "Tea Widow"],
    "description": "Our signature blend",
    "price": 50.0,
    "private_data": "another_location_data"
  }
]
```

#### 6.2 Updated ItemService (`services/item.py`)

```python
from json import load
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from callbacks import AddType
from db import session_commit
from enums.bot_entity import BotEntity
from models.item import ItemDTO
from repositories.category import CategoryRepository
from repositories.item import ItemRepository
from utils.localizator import Localizator


class ItemService:

    @staticmethod
    async def get_new(session: AsyncSession | Session) -> list[ItemDTO]:
        return await ItemRepository.get_new(session)

    @staticmethod
    async def get_in_stock_items(session: AsyncSession | Session):
        return await ItemRepository.get_in_stock(session)

    @staticmethod
    async def parse_items_json(path_to_file: str, session: AsyncSession | Session):
        with open(path_to_file, 'r', encoding='utf-8') as file:
            items = load(file)
            items_list = []
            for item in items:
                # Get or create the full category path
                category = await CategoryRepository.get_or_create_path(
                    path=item['path'],
                    is_last_product=True,
                    price=item['price'],
                    description=item['description'],
                    session=session
                )
                items_list.append(ItemDTO(
                    category_id=category.id,
                    private_data=item['private_data']
                ))
            return items_list

    @staticmethod
    async def parse_items_txt(path_to_file: str, session: AsyncSession | Session):
        with open(path_to_file, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            items_list = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                # Format: Path>Path>Product;Description;Price;PrivateData
                path_part, description, price, private_data = line.split(';')
                path = [p.strip() for p in path_part.split('>')]

                category = await CategoryRepository.get_or_create_path(
                    path=path,
                    is_last_product=True,
                    price=float(price),
                    description=description,
                    session=session
                )
                items_list.append(ItemDTO(
                    category_id=category.id,
                    private_data=private_data
                ))
            return items_list

    @staticmethod
    async def add_items(path_to_file: str, add_type: AddType, session: AsyncSession | Session) -> str:
        try:
            items = []
            if add_type == AddType.JSON:
                items += await ItemService.parse_items_json(path_to_file, session)
            else:
                items += await ItemService.parse_items_txt(path_to_file, session)
            await ItemRepository.add_many(items, session)
            await session_commit(session)
            return Localizator.get_text(BotEntity.ADMIN, "add_items_success").format(adding_result=len(items))
        except Exception as e:
            return Localizator.get_text(BotEntity.ADMIN, "add_items_err").format(adding_result=e)
        finally:
            Path(path_to_file).unlink(missing_ok=True)
```

---

### Phase 7: Admin Photo Upload

#### 7.1 Add Photo Upload Handler

Add new states and handlers for uploading product photos:

```python
# In handlers/admin/constants.py
class AdminInventoryManagementStates(StatesGroup):
    document = State()
    photo_upload = State()  # NEW


# In handlers/admin/inventory_management.py - add photo upload handler
@inventory_management.message(AdminIdFilter(), F.photo, StateFilter(AdminInventoryManagementStates.photo_upload))
async def upload_product_photo(message: Message, state: FSMContext, session: AsyncSession | Session):
    state_data = await state.get_data()
    category_id = state_data['category_id']

    # Get the largest photo
    photo = message.photo[-1]
    file_id = photo.file_id

    await CategoryRepository.update_photo(category_id, file_id, session)
    await session_commit(session)
    await state.clear()

    await message.answer(Localizator.get_text(BotEntity.ADMIN, "photo_uploaded_success"))
```

---

### Phase 8: Localization Updates

Add new strings to `l10n/en.json`:

```json
{
  "user": {
    "product_button": "\uD83D\uDCE6 {product_name}| {currency_sym}{price:.2f} | Qty: {available_quantity}",
    "select_quantity_product": "\uD83D\uDED2 <b>{breadcrumb}</b>\n\n<b>Price:</b> {currency_sym}{price:.2f}\n<b>Description:</b> {description}\n<b>Available:</b> {quantity}",
    "buy_confirmation_product": "\uD83D\uDED2 <b>{breadcrumb}</b>\n\n<b>Price:</b> {currency_sym}{price:.2f}\n<b>Description:</b> {description}\n<b>Quantity:</b> {quantity}\n<b>Total:</b> {currency_sym}{total_price:.2f}"
  },
  "admin": {
    "upload_product_photo": "\uD83D\uDCF7 <b>Send a photo for this product or \"cancel\" to skip:</b>",
    "photo_uploaded_success": "\u2705 <b>Product photo uploaded successfully!</b>",
    "manage_product_photos": "\uD83D\uDDBC\uFE0F Manage Product Photos",
    "add_items_json_msg_v2": "\uD83D\uDCC4 <b>Send .json file with new items or type \"cancel\" for cancel.</b>\nFile content example:\n<pre><code class=\"language-json\">[\n  {\n    \"path\": [\"Tea\", \"Green\", \"Tea Widow\"],\n    \"description\": \"Our signature blend\",\n    \"price\": 50.0,\n    \"private_data\": \"52.123, 13.456, photo_of_location\"\n  }\n]</code></pre>",
    "add_items_txt_msg_v2": "\uD83D\uDCC4 <b>Send .txt file with new items or type \"cancel\" for cancel.</b>\nFile content example:\n<pre><code class=\"language-txt\">Tea>Green>Tea Widow;Our signature blend;50.0;52.123, 13.456, photo_of_location\nTea>Green>Tea Widow;Our signature blend;50.0;52.789, 13.012, another_location\n</code></pre>"
  }
}
```

---

### Phase 9: Database Migration Strategy

Since no migration system exists, we need a careful approach:

#### Option A: Fresh Start (Recommended for Development)
1. Delete `data/database.db`
2. Run bot - new schema created automatically

#### Option B: Manual Migration Script (For Production)
Create `migrate_to_tree.py`:

```python
"""
Migration script: Convert old Category/Subcategory to tree structure.
Run this ONCE before starting the updated bot.
"""
import sqlite3

def migrate():
    conn = sqlite3.connect('data/database.db')
    cursor = conn.cursor()

    # 1. Backup old tables
    cursor.execute("ALTER TABLE categories RENAME TO categories_old")
    cursor.execute("ALTER TABLE subcategories RENAME TO subcategories_old")
    cursor.execute("ALTER TABLE items RENAME TO items_old")

    # 2. Create new categories table
    cursor.execute("""
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY,
            parent_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            is_product BOOLEAN NOT NULL DEFAULT 0,
            photo_file_id TEXT,
            description TEXT,
            price REAL,
            CONSTRAINT check_product_has_price CHECK (
                (is_product = 0) OR (is_product = 1 AND price > 0)
            )
        )
    """)

    # 3. Migrate categories as roots
    cursor.execute("""
        INSERT INTO categories (id, parent_id, name, is_product)
        SELECT id, NULL, name, 0 FROM categories_old
    """)

    # 4. Create subcategories as children
    # Get max category id
    cursor.execute("SELECT MAX(id) FROM categories")
    max_id = cursor.fetchone()[0] or 0

    cursor.execute("SELECT DISTINCT subcategory_id FROM items_old")
    subcats = cursor.fetchall()

    subcat_mapping = {}
    for (subcat_id,) in subcats:
        cursor.execute("SELECT name FROM subcategories_old WHERE id = ?", (subcat_id,))
        result = cursor.fetchone()
        if result:
            name = result[0]
            # Get category_id and other info from first item
            cursor.execute("""
                SELECT category_id, price, description
                FROM items_old
                WHERE subcategory_id = ?
                LIMIT 1
            """, (subcat_id,))
            item = cursor.fetchone()
            if item:
                cat_id, price, description = item
                max_id += 1
                cursor.execute("""
                    INSERT INTO categories (id, parent_id, name, is_product, description, price)
                    VALUES (?, ?, ?, 1, ?, ?)
                """, (max_id, cat_id, name, description, price))
                subcat_mapping[subcat_id] = max_id

    # 5. Create new items table
    cursor.execute("""
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
            private_data TEXT NOT NULL,
            is_sold BOOLEAN NOT NULL DEFAULT 0,
            is_new BOOLEAN NOT NULL DEFAULT 1
        )
    """)

    # 6. Migrate items
    cursor.execute("SELECT id, subcategory_id, private_data, is_sold, is_new FROM items_old")
    for item_id, subcat_id, private_data, is_sold, is_new in cursor.fetchall():
        new_cat_id = subcat_mapping.get(subcat_id)
        if new_cat_id:
            cursor.execute("""
                INSERT INTO items (id, category_id, private_data, is_sold, is_new)
                VALUES (?, ?, ?, ?, ?)
            """, (item_id, new_cat_id, private_data, is_sold, is_new))

    # 7. Update cart_items
    cursor.execute("""
        CREATE TABLE cart_items_new (
            id INTEGER PRIMARY KEY,
            cart_id INTEGER NOT NULL REFERENCES carts(id),
            category_id INTEGER NOT NULL REFERENCES categories(id),
            quantity INTEGER NOT NULL CHECK (quantity > 0)
        )
    """)

    cursor.execute("SELECT id, cart_id, subcategory_id, quantity FROM cart_items")
    for ci_id, cart_id, subcat_id, qty in cursor.fetchall():
        new_cat_id = subcat_mapping.get(subcat_id)
        if new_cat_id:
            cursor.execute("""
                INSERT INTO cart_items_new (id, cart_id, category_id, quantity)
                VALUES (?, ?, ?, ?)
            """, (ci_id, cart_id, new_cat_id, qty))

    cursor.execute("DROP TABLE cart_items")
    cursor.execute("ALTER TABLE cart_items_new RENAME TO cart_items")

    # 8. Clean up old tables
    cursor.execute("DROP TABLE items_old")
    cursor.execute("DROP TABLE categories_old")
    cursor.execute("DROP TABLE subcategories_old")

    conn.commit()
    conn.close()
    print("Migration complete!")

if __name__ == "__main__":
    migrate()
```

---

## Files to Modify/Create

### Models (5 files)
| File | Action |
|------|--------|
| `models/category.py` | **REWRITE** - Add tree structure |
| `models/subcategory.py` | **DELETE** |
| `models/item.py` | **REWRITE** - Simplify |
| `models/cartItem.py` | **MODIFY** - Remove subcategory_id |
| `db.py` | **MODIFY** - Remove subcategory import |

### Repositories (3 files)
| File | Action |
|------|--------|
| `repositories/category.py` | **REWRITE** - Tree operations |
| `repositories/subcategory.py` | **DELETE** |
| `repositories/item.py` | **REWRITE** - Simplify |

### Services (4 files)
| File | Action |
|------|--------|
| `services/category.py` | **REWRITE** - Tree navigation + photo |
| `services/subcategory.py` | **DELETE** |
| `services/item.py` | **REWRITE** - New import format |
| `services/cart.py` | **MODIFY** - Use category_id only |
| `services/notification.py` | **MODIFY** - Use breadcrumb |

### Handlers (2 files)
| File | Action |
|------|--------|
| `handlers/user/all_categories.py` | **REWRITE** - Dynamic navigation + photos |
| `handlers/admin/inventory_management.py` | **MODIFY** - Add photo upload |

### Other (3 files)
| File | Action |
|------|--------|
| `callbacks.py` | **MODIFY** - Simplify AllCategoriesCallback |
| `l10n/en.json` | **MODIFY** - Add new strings |
| `l10n/de.json` | **MODIFY** - Add new strings |

---

## Testing Checklist

- [ ] Root categories display correctly
- [ ] N-level deep navigation works
- [ ] Products show with photo, price, description
- [ ] Quantity selection works
- [ ] Add to cart works
- [ ] Checkout flow works
- [ ] Item import (JSON) works with new format
- [ ] Item import (TXT) works with new format
- [ ] Admin can upload product photos
- [ ] Admin can delete products/categories
- [ ] Purchase history shows correct data
- [ ] Notifications show breadcrumb path
- [ ] Back navigation works at all levels
- [ ] Pagination works at all levels

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Data loss during migration | Backup database before migration |
| Breaking existing carts | Clear carts before migration or migrate cart_items |
| Performance with deep trees | Add index on parent_id; limit depth in UI |
| Complex rollback | Keep old code in separate branch |

---

## Summary

This implementation provides:
1. **Unlimited category depth** via self-referential tree
2. **Flexible product marking** via `is_product` flag
3. **Image support** via `photo_file_id` stored on product categories
4. **Simplified Item model** with only unique data (`private_data`)
5. **Dynamic navigation** that adapts to tree structure
6. **Backward compatible import** (with new format)

The architecture is now truly universal and future-proof.
