import { useCallback, useEffect, useRef, useState } from "react";
import {
  Card, Row, Col, Button, Space, Typography, Alert,
  Input, InputNumber, Switch, message as antdMessage, Tooltip,
} from "antd";
import {
  SafetyCertificateOutlined, ReloadOutlined, GlobalOutlined,
  CheckCircleFilled, CloseCircleFilled, KeyOutlined, ApiOutlined,
  LockOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader, KpiCard } from "../../components/ui";

const { Text, Paragraph } = Typography;

type Status = {
  enabled: boolean;
  gateway_host: string;
  gateway_port: number;
  username: string;
  realm: string;
  iface: string;
  remote_subnets: string[];
  set_dns: boolean;
  persistent: boolean;
  has_password: boolean;
  has_trusted_cert: boolean;
  trusted_cert: string;
  unit_active: boolean;
  tunnel_up: boolean;
  tunnel_address: string;
};

export function FortinetPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [probing, setProbing] = useState(false);

  const [enabled, setEnabled] = useState(false);
  const [gatewayHost, setGatewayHost] = useState("");
  const [gatewayPort, setGatewayPort] = useState(443);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [realm, setRealm] = useState("");
  const [trustedCert, setTrustedCert] = useState("");
  const [iface, setIface] = useState("ppp-forti");
  const [remoteSubnets, setRemoteSubnets] = useState("");
  const [setDns, setSetDns] = useState(false);
  const [persistent, setPersistent] = useState(true);
  const dirtyRef = useRef(false);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const r = await api.get<{ fortinet: Status }>("/api/vpn/status");
      const f = r.data.fortinet;
      setStatus(f);
      if (!dirtyRef.current) {
        setEnabled(f.enabled);
        setGatewayHost(f.gateway_host);
        setGatewayPort(f.gateway_port);
        setUsername(f.username);
        setRealm(f.realm);
        setTrustedCert(f.trusted_cert);
        setIface(f.iface);
        setRemoteSubnets((f.remote_subnets || []).join(", "));
        setSetDns(f.set_dns);
        setPersistent(f.persistent);
      }
    } catch {
      /* ignore */
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(() => load(true), 5000);
    return () => window.clearInterval(t);
  }, [load]);

  const markDirty = () => { dirtyRef.current = true; };

  const probeCert = async () => {
    if (!gatewayHost) {
      antdMessage.warning("Informe o host do gateway primeiro");
      return;
    }
    setProbing(true);
    try {
      const r = await api.post<{ trusted_cert: string }>("/api/vpn/fortinet/probe-cert", {
        host: gatewayHost, port: gatewayPort,
      });
      setTrustedCert(r.data.trusted_cert);
      markDirty();
      antdMessage.success("Impressão digital obtida — revise e aplique para fixá-la");
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao obter o certificado");
    } finally {
      setProbing(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      const subnets = remoteSubnets
        .split(/[,\s]+/).map((s) => s.trim()).filter(Boolean);
      const body: Record<string, unknown> = {
        enabled, gateway_host: gatewayHost, gateway_port: gatewayPort,
        username, realm, trusted_cert: trustedCert, iface,
        remote_subnets: subnets, set_dns: setDns, persistent,
      };
      if (password) body.password = password;
      await api.put("/api/vpn/fortinet", body);
      dirtyRef.current = false;
      setPassword("");
      antdMessage.success("Cliente Fortinet aplicado");
      await load();
    } catch (e: any) {
      antdMessage.error(e?.response?.data?.detail || "Falha ao aplicar");
    } finally {
      setSaving(false);
    }
  };

  const tunnelState = !enabled
    ? { tag: "—", color: "#94a3b8" }
    : status?.tunnel_up
      ? { tag: "conectado", color: "#22c55e" }
      : status?.unit_active
        ? { tag: "conectando…", color: "#f59e0b" }
        : { tag: "parado", color: "#ef4444" };

  return (
    <div>
      <PageHeader
        eyebrow="VPN"
        title="Fortinet (cliente)"
        subtitle="O appliance disca para um FortiGate SSL-VPN remoto (site-to-site de saída)"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => load()} loading={loading}>
              Atualizar
            </Button>
            <Button type="primary" onClick={save} loading={saving}>
              Aplicar
            </Button>
          </Space>
        }
      />

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Cliente openfortivpn — desligado por padrão"
        description="Aqui o Mundix é o CLIENTE: ele se conecta a um FortiGate da matriz/provedor e leva a LAN local até as redes remotas. As credenciais ficam protegidas (gravadas só no appliance, 0600). Por segurança, fixe a impressão digital (sha256) do certificado do gateway: clique em ‘Obter certificado’, confira o valor com o administrador do FortiGate e aplique."
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}>
          <KpiCard icon={<ApiOutlined />} color="#6366f1" label="Túnel"
            value={tunnelState.tag} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={status?.tunnel_up ? <CheckCircleFilled /> : <CloseCircleFilled />}
            color={tunnelState.color} label="IP do túnel"
            value={status?.tunnel_address || "—"} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<GlobalOutlined />} color="#0ea5e9" label="Gateway"
            value={status?.gateway_host ? `${status.gateway_host}:${status.gateway_port}` : "—"} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<LockOutlined />} color={status?.has_trusted_cert ? "#22c55e" : "#f59e0b"}
            label="Certificado" value={status?.has_trusted_cert ? "fixado" : "não fixado"} />
        </Col>
      </Row>

      <Card style={{ marginBottom: 16 }} title={<Space><KeyOutlined />Conexão</Space>}>
        <Row gutter={[24, 16]} align="middle">
          <Col xs={24} md={8}>
            <Space>
              <Switch checked={enabled} onChange={(v) => { setEnabled(v); markDirty(); }} />
              <Text strong>{enabled ? "Fortinet ATIVO" : "Fortinet desligado"}</Text>
            </Space>
          </Col>
          <Col xs={16} md={8}>
            <Text type="secondary">Host do FortiGate</Text>
            <Input value={gatewayHost} placeholder="vpn.empresa.com.br"
              onChange={(e) => { setGatewayHost(e.target.value); markDirty(); }} />
          </Col>
          <Col xs={8} md={4}>
            <Text type="secondary">Porta</Text>
            <InputNumber style={{ width: "100%" }} min={1} max={65535} value={gatewayPort}
              onChange={(v) => { setGatewayPort(Number(v)); markDirty(); }} />
          </Col>
          <Col xs={12} md={4}>
            <Text type="secondary">Realm (opcional)</Text>
            <Input value={realm} onChange={(e) => { setRealm(e.target.value); markDirty(); }} />
          </Col>
          <Col xs={12} md={8}>
            <Text type="secondary">Usuário</Text>
            <Input value={username} autoComplete="off"
              onChange={(e) => { setUsername(e.target.value); markDirty(); }} />
          </Col>
          <Col xs={12} md={8}>
            <Text type="secondary">Senha {status?.has_password ? "(salva — deixe em branco para manter)" : ""}</Text>
            <Input.Password value={password} autoComplete="new-password"
              placeholder={status?.has_password ? "••••••••" : ""}
              onChange={(e) => { setPassword(e.target.value); markDirty(); }} />
          </Col>
        </Row>
      </Card>

      <Card style={{ marginBottom: 16 }}
        title={<Space><SafetyCertificateOutlined />Certificado do gateway (pinning)</Space>}>
        <Paragraph type="secondary" style={{ marginBottom: 12 }}>
          A conexão só é aceita se o certificado do FortiGate corresponder a esta impressão
          digital sha256. Obtenha-a do gateway, confirme com o administrador e aplique.
        </Paragraph>
        <Row gutter={[12, 12]} align="middle">
          <Col flex="auto">
            <Input value={trustedCert} placeholder="impressão digital sha256 (64 hex)"
              onChange={(e) => { setTrustedCert(e.target.value.trim()); markDirty(); }} />
          </Col>
          <Col>
            <Tooltip title="Conecta ao gateway e busca a impressão digital do certificado">
              <Button icon={<SafetyCertificateOutlined />} loading={probing} onClick={probeCert}>
                Obter certificado
              </Button>
            </Tooltip>
          </Col>
        </Row>
      </Card>

      <Card title={<Space><GlobalOutlined />Rede</Space>}>
        <Row gutter={[24, 16]} align="middle">
          <Col xs={24} md={12}>
            <Text type="secondary">Sub-redes remotas (informativo, vírgula)</Text>
            <Input value={remoteSubnets} placeholder="10.50.0.0/24, 172.16.0.0/16"
              onChange={(e) => { setRemoteSubnets(e.target.value); markDirty(); }} />
          </Col>
          <Col xs={12} md={6}>
            <Text type="secondary">Interface do túnel</Text>
            <Input value={iface}
              onChange={(e) => { setIface(e.target.value); markDirty(); }} />
          </Col>
          <Col xs={12} md={3}>
            <Space>
              <Switch checked={persistent} onChange={(v) => { setPersistent(v); markDirty(); }} />
              <Text type="secondary">Reconectar</Text>
            </Space>
          </Col>
          <Col xs={12} md={3}>
            <Space>
              <Switch checked={setDns} onChange={(v) => { setSetDns(v); markDirty(); }} />
              <Text type="secondary">Usar DNS remoto</Text>
            </Space>
          </Col>
        </Row>
        <Alert style={{ marginTop: 12 }} type="info" showIcon
          message="As rotas para as redes remotas são instaladas automaticamente pelo FortiGate. A LAN local sai mascarada pela interface do túnel." />
      </Card>
    </div>
  );
}
