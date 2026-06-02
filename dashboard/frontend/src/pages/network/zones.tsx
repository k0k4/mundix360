import { List, useTable, EditButton, DeleteButton, Create, Edit, useForm } from "@refinedev/antd";
import { Table, Tag, Form, Input, Select, Space, Typography, Alert } from "antd";

const { Text } = Typography;

const INTERFACES = [
  { value: "ens19", label: "ens19 (LAN)" },
  { value: "ens20", label: "ens20 (DMZ)" },
  { value: "ens21", label: "ens21 (IoT)" },
];

export const ZoneList = () => {
  const { tableProps } = useTable({ resource: "zones", syncWithLocation: false });
  return (
    <List title="Rede — VLANs / Zonas">
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
          title="Gateway"
          dataIndex="gateway"
          render={(g) => <span className="mx-mono">{g || "—"}</span>}
        />
        <Table.Column
          title="DHCP"
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

const ZoneFormFields = () => (
  <>
    <Form.Item name="interface" label="Interface" rules={[{ required: true }]}>
      <Select options={INTERFACES} />
    </Form.Item>
    <Form.Item name="domain" label="Domínio local">
      <Input placeholder="lan.mundix" />
    </Form.Item>
    <Form.Item name="gateway" label="Gateway / IP do router">
      <Input placeholder="192.168.10.1" className="mx-mono" />
    </Form.Item>
    <Form.Item name="netmask" label="Máscara">
      <Input placeholder="255.255.255.0" className="mx-mono" />
    </Form.Item>
    <Space size={12}>
      <Form.Item name="dhcp_start" label="DHCP início">
        <Input placeholder="192.168.10.50" className="mx-mono" />
      </Form.Item>
      <Form.Item name="dhcp_end" label="DHCP fim">
        <Input placeholder="192.168.10.200" className="mx-mono" />
      </Form.Item>
      <Form.Item name="lease_time" label="Lease" initialValue="24h">
        <Input placeholder="24h" />
      </Form.Item>
    </Space>
  </>
);

export const ZoneCreate = () => {
  const { formProps, saveButtonProps } = useForm({
    resource: "zones",
    action: "create",
    redirect: "list",
  });
  return (
    <Create saveButtonProps={saveButtonProps} title="Nova Zona / VLAN">
      <Alert
        type="info"
        showIcon
        message="A configuração é validada com dnsmasq --test antes de aplicar; em caso de erro há rollback automático."
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
    <Edit saveButtonProps={saveButtonProps} title="Editar Zona">
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
