import { useCustom } from "@refinedev/core";
import {
  Row,
  Col,
  Card,
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
  ThunderboltOutlined,
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
import { PageHeader, KpiCard } from "../components/ui";

const { Text } = Typography;

function ResourceBar({
  label,
  pct,
  color,
}: {
  label: string;
  pct: number;
  color: string;
}) {
  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 4,
        }}
      >
        <Text type="secondary" style={{ fontSize: 13 }}>
          {label}
        </Text>
        <Text style={{ fontSize: 13, fontWeight: 600 }}>{pct}%</Text>
      </div>
      <Progress
        percent={pct}
        strokeColor={color}
        trailColor="rgba(255,255,255,0.06)"
        showInfo={false}
      />
    </div>
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
      <div style={{ textAlign: "center", padding: 100 }}>
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
  const spark = timeline.map((p: any) => p.alerts as number);
  const bySeverity = st?.data?.by_severity ?? [];

  return (
    <div>
      <PageHeader
        eyebrow={
          <>
            <ThunderboltOutlined /> Centro de Comando
          </>
        }
        title="Visão Geral"
        subtitle="Saúde, ameaças e tráfego da rede em tempo real"
      />

      <Row gutter={[18, 18]}>
        <Col xs={24} sm={12} xl={6}>
          <KpiCard
            icon={<AlertOutlined />}
            color="#2f81f7"
            label="Alertas (24h)"
            value={d.siem?.alerts_24h ?? 0}
            spark={spark.length > 1 ? spark : undefined}
          />
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <KpiCard
            icon={<WarningOutlined />}
            color="#f87171"
            label="Críticos (24h)"
            value={d.siem?.alerts_high_24h ?? 0}
          />
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <KpiCard
            icon={<StopOutlined />}
            color="#fbbf24"
            label="IPs Bloqueados"
            value={d.firewall?.blocked_ips ?? 0}
          />
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <KpiCard
            icon={<CloudServerOutlined />}
            color="#34d399"
            label="Serviços Ativos"
            value={`${up}/${services.length}`}
          />
        </Col>
      </Row>

      <Row gutter={[18, 18]} style={{ marginTop: 18 }}>
        <Col xs={24} lg={16}>
          <Card title="Alertas por hora · últimas 24h" bordered={false}>
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart
                data={timeline}
                margin={{ top: 6, right: 6, left: -18, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#2f81f7" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="#16233c"
                  vertical={false}
                />
                <XAxis
                  dataKey="t"
                  stroke="#5f7088"
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  stroke="#5f7088"
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  cursor={{ stroke: "#22d3ee", strokeOpacity: 0.3 }}
                  contentStyle={{
                    background: "#0e1626",
                    border: "1px solid #1b2942",
                    borderRadius: 10,
                    boxShadow: "0 10px 30px -12px rgba(0,0,0,.7)",
                  }}
                  labelStyle={{ color: "#93a4c0" }}
                />
                <Area
                  type="monotone"
                  dataKey="alerts"
                  stroke="#22d3ee"
                  fill="url(#g1)"
                  strokeWidth={2.2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="Recursos do Host" bordered={false}>
            <Space direction="vertical" size={20} style={{ width: "100%" }}>
              <ResourceBar
                label="CPU (load)"
                pct={Math.round(d.host?.load_pct ?? 0)}
                color="#2f81f7"
              />
              <ResourceBar
                label="Memória"
                pct={Math.round(d.host?.memory?.used_pct ?? 0)}
                color="#a855f7"
              />
              <ResourceBar
                label="Disco"
                pct={Math.round(d.host?.disk?.used_pct ?? 0)}
                color="#22d3ee"
              />
            </Space>
          </Card>
        </Col>
      </Row>

      <Row gutter={[18, 18]} style={{ marginTop: 18 }}>
        <Col xs={24} lg={12}>
          <Card title="Severidade dos Alertas · 24h" bordered={false}>
            <Table
              size="middle"
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
              size="middle"
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
                    <Tag
                      icon={
                        <span
                          className={`mx-dot ${r ? "" : "down"}`}
                          style={{ marginRight: 6 }}
                        />
                      }
                      color={r ? "success" : "error"}
                    >
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
