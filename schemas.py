from datetime import date as date_type, datetime
from pydantic import BaseModel, Field, field_validator, model_validator


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
    phone: str | None = None
    birth_date: date_type | None = None
    is_active: bool
    last_login_at: datetime | None = None
    group_ids: list[int] = []
    chat_notifications_enabled: bool = True
    avatar_url: str | None = None
    chat_wallpaper_id: int | None = None
    chat_wallpaper_url: str | None = None
    schedule_color: str | None = None

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
    is_reportnik: bool = False
    role: str = "user"  # "admin" | "manager" | "consultant" | "user" — для однозначного определения на фронте
    impersonator_username: str | None = None  # логин администратора, если сессия «вход под пользователем»


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
    phone: str | None = None
    birth_date: date_type | None = None


class UserUpdate(BaseModel):
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    patronymic: str | None = None
    telegram_id: str | None = None
    phone: str | None = None
    birth_date: date_type | None = None
    schedule_color: str | None = None
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
    border_color: str | None = None
    show_in_lens_catalog: bool = True
    open_pdf_in_lens_catalog: bool = True
    show_country_in_lens_catalog: bool = True
    show_description_in_lens_catalog: bool = True
    country: CountryResponse | None = None

    class Config:
        from_attributes = True


class ManufacturerCreate(BaseModel):
    name: str
    description: str | None = None
    country_id: int | None = None
    image_url: str | None = None
    catalog_pdf_url: str | None = None
    border_color: str | None = None
    show_in_lens_catalog: bool = True
    open_pdf_in_lens_catalog: bool = True
    show_country_in_lens_catalog: bool = True
    show_description_in_lens_catalog: bool = True


class ManufacturerUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    country_id: int | None = None
    image_url: str | None = None
    catalog_pdf_url: str | None = None
    border_color: str | None = None
    show_in_lens_catalog: bool | None = None
    open_pdf_in_lens_catalog: bool | None = None
    show_country_in_lens_catalog: bool | None = None
    show_description_in_lens_catalog: bool | None = None


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
    display_as_tiles: bool = False
    tiles_per_page: int = 4
    admin_only: bool = False

    class Config:
        from_attributes = True


class PricelistGroupCreate(BaseModel):
    name: str
    sort_index: int = 500
    display_properties_in_list: bool = True
    display_as_tiles: bool = False
    tiles_per_page: int = 4
    admin_only: bool = False


class PricelistGroupUpdate(BaseModel):
    name: str | None = None
    sort_index: int | None = None
    display_properties_in_list: bool | None = None
    display_as_tiles: bool | None = None
    tiles_per_page: int | None = None
    admin_only: bool | None = None


# --- Pricelist ---


class BarcodeEntry(BaseModel):
    """Штрихкод с опциональными ценой и описанием."""
    code: str
    price: float | None = None
    description: str | None = None


class BarcodeSection(BaseModel):
    """Именованная группа штрихкодов (name=None — общий список без заголовка)."""
    name: str | None = None
    items: list[BarcodeEntry] = []


