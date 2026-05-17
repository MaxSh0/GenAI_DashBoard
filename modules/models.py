"""SQLAlchemy ORM models for the GenAI dashboard platform."""

from datetime import datetime

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Table, DateTime, JSON
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


# Association table: links pages to charts (many-to-many).
chart_page_association = Table(
    'chart_page_link', Base.metadata,
    Column('page_id', Integer, ForeignKey('pages.id')),
    Column('chart_id', Integer, ForeignKey('charts.id'))
)

# Association table: links charts to data sources (many-to-many).
chart_source_association = Table(
    'chart_source_link', Base.metadata,
    Column('chart_id', Integer, ForeignKey('charts.id')),
    Column('source_id', Integer, ForeignKey('data_sources.id'))
)

# Association table: links users to workspaces with a role.
# The role column is a string placeholder for future admin/editor distinction.
workspace_user_link = Table(
    'workspace_user_link', Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id')),
    Column('workspace_id', Integer, ForeignKey('workspaces.id')),
    Column('role', String, default='member')
)


class User(Base):
    """A registered user of the platform.

    Attributes:
        id: Primary key.
        username: Unique login name.
        password_hash: Hashed password.
        name: Display name.
        email: Email address.
        google_token: Optional Google OAuth token.
        default_theme_id: Foreign key to the user's preferred chart theme.
        workspaces: Workspaces the user belongs to.
        llm_providers: LLM provider configurations owned by the user.
    """

    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name = Column(String)
    email = Column(String)
    google_token = Column(String, nullable=True)
    default_theme_id = Column(Integer, ForeignKey("chart_themes.id"), nullable=True)

    workspaces = relationship("Workspace", secondary=workspace_user_link, back_populates="users")
    llm_providers = relationship("LLMProvider", back_populates="user")


class Workspace(Base):
    """A collaborative workspace that groups pages, charts, sources, and ETL handlers.

    Attributes:
        id: Primary key.
        name: Display name of the workspace.
        owner_id: Foreign key to the user who created the workspace.
        users: Users who are members of this workspace.
        pages: Pages belonging to this workspace.
        charts: Charts belonging to this workspace.
        sources: Data sources belonging to this workspace.
        etl_handlers: ETL handlers belonging to this workspace.
    """

    __tablename__ = 'workspaces'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    owner_id = Column(Integer, ForeignKey('users.id'))

    users = relationship("User", secondary=workspace_user_link, back_populates="workspaces")

    pages = relationship("Page", back_populates="workspace")
    charts = relationship("Chart", back_populates="workspace")
    sources = relationship("DataSource", back_populates="workspace")
    etl_handlers = relationship("ETLHandler", back_populates="workspace")


class Page(Base):
    """A dashboard page within a workspace.

    Attributes:
        id: Primary key.
        workspace_id: Foreign key to the owning workspace.
        name: Display name of the page.
        order: Sort order within the workspace.
        workspace: The workspace this page belongs to.
        charts: Charts assigned to this page.
    """

    __tablename__ = 'pages'
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey('workspaces.id'))
    name = Column(String, nullable=False)
    order = Column(Integer, default=0)

    workspace = relationship("Workspace", back_populates="pages")
    charts = relationship("Chart", secondary=chart_page_association)


class Chart(Base):
    """A chart (graph, visualization) within a workspace.

    Attributes:
        id: Primary key.
        workspace_id: Foreign key to the owning workspace.
        technical_name: Internal/system name for the chart.
        display_name: Human-readable chart title.
        created_at: Timestamp of chart creation.
        workspace: The workspace this chart belongs to.
        data_sources: Data sources powering this chart.
    """

    __tablename__ = 'charts'
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey('workspaces.id'))
    technical_name = Column(String, nullable=False)
    display_name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    workspace = relationship("Workspace", back_populates="charts")
    data_sources = relationship("DataSource", secondary=chart_source_association)


class DataSource(Base):
    """A data source (connector configuration) within a workspace.

    Attributes:
        id: Primary key.
        workspace_id: Foreign key to the owning workspace.
        connector_id: Identifies the connector type.
        filename: Name of the source file.
        config_json: Connector-specific configuration as JSON.
        active: Whether this source is currently active.
        handler_id: Optional foreign key to the ETL handler.
        workspace: The workspace this source belongs to.
        handler: The ETL handler assigned to this source.
    """

    __tablename__ = 'data_sources'
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey('workspaces.id'))
    connector_id = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    config_json = Column(JSON)
    active = Column(Boolean, default=True)
    handler_id = Column(Integer, ForeignKey('etl_handlers.id'), nullable=True)

    workspace = relationship("Workspace", back_populates="sources")
    handler = relationship("ETLHandler", back_populates="sources")


class ETLHandler(Base):
    """An ETL handler (data transformation pipeline) within a workspace.

    Attributes:
        id: Primary key.
        workspace_id: Foreign key to the owning workspace.
        name: Display name of the handler.
        technical_name: Internal/system name for the handler.
        workspace: The workspace this handler belongs to.
        sources: Data sources processed by this handler.
    """

    __tablename__ = 'etl_handlers'
    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey('workspaces.id'))
    name = Column(String, nullable=False)
    technical_name = Column(String, nullable=False)

    workspace = relationship("Workspace", back_populates="etl_handlers")
    sources = relationship("DataSource", back_populates="handler")


class LLMProvider(Base):
    """An LLM API provider configuration owned by a user.

    Attributes:
        id: Primary key.
        user_id: Foreign key to the owning user.
        name: Display name of the provider.
        api_type: Type of API (e.g. openai, anthropic).
        api_key: Encrypted API key.
        base_url: Optional custom base URL for the API.
        models: Comma-separated list of available model names.
        user: The user who owns this provider configuration.
    """

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
    """A chart color theme owned by a user.

    Attributes:
        id: Primary key.
        user_id: Foreign key to the owning user.
        name: Display name of the theme.
        colors: Color palette definition.
        dark_mode: Whether this is a dark-mode theme.
        user: The user who owns this theme.
    """

    __tablename__ = "chart_themes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String, nullable=False)
    colors = Column(String)
    dark_mode = Column(Boolean, default=False)
    user = relationship("User", foreign_keys=[user_id])
