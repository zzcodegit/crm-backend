from datetime import date as date_type, datetime
from pydantic import BaseModel, field_validator, model_validator


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    username: str
    first_name: str | None = None
    last_name: str | None = None
    patronymic: str | None = None
    telegram_id: str | None = None
    is_active: bool
    last_login_at: datetime | None = None
    group_ids: list[int] = []

    class Config:
        from_attributes = True

    @model_validator(mode="wrap")
    @classmethod
    def add_group_ids(cls, data, handler):
        obj = handler(data)
        if hasattr(data, "groups"):
            obj.group_ids = [g.id for g in data.groups]
        return obj


class MeResponse(UserResponse):
    is_admin: bool = False
    is_manager: bool = False
    is_consultant: bool = False
    role: str = "user"  # "admin" | "manager" | "consultant" | "user" — для однозначного определения на фронте


class UserLogin(BaseModel):
    username: str
    password: str


class InviteUserRequest(BaseModel):
    fio: str
    group_name: str | None = None


class SetupPasswordRequest(BaseModel):
    username: str
    password: str
    password_confirm: str

    @model_validator(mode="after")
    def validate_match(self):
        if self.password != self.password_confirm:
            raise ValueError("Пароли не совпадают")
        return self


class UserCreate(BaseModel):
    username: str
    password: str
    first_name: str | None = None
    last_name: str | None = None
    patronymic: str | None = None
    telegram_id: str | None = None


class UserUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    patronymic: str | None = None
    telegram_id: str | None = None
    is_active: bool | None = None
    password: str | None = None


# --- Groups ---