class PricelistItemResponse(BaseModel):
    id: int
    manufacturer_id: int | None = None
    manufacturer_name: str = ""
    manufacturer_image_url: str | None = None
    manufacturer_country_name: str | None = None
    lens_name: str
    description: str | None = None
    full_description: str | None = None
    barcode: str | None = None
    barcodes: list[BarcodeEntry] = []
    """Группы штрихкодов; для старых записей — одна секция без названия."""
    barcode_sections: list[BarcodeSection] = []
    photo_url: str | None = None
    photo_urls: list[str] = []
    sph: str | None = None
    cyl: str | None = None
    step: str | None = None
    diameters: str | None = None
    price: float
    sort_index: int = 500
    price_from: bool = False
    is_promo: bool = False
    uv_protection: bool = False
    material: str | None = None
    lens_id: int | None = None
    group: str
    coefficient: str | None = None
    feature_ids: list[int] = []
    feature_colors: dict[str, list[str]] = {}  # feature_id (str) -> список названий цветов
    custom_values: dict[str, str | bool | list[str] | None] | None = None
    hide_detail_link: bool = False
    hide_photo: bool = False
    enable_transposition_calc: bool = False
    admin_only: bool = False

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
    barcode_sections: list[BarcodeSection] | None = None
    photo_url: str | None = None
    photo_urls: list[str] | None = None
    sph: str | None = None
    cyl: str | None = None
    step: str | None = None
    diameters: str | None = None
    price: float
    sort_index: int = 500
    price_from: bool = False
    is_promo: bool = False
    uv_protection: bool = False
    material: str | None = None
    lens_id: int | None = None
    group: str
    coefficient: str | None = None
    feature_ids: list[int] = []
    feature_colors: dict[str, list[str]] | None = None
    custom_values: dict[str, str | bool | list[str] | None] | None = None
    hide_detail_link: bool = False
    hide_photo: bool = False
    enable_transposition_calc: bool = False
    admin_only: bool = False
    publish_mode: str | None = "now"  # now | schedule
    publish_at: datetime | None = None

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
    barcode_sections: list[BarcodeSection] | None = None
    photo_url: str | None = None
    photo_urls: list[str] | None = None
    sph: str | None = None
    cyl: str | None = None
    step: str | None = None
    diameters: str | None = None
    price: float | None = None
    sort_index: int | None = None
    price_from: bool | None = None
    is_promo: bool | None = None
    uv_protection: bool | None = None
    material: str | None = None
    lens_id: int | None = None
    group: str | None = None
    coefficient: str | None = None
    feature_ids: list[int] | None = None
    feature_colors: dict[str, list[str]] | None = None
    custom_values: dict[str, str | bool | list[str] | None] | None = None
    hide_detail_link: bool | None = None
    hide_photo: bool | None = None
    enable_transposition_calc: bool | None = None
    admin_only: bool | None = None
    publish_mode: str | None = "now"  # now | schedule
    publish_at: datetime | None = None


class PricelistPublicationJobResponse(BaseModel):
    id: int
    catalog: str
    action: str
    target_item_id: int | None = None
    payload_json: dict
    batch_code: str | None = None
    batch_name: str | None = None
    publish_at: datetime
    status: str
    created_by_user_id: int | None = None
    created_at: datetime | None = None
    applied_at: datetime | None = None
    error_text: str | None = None

    class Config:
        from_attributes = True


class PricelistPublicationJobCreate(BaseModel):
    catalog: str  # warehouse | rx | mkl
    action: str = "create"  # create | update | upsert
    target_item_id: int | None = None
    payload_json: dict
    publish_at: datetime
    batch_code: str | None = None
    batch_name: str | None = None


class PricelistPublicationBatchAssign(BaseModel):
    job_ids: list[int]
    batch_name: str


class DriveItemBase(BaseModel):
    parent_id: int | None = None
    is_folder: bool = True
    name: str
    file_url: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    shared_user_ids: list[int] | None = None
    shared_group_ids: list[int] | None = None
    folder_icon: str | None = None


class DriveItemCreate(DriveItemBase):
    pass


class DriveItemUpdate(BaseModel):
    parent_id: int | None = None
    name: str | None = None
    shared_user_ids: list[int] | None = None
    shared_group_ids: list[int] | None = None
    folder_icon: str | None = None
    public_enabled: bool | None = None


class DriveItemCopyBody(BaseModel):
    """Копия в указанную папку; null — в ту же папку, что у оригинала."""
    parent_id: int | None = None


class DriveFolderPickerItem(BaseModel):
    id: int
    parent_id: int | None
    name: str

    class Config:
        from_attributes = True


class DrivePublicItemResponse(BaseModel):
    item_id: int
    name: str
    file_url: str | None
    mime_type: str | None
    size_bytes: int | None


class DriveBreadcrumbItem(BaseModel):
    id: int
    name: str


class DriveItemResponse(BaseModel):
    id: int
    parent_id: int | None
    is_folder: bool
    name: str
    owner_user_id: int
    file_url: str | None
    mime_type: str | None
    size_bytes: int | None
    shared_user_ids: list[int] | None
    shared_group_ids: list[int] | None
    folder_icon: str | None
    public_enabled: bool
    public_token: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


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
    show_in_warehouse: bool = True
    show_in_rx: bool = True
    show_in_mkl: bool = True
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
    show_in_warehouse: bool = True
    show_in_rx: bool = True
    show_in_mkl: bool = True
    sort_index: int = 500


class CustomFieldDefinitionUpdate(BaseModel):
    code: str | None = None
    label: str | None = None
    field_type: str | None = None
    is_required: bool | None = None
    is_active: bool | None = None
    show_in_warehouse: bool | None = None
    show_in_rx: bool | None = None
    show_in_mkl: bool | None = None
    sort_index: int | None = None


