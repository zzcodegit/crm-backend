"""
CRUD API для справочников + сервисные выгрузки.
"""
from __future__ import annotations

from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import re
import io
import json
import zipfile
from datetime import datetime, timezone
from uuid import uuid4
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen, Request

from database import get_db
from models import (
    Organization,
    Department,
    Warehouse,
    Author,
    Product,
    ProductCharacteristic,
    VatRate,
    OrderStatus,
    Priority,
    ExpenseArticle,
    TakenReason,
    TakenSource,
    DebtReason,
    Color,
    Manufacturer,
    Country,
    Feature,
    Coefficient,
    PricelistGroup,
    PricelistItem,
    PricelistRxGroup,
    PricelistRxItem,
    PricelistMklGroup,
    PricelistMklItem,
    PricelistPublicationJob,
    CustomFieldDefinition,
    CustomFieldOption,
)
from schemas import (
    OrganizationResponse,
    DepartmentResponse,
    WarehouseResponse,
    WarehouseCreate,
    WarehouseUpdate,
    AuthorResponse,
    ProductResponse,
    ProductCreate,
    ProductUpdate,
    ProductCharacteristicResponse,
    ProductCharacteristicCreate,
    ProductCharacteristicUpdate,
    VatRateResponse,
    RefResponse,
    RefCreate,
    RefUpdate,
    CountryResponse,
    ManufacturerResponse,
    ManufacturerCreate,
    ManufacturerUpdate,
    FeatureResponse,
    FeatureCreate,
    FeatureUpdate,
    PricelistGroupResponse,
    PricelistGroupCreate,
    PricelistGroupUpdate,
    PricelistItemResponse,
    PricelistItemCreate,
    PricelistBulkCreateRequest,
    PricelistItemUpdate,
    BarcodeEntry,
    BarcodeSection,
    CustomFieldDefinitionResponse,
    CustomFieldDefinitionCreate,
    CustomFieldDefinitionUpdate,
    CustomFieldOptionResponse,
    CustomFieldOptionCreate,
    CustomFieldOptionUpdate,
    PricelistPublicationJobResponse,
    PricelistPublicationJobCreate,
    PricelistPublicationBatchAssign,
)
from deps import get_admin_user, get_current_user, is_admin
from models import User, Group

router = APIRouter(tags=["references"])

MANAGER_GROUP_NAME = "Менеджер"
UPLOADS_DIR = Path("/home/crm-backend/uploads")


