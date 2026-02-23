from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Table, DateTime, JSON
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

# --- ТАБЛИЦЫ СВЯЗЕЙ ---
chart_page_association = Table(
    'chart_page_link', Base.metadata,
    Column('page_id', Integer, ForeignKey('pages.id')),
    Column('chart_id', Integer, ForeignKey('charts.id'))
)

chart_source_association = Table(
    'chart_source_link', Base.metadata,
    Column('chart_id', Integer, ForeignKey('charts.id')),
    Column('source_id', Integer, ForeignKey('data_sources.id'))
)

# НОВАЯ ТАБЛИЦА: Кто в каких пространствах состоит
workspace_user_link = Table(
    'workspace_user_link', Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id')),
    Column('workspace_id', Integer, ForeignKey('workspaces.id')),
    Column('role', String, default='member')  # В будущем можно сделать admin/editor
)


# --- БАЗОВЫЕ СУЩНОСТИ ---
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name = Column(String)
    email = Column(String)
    google_token = Column(String, nullable=True)
    default_theme_id = Column(Integer, ForeignKey("chart_themes.id"), nullable=True)

    # Связи пользователя
    workspaces = relationship("Workspace", secondary=workspace_user_link, back_populates="users")
    llm_providers = relationship("LLMProvider", back_populates="user")


class Workspace(Base):
    __tablename__ = 'workspaces'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    owner_id = Column(Integer, ForeignKey('users.id'))  # Кто создал

    users = relationship("User", secondary=workspace_user_link, back_populates="workspaces")

    # Всё, что принадлежит пространству:
    pages = relationship("Page", back_populates="workspace")
    charts = relationship("Chart", back_populates="workspace")
    sources = relationship("DataSource", back_populates="workspace")
    etl_handlers = relationship("ETLHandler", back_populates="workspace")


# --- РАБОЧИЕ СУЩНОСТИ (теперь привязаны к Workspace) ---
class Page(Base):
    __tablename__ = 'pages'
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey('workspaces.id'))  # БЫЛО user_id
    name = Column(String, nullable=False)
    order = Column(Integer, default=0)

    workspace = relationship("Workspace", back_populates="pages")
    charts = relationship("Chart", secondary=chart_page_association)


class Chart(Base):
    __tablename__ = 'charts'
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey('workspaces.id'))  # БЫЛО user_id
    technical_name = Column(String, nullable=False)
    display_name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    workspace = relationship("Workspace", back_populates="charts")
    data_sources = relationship("DataSource", secondary=chart_source_association)


class DataSource(Base):
    __tablename__ = 'data_sources'
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey('workspaces.id'))  # БЫЛО user_id
    connector_id = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    config_json = Column(JSON)
    active = Column(Boolean, default=True)
    handler_id = Column(Integer, ForeignKey('etl_handlers.id'), nullable=True)

    workspace = relationship("Workspace", back_populates="sources")
    handler = relationship("ETLHandler", back_populates="sources")


class ETLHandler(Base):
    __tablename__ = 'etl_handlers'
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey('workspaces.id'))  # БЫЛО user_id
    name = Column(String, nullable=False)
    technical_name = Column(String, nullable=False)

    workspace = relationship("Workspace", back_populates="etl_handlers")
    sources = relationship("DataSource", back_populates="handler")


class LLMProvider(Base):
    __tablename__ = "llm_providers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String, nullable=False)
    api_type = Column(String, nullable=False)
    api_key = Column(String, nullable=False)
    base_url = Column(String)
    models = Column(String)
    user = relationship("User", back_populates="llm_providers")


class ChartTheme(Base):
    __tablename__ = "chart_themes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String, nullable=False)
    colors = Column(String)
    dark_mode = Column(Boolean, default=False)
    user = relationship("User", foreign_keys=[user_id])