class PortalTaskResponse(BaseModel):
    id: int
    title: str
    description: str | None = None
    status: str
    priority: str
    created_by_user_id: int | None = None
    created_by_username: str | None = None
    assignee_user_id: int | None = None
    assignee_label: str | None = None
    due_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class TaskAssigneeOption(BaseModel):
    id: int
    username: str
    label: str


class PortalTaskCreate(BaseModel):
    title: str
    description: str | None = None
    status: str = "new"
    priority: str = "medium"
    assignee_user_id: int | None = None
    due_at: datetime | None = None


class PortalTaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    assignee_user_id: int | None = None
    due_at: datetime | None = None


class TrainingArticleResponse(BaseModel):
    id: int
    title: str
    section: str = "Общее"
    preview_image_url: str | None = None
    content_html: str
    is_published: bool
    created_by_user_id: int | None = None
    created_by_username: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class TrainingArticleListItem(BaseModel):
    id: int
    title: str
    section: str = "Общее"
    preview_image_url: str | None = None
    is_published: bool
    created_by_user_id: int | None = None
    created_by_username: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class TrainingArticleCreate(BaseModel):
    title: str
    section: str = "Общее"
    preview_image_url: str | None = None
    content_html: str = ""
    is_published: bool = True


class TrainingArticleUpdate(BaseModel):
    title: str | None = None
    section: str | None = None
    preview_image_url: str | None = None
    content_html: str | None = None
    is_published: bool | None = None


class TrainingArticleViewReportItem(BaseModel):
    user_id: int
    username: str
    display_name: str
    visited: bool
    first_viewed_at: datetime | None = None
    last_viewed_at: datetime | None = None
    view_count: int = 0


class TrainingArticleAnalyticsItem(BaseModel):
    article_id: int
    title: str
    section: str
    is_published: bool
    unique_viewers: int
    total_views: int
    last_viewed_at: datetime | None = None


class NormativeActResponse(BaseModel):
    id: int
    title: str
    section: str = "Общее"
    preview_image_url: str | None = None
    attachment_url: str | None = None
    attachment_filename: str | None = None
    visible_user_ids: list[int] = []
    content_html: str
    is_published: bool
    created_by_user_id: int | None = None
    created_by_username: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    signed_by_me: bool = False
    signed_at: datetime | None = None

    class Config:
        from_attributes = True


class NormativeActCreate(BaseModel):
    title: str
    section: str = "Общее"
    preview_image_url: str | None = None
    attachment_url: str | None = None
    attachment_filename: str | None = None
    visible_user_ids: list[int] = []
    content_html: str = ""
    is_published: bool = True


class NormativeActUpdate(BaseModel):
    title: str | None = None
    section: str | None = None
    preview_image_url: str | None = None
    attachment_url: str | None = None
    attachment_filename: str | None = None
    visible_user_ids: list[int] | None = None
    content_html: str | None = None
    is_published: bool | None = None


class NormativeActSignResponse(BaseModel):
    ok: bool = True
    signed_at: datetime | None = None


class NormativeActSignReportItem(BaseModel):
    user_id: int
    username: str
    display_name: str
    signed: bool
    signed_at: datetime | None = None


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


class VzyalaTakenItem(BaseModel):
    """Строка «взято» в зарплате: заказ, сумма, точка (склад)."""

    order_number: str = ""
    amount: float
    taken_reason_id: int | None = None
    taken_source_id: int | None = None
    order_percent: float | None = None
    report_month: str | None = None  # формат YYYY-MM (месяц) или YYYY-MM-DD (дата)
    warehouse_id: int | None = None
    linked_debt_row_uid: str | None = None
    linked_debt_report_id: int | None = None


class DolgTakenItem(BaseModel):
    """Строка «долг» в зарплате: заказ, сумма, точка (склад)."""

    order_number: str = ""
    amount: float
    debt_reason_id: int | None = None
    order_percent: float | None = None
    report_month: str | None = None  # формат YYYY-MM (месяц) или YYYY-MM-DD (дата)
    warehouse_id: int | None = None
    debt_row_uid: str | None = None
    admin_closed: bool | None = None
    closed_at: str | None = None


class ReportExpenseItem(BaseModel):
    amount: float
    expense_article_id: int
    taken_source_id: int | None = None


