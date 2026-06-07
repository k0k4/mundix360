import { useCustom } from "@refinedev/core";
import { Row, Col, Card, Statistic, Table, Spin } from "antd";
import { PartitionOutlined } from "@ant-design/icons";
import { fmtBytes, stripV6 } from "../format";
import { PageHeader } from "../components/ui";

export const FlowsPage = () => {
  const { data, isLoading } = useCustom<any>({
    url: "/api/flows/summary",
    method: "get",
  });

  if (isLoading) {
    return (
      <div style={{ textAlign: "center", padding: 80 }}>
        <Spin size="large" />
      </div>
    );
  }

  const d = data?.data ?? {};
  const totals = d.totals ?? {};
  const cols = (key: string) => [
    {
      title: "Endereço",
      dataIndex: key,
      render: (v: string) => <span className="mx-mono">{stripV6(v)}</span>,
    },
    {
      title: "Tráfego",
      dataIndex: "bytes",
      align: "right" as const,
      render: (b: number) => fmtBytes(b),
    },
  ];

  return (
    <div>
      <PageHeader
        eyebrow={
          <>
            <PartitionOutlined /> NetFlow · Akvorado
          </>
        }
        title="Flows de Rede"
        subtitle="Volume de tráfego e principais conversas observadas"
      />
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={8}>
          <Card bordered={false}>
            <Statistic title="Total de Flows" value={totals.flows ?? 0} />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card bordered={false}>
            <Statistic
              title="Bytes"
              value={fmtBytes(totals.bytes ?? 0)}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card bordered={false}>
            <Statistic title="Pacotes" value={totals.packets ?? 0} />
          </Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="Top Origens" bordered={false}>
            <Table
              rowKey="src"
              size="small"
              pagination={false}
              dataSource={d.top_src ?? []}
              columns={cols("src")}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="Top Destinos" bordered={false}>
            <Table
              rowKey="dst"
              size="small"
              pagination={false}
              dataSource={d.top_dst ?? []}
              columns={cols("dst")}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
};
