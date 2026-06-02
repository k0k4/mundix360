import { useCustom } from "@refinedev/core";
import {
  Row,
  Col,
  Card,
  Statistic,
  Typography,
  Progress,
  Tag,
  Table,
  Spin,
  Space,
} from "antd";
import {
  AlertOutlined,
  StopOutlined,
  CloudServerOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { sevColor, sevLabel } from "../format";

const { Title, Text } = Typography;

function KpiCard({
  icon,
  color,
  title,
  value,
  suffix,
}: {
  icon: React.ReactNode;
  color: string;
  title: string;
  value: number | string;
  suffix?: string;
}) {
  return (
    <Card bordered={false} styles={{ body: { padding: 18 } }}>
      <Space align="center" size={14}>
        <div
          className="mx-kpi-icon"
          style={{ background: `${color}22`, color }}
        >
          {icon}
        </div>
        <Statistic title={title} value={value} suffix={suffix} />
      </Space>
    </Card>
  );
}

export const Overview = () => {
  const { data: ov, isLoading } = useCustom<any>({
    url: "/api/overview",
    method: "get",
  });
  const { data: st } = useCustom<any>({
    url: "/api/alerts/stats",
    method: "get",
    config: { query: { hours: 24 } },
  });

  if (isLoading || !ov?.data) {
    return (
      <div style={{ textAlign: "center", padding: 80 }}>
        <Spin size="large" />
      </div>
    );
  }

  const d = ov.data;
  const services = d.services ?? [];
  const up = services.filter((s: any) => s.running).length;
  const timeline = (st?.data?.timeline ?? []).map((p: any) => ({
    t: new Date(p.bucket ?? p.ts ?? p.time).toLocaleTimeString("pt-BR", {
      hour: "2-digit",
    }),
    alerts: p.count,
  }));
  const bySeverity = st?.data?.by_severity ?? [];

  return (
    <div>
      <Title level={3} style={{ marginTop: 0 }}>
        Visão Geral
      </Title>
      <Text type="secondary">
        Centro de comando — saúde, ameaças e tráfego em tempo real
      </Text>

      <Row gutter={[16, 16]} style={{ marginTop: 18 }}>
        <Col xs={24} sm={12} lg={6}>
          <KpiCard
            icon={<AlertOutlined />}
            color="#1668dc"
            title="Alertas (24h)"
            value={d.siem?.alerts_24h ?? 0}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <KpiCard
            icon={<WarningOutlined />}
            color="#cf1322"
            title="Alertas Críticos (24h)"
            value={d.siem?.alerts_high_24h ?? 0}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <KpiCard
            icon={<StopOutlined />}
            color="#fa8c16"
            title="IPs Bloqueados"
            value={d.firewall?.blocked_ips ?? 0}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <KpiCard
            icon={<CloudServerOutlined />}
            color="#52c41a"
            title="Serviços Ativos"
            value={`${up}/${services.length}`}
          />
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={16}>
          <Card title="Alertas por hora (24h)" bordered={false}>
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={timeline}>
                <defs>
                  <linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#1668dc" stopOpacity={0.6} />
                    <stop offset="100%" stopColor="#1668dc" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2a44" />
                <XAxis dataKey="t" stroke="#64748b" fontSize={11} />
                <YAxis stroke="#64748b" fontSize={11} />
                <Tooltip
                  contentStyle={{
                    background: "#15203a",
                    border: "1px solid #1f2a44",
                    borderRadius: 8,
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="alerts"
                  stroke="#1668dc"
                  fill="url(#g1)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="Recursos do Host" bordered={false}>
            <Space direction="vertical" size={16} style={{ width: "100%" }}>
              <div>
                <Text type="secondary">CPU (load)</Text>
                <Progress
                  percent={Math.round(d.host?.load_pct ?? 0)}
                  strokeColor="#1668dc"
                />
              </div>
              <div>
                <Text type="secondary">Memória</Text>
                <Progress
                  percent={Math.round(d.host?.memory?.used_pct ?? 0)}
                  strokeColor="#722ed1"
                />
              </div>
              <div>
                <Text type="secondary">Disco</Text>
                <Progress
                  percent={Math.round(d.host?.disk?.used_pct ?? 0)}
                  strokeColor="#13c2c2"
                />
              </div>
            </Space>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="Severidade dos Alertas (24h)" bordered={false}>
            <Table
              size="small"
              rowKey="severity"
              pagination={false}
              dataSource={bySeverity}
              columns={[
                {
                  title: "Severidade",
                  dataIndex: "severity",
                  render: (s: number) => (
                    <Tag color={sevColor(s)}>{sevLabel(s)}</Tag>
                  ),
                },
                { title: "Quantidade", dataIndex: "count", align: "right" },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="Serviços da Plataforma" bordered={false}>
            <Table
              size="small"
              rowKey="name"
              pagination={false}
              scroll={{ y: 240 }}
              dataSource={services}
              columns={[
                { title: "Serviço", dataIndex: "name" },
                {
                  title: "Estado",
                  dataIndex: "running",
                  align: "right",
                  render: (r: boolean) => (
                    <Tag color={r ? "success" : "error"}>
                      {r ? "ativo" : "parado"}
                    </Tag>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
};