class WithholdingAppliedItem(BaseModel):
    """Погашение открытого ручного удержания в сменном отчёте (частично или полностью)."""

    withholding_id: int
    amount: float


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
    ost_fact: float | None = None
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
    vzyala: float | None = None  # взяла (блок Зарплата): при наличии vzyala_details = сумма строк
    vzyala_details: list[VzyalaTakenItem] = []
    dolg: float | None = None  # долг (блок Зарплата)
    dolg_details: list[DolgTakenItem] = []
    has_expenses: bool = False
    expenses: list[ReportExpenseItem] = []
    z_report_urls: list[str] = []
    card_reconciliation_urls: list[str] = []
    has_encashment: bool = False
    encashment_nal: float | None = None
    encashment_bn: float | None = None
    withholding_details: list[WithholdingAppliedItem] = []


class DailyReportAdminPatch(DailyReportCreate):
    """PATCH отчёта администратором: те же поля, плюс смена даты/времени создания и отправителя."""
    created_at: datetime | None = None
    submitted_at: datetime | None = None
    user_id: int | None = None  # смена пользователя-отправителя (консультант); только при явной передаче в теле


class DailyReportResponse(BaseModel):
    id: int
    created_at: datetime | None = None
    submitted_at: datetime | None = None
    user_id: int
    user_username: str = ""
    warehouse_id: int | None = None
    warehouse_name: str = ""
    utro: float | None = None
    revenue: float | None = None
    nal: float | None = None
    bn: float | None = None
    ost: float | None = None
    ost_fact: float | None = None
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
    vzyala_details: list[dict] = []
    dolg: float | None = None
    dolg_details: list[dict] = []
    has_expenses: bool = False
    expenses: list[dict] = []
    z_report_urls: list[str] = []
    card_reconciliation_urls: list[str] = []
    has_encashment: bool = False
    encashment_nal: float | None = None
    encashment_bn: float | None = None
    withholding_details: list[dict] = []

    class Config:
        from_attributes = True


class WarehouseLastOstResponse(BaseModel):
    warehouse_id: int
    ost: float | None = None
    last_report_created_at: datetime | None = None


class ExpenseSummaryRow(BaseModel):
    expense_article_id: int
    expense_article_name: str
    total_amount: float


class ExpenseDetailRow(BaseModel):
    """Одна строка расхода из сменного отчёта (для детализации)."""

    expense_article_id: int
    expense_article_name: str
    amount: float
    warehouse_name: str
    report_date: str  # YYYY-MM-DD
    seller_name: str


class ExpenseSummaryResponse(BaseModel):
    date_from: str
    date_to: str
    rows: list[ExpenseSummaryRow]
    grand_total: float
    detail_rows: list[ExpenseDetailRow] = []


class EncashmentReportItem(BaseModel):
    report_id: int
    report_date: str
    seller_name: str
    nal: float
    bn: float
    total: float


class EncashmentSummaryRow(BaseModel):
    report_id: int | None = None
    warehouse_id: int
    warehouse_name: str
    total_nal: float
    total_bn: float
    total: float
    """Календарные даты отчётов с инкассацией по точке (YYYY-MM-DD), по возрастанию."""
    report_dates: list[str] = []
    """Авторы сменных отчётов с инкассацией по точке за период (ФИО или логин), по алфавиту."""
    seller_names: list[str] = []
    received: bool = False
    received_at: str | None = None
    received_by_name: str | None = None
    report_items: list[EncashmentReportItem] = []


class EncashmentReceiptMarkRequest(BaseModel):
    warehouse_id: int
    date_from: str
    date_to: str


class EncashmentSummaryResponse(BaseModel):
    date_from: str
    date_to: str
    rows: list[EncashmentSummaryRow]
    grand_total_nal: float
    grand_total_bn: float
    grand_total: float


class AvailableDebtRow(BaseModel):
    debt_row_uid: str
    report_id: int
    report_created_at: datetime | None = None
    report_submitted_at: datetime | None = None
    amount: float
    order_number: str = ""
    debt_reason_id: int | None = None
    debt_reason_name: str | None = None
    report_month: str | None = None
    warehouse_id: int | None = None
    warehouse_name: str | None = None
    manual_debt_id: int | None = None
    admin_note: str | None = None


class AvailableDebtResponse(BaseModel):
    rows: list[AvailableDebtRow] = []


class DebtTakeEventItem(BaseModel):
    """Один зачёт долга из отчёта (не схлопывать несколько частей в один)."""

    amount: float
    report_id: int
    taken_at: datetime | None = None
    taken_user_id: int | None = None
    taken_user_name: str = ""
    taken_reason_id: int | None = None
    taken_reason_name: str | None = None