# Organizations
@router.get("/api/ref/organizations", response_model=list[OrganizationResponse])
def list_organizations(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    return db.query(Organization).order_by(Organization.name).all()


@router.post("/api/ref/organizations", response_model=OrganizationResponse, status_code=201)
def create_organization(data: RefCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = Organization(name=data.name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/api/ref/organizations/{item_id}", response_model=OrganizationResponse)
def get_organization(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Organization).filter(Organization.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.patch("/api/ref/organizations/{item_id}", response_model=OrganizationResponse)
def update_organization(item_id: int, data: RefUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Organization).filter(Organization.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    obj.name = data.name
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/organizations/{item_id}", status_code=204)
def delete_organization(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Organization).filter(Organization.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# Departments
@router.get("/api/ref/departments", response_model=list[DepartmentResponse])
def list_departments(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    return db.query(Department).order_by(Department.name).all()


@router.post("/api/ref/departments", response_model=DepartmentResponse, status_code=201)
def create_department(data: RefCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = Department(name=data.name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/api/ref/departments/{item_id}", response_model=DepartmentResponse)
def get_department(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Department).filter(Department.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.patch("/api/ref/departments/{item_id}", response_model=DepartmentResponse)
def update_department(item_id: int, data: RefUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Department).filter(Department.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    obj.name = data.name
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/departments/{item_id}", status_code=204)
def delete_department(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Department).filter(Department.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# Managers (для выбора менеджера склада)
@router.get("/api/ref/managers", response_model=list)
def list_managers(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    """Пользователи из группы «Менеджер» для назначения менеджером склада."""
    from sqlalchemy.orm import joinedload
    managers = db.query(User).join(User.groups).filter(Group.name == MANAGER_GROUP_NAME).options(joinedload(User.groups)).order_by(User.last_name, User.first_name).all()
    return [{"id": u.id, "username": u.username, "first_name": u.first_name, "last_name": u.last_name, "display_name": _user_display_name(u)} for u in managers]


def _user_display_name(u) -> str:
    parts = [u.first_name, u.last_name]
    name = " ".join(p for p in parts if p and str(p).strip())
    return name or u.username or str(u.id)


# Warehouses
def _warehouse_query(db):
    from sqlalchemy.orm import joinedload
    return (
        db.query(Warehouse)
        .options(joinedload(Warehouse.organization_rel), joinedload(Warehouse.manager_rel))
        .order_by(Warehouse.sort_order.asc(), Warehouse.name.asc())
    )


@router.get("/api/ref/warehouses", response_model=list[WarehouseResponse])
def list_warehouses(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _warehouse_query(db).all()


@router.post("/api/ref/warehouses", response_model=WarehouseResponse, status_code=201)
def create_warehouse(data: WarehouseCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    oh = data.opening_hours.model_dump(mode="json") if data.opening_hours is not None else None
    obj = Warehouse(
        name=data.name,
        organization_id=data.organization_id,
        manager_id=data.manager_id,
        sort_order=int(data.sort_order or 0),
        opening_hours=oh,
        hide_in_reports=bool(data.hide_in_reports),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    from sqlalchemy.orm import joinedload
    obj = db.query(Warehouse).options(joinedload(Warehouse.organization_rel), joinedload(Warehouse.manager_rel)).filter(Warehouse.id == obj.id).first()
    return obj


@router.get("/api/ref/warehouses/{item_id}", response_model=WarehouseResponse)
def get_warehouse(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = _warehouse_query(db).filter(Warehouse.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.patch("/api/ref/warehouses/{item_id}", response_model=WarehouseResponse)
def update_warehouse(item_id: int, data: WarehouseUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Warehouse).filter(Warehouse.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    if data.name is not None:
        obj.name = data.name
    if "organization_id" in data.model_fields_set:
        obj.organization_id = data.organization_id
    if data.manager_id is not None:
        obj.manager_id = data.manager_id
    if "sort_order" in data.model_fields_set:
        obj.sort_order = int(data.sort_order or 0)
    if "opening_hours" in data.model_fields_set:
        obj.opening_hours = (
            data.opening_hours.model_dump(mode="json") if data.opening_hours is not None else None
        )
    if "hide_in_reports" in data.model_fields_set:
        obj.hide_in_reports = bool(data.hide_in_reports)
    db.commit()
    db.refresh(obj)
    obj = _warehouse_query(db).filter(Warehouse.id == item_id).first()
    return obj


@router.delete("/api/ref/warehouses/{item_id}", status_code=204)
def delete_warehouse(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Warehouse).filter(Warehouse.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# Authors
@router.get("/api/ref/authors", response_model=list[AuthorResponse])
def list_authors(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    return db.query(Author).order_by(Author.name).all()


@router.post("/api/ref/authors", response_model=AuthorResponse, status_code=201)
def create_author(data: RefCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = Author(name=data.name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/api/ref/authors/{item_id}", response_model=AuthorResponse)
def get_author(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Author).filter(Author.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.patch("/api/ref/authors/{item_id}", response_model=AuthorResponse)
def update_author(item_id: int, data: RefUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Author).filter(Author.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    obj.name = data.name
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/authors/{item_id}", status_code=204)
def delete_author(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Author).filter(Author.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# Products
@router.get("/api/ref/products", response_model=list[ProductResponse])
def list_products(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Product).order_by(Product.name).all()


@router.post("/api/ref/products", response_model=ProductResponse, status_code=201)
def create_product(data: ProductCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = Product(name=data.name, code=data.code)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/api/ref/products/{item_id}", response_model=ProductResponse)
def get_product(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Product).filter(Product.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.patch("/api/ref/products/{item_id}", response_model=ProductResponse)
def update_product(item_id: int, data: ProductUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Product).filter(Product.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    if data.name is not None:
        obj.name = data.name
    if data.code is not None:
        obj.code = data.code
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/products/{item_id}", status_code=204)
def delete_product(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Product).filter(Product.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# Product characteristics
@router.get("/api/ref/product-characteristics", response_model=list[ProductCharacteristicResponse])
def list_characteristics(product_id: int | None = Query(None), db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    q = db.query(ProductCharacteristic).order_by(ProductCharacteristic.name)
    if product_id is not None:
        q = q.filter(ProductCharacteristic.product_id == product_id)
    return q.all()


@router.post("/api/ref/product-characteristics", response_model=ProductCharacteristicResponse, status_code=201)
def create_characteristic(data: ProductCharacteristicCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = ProductCharacteristic(product_id=data.product_id, name=data.name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.patch("/api/ref/product-characteristics/{item_id}", response_model=ProductCharacteristicResponse)
def update_characteristic(item_id: int, data: ProductCharacteristicUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(ProductCharacteristic).filter(ProductCharacteristic.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    if data.name is not None:
        obj.name = data.name
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/product-characteristics/{item_id}", status_code=204)
def delete_characteristic(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(ProductCharacteristic).filter(ProductCharacteristic.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# VAT rates
@router.get("/api/ref/vat-rates", response_model=list[VatRateResponse])
def list_vat_rates(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    return db.query(VatRate).order_by(VatRate.name).all()


@router.post("/api/ref/vat-rates", response_model=VatRateResponse, status_code=201)
def create_vat_rate(data: RefCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = VatRate(name=data.name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/api/ref/vat-rates/{item_id}", response_model=VatRateResponse)
def get_vat_rate(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(VatRate).filter(VatRate.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.patch("/api/ref/vat-rates/{item_id}", response_model=VatRateResponse)
def update_vat_rate(item_id: int, data: RefUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(VatRate).filter(VatRate.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    obj.name = data.name
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/vat-rates/{item_id}", status_code=204)
def delete_vat_rate(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(VatRate).filter(VatRate.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# Order statuses
@router.get("/api/ref/order-statuses", response_model=list)
def list_order_statuses(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    return db.query(OrderStatus).order_by(OrderStatus.name).all()


@router.post("/api/ref/order-statuses", response_model=RefResponse, status_code=201)
def create_order_status(data: RefCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = OrderStatus(name=data.name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/api/ref/order-statuses/{item_id}", response_model=RefResponse)
def get_order_status(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(OrderStatus).filter(OrderStatus.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.patch("/api/ref/order-statuses/{item_id}", response_model=RefResponse)
def update_order_status(item_id: int, data: RefUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(OrderStatus).filter(OrderStatus.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    obj.name = data.name
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/order-statuses/{item_id}", status_code=204)
def delete_order_status(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(OrderStatus).filter(OrderStatus.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# Priorities
@router.get("/api/ref/priorities", response_model=list)
def list_priorities(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    return db.query(Priority).order_by(Priority.name).all()


@router.post("/api/ref/priorities", response_model=RefResponse, status_code=201)
def create_priority(data: RefCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = Priority(name=data.name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/api/ref/priorities/{item_id}", response_model=RefResponse)
def get_priority(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Priority).filter(Priority.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.patch("/api/ref/priorities/{item_id}", response_model=RefResponse)
def update_priority(item_id: int, data: RefUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Priority).filter(Priority.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    obj.name = data.name
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/priorities/{item_id}", status_code=204)
def delete_priority(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Priority).filter(Priority.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# Статьи расходов (отчёты консультантов; список — всем авторизованным)
@router.get("/api/ref/expense-articles", response_model=list[RefResponse])
def list_expense_articles(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(ExpenseArticle).order_by(ExpenseArticle.name).all()


@router.post("/api/ref/expense-articles", response_model=RefResponse, status_code=201)
def create_expense_article(data: RefCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = ExpenseArticle(name=data.name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/api/ref/expense-articles/{item_id}", response_model=RefResponse)
def get_expense_article(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(ExpenseArticle).filter(ExpenseArticle.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.patch("/api/ref/expense-articles/{item_id}", response_model=RefResponse)
def update_expense_article(item_id: int, data: RefUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(ExpenseArticle).filter(ExpenseArticle.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    obj.name = data.name
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/expense-articles/{item_id}", status_code=204)
def delete_expense_article(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(ExpenseArticle).filter(ExpenseArticle.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# «Взято за что» (справочник; список — всем авторизованным)
@router.get("/api/ref/taken-reasons", response_model=list[RefResponse])
def list_taken_reasons(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(TakenReason).order_by(TakenReason.name).all()


@router.post("/api/ref/taken-reasons", response_model=RefResponse, status_code=201)
def create_taken_reason(data: RefCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = TakenReason(name=data.name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/api/ref/taken-reasons/{item_id}", response_model=RefResponse)
def get_taken_reason(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(TakenReason).filter(TakenReason.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.patch("/api/ref/taken-reasons/{item_id}", response_model=RefResponse)
def update_taken_reason(item_id: int, data: RefUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(TakenReason).filter(TakenReason.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    obj.name = data.name
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/taken-reasons/{item_id}", status_code=204)
def delete_taken_reason(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(TakenReason).filter(TakenReason.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# «Долг за что» (справочник; список — всем авторизованным)
@router.get("/api/ref/debt-reasons", response_model=list[RefResponse])
def list_debt_reasons(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(DebtReason).order_by(DebtReason.name).all()


@router.post("/api/ref/debt-reasons", response_model=RefResponse, status_code=201)
def create_debt_reason(data: RefCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = DebtReason(name=data.name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/api/ref/debt-reasons/{item_id}", response_model=RefResponse)
def get_debt_reason(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(DebtReason).filter(DebtReason.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.patch("/api/ref/debt-reasons/{item_id}", response_model=RefResponse)
def update_debt_reason(item_id: int, data: RefUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(DebtReason).filter(DebtReason.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    obj.name = data.name
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/debt-reasons/{item_id}", status_code=204)
def delete_debt_reason(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(DebtReason).filter(DebtReason.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# «Откуда взято» (справочник; список — всем авторизованным)
@router.get("/api/ref/taken-sources", response_model=list[RefResponse])
def list_taken_sources(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(TakenSource).order_by(TakenSource.name).all()


@router.post("/api/ref/taken-sources", response_model=RefResponse, status_code=201)
def create_taken_source(data: RefCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = TakenSource(name=data.name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/api/ref/taken-sources/{item_id}", response_model=RefResponse)
def get_taken_source(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(TakenSource).filter(TakenSource.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.patch("/api/ref/taken-sources/{item_id}", response_model=RefResponse)
def update_taken_source(item_id: int, data: RefUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(TakenSource).filter(TakenSource.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    obj.name = data.name
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/taken-sources/{item_id}", status_code=204)
def delete_taken_source(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(TakenSource).filter(TakenSource.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# Colors (справочник цветов для особенностей линз)
@router.get("/api/ref/colors", response_model=list[RefResponse])
def list_colors(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Color).order_by(Color.name).all()


@router.post("/api/ref/colors", response_model=RefResponse, status_code=201)
def create_color(data: RefCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    name = data.name.strip()
    existing = db.query(Color).filter(Color.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Цвет с таким названием уже есть")
    obj = Color(name=name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/api/ref/colors/{item_id}", response_model=RefResponse)
def get_color(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Color).filter(Color.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.patch("/api/ref/colors/{item_id}", response_model=RefResponse)
def update_color(item_id: int, data: RefUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Color).filter(Color.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    obj.name = data.name.strip()
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/colors/{item_id}", status_code=204)
def delete_color(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Color).filter(Color.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# Countries
@router.get("/api/ref/countries", response_model=list[CountryResponse])
def list_countries(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    return db.query(Country).order_by(Country.name).all()


@router.post("/api/ref/countries", response_model=CountryResponse, status_code=201)
def create_country(data: RefCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = Country(name=data.name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# Manufacturers
@router.get("/api/ref/manufacturers", response_model=list[ManufacturerResponse])
def list_manufacturers(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(Manufacturer).order_by(Manufacturer.name).all()


@router.post("/api/ref/manufacturers", response_model=ManufacturerResponse, status_code=201)
def create_manufacturer(data: ManufacturerCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = Manufacturer(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/api/ref/manufacturers/{item_id}", response_model=ManufacturerResponse)
def get_manufacturer(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    obj = db.query(Manufacturer).filter(Manufacturer.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.patch("/api/ref/manufacturers/{item_id}", response_model=ManufacturerResponse)
def update_manufacturer(item_id: int, data: ManufacturerUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Manufacturer).filter(Manufacturer.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)
    
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/manufacturers/{item_id}", status_code=204)
def delete_manufacturer(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Manufacturer).filter(Manufacturer.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.query(PricelistItem).filter(PricelistItem.manufacturer_id == item_id).update(
        {PricelistItem.manufacturer_id: None},
        synchronize_session=False,
    )
    db.delete(obj)
    db.commit()
    return None


# Custom fields for pricelist
ALLOWED_CUSTOM_FIELD_TYPES = {"string", "string_multi", "select", "multi_select", "checkbox", "reference"}


def _slug_from_label(value: str) -> str:
    # Keep only latin/digits/underscore; convert spaces and punctuation to underscore.
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug


def _build_unique_code(db: Session, preferred: str) -> str:
    base = preferred or "custom_field"
    candidate = base
    idx = 2
    while db.query(CustomFieldDefinition).filter(CustomFieldDefinition.code == candidate).first():
        candidate = f"{base}_{idx}"
        idx += 1
    return candidate


def _field_to_response(field: CustomFieldDefinition) -> CustomFieldDefinitionResponse:
    options = sorted((field.options or []), key=lambda o: (o.sort_index, o.id))
    return CustomFieldDefinitionResponse(
        id=field.id,
        code=field.code,
        label=field.label,
        field_type=field.field_type,
        is_required=field.is_required,
        is_active=field.is_active,
        show_in_warehouse=field.show_in_warehouse,
        show_in_rx=field.show_in_rx,
        show_in_mkl=field.show_in_mkl,
        sort_index=field.sort_index,
        options=[CustomFieldOptionResponse.model_validate(o) for o in options if o.is_active],
    )


@router.get("/api/ref/custom-fields", response_model=list[CustomFieldDefinitionResponse])
def list_custom_fields(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    fields = db.query(CustomFieldDefinition).order_by(CustomFieldDefinition.sort_index, CustomFieldDefinition.id).all()
    return [_field_to_response(f) for f in fields if f.is_active]


@router.get("/api/ref/custom-fields/all", response_model=list[CustomFieldDefinitionResponse])
def list_custom_fields_all(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    fields = db.query(CustomFieldDefinition).order_by(CustomFieldDefinition.sort_index, CustomFieldDefinition.id).all()
    return [_field_to_response(f) for f in fields]


@router.post("/api/ref/custom-fields", response_model=CustomFieldDefinitionResponse, status_code=201)
def create_custom_field(data: CustomFieldDefinitionCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    raw_code = (data.code or "").strip().lower()
    label = data.label.strip()
    field_type = data.field_type.strip().lower()
    if not label:
        raise HTTPException(status_code=400, detail="Название обязательно")
    if field_type not in ALLOWED_CUSTOM_FIELD_TYPES:
        raise HTTPException(status_code=400, detail="Неверный тип поля")
    normalized_code = _slug_from_label(raw_code) if raw_code else _slug_from_label(label)
    code = _build_unique_code(db, normalized_code)
    obj = CustomFieldDefinition(
        code=code,
        label=label,
        field_type=field_type,
        is_required=data.is_required,
        is_active=data.is_active,
        show_in_warehouse=data.show_in_warehouse,
        show_in_rx=data.show_in_rx,
        show_in_mkl=data.show_in_mkl,
        sort_index=data.sort_index,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return _field_to_response(obj)


@router.patch("/api/ref/custom-fields/{field_id}", response_model=CustomFieldDefinitionResponse)
def update_custom_field(field_id: int, data: CustomFieldDefinitionUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(CustomFieldDefinition).filter(CustomFieldDefinition.id == field_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Поле не найдено")
    payload = data.model_dump(exclude_unset=True)
    if "field_type" in payload and payload["field_type"] is not None:
        payload["field_type"] = str(payload["field_type"]).strip().lower()
        if payload["field_type"] not in ALLOWED_CUSTOM_FIELD_TYPES:
            raise HTTPException(status_code=400, detail="Неверный тип поля")
    if "code" in payload and payload["code"] is not None:
        payload["code"] = str(payload["code"]).strip()
        exists = (
            db.query(CustomFieldDefinition)
            .filter(CustomFieldDefinition.code == payload["code"], CustomFieldDefinition.id != field_id)
            .first()
        )
        if exists:
            raise HTTPException(status_code=400, detail="Поле с таким кодом уже существует")
    if "label" in payload and payload["label"] is not None:
        payload["label"] = str(payload["label"]).strip()
    for key, value in payload.items():
        setattr(obj, key, value)
    db.commit()
    db.refresh(obj)
    return _field_to_response(obj)


@router.delete("/api/ref/custom-fields/{field_id}", status_code=204)
def delete_custom_field(field_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(CustomFieldDefinition).filter(CustomFieldDefinition.id == field_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Поле не найдено")
    db.delete(obj)
    db.commit()
    return None


@router.post("/api/ref/custom-fields/{field_id}/options", response_model=CustomFieldOptionResponse, status_code=201)
def create_custom_field_option(field_id: int, data: CustomFieldOptionCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    field = db.query(CustomFieldDefinition).filter(CustomFieldDefinition.id == field_id).first()
    if not field:
        raise HTTPException(status_code=404, detail="Поле не найдено")
    # Опции:
    # - select/reference: фиксированные варианты выбора
    # - multi_select: шаблонные подпункты (выбор нескольких + отдельный текст на каждый)
    # - string_multi: справочник строк для множественного выбора
    if field.field_type not in {"select", "reference", "multi_select", "string_multi"}:
        raise HTTPException(
            status_code=400,
            detail="Опции доступны только для списка, справочника, многострочного текста и множественных строк",
        )
    value = data.value.strip()
    if not value:
        raise HTTPException(status_code=400, detail="Значение не может быть пустым")
    obj = CustomFieldOption(field_id=field_id, value=value, sort_index=data.sort_index, is_active=data.is_active)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return CustomFieldOptionResponse.model_validate(obj)


@router.patch("/api/ref/custom-fields/{field_id}/options/{option_id}", response_model=CustomFieldOptionResponse)
def update_custom_field_option(field_id: int, option_id: int, data: CustomFieldOptionUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = (
        db.query(CustomFieldOption)
        .filter(CustomFieldOption.id == option_id, CustomFieldOption.field_id == field_id)
        .first()
    )
    if not obj:
        raise HTTPException(status_code=404, detail="Значение не найдено")
    payload = data.model_dump(exclude_unset=True)
    if "value" in payload and payload["value"] is not None:
        payload["value"] = str(payload["value"]).strip()
    for key, value in payload.items():
        setattr(obj, key, value)
    db.commit()
    db.refresh(obj)
    return CustomFieldOptionResponse.model_validate(obj)


@router.delete("/api/ref/custom-fields/{field_id}/options/{option_id}", status_code=204)
def delete_custom_field_option(field_id: int, option_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = (
        db.query(CustomFieldOption)
        .filter(CustomFieldOption.id == option_id, CustomFieldOption.field_id == field_id)
        .first()
    )
    if not obj:
        raise HTTPException(status_code=404, detail="Значение не найдено")
    db.delete(obj)
    db.commit()
    return None


# Features
def _feature_to_response(x: Feature) -> FeatureResponse:
    cl = getattr(x, "colors", None)
    if isinstance(cl, list) and len(cl) > 0:
        colors = [str(c).strip() for c in cl if c and str(c).strip()]
        color = colors[0] if colors else x.color
    else:
        color = x.color
        colors = [x.color] if x.color and str(x.color).strip() else []
    return FeatureResponse(
        id=x.id,
        name=x.name,
        icon_url=x.icon_url,
        color=color,
        colors=colors,
    )


@router.get("/api/ref/features", response_model=list[FeatureResponse])
def list_features(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return [_feature_to_response(x) for x in db.query(Feature).order_by(Feature.name).all()]


@router.post("/api/ref/features", response_model=FeatureResponse, status_code=201)
def create_feature(data: FeatureCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    colors = data.colors if data.colors else ([data.color] if data.color and data.color.strip() else [])
    colors = [c.strip() for c in colors if c and str(c).strip()]
    first_color = colors[0] if colors else data.color
    obj = Feature(
        name=data.name,
        icon_url=data.icon_url,
        color=first_color,
        colors=colors if colors else None,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return _feature_to_response(obj)


@router.get("/api/ref/features/{item_id}", response_model=FeatureResponse)
def get_feature(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Feature).filter(Feature.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return _feature_to_response(obj)


@router.patch("/api/ref/features/{item_id}", response_model=FeatureResponse)
def update_feature(item_id: int, data: FeatureUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Feature).filter(Feature.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    payload = data.model_dump(exclude_unset=True)
    if "colors" in payload:
        cl = payload["colors"] or []
        cl = [c.strip() for c in cl if c and str(c).strip()]
        payload["color"] = cl[0] if cl else None
        payload["colors"] = cl if cl else None
    for key, value in payload.items():
        setattr(obj, key, value)
    db.commit()
    db.refresh(obj)
    return _feature_to_response(obj)


@router.delete("/api/ref/features/{item_id}", status_code=204)
def delete_feature(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Feature).filter(Feature.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# Coefficients
@router.get("/api/ref/coefficients", response_model=list[RefResponse])
def list_coefficients(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    return db.query(Coefficient).order_by(Coefficient.name).all()


@router.post("/api/ref/coefficients", response_model=RefResponse, status_code=201)
def create_coefficient(data: RefCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    existing = db.query(Coefficient).filter(Coefficient.name == data.name.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Коэффициент с таким названием уже есть")
    obj = Coefficient(name=data.name.strip())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/coefficients/{item_id}", status_code=204)
def delete_coefficient(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(Coefficient).filter(Coefficient.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# Pricelist groups (группы для прайслиста: Однофокальные, Прогрессивные и т.д.)
@router.get("/api/ref/pricelist-groups", response_model=list[PricelistGroupResponse])
def list_pricelist_groups(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(PricelistGroup).order_by(PricelistGroup.sort_index, PricelistGroup.name).all()


@router.get("/api/ref/pricelist-groups/{item_id}", response_model=PricelistGroupResponse)
def get_pricelist_group(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    obj = db.query(PricelistGroup).filter(PricelistGroup.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.post("/api/ref/pricelist-groups", response_model=PricelistGroupResponse, status_code=201)
def create_pricelist_group(data: PricelistGroupCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    existing = db.query(PricelistGroup).filter(PricelistGroup.name == data.name.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Группа с таким названием уже есть")
    obj = PricelistGroup(
        name=data.name.strip(),
        sort_index=data.sort_index,
        display_properties_in_list=data.display_properties_in_list,
        display_as_tiles=data.display_as_tiles,
        tiles_per_page=max(1, min(48, int(data.tiles_per_page))),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.patch("/api/ref/pricelist-groups/{item_id}", response_model=PricelistGroupResponse)
def update_pricelist_group(item_id: int, data: PricelistGroupUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(PricelistGroup).filter(PricelistGroup.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    payload = data.model_dump(exclude_unset=True)
    if "name" in payload and payload["name"] is not None:
        new_name = payload["name"].strip()
        existing = db.query(PricelistGroup).filter(PricelistGroup.name == new_name, PricelistGroup.id != item_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Группа с таким названием уже есть")
        obj.name = new_name
    if "sort_index" in payload and payload["sort_index"] is not None:
        obj.sort_index = payload["sort_index"]
    if "display_properties_in_list" in payload and payload["display_properties_in_list"] is not None:
        obj.display_properties_in_list = bool(payload["display_properties_in_list"])
    if "display_as_tiles" in payload and payload["display_as_tiles"] is not None:
        obj.display_as_tiles = bool(payload["display_as_tiles"])
    if "tiles_per_page" in payload and payload["tiles_per_page"] is not None:
        obj.tiles_per_page = max(1, min(48, int(payload["tiles_per_page"])))
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/pricelist-groups/{item_id}", status_code=204)
def delete_pricelist_group(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(PricelistGroup).filter(PricelistGroup.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


# --- Pricelist ---

def _normalize_feature_colors(raw: dict | None) -> dict[str, list[str]]:
    """Приводит feature_colors к виду { feature_id: [color, ...] }. Поддерживает старый формат { id: "один цвет" }."""
    if not raw or not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for k, v in raw.items():
        sk = str(k).strip()
        if not sk:
            continue
        if isinstance(v, list):
            out[sk] = [str(c).strip() for c in v if c and str(c).strip()]
        elif v is not None and str(v).strip():
            out[sk] = [str(v).strip()]
    return out


def _dict_to_barcode_entry(b: dict) -> BarcodeEntry | None:
    if not isinstance(b, dict) or not b.get("code"):
        return None
    code = str(b.get("code", "")).strip()
    if not code:
        return None
    price_val = b.get("price")
    if price_val is not None:
        try:
            price_val = float(price_val)
        except (TypeError, ValueError):
            price_val = None
    desc = b.get("description")
    desc = str(desc).strip() if desc else None
    return BarcodeEntry(code=code, price=price_val, description=desc)


def _parse_barcodes_from_db(bcs) -> tuple[list[BarcodeEntry], list[BarcodeSection]]:
    """Читает JSONB barcodes: плоский список (legacy) или {\"_v\":2,\"sections\":...}."""
    if bcs is None:
        return [], []
    if isinstance(bcs, list):
        flat: list[BarcodeEntry] = []
        for b in bcs:
            if isinstance(b, dict) and b.get("code"):
                be = _dict_to_barcode_entry(b)
                if be:
                    flat.append(be)
            elif b and str(b).strip():
                flat.append(BarcodeEntry(code=str(b).strip()))
        sections = [BarcodeSection(name=None, items=list(flat))] if flat else []
        return flat, sections
    if isinstance(bcs, dict) and bcs.get("_v") == 2:
        flat_all: list[BarcodeEntry] = []
        sections_out: list[BarcodeSection] = []
        for sec in bcs.get("sections") or []:
            if not isinstance(sec, dict):
                continue
            name = sec.get("name")
            if name is not None:
                name = str(name).strip() or None
            items: list[BarcodeEntry] = []
            for it in sec.get("items") or []:
                if isinstance(it, dict) and it.get("code"):
                    be = _dict_to_barcode_entry(it)
                    if be:
                        items.append(be)
                        flat_all.append(be)
            sections_out.append(BarcodeSection(name=name, items=items))
        return flat_all, sections_out
    return [], []


def _entry_to_storage_dict(b: BarcodeEntry) -> dict:
    d = {"code": b.code.strip()}
    if b.price is not None:
        d["price"] = b.price
    if b.description:
        d["description"] = b.description
    return d


def _storage_from_barcode_sections(sections: list[BarcodeSection]) -> tuple[Union[list, dict, None], str | None]:
    """
    Сохранение в JSONB: один блок без названия — плоский список (как раньше);
    несколько блоков или одно имя — {\"_v\":2,\"sections\":[...]}.
    """
    cleaned: list[dict] = []
    for sec in sections:
        name = sec.name
        if name is not None:
            name = str(name).strip() or None
        items = [_entry_to_storage_dict(b) for b in sec.items if b.code and str(b.code).strip()]
        if not items:
            continue
        cleaned.append({"name": name, "items": items})
    if not cleaned:
        return None, None
    if len(cleaned) == 1 and cleaned[0]["name"] is None:
        return cleaned[0]["items"], cleaned[0]["items"][0]["code"]
    return {"_v": 2, "sections": cleaned}, cleaned[0]["items"][0]["code"]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _catalog_item_model(catalog: str):
    c = (catalog or "").strip().lower()
    if c == "warehouse":
        return PricelistItem
    if c == "rx":
        return PricelistRxItem
    if c == "mkl":
        return PricelistMklItem
    raise HTTPException(status_code=400, detail="Некорректный каталог публикации")


def _apply_item_payload_for_update(item, payload: dict) -> None:
    upd = dict(payload or {})
    if "feature_ids" in upd and upd["feature_ids"] is None:
        upd["feature_ids"] = []
    if "feature_colors" in upd and upd["feature_colors"] is None:
        upd["feature_colors"] = {}
    if "photo_urls" in upd:
        urls = upd["photo_urls"] or []
        upd["photo_url"] = urls[0] if urls else None
        upd["photo_urls"] = urls if urls else None
    if "barcode_sections" in upd:
        secs_raw = upd.pop("barcode_sections")
        sections = [BarcodeSection.model_validate(s) for s in secs_raw] if secs_raw else []
        storage, first_bc = _storage_from_barcode_sections(sections)
        upd["barcode"] = first_bc
        upd["barcodes"] = storage
    elif "barcodes" in upd:
        bcs = upd["barcodes"] or []
        bcs_stored = []
        for b in bcs:
            if isinstance(b, dict) and b.get("code"):
                bcs_stored.append({"code": str(b["code"]).strip(), "price": b.get("price"), "description": b.get("description")})
            elif isinstance(b, BarcodeEntry) and b.code.strip():
                bcs_stored.append({"code": b.code, "price": b.price, "description": b.description})
        upd["barcode"] = bcs_stored[0]["code"] if bcs_stored else None
        upd["barcodes"] = bcs_stored if bcs_stored else None
    for k, v in upd.items():
        setattr(item, k, v)


def _build_item_for_create(item_model, payload: dict):
    data = dict(payload or {})
    photo_urls = data.get("photo_urls") if data.get("photo_urls") else ([data.get("photo_url")] if data.get("photo_url") else [])
    first_photo = photo_urls[0] if photo_urls else data.get("photo_url")
    if data.get("barcode_sections") is not None:
        sections = [BarcodeSection.model_validate(s) for s in (data.get("barcode_sections") or [])]
        bcs_stored, first_bc = _storage_from_barcode_sections(sections)
        raw_barcode = data.get("barcode")
        first_barcode = first_bc or (str(raw_barcode).strip() if raw_barcode and str(raw_barcode).strip() else None)
    else:
        bcs_raw = data.get("barcodes") if data.get("barcodes") else ([BarcodeEntry(code=data.get("barcode"))] if data.get("barcode") and str(data.get("barcode")).strip() else [])
        bcs_stored = []
        for b in bcs_raw:
            if isinstance(b, dict) and b.get("code"):
                bcs_stored.append({"code": str(b["code"]).strip(), "price": b.get("price"), "description": b.get("description")})
            elif isinstance(b, BarcodeEntry) and b.code.strip():
                bcs_stored.append({"code": b.code, "price": b.price, "description": b.description})
        first_barcode = bcs_stored[0]["code"] if bcs_stored else data.get("barcode")
    return item_model(
        manufacturer_id=data.get("manufacturer_id"),
        lens_name=data.get("lens_name"),
        description=data.get("description"),
        full_description=data.get("full_description"),
        barcode=first_barcode,
        barcodes=bcs_stored if bcs_stored else None,
        photo_url=first_photo,
        photo_urls=photo_urls if photo_urls else None,
        sph=data.get("sph"),
        cyl=data.get("cyl"),
        step=data.get("step"),
        diameters=data.get("diameters"),
        price=data.get("price"),
        sort_index=data.get("sort_index", 500) or 500,
        price_from=data.get("price_from", False) or False,
        is_promo=data.get("is_promo", False) or False,
        uv_protection=data.get("uv_protection", False) or False,
        material=data.get("material"),
        lens_id=data.get("lens_id"),
        group=data.get("group"),
        coefficient=data.get("coefficient"),
        feature_ids=data.get("feature_ids") or [],
        feature_colors=data.get("feature_colors") or {},
        custom_values=data.get("custom_values") or {},
        hide_detail_link=data.get("hide_detail_link", False) or False,
        hide_photo=data.get("hide_photo", False) or False,
        enable_transposition_calc=data.get("enable_transposition_calc", False) or False,
        admin_only=data.get("admin_only", False) or False,
    )


def _queue_publication_job(
    db: Session,
    *,
    catalog: str,
    action: str,
    payload: dict,
    publish_at: datetime,
    created_by_user_id: int | None,
    target_item_id: int | None = None,
    batch_code: str | None = None,
    batch_name: str | None = None,
) -> PricelistPublicationJob:
    when = publish_at if publish_at.tzinfo else publish_at.replace(tzinfo=timezone.utc)
    job = PricelistPublicationJob(
        catalog=catalog,
        action=action,
        payload_json=payload,
        publish_at=when,
        status="pending",
        created_by_user_id=created_by_user_id,
        target_item_id=target_item_id,
        batch_code=batch_code,
        batch_name=batch_name,
    )
    db.add(job)
    db.flush()
    return job


def _apply_pending_pricelist_publications(db: Session) -> None:
    now = _now_utc()
    jobs = (
        db.query(PricelistPublicationJob)
        .filter(PricelistPublicationJob.status == "pending", PricelistPublicationJob.publish_at <= now)
        .order_by(PricelistPublicationJob.publish_at.asc(), PricelistPublicationJob.id.asc())
        .all()
    )
    if not jobs:
        return
    for job in jobs:
        try:
            model = _catalog_item_model(job.catalog)
            payload = dict(job.payload_json or {})
            action = (job.action or "upsert").strip().lower()
            if action in {"update", "upsert"} and job.target_item_id:
                item = db.query(model).filter(model.id == job.target_item_id).first()
                if item is None and action == "update":
                    raise RuntimeError("target item not found for scheduled update")
                if item is None:
                    item = _build_item_for_create(model, payload)
                    db.add(item)
                    db.flush()
                    job.target_item_id = int(item.id)
                else:
                    _apply_item_payload_for_update(item, payload)
            elif action == "create" or (action == "upsert" and not job.target_item_id):
                item = _build_item_for_create(model, payload)
                db.add(item)
                db.flush()
                job.target_item_id = int(item.id)
            else:
                raise RuntimeError("unsupported publication action")
            job.status = "applied"
            job.applied_at = now
            job.error_text = None
        except Exception as e:
            job.status = "failed"
            job.error_text = str(e)[:2000]
            job.applied_at = now
    db.commit()

def _pricelist_item_to_response(x: Union[PricelistItem, PricelistRxItem]) -> PricelistItemResponse:
    manufacturer = getattr(x, "manufacturer", None)
    urls = getattr(x, "photo_urls", None)
    if isinstance(urls, list) and len(urls) > 0:
        photo_urls = [str(u) for u in urls]
        photo_url = photo_urls[0] if photo_urls else x.photo_url
    else:
        photo_url = x.photo_url
        photo_urls = [x.photo_url] if x.photo_url else []
    bcs = getattr(x, "barcodes", None)
    barcodes, barcode_sections = _parse_barcodes_from_db(bcs)
    if barcodes:
        barcode = barcodes[0].code
    else:
        barcode = x.barcode
        if x.barcode and str(x.barcode).strip():
            barcodes = [BarcodeEntry(code=str(x.barcode).strip())]
            barcode_sections = [BarcodeSection(name=None, items=list(barcodes))]
    return PricelistItemResponse(
        id=x.id,
        manufacturer_id=x.manufacturer_id,
        manufacturer_name=manufacturer.name if manufacturer else "",
        manufacturer_image_url=getattr(manufacturer, "image_url", None) if manufacturer else None,
        manufacturer_country_name=(getattr(getattr(manufacturer, "country", None), "name", None) if manufacturer else None),
        lens_name=x.lens_name,
        description=x.description,
        full_description=x.full_description,
        barcode=barcode,
        barcodes=barcodes,
        barcode_sections=barcode_sections,
        photo_url=photo_url,
        photo_urls=photo_urls,
        sph=x.sph,
        cyl=x.cyl,
        step=x.step,
        diameters=x.diameters,
        price=float(x.price),
        sort_index=int(getattr(x, "sort_index", 500) or 500),
        price_from=bool(getattr(x, "price_from", False)),
        is_promo=getattr(x, "is_promo", False) or False,
        uv_protection=getattr(x, "uv_protection", False) or False,
        material=getattr(x, "material", None),
        lens_id=x.lens_id,
        group=x.group,
        coefficient=x.coefficient,
        feature_ids=x.feature_ids or [],
        feature_colors=_normalize_feature_colors(getattr(x, "feature_colors", None)),
        custom_values=(getattr(x, "custom_values", None) or {}),
        hide_detail_link=getattr(x, "hide_detail_link", False) or False,
        hide_photo=getattr(x, "hide_photo", False) or False,
        enable_transposition_calc=getattr(x, "enable_transposition_calc", False) or False,
        admin_only=getattr(x, "admin_only", False) or False,
    )


@router.get("/api/pricelist", response_model=list[PricelistItemResponse])
def list_pricelist(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    from sqlalchemy.orm import joinedload
    _apply_pending_pricelist_publications(db)
    items = (
        db.query(PricelistItem)
        .options(joinedload(PricelistItem.manufacturer))
        .order_by(PricelistItem.group, PricelistItem.sort_index, PricelistItem.id)
        .all()
    )
    return [_pricelist_item_to_response(x) for x in items]


@router.get("/api/pricelist/{item_id}", response_model=PricelistItemResponse)
def get_pricelist_item(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    from sqlalchemy.orm import joinedload
    _apply_pending_pricelist_publications(db)
    item = db.query(PricelistItem).options(joinedload(PricelistItem.manufacturer)).filter(PricelistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Позиция прайслиста не найдена")
    return _pricelist_item_to_response(item)


@router.post("/api/ref/pricelist", response_model=PricelistItemResponse, status_code=201)
def create_pricelist_item(data: PricelistItemCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    photo_urls = data.photo_urls if data.photo_urls else ([data.photo_url] if data.photo_url else [])
    first_photo = photo_urls[0] if photo_urls else data.photo_url
    if data.barcode_sections is not None:
        bcs_stored, first_bc = _storage_from_barcode_sections(data.barcode_sections)
        first_barcode = first_bc or (data.barcode.strip() if data.barcode and str(data.barcode).strip() else None)
    else:
        bcs = data.barcodes if data.barcodes else ([BarcodeEntry(code=data.barcode)] if data.barcode and data.barcode.strip() else [])
        bcs_stored = [{"code": b.code, "price": b.price, "description": b.description} for b in bcs if b and b.code.strip()]
        first_barcode = bcs_stored[0]["code"] if bcs_stored else data.barcode
    obj = PricelistItem(
        manufacturer_id=data.manufacturer_id,
        lens_name=data.lens_name,
        description=data.description,
        full_description=data.full_description,
        barcode=first_barcode,
        barcodes=bcs_stored if bcs_stored else None,
        photo_url=first_photo,
        photo_urls=photo_urls if photo_urls else None,
        sph=data.sph,
        cyl=data.cyl,
        step=data.step,
        diameters=data.diameters,
        price=data.price,
        sort_index=getattr(data, "sort_index", 500) or 500,
        price_from=getattr(data, "price_from", False) or False,
        is_promo=getattr(data, "is_promo", False) or False,
        uv_protection=getattr(data, "uv_protection", False) or False,
        material=getattr(data, "material", None),
        lens_id=data.lens_id,
        group=data.group,
        coefficient=data.coefficient,
        feature_ids=data.feature_ids or [],
        feature_colors=getattr(data, "feature_colors", None) or {},
        custom_values=getattr(data, "custom_values", None) or {},
        hide_detail_link=getattr(data, "hide_detail_link", False) or False,
        hide_photo=getattr(data, "hide_photo", False) or False,
        enable_transposition_calc=getattr(data, "enable_transposition_calc", False) or False,
        admin_only=getattr(data, "admin_only", False) or False,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    from sqlalchemy.orm import joinedload
    item = db.query(PricelistItem).options(joinedload(PricelistItem.manufacturer)).filter(PricelistItem.id == obj.id).first()
    return _pricelist_item_to_response(item)


@router.post("/api/ref/pricelist/bulk", response_model=list[PricelistItemResponse], status_code=201)
def bulk_create_pricelist_items(
    data: PricelistBulkCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    created_ids: list[int] = []
    for req in data.items:
        photo_urls = req.photo_urls if req.photo_urls else ([req.photo_url] if req.photo_url else [])
        first_photo = photo_urls[0] if photo_urls else req.photo_url
        if req.barcode_sections is not None:
            bcs_stored, first_bc = _storage_from_barcode_sections(req.barcode_sections)
            first_barcode = first_bc or (req.barcode.strip() if req.barcode and str(req.barcode).strip() else None)
        else:
            bcs = req.barcodes if req.barcodes else ([BarcodeEntry(code=req.barcode)] if req.barcode and req.barcode.strip() else [])
            bcs_stored = [{"code": b.code, "price": b.price, "description": b.description} for b in bcs if b and b.code.strip()]
            first_barcode = bcs_stored[0]["code"] if bcs_stored else req.barcode

        obj = PricelistItem(
            manufacturer_id=req.manufacturer_id,
            lens_name=req.lens_name,
            description=req.description,
            full_description=req.full_description,
            barcode=first_barcode,
            barcodes=bcs_stored if bcs_stored else None,
            photo_url=first_photo,
            photo_urls=photo_urls if photo_urls else None,
            sph=req.sph,
            cyl=req.cyl,
            step=req.step,
            diameters=req.diameters,
            price=req.price,
            sort_index=getattr(req, "sort_index", 500) or 500,
            price_from=getattr(req, "price_from", False) or False,
            is_promo=getattr(req, "is_promo", False) or False,
            uv_protection=getattr(req, "uv_protection", False) or False,
            material=getattr(req, "material", None),
            lens_id=req.lens_id,
            group=req.group,
            coefficient=req.coefficient,
            feature_ids=req.feature_ids or [],
            feature_colors=getattr(req, "feature_colors", None) or {},
            custom_values=getattr(req, "custom_values", None) or {},
            hide_detail_link=getattr(req, "hide_detail_link", False) or False,
            hide_photo=getattr(req, "hide_photo", False) or False,
            enable_transposition_calc=getattr(req, "enable_transposition_calc", False) or False,
            admin_only=getattr(req, "admin_only", False) or False,
        )
        db.add(obj)
        db.flush()
        created_ids.append(obj.id)

    db.commit()

    from sqlalchemy.orm import joinedload
    items = (
        db.query(PricelistItem)
        .options(joinedload(PricelistItem.manufacturer))
        .filter(PricelistItem.id.in_(created_ids))
        .all()
    )
    items_by_id = {it.id: it for it in items}
    return [_pricelist_item_to_response(items_by_id[i]) for i in created_ids if i in items_by_id]


@router.patch("/api/ref/pricelist/{item_id}", response_model=PricelistItemResponse)
def update_pricelist_item(item_id: int, data: PricelistItemUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_admin_user)):
    from sqlalchemy.orm import joinedload
    item = db.query(PricelistItem).filter(PricelistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Позиция прайслиста не найдена")
    payload = data.model_dump(exclude_unset=True, exclude={"publish_mode", "publish_at"})
    publish_mode = (data.publish_mode or "now").strip().lower()
    publish_at = data.publish_at
    if publish_mode == "schedule":
        if publish_at is None:
            raise HTTPException(status_code=400, detail="Для отложенной публикации укажите дату/время publish_at")
        _queue_publication_job(
            db,
            catalog="warehouse",
            action="update",
            payload=payload,
            publish_at=publish_at,
            created_by_user_id=getattr(current_user, "id", None),
            target_item_id=item_id,
        )
    else:
        _apply_item_payload_for_update(item, payload)
    db.commit()
    db.refresh(item)
    item = db.query(PricelistItem).options(joinedload(PricelistItem.manufacturer)).filter(PricelistItem.id == item_id).first()
    return _pricelist_item_to_response(item)


@router.delete("/api/ref/pricelist/{item_id}", status_code=204)
def delete_pricelist_item(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    item = db.query(PricelistItem).filter(PricelistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Позиция прайслиста не найдена")
    db.delete(item)
    db.commit()
    return None


# --- Pricelist RX (отдельные таблицы pricelist_rx_*; те же поля, что у склада) ---


@router.get("/api/ref/pricelist-rx-groups", response_model=list[PricelistGroupResponse])
def list_pricelist_rx_groups(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(PricelistRxGroup).order_by(PricelistRxGroup.sort_index, PricelistRxGroup.name)
    if not is_admin(current_user):
        query = query.filter(PricelistRxGroup.admin_only.is_(False))
    return query.all()


@router.get("/api/ref/pricelist-rx-groups/{item_id}", response_model=PricelistGroupResponse)
def get_pricelist_rx_group(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    obj = db.query(PricelistRxGroup).filter(PricelistRxGroup.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    if bool(getattr(obj, "admin_only", False)) and not is_admin(current_user):
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.post("/api/ref/pricelist-rx-groups", response_model=PricelistGroupResponse, status_code=201)
def create_pricelist_rx_group(data: PricelistGroupCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    existing = db.query(PricelistRxGroup).filter(PricelistRxGroup.name == data.name.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Группа с таким названием уже есть")
    obj = PricelistRxGroup(
        name=data.name.strip(),
        sort_index=data.sort_index,
        display_properties_in_list=data.display_properties_in_list,
        display_as_tiles=data.display_as_tiles,
        tiles_per_page=max(1, min(48, int(data.tiles_per_page))),
        admin_only=bool(getattr(data, "admin_only", False)),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.patch("/api/ref/pricelist-rx-groups/{item_id}", response_model=PricelistGroupResponse)
def update_pricelist_rx_group(item_id: int, data: PricelistGroupUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(PricelistRxGroup).filter(PricelistRxGroup.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    payload = data.model_dump(exclude_unset=True)
    if "name" in payload and payload["name"] is not None:
        new_name = payload["name"].strip()
        existing = db.query(PricelistRxGroup).filter(PricelistRxGroup.name == new_name, PricelistRxGroup.id != item_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Группа с таким названием уже есть")
        obj.name = new_name
    if "sort_index" in payload and payload["sort_index"] is not None:
        obj.sort_index = payload["sort_index"]
    if "display_properties_in_list" in payload and payload["display_properties_in_list"] is not None:
        obj.display_properties_in_list = bool(payload["display_properties_in_list"])
    if "display_as_tiles" in payload and payload["display_as_tiles"] is not None:
        obj.display_as_tiles = bool(payload["display_as_tiles"])
    if "tiles_per_page" in payload and payload["tiles_per_page"] is not None:
        obj.tiles_per_page = max(1, min(48, int(payload["tiles_per_page"])))
    if "admin_only" in payload and payload["admin_only"] is not None:
        obj.admin_only = bool(payload["admin_only"])
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/pricelist-rx-groups/{item_id}", status_code=204)
def delete_pricelist_rx_group(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(PricelistRxGroup).filter(PricelistRxGroup.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


@router.get("/api/pricelist-rx", response_model=list[PricelistItemResponse])
def list_pricelist_rx(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from sqlalchemy.orm import joinedload
    _apply_pending_pricelist_publications(db)
    query = (
        db.query(PricelistRxItem)
        .options(joinedload(PricelistRxItem.manufacturer))
        .order_by(PricelistRxItem.group, PricelistRxItem.sort_index, PricelistRxItem.id)
    )
    if not is_admin(current_user):
        query = query.filter(PricelistRxItem.admin_only.is_(False))
    items = query.all()
    return [_pricelist_item_to_response(x) for x in items]


@router.get("/api/pricelist-rx/{item_id}", response_model=PricelistItemResponse)
def get_pricelist_rx_item(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from sqlalchemy.orm import joinedload
    _apply_pending_pricelist_publications(db)
    item = db.query(PricelistRxItem).options(joinedload(PricelistRxItem.manufacturer)).filter(PricelistRxItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Позиция прайслиста не найдена")
    if bool(getattr(item, "admin_only", False)) and not is_admin(current_user):
        raise HTTPException(status_code=404, detail="Позиция прайслиста не найдена")
    return _pricelist_item_to_response(item)


@router.post("/api/ref/pricelist-rx", response_model=PricelistItemResponse, status_code=201)
def create_pricelist_rx_item(data: PricelistItemCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    photo_urls = data.photo_urls if data.photo_urls else ([data.photo_url] if data.photo_url else [])
    first_photo = photo_urls[0] if photo_urls else data.photo_url
    if data.barcode_sections is not None:
        bcs_stored, first_bc = _storage_from_barcode_sections(data.barcode_sections)
        first_barcode = first_bc or (data.barcode.strip() if data.barcode and str(data.barcode).strip() else None)
    else:
        bcs = data.barcodes if data.barcodes else ([BarcodeEntry(code=data.barcode)] if data.barcode and data.barcode.strip() else [])
        bcs_stored = [{"code": b.code, "price": b.price, "description": b.description} for b in bcs if b and b.code.strip()]
        first_barcode = bcs_stored[0]["code"] if bcs_stored else data.barcode
    obj = PricelistRxItem(
        manufacturer_id=data.manufacturer_id,
        lens_name=data.lens_name,
        description=data.description,
        full_description=data.full_description,
        barcode=first_barcode,
        barcodes=bcs_stored if bcs_stored else None,
        photo_url=first_photo,
        photo_urls=photo_urls if photo_urls else None,
        sph=data.sph,
        cyl=data.cyl,
        step=data.step,
        diameters=data.diameters,
        price=data.price,
        sort_index=getattr(data, "sort_index", 500) or 500,
        price_from=getattr(data, "price_from", False) or False,
        is_promo=getattr(data, "is_promo", False) or False,
        uv_protection=getattr(data, "uv_protection", False) or False,
        material=getattr(data, "material", None),
        lens_id=data.lens_id,
        group=data.group,
        coefficient=data.coefficient,
        feature_ids=data.feature_ids or [],
        feature_colors=getattr(data, "feature_colors", None) or {},
        custom_values=getattr(data, "custom_values", None) or {},
        hide_detail_link=getattr(data, "hide_detail_link", False) or False,
        hide_photo=getattr(data, "hide_photo", False) or False,
        enable_transposition_calc=getattr(data, "enable_transposition_calc", False) or False,
        admin_only=getattr(data, "admin_only", False) or False,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    from sqlalchemy.orm import joinedload

    item = db.query(PricelistRxItem).options(joinedload(PricelistRxItem.manufacturer)).filter(PricelistRxItem.id == obj.id).first()
    return _pricelist_item_to_response(item)


@router.post("/api/ref/pricelist-rx/bulk", response_model=list[PricelistItemResponse], status_code=201)
def bulk_create_pricelist_rx_items(
    data: PricelistBulkCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    created_ids: list[int] = []
    for req in data.items:
        photo_urls = req.photo_urls if req.photo_urls else ([req.photo_url] if req.photo_url else [])
        first_photo = photo_urls[0] if photo_urls else req.photo_url
        if req.barcode_sections is not None:
            bcs_stored, first_bc = _storage_from_barcode_sections(req.barcode_sections)
            first_barcode = first_bc or (req.barcode.strip() if req.barcode and str(req.barcode).strip() else None)
        else:
            bcs = req.barcodes if req.barcodes else ([BarcodeEntry(code=req.barcode)] if req.barcode and req.barcode.strip() else [])
            bcs_stored = [{"code": b.code, "price": b.price, "description": b.description} for b in bcs if b and b.code.strip()]
            first_barcode = bcs_stored[0]["code"] if bcs_stored else req.barcode

        obj = PricelistRxItem(
            manufacturer_id=req.manufacturer_id,
            lens_name=req.lens_name,
            description=req.description,
            full_description=req.full_description,
            barcode=first_barcode,
            barcodes=bcs_stored if bcs_stored else None,
            photo_url=first_photo,
            photo_urls=photo_urls if photo_urls else None,
            sph=req.sph,
            cyl=req.cyl,
            step=req.step,
            diameters=req.diameters,
            price=req.price,
            sort_index=getattr(req, "sort_index", 500) or 500,
            price_from=getattr(req, "price_from", False) or False,
            is_promo=getattr(req, "is_promo", False) or False,
            uv_protection=getattr(req, "uv_protection", False) or False,
            material=getattr(req, "material", None),
            lens_id=req.lens_id,
            group=req.group,
            coefficient=req.coefficient,
            feature_ids=req.feature_ids or [],
            feature_colors=getattr(req, "feature_colors", None) or {},
            custom_values=getattr(req, "custom_values", None) or {},
            hide_detail_link=getattr(req, "hide_detail_link", False) or False,
            hide_photo=getattr(req, "hide_photo", False) or False,
            enable_transposition_calc=getattr(req, "enable_transposition_calc", False) or False,
            admin_only=getattr(req, "admin_only", False) or False,
        )
        db.add(obj)
        db.flush()
        created_ids.append(obj.id)

    db.commit()

    from sqlalchemy.orm import joinedload

    items = (
        db.query(PricelistRxItem)
        .options(joinedload(PricelistRxItem.manufacturer))
        .filter(PricelistRxItem.id.in_(created_ids))
        .all()
    )
    items_by_id = {it.id: it for it in items}
    return [_pricelist_item_to_response(items_by_id[i]) for i in created_ids if i in items_by_id]


@router.patch("/api/ref/pricelist-rx/{item_id}", response_model=PricelistItemResponse)
def update_pricelist_rx_item(item_id: int, data: PricelistItemUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_admin_user)):
    from sqlalchemy.orm import joinedload

    item = db.query(PricelistRxItem).filter(PricelistRxItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Позиция прайслиста не найдена")
    payload = data.model_dump(exclude_unset=True, exclude={"publish_mode", "publish_at"})
    publish_mode = (data.publish_mode or "now").strip().lower()
    publish_at = data.publish_at
    if publish_mode == "schedule":
        if publish_at is None:
            raise HTTPException(status_code=400, detail="Для отложенной публикации укажите дату/время publish_at")
        _queue_publication_job(
            db,
            catalog="rx",
            action="update",
            payload=payload,
            publish_at=publish_at,
            created_by_user_id=getattr(current_user, "id", None),
            target_item_id=item_id,
        )
    else:
        _apply_item_payload_for_update(item, payload)
    db.commit()
    db.refresh(item)
    item = db.query(PricelistRxItem).options(joinedload(PricelistRxItem.manufacturer)).filter(PricelistRxItem.id == item_id).first()
    return _pricelist_item_to_response(item)


@router.delete("/api/ref/pricelist-rx/{item_id}", status_code=204)
def delete_pricelist_rx_item(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    item = db.query(PricelistRxItem).filter(PricelistRxItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Позиция прайслиста не найдена")
    db.delete(item)
    db.commit()
    return None


# --- Pricelist MKL (отдельные таблицы pricelist_mkl_*; те же поля, что у склада) ---


@router.get("/api/ref/pricelist-mkl-groups", response_model=list[PricelistGroupResponse])
def list_pricelist_mkl_groups(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(PricelistMklGroup).order_by(PricelistMklGroup.sort_index, PricelistMklGroup.name).all()


@router.get("/api/ref/pricelist-mkl-groups/{item_id}", response_model=PricelistGroupResponse)
def get_pricelist_mkl_group(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    obj = db.query(PricelistMklGroup).filter(PricelistMklGroup.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    return obj


@router.post("/api/ref/pricelist-mkl-groups", response_model=PricelistGroupResponse, status_code=201)
def create_pricelist_mkl_group(data: PricelistGroupCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    existing = db.query(PricelistMklGroup).filter(PricelistMklGroup.name == data.name.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Группа с таким названием уже есть")
    obj = PricelistMklGroup(
        name=data.name.strip(),
        sort_index=data.sort_index,
        display_properties_in_list=data.display_properties_in_list,
        display_as_tiles=data.display_as_tiles,
        tiles_per_page=max(1, min(48, int(data.tiles_per_page))),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.patch("/api/ref/pricelist-mkl-groups/{item_id}", response_model=PricelistGroupResponse)
def update_pricelist_mkl_group(item_id: int, data: PricelistGroupUpdate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(PricelistMklGroup).filter(PricelistMklGroup.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    payload = data.model_dump(exclude_unset=True)
    if "name" in payload and payload["name"] is not None:
        new_name = payload["name"].strip()
        existing = db.query(PricelistMklGroup).filter(PricelistMklGroup.name == new_name, PricelistMklGroup.id != item_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Группа с таким названием уже есть")
        obj.name = new_name
    if "sort_index" in payload and payload["sort_index"] is not None:
        obj.sort_index = payload["sort_index"]
    if "display_properties_in_list" in payload and payload["display_properties_in_list"] is not None:
        obj.display_properties_in_list = bool(payload["display_properties_in_list"])
    if "display_as_tiles" in payload and payload["display_as_tiles"] is not None:
        obj.display_as_tiles = bool(payload["display_as_tiles"])
    if "tiles_per_page" in payload and payload["tiles_per_page"] is not None:
        obj.tiles_per_page = max(1, min(48, int(payload["tiles_per_page"])))
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/api/ref/pricelist-mkl-groups/{item_id}", status_code=204)
def delete_pricelist_mkl_group(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    obj = db.query(PricelistMklGroup).filter(PricelistMklGroup.id == item_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Не найдено")
    db.delete(obj)
    db.commit()
    return None


@router.get("/api/pricelist-mkl", response_model=list[PricelistItemResponse])
def list_pricelist_mkl(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from sqlalchemy.orm import joinedload
    _apply_pending_pricelist_publications(db)
    query = (
        db.query(PricelistMklItem)
        .options(joinedload(PricelistMklItem.manufacturer))
        .order_by(PricelistMklItem.group, PricelistMklItem.sort_index, PricelistMklItem.id)
    )
    if not is_admin(current_user):
        query = query.filter(PricelistMklItem.admin_only.is_(False))
    items = query.all()
    return [_pricelist_item_to_response(x) for x in items]


@router.get("/api/pricelist-mkl/{item_id}", response_model=PricelistItemResponse)
def get_pricelist_mkl_item(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from sqlalchemy.orm import joinedload
    _apply_pending_pricelist_publications(db)
    item = db.query(PricelistMklItem).options(joinedload(PricelistMklItem.manufacturer)).filter(PricelistMklItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Позиция прайслиста не найдена")
    if bool(getattr(item, "admin_only", False)) and not is_admin(current_user):
        raise HTTPException(status_code=404, detail="Позиция прайслиста не найдена")
    return _pricelist_item_to_response(item)


@router.post("/api/ref/pricelist-mkl", response_model=PricelistItemResponse, status_code=201)
def create_pricelist_mkl_item(data: PricelistItemCreate, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    photo_urls = data.photo_urls if data.photo_urls else ([data.photo_url] if data.photo_url else [])
    first_photo = photo_urls[0] if photo_urls else data.photo_url
    if data.barcode_sections is not None:
        bcs_stored, first_bc = _storage_from_barcode_sections(data.barcode_sections)
        first_barcode = first_bc or (data.barcode.strip() if data.barcode and str(data.barcode).strip() else None)
    else:
        bcs = data.barcodes if data.barcodes else ([BarcodeEntry(code=data.barcode)] if data.barcode and data.barcode.strip() else [])
        bcs_stored = [{"code": b.code, "price": b.price, "description": b.description} for b in bcs if b and b.code.strip()]
        first_barcode = bcs_stored[0]["code"] if bcs_stored else data.barcode
    obj = PricelistMklItem(
        manufacturer_id=data.manufacturer_id,
        lens_name=data.lens_name,
        description=data.description,
        full_description=data.full_description,
        barcode=first_barcode,
        barcodes=bcs_stored if bcs_stored else None,
        photo_url=first_photo,
        photo_urls=photo_urls if photo_urls else None,
        sph=data.sph,
        cyl=data.cyl,
        step=data.step,
        diameters=data.diameters,
        price=data.price,
        sort_index=getattr(data, "sort_index", 500) or 500,
        price_from=getattr(data, "price_from", False) or False,
        is_promo=getattr(data, "is_promo", False) or False,
        uv_protection=getattr(data, "uv_protection", False) or False,
        material=getattr(data, "material", None),
        lens_id=data.lens_id,
        group=data.group,
        coefficient=data.coefficient,
        feature_ids=data.feature_ids or [],
        feature_colors=getattr(data, "feature_colors", None) or {},
        custom_values=getattr(data, "custom_values", None) or {},
        hide_detail_link=getattr(data, "hide_detail_link", False) or False,
        hide_photo=getattr(data, "hide_photo", False) or False,
        enable_transposition_calc=getattr(data, "enable_transposition_calc", False) or False,
        admin_only=getattr(data, "admin_only", False) or False,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    from sqlalchemy.orm import joinedload

    item = db.query(PricelistMklItem).options(joinedload(PricelistMklItem.manufacturer)).filter(PricelistMklItem.id == obj.id).first()
    return _pricelist_item_to_response(item)


@router.post("/api/ref/pricelist-mkl/bulk", response_model=list[PricelistItemResponse], status_code=201)
def bulk_create_pricelist_mkl_items(
    data: PricelistBulkCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    created_ids: list[int] = []
    for req in data.items:
        photo_urls = req.photo_urls if req.photo_urls else ([req.photo_url] if req.photo_url else [])
        first_photo = photo_urls[0] if photo_urls else req.photo_url
        if req.barcode_sections is not None:
            bcs_stored, first_bc = _storage_from_barcode_sections(req.barcode_sections)
            first_barcode = first_bc or (req.barcode.strip() if req.barcode and str(req.barcode).strip() else None)
        else:
            bcs = req.barcodes if req.barcodes else ([BarcodeEntry(code=req.barcode)] if req.barcode and req.barcode.strip() else [])
            bcs_stored = [{"code": b.code, "price": b.price, "description": b.description} for b in bcs if b and b.code.strip()]
            first_barcode = bcs_stored[0]["code"] if bcs_stored else req.barcode

        obj = PricelistMklItem(
            manufacturer_id=req.manufacturer_id,
            lens_name=req.lens_name,
            description=req.description,
            full_description=req.full_description,
            barcode=first_barcode,
            barcodes=bcs_stored if bcs_stored else None,
            photo_url=first_photo,
            photo_urls=photo_urls if photo_urls else None,
            sph=req.sph,
            cyl=req.cyl,
            step=req.step,
            diameters=req.diameters,
            price=req.price,
            sort_index=getattr(req, "sort_index", 500) or 500,
            price_from=getattr(req, "price_from", False) or False,
            is_promo=getattr(req, "is_promo", False) or False,
            uv_protection=getattr(req, "uv_protection", False) or False,
            material=getattr(req, "material", None),
            lens_id=req.lens_id,
            group=req.group,
            coefficient=req.coefficient,
            feature_ids=req.feature_ids or [],
            feature_colors=getattr(req, "feature_colors", None) or {},
            custom_values=getattr(req, "custom_values", None) or {},
            hide_detail_link=getattr(req, "hide_detail_link", False) or False,
            hide_photo=getattr(req, "hide_photo", False) or False,
            enable_transposition_calc=getattr(req, "enable_transposition_calc", False) or False,
            admin_only=getattr(req, "admin_only", False) or False,
        )
        db.add(obj)
        db.flush()
        created_ids.append(obj.id)

    db.commit()

    from sqlalchemy.orm import joinedload

    items = (
        db.query(PricelistMklItem)
        .options(joinedload(PricelistMklItem.manufacturer))
        .filter(PricelistMklItem.id.in_(created_ids))
        .all()
    )
    items_by_id = {it.id: it for it in items}
    return [_pricelist_item_to_response(items_by_id[i]) for i in created_ids if i in items_by_id]


@router.patch("/api/ref/pricelist-mkl/{item_id}", response_model=PricelistItemResponse)
def update_pricelist_mkl_item(item_id: int, data: PricelistItemUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_admin_user)):
    from sqlalchemy.orm import joinedload

    item = db.query(PricelistMklItem).filter(PricelistMklItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Позиция прайслиста не найдена")
    payload = data.model_dump(exclude_unset=True, exclude={"publish_mode", "publish_at"})
    publish_mode = (data.publish_mode or "now").strip().lower()
    publish_at = data.publish_at
    if publish_mode == "schedule":
        if publish_at is None:
            raise HTTPException(status_code=400, detail="Для отложенной публикации укажите дату/время publish_at")
        _queue_publication_job(
            db,
            catalog="mkl",
            action="update",
            payload=payload,
            publish_at=publish_at,
            created_by_user_id=getattr(current_user, "id", None),
            target_item_id=item_id,
        )
    else:
        _apply_item_payload_for_update(item, payload)
    db.commit()
    db.refresh(item)
    item = db.query(PricelistMklItem).options(joinedload(PricelistMklItem.manufacturer)).filter(PricelistMklItem.id == item_id).first()
    return _pricelist_item_to_response(item)


@router.delete("/api/ref/pricelist-mkl/{item_id}", status_code=204)
def delete_pricelist_mkl_item(item_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    item = db.query(PricelistMklItem).filter(PricelistMklItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Позиция прайслиста не найдена")
    db.delete(item)
    db.commit()
    return None


@router.get("/api/ref/pricelist-publications", response_model=list[PricelistPublicationJobResponse])
def list_pricelist_publications(
    catalog: str | None = Query(None, description="warehouse | rx | mkl"),
    status: str | None = Query("pending", description="pending | applied | failed | cancelled | all"),
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    _apply_pending_pricelist_publications(db)
    q = db.query(PricelistPublicationJob)
    if catalog:
        q = q.filter(PricelistPublicationJob.catalog == catalog.strip().lower())
    st = (status or "").strip().lower()
    if st and st != "all":
        q = q.filter(PricelistPublicationJob.status == st)
    rows = q.order_by(PricelistPublicationJob.publish_at.asc(), PricelistPublicationJob.id.asc()).all()
    return rows


@router.post("/api/ref/pricelist-publications", response_model=PricelistPublicationJobResponse, status_code=201)
def create_pricelist_publication(
    data: PricelistPublicationJobCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user),
):
    job = _queue_publication_job(
        db,
        catalog=(data.catalog or "").strip().lower(),
        action=(data.action or "create").strip().lower(),
        payload=dict(data.payload_json or {}),
        publish_at=data.publish_at,
        created_by_user_id=getattr(current_user, "id", None),
        target_item_id=data.target_item_id,
        batch_code=(data.batch_code or None),
        batch_name=(data.batch_name or None),
    )
    db.commit()
    db.refresh(job)
    return job


@router.post("/api/ref/pricelist-publications/assign-batch", response_model=list[PricelistPublicationJobResponse])
def assign_pricelist_publications_batch(
    data: PricelistPublicationBatchAssign,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    ids = [int(x) for x in (data.job_ids or []) if int(x) > 0]
    if not ids:
        raise HTTPException(status_code=400, detail="Не выбраны задачи для батча")
    batch_name = (data.batch_name or "").strip()
    if not batch_name:
        raise HTTPException(status_code=400, detail="Укажите название версии")
    batch_code = f"plv-{uuid4().hex[:12]}"
    rows = (
        db.query(PricelistPublicationJob)
        .filter(PricelistPublicationJob.id.in_(ids), PricelistPublicationJob.status.in_(["pending", "failed"]))
        .all()
    )
    for r in rows:
        r.batch_code = batch_code
        r.batch_name = batch_name
    db.commit()
    return (
        db.query(PricelistPublicationJob)
        .filter(PricelistPublicationJob.id.in_([r.id for r in rows]))
        .order_by(PricelistPublicationJob.publish_at.asc(), PricelistPublicationJob.id.asc())
        .all()
    )


@router.post("/api/ref/pricelist-publications/batches/{batch_code}/publish-now", response_model=list[PricelistPublicationJobResponse])
def publish_pricelist_batch_now(batch_code: str, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    rows = (
        db.query(PricelistPublicationJob)
        .filter(
            PricelistPublicationJob.batch_code == batch_code,
            PricelistPublicationJob.status.in_(["pending", "failed"]),
        )
        .all()
    )
    now = _now_utc()
    for r in rows:
        r.status = "pending"
        r.publish_at = now
    db.commit()
    _apply_pending_pricelist_publications(db)
    return (
        db.query(PricelistPublicationJob)
        .filter(PricelistPublicationJob.batch_code == batch_code)
        .order_by(PricelistPublicationJob.publish_at.asc(), PricelistPublicationJob.id.asc())
        .all()
    )


@router.post("/api/ref/pricelist-publications/{job_id}/publish-now", response_model=PricelistPublicationJobResponse)
def publish_pricelist_publication_now(job_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    job = db.query(PricelistPublicationJob).filter(PricelistPublicationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Версия публикации не найдена")
    if job.status not in {"pending", "failed"}:
        return job
    job.status = "pending"
    job.publish_at = _now_utc()
    db.commit()
    _apply_pending_pricelist_publications(db)
    db.refresh(job)
    return job


@router.post("/api/ref/pricelist-publications/publish-all-now", response_model=list[PricelistPublicationJobResponse])
def publish_all_pricelist_publications_now(
    catalog: str | None = Query(None, description="warehouse | rx | mkl"),
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    q = db.query(PricelistPublicationJob).filter(PricelistPublicationJob.status.in_(["pending", "failed"]))
    if catalog:
        q = q.filter(PricelistPublicationJob.catalog == catalog.strip().lower())
    rows = q.all()
    now = _now_utc()
    for r in rows:
        r.status = "pending"
        r.publish_at = now
    db.commit()
    _apply_pending_pricelist_publications(db)
    ids = [r.id for r in rows]
    if not ids:
        return []
    return (
        db.query(PricelistPublicationJob)
        .filter(PricelistPublicationJob.id.in_(ids))
        .order_by(PricelistPublicationJob.publish_at.asc(), PricelistPublicationJob.id.asc())
        .all()
    )


@router.delete("/api/ref/pricelist-publications/{job_id}", status_code=204)
def cancel_pricelist_publication(job_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    job = db.query(PricelistPublicationJob).filter(PricelistPublicationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Версия публикации не найдена")
    if job.status == "applied":
        raise HTTPException(status_code=400, detail="Уже опубликовано, отмена недоступна")
    job.status = "cancelled"
    db.commit()
    return None


@router.post("/api/ref/pricelist-publications/cancel-many", response_model=list[PricelistPublicationJobResponse])
def cancel_many_pricelist_publications(
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    raw_ids = body.get("job_ids") if isinstance(body, dict) else None
    if not isinstance(raw_ids, list):
        raise HTTPException(status_code=400, detail="Ожидается массив job_ids")
    ids: list[int] = []
    for v in raw_ids:
        try:
            ids.append(int(v))
        except Exception:
            continue
    if not ids:
        return []
    jobs = (
        db.query(PricelistPublicationJob)
        .filter(PricelistPublicationJob.id.in_(ids))
        .order_by(PricelistPublicationJob.publish_at.asc(), PricelistPublicationJob.id.asc())
        .all()
    )
    for job in jobs:
        if job.status != "applied":
            job.status = "cancelled"
    db.commit()
    return jobs


@router.post("/api/ref/pricelist-publications/batches/{batch_code}/cancel", response_model=list[PricelistPublicationJobResponse])
def cancel_pricelist_publication_batch(
    batch_code: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    code = (batch_code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="batch_code обязателен")
    jobs = (
        db.query(PricelistPublicationJob)
        .filter(PricelistPublicationJob.batch_code == code)
        .order_by(PricelistPublicationJob.publish_at.asc(), PricelistPublicationJob.id.asc())
        .all()
    )
    if not jobs:
        raise HTTPException(status_code=404, detail="Версионный набор не найден")
    for job in jobs:
        if job.status != "applied":
            job.status = "cancelled"
    db.commit()
    return jobs


def _serialize_rows(rows: list, fields: list[str]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        item: dict = {}
        for f in fields:
            v = getattr(row, f, None)
            if isinstance(v, datetime):
                item[f] = v.isoformat()
            elif isinstance(v, Decimal):
                # Preserve precision while remaining JSON-serializable.
                item[f] = float(v)
            else:
                item[f] = v
        out.append(item)
    return out


def _sql_literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, datetime):
        return f"'{v.isoformat()}'"
    if isinstance(v, (dict, list)):
        txt = json.dumps(v, ensure_ascii=False).replace("'", "''")
        return f"'{txt}'::jsonb"
    txt = str(v).replace("'", "''")
    return f"'{txt}'"


def _build_insert_sql(table_name: str, rows: list[dict]) -> str:
    if not rows:
        return f"-- {table_name}: no rows\n"
    cols = list(rows[0].keys())
    lines = [f"-- {table_name}", "BEGIN;"]
    for r in rows:
        values = ", ".join(_sql_literal(r.get(c)) for c in cols)
        lines.append(f"INSERT INTO {table_name} ({', '.join(cols)}) VALUES ({values});")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def _collect_static_urls(
    pricelist_items: list[PricelistItem],
    pricelist_rx_items: list[PricelistRxItem],
    pricelist_mkl_items: list[PricelistMklItem],
    manufacturers: list[Manufacturer],
    features: list[Feature],
) -> list[str]:
    urls: set[str] = set()
    for m in manufacturers:
        if m.image_url:
            urls.add(m.image_url)
        if m.catalog_pdf_url:
            urls.add(m.catalog_pdf_url)
    for f in features:
        if f.icon_url:
            urls.add(f.icon_url)
    for p in [*pricelist_items, *pricelist_rx_items, *pricelist_mkl_items]:
        photo_url = getattr(p, "photo_url", None)
        photo_urls = getattr(p, "photo_urls", None)
        if photo_url:
            urls.add(photo_url)
        if isinstance(photo_urls, list):
            for u in photo_urls:
                if u:
                    urls.add(str(u))
    return sorted(u for u in urls if str(u).strip())


def _read_static_file_bytes(url: str) -> tuple[str, bytes] | None:
    parsed = urlparse(url)
    # Local uploaded file: /uploads/<name>
    if url.startswith("/uploads/"):
        local = UPLOADS_DIR / url.replace("/uploads/", "", 1)
        if local.exists() and local.is_file():
            return (f"static/uploads/{local.name}", local.read_bytes())
        return None

    # Remote URL
    if parsed.scheme in ("http", "https"):
        try:
            req = Request(url, headers={"User-Agent": "MosoptikaExport/1.0"})
            with urlopen(req, timeout=20) as resp:
                data = resp.read()
            name = Path(parsed.path).name or "file.bin"
            safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
            host = parsed.netloc.replace(":", "_")
            return (f"static/remote/{host}/{safe_name}", data)
        except Exception:
            return None

    return None


@router.get("/api/settings/pricelist/export")
def export_pricelist_bundle(
    catalog: str = Query("all", description="all | warehouse | rx | mkl"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Экспорт раздела прайслиста:
    - связанные таблицы БД (json + sql inserts);
    - связанные статические файлы (uploads/URL-ресурсы).
    Доступен всем авторизованным пользователям.
    """
    normalized_catalog = (catalog or "all").strip().lower()
    if normalized_catalog not in {"all", "warehouse", "rx", "mkl"}:
        raise HTTPException(status_code=400, detail="Некорректный catalog. Используйте: all | warehouse | rx | mkl")

    pricelist_items = db.query(PricelistItem).order_by(PricelistItem.id).all() if normalized_catalog in {"all", "warehouse"} else []
    pricelist_groups = db.query(PricelistGroup).order_by(PricelistGroup.id).all() if normalized_catalog in {"all", "warehouse"} else []
    pricelist_rx_items = db.query(PricelistRxItem).order_by(PricelistRxItem.id).all() if normalized_catalog in {"all", "rx"} else []
    pricelist_rx_groups = db.query(PricelistRxGroup).order_by(PricelistRxGroup.id).all() if normalized_catalog in {"all", "rx"} else []
    pricelist_mkl_items = db.query(PricelistMklItem).order_by(PricelistMklItem.id).all() if normalized_catalog in {"all", "mkl"} else []
    pricelist_mkl_groups = db.query(PricelistMklGroup).order_by(PricelistMklGroup.id).all() if normalized_catalog in {"all", "mkl"} else []
    manufacturers = db.query(Manufacturer).order_by(Manufacturer.id).all()
    countries = db.query(Country).order_by(Country.id).all()
    features = db.query(Feature).order_by(Feature.id).all()
    coefficients = db.query(Coefficient).order_by(Coefficient.id).all()
    custom_fields = db.query(CustomFieldDefinition).order_by(CustomFieldDefinition.id).all()
    custom_field_options = db.query(CustomFieldOption).order_by(CustomFieldOption.id).all()
    colors = db.query(Color).order_by(Color.id).all()
    products = db.query(Product).order_by(Product.id).all()
    product_characteristics = db.query(ProductCharacteristic).order_by(ProductCharacteristic.id).all()

    datasets = {
        "pricelist_items": _serialize_rows(pricelist_items, [c.name for c in PricelistItem.__table__.columns]),
        "pricelist_groups": _serialize_rows(pricelist_groups, [c.name for c in PricelistGroup.__table__.columns]),
        "pricelist_rx_items": _serialize_rows(pricelist_rx_items, [c.name for c in PricelistRxItem.__table__.columns]),
        "pricelist_rx_groups": _serialize_rows(pricelist_rx_groups, [c.name for c in PricelistRxGroup.__table__.columns]),
        "pricelist_mkl_items": _serialize_rows(pricelist_mkl_items, [c.name for c in PricelistMklItem.__table__.columns]),
        "pricelist_mkl_groups": _serialize_rows(pricelist_mkl_groups, [c.name for c in PricelistMklGroup.__table__.columns]),
        "manufacturers": _serialize_rows(manufacturers, [c.name for c in Manufacturer.__table__.columns]),
        "countries": _serialize_rows(countries, [c.name for c in Country.__table__.columns]),
        "features": _serialize_rows(features, [c.name for c in Feature.__table__.columns]),
        "coefficients": _serialize_rows(coefficients, [c.name for c in Coefficient.__table__.columns]),
        "custom_field_definitions": _serialize_rows(custom_fields, [c.name for c in CustomFieldDefinition.__table__.columns]),
        "custom_field_options": _serialize_rows(custom_field_options, [c.name for c in CustomFieldOption.__table__.columns]),
        "colors": _serialize_rows(colors, [c.name for c in Color.__table__.columns]),
        "products": _serialize_rows(products, [c.name for c in Product.__table__.columns]),
        "product_characteristics": _serialize_rows(product_characteristics, [c.name for c in ProductCharacteristic.__table__.columns]),
    }

    static_urls = _collect_static_urls(pricelist_items, pricelist_rx_items, pricelist_mkl_items, manufacturers, features)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        meta = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "mosoptika pricelist export",
            "catalog": normalized_catalog,
            "static_urls_count": len(static_urls),
        }
        zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        zf.writestr("db/pricelist_related.json", json.dumps(datasets, ensure_ascii=False, indent=2))

        sql_chunks = []
        for table_name, rows in datasets.items():
            sql_chunks.append(_build_insert_sql(table_name, rows))
        zf.writestr("db/pricelist_related.sql", "\n".join(sql_chunks))

        static_index: list[dict] = []
        for url in static_urls:
            file_data = _read_static_file_bytes(url)
            if not file_data:
                static_index.append({"url": url, "saved": False})
                continue
            archive_name, raw = file_data
            zf.writestr(archive_name, raw)
            static_index.append({"url": url, "saved": True, "path": archive_name, "size": len(raw)})

        zf.writestr("static/index.json", json.dumps(static_index, ensure_ascii=False, indent=2))

    buf.seek(0)
    filename = f"pricelist-export-{normalized_catalog}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(buf, media_type="application/zip", headers=headers)
