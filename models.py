from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, ForeignKey, Table, Numeric, Text, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    hashed_password = Column(String(256), nullable=False)
    first_name = Column(String(128), nullable=True)
    last_name = Column(String(128), nullable=True)
    patronymic = Column(String(128), nullable=True)
    telegram_id = Column(String(64), nullable=True)
    phone = Column(String(64), nullable=True)
    birth_date = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # Push и бейдж непрочитанного: при False — не слать FCM и не показывать счётчик (веб).
    chat_notifications_enabled = Column(Boolean, default=True, nullable=False)
    avatar_url = Column(String(1024), nullable=True)
    chat_wallpaper_id = Column(Integer, ForeignKey("chat_wallpapers.id", ondelete="SET NULL"), nullable=True)
    chat_wallpaper_url = Column(String(1024), nullable=True)
    # Цвет сотрудника в графике работ (hex/rgb строка).
    schedule_color = Column(String(32), nullable=True)

    groups = relationship("Group", secondary="user_groups", back_populates="users")


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    users = relationship("User", secondary="user_groups", back_populates="groups")


user_groups = Table(
    "user_groups",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", Integer, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)


# --- Справочники ---

class Organization(Base):
    __tablename__ = "organizations"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), nullable=False)


class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), nullable=False)


class Warehouse(Base):
    __tablename__ = "warehouses"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0, server_default="0")
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    manager_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # {"weekly": {"mon": {"open":"10:00","close":"20:00"}, ...}, "holidays": [{"date":"2026-01-01","closed":true}, ...]}
    opening_hours = Column(JSONB, nullable=True)
    hide_in_reports = Column(Boolean, default=False, nullable=False, server_default="false")

    organization_rel = relationship("Organization", foreign_keys=[organization_id])
    manager_rel = relationship("User", foreign_keys=[manager_id])


class Author(Base):
    __tablename__ = "authors"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), nullable=False)


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(512), nullable=False)
    code = Column(String(128), nullable=True)
    characteristics = relationship("ProductCharacteristic", back_populates="product", cascade="all, delete-orphan")


class ProductCharacteristic(Base):
    __tablename__ = "product_characteristics"
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(256), nullable=False)
    product = relationship("Product", back_populates="characteristics")


class VatRate(Base):
    __tablename__ = "vat_rates"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False)


class OrderStatus(Base):
    __tablename__ = "order_statuses"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)


class Priority(Base):
    __tablename__ = "priorities"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)


class ExpenseArticle(Base):
    """Статьи расходов (справочник для отчётов консультантов)."""
    __tablename__ = "expense_articles"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), nullable=False)


class TakenReason(Base):
    """Справочник «Взято за что»."""
    __tablename__ = "taken_reasons"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), nullable=False)


class TakenSource(Base):
    """Справочник «Откуда взято»."""
    __tablename__ = "taken_sources"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), nullable=False)


class DebtReason(Base):
    """Справочник «Долг за что»."""
    __tablename__ = "debt_reasons"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), nullable=False)


class Color(Base):
    __tablename__ = "colors"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), unique=True, nullable=False)


class Manufacturer(Base):
    __tablename__ = "manufacturers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    country_id = Column(Integer, ForeignKey("countries.id"), nullable=True)
    image_url = Column(String(512), nullable=True)
    catalog_pdf_url = Column(String(512), nullable=True)
    border_color = Column(String(64), nullable=True)
    show_in_lens_catalog = Column(Boolean, default=True, nullable=False)
    open_pdf_in_lens_catalog = Column(Boolean, default=True, nullable=False)
    show_country_in_lens_catalog = Column(Boolean, default=True, nullable=False)
    show_description_in_lens_catalog = Column(Boolean, default=True, nullable=False)

    country = relationship("Country", back_populates="manufacturers")


class Country(Base):
    __tablename__ = "countries"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), nullable=False)
    code = Column(String(3), nullable=True)
    
    manufacturers = relationship("Manufacturer", back_populates="country")


class Feature(Base):
    __tablename__ = "features"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), nullable=False)
    icon_url = Column(String(512), nullable=True)
    color = Column(String(256), nullable=True)  # deprecated: use colors[0]
    colors = Column(JSONB, nullable=True)  # list of color names


class Coefficient(Base):
    __tablename__ = "coefficients"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(32), unique=True, nullable=False)


class PricelistGroup(Base):
    __tablename__ = "pricelist_groups"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), unique=True, nullable=False)
    sort_index = Column(Integer, default=500, nullable=False)
    display_properties_in_list = Column(Boolean, default=True, nullable=False)
    display_as_tiles = Column(Boolean, default=False, nullable=False)
    tiles_per_page = Column(Integer, default=4, nullable=False)
    admin_only = Column(Boolean, default=False, nullable=False)