class DebtSummaryRow(BaseModel):
    debt_row_uid: str
    debt_report_id: int
    debt_created_at: datetime | None = None
    debt_submitted_at: datetime | None = None
    debt_user_id: int
    debt_user_name: str = ""
    debt_amount: float
    debt_order_number: str = ""
    debt_reason_id: int | None = None
    debt_reason_name: str | None = None
    debt_report_month: str | None = None
    debt_warehouse_id: int | None = None
    debt_warehouse_name: str | None = None
    taken_report_id: int | None = None
    taken_at: datetime | None = None
    taken_user_id: int | None = None
    taken_user_name: str | None = None
    taken_amount: float | None = None
    taken_reason_id: int | None = None
    taken_reason_name: str | None = None
    status: str = "open"  # open | taken
    debt_source: str = "report"  # report | manual
    manual_debt_id: int | None = None
    one_c_exchange_log_id: int | None = None
    admin_note: str | None = None
    take_events: list[DebtTakeEventItem] = []


class DebtSummaryResponse(BaseModel):
    rows: list[DebtSummaryRow] = []


class ManualDebtCreate(BaseModel):
    user_id: int
    amount: float
    debt_reason_id: int | None = None
    warehouse_id: int | None = None
    report_month: str | None = None
    order_number: str = ""
    note: str | None = None


class ManualDebtUpdate(BaseModel):
    """Частичное обновление ручной записи долга (админ)."""

    amount: float | None = None
    debt_reason_id: int | None = None
    warehouse_id: int | None = None
    report_month: str | None = None
    order_number: str | None = None
    note: str | None = None


class OneCDebtItemUpdate(BaseModel):
    """Корректировка строки bonus_arr из 1С (админ)."""

    amount: float | None = None
    warehouse_id: int | None = None
    report_month: str | None = None
    order_number: str | None = None
    note: str | None = None


class ManualDebtResponse(BaseModel):
    id: int
    user_id: int
    amount: float
    debt_row_uid: str
    debt_reason_id: int | None = None
    warehouse_id: int | None = None
    report_month: str | None = None
    order_number: str = ""
    note: str | None = None
    created_at: datetime | None = None


class TakenSummaryRow(BaseModel):
    row_key: str
    report_id: int
    report_created_at: datetime | None = None
    report_submitted_at: datetime | None = None
    user_id: int
    user_name: str = ""
    amount: float
    taken_reason_id: int | None = None
    taken_reason_name: str | None = None
    taken_source_id: int | None = None
    taken_source_name: str | None = None
    order_number: str = ""
    report_month: str | None = None
    warehouse_id: int | None = None
    warehouse_name: str | None = None
    linked_debt_row_uid: str | None = None
    linked_debt_report_id: int | None = None
    is_linked_debt_take: bool = False
    # Документ долга для колонки «Источник» (1С doc / отчёт / ручной).
    debt_source_label: str | None = None
    debt_source_kind: str | None = None  # 1c | report | manual
    # Причина долга из привязанной строки (как в расшифровке «Взято»).
    debt_reason_name: str | None = None


class TakenSummaryResponse(BaseModel):
    rows: list[TakenSummaryRow] = []


class EmployeeLedgerLine(BaseModel):
    at: datetime | None = None
    kind: str
    report_id: int | None = None
    manual_debt_id: int | None = None
    amount: float
    description: str
    taken_reason_name: str | None = None
    taken_source_name: str | None = None
    debt_source_label: str | None = None
    debt_source_kind: str | None = None
    debt_reason_name: str | None = None
    is_linked_debt_take: bool = False
    linked_debt_report_id: int | None = None


class EmployeeLedgerResponse(BaseModel):
    user_id: int
    user_name: str = ""
    remaining_debt_total: float
    vzyala_total: float
    vzyala_linked_debt_total: float
    lines: list[EmployeeLedgerLine] = []


class EmployeeSalaryWithholdingItem(BaseModel):
    """Открытое ручное удержание — для блока «Удержания» в отчёте."""

    id: int
    amount: float
    reason: str | None = None
    note: str | None = None
    report_month: str | None = None
    warehouse_name: str | None = None


class EmployeeSalaryBalanceResponse(BaseModel):
    """Выплаты из ЦК и «Взято» из отчётов. Ручные удержания на баланс не влияют."""

    user_id: int
    central_cash_issued: float
    vzyala_taken: float  # списано из пула ЦК строками «Взято» в отчётах (не больше issued)
    manual_withholdings: float = 0.0  # открытые ручные удержания (инфо, не в балансе)
    withholding_items: list[EmployeeSalaryWithholdingItem] = []
    balance: float  # остаток пула ЦК (>= 0)


