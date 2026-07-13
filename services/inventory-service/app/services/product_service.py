"""Business logic for the product catalog."""
from __future__ import annotations

import uuid
from decimal import Decimal

from app.domain.models import Product
from app.repositories.category_repository import CategoryRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.supplier_repository import SupplierRepository


class DuplicateSKUError(Exception):
    pass


class DuplicateBarcodeError(Exception):
    pass


class ProductNotFoundError(Exception):
    pass


class InvalidProductReferenceError(Exception):
    """category_id or supplier_id doesn't belong to the calling business —
    same class of bug, and same fix pattern, as StockService's
    InvalidStockReferenceError (see that module for the full rationale)."""


class ProductService:
    def __init__(
        self,
        product_repo: ProductRepository,
        category_repo: CategoryRepository,
        supplier_repo: SupplierRepository,
    ):
        self._products = product_repo
        self._categories = category_repo
        self._suppliers = supplier_repo

    async def _verify_references(
        self,
        *,
        business_id: uuid.UUID,
        category_id: uuid.UUID | None,
        supplier_id: uuid.UUID | None,
    ) -> None:
        if category_id is not None:
            category = await self._categories.get_by_id(
                business_id=business_id, category_id=category_id
            )
            if category is None:
                raise InvalidProductReferenceError(
                    f"Category {category_id} not found for this business"
                )
        if supplier_id is not None:
            supplier = await self._suppliers.get_by_id(
                business_id=business_id, supplier_id=supplier_id
            )
            if supplier is None:
                raise InvalidProductReferenceError(
                    f"Supplier {supplier_id} not found for this business"
                )

    async def create_product(
        self,
        *,
        business_id: uuid.UUID,
        sku: str,
        name: str,
        unit_price: Decimal,
        cost_price: Decimal = Decimal("0"),
        barcode: str | None = None,
        category_id: uuid.UUID | None = None,
        supplier_id: uuid.UUID | None = None,
        description: str | None = None,
        unit: str = "piece",
        low_stock_threshold: Decimal = Decimal("0"),
    ) -> Product:
        await self._verify_references(
            business_id=business_id, category_id=category_id, supplier_id=supplier_id
        )

        # Pre-check for a friendly error message. The DB's UniqueConstraint
        # (business_id, sku) is still the authoritative guard against a
        # concurrent duplicate insert — this check just avoids surfacing a
        # raw IntegrityError to the API layer in the common, non-racing case.
        if await self._products.get_by_sku(business_id=business_id, sku=sku) is not None:
            raise DuplicateSKUError(f"SKU '{sku}' already exists for this business")

        if barcode and await self._products.get_by_barcode(
            business_id=business_id, barcode=barcode
        ):
            raise DuplicateBarcodeError(f"Barcode '{barcode}' already exists for this business")

        product = Product(
            business_id=business_id,
            sku=sku,
            barcode=barcode,
            name=name,
            description=description,
            unit=unit,
            cost_price=cost_price,
            unit_price=unit_price,
            low_stock_threshold=low_stock_threshold,
            category_id=category_id,
            supplier_id=supplier_id,
        )
        created = await self._products.create(product)
        await self._products.commit()
        return created

    async def get_product(self, *, business_id: uuid.UUID, product_id: uuid.UUID) -> Product:
        product = await self._products.get_by_id(business_id=business_id, product_id=product_id)
        if product is None:
            raise ProductNotFoundError(f"Product {product_id} not found")
        return product

    async def get_by_barcode(self, *, business_id: uuid.UUID, barcode: str) -> Product:
        product = await self._products.get_by_barcode(business_id=business_id, barcode=barcode)
        if product is None:
            raise ProductNotFoundError(f"No product with barcode '{barcode}'")
        return product

    async def get_products_by_ids(
        self, *, business_id: uuid.UUID, product_ids: list[uuid.UUID]
    ) -> list[Product]:
        """Batch lookup for cross-service callers (sales-service builds a
        checkout from several product_ids and needs current authoritative
        prices/names in one round trip rather than N sequential calls).
        Silently omits IDs that don't exist or belong to another business —
        the caller must check the returned count/IDs against what it asked
        for if it needs to detect missing items."""
        return await self._products.get_by_ids(business_id=business_id, product_ids=product_ids)

    async def list_products(
        self,
        *,
        business_id: uuid.UUID,
        category_id: uuid.UUID | None = None,
        is_active: bool | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Product]:
        return await self._products.list_by_business(
            business_id=business_id,
            category_id=category_id,
            is_active=is_active,
            search=search,
            limit=limit,
            offset=offset,
        )

    async def update_product(
        self,
        *,
        business_id: uuid.UUID,
        product_id: uuid.UUID,
        **fields,
    ) -> Product:
        product = await self.get_product(business_id=business_id, product_id=product_id)

        await self._verify_references(
            business_id=business_id,
            category_id=fields.get("category_id"),
            supplier_id=fields.get("supplier_id"),
        )

        new_sku = fields.get("sku")
        if new_sku and new_sku != product.sku:
            existing = await self._products.get_by_sku(business_id=business_id, sku=new_sku)
            if existing is not None and existing.id != product.id:
                raise DuplicateSKUError(f"SKU '{new_sku}' already exists for this business")

        new_barcode = fields.get("barcode")
        if new_barcode and new_barcode != product.barcode:
            existing = await self._products.get_by_barcode(
                business_id=business_id, barcode=new_barcode
            )
            if existing is not None and existing.id != product.id:
                raise DuplicateBarcodeError(
                    f"Barcode '{new_barcode}' already exists for this business"
                )

        for field, value in fields.items():
            if value is not None and hasattr(product, field):
                setattr(product, field, value)

        updated = await self._products.update(product)
        await self._products.commit()
        return updated
