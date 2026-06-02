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
  Select,
  Tag,
  message,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";

export const PortRulesPage = () => {
  const { tableProps } = useTable({
    resource: "input-rules",
    syncWithLocation: false,
  });
  const { mutate, isLoading } = useCreate();
  const invalidate = useInvalidate();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();

  const submit = () => {
    form.validateFields().then((values) => {
      mutate(
        { resource: "input-rules", values },
        {
          onSuccess: () => {
            message.success("Regra adicionada");
            setOpen(false);
            form.resetFields();
            invalidate({ resource: "input-rules", invalidates: ["list"] });
          },
        }
      );
    });
  };

  return (
    <List
      title="Firewall — Regras de Porta (chain input)"
      headerButtons={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setOpen(true)}
        >
          Nova Regra
        </Button>
      }
    >
      <Table {...tableProps} rowKey="id" size="middle">
        <Table.Column title="Handle" dataIndex="handle" width={90} />
        <Table.Column
          title="Expressão (nft)"
          dataIndex="expr"
          render={(e) => <span className="mx-mono">{e}</span>}
        />
        <Table.Column
          title="Ações"
          width={120}
          render={(_, r: any) => (
            <DeleteButton
              hideText
              size="small"
              resource="input-rules"
              recordItemId={r.id}
              confirmTitle={`Remover regra handle ${r.handle}?`}
            />
          )}
        />
      </Table>

      <Modal
        title="Nova regra de porta"
        open={open}
        onOk={submit}
        confirmLoading={isLoading}
        onCancel={() => setOpen(false)}
        okText="Adicionar"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="proto"
            label="Protocolo"
            initialValue="tcp"
            rules={[{ required: true }]}
          >
            <Select
              options={[
                { value: "tcp", label: "TCP" },
                { value: "udp", label: "UDP" },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="port"
            label="Porta"
            rules={[{ required: true, message: "Informe a porta" }]}
          >
            <InputNumber style={{ width: "100%" }} min={1} max={65535} />
          </Form.Item>
          <Form.Item name="action" label="Ação" initialValue="accept">
            <Select
              options={[
                { value: "accept", label: "Aceitar" },
                { value: "drop", label: "Descartar" },
              ]}
            />
          </Form.Item>
          <Form.Item name="iif" label="Interface de entrada (opcional)">
            <Input placeholder="ens18" className="mx-mono" />
          </Form.Item>
        </Form>
      </Modal>
    </List>
  );
};