class WorkScheduleWeeksPayload(BaseModel):
    """Недели: ключ — понедельник недели (YYYY-MM-DD), значение — ячейки «точка|день» → ФИО."""

    weeks: dict[str, dict[str, str]] = {}
    consultant_colors: dict[str, str] = Field(default_factory=dict)


class WorkScheduleDraftCreate(BaseModel):
    name: str
    payload: WorkScheduleWeeksPayload


class WorkScheduleDraftUpdate(BaseModel):
    name: str | None = None
    payload: WorkScheduleWeeksPayload | None = None


class WorkScheduleDraftResponse(BaseModel):
    id: int
    name: str
    payload: dict
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class WorkScheduleConfirmBody(BaseModel):
    """Подтверждение ознакомления с графиком на неделю (понедельник)."""

    week_start: str = Field(..., description="YYYY-MM-DD — понедельник недели")


class WorkScheduleMyConfirmationResponse(BaseModel):
    week_start: str
    confirmed: bool
    confirmed_at: datetime | None = None


class WorkScheduleConfirmationReportRow(BaseModel):
    user_id: int
    username: str
    display_name: str
    confirmed_at: datetime | None = None


class WorkScheduleConfirmationReportResponse(BaseModel):
    week_start: str
    total_consultants: int
    confirmed_count: int
    rows: list[WorkScheduleConfirmationReportRow]


class OrganizationResponse(RefResponse):
    pass
class DepartmentResponse(RefResponse):
    pass
class WarehouseDayHours(BaseModel):
    """Часы работы в один день недели."""

    open: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    close: str = Field(..., pattern=r"^\d{2}:\d{2}$")


class WarehouseWeeklyHours(BaseModel):
    mon: WarehouseDayHours | None = None
    tue: WarehouseDayHours | None = None
    wed: WarehouseDayHours | None = None
    thu: WarehouseDayHours | None = None
    fri: WarehouseDayHours | None = None
    sat: WarehouseDayHours | None = None
    sun: WarehouseDayHours | None = None


class WarehouseHolidayEntry(BaseModel):
    """Особый режим в конкретную дату (праздник и т.п.)."""

    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    closed: bool = False
    open: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    close: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")

    @model_validator(mode="after")
    def _hours_if_open(self):
        if not self.closed:
            if not self.open or not self.close:
                raise ValueError("Для рабочего дня укажите время открытия и закрытия")
        return self


class WarehouseOpeningHoursPayload(BaseModel):
    weekly: WarehouseWeeklyHours | None = None
    holidays: list[WarehouseHolidayEntry] = []


class WarehouseResponse(RefResponse):
    organization_id: int | None = None
    organization_name: str | None = None
    manager_id: int | None = None
    manager_name: str | None = None
    sort_order: int = 0
    opening_hours: dict | None = None
    hide_in_reports: bool = False

    class Config:
        from_attributes = True

    @model_validator(mode="wrap")
    @classmethod
    def add_manager(cls, data, handler):
        obj = handler(data)
        if hasattr(data, "organization_rel") and data.organization_rel:
            org = data.organization_rel
            obj.organization_id = org.id
            obj.organization_name = org.name
        if hasattr(data, "manager_rel") and data.manager_rel:
            u = data.manager_rel
            obj.manager_id = u.id
            parts = [u.first_name, u.last_name, u.patronymic]
            obj.manager_name = " ".join(p for p in parts if p and str(p).strip()) or u.username or None
        return obj


class WarehouseCreate(BaseModel):
    name: str
    organization_id: int | None = None
    manager_id: int | None = None
    sort_order: int = 0
    opening_hours: WarehouseOpeningHoursPayload | None = None
    hide_in_reports: bool = False


class WarehouseUpdate(BaseModel):
    name: str | None = None
    organization_id: int | None = None
    manager_id: int | None = None
    sort_order: int | None = None
    opening_hours: WarehouseOpeningHoursPayload | None = None
    hide_in_reports: bool | None = None


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
    avatar_url: str | None = None

    class Config:
        from_attributes = True


class ChatUserProfileResponse(BaseModel):
    """Контактные данные собеседника для экрана профиля в чате (как в Telegram)."""
    id: int
    username: str
    display_name: str
    avatar_url: str | None = None
    phone: str | None = None
    birth_date: date_type | None = None

    class Config:
        from_attributes = True


