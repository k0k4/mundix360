import { useState } from "react";
import { useTable, List, DeleteButton } from "@refinedev/antd";
import { useCreate, useInvalidate } from "@refinedev/core";
import { Table, Button, Modal, Form, Input, Space, message } from "antd";
import { PlusOutlined, GlobalOutlined } from "@ant-design/icons";
import { ListTitle } from "../../components/ui";

export const DomainsPage = () => {
  const { tableProps } = useTable({
    resource: "domains",
    syncWithLocation: false,
  });
  const { mutate, isLoading } = useCreate();
  const invalidate = useInvalidate();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();

  const submit = () => {
    form.validateFields().then((values) => {
      mutate(
        { resource: "domains", values },
        {
          onSuccess: () => {
            message.success(`Domínio ${values.domain} bloqueado`);
            setOpen(false);
            form.resetFields();
            invalidate({ resource: "domains", invalidates: ["list"] });
          },
        }
      );
    });
  };

  return (
    <List
      title={
        <ListTitle eyebrow={<><GlobalOutlined /> DNS Sinkhole</>}>
          Filtro de Conteúdo
        </ListTitle>
      }
      headerButtons={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => setOpen(true)}
        >
          Bloquear Domínio
        </Button>
      }
    >
      <Table {...tableProps} rowKey="id" size="middle">
        <Table.Column
          title="Domínio"
          dataIndex="domain"
          render={(d) => (
            <Space>
              <GlobalOutlined style={{ color: "#fa8c16" }} />
              <span className="mx-mono">{d}</span>
            </Space>
          )}
        />
        <Table.Column title="Nota" dataIndex="note" />
        <Table.Column
          title="Ações"
          width={120}
          render={(_, r: any) => (
            <DeleteButton
              hideText
              size="small"
              resource="domains"
              recordItemId={r.id}
              confirmTitle={`Desbloquear ${r.domain}?`}
            />
          )}
        />
      </Table>

      <Modal
        title="Bloquear domínio"
        open={open}
        onOk={submit}
        confirmLoading={isLoading}
        onCancel={() => setOpen(false)}
        okText="Bloquear"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="domain"
            label="Domínio"
            rules={[{ required: true, message: "Informe o domínio" }]}
          >
            <Input placeholder="exemplo.com" className="mx-mono" />
          </Form.Item>
          <Form.Item name="note" label="Nota / categoria">
            <Input placeholder="malware, adulto, ..." />
          </Form.Item>
        </Form>
      </Modal>
    </List>
  );
};
