import { useTable, List } from "@refinedev/antd";
import { useCustomMutation, useInvalidate } from "@refinedev/core";
import { Table, Tag, Button, Space, Popconfirm, message } from "antd";
import {
  ReloadOutlined,
  PlayCircleOutlined,
  PoweroffOutlined,
  SyncOutlined,
  CloudServerOutlined,
} from "@ant-design/icons";
import { ListTitle } from "../../components/ui";

export const ServicesPage = () => {
  const { tableProps } = useTable({
    resource: "services",
    syncWithLocation: false,
  });
  const { mutate, isLoading } = useCustomMutation();
  const invalidate = useInvalidate();

  const act = (name: string, action: string) => {
    mutate(
      {
        url: `/api/system/services/${name}/action`,
        method: "post",
        values: { action },
      },
      {
        onSuccess: () => {
          message.success(`${name}: ${action} executado`);
          invalidate({ resource: "services", invalidates: ["list"] });
        },
        onError: () => message.error(`Falha ao executar ${action} em ${name}`),
      }
    );
  };

  return (
    <List
      title={
        <ListTitle eyebrow={<><CloudServerOutlined /> Sistema</>}>
          Serviços da Plataforma
        </ListTitle>
      }
    >
      <Table {...tableProps} rowKey="id" size="middle">
        <Table.Column
          title="Serviço"
          dataIndex="name"
          render={(n) => <span className="mx-mono">{n}</span>}
        />
        <Table.Column
          title="Estado"
          dataIndex="running"
          render={(r: boolean, rec: any) => (
            <Tag color={r ? "success" : "error"}>{rec.active}</Tag>
          )}
        />
        <Table.Column
          title="Boot"
          dataIndex="enabled"
          render={(e) => <Tag>{e}</Tag>}
        />
        <Table.Column
          title="Ações"
          width={260}
          render={(_, r: any) => (
            <Space>
              <Button
                size="small"
                icon={<ReloadOutlined />}
                loading={isLoading}
                onClick={() => act(r.name, "restart")}
              >
                Reiniciar
              </Button>
              <Button
                size="small"
                icon={<SyncOutlined />}
                onClick={() => act(r.name, "reload-or-restart")}
              >
                Reload
              </Button>
              {r.running ? (
                <Popconfirm
                  title={`Parar ${r.name}?`}
                  onConfirm={() => act(r.name, "stop")}
                >
                  <Button size="small" danger icon={<PoweroffOutlined />} />
                </Popconfirm>
              ) : (
                <Button
                  size="small"
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  onClick={() => act(r.name, "start")}
                />
              )}
            </Space>
          )}
        />
      </Table>
    </List>
  );
};
