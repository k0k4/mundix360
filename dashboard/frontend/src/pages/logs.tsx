import { useState } from "react";
import { useCustom } from "@refinedev/core";
import { Card, Table, Tag, Input, Space, Typography, Select } from "antd";
import { FileTextOutlined } from "@ant-design/icons";
import { fmtTime } from "../format";
import { PageHeader } from "../components/ui";

const { Text } = Typography;

export const LogsPage = () => {
  const [query, setQuery] = useState('{job=~".+"}');
  const [limit, setLimit] = useState(100);

  const { data, isLoading } = useCustom<any>({
    url: "/api/logs",
    method: "get",
    config: { query: { query, limit } },
  });

  const entries = data?.data?.entries ?? [];

  return (
    <div>
      <PageHeader
        eyebrow={
          <>
            <FileTextOutlined /> Loki
          </>
        }
        title="Logs"
        subtitle="Consulta em tempo real aos logs agregados (LogQL)"
      />
      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ width: 360 }}
          className="mx-mono"
          placeholder='{job="suricata"}'
        />
        <Select
          value={limit}
          onChange={setLimit}
          style={{ width: 120 }}
          options={[
            { value: 50, label: "50 linhas" },
            { value: 100, label: "100 linhas" },
            { value: 300, label: "300 linhas" },
          ]}
        />
      </Space>
      <Card bordered={false}>
        <Table
          loading={isLoading}
          dataSource={entries}
          rowKey={(_, i) => String(i)}
          size="small"
          pagination={{ pageSize: 25 }}
          columns={[
            {
              title: "Horário",
              dataIndex: "timestamp",
              width: 180,
              render: (t) => <Text className="mx-mono">{fmtTime(t)}</Text>,
            },
            {
              title: "Job",
              dataIndex: "labels",
              width: 120,
              render: (l: any) => <Tag color="blue">{l?.job || "—"}</Tag>,
            },
            {
              title: "Linha",
              dataIndex: "line",
              render: (l) => (
                <Text className="mx-mono" style={{ fontSize: 11 }}>
                  {l}
                </Text>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
};
