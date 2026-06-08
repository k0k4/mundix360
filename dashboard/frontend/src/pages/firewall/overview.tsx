import { useCallback, useEffect, useState } from "react";
import { Row, Col, Card, Space, Tag, Button, Alert, Statistic } from "antd";
import { useNavigate } from "react-router-dom";
import {
  SafetyCertificateOutlined, FilterOutlined, SwapOutlined, TagsOutlined,
  StopOutlined, PartitionOutlined, ReloadOutlined, RightOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader, KpiCard } from "../../components/ui";

export const FirewallOverview = () => {
  const nav = useNavigate();
  const [ov, setOv] = useState<any>(null);
  const [blocked, setBlocked] = useState(0);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [o, b] = await Promise.all([
        api.get("/api/firewall/overview"),
        api.get("/api/firewall/blocklist"),
      ]);
      setOv(o.data);
      setBlocked(b.data.count || 0);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const fwd = ov?.forwarding;

  return (
    <div>
      <PageHeader
        eyebrow={<><SafetyCertificateOutlined /> Firewall</>}
        title="Central de Firewall"
        subtitle="Regras, NAT, aliases e proteção — inspirado em pfSense/OPNsense"
        extra={<Button icon={<ReloadOutlined />} onClick={load} loading={loading} />}
      />

      {ov && !ov.include_installed && (
        <Alert type="info" showIcon style={{ marginBottom: 16 }}
          message="O ruleset gerenciado ainda não foi aplicado. Ele é ativado automaticamente na primeira alteração de regra/NAT e passa a ser carregado no boot." />
      )}
      {fwd && !fwd.enabled && (ov.port_forwards > 0) && (
        <Alert type="warning" showIcon style={{ marginBottom: 16 }}
          message="Existem port-forwards configurados, mas o encaminhamento IP está desativado — eles não funcionarão até ativá-lo na aba NAT." />
      )}

      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <KpiCard icon={<FilterOutlined />} color="#22d3ee" label="Regras de filtro"
            value={ov?.filter_rules ?? "—"}
            suffix={ov ? `${ov.input_rules}in/${ov.forward_rules}fw` : ""} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<SwapOutlined />} color="#a78bfa" label="Port-forwards"
            value={ov?.port_forwards ?? "—"} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<TagsOutlined />} color="#34d399" label="Aliases"
            value={ov?.aliases ?? "—"} />
        </Col>
        <Col xs={12} md={6}>
          <KpiCard icon={<StopOutlined />} color="#f87171" label="IPs bloqueados"
            value={blocked} />
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {[
          { icon: <FilterOutlined />, title: "Regras de Filtro",
            desc: "Permitir/bloquear tráfego por interface, origem, destino e porta",
            to: "/firewall/rules", color: "#22d3ee" },
          { icon: <SwapOutlined />, title: "NAT",
            desc: "Port-forward (entrada) e masquerade (saída)",
            to: "/firewall/nat", color: "#a78bfa" },
          { icon: <TagsOutlined />, title: "Aliases",
            desc: "Grupos reutilizáveis de hosts, redes e portas",
            to: "/firewall/aliases", color: "#34d399" },
          { icon: <StopOutlined />, title: "Bloqueio de IP",
            desc: "Lista dinâmica de IPs bloqueados (active response)",
            to: "/firewall/blocklist", color: "#f87171" },
          { icon: <PartitionOutlined />, title: "Ruleset (diagnóstico)",
            desc: "Visão ao vivo das tabelas e chains do nftables",
            to: "/firewall/ruleset", color: "#fbbf24" },
        ].map((c) => (
          <Col xs={24} md={12} lg={8} key={c.to}>
            <Card hoverable bordered={false} onClick={() => nav(c.to)}
              styles={{ body: { padding: 18 } }} style={{ cursor: "pointer" }}>
              <Space align="start" style={{ width: "100%", justifyContent: "space-between" }}>
                <Space align="start">
                  <div className="mx-kpi-icon"
                    style={{ background: `${c.color}1f`, color: c.color }}>
                    {c.icon}
                  </div>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 15 }}>{c.title}</div>
                    <div className="mx-page-sub" style={{ marginTop: 2 }}>{c.desc}</div>
                  </div>
                </Space>
                <RightOutlined style={{ color: "var(--mx-text-dim)" }} />
              </Space>
            </Card>
          </Col>
        ))}
      </Row>

      {ov && (
        <Card bordered={false} style={{ marginTop: 16 }} title="Estado do sistema">
          <Row gutter={16}>
            <Col xs={12} md={6}>
              <Statistic title="Ruleset gerenciado"
                value={ov.managed_active ? "ativo" : "inativo"} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="Carregado no boot"
                value={ov.include_installed ? "sim" : "não"} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="IP forwarding"
                value={fwd?.enabled ? "ativo" : "desativado"} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="NAT de saída" value={ov.outbound_mode} />
            </Col>
          </Row>
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col xs={12} md={6}>
              <Statistic title="Hardening de kernel"
                valueStyle={{ color: ov.hardening?.applied ? "#52c41a" : "#faad14" }}
                value={ov.hardening?.applied ? "aplicado" : "pendente"} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="Anti-spoof (rp_filter)"
                value={ov.hardening?.live?.["net.ipv4.conf.all.rp_filter"] === "0"
                  ? "desativado" : "ativo"} />
            </Col>
            <Col xs={12} md={6}>
              <Statistic title="Persistido (boot)"
                value={ov.hardening?.persisted ? "sim" : "não"} />
            </Col>
          </Row>
        </Card>
      )}
    </div>
  );
};
