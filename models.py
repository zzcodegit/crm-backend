from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, ForeignKey, Table, Numeric, Text, Index
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
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

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
    manager_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

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
    is_promo = Column(Boolean, default=False, nullable=False)
    # UV-защита (отдельный флаг, не зависит от справочника особенностей)
    uv_protection = Column(Boolean, default=False, nullable=False)
    # Материал линзы/покрытия (одним значением, без списка/динамического добавления)
    material = Column(Text, nullable=True)
    lens_id = Column(Integer, nullable=True)
    group = Column(String(128), nullable=False)
    coefficient = Column(String(32), nullable=True)
    feature_ids = Column(JSONB, nullable=True)
    feature_colors = Column(JSONB, nullable=True)  # { "feature_id": "color_name" } для особенностей с выбором цвета
    custom_values = Column(JSONB, nullable=True)  # { "field_key": string|boolean|null }

    manufacturer = relationship("Manufacturer", backref="pricelist_items")


class CustomFieldDefinition(Base):
    __tablename__ = "custom_field_definitions"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(128), unique=True, nullable=False)
    label = Column(String(256), nullable=False)
    field_type = Column(String(32), nullable=False)  # string | select | checkbox | reference
    is_required = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_index = Column(Integer, default=500, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    options = relationship("CustomFieldOption", back_populates="field", cascade="all, delete-orphan")


class CustomFieldOption(Base):
    __tablename__ = "custom_field_options"
    id = Column(Integer, primary_key=True, index=True)
    field_id = Column(Integer, ForeignKey("custom_field_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    value = Column(Text, nullable=False)
    sort_index = Column(Integer, default=500, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    field = relationship("CustomFieldDefinition", back_populates="options")


class PortalTask(Base):
    __tablename__ = "portal_tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="new")
    priority = Column(String(32), nullable=False, default="medium")
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    created_by = relationship("User")


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


class DailyReport(Base):
    """Отчёт консультанта: точка (склад), суммы, возвраты, Z-отчёт и сверка по картам."""
    __tablename__ = "daily_reports"
    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_draft = Column(Boolean, default=False, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True)
    utro = Column(Numeric(15, 2), nullable=True)
    revenue = Column(Numeric(15, 2), nullable=True)  # Выручка
    nal = Column(Numeric(15, 2), nullable=True)  # Нал
    bn = Column(Numeric(15, 2), nullable=True)  # Бн (безнал)
    zp = Column(Numeric(15, 2), nullable=True)  # Зп (устарело, оставлено для старых записей)
    ost = Column(Numeric(15, 2), nullable=True)  # Ост
    has_returns = Column(Boolean, default=False, nullable=False)
    return_bn = Column(Numeric(15, 2), nullable=True)  # Сумма возвратов по безналу
    return_nal = Column(Numeric(15, 2), nullable=True)  # Сумма возвратов по налу
    returns_details = Column(JSONB, nullable=True)  # [{"date_check": str, "consultant_last_name": str, "amount": float}, ...]
    bn_card_reconciliation = Column(Numeric(15, 2), nullable=True)  # Безнал сверка итогов
    bn_z_report = Column(Numeric(15, 2), nullable=True)  # Безнал Z-отчёт
    extra_payments = Column(JSONB, nullable=True)  # [{"amount": float, "order_number": str}, ...]
    vyhod = Column(Numeric(15, 2), nullable=True)  # Выход (блок Зарплата)
    percent = Column(Numeric(8, 2), nullable=True)  # Процент (блок Зарплата)
    vzyala = Column(Numeric(15, 2), nullable=True)  # Взяла (блок Зарплата)
    dolg = Column(Numeric(15, 2), nullable=True)  # Долг (блок Зарплата)
    z_report_urls = Column(JSONB, nullable=True)  # список URL файлов Z-отчёта
    card_reconciliation_urls = Column(JSONB, nullable=True)  # список URL файлов сверки по картам

    user = relationship("User", backref="daily_reports")
    warehouse = relationship("Warehouse", backref="daily_reports")


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

    user1 = relationship("User", foreign_keys=[user1_id])
    user2 = relationship("User", foreign_keys=[user2_id])


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    # private dialogs use private_dialog_id; general chat uses NULL here
    private_dialog_id = Column(Integer, ForeignKey("private_dialogs.id", ondelete="CASCADE"), nullable=True)
    group_dialog_id = Column(Integer, ForeignKey("group_chat_dialogs.id", ondelete="CASCADE"), nullable=True)
    reply_to_message_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)

    sender_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # NULL for system messages
    text = Column(Text, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    edited_at = Column(DateTime(timezone=True), nullable=True)

    attachments = relationship("ChatMessageAttachment", back_populates="message", cascade="all, delete-orphan")

    sender = relationship("User", foreign_keys=[sender_user_id])
    private_dialog = relationship("PrivateDialog", foreign_keys=[private_dialog_id])
    group_dialog = relationship("GroupChatDialog", foreign_keys=[group_dialog_id])
    reply_to_message = relationship("ChatMessage", remote_side=[id], foreign_keys=[reply_to_message_id])


class ChatMessageAttachment(Base):
    __tablename__ = "chat_message_attachments"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(512), nullable=False)
    media_type = Column(String(16), nullable=False)  # "image" | "video"
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


class GroupChatDialog(Base):
    __tablename__ = "group_chat_dialogs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    members = relationship("GroupChatMember", back_populates="dialog", cascade="all, delete-orphan")


class GroupChatMember(Base):
    __tablename__ = "group_chat_members"

    id = Column(Integer, primary_key=True, index=True)
    dialog_id = Column(Integer, ForeignKey("group_chat_dialogs.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
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