class GroupResponse(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class GroupCreate(BaseModel):
    name: str


class GroupMemberResponse(BaseModel):
    id: int
    username: str
    is_active: bool

    class Config:
        from_attributes = True


# --- Справочники ---

class RefResponse(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class RefCreate(BaseModel):
    name: str


class RefUpdate(BaseModel):
    name: str


class CountryResponse(BaseModel):
    id: int
    name: str
    code: str | None = None

    class Config:
        from_attributes = True


class ManufacturerResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    country_id: int | None = None
    image_url: str | None = None
    catalog_pdf_url: str | None = None
    country: CountryResponse | None = None

    class Config:
        from_attributes = True


class ManufacturerCreate(BaseModel):
    name: str
    description: str | None = None
    country_id: int | None = None
    image_url: str | None = None
    catalog_pdf_url: str | None = None


class ManufacturerUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    country_id: int | None = None
    image_url: str | None = None
    catalog_pdf_url: str | None = None


class FeatureResponse(BaseModel):
    id: int
    name: str
    icon_url: str | None = None
    color: str | None = None
    colors: list[str] = []

    class Config:
        from_attributes = True


class FeatureCreate(BaseModel):
    name: str
    icon_url: str | None = None
    color: str | None = None
    colors: list[str] | None = None


class FeatureUpdate(BaseModel):
    name: str | None = None
    icon_url: str | None = None
    color: str | None = None
    colors: list[str] | None = None


# --- Pricelist groups ---

class PricelistGroupResponse(BaseModel):
    id: int
    name: str
    sort_index: int = 0
    display_properties_in_list: bool = True

    class Config:
        from_attributes = True


class PricelistGroupCreate(BaseModel):
    name: str
    sort_index: int = 500
    display_properties_in_list: bool = True


class PricelistGroupUpdate(BaseModel):
    name: str | None = None
    sort_index: int | None = None
    display_properties_in_list: bool | None = None


# --- Pricelist ---


class BarcodeEntry(BaseModel):
    """Штрихкод с опциональными ценой и описанием."""
    code: str
    price: float | None = None
    description: str | None = None


class PricelistItemResponse(BaseModel):
    id: int
    manufacturer_id: int | None = None
    manufacturer_name: str = ""
    lens_name: str
    description: str | None = None
    full_description: str | None = None
    barcode: str | None = None
    barcodes: list[BarcodeEntry] = []
    photo_url: str | None = None
    photo_urls: list[str] = []
    sph: str | None = None
    cyl: str | None = None
    step: str | None = None
    diameters: str | None = None
    price: float
    is_promo: bool = False
    uv_protection: bool = False
    material: str | None = None
    lens_id: int | None = None
    group: str
    coefficient: str | None = None
    feature_ids: list[int] = []
    feature_colors: dict[str, list[str]] = {}  # feature_id (str) -> список названий цветов
    custom_values: dict[str, str | bool | list[str] | None] | None = None

    class Config:
        from_attributes = True


def _normalize_barcode(v: str | dict) -> BarcodeEntry:
    """Преобразует строку или dict в BarcodeEntry."""
    if isinstance(v, str):
        return BarcodeEntry(code=v.strip())
    if isinstance(v, dict):
        code = str(v.get("code", "")).strip()
        price_val = v.get("price")
        if price_val is not None:
            try:
                price_val = float(price_val) if isinstance(price_val, str) and price_val.strip() else float(price_val)
            except (TypeError, ValueError):
                price_val = None
        desc = v.get("description")
        desc = str(desc).strip() if desc is not None and desc != "" else None
        return BarcodeEntry(code=code, price=price_val, description=desc)
    raise ValueError("barcode must be str or dict")


class PricelistItemCreate(BaseModel):
    manufacturer_id: int
    lens_name: str
    description: str | None = None
    full_description: str | None = None
    barcode: str | None = None
    barcodes: list[BarcodeEntry] | None = None
    photo_url: str | None = None
    photo_urls: list[str] | None = None
    sph: str | None = None
    cyl: str | None = None
    step: str | None = None
    diameters: str | None = None
    price: float
    is_promo: bool = False
    uv_protection: bool = False
    material: str | None = None
    lens_id: int | None = None
    group: str
    coefficient: str | None = None
    feature_ids: list[int] = []
    feature_colors: dict[str, list[str]] | None = None
    custom_values: dict[str, str | bool | list[str] | None] | None = None

    @field_validator("barcodes", mode="before")
    @classmethod
    def normalize_barcodes_create(cls, v):
        if v is None:
            return None
        if not isinstance(v, list):
            return v
        return [_normalize_barcode(x) for x in v if (isinstance(x, str) and x.strip()) or (isinstance(x, dict) and x.get("code"))]


class PricelistBulkCreateRequest(BaseModel):
    items: list[PricelistItemCreate]


class PricelistItemUpdate(BaseModel):
    manufacturer_id: int | None = None
    lens_name: str | None = None
    description: str | None = None
    full_description: str | None = None
    barcode: str | None = None
    barcodes: list[BarcodeEntry] | None = None
    photo_url: str | None = None
    photo_urls: list[str] | None = None
    sph: str | None = None
    cyl: str | None = None
    step: str | None = None
    diameters: str | None = None
    price: float | None = None
    is_promo: bool | None = None
    uv_protection: bool | None = None
    material: str | None = None
    lens_id: int | None = None
    group: str | None = None
    coefficient: str | None = None
    feature_ids: list[int] | None = None
    feature_colors: dict[str, list[str]] | None = None
    custom_values: dict[str, str | bool | list[str] | None] | None = None

    @field_validator("barcodes", mode="before")
    @classmethod
    def normalize_barcodes_update(cls, v):
        if v is None:
            return None
        if not isinstance(v, list):
            return v
        return [_normalize_barcode(x) for x in v if (isinstance(x, str) and x.strip()) or (isinstance(x, dict) and x.get("code"))]


class CustomFieldOptionResponse(BaseModel):
    id: int
    value: str
    sort_index: int
    is_active: bool = True

    class Config:
        from_attributes = True


class CustomFieldOptionCreate(BaseModel):
    value: str
    sort_index: int = 500
    is_active: bool = True


class CustomFieldOptionUpdate(BaseModel):
    value: str | None = None
    sort_index: int | None = None
    is_active: bool | None = None


class CustomFieldDefinitionResponse(BaseModel):
    id: int
    code: str
    label: str
    field_type: str
    is_required: bool = False
    is_active: bool = True
    sort_index: int
    options: list[CustomFieldOptionResponse] = []

    class Config:
        from_attributes = True


class CustomFieldDefinitionCreate(BaseModel):
    code: str | None = None
    label: str
    field_type: str
    is_required: bool = False
    is_active: bool = True
    sort_index: int = 500


class CustomFieldDefinitionUpdate(BaseModel):
    code: str | None = None
    label: str | None = None
    field_type: str | None = None
    is_required: bool | None = None
    is_active: bool | None = None
    sort_index: int | None = None


class PortalTaskResponse(BaseModel):
    id: int
    title: str
    description: str | None = None
    status: str
    priority: str
    created_by_user_id: int | None = None
    created_by_username: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class PortalTaskCreate(BaseModel):
    title: str
    description: str | None = None
    status: str = "new"
    priority: str = "medium"


class PortalTaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None


class SupplyTicketResponse(BaseModel):
    id: int
    warehouse_id: int | None = None
    warehouse_name: str | None = None
    request_text: str
    created_by_user_id: int | None = None
    created_by_username: str | None = None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SupplyTicketCreate(BaseModel):
    warehouse_id: int | None = None
    request_text: str


class SupplyTicketStatusUpdate(BaseModel):
    status: str


class SupplyTicketMessageResponse(BaseModel):
    id: int
    ticket_id: int
    author_user_id: int | None = None
    author_username: str | None = None
    message: str
    created_at: datetime | None = None


class SupplyTicketMessageCreate(BaseModel):
    message: str


# --- Daily report (отчёт консультанта) ---
class ExtraPaymentItem(BaseModel):
    amount: float
    order_number: str = ""
    consultant_last_name: str | None = None


class ReturnDetailItem(BaseModel):
    date_check: str | None = None
    consultant_last_name: str | None = None
    return_reason: str | None = None
    amount: float | None = None


class ConsultantItem(BaseModel):
    id: int
    last_name: str


class DailyReportCreate(BaseModel):
    warehouse_id: int | None = None
    utro: float | None = None
    revenue: float | None = None
    nal: float | None = None
    bn: float | None = None
    ost: float | None = None
    is_draft: bool = False
    has_returns: bool = False
    return_bn: float | None = None
    return_nal: float | None = None
    returns_details: list[ReturnDetailItem] = []
    bn_card_reconciliation: float | None = None  # безнал сверка итогов
    bn_z_report: float | None = None  # безнал Z-отчёт
    extra_payments: list[ExtraPaymentItem] = []  # доплаты: сумма + номер заказа
    vyhod: float | None = None  # выход (блок Зарплата)
    percent: float | None = None  # процент (блок Зарплата)
    vzyala: float | None = None  # взяла (блок Зарплата)
    dolg: float | None = None  # долг (блок Зарплата)
    z_report_urls: list[str] = []
    card_reconciliation_urls: list[str] = []


class DailyReportResponse(BaseModel):
    id: int
    created_at: datetime | None = None
    user_id: int
    user_username: str = ""
    warehouse_id: int | None = None
    warehouse_name: str = ""
    utro: float | None = None
    revenue: float | None = None
    nal: float | None = None
    bn: float | None = None
    ost: float | None = None
    is_draft: bool = False
    has_returns: bool = False
    return_bn: float | None = None
    return_nal: float | None = None
    returns_details: list[dict] = []
    bn_card_reconciliation: float | None = None
    bn_z_report: float | None = None
    extra_payments: list[dict] = []
    vyhod: float | None = None
    percent: float | None = None
    vzyala: float | None = None
    dolg: float | None = None
    z_report_urls: list[str] = []
    card_reconciliation_urls: list[str] = []

    class Config:
        from_attributes = True


class WarehouseLastOstResponse(BaseModel):
    warehouse_id: int
    ost: float | None = None
    last_report_created_at: datetime | None = None


class OrganizationResponse(RefResponse):
    pass
class DepartmentResponse(RefResponse):
    pass
class WarehouseResponse(RefResponse):
    manager_id: int | None = None
    manager_name: str | None = None

    class Config:
        from_attributes = True

    @model_validator(mode="wrap")
    @classmethod
    def add_manager(cls, data, handler):
        obj = handler(data)
        if hasattr(data, "manager_rel") and data.manager_rel:
            u = data.manager_rel
            obj.manager_id = u.id
            parts = [u.first_name, u.last_name, u.patronymic]
            obj.manager_name = " ".join(p for p in parts if p and str(p).strip()) or u.username or None
        return obj


class WarehouseCreate(BaseModel):
    name: str
    manager_id: int | None = None


class WarehouseUpdate(BaseModel):
    name: str | None = None
    manager_id: int | None = None
class AuthorResponse(RefResponse):
    pass


class ProductResponse(BaseModel):
    id: int
    name: str
    code: str | None = None

    class Config:
        from_attributes = True


class ProductCreate(BaseModel):
    name: str
    code: str | None = None


class ProductUpdate(BaseModel):
    name: str | None = None
    code: str | None = None


class ProductCharacteristicResponse(BaseModel):
    id: int
    product_id: int
    name: str

    class Config:
        from_attributes = True


class ProductCharacteristicCreate(BaseModel):
    product_id: int
    name: str


class ProductCharacteristicUpdate(BaseModel):
    name: str | None = None


class VatRateResponse(RefResponse):
    pass


# --- Orders ---

class OrderItemResponse(BaseModel):
    id: int
    order_id: int
    line_number: int
    product_id: int | None = None
    characteristic_id: int | None = None
    nomenclature: str | None = None
    quantity: float = 0
    price: float = 0
    percent_manual: float | None = None
    sum_manual: float | None = None
    sum: float = 0
    vat_rate_id: int | None = None
    product_name: str | None = None
    characteristic_name: str | None = None
    vat_rate_name: str | None = None

    class Config:
        from_attributes = True


class OrderItemCreate(BaseModel):
    line_number: int = 1
    product_id: int | None = None
    product_name: str | None = None
    characteristic_id: int | None = None
    characteristic_name: str | None = None
    nomenclature: str | None = None
    quantity: float = 0
    price: float = 0
    percent_manual: float | None = None
    sum_manual: float | None = None
    sum: float = 0
    vat_rate_id: int | None = None
    vat_rate_name: str | None = None


class OrderResponse(BaseModel):
    id: int
    status: str | None = None
    order_status_id: int | None = None
    order_status_name: str | None = None
    priority_id: int | None = None
    priority_name: str | None = None
    consultant_id: int | None = None
    consultant: str | None = None
    order_number: str | None = None
    # Backend хранит эти поля как `date` в БД, но фронтенду/интерфейсу нужен корректный
    # time representation без "UTC->MSK" сдвига.
    # Поэтому возвращаем их как строку datetime в таймзоне Москвы.
    date: str | None = None
    readiness_date: str | None = None
    client_id: int | None = None
    client: str | None = None
    age: int | None = None
    phone: str | None = None
    sms: bool = False
    call: str | None = None
    prepayment: float | None = None
    card: bool = False
    cash: bool = False
    extra_payment: float | None = None
    od_sph: str | None = None
    od_cyl: str | None = None
    od_axis: str | None = None
    od_pd: str | None = None
    od_add_deg: str | None = None
    od_height: str | None = None
    diametr: str | None = None
    os_sph: str | None = None
    os_cyl: str | None = None
    os_axis: str | None = None
    os_pd: str | None = None
    os_add_deg: str | None = None
    os_height: str | None = None
    for_what: str | None = None
    frame_article: str | None = None
    print_info: str | None = None
    promotion: bool = False
    prescription_order: bool = False
    child_order: bool = False
    no_lenses: bool = False
    client_frame_lenses: bool = False
    case_included: bool = False
    from_client_words: bool = False
    doctor_prescription: bool = False
    doctor_name: str | None = None
    clinic: str | None = None
    by_client_glasses: bool = False
    demo_mo: bool = False
    price_includes_vat: bool = False
    organization_id: int | None = None
    organization_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    warehouse: str | None = None
    warehouse_id: int | None = None
    warehouse_name: str | None = None
    author_id: int | None = None
    author_name: str | None = None
    ship_one_date: bool = False
    ship_date: str | None = None
    total: float = 0
    comment: str | None = None
    created_at: datetime | None = None
    items: list[OrderItemResponse] = []

    class Config:
        from_attributes = True


class OrderCreate(BaseModel):
    order_status_name: str | None = None
    priority_name: str | None = None
    consultant: str | None = None
    consultant_id: int | None = None
    order_number: str | None = None
    date: str | None = None
    readiness_date: str | None = None
    client: str | None = None
    client_id: int | None = None
    age: int | None = None
    phone: str | None = None
    sms: bool = False
    call: str | None = None
    prepayment: float | None = None
    card: bool = False
    cash: bool = False
    extra_payment: float | None = None
    od_sph: str | None = None
    od_cyl: str | None = None
    od_axis: str | None = None
    od_pd: str | None = None
    od_add_deg: str | None = None
    od_height: str | None = None
    os_sph: str | None = None
    os_cyl: str | None = None
    os_axis: str | None = None
    os_pd: str | None = None
    os_add_deg: str | None = None
    os_height: str | None = None
    for_what: str | None = None
    frame_article: str | None = None
    print_info: str | None = None
    promotion: bool = False
    prescription_order: bool = False
    child_order: bool = False
    no_lenses: bool = False
    client_frame_lenses: bool = False
    case_included: bool = False
    from_client_words: bool = False
    doctor_prescription: bool = False
    doctor_name: str | None = None
    clinic: str | None = None
    by_client_glasses: bool = False
    demo_mo: bool = False
    price_includes_vat: bool = False
    organization_id: int | None = None
    organization_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    warehouse_id: int | None = None
    warehouse_name: str | None = None
    warehouse: str | None = None
    author_id: int | None = None
    author_name: str | None = None
    ship_one_date: bool = False
    ship_date: str | None = None
    total: float = 0
    comment: str | None = None
    items: list[OrderItemCreate] = []


class OrderUpdate(BaseModel):
    order_status_name: str | None = None
    priority_name: str | None = None
    consultant: str | None = None
    order_number: str | None = None
    date: str | None = None
    readiness_date: str | None = None
    client: str | None = None
    age: int | None = None
    phone: str | None = None
    sms: bool | None = None
    call: str | None = None
    prepayment: float | None = None
    card: bool | None = None
    cash: bool | None = None
    extra_payment: float | None = None
    od_sph: str | None = None
    od_cyl: str | None = None
    od_axis: str | None = None
    od_pd: str | None = None
    od_add_deg: str | None = None
    od_height: str | None = None
    os_sph: str | None = None
    os_cyl: str | None = None
    os_axis: str | None = None
    os_pd: str | None = None
    os_add_deg: str | None = None
    os_height: str | None = None
    for_what: str | None = None
    frame_article: str | None = None
    print_info: str | None = None
    promotion: bool | None = None
    prescription_order: bool | None = None
    child_order: bool | None = None
    no_lenses: bool | None = None
    client_frame_lenses: bool | None = None
    case_included: bool | None = None
    from_client_words: bool | None = None
    doctor_prescription: bool | None = None
    doctor_name: str | None = None
    clinic: str | None = None
    by_client_glasses: bool | None = None
    demo_mo: bool | None = None
    price_includes_vat: bool | None = None
    organization_id: int | None = None
    organization_name: str | None = None
    department_id: int | None = None
    department_name: str | None = None
    warehouse_id: int | None = None
    warehouse_name: str | None = None
    author_id: int | None = None
    author_name: str | None = None
    ship_one_date: bool | None = None
    ship_date: str | None = None
    total: float | None = None
    comment: str | None = None
    items: list[OrderItemCreate] | None = None


# --- Chat (common + private) ---


class ChatUserShortResponse(BaseModel):
    id: int
    username: str
    display_name: str
    is_active: bool

    class Config:
        from_attributes = True


class ChatAttachmentResponse(BaseModel):
    id: int
    url: str
    media_type: str  # "image" | "video"
    filename: str | None = None
    mime_type: str | None = None
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class ChatMessageSenderResponse(BaseModel):
    id: int
    username: str
    display_name: str

    class Config:
        from_attributes = True


class ChatMessageResponse(BaseModel):
    id: int
    private_dialog_id: int | None = None
    group_dialog_id: int | None = None
    sender: ChatMessageSenderResponse | None = None  # NULL for system messages

    # For UI:
    # - if message was deleted -> "Сообщение было удалено"
    # - otherwise -> original text (может быть null, если только вложения)
    display_text: str | None = None
    is_deleted: bool = False

    created_at: datetime | None = None
    edited_at: datetime | None = None

    attachments: list[ChatAttachmentResponse] = []
    reply_to_message_id: int | None = None
    reply_to_text: str | None = None
    reply_to_sender_name: str | None = None
    reply_to_is_deleted: bool = False
    
    is_read: bool = False  # Whether the message was read by the other party

    class Config:
        from_attributes = True


class PrivateDialogResponse(BaseModel):
    id: int
    other_user: ChatUserShortResponse
    last_message_text: str | None = None
    last_message_at: datetime | None = None


class GroupChatDialogResponse(BaseModel):
    id: int
    name: str
    last_message_text: str | None = None
    last_message_at: datetime | None = None


class GroupChatDialogCreateRequest(BaseModel):
    name: str
    member_ids: list[int] = []


class GroupChatMemberResponse(BaseModel):
    user: ChatUserShortResponse
    is_admin: bool
    is_active: bool
    joined_at: datetime | None = None
    left_at: datetime | None = None

    class Config:
        from_attributes = True


class ChatEditMessageRequest(BaseModel):
    text: str | None = None


class ChatUserSearchResponse(ChatUserShortResponse):
    pass


class ChatNotificationSummaryResponse(BaseModel):
    unread_count: int
    last_message_text: str | None = None
    last_message_sender: str | None = None
    last_message_chat: str | None = None