class PricelistItem(Base):
    __tablename__ = "pricelist_items"
    id = Column(Integer, primary_key=True, index=True)
    manufacturer_id = Column(Integer, ForeignKey("manufacturers.id", ondelete="SET NULL"), nullable=True)
    lens_name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    full_description = Column(Text, nullable=True)
    barcode = Column(String(128), nullable=True)  # deprecated: use barcodes[0]
    barcodes = Column(JSONB, nullable=True)  # list of barcode strings
    photo_url = Column(String(512), nullable=True)  # deprecated: use photo_urls[0]
    photo_urls = Column(JSONB, nullable=True)  # list of image URLs
    sph = Column(String(512), nullable=True)
    cyl = Column(String(512), nullable=True)
    step = Column(String(256), nullable=True)
    diameters = Column(String(256), nullable=True)
    price = Column(Numeric(12, 2), nullable=False)
    # Порядок позиции внутри своей группы (чем меньше, тем выше).
    sort_index = Column(Integer, default=500, nullable=False)
    # Цена «от N» — в UI показываем префикс «от», сумма в price
    price_from = Column(Boolean, default=False, nullable=False)
    is_promo = Column(Boolean, default=False, nullable=False)
    # UV-защита (отдельный флаг, не зависит от справочника особенностей)
    uv_protection = Column(Boolean, default=False, nullable=False)
    # Материал линзы/покрытия (одним значением, без списка/динамического добавления)
    material = Column(Text, nullable=True)
    lens_id = Column(Integer, nullable=True)
    group = Column(String(128), nullable=False)
    # МКЛ может хранить список ВС (например, "8.5/9.0, 8.5/9.0, ..."), поэтому 32 символов недостаточно.
    coefficient = Column(String(512), nullable=True)
    feature_ids = Column(JSONB, nullable=True)
    feature_colors = Column(JSONB, nullable=True)  # { "feature_id": "color_name" } для особенностей с выбором цвета
    custom_values = Column(JSONB, nullable=True)  # { "field_key": string|boolean|null }
    hide_detail_link = Column(Boolean, default=False, nullable=False)
    hide_photo = Column(Boolean, default=False, nullable=False)
    enable_transposition_calc = Column(Boolean, default=False, nullable=False)
    admin_only = Column(Boolean, default=False, nullable=False)

    manufacturer = relationship("Manufacturer", backref="pricelist_items")


class PricelistRxGroup(Base):
    """Группы раздела «Прайс RX» — отдельно от pricelist_groups (склад)."""

    __tablename__ = "pricelist_rx_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), unique=True, nullable=False)
    sort_index = Column(Integer, default=500, nullable=False)
    display_properties_in_list = Column(Boolean, default=True, nullable=False)
    display_as_tiles = Column(Boolean, default=False, nullable=False)
    tiles_per_page = Column(Integer, default=4, nullable=False)
    admin_only = Column(Boolean, default=False, nullable=False)


class PricelistRxItem(Base):
    """Позиции прайса RX — отдельная таблица, не shared с pricelist_items."""

    __tablename__ = "pricelist_rx_items"

    id = Column(Integer, primary_key=True, index=True)
    manufacturer_id = Column(Integer, ForeignKey("manufacturers.id", ondelete="SET NULL"), nullable=True)
    lens_name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    full_description = Column(Text, nullable=True)
    barcode = Column(String(128), nullable=True)
    barcodes = Column(JSONB, nullable=True)
    photo_url = Column(String(512), nullable=True)
    photo_urls = Column(JSONB, nullable=True)
    sph = Column(String(512), nullable=True)
    cyl = Column(String(512), nullable=True)
    step = Column(String(256), nullable=True)
    diameters = Column(String(256), nullable=True)
    price = Column(Numeric(12, 2), nullable=False)
    # Порядок позиции внутри своей группы (чем меньше, тем выше).
    sort_index = Column(Integer, default=500, nullable=False)
    price_from = Column(Boolean, default=False, nullable=False)
    is_promo = Column(Boolean, default=False, nullable=False)
    uv_protection = Column(Boolean, default=False, nullable=False)
    material = Column(Text, nullable=True)
    lens_id = Column(Integer, nullable=True)
    group = Column(String(128), nullable=False)
    coefficient = Column(String(32), nullable=True)
    feature_ids = Column(JSONB, nullable=True)
    feature_colors = Column(JSONB, nullable=True)
    custom_values = Column(JSONB, nullable=True)
    hide_detail_link = Column(Boolean, default=False, nullable=False)
    hide_photo = Column(Boolean, default=False, nullable=False)
    enable_transposition_calc = Column(Boolean, default=False, nullable=False)
    admin_only = Column(Boolean, default=False, nullable=False)

    manufacturer = relationship("Manufacturer", backref="pricelist_rx_items")


class PricelistMklGroup(Base):
    """Группы раздела «Прайс МКЛ» — отдельно от склада и RX."""

    __tablename__ = "pricelist_mkl_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), unique=True, nullable=False)
    sort_index = Column(Integer, default=500, nullable=False)
    display_properties_in_list = Column(Boolean, default=True, nullable=False)
    display_as_tiles = Column(Boolean, default=False, nullable=False)
    tiles_per_page = Column(Integer, default=4, nullable=False)
    admin_only = Column(Boolean, default=False, nullable=False)


