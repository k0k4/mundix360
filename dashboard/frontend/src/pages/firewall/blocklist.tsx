import { useState } from "react";
import { useTable, List, DeleteButton } from "@refinedev/antd";
import { useCreate, useInvalidate } from "@refinedev/core";
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  InputNumber,
  Tag,
  Space,
  message,
} from "antd";
import { PlusOutlined, StopOutlined } from "@ant-design/icons";
import { ListTitle } from "../../components/ui";

export const BlocklistPage = () => {
  const { tableProps } = useTable({
    resource: "blocklist",
    syncWithLocation: false,
  });
  const { mutate, isLoading } = useCreate();
  const invalidate = useInvalidate();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();

  const submit = () => {
    form.validateFields().then((values) => {
      mutate(
        { resource: "blocklist", values },
        {
          onSuccess: () => {
            message.success(`IP ${values.ip} bloqueado`);
            setOpen(false);
            form.resetFields();
            invalidate({ resource: "blocklist", invalidates: ["list"] });
          },
        }
      );
    });
  };

  return (
    <List
      title={
        <ListTitle eyebrow={<><StopOutlined /> Firewall</>}>
          Bloqueio de IP
        </ListTitle>
      }
      headerButtons={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setOpen(true)}
        >
          Bloquear IP
        </Button>
      }
    >
      <Table {...tableProps} rowKey="id" size="middle">
        <Table.Column
          title="Endereço IP"
          dataIndex="ip"
          render={(ip) => (
            <Space>
              <StopOutlined style={{ color: "#cf1322" }} />
              <span className="mx-mono">{ip}</span>
            </Space>
          )}
        />
        <Table.Column
          title="Estado"
          render={() => <Tag color="error">bloqueado</Tag>}
          width={140}
        />
        <Table.Column
          title="Ações"
          width={140}
          render={(_, r: any) => (
            <DeleteButton
              hideText
              size="small"
              resource="blocklist"
              recordItemId={r.id}
              confirmTitle={`Desbloquear ${r.ip}?`}
            />
          )}
        />
      </Table>

      <Modal
        title="Bloquear endereço IP"
        open={open}
        onOk={submit}
        confirmLoading={isLoading}
        onCancel={() => setOpen(false)}
        okText="Bloquear"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="ip"
            label="Endereço IP"
            rules={[{ required: true, message: "Informe o IP" }]}
          >
            <Input placeholder="203.0.113.10" className="mx-mono" />
          </Form.Item>
          <Form.Item
            name="duration"
            label="Duração (segundos)"
            initialValue={3600}
          >
            <InputNumber style={{ width: "100%" }} min={60} max={2592000} />
          </Form.Item>
          <Form.Item name="reason" label="Motivo">
            <Input placeholder="Atividade maliciosa" />
          </Form.Item>
        </Form>
      </Modal>
    </List>
  );
};
