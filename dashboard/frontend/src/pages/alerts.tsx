import { useState } from "react";
import { useShow, useUpdate, useInvalidate } from "@refinedev/core";
import { List, useTable, ShowButton } from "@refinedev/antd";
import {
  Table,
  Tag,
  Space,
  Select,
  Input,
  Card,
  Descriptions,
  Button,
  Switch,
  Typography,
  Row,
  Col,
  message,
  Tabs,
} from "antd";
import { useParams, useNavigate } from "react-router-dom";
import { sevColor, sevLabel, fmtTime } from "../format";

const { Text, Paragraph } = Typography;

export const AlertList = () => {
  const { tableProps, setFilters } = useTable({
    resource: "alerts",
    pagination: { pageSize: 25 },
    syncWithLocation: true,
  });

  return (
    <List title="SIEM — Alertas de Segurança">
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          placeholder="Severidade mínima"
          allowClear
          style={{ width: 180 }}
          onChange={(v) =>
            setFilters([{ field: "min_severity", operator: "eq", value: v }])
          }
          options={[
            { value: 7, label: "Alto (≥7)" },
            { value: 5, label: "Médio (≥5)" },
            { value: 3, label: "Baixo (≥3)" },
          ]}
        />
        <Select
          placeholder="Fonte"
          allowClear
          style={{ width: 160 }}
          onChange={(v) =>
            setFilters([{ field: "source", operator: "eq", value: v }])
          }
          options={[
            { value: "suricata", label: "Suricata" },
            { value: "auditd", label: "Auditd" },
            { value: "auth", label: "Auth" },
          ]}
        />
        <Input.Search
          placeholder="Buscar descrição/IP"
          allowClear
          style={{ width: 240 }}
          onSearch={(v) =>
            setFilters([{ field: "search", operator: "contains", value: v }])
          }
        />
      </Space>

      <Table {...tableProps} rowKey="id" size="small" scroll={{ x: 900 }}>
        <Table.Column
          title="Horário"
          dataIndex="timestamp"
          render={(v) => <Text className="mx-mono">{fmtTime(v)}</Text>}
          width={170}
        />
        <Table.Column
          title="Sev"
          dataIndex="severity"
          width={110}
          render={(s: number) => <Tag color={sevColor(s)}>{sevLabel(s)}</Tag>}
        />
        <Table.Column title="Fonte" dataIndex="source" width={90} />
        <Table.Column title="Regra" dataIndex="rule_name" ellipsis />
        <Table.Column
          title="Origem → Destino"
          render={(_, r: any) => (
            <Text className="mx-mono">
              {r.src_ip || "—"} → {r.dst_ip || "—"}
            </Text>
          )}
          width={220}
        />
        <Table.Column
          title="FP"
          dataIndex="false_positive"
          width={60}
          render={(v: number) =>
            v ? <Tag color="default">FP</Tag> : null
          }
        />
        <Table.Column
          title=""
          width={70}
          render={(_, r: any) => <ShowButton hideText size="small" recordItemId={r.id} />}
        />
      </Table>
    </List>
  );
};

export const AlertShow = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const { queryResult } = useShow({ resource: "alerts", id });
  const { mutate, isLoading: saving } = useUpdate();
  const invalidate = useInvalidate();
  const record: any = queryResult.data?.data;

  const [fp, setFp] = useState<boolean | undefined>();
  const [notes, setNotes] = useState<string | undefined>();

  if (queryResult.isLoading || !record) {
    return <Card loading title="Carregando alerta..." />;
  }

  const save = () => {
    mutate(
      {
        resource: "alerts",
        id: id!,
        values: {
          false_positive: (fp ?? !!record.false_positive) ? 1 : 0,
          triage_notes: notes ?? "",
        },
      },
      {
        onSuccess: () => {
          message.success("Triage salvo");
          invalidate({ resource: "alerts", invalidates: ["detail", "list"] });
        },
      }
    );
  };

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button onClick={() => navigate("/siem")}>← Voltar</Button>
        <Tag color={sevColor(record.severity)}>{sevLabel(record.severity)}</Tag>
      </Space>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={15}>
          <Card title={record.rule_name || "Alerta"} bordered={false}>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="Horário" span={2}>
                {fmtTime(record.timestamp)}
              </Descriptions.Item>
              <Descriptions.Item label="Fonte">
                {record.source}
              </Descriptions.Item>
              <Descriptions.Item label="Tipo">
                {record.source_type}
              </Descriptions.Item>
              <Descriptions.Item label="Categoria">
                {record.category || "—"}
              </Descriptions.Item>
              <Descriptions.Item label="Regra ID">
                {record.rule_id || "—"}
              </Descriptions.Item>
              <Descriptions.Item label="IP Origem">
                {record.src_ip || "—"}
              </Descriptions.Item>
              <Descriptions.Item label="IP Destino">
                {record.dst_ip || "—"}
              </Descriptions.Item>
              <Descriptions.Item label="MITRE Tática">
                {record.mitre_tactic || "—"}
              </Descriptions.Item>
              <Descriptions.Item label="MITRE Técnica">
                {record.mitre_technique || "—"}
              </Descriptions.Item>
              <Descriptions.Item label="Descrição" span={2}>
                {record.description || "—"}
              </Descriptions.Item>
            </Descriptions>

            <Tabs
              style={{ marginTop: 16 }}
              items={[
                {
                  key: "raw",
                  label: "Log Bruto",
                  children: (
                    <Paragraph>
                      <pre className="mx-mono" style={{ whiteSpace: "pre-wrap" }}>
                        {record.full_log || "—"}
                      </pre>
                    </Paragraph>
                  ),
                },
                {
                  key: "triage",
                  label: "Triage / Notas",
                  children: (
                    <pre className="mx-mono" style={{ whiteSpace: "pre-wrap" }}>
                      {record.triage_notes || "Sem notas"}
                    </pre>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={9}>
          <Card title="Triage" bordered={false}>
            <Space direction="vertical" size={16} style={{ width: "100%" }}>
              <div>
                <Text>Marcar como falso positivo</Text>
                <br />
                <Switch
                  checked={fp ?? !!record.false_positive}
                  onChange={setFp}
                  style={{ marginTop: 8 }}
                />
              </div>
              <div>
                <Text>Nota de triage</Text>
                <Input.TextArea
                  rows={5}
                  defaultValue={record.triage_notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Análise do analista..."
                  style={{ marginTop: 8 }}
                />
              </div>
              <Button type="primary" block loading={saving} onClick={save}>
                Salvar Triage
              </Button>
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  );
};