class ChatAttachmentResponse(BaseModel):
    id: int
    url: str
    media_type: str  # "image" | "video" | "audio"
    filename: str | None = None
    mime_type: str | None = None
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class ChatMessageSenderResponse(BaseModel):
    id: int
    username: str
    display_name: str
    avatar_url: str | None = None

    class Config:
        from_attributes = True


class ChatPollOptionResponse(BaseModel):
    id: int
    text: str
    position: int = 0
    vote_count: int = 0


class ChatPollResponse(BaseModel):
    id: int
    question: str
    allows_multiple: bool = False
    total_voters: int = 0
    my_option_ids: list[int] = []
    options: list[ChatPollOptionResponse] = []


class ChatPollCreateRequest(BaseModel):
    question: str
    options: list[str]
    allows_multiple: bool = False
    reply_to_message_id: int | None = None


class ChatPollVoteRequest(BaseModel):
    option_ids: list[int] = []


class ChatReactionSummary(BaseModel):
    emoji: str
    count: int = 0
    reacted_by_me: bool = False


class ChatMessageReactionRequest(BaseModel):
    emoji: str


class ChatBotThreadItem(BaseModel):
    user: ChatUserShortResponse
    last_message_text: str | None = None
    last_message_at: datetime | None = None
    unread_count: int = 0
    is_closed: bool = False
    closed_at: datetime | None = None


class ChatMessageResponse(BaseModel):
    id: int
    private_dialog_id: int | None = None
    group_dialog_id: int | None = None
    bot_thread_user_id: int | None = None
    gigachat_thread_user_id: int | None = None
    sender: ChatMessageSenderResponse | None = None  # NULL for system messages

    # For UI:
    # - if message was deleted -> "Сообщение было удалено"
    # - otherwise -> original text (может быть null, если только вложения)
    display_text: str | None = None
    is_deleted: bool = False

    created_at: datetime | None = None
    edited_at: datetime | None = None

    attachments: list[ChatAttachmentResponse] = []
    poll: ChatPollResponse | None = None
    reply_to_message_id: int | None = None
    reply_to_text: str | None = None
    reply_to_sender_name: str | None = None
    reply_to_is_deleted: bool = False
    
    is_read: bool = False  # Whether the message was read by the other party
    read_count: int = 0
    recipient_count: int = 0
    ack_required: bool = False
    ack_count: int = 0
    ack_recipient_count: int = 0
    user_acknowledged: bool = False
    reactions: list[ChatReactionSummary] = []

    class Config:
        from_attributes = True


class ChatMessageReadUserItem(BaseModel):
    user: ChatUserShortResponse
    read_at: datetime | None = None


class ChatMessageReadsResponse(BaseModel):
    message_id: int
    read: list[ChatMessageReadUserItem] = []
    unread: list[ChatMessageReadUserItem] = []
    recipient_count: int = 0


class ChatSharedMediaItem(BaseModel):
    message_id: int
    attachment_id: int | None = None
    url: str | None = None
    media_type: str | None = None
    filename: str | None = None
    mime_type: str | None = None
    link_url: str | None = None
    preview_text: str | None = None
    created_at: datetime | None = None
    sender_name: str | None = None


class ChatSharedMediaResponse(BaseModel):
    items: list[ChatSharedMediaItem] = []
    total: int = 0


class GeneralChatStatusResponse(BaseModel):
    """Сводка общего чата для списка диалогов (включая has_unread для бейджа)."""

    is_member: bool
    has_unread: bool = False
    last_message_text: str | None = None
    last_message_at: datetime | None = None


class PrivateDialogResponse(BaseModel):
    id: int
    other_user: ChatUserShortResponse
    last_message_text: str | None = None
    last_message_at: datetime | None = None
    has_unread: bool = False


class GroupChatDialogResponse(BaseModel):
    id: int
    name: str
    image_url: str | None = None
    forbid_exit: bool = False
    is_channel: bool = False
    members_see_own_only: bool = False
    notifications_enabled: bool = True
    last_message_text: str | None = None
    last_message_at: datetime | None = None
    has_unread: bool = False


class GroupChatNotificationsSettingsBody(BaseModel):
    enabled: bool


class GroupChatDialogCreateRequest(BaseModel):
    name: str
    member_ids: list[int] = []
    image_url: str | None = None
    forbid_exit: bool = False
    is_channel: bool = False
    members_see_own_only: bool = False


