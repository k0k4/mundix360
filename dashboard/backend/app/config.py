from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MUNDIX_", env_file=".env", extra="ignore")

    # API
    api_host: str = "127.0.0.1"
    api_port: int = 8099
    api_token: str = ""  # if set, required as Bearer token
    cors_origins: str = "http://127.0.0.1:3001,http://localhost:3001"

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
    block_ip_script: str = "/opt/mundix360/scripts/active-response/block-ip.sh"
    dnsmasq_dir: str = "/opt/mundix360/configs/dnsmasq"
    dnsmasq_etc_dir: str = "/etc/dnsmasq.d"
    dhcp_leases_file: str = "/var/lib/misc/dnsmasq.leases"
    content_blocklist_file: str = "/etc/dnsmasq.d/mundix-content-block.conf"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
