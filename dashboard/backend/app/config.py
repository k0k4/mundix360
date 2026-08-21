from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MUNDIX_",
        env_file=("/opt/mundix360/.env", ".env"),
        extra="ignore",
    )

    # API
    api_host: str = "127.0.0.1"
    api_port: int = 8099
    api_token: str = ""  # if set, accepted as a Bearer token (machine/back-compat)
    cors_origins: str = "http://127.0.0.1:3001,http://localhost:3001"

    # Dashboard user authentication (local accounts + opaque cookie sessions)
    auth_db_path: str = "/opt/mundix360/dashboard/backend/data/auth.db"
    session_ttl_hours: int = 12
    session_cookie: str = "mundix_session"
    # Set true only when the panel is served exclusively over HTTPS; on a LAN
    # appliance reachable over plain HTTP this must stay false or the cookie is
    # never sent back and login silently fails.
    cookie_secure: bool = False

    # ClickHouse
    clickhouse_host: str = "127.0.0.1"
    clickhouse_port: int = 8123
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_db: str = "akvorado"

    # VictoriaMetrics
    victoriametrics_url: str = "http://127.0.0.1:8428"

    # Loki
    loki_url: str = "http://127.0.0.1:3100"

    # Paths
    base_dir: str = "/opt/mundix360"
    # Canal de atualizações estáveis (repo APT assinado em GitHub Pages, só o
    # pacote mundix360). O painel consulta "<update_url>/version".
    update_url: str = "https://k0k4.github.io/mundix360-repo"
    block_ip_script: str = "/opt/mundix360/scripts/active-response/block-ip.sh"
    dnsmasq_dir: str = "/opt/mundix360/configs/dnsmasq"
    dnsmasq_etc_dir: str = "/etc/dnsmasq.d"
    dhcp_leases_file: str = "/var/lib/misc/dnsmasq.leases"
    content_blocklist_file: str = "/etc/dnsmasq.d/mundix-content-block.conf"
    dnsmasq_log_file: str = "/var/log/dnsmasq/dnsmasq.log"

    # Network interface/VLAN management (netplan, networkd renderer)
    netplan_dir: str = "/etc/netplan"
    iface_meta_file: str = "/etc/mundix/interfaces.json"
    netplan_backup_dir: str = "/etc/mundix/netplan-backups"

    # AI assistant (Qwen3.7-Max via DashScope, OpenAI-compatible)
    dashscope_api_key: str = Field(
        "", validation_alias=AliasChoices("DASHSCOPE_API_KEY", "MUNDIX_DASHSCOPE_API_KEY")
    )
    ai_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    ai_model: str = "qwen3.7-max"
    # Output token budget per model call. Qwen3-Max supports large completions;
    # 1536 was far too small for a coding assistant and truncated answers/diffs
    # mid-stream (showing up as empty assistant turns). Generous default so the
    # model can actually finish reasoning and emit complete code.
    ai_max_tokens: int = 8192
    # Cap on tool-calling iterations per turn. A finite default bounds runaway
    # agent loops (the previous 0 = unlimited could pin the Atom's 2 cores until
    # the wall-clock backstop). After this many rounds the agent is forced to
    # answer from what it gathered. Operators can still raise it in AI settings.
    ai_max_tool_iters: int = 12
    ai_request_timeout: int = 120
    ai_master_password: str = Field(
        "", validation_alias=AliasChoices("MUNDIX_AI_MASTER_PASSWORD", "AI_MASTER_PASSWORD")
    )
    ai_db_path: str = "/opt/mundix360/dashboard/backend/data/ai.db"
    ai_editable_root: str = "/opt/mundix360"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