class GroupChatDialogUpdateRequest(BaseModel):
    name: str | None = None
    image_url: str | None = None
    forbid_exit: bool | None = None
    is_channel: bool | None = None
    members_see_own_only: bool | None = None


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


class ChatForwardMessageRequest(BaseModel):
    target_chat_type: str  # "general" | "private" | "group"
    target_dialog_id: int | None = None


class ChatUserSearchResponse(ChatUserShortResponse):
    pass


class ChatSearchMessageHit(BaseModel):
    message_id: int
    chat_type: str  # general | private | group | bot
    private_dialog_id: int | None = None
    group_dialog_id: int | None = None
    bot_thread_user_id: int | None = None
    chat_title: str
    preview_text: str | None = None
    sender_name: str | None = None
    created_at: datetime | None = None


class ChatSearchResponse(BaseModel):
    users: list[ChatUserShortResponse] = []
    messages: list[ChatSearchMessageHit] = []


class ChatNotificationSummaryResponse(BaseModel):
    unread_count: int
    last_message_text: str | None = None
    last_message_sender: str | None = None
    last_message_chat: str | None = None
    last_message_id: int | None = None
    last_message_chat_type: str | None = None
    last_message_dialog_id: int | None = None
    last_message_thread_user_id: int | None = None


class ChatNotificationsSettingsBody(BaseModel):
    enabled: bool


class ChatNotificationsSettingsResponse(BaseModel):
    chat_notifications_enabled: bool


class ChatWallpaperItemResponse(BaseModel):
    id: int
    title: str
    url: str
    thumb_url: str | None = None
    sort_order: int = 0

    class Config:
        from_attributes = True


class ChatWallpaperSettingsResponse(BaseModel):
    wallpaper_id: int | None = None
    wallpaper_url: str | None = None
    resolved_url: str | None = None


class ChatWallpaperSettingsBody(BaseModel):
    wallpaper_id: int | None = None
    wallpaper_url: str | None = None
    reset: bool = False


class ChatFolderItemResponse(BaseModel):
    id: int
    chat_type: str
    private_dialog_id: int | None = None
    group_dialog_id: int | None = None


class ChatFolderResponse(BaseModel):
    id: int
    name: str
    position: int = 0
    items: list[ChatFolderItemResponse] = []


class ChatFolderCreateRequest(BaseModel):
    name: str


class ChatFolderUpdateRequest(BaseModel):
    name: str | None = None
    position: int | None = None


class ChatFolderAddItemRequest(BaseModel):
    chat_type: str
    private_dialog_id: int | None = None
    group_dialog_id: int | None = None


class PushTokenRegisterRequest(BaseModel):
    token: str
    platform: str = "android"


class WebPushSubscribeRequest(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    platform: str = "web"


class CentralCashPayoutCreate(BaseModel):
    paid_to_user_id: int
    amount: float
    taken_source_id: int | None = None
    note: str | None = None


class CentralCashPayoutUpdate(BaseModel):
    """Частичное обновление выплаты из центральной кассы."""

    paid_to_user_id: int | None = None
    amount: float | None = None
    taken_source_id: int | None = None
    note: str | None = None


class CentralCashPayoutResponse(BaseModel):
    id: int
    created_at: datetime
    paid_to_user_id: int
    paid_to_name: str = ""
    amount: float
    taken_source_id: int | None = None
    taken_source_name: str | None = None
    note: str | None = None
    recorded_by_user_id: int | None = None
    recorded_by_name: str = ""

    class Config:
        from_attributes = True


# --- Chat birthday reminders ---


class ChatBirthdayReminderRuleInput(BaseModel):
    enabled: bool = True
    days_before: int = 0
    notify_time: str = "09:00"
    recipient_user_ids: list[int] = Field(default_factory=list)


class ChatBirthdayReminderRuleResponse(BaseModel):
    id: int
    enabled: bool
    days_before: int
    notify_time: str
    recipient_users: list[ChatUserShortResponse] = Field(default_factory=list)


class ChatBirthdayReminderSettingsResponse(BaseModel):
    subject_user_id: int
    subject_birth_date: date_type | None = None
    rules: list[ChatBirthdayReminderRuleResponse] = Field(default_factory=list)


class ChatBirthdayReminderSettingsUpdate(BaseModel):
    rules: list[ChatBirthdayReminderRuleInput] = Field(default_factory=list)
