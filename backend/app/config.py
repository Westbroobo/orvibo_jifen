from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")
    app_env: str = "production"
    database_url: str = "mysql+pymysql://jifen:change-me@127.0.0.1:3306/jifen?charset=utf8mb4"
    public_url: str = "http://localhost:5173"
    session_secret: str = ""
    cookie_secure: bool = True
    session_hours: int = 12
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_tenant_key: str = ""
    feishu_redirect_uri: str = "http://localhost:5173/api/auth/callback"
    feishu_event_enabled: bool = True
    initial_admin_user_ids: str = ""
    send_interval_seconds: float = 0.25
    worker_poll_seconds: float = 2
    max_send_attempts: int = 6
    demo_mode: bool = False

    def validate_runtime(self):
        if self.app_env == "production":
            if not self.database_url.startswith("mysql+"):
                raise ValueError("生产环境必须使用 MySQL")
            if len(self.session_secret) < 32 or self.session_secret.startswith("REPLACE_") or not self.cookie_secure or self.demo_mode:
                raise ValueError("生产环境须配置至少 32 字符的 SESSION_SECRET、安全 Cookie，并关闭演示模式")
        if self.demo_mode and self.app_env != "development":
            raise ValueError("演示模式仅可用于 development 环境")

    @property
    def bootstrap_admins(self):
        return {value.strip() for value in self.initial_admin_user_ids.split(",") if value.strip()}


@lru_cache
def get_settings():
    return Settings()
