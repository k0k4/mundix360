import { useState } from "react";
import { useTable, List, DeleteButton } from "@refinedev/antd";
import { useCreate, useInvalidate } from "@refinedev/core";
import { Table, Button, Modal, Form, Input, message } from "antd";
import { PlusOutlined } from "@ant-design/icons";

export const ReservationsPage = () => {
  const { tableProps } = useTable({
    resource: "reservations",
    syncWithLocation: false,
  });
  const { mutate, isLoading } = useCreate();
  const invalidate = useInvalidate();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();

  const submit = () => {
    form.validateFields().then((values) => {
      mutate(
        { resource: "reservations", values },
        {
          onSuccess: () => {
            message.success("Reserva criada");
            setOpen(false);
            form.resetFields();
            invalidate({ resource: "reservations", invalidates: ["list"] });
          },
        }
      );
    });
  };

  return (
    <List
      title="Rede — Reservas DHCP (IP fixo)"
      headerButtons={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setOpen(true)}
        >
          Nova Reserva
        </Button>
      }
    >
      <Table {...tableProps} rowKey="id" size="middle">
        <Table.Column
          title="MAC"
          dataIndex="mac"
          render={(m) => <span className="mx-mono">{m}</span>}
        />
        <Table.Column
          title="IP"
          dataIndex="ip"
          render={(i) => <span className="mx-mono">{i}</span>}
        />
        <Table.Column title="Hostname" dataIndex="hostname" />
        <Table.Column
          title="Ações"
          width={120}
          render={(_, r: any) => (
            <DeleteButton
              hideText
              size="small"
              resource="reservations"
              recordItemId={r.id}
              confirmTitle={`Remover reserva ${r.mac}?`}
            />
          )}
        />
      </Table>

      <Modal
        title="Nova reserva DHCP"
        open={open}
        onOk={submit}
        confirmLoading={isLoading}
        onCancel={() => setOpen(false)}
        okText="Criar"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="mac"
            label="Endereço MAC"
            rules={[
              { required: true },
              {
                pattern: /^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$/,
                message: "Formato: aa:bb:cc:dd:ee:ff",
              },
            ]}
          >
            <Input placeholder="aa:bb:cc:dd:ee:ff" className="mx-mono" />
          </Form.Item>
          <Form.Item
            name="ip"
            label="IP reservado"
            rules={[{ required: true }]}
          >
            <Input placeholder="192.168.0.50" className="mx-mono" />
          </Form.Item>
          <Form.Item name="hostname" label="Hostname">
            <Input placeholder="impressora" />
          </Form.Item>
        </Form>
      </Modal>
    </List>
  );
};
