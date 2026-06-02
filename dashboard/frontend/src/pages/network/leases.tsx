import { useTable, List } from "@refinedev/antd";
import { Table, Tag, Empty } from "antd";
import { fmtTime } from "../../format";

export const LeasesPage = () => {
  const { tableProps } = useTable({
    resource: "dhcp-leases",
    syncWithLocation: false,
  });
  return (
    <List title="Rede — Leases DHCP ativos">
      <Table
        {...tableProps}
        rowKey={(r: any) => r.mac || r.ip}
        size="middle"
        locale={{ emptyText: <Empty description="Nenhum lease ativo" /> }}
      >
        <Table.Column
          title="IP"
          dataIndex="ip"
          render={(i) => <span className="mx-mono">{i}</span>}
        />
        <Table.Column
          title="MAC"
          dataIndex="mac"
          render={(m) => <span className="mx-mono">{m}</span>}
        />
        <Table.Column
          title="Hostname"
          dataIndex="hostname"
          render={(h) => h || <Tag>—</Tag>}
        />
        <Table.Column
          title="Zona"
          dataIndex="zone"
          render={(z) => (z ? <Tag color="blue">{z}</Tag> : "—")}
        />
        <Table.Column
          title="Expira"
          dataIndex="expiry"
          render={(e) => (e ? fmtTime(e * 1000) : "—")}
        />
      </Table>
    </List>
  );
};
