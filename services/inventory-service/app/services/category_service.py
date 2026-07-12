from __future__ import annotations

import uuid

from app.domain.models import Category
from app.repositories.category_repository import CategoryRepository


class CategoryNotFoundError(Exception):
    pass


class InvalidParentCategoryError(Exception):
    pass


class CategoryService:
    def __init__(self, category_repo: CategoryRepository):
        self._categories = category_repo

    async def create_category(
        self, *, business_id: uuid.UUID, name: str, parent_id: uuid.UUID | None = None
    ) -> Category:
        if parent_id is not None:
            parent = await self._categories.get_by_id(
                business_id=business_id, category_id=parent_id
            )
            if parent is None:
                raise InvalidParentCategoryError(
                    "Parent category does not exist for this business"
                )

        category = Category(business_id=business_id, name=name, parent_id=parent_id)
        created = await self._categories.create(category)
        await self._categories.commit()
        return created

    async def list_categories(self, *, business_id: uuid.UUID) -> list[Category]:
        return await self._categories.list_by_business(business_id=business_id)

    async def get_category(self, *, business_id: uuid.UUID, category_id: uuid.UUID) -> Category:
        category = await self._categories.get_by_id(
            business_id=business_id, category_id=category_id
        )
        if category is None:
            raise CategoryNotFoundError(f"Category {category_id} not found")
        return category