class PricelistMklItem(Base):
    """Позиции прайса МКЛ — отдельная таблица, не shared с pricelist_items."""

    __tablename__ = "pricelist_mkl_items"

    id = Column(Integer, primary_key=True, index=True)
    manufacturer_id = Column(Integer, ForeignKey("manufacturers.id", ondelete="SET NULL"), nullable=True)
    lens_name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    full_description = Column(Text, nullable=True)
    barcode = Column(String(128), nullable=True)
    barcodes = Column(JSONB, nullable=True)
    photo_url = Column(String(512), nullable=True)
    photo_urls = Column(JSONB, nullable=True)
    sph = Column(String(512), nullable=True)
    cyl = Column(String(512), nullable=True)
    step = Column(String(256), nullable=True)
    diameters = Column(String(256), nullable=True)
    price = Column(Numeric(12, 2), nullable=False)
    sort_index = Column(Integer, default=500, nullable=False)
    price_from = Column(Boolean, default=False, nullable=False)
    is_promo = Column(Boolean, default=False, nullable=False)
    uv_protection = Column(Boolean, default=False, nullable=False)
    material = Column(Text, nullable=True)
    lens_id = Column(Integer, nullable=True)
    group = Column(String(128), nullable=False)
    coefficient = Column(String(32), nullable=True)
    feature_ids = Column(JSONB, nullable=True)
    feature_colors = Column(JSONB, nullable=True)
    custom_values = Column(JSONB, nullable=True)
    hide_detail_link = Column(Boolean, default=False, nullable=False)
    hide_photo = Column(Boolean, default=False, nullable=False)
    enable_transposition_calc = Column(Boolean, default=False, nullable=False)
    admin_only = Column(Boolean, default=False, nullable=False)

    manufacturer = relationship("Manufacturer", backref="pricelist_mkl_items")


