from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Table, DateTime, JSON
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()

# Таблица связи Множество-ко-Многим: Графики на Страницах
chart_page_association = Table(
    'chart_page_link', Base.metadata,
    Column('page_id', Integer, ForeignKey('pages.id')),
    Column('chart_id', Integer, ForeignKey('charts.id'))
)

# Таблица связи Множество-ко-Многим: Графики и их Источники данных
chart_source_association = Table(
    'chart_source_link', Base.metadata,
    Column('chart_id', Integer, ForeignKey('charts.id')),
    Column('source_id', Integer, ForeignKey('data_sources.id'))
)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name = Column(String)
    email = Column(String)
    google_token = Column(String, nullable=True)
    etl_handlers = relationship("ETLHandler", back_populates="user")
    
    pages = relationship("Page", back_populates="user")
    charts = relationship("Chart", back_populates="user")
    sources = relationship("DataSource", back_populates="user")
    default_theme_id = Column(Integer, ForeignKey("chart_themes.id"), nullable=True)

class ETLHandler(Base):
    __tablename__ = 'etl_handlers'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    name = Column(String, nullable=False)
    technical_name = Column(String, nullable=False)
    
    user = relationship("User", back_populates="etl_handlers")
    sources = relationship("DataSource", back_populates="handler")

class Page(Base):
    __tablename__ = 'pages'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    name = Column(String, nullable=False)
    order = Column(Integer, default=0)

    user = relationship("User", back_populates="pages")
    charts = relationship("Chart", secondary=chart_page_association)

class Chart(Base):
    __tablename__ = 'charts'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    technical_name = Column(String, nullable=False) # Название .py файла
    display_name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="charts")
    # Какие данные нужны этому графику
    data_sources = relationship("DataSource", secondary=chart_source_association)

class DataSource(Base):
    __tablename__ = 'data_sources'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    connector_id = Column(String, nullable=False) 
    filename = Column(String, nullable=False)
    config_json = Column(JSON) 
    active = Column(Boolean, default=True)
    
    handler_name = Column(String) 
    handler_id = Column(Integer, ForeignKey('etl_handlers.id'), nullable=True)
    
    user = relationship("User", back_populates="sources")
    handler = relationship("ETLHandler", back_populates="sources")

class LLMProvider(Base):
    __tablename__ = "llm_providers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String, nullable=False)
    api_type = Column(String, nullable=False)
    api_key = Column(String, nullable=False)
    base_url = Column(String)
    models = Column(String)

class ChartTheme(Base):
    __tablename__ = "chart_themes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String, nullable=False)
    colors = Column(String)
    dark_mode = Column(Boolean, default=False)