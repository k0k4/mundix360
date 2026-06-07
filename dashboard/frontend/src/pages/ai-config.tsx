import { useCallback, useEffect, useState } from "react";
import {
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
  Button,
  Space,
  Tag,
  Typography,
  Divider,
  Alert,
  message as antdMessage,
  Row,
  Col,
  Tabs,
} from "antd";
import {
  ApiOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  KeyOutlined,
  ExperimentOutlined,
  MessageOutlined,
} from "@ant-design/icons";
import { PageHeader } from "../components/ui";
import { AssistantChat, authHeaders } from "../components/AssistantChat";
import { AiBridge } from "../components/AiBridge";

const { Text, Paragraph } = Typography;

type Preset = { id: string; label: string; base_url: string; models: string[] };

type PublicConfig = {
  base_url: string;
  model: string;
  request_timeout: number;
  max_tokens: number;
  max_tool_iters: number;
  temperature: number;
  masking_enabled: boolean;
  custom_instructions: string;
  api_key_set: boolean;
  api_key_source: string;
  master_password_set: boolean;
  master_password_source: string;
  presets: Preset[];
};

export function AiConfigPage() {
  const [cfg, setCfg] = useState<PublicConfig | null>(null);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [masterCurrent, setMasterCurrent] = useState("");
  const [masterNew, setMasterNew] = useState("");

  const load = useCallback(async () => {
    const r = await fetch("/api/ai/config", { headers: authHeaders() });
    const j: PublicConfig = await r.json();
    setCfg(j);
    form.setFieldsValue({
      base_url: j.base_url,
      model: j.model,
      request_timeout: j.request_timeout,
      max_tokens: j.max_tokens,
      max_tool_iters: j.max_tool_iters,
      temperature: j.temperature,
      masking_enabled: j.masking_enabled,
      custom_instructions: j.custom_instructions,
    });
  }, [form]);

  useEffect(() => {
    load();
  }, [load]);

  const applyPreset = (id: string) => {
    const p = cfg?.presets.find((x) => x.id === id);
    if (!p) return;
    if (p.base_url) form.setFieldValue("base_url", p.base_url);
    if (p.models[0]) form.setFieldValue("model", p.models[0]);
  };

  const save = async (payload: Record<string, unknown>) => {
    setSaving(true);
    try {
      const body: Record<string, unknown> = { ...payload };
      if (cfg?.master_password_set && masterCurrent)
        body.master_password_current = masterCurrent;
      const r = await fetch("/api/ai/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify(body),
      });
      if (r.status === 403) {
        antdMessage.error(
          "Senha mestra atual obrigatória/incorreta para campos sensíveis.",
        );
        return false;
      }
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        antdMessage.error(j.detail || `Falha (HTTP ${r.status})`);
        return false;
      }
      const j: PublicConfig = await r.json();
      setCfg(j);
      antdMessage.success("Configuração salva.");
      return true;
    } catch (e: any) {
      antdMessage.error(e?.message || "Erro");
      return false;
    } finally {
      setSaving(false);
    }
  };

  const saveProvider = async () => {
    const v = form.getFieldsValue([
      "base_url",
      "model",
      "request_timeout",
    ]);
    const payload: Record<string, unknown> = { ...v };
    if (apiKey.trim()) payload.api_key = apiKey.trim();
    const ok = await save(payload);
    if (ok) setApiKey("");
  };

  const saveGeneration = async () => {
    const v = form.getFieldsValue(["max_tokens", "max_tool_iters", "temperature"]);
    await save(v);
  };

  const saveGuardrails = async () => {
    const payload: Record<string, unknown> = {
      masking_enabled: form.getFieldValue("masking_enabled"),
    };
    if (masterNew.trim()) payload.master_password = masterNew.trim();
    const ok = await save(payload);
    if (ok) {
      setMasterNew("");
      setMasterCurrent("");
    }
  };

  const savePrompt = async () => {
    await save({ custom_instructions: form.getFieldValue("custom_instructions") });
  };

  const testConnection = async () => {
    setTesting(true);
    try {
      const body: Record<string, unknown> = {
        base_url: form.getFieldValue("base_url"),
        model: form.getFieldValue("model"),
      };
      if (apiKey.trim()) body.api_key = apiKey.trim();
      const r = await fetch("/api/ai/config/test", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify(body),
      });
      const j = await r.json();
      if (j.ok)
        antdMessage.success(`Conexão OK — modelo ${j.model} respondeu "${j.reply}".`);
      else antdMessage.error(`Falha na conexão: ${j.error || "desconhecida"}`);
    } catch (e: any) {
      antdMessage.error(e?.message || "Erro no teste");
    } finally {
      setTesting(false);
    }
  };

  if (!cfg) return null;

  const sensitiveNote = cfg.master_password_set ? (
    <Form.Item label="Senha mestra atual (para autorizar alterações sensíveis)">
      <Input.Password
        value={masterCurrent}
        onChange={(e) => setMasterCurrent(e.target.value)}
        placeholder="Necessária para mudar provedor, chave, guardrails…"
      />
    </Form.Item>
  ) : (
    <Alert
      type="info"
      showIcon
      style={{ marginBottom: 16 }}
      message="Nenhuma senha mestra definida"
      description="Defina uma senha mestra na aba Guardrails para habilitar a edição de código pela IA e proteger alterações sensíveis."
    />
  );

  const configTab = (
    <Form form={form} layout="vertical" requiredMark={false}>
      {sensitiveNote}

      <Card
        title={
          <Space>
            <ApiOutlined /> Provedor
          </Space>
        }
        style={{ marginBottom: 16 }}
        extra={
          <Space>
            <Tag color={cfg.api_key_set ? "green" : "red"}>
              {cfg.api_key_set ? `chave: ${cfg.api_key_source}` : "sem chave"}
            </Tag>
            <Button
              icon={<ThunderboltOutlined />}
              loading={testing}
              onClick={testConnection}
            >
              Testar conexão
            </Button>
          </Space>
        }
      >
        <Row gutter={16}>
          <Col xs={24} md={8}>
            <Form.Item label="Preset">
              <Select
                placeholder="Selecionar provedor…"
                onChange={applyPreset}
                options={cfg.presets.map((p) => ({ value: p.id, label: p.label }))}
              />
            </Form.Item>
          </Col>
          <Col xs={24} md={16}>
            <Form.Item label="Base URL" name="base_url">
              <Input placeholder="https://…/v1" />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item label="Modelo" name="model">
              <Input placeholder="qwen3.7-max" />
            </Form.Item>
          </Col>
          <Col xs={24} md={12}>
            <Form.Item label="Timeout (s)" name="request_timeout">
              <InputNumber min={5} max={600} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col xs={24}>
            <Form.Item
              label={
                <Space>
                  <KeyOutlined /> Chave de API (gravação; não é exibida)
                </Space>
              }
            >
              <Input.Password
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={
                  cfg.api_key_set
                    ? "•••••• (deixe em branco para manter a atual)"
                    : "Cole a chave de API"
                }
              />
            </Form.Item>
          </Col>
        </Row>
        <Button type="primary" loading={saving} onClick={saveProvider}>
          Salvar provedor
        </Button>
      </Card>

      <Card
        title={
          <Space>
            <ExperimentOutlined /> Geração
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <Row gutter={16}>
          <Col xs={24} md={8}>
            <Form.Item label="Máx. tokens" name="max_tokens">
              <InputNumber min={64} max={8192} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col xs={24} md={8}>
            <Form.Item
              label="Máx. iterações de ferramenta"
              name="max_tool_iters"
              tooltip="0 = sem limite (a IA continua até concluir)"
            >
              <InputNumber min={0} max={500} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col xs={24} md={8}>
            <Form.Item label="Temperatura" name="temperature">
              <InputNumber
                min={0}
                max={2}
                step={0.1}
                style={{ width: "100%" }}
              />
            </Form.Item>
          </Col>
        </Row>
        <Button type="primary" loading={saving} onClick={saveGeneration}>
          Salvar geração
        </Button>
      </Card>

      <Card
        title={
          <Space>
            <SafetyCertificateOutlined /> Guardrails &amp; Segurança
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <Form.Item
          label="Mascaramento de dados sensíveis (anti-moderação)"
          name="masking_enabled"
          valuePropName="checked"
          extra="Substitui domínios/URLs por marcadores antes de enviar ao modelo. Recomenda-se manter LIGADO."
        >
          <Switch checkedChildren="ON" unCheckedChildren="OFF" />
        </Form.Item>
        <Divider />
        <Paragraph type="secondary" style={{ marginBottom: 8 }}>
          Senha mestra{" "}
          <Tag color={cfg.master_password_set ? "green" : "orange"}>
            {cfg.master_password_set
              ? `definida (${cfg.master_password_source})`
              : "não definida"}
          </Tag>
          — protege a edição de código pela IA e alterações sensíveis.
        </Paragraph>
        <Form.Item label="Nova senha mestra">
          <Input.Password
            value={masterNew}
            onChange={(e) => setMasterNew(e.target.value)}
            placeholder={
              cfg.master_password_set
                ? "Definir nova senha (opcional)"
                : "Definir senha mestra"
            }
          />
        </Form.Item>
        <Button type="primary" loading={saving} onClick={saveGuardrails}>
          Salvar guardrails
        </Button>
      </Card>

      <Card
        title={
          <Space>
            <MessageOutlined /> Prompt do sistema (instruções do operador)
          </Space>
        }
      >
        <Paragraph type="secondary">
          Adicione preferências e instruções de comportamento. Elas são{" "}
          <Text strong>subordinadas</Text> à política de segurança fixa da
          plataforma.
        </Paragraph>
        <Form.Item name="custom_instructions">
          <Input.TextArea
            rows={6}
            placeholder="Ex.: Responda sempre em português, seja conciso, confirme antes de ações destrutivas…"
          />
        </Form.Item>
        <Button type="primary" loading={saving} onClick={savePrompt}>
          Salvar prompt
        </Button>
      </Card>
    </Form>
  );

  return (
    <div>
      <PageHeader
        eyebrow="Mundix AI"
        title="Configuração da IA"
        subtitle="Provedor, geração, guardrails de segurança e prompt do sistema. O chat contextual fica disponível no botão flutuante em todas as telas."
      />
      <Tabs
        items={[
          { key: "config", label: "Configuração", children: configTab },
          {
            key: "memory",
            label: "Memória viva & Mural",
            children: <AiBridge />,
          },
          {
            key: "chat",
            label: "Chat",
            children: (
              <Card styles={{ body: { padding: 0 } }}>
                <div style={{ height: "calc(100vh - 320px)", minHeight: 420 }}>
                  <AssistantChat emptyHint='Painel de teste do agente. Ex.: "Liste os serviços parados".' />
                </div>
              </Card>
            ),
          },
        ]}
      />
    </div>
  );
}