class CustomFieldDefinition(Base):
    __tablename__ = "custom_field_definitions"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(128), unique=True, nullable=False)
    label = Column(String(256), nullable=False)
    field_type = Column(String(32), nullable=False)  # string | string_multi | select | multi_select | checkbox | reference
    is_required = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    # Visibility by pricelist catalog in create/edit/detail forms.
    show_in_warehouse = Column(Boolean, default=True, nullable=False)
    show_in_rx = Column(Boolean, default=True, nullable=False)
    show_in_mkl = Column(Boolean, default=True, nullable=False)
    sort_index = Column(Integer, default=500, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    options = relationship("CustomFieldOption", back_populates="field", cascade="all, delete-orphan")


class DriveItem(Base):
    """
    Узел «Общего диска»: папка или файл.
    Доступ по умолчанию — только владелец; расшаривание по пользователям и группам.
    """

    __tablename__ = "drive_items"

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("drive_items.id", ondelete="CASCADE"), nullable=True, index=True)
    is_folder = Column(Boolean, nullable=False, default=True)
    name = Column(String(512), nullable=False)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    file_url = Column(String(1024), nullable=True)
    mime_type = Column(String(256), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    shared_user_ids = Column(JSONB, nullable=True)  # [user_id, ...]
    shared_group_ids = Column(JSONB, nullable=True)  # [group_id, ...]
    # Иконка папки: либо URL (картинка), либо "preset:<name>".
    folder_icon = Column(String(1024), nullable=True)
    # Публичная ссылка на файл (без авторизации).
    public_enabled = Column(Boolean, nullable=False, default=False)
    public_token = Column(String(64), nullable=True, unique=True, index=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    parent = relationship("DriveItem", remote_side=[id], backref="children")
    owner = relationship("User", backref="drive_items", foreign_keys=[owner_user_id])


class CustomFieldOption(Base):
    __tablename__ = "custom_field_options"
    id = Column(Integer, primary_key=True, index=True)
    field_id = Column(Integer, ForeignKey("custom_field_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    value = Column(Text, nullable=False)
    sort_index = Column(Integer, default=500, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    field = relationship("CustomFieldDefinition", back_populates="options")


class PricelistPublicationJob(Base):
    """Scheduled/queued publication for warehouse/rx/mkl pricelist items."""

    __tablename__ = "pricelist_publication_jobs"

    id = Column(Integer, primary_key=True, index=True)
    catalog = Column(String(16), nullable=False, index=True)  # warehouse | rx | mkl
    action = Column(String(16), nullable=False, default="upsert")  # create | update | upsert
    target_item_id = Column(Integer, nullable=True, index=True)
    payload_json = Column(JSONB, nullable=False)
    batch_code = Column(String(64), nullable=True, index=True)
    batch_name = Column(String(255), nullable=True)
    publish_at = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="pending", index=True)  # pending | applied | cancelled | failed
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    applied_at = Column(DateTime(timezone=True), nullable=True)
    error_text = Column(Text, nullable=True)

    created_by = relationship("User", foreign_keys=[created_by_user_id])


class PortalTask(Base):
    __tablename__ = "portal_tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="new")
    priority = Column(String(32), nullable=False, default="medium")
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assignee_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_by = relationship("User", foreign_keys=[created_by_user_id])
    assignee = relationship("User", foreign_keys=[assignee_user_id])


class TrainingArticle(Base):
    __tablename__ = "training_articles"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(256), nullable=False)
    section = Column(String(128), nullable=False, default="Общее")
    preview_image_url = Column(String(512), nullable=True)
    content_html = Column(Text, nullable=False, default="")
    is_published = Column(Boolean, default=True, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_by = relationship("User")


class TrainingArticleView(Base):
    """Просмотры статей обучения (одна строка на пару статья + пользователь)."""

    __tablename__ = "training_article_views"
    __table_args__ = (UniqueConstraint("article_id", "user_id", name="uq_training_article_view_user"),)

    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(Integer, ForeignKey("training_articles.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    view_count = Column(Integer, nullable=False, default=1)
    first_viewed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_viewed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    article = relationship("TrainingArticle")
    user = relationship("User")


class TrainingCourse(Base):
    """Курс: структура блоков, тестов и экзамена хранится в payload (JSON)."""

    __tablename__ = "training_courses"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=False, default="")
    preview_image_url = Column(String(512), nullable=True)
    is_published = Column(Boolean, default=False, nullable=False)
    payload = Column(JSONB, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_by = relationship("User", foreign_keys=[created_by_user_id])


class TrainingUserCourseProgress(Base):
    """Прогресс пользователя по курсу (JSON)."""

    __tablename__ = "training_user_course_progress"

    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_training_progress_user_course"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("training_courses.id", ondelete="CASCADE"), nullable=False, index=True)
    progress = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", foreign_keys=[user_id])
    course = relationship("TrainingCourse", foreign_keys=[course_id])


class NormativeAct(Base):
    __tablename__ = "normative_acts"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(256), nullable=False)
    section = Column(String(128), nullable=False, default="Общее")
    preview_image_url = Column(String(512), nullable=True)
    attachment_url = Column(String(512), nullable=True)
    attachment_filename = Column(String(256), nullable=True)
    visible_user_ids = Column(JSONB, nullable=True)  # если пусто/null — документ виден всем
    content_html = Column(Text, nullable=False, default="")
    is_published = Column(Boolean, default=True, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_by = relationship("User")
    signatures = relationship("NormativeActSignature", back_populates="act", cascade="all, delete-orphan")


class NormativeActSignature(Base):
    __tablename__ = "normative_act_signatures"
    id = Column(Integer, primary_key=True, index=True)
    act_id = Column(Integer, ForeignKey("normative_acts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    signed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_normative_act_user_unique", "act_id", "user_id", unique=True),
    )

    act = relationship("NormativeAct", back_populates="signatures")
    user = relationship("User")


class SupplyTicket(Base):
    __tablename__ = "supply_tickets"
    id = Column(Integer, primary_key=True, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True)
    request_text = Column(Text, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(32), nullable=False, default="open")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_by = relationship("User", foreign_keys=[created_by_user_id])
    warehouse = relationship("Warehouse")
    messages = relationship("SupplyTicketMessage", back_populates="ticket", cascade="all, delete-orphan")


class SupplyTicketMessage(Base):
    __tablename__ = "supply_ticket_messages"
    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("supply_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    ticket = relationship("SupplyTicket", back_populates="messages")
    author = relationship("User", foreign_keys=[author_user_id])


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String(32), default="new")
    order_status_id = Column(Integer, ForeignKey("order_statuses.id", ondelete="SET NULL"), nullable=True)
    priority_id = Column(Integer, ForeignKey("priorities.id", ondelete="SET NULL"), nullable=True)
    consultant_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    consultant = Column(String(256), nullable=True)
    order_number = Column(String(64), nullable=True)
    date = Column(Date, nullable=True)
    readiness_date = Column(Date, nullable=True)
    client_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    client = Column(String(256), nullable=True)
    age = Column(Integer, nullable=True)
    phone = Column(String(64), nullable=True)
    sms = Column(Boolean, default=False)
    call = Column(String(128), nullable=True)
    total = Column(Numeric(15, 2), default=0)
    od_sph = Column(String(32), nullable=True)
    od_cyl = Column(String(32), nullable=True)
    od_axis = Column(String(32), nullable=True)
    od_pd = Column(String(32), nullable=True)
    od_add_deg = Column(String(32), nullable=True)
    od_height = Column(String(32), nullable=True)
    diametr = Column(String(32), nullable=True)
    os_sph = Column(String(32), nullable=True)
    os_cyl = Column(String(32), nullable=True)
    os_axis = Column(String(32), nullable=True)
    os_pd = Column(String(32), nullable=True)
    os_add_deg = Column(String(32), nullable=True)
    os_height = Column(String(32), nullable=True)
    for_what = Column(String(512), nullable=True)
    frame_article = Column(String(128), nullable=True)
    print_info = Column(Text, nullable=True)
    promotion = Column(Boolean, default=False)
    prescription_order = Column(Boolean, default=False)
    child_order = Column(Boolean, default=False)
    no_lenses = Column(Boolean, default=False)
    client_frame_lenses = Column(Boolean, default=False)
    case_included = Column(Boolean, default=False)
    from_client_words = Column(Boolean, default=False)
    doctor_prescription = Column(Boolean, default=False)
    doctor_name = Column(String(256), nullable=True)
    clinic = Column(String(256), nullable=True)
    by_client_glasses = Column(Boolean, default=False)
    demo_mo = Column(Boolean, default=False)
    price_includes_vat = Column(Boolean, default=False)
    prepayment = Column(Numeric(15, 2), nullable=True)
    card = Column(Boolean, default=False)
    cash = Column(Boolean, default=False)
    extra_payment = Column(Numeric(15, 2), nullable=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    department_id = Column(Integer, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    warehouse = Column(String(256), nullable=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True)
    author_id = Column(Integer, ForeignKey("authors.id", ondelete="SET NULL"), nullable=True)
    ship_one_date = Column(Boolean, default=False)
    ship_date = Column(Date, nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    synced_to_1c_at = Column(DateTime(timezone=True), nullable=True)
    warehouse_manager_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.line_number")
    order_status_rel = relationship("OrderStatus", foreign_keys=[order_status_id])
    priority_rel = relationship("Priority", foreign_keys=[priority_id])
    organization_rel = relationship("Organization", foreign_keys=[organization_id])
    department_rel = relationship("Department", foreign_keys=[department_id])
    warehouse_rel = relationship("Warehouse", foreign_keys=[warehouse_id])
    author_rel = relationship("Author", foreign_keys=[author_id])
    warehouse_manager_rel = relationship("User", foreign_keys=[warehouse_manager_id])


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    line_number = Column(Integer, default=1)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    characteristic_id = Column(Integer, ForeignKey("product_characteristics.id", ondelete="SET NULL"), nullable=True)
    nomenclature = Column(String(512), nullable=True)
    quantity = Column(Numeric(15, 3), default=0)
    price = Column(Numeric(15, 2), default=0)
    percent_manual = Column(Numeric(8, 2), nullable=True)
    sum_manual = Column(Numeric(15, 2), nullable=True)
    sum = Column(Numeric(15, 2), default=0)
    vat_rate_id = Column(Integer, ForeignKey("vat_rates.id", ondelete="SET NULL"), nullable=True)

    order = relationship("Order", back_populates="items")
    product_rel = relationship("Product", foreign_keys=[product_id])
    characteristic_rel = relationship("ProductCharacteristic", foreign_keys=[characteristic_id])
    vat_rate_rel = relationship("VatRate", foreign_keys=[vat_rate_id])


class Order1cExchangeLog(Base):
    """Журнал входящих тел от 1С (POST /api/order/, /api/order/1c-intake/)."""

    __tablename__ = "order_1c_exchange_logs"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    request_path = Column(String(512), nullable=False)
    client_ip = Column(String(128), nullable=False)
    content_type = Column(String(512), nullable=True)
    body_length = Column(Integer, nullable=False)
    body_encoding = Column(String(16), nullable=False, default="utf-8")  # utf-8 | base64
    body_text = Column(Text, nullable=True)
    json_parse_ok = Column(Boolean, nullable=False, default=False)
    payload_is_object = Column(Boolean, nullable=False, default=False)
    order_created = Column(Boolean, nullable=False, default=False)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    error_message = Column(Text, nullable=True)

    order = relationship("Order", foreign_keys=[order_id])


class DailyReport(Base):
    """Отчёт консультанта: точка (склад), суммы, возвраты, Z-отчёт и сверка по картам."""
    __tablename__ = "daily_reports"
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    """Момент первой отправки (не черновика); для сопоставления с временем создания записи черновика."""
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    is_draft = Column(Boolean, default=False, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True)
    utro = Column(Numeric(15, 2), nullable=True)
    revenue = Column(Numeric(15, 2), nullable=True)  # Выручка
    nal = Column(Numeric(15, 2), nullable=True)  # Нал
    bn = Column(Numeric(15, 2), nullable=True)  # Бн (безнал)
    zp = Column(Numeric(15, 2), nullable=True)  # Зп (устарело, оставлено для старых записей)
    ost = Column(Numeric(15, 2), nullable=True)  # Ост (расчётный)
    ost_fact = Column(Numeric(15, 2), nullable=True)  # Остаток наличных факт (для следующей смены → «утро»)
    has_returns = Column(Boolean, default=False, nullable=False)
    return_bn = Column(Numeric(15, 2), nullable=True)  # Сумма возвратов по безналу
    return_nal = Column(Numeric(15, 2), nullable=True)  # Сумма возвратов по налу
    returns_details = Column(JSONB, nullable=True)  # [{"date_check": str, "consultant_last_name": str, "amount": float}, ...]
    bn_card_reconciliation = Column(Numeric(15, 2), nullable=True)  # Безнал сверка итогов
    bn_z_report = Column(Numeric(15, 2), nullable=True)  # Безнал Z-отчёт
    extra_payments = Column(JSONB, nullable=True)  # [{"amount": float, "order_number": str}, ...]
    vyhod = Column(Numeric(15, 2), nullable=True)  # Выход (блок Зарплата)
    percent = Column(Numeric(8, 2), nullable=True)  # Процент (блок Зарплата)
    vzyala = Column(Numeric(15, 2), nullable=True)  # Взяла (блок Зарплата), сумма по строкам или вручную
    vzyala_details = Column(JSONB, nullable=True)  # [{"order_number": str, "amount": float, "warehouse_id": int|null}, ...]
    dolg = Column(Numeric(15, 2), nullable=True)  # Долг (блок Зарплата)
    dolg_details = Column(JSONB, nullable=True)  # [{"order_number": str, "amount": float, "warehouse_id": int|null}, ...]
    has_expenses = Column(Boolean, default=False, nullable=False)
    expenses = Column(JSONB, nullable=True)  # [{"amount": float, "expense_article_id": int}, ...]
    z_report_urls = Column(JSONB, nullable=True)  # список URL файлов Z-отчёта
    card_reconciliation_urls = Column(JSONB, nullable=True)  # список URL файлов сверки по картам
    has_encashment = Column(Boolean, default=False, nullable=False)
    encashment_nal = Column(Numeric(15, 2), nullable=True)  # сумма инкассации (нал)
    encashment_bn = Column(Numeric(15, 2), nullable=True)  # сумма инкассации (безнал)
    # Погашение ручных удержаний в отчёте: [{"withholding_id": int, "amount": float}, ...]
    withholding_details = Column(JSONB, nullable=True)

    user = relationship("User", backref="daily_reports")
    warehouse = relationship("Warehouse", backref="daily_reports")


class ManualEmployeeDebt(Base):
    """Долг сотруднику, внесённый администратором вне сменного отчёта (мотивация и т.п.); зачитывается через «Взято» как обычный долг."""

    __tablename__ = "manual_employee_debts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Numeric(15, 2), nullable=False)
    debt_reason_id = Column(Integer, ForeignKey("debt_reasons.id", ondelete="SET NULL"), nullable=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True)
    report_month = Column(String(32), nullable=True)
    order_number = Column(String(128), nullable=True, default="")
    note = Column(Text, nullable=True)
    debt_row_uid = Column(String(64), nullable=False, unique=True, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", foreign_keys=[user_id])
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    warehouse = relationship("Warehouse", foreign_keys=[warehouse_id])
    debt_reason_rel = relationship("DebtReason", foreign_keys=[debt_reason_id])


class CentralCashPayout(Base):
    """Выплата сотруднику из центральной кассы (учёт отдельно от сменных отчётов)."""

    __tablename__ = "central_cash_payouts"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Календарный день, с которого сумма доступна на балансе сотрудника (FIFO «Взято»).
    balance_effective_date = Column(Date, nullable=False, index=True)
    paid_to_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Numeric(15, 2), nullable=False)
    taken_source_id = Column(Integer, ForeignKey("taken_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    note = Column(Text, nullable=True)
    recorded_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    paid_to = relationship("User", foreign_keys=[paid_to_user_id])
    recorded_by = relationship("User", foreign_keys=[recorded_by_user_id])
    taken_source = relationship("TakenSource", foreign_keys=[taken_source_id])


class EncashmentReceipt(Base):
    """Отметка «инкассация получена» по точке за календарный период (для отчёта /reports/encashment)."""
    __tablename__ = "encashment_receipts"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "period_from", "period_to", name="uq_encashment_receipt_wh_period"),
    )

    id = Column(Integer, primary_key=True, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True)
    period_from = Column(Date, nullable=False)
    period_to = Column(Date, nullable=False)
    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    received_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    warehouse = relationship("Warehouse", foreign_keys=[warehouse_id])
    received_by = relationship("User", foreign_keys=[received_by_user_id])


class ManualWithholding(Base):
    """Ручное удержание по пользователю (отдельно от блока «Взято» в отчётах)."""

    __tablename__ = "manual_withholdings"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Numeric(15, 2), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True, index=True)
    report_month = Column(String(32), nullable=True)
    reason = Column(String(256), nullable=True)
    note = Column(Text, nullable=True)
    recorded_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    closed = Column(Boolean, default=False, nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Пока False — видно только админу на /reports/withholding; в ЛК сотрудника не попадает.
    published_to_lk = Column(Boolean, default=False, nullable=False, index=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    published_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Отчёт, указанный админом в форме («Забрано в отчёте»).
    linked_report_id = Column(Integer, ForeignKey("daily_reports.id", ondelete="SET NULL"), nullable=True, index=True)

    user = relationship("User", foreign_keys=[user_id])
    warehouse = relationship("Warehouse", foreign_keys=[warehouse_id])
    recorded_by = relationship("User", foreign_keys=[recorded_by_user_id])
    closed_by = relationship("User", foreign_keys=[closed_by_user_id])
    published_by = relationship("User", foreign_keys=[published_by_user_id])
    linked_report = relationship("DailyReport", foreign_keys=[linked_report_id])


class WorkScheduleDraft(Base):
    """Черновик графика работы (несколько версий). payload: {\"weeks\": { weekStartISO: { \"точка|дата\": \"ФИО\" } } }"""
    __tablename__ = "work_schedule_drafts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(256), nullable=False)
    payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    user = relationship("User", foreign_keys=[user_id])


class WorkSchedulePublished(Base):
    """Опубликованный график — один актуальный срез для главной страницы."""
    __tablename__ = "work_schedule_published"
    id = Column(Integer, primary_key=True)  # всегда 1
    payload = Column(JSONB, nullable=False)
    published_at = Column(DateTime(timezone=True), server_default=func.now())
    published_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    published_by = relationship("User", foreign_keys=[published_by_id])


class WorkScheduleConfirmation(Base):
    """Подтверждение консультантом ознакомления с опубликованным графиком на неделю (понедельник week_start)."""

    __tablename__ = "work_schedule_confirmations"
    __table_args__ = (UniqueConstraint("user_id", "week_start", name="uq_work_schedule_conf_user_week"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    week_start = Column(String(10), nullable=False, index=True)
    confirmed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", foreign_keys=[user_id])


# --- Chat (common + private dialogs) ---


class GeneralChatMember(Base):
    __tablename__ = "general_chat_members"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    joined_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    left_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", backref="general_chat_members")


class PrivateDialog(Base):
    __tablename__ = "private_dialogs"

    id = Column(Integer, primary_key=True, index=True)
    user1_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    user2_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Скрыт из списка у пользователя (удалить чат у себя); собеседник видит диалог как обычно.
    user1_hidden = Column(Boolean, default=False, nullable=False)
    user2_hidden = Column(Boolean, default=False, nullable=False)

    user1 = relationship("User", foreign_keys=[user1_id])
    user2 = relationship("User", foreign_keys=[user2_id])


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    # private dialogs use private_dialog_id; general chat uses NULL here
    private_dialog_id = Column(Integer, ForeignKey("private_dialogs.id", ondelete="CASCADE"), nullable=True)
    group_dialog_id = Column(Integer, ForeignKey("group_chat_dialogs.id", ondelete="CASCADE"), nullable=True)
    # Сообщения бота поддержки: оба dialog id NULL, bot_thread_user_id = id пользователя-треда
    bot_thread_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    # Диалог с нейросетью: оба dialog id NULL, gigachat_thread_user_id = id пользователя (персональный тред)
    gigachat_thread_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    reply_to_message_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)

    sender_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # NULL for system messages
    text = Column(Text, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    ack_required = Column(Boolean, default=False, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    edited_at = Column(DateTime(timezone=True), nullable=True)

    attachments = relationship("ChatMessageAttachment", back_populates="message", cascade="all, delete-orphan")

    sender = relationship("User", foreign_keys=[sender_user_id])
    bot_thread_user = relationship("User", foreign_keys=[bot_thread_user_id])
    gigachat_thread_user = relationship("User", foreign_keys=[gigachat_thread_user_id])
    private_dialog = relationship("PrivateDialog", foreign_keys=[private_dialog_id])
    group_dialog = relationship("GroupChatDialog", foreign_keys=[group_dialog_id])
    reply_to_message = relationship("ChatMessage", remote_side=[id], foreign_keys=[reply_to_message_id])


class ChatBotThreadMeta(Base):
    """Статус обращения в поддержку (по user_id треда)."""

    __tablename__ = "chat_bot_thread_meta"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    closed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ChatMessageAttachment(Base):
    __tablename__ = "chat_message_attachments"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(512), nullable=False)
    media_type = Column(String(16), nullable=False)  # "image" | "video" | "audio"
    filename = Column(String(256), nullable=True)
    mime_type = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    message = relationship("ChatMessage", back_populates="attachments")


class ChatMessageRead(Base):
    __tablename__ = "chat_message_reads"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    read_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        # unique constraint: one user can mark message as read only once
        Index("idx_message_user_read", "message_id", "user_id", unique=True),
    )


class ChatPoll(Base):
    __tablename__ = "chat_polls"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False, unique=True)
    question = Column(String(512), nullable=False)
    allows_multiple = Column(Boolean, default=False, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    message = relationship("ChatMessage", backref="poll", uselist=False)
    options = relationship("ChatPollOption", back_populates="poll", cascade="all, delete-orphan", order_by="ChatPollOption.position")
    votes = relationship("ChatPollVote", back_populates="poll", cascade="all, delete-orphan")


class ChatPollOption(Base):
    __tablename__ = "chat_poll_options"

    id = Column(Integer, primary_key=True, index=True)
    poll_id = Column(Integer, ForeignKey("chat_polls.id", ondelete="CASCADE"), nullable=False, index=True)
    text = Column(String(256), nullable=False)
    position = Column(Integer, nullable=False, default=0)

    poll = relationship("ChatPoll", back_populates="options")
    votes = relationship("ChatPollVote", back_populates="option", cascade="all, delete-orphan")


class ChatPollVote(Base):
    __tablename__ = "chat_poll_votes"

    id = Column(Integer, primary_key=True, index=True)
    poll_id = Column(Integer, ForeignKey("chat_polls.id", ondelete="CASCADE"), nullable=False, index=True)
    option_id = Column(Integer, ForeignKey("chat_poll_options.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    voted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    poll = relationship("ChatPoll", back_populates="votes")
    option = relationship("ChatPollOption", back_populates="votes")

    __table_args__ = (
        Index("idx_chat_poll_vote_user_option", "poll_id", "user_id", "option_id", unique=True),
    )


class ChatMessageAcknowledgment(Base):
    """Нажатие «Ознакомиться» на публикации в канале."""
    __tablename__ = "chat_message_acknowledgments"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    acknowledged_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_message_user_ack", "message_id", "user_id", unique=True),
    )


class ChatMessageReaction(Base):
    __tablename__ = "chat_message_reactions"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    emoji = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_message_user_reaction", "message_id", "user_id", unique=True),
    )


class GroupChatDialog(Base):
    __tablename__ = "group_chat_dialogs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    image_url = Column(String(1024), nullable=True)
    forbid_exit = Column(Boolean, default=False, nullable=False, server_default="false")
    is_channel = Column(Boolean, default=False, nullable=False, server_default="false")
    # Участники видят только свои сообщения; админы группы и CRM-админы — всю переписку.
    members_see_own_only = Column(Boolean, default=False, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    members = relationship("GroupChatMember", back_populates="dialog", cascade="all, delete-orphan")


class ChatWallpaper(Base):
    """Библиотека обоев для фона чата."""

    __tablename__ = "chat_wallpapers"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(128), nullable=False)
    url = Column(String(1024), nullable=False)
    thumb_url = Column(String(1024), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, default=True, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ChatFolder(Base):
    """Пользовательская папка для организации чатов в списке."""

    __tablename__ = "chat_folders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", backref="chat_folders")
    items = relationship("ChatFolderItem", back_populates="folder", cascade="all, delete-orphan", order_by="ChatFolderItem.position")


class ChatFolderItem(Base):
    __tablename__ = "chat_folder_items"

    id = Column(Integer, primary_key=True, index=True)
    folder_id = Column(Integer, ForeignKey("chat_folders.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_type = Column(String(16), nullable=False)  # private | group
    private_dialog_id = Column(Integer, ForeignKey("private_dialogs.id", ondelete="CASCADE"), nullable=True)
    group_dialog_id = Column(Integer, ForeignKey("group_chat_dialogs.id", ondelete="CASCADE"), nullable=True)
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    folder = relationship("ChatFolder", back_populates="items")

    __table_args__ = (
        Index(
            "idx_chat_folder_item_unique",
            "folder_id",
            "chat_type",
            "private_dialog_id",
            "group_dialog_id",
            unique=True,
        ),
    )


class GroupChatMember(Base):
    __tablename__ = "group_chat_members"

    id = Column(Integer, primary_key=True, index=True)
    dialog_id = Column(Integer, ForeignKey("group_chat_dialogs.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    notifications_enabled = Column(Boolean, default=True, nullable=False)
    joined_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    left_at = Column(DateTime(timezone=True), nullable=True)

    dialog = relationship("GroupChatDialog", back_populates="members")
    user = relationship("User")


class PushDeviceToken(Base):
    __tablename__ = "push_device_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String(512), nullable=False, unique=True, index=True)
    platform = Column(String(32), nullable=False, default="android")
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")


class WebPushSubscription(Base):
    __tablename__ = "web_push_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint = Column(String(1024), nullable=False, unique=True, index=True)
    p256dh = Column(String(512), nullable=False)
    auth = Column(String(512), nullable=False)
    platform = Column(String(32), nullable=False, default="web")
    user_agent = Column(String(1024), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")


class ChatBirthdayReminderRule(Base):
    """Правило напоминания о дне рождения сотрудника в чат."""

    __tablename__ = "chat_birthday_reminder_rules"

    id = Column(Integer, primary_key=True, index=True)
    subject_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    enabled = Column(Boolean, default=True, nullable=False)
    days_before = Column(Integer, default=0, nullable=False)
    notify_hour = Column(Integer, default=9, nullable=False)
    notify_minute = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    subject_user = relationship("User", foreign_keys=[subject_user_id])
    recipients = relationship(
        "ChatBirthdayReminderRecipient",
        back_populates="rule",
        cascade="all, delete-orphan",
    )


class ChatBirthdayReminderRecipient(Base):
    __tablename__ = "chat_birthday_reminder_recipients"
    __table_args__ = (UniqueConstraint("rule_id", "recipient_user_id", name="uq_bday_reminder_recipient"),)

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("chat_birthday_reminder_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    rule = relationship("ChatBirthdayReminderRule", back_populates="recipients")
    recipient_user = relationship("User", foreign_keys=[recipient_user_id])


class ChatBirthdayReminderSentLog(Base):
    """Защита от повторной отправки в тот же календарный день."""

    __tablename__ = "chat_birthday_reminder_sent_log"
    __table_args__ = (
        UniqueConstraint("rule_id", "recipient_user_id", "fire_date", name="uq_bday_reminder_sent"),
    )

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("chat_birthday_reminder_rules.id", ondelete="CASCADE"), nullable=False)
    recipient_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    fire_date = Column(Date, nullable=False)
    sent_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MobileAppClient(Base):
    """Регистрация мобильных/WebView клиентов: версии APK/OTA и последняя активность."""

    __tablename__ = "mobile_app_clients"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(128), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    warehouse_id = Column(Integer, nullable=True, index=True)
    app_slug = Column(String(64), nullable=False, default="apkprice", index=True)
    native_version = Column(String(64), nullable=True)
    native_build = Column(Integer, nullable=True)
    bundle_version = Column(String(128), nullable=True)
    offline_data_version = Column(String(128), nullable=True)
    platform = Column(String(32), nullable=False, default="android")
    os_version = Column(String(64), nullable=True)
    device_model = Column(String(128), nullable=True)
    device_manufacturer = Column(String(128), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User")

