import { useMemo, useState } from "react";
import { useCustom } from "@refinedev/core";
import {
  Row,
  Col,
  Card,
  Table,
  Tag,
  Input,
  Select,
  Space,
  Button,
  Typography,
  Switch,
  Tooltip,
  List,
  Empty,
} from "antd";
import {
  SafetyOutlined,
  ReloadOutlined,
  StopOutlined,
  AimOutlined,
  ApiOutlined,
  GlobalOutlined,
} from "@ant-design/icons";
import { fmtTime } from "../format";
import { PageHeader, KpiCard } from "../components/ui";

const { Text } = Typography;

const CATEGORY_LABEL: Record<string, string> = {
  input: "Entrada",
  forward: "Encaminhamento",
  ssh: "SSH",
  zone: "Entre zonas",
  rule: "Regra",
  other: "Outro",
};

const actionTag = (action: string, reason: string) => {
  if (action === "drop")
    return (
      <Tooltip title={reason}>
        <Tag color="red" icon={<StopOutlined />}>
          Bloqueado
        </Tag>
      </Tooltip>
    );
  return (
    <Tooltip title={reason}>
      <Tag color="blue">Registro</Tag>
    </Tooltip>
  );
};

const portTag = (proto?: string, p?: number) =>
  p ? (
    <Tag className="mx-mono" color={proto === "TCP" ? "geekblue" : "purple"}>
      {proto}/{p}
    </Tag>
  ) : (
    <Text type="secondary">—</Text>
  );

