import {
  List,
  useTable,
  EditButton,
  DeleteButton,
  Create,
  Edit,
  useForm,
} from "@refinedev/antd";
import {
  Table,
  Tag,
  Form,
  Input,
  Select,
  Space,
  Typography,
  Alert,
  Row,
  Col,
  Divider,
} from "antd";
import { PartitionOutlined } from "@ant-design/icons";
import { useEffect, useState } from "react";
import { api } from "../../api";
import { ListTitle } from "../../components/ui";
import {
  deriveNetwork,
  derivePool,
  prefixToMask,
} from "./ipmath";

const { Text } = Typography;

type Iface = {
  interface: string;
  address?: string | null;
  addresses?: string[];
  state?: string;
  mac?: string;
  is_wan?: boolean;
};

function useInterfaces() {
  const [ifaces, setIfaces] = useState<Iface[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    api
      .get<{ interfaces: Iface[] }>("/api/network/interfaces")
      .then((r) => {
        const list = r.data?.interfaces;
        if (alive) setIfaces(Array.isArray(list) ? list : []);
      })
      .catch(() => {
        if (alive) setIfaces([]);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);
  return { ifaces, loading };
}

const NETMASKS = [
  { value: "255.255.255.0", label: "/24 · 255.255.255.0 (254 hosts)" },
  { value: "255.255.255.128", label: "/25 · 255.255.255.128 (126 hosts)" },
  { value: "255.255.255.192", label: "/26 · 255.255.255.192 (62 hosts)" },
  { value: "255.255.0.0", label: "/16 · 255.255.0.0 (65534 hosts)" },
  { value: "255.0.0.0", label: "/8 · 255.0.0.0" },
];

export const ZoneList = () => {
  const { tableProps } = useTable({ resource: "zones", syncWithLocation: false });
  return (
    <List
      title={
        <ListTitle eyebrow={<><PartitionOutlined /> Rede · Segmentação</>}>
          VLANs / Sub-redes
        </ListTitle>
      }
    >
      <Table {...tableProps} rowKey="id" size="middle">
        <Table.Column
          title="Zona"
          dataIndex="zone"
          render={(z, r: any) => (
            <Space>
              <Text strong>{z}</Text>
              {r.builtin && <Tag color="blue">built-in</Tag>}
            </Space>
          )}
        />
        <Table.Column
          title="Interface"
          dataIndex="interface"
          render={(i) => <span className="mx-mono">{i}</span>}
        />
        <Table.Column
          title="Rede"
          render={(_, r: any) => (
            <Space direction="vertical" size={0}>
              <span className="mx-mono">{r.network || "—"}</span>
              {r.listen_address && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  appliance <span className="mx-mono">{r.listen_address}</span>
                </Text>
              )}
            </Space>
          )}
        />
        <Table.Column
          title="Gateway"
          dataIndex="gateway"
          render={(g) => <span className="mx-mono">{g || "—"}</span>}
        />
        <Table.Column
          title="Pool DHCP"
          render={(_, r: any) =>
            r.dhcp_start ? (
              <span className="mx-mono">
                {r.dhcp_start} → {r.dhcp_end}
              </span>
            ) : (
              <Tag>desativado</Tag>
            )
          }
        />
        <Table.Column
          title="Ações"
          width={140}
          render={(_, r: any) => (
            <Space>
              <EditButton hideText size="small" recordItemId={r.id} />
              <DeleteButton
                hideText
                size="small"
                recordItemId={r.id}
                disabled={r.builtin}
                confirmTitle={`Excluir zona ${r.zone}?`}
              />
            </Space>
          )}
        />
      </Table>
    </List>
  );
};

const NetworkHint = () => {
  const ip = Form.useWatch("listen_address");
  const mask = Form.useWatch("netmask");
  const net = deriveNetwork(ip, mask);
  if (!net) return null;
  return (
    <Alert
      type="success"
      showIcon
      style={{ marginBottom: 16 }}
      message={
        <span>
          Sub-rede resultante: <span className="mx-mono">{net}</span>
        </span>
      }
    />
  );
};

const ZoneFormFields = () => {
  const { ifaces, loading } = useInterfaces();
  const form = Form.useFormInstance();
  const options = ifaces.map((i) => {
    const meta: string[] = [];
    if (i.address) meta.push(i.address);
    if (i.state && i.state !== "up") meta.push(i.state);
    const suffix = meta.length ? ` · ${meta.join(" · ")}` : "";
    return {
      value: i.interface,
      label: `${i.interface}${i.is_wan ? " (WAN)" : ""}${suffix}`,
    };
  });
  // Pre-fill addressing from the selected interface, but ONLY empty fields —
  // never overwrite what the operator typed. Makes the default DHCP pool
  // visible on screen instead of hidden magic.
  const onIfaceChange = (name: string) => {
    const i = ifaces.find((x) => x.interface === name);
    const cidr = i?.address || i?.addresses?.[0];
    const [ip, p] = (cidr || "").split("/");
    const mask = prefixToMask(Number(p));
    if (!ip || !mask) return;
    const patch: Record<string, string> = {};
    if (!form.getFieldValue("listen_address")) patch.listen_address = ip;
    if (!form.getFieldValue("netmask")) patch.netmask = mask;
    if (!form.getFieldValue("gateway")) patch.gateway = ip;
    const pool = derivePool(ip, mask);
    if (pool) {
      if (!form.getFieldValue("dhcp_start")) patch.dhcp_start = pool[0];
      if (!form.getFieldValue("dhcp_end")) patch.dhcp_end = pool[1];
    }
    if (Object.keys(patch).length) form.setFieldsValue(patch);
  };
  return (
    <>
      <Divider orientation="left" plain>
        Segmento
      </Divider>
      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Form.Item
            name="interface"
            label="Interface"
            rules={[{ required: true }]}
            tooltip="Interfaces detectadas automaticamente neste appliance. Você também pode digitar um nome manualmente."
          >
            <Select
              showSearch
              loading={loading}
              options={options}
              placeholder={loading ? "Detectando interfaces…" : "Selecione a interface"}
              notFoundContent={loading ? "Detectando…" : "Nenhuma interface detectada"}
              optionFilterProp="label"
              onChange={onIfaceChange}
            />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name="domain" label="Domínio local">
            <Input placeholder="lan.mundix360.local" />
          </Form.Item>
        </Col>
      </Row>

      <Divider orientation="left" plain>
        Endereçamento da rede
      </Divider>
      <NetworkHint />
      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Form.Item
            name="listen_address"
            label="Endereço do appliance"
            tooltip="IP deste appliance nesta rede (serve DNS e DHCP)."
          >
            <Input placeholder="192.168.10.2" className="mx-mono" />
          </Form.Item>
        </Col>
        <Col xs={24} md={8}>
          <Form.Item name="netmask" label="Máscara de rede">
            <Select
              options={NETMASKS}
              placeholder="255.255.255.0"
              showSearch
              allowClear
            />
          </Form.Item>
        </Col>
        <Col xs={24} md={8}>
          <Form.Item
            name="gateway"
            label="Gateway (router)"
            tooltip="Gateway entregue aos clientes via DHCP (opção 3)."
          >
            <Input placeholder="192.168.10.1" className="mx-mono" />
          </Form.Item>
        </Col>
      </Row>

      <Divider orientation="left" plain>
        Pool DHCP
      </Divider>
      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Form.Item name="dhcp_start" label="Início do pool">
            <Input placeholder="192.168.10.50" className="mx-mono" />
          </Form.Item>
        </Col>
        <Col xs={24} md={8}>
          <Form.Item name="dhcp_end" label="Fim do pool">
            <Input placeholder="192.168.10.200" className="mx-mono" />
          </Form.Item>
        </Col>
        <Col xs={24} md={8}>
          <Form.Item name="lease_time" label="Tempo de lease" initialValue="24h">
            <Input placeholder="24h" />
          </Form.Item>
        </Col>
      </Row>

      <Divider orientation="left" plain>
        DNS
      </Divider>
      <Form.Item
        name="upstream_dns"
        label="DNS upstream (resolvers desta zona)"
        tooltip="Servidores para os quais o dnsmasq encaminha consultas nesta zona."
      >
        <Select
          mode="tags"
          tokenSeparators={[",", " "]}
          placeholder="1.1.1.1, 9.9.9.9"
          className="mx-mono"
        />
      </Form.Item>
    </>
  );
};

export const ZoneCreate = () => {
  const { formProps, saveButtonProps } = useForm({
    resource: "zones",
    action: "create",
    redirect: "list",
  });
  return (
    <Create saveButtonProps={saveButtonProps} title="Nova Zona / Sub-rede">
      <Alert
        type="info"
        showIcon
        message="A configuração é validada (sub-rede coerente + dnsmasq --test) antes de aplicar; em caso de erro há rollback automático."
        style={{ marginBottom: 16 }}
      />
      <Form {...formProps} layout="vertical">
        <Form.Item
          name="zone"
          label="Nome da zona"
          rules={[
            { required: true },
            {
              pattern: /^[a-z][a-z0-9_-]{1,30}$/,
              message: "minúsculas, começa com letra (ex: guest)",
            },
          ]}
        >
          <Input placeholder="guest" />
        </Form.Item>
        <ZoneFormFields />
      </Form>
    </Create>
  );
};

export const ZoneEdit = () => {
  const { formProps, saveButtonProps, queryResult } = useForm({
    resource: "zones",
    action: "edit",
    redirect: "list",
  });
  const builtin = queryResult?.data?.data?.builtin;
  return (
    <Edit saveButtonProps={saveButtonProps} title="Editar Zona / Sub-rede">
      {builtin && (
        <Alert
          type="warning"
          message="Zona built-in: edite com cuidado para não interromper a rede em produção."
          style={{ marginBottom: 16 }}
        />
      )}
      <Form {...formProps} layout="vertical">
        <Form.Item name="zone" label="Nome da zona">
          <Input disabled />
        </Form.Item>
        <ZoneFormFields />
      </Form>
    </Edit>
  );
};
