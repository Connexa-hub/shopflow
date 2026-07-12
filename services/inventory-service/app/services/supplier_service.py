from __future__ import annotations

import uuid

from app.domain.models import Supplier
from app.repositories.supplier_repository import SupplierRepository


class SupplierNotFoundError(Exception):
    pass


class SupplierService:
    def __init__(self, supplier_repo: SupplierRepository):
        self._suppliers = supplier_repo

    async def create_supplier(
        self,
        *,
        business_id: uuid.UUID,
        name: str,
        phone_number: str | None = None,
        email: str | None = None,
        address: str | None = None,
    ) -> Supplier:
        supplier = Supplier(
            business_id=business_id,
            name=name,
            phone_number=phone_number,
            email=email,
            address=address,
        )
        created = await self._suppliers.create(supplier)
        await self._suppliers.commit()
        return created

    async def list_suppliers(self, *, business_id: uuid.UUID) -> list[Supplier]:
        return await self._suppliers.list_by_business(business_id=business_id)

    async def get_supplier(self, *, business_id: uuid.UUID, supplier_id: uuid.UUID) -> Supplier:
        supplier = await self._suppliers.get_by_id(
            business_id=business_id, supplier_id=supplier_id
        )
        if supplier is None:
            raise SupplierNotFoundError(f"Supplier {supplier_id} not found")
        return supplier
