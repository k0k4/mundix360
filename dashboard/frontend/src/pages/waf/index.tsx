import { useCallback, useEffect, useState } from "react";
import {
  Table, Tag, Card, Row, Col, Alert, Typography, Spin, Button, Tooltip,
} from "antd";
import {
  StopOutlined, ReloadOutlined,
  CheckCircleFilled, CloseCircleFilled, ApiOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader, KpiCard } from "../../components/ui";

const { Text } = Typography;

const fmtNum = (n: number) => (n ?? 0).toLocaleString("pt-BR");

export function WafPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/api/waf/summary?limit=80");
      setData(data);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (loading && !data) return <Spin style={{ display: "block", margin: "80px auto" }} />;

  const recent: any[] = data?.recent || [];
  const topRules: any[] = data?.top_rules || [];

  return (
    <div className="mx-page">
      <PageHeader
        eyebrow="Firewall · WAF"
        title="Web Application Firewall"
        subtitle="Proteção do dashboard via nginx + ModSecurity v3 + OWASP Core Rule Set (OWASP Top 10, brute-force, bots)."
        extra={
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
            Atualizar
          </Button>
        }
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={24} sm={8}>
          <KpiCard icon={data?.engine_on ? <CheckCircleFilled /> : <CloseCircleFilled />}
            color={data?.engine_on ? "#52c41a" : "#f5222d"}
            label="Motor WAF" value={data?.engine_on ? "Ativo (bloqueio)" : "Inativo"} />
        </Col>
        <Col xs={24} sm={8}>
          <KpiCard icon={<StopOutlined />} color="#f5222d"
            label="Requisições bloqueadas" value={fmtNum(data?.total_blocked || 0)} />
        </Col>
        <Col xs={24} sm={8}>
          <KpiCard icon={<ApiOutlined />} color="#1677ff"
            label="Eventos analisados" value={fmtNum(data?.total_matched || 0)} />
        </Col>
      </Row>

      <Alert type="info" showIcon style={{ marginBottom: 16 }}
        message="Reverse proxy com inspeção em tempo real"
        description="Todo o tráfego do painel passa pelo nginx com ModSecurity + OWASP CRS antes de chegar à API. Ataques (SQLi, XSS, path traversal, RCE) são barrados, há limite de taxa contra brute-force e cabeçalhos de segurança são aplicados. Os endpoints da IA são monitorados (não bloqueados) por carregarem código/comandos legítimos. As regras ficam em /etc/nginx/modsec." />

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={9}>
          <Card title="Regras mais acionadas" bordered={false} className="mx-card">
            {topRules.length === 0
              ? <Text type="secondary">Nenhum bloqueio registrado ainda.</Text>
              : <Table size="small" pagination={false} rowKey="id" dataSource={topRules}
                  columns={[
                    { title: "Regra", dataIndex: "id", width: 90,
                      render: (v) => <Tag color="volcano">{v}</Tag> },
                    { title: "Descrição", dataIndex: "msg", ellipsis: true,
                      render: (v) => <Text style={{ fontSize: 12 }}>{v || "—"}</Text> },
                    { title: "Qtd", dataIndex: "count", width: 60, align: "right" },
                  ]} />}
          </Card>
        </Col>
        <Col xs={24} lg={15}>
          <Card title="Eventos recentes" bordered={false} className="mx-card">
            <Table size="small" rowKey="id" dataSource={recent}
              pagination={{ pageSize: 8, size: "small" }}
              columns={[
                { title: "Hora", dataIndex: "time", width: 110,
                  render: (v) => <Text type="secondary" style={{ fontSize: 11 }}>{(v || "").split(" ")[0]}</Text> },
                { title: "", dataIndex: "blocked", width: 80,
                  render: (b) => b
                    ? <Tag color="error" icon={<StopOutlined />}>bloqueado</Tag>
                    : <Tag color="warning">alerta</Tag> },
                { title: "Método", dataIndex: "method", width: 70,
                  render: (v) => <Tag>{v}</Tag> },
                { title: "URI", dataIndex: "uri", ellipsis: true,
                  render: (v, r) => (
                    <Tooltip title={(r.messages || []).join(" · ")}>
                      <Text code style={{ fontSize: 11 }}>{v}</Text>
                    </Tooltip>) },
                { title: "Score", dataIndex: "score", width: 60, align: "right",
                  render: (v) => v != null
                    ? <Tag color={v >= 5 ? "red" : "default"}>{v}</Tag> : "—" },
              ]} />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
