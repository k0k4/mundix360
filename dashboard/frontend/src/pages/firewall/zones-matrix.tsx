import { useCallback, useEffect, useState } from "react";
import {
  Table, Tag, Button, Space, Switch, Tooltip, Alert, Typography, Card,
  message as antdMessage, Spin,
} from "antd";
import {
  ReloadOutlined, CheckCircleOutlined, StopOutlined, SafetyOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader } from "../../components/ui";

const { Text } = Typography;

type Zone = { name: string; iface: string; net: string };
type Cell = { src: string; dst: string; action: "allow" | "block"; log: boolean };
type Payload = { zones: Zone[]; dst_zones: string[]; policies: Cell[] };

const ZONE_META: Record<string, { label: string; color: string }> = {
  lan: { label: "LAN", color: "#13c2c2" },
  dmz: { label: "DMZ", color: "#fa8c16" },
  iot: { label: "IoT", color: "#722ed1" },
  wan: { label: "WAN / Internet", color: "#1677ff" },
};

export function ZonesMatrixPage() {
  const [data, setData] = useState<Payload | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, ctx] = antdMessage.useMessage();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<Payload>("/api/firewall/zone-policies");
      setData(res.data);
    } catch (e: any) {
      msg.error(e?.response?.data?.detail || "Falha ao carregar políticas de zona");
    } finally {
      setLoading(false);
    }
  }, [msg]);

  useEffect(() => { load(); }, [load]);

  const cellOf = useCallback(
    (src: string, dst: string): Cell | undefined =>
      data?.policies.find((c) => c.src === src && c.dst === dst),
    [data],
  );

  const apply = useCallback(
    async (src: string, dst: string, action: "allow" | "block", log: boolean) => {
      const key = `${src}>${dst}`;
      setBusy(key);
      try {
        await api.put(`/api/firewall/zone-policies/${src}/${dst}`, { action, log });
        msg.success(
          `${ZONE_META[src]?.label} → ${ZONE_META[dst]?.label}: ${
            action === "allow" ? "permitido" : "bloqueado"
          }`,
        );
        await load();
      } catch (e: any) {
        msg.error(e?.response?.data?.detail || "Falha ao aplicar política");
      } finally {
        setBusy(null);
      }
    },
    [load, msg],
  );

  const dstZones = data?.dst_zones ?? [];
  const srcZones = data?.zones ?? [];

  const columns = [
    {
      title: <Text strong>Origem ↓ / Destino →</Text>,
      dataIndex: "src",
      key: "src",
      fixed: "left" as const,
      width: 200,
      render: (src: string) => {
        const z = srcZones.find((x) => x.name === src);
        const m = ZONE_META[src];
        return (
          <Space direction="vertical" size={0}>
            <Tag color={m?.color} style={{ fontWeight: 600, fontSize: 13 }}>
              {m?.label || src}
            </Tag>
            {z && (
              <Text type="secondary" style={{ fontSize: 11 }}>
                {z.iface} · {z.net}
              </Text>
            )}
          </Space>
        );
      },
    },
    ...dstZones.map((dst) => ({
      title: (
        <Tag color={ZONE_META[dst]?.color} style={{ fontWeight: 600 }}>
          {ZONE_META[dst]?.label || dst}
        </Tag>
      ),
      dataIndex: dst,
      key: dst,
      align: "center" as const,
      width: 150,
      render: (_: any, row: { src: string }) => {
        const src = row.src;
        if (src === dst) {
          return <Text type="secondary" style={{ fontSize: 18 }}>—</Text>;
        }
        const cell = cellOf(src, dst);
        const action = cell?.action ?? "allow";
        const log = cell?.log ?? false;
        const key = `${src}>${dst}`;
        const allow = action === "allow";
        return (
          <Space direction="vertical" size={4}>
            <Button
              size="small"
              loading={busy === key}
              icon={allow ? <CheckCircleOutlined /> : <StopOutlined />}
              danger={!allow}
              type={allow ? "primary" : "default"}
              ghost={allow}
              onClick={() =>
                apply(src, dst, allow ? "block" : "allow", log)
              }
              style={allow ? {} : { borderColor: "#ff4d4f", color: "#ff4d4f" }}
            >
              {allow ? "Permitir" : "Bloquear"}
            </Button>
            {!allow && (
              <Tooltip title="Registrar (log) os pacotes bloqueados">
                <span>
                  <Switch
                    size="small"
                    checked={log}
                    onChange={(v) => apply(src, dst, "block", v)}
                    checkedChildren="log"
                    unCheckedChildren="log"
                  />
                </span>
              </Tooltip>
            )}
          </Space>
        );
      },
    })),
  ];

  const rows = srcZones.map((z) => ({ key: z.name, src: z.name }));

  return (
    <>
      {ctx}
      <PageHeader
        title="Matriz de Zonas"
        subtitle="Segmentação inter-zona: defina quais zonas podem se comunicar entre si e com a Internet."
        extra={
          <Button icon={<ReloadOutlined />} onClick={load}>
            Recarregar
          </Button>
        }
      />

      <Alert
        type="info"
        showIcon
        icon={<SafetyOutlined />}
        style={{ marginBottom: 16 }}
        message="Como funciona a matriz"
        description={
          <Text type="secondary">
            Cada célula representa o tráfego de uma zona de <b>origem</b> (linha)
            para uma zona de <b>destino</b> (coluna). <b>Permitir</b> libera o
            encaminhamento; <b>Bloquear</b> descarta (com opção de log).
            Regras de filtro específicas têm precedência sobre esta linha de base.
            Padrão seguro: LAN é confiável; DMZ e IoT são isoladas da LAN e entre si.
          </Text>
        }
      />

      <Card>
        <Spin spinning={loading}>
          <Table
            columns={columns as any}
            dataSource={rows}
            pagination={false}
            scroll={{ x: "max-content" }}
            size="middle"
          />
        </Spin>
      </Card>
    </>
  );
}