export const LogsPage = () => {
  const [hours, setHours] = useState(24);
  const [src, setSrc] = useState("");
  const [dst, setDst] = useState("");
  const [port, setPort] = useState("");
  const [proto, setProto] = useState<string | undefined>();
  const [action, setAction] = useState<string | undefined>();
  const [category, setCategory] = useState<string | undefined>();
  const [search, setSearch] = useState("");
  const [hideBroadcast, setHideBroadcast] = useState(true);

  const queryParams = useMemo(() => {
    const q: Record<string, any> = { hours, limit: 500, hide_broadcast: hideBroadcast };
    if (src.trim()) q.src = src.trim();
    if (dst.trim()) q.dst = dst.trim();
    if (port.trim()) q.port = port.trim();
    if (proto) q.proto = proto;
    if (action) q.action = action;
    if (category) q.category = category;
    if (search.trim()) q.search = search.trim();
    return q;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hours, src, dst, port, proto, action, category, search, hideBroadcast]);

  const { data, isLoading, isFetching, refetch } = useCustom<any>({
    url: "/api/fwlog/events",
    method: "get",
    config: { query: queryParams },
  });

  const { data: sumData, refetch: refetchSummary } = useCustom<any>({
    url: "/api/fwlog/summary",
    method: "get",
    config: { query: { hours, hide_broadcast: hideBroadcast, top: 10 } },
  });

  const events = data?.data?.events ?? [];
  const truncated = data?.data?.truncated;
  const s = sumData?.data ?? {};
  const topSources = s.top_sources ?? [];
  const topPorts = s.top_ports ?? [];

  const doRefresh = () => {
    refetch();
    refetchSummary();
  };

  return (
    <div>
      <PageHeader
        eyebrow={
          <>
            <SafetyOutlined /> Firewall · Visibilidade
          </>
        }
        title="Eventos de Firewall"
        subtitle="Quem bateu em qual porta, o que foi bloqueado e por quê — origem, destino, protocolo e interface"
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <KpiCard
            icon={<StopOutlined />}
            color="#cf1322"
            label={`Bloqueios (${s.window_hours ?? hours}h)`}
            value={(s.by_action?.drop ?? 0).toLocaleString("pt-BR")}
          />
        </Col>
        <Col xs={12} sm={6}>
          <KpiCard
            icon={<GlobalOutlined />}
            color="#1677ff"
            label="IPs de origem distintos"
            value={(s.unique_sources ?? 0).toLocaleString("pt-BR")}
          />
        </Col>
        <Col xs={12} sm={6}>
          <KpiCard
            icon={<AimOutlined />}
            color="#722ed1"
            label="Porta mais visada"
            value={topPorts[0] ? `${topPorts[0].proto}/${topPorts[0].port}` : "—"}
            suffix={topPorts[0] ? `${topPorts[0].count}×` : undefined}
          />
        </Col>
        <Col xs={12} sm={6}>
          <KpiCard
            icon={<ApiOutlined />}
            color="#fa8c16"
            label="Eventos na janela"
            value={(s.total ?? 0).toLocaleString("pt-BR")}
          />
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} md={12}>
          <Card
            bordered={false}
            size="small"
            title={
              <>
                <GlobalOutlined /> Top origens bloqueadas
              </>
            }
          >
            {topSources.length ? (
              <List
                size="small"
                dataSource={topSources}
                renderItem={(it: any) => (
                  <List.Item
                    actions={[<Tag color="red">{it.count}×</Tag>]}
                    style={{ cursor: "pointer" }}
                    onClick={() => setSrc(it.ip)}
                  >
                    <Text className="mx-mono">{it.ip}</Text>
                  </List.Item>
                )}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Sem dados" />
            )}
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card
            bordered={false}
            size="small"
            title={
              <>
                <AimOutlined /> Portas mais visadas
              </>
            }
          >
            {topPorts.length ? (
              <List
                size="small"
                dataSource={topPorts}
                renderItem={(it: any) => (
                  <List.Item
                    actions={[<Tag color="purple">{it.count}×</Tag>]}
                    style={{ cursor: "pointer" }}
                    onClick={() => setPort(String(it.port))}
                  >
                    <Space>{portTag(it.proto, it.port)}</Space>
                  </List.Item>
                )}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Sem dados" />
            )}
          </Card>
        </Col>
      </Row>

      <Card
        bordered={false}
        style={{ marginBottom: 16 }}
        styles={{ body: { paddingBottom: 8 } }}
      >
        <Space wrap size={[8, 8]}>
          <Select
            value={hours}
            onChange={setHours}
            style={{ width: 130 }}
            options={[
              { value: 1, label: "Última 1h" },
              { value: 6, label: "Últimas 6h" },
              { value: 24, label: "Últimas 24h" },
              { value: 72, label: "Últimos 3 dias" },
              { value: 168, label: "Últimos 7 dias" },
            ]}
          />
          <Input
            allowClear
            value={src}
            onChange={(e) => setSrc(e.target.value)}
            placeholder="IP de origem"
            style={{ width: 150 }}
            className="mx-mono"
          />
          <Input
            allowClear
            value={dst}
            onChange={(e) => setDst(e.target.value)}
            placeholder="IP de destino"
            style={{ width: 150 }}
            className="mx-mono"
          />
          <Input
            allowClear
            value={port}
            onChange={(e) => setPort(e.target.value)}
            placeholder="Porta"
            style={{ width: 100 }}
            className="mx-mono"
          />
          <Select
            allowClear
            value={proto}
            onChange={setProto}
            placeholder="Protocolo"
            style={{ width: 120 }}
            options={[
              { value: "TCP", label: "TCP" },
              { value: "UDP", label: "UDP" },
              { value: "ICMP", label: "ICMP" },
            ]}
          />
          <Select
            allowClear
            value={action}
            onChange={setAction}
            placeholder="Ação"
            style={{ width: 130 }}
            options={[
              { value: "drop", label: "Bloqueado" },
              { value: "log", label: "Registro" },
            ]}
          />
          <Select
            allowClear
            value={category}
            onChange={setCategory}
            placeholder="Tipo"
            style={{ width: 150 }}
            options={Object.entries(CATEGORY_LABEL).map(([v, l]) => ({
              value: v,
              label: l,
            }))}
          />
          <Input
            allowClear
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Busca livre"
            style={{ width: 160 }}
          />
          <Tooltip title="Oculta o ruído de broadcast (255.255.255.255:10001)">
            <Space size={4}>
              <Switch
                size="small"
                checked={hideBroadcast}
                onChange={setHideBroadcast}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                Ocultar broadcast
              </Text>
            </Space>
          </Tooltip>
          <Button icon={<ReloadOutlined />} loading={isFetching} onClick={doRefresh}>
            Atualizar
          </Button>
        </Space>
      </Card>

      <Card bordered={false}>
        <Table
          loading={isLoading}
          dataSource={events}
          rowKey={(_, i) => String(i)}
          size="small"
          pagination={{ pageSize: 25, showSizeChanger: false }}
          footer={() =>
            truncated ? (
              <Text type="secondary" style={{ fontSize: 12 }}>
                Exibindo os 500 eventos mais recentes da janela. Refine os filtros
                para ver mais.
              </Text>
            ) : (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {events.length} evento(s)
              </Text>
            )
          }
          columns={[
            {
              title: "Horário",
              dataIndex: "ts",
              width: 165,
              render: (t) => (
                <Text className="mx-mono" style={{ fontSize: 12 }}>
                  {t ? fmtTime(t) : "—"}
                </Text>
              ),
            },
            {
              title: "Ação",
              dataIndex: "action",
              width: 120,
              render: (a, r: any) => actionTag(a, r.reason),
            },
            {
              title: "Tipo",
              dataIndex: "category",
              width: 130,
              render: (c) => (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {CATEGORY_LABEL[c] ?? c}
                </Text>
              ),
            },
            {
              title: "Origem",
              dataIndex: "src",
              render: (v, r: any) => (
                <Space size={4}>
                  <Text
                    className="mx-mono"
                    style={{ cursor: "pointer" }}
                    onClick={() => v && setSrc(v)}
                  >
                    {v ?? "—"}
                  </Text>
                  {portTag(r.proto, r.spt)}
                </Space>
              ),
            },
            {
              title: "Destino",
              dataIndex: "dst",
              render: (v, r: any) => (
                <Space size={4}>
                  <Text
                    className="mx-mono"
                    style={{ cursor: "pointer" }}
                    onClick={() => v && setDst(v)}
                  >
                    {v ?? "—"}
                  </Text>
                  {portTag(r.proto, r.dpt)}
                </Space>
              ),
            },
            {
              title: "Interface",
              dataIndex: "in_iface",
              width: 120,
              render: (v, r: any) => (
                <Text
                  type="secondary"
                  style={{ fontSize: 12 }}
                  className="mx-mono"
                >
                  {v || r.out_iface || "—"}
                </Text>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
};
