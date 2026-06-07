import { useCallback, useEffect, useState } from "react";
import {
  Card, Row, Col, Button, Input, Space, Tag, Typography, Empty, Spin,
  Tooltip, message as antdMessage,
} from "antd";
import {
  SaveOutlined, ReloadOutlined, SendOutlined, BookOutlined,
  RobotOutlined, ToolOutlined, UserOutlined, BulbOutlined,
} from "@ant-design/icons";
import { authHeaders } from "./AssistantChat";

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

const AUTHOR_META: Record<string, { icon: any; color: string; label: string }> = {
  "mundix-ai": { icon: <RobotOutlined />, color: "#22d3ee", label: "Mundix AI" },
  "copilot-cli": { icon: <ToolOutlined />, color: "#a855f7", label: "Copilot CLI" },
  operator: { icon: <UserOutlined />, color: "#22c55e", label: "Operador" },
};

const fmt = (t: number) =>
  new Date(t * 1000).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });

async function jget(url: string) {
  const r = await fetch(url, { headers: authHeaders() });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function jsend(url: string, method: string, body: any) {
  const r = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail || "falha");
  return r.json();
}

/* ----------------------------------------------------- Living memory ----- */
function LivingMemory() {
  const [content, setContent] = useState("");
  const [meta, setMeta] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, ctx] = antdMessage.useMessage();

  const load = useCallback(async () => {
    setLoading(true);
    const d = await jget("/api/ai/living-memory");
    setContent(d.content || "");
    setMeta(d);
    setDirty(false);
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const d = await jsend("/api/ai/living-memory", "PUT",
        { content, updated_by: "operator" });
      setMeta(d); setDirty(false); msg.success("Memória viva salva");
    } catch (e: any) { msg.error(e.message || "Falha ao salvar"); }
    finally { setSaving(false); }
  };

  return (
    <Card bordered={false}>
      {ctx}
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 12 }} wrap>
        <Space>
          <BookOutlined style={{ color: "#22d3ee" }} />
          <Text strong>Documento vivo do sistema</Text>
          {meta && <Tag>{(content.length / 1000).toFixed(1)}k / 20k chars</Tag>}
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load}>Recarregar</Button>
          <Button type="primary" icon={<SaveOutlined />} loading={saving}
            disabled={!dirty} onClick={save}>Salvar</Button>
        </Space>
      </Space>
      <Paragraph type="secondary" style={{ fontSize: 13 }}>
        Curado pelo operador, pela Mundix AI (ferramenta <code>update_system_memory</code>)
        e pelo agente de build. É injetado no prompt a cada conversa, então a IA nunca
        “esquece” como o sistema funciona. Mantenha enxuto (markdown com seções <code>## </code>).
      </Paragraph>
      {loading ? <Spin /> : (
        <TextArea value={content} className="mx-mono"
          onChange={(e) => { setContent(e.target.value); setDirty(true); }}
          autoSize={{ minRows: 16, maxRows: 32 }}
          style={{ fontSize: 13 }} />
      )}
      {meta?.updated_at && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          Última edição: {fmt(meta.updated_at)} por {meta.updated_by}
        </Text>
      )}
    </Card>
  );
}

/* ----------------------------------------------------------- Journal ----- */
function Journal() {
  const [entries, setEntries] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState("");
  const [topic, setTopic] = useState("");
  const [sending, setSending] = useState(false);
  const [msg, ctx] = antdMessage.useMessage();

  const load = useCallback(async () => {
    setLoading(true);
    const d = await jget("/api/ai/journal?limit=100");
    setEntries(d.entries || []);
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);

  const post = async () => {
    if (!text.trim()) return;
    setSending(true);
    try {
      await jsend("/api/ai/journal", "POST",
        { message: text.trim(), topic: topic.trim() || undefined, author: "operator" });
      setText(""); setTopic(""); msg.success("Recado publicado"); load();
    } catch (e: any) { msg.error(e.message || "Falha"); }
    finally { setSending(false); }
  };

  return (
    <Card bordered={false}>
      {ctx}
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 12 }} wrap>
        <Space><BulbOutlined style={{ color: "#f59e0b" }} />
          <Text strong>Mural / Diário entre IAs e operador</Text></Space>
        <Button icon={<ReloadOutlined />} onClick={load}>Recarregar</Button>
      </Space>
      <Paragraph type="secondary" style={{ fontSize: 13 }}>
        Canal compartilhado: a <b>Mundix AI</b>, o <b>agente de build (Copilot CLI)</b> e
        você trocam recados aqui. As mensagens recentes entram no contexto da IA.
      </Paragraph>

      <Card size="small" style={{ marginBottom: 16, background: "#0e1830" }}>
        <Space.Compact style={{ width: "100%", marginBottom: 8 }}>
          <Input prefix="#" placeholder="assunto (opcional)" value={topic}
            onChange={(e) => setTopic(e.target.value)} style={{ maxWidth: 220 }} />
        </Space.Compact>
        <TextArea value={text} onChange={(e) => setText(e.target.value)}
          placeholder="Deixe um recado para a Mundix AI ou para o agente de build…"
          autoSize={{ minRows: 2, maxRows: 5 }} />
        <div style={{ textAlign: "right", marginTop: 8 }}>
          <Button type="primary" icon={<SendOutlined />} loading={sending}
            onClick={post} disabled={!text.trim()}>Publicar</Button>
        </div>
      </Card>

      {loading ? <Spin /> : entries.length === 0 ? (
        <Empty description="Nenhum recado ainda" />
      ) : (
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          {entries.map((e) => {
            const m = AUTHOR_META[e.author] || AUTHOR_META.operator;
            return (
              <Card key={e.id} size="small" styles={{ body: { padding: 12 } }}
                style={{ borderLeft: `3px solid ${m.color}` }}>
                <Space style={{ justifyContent: "space-between", width: "100%" }} wrap>
                  <Space size={6}>
                    <span style={{ color: m.color }}>{m.icon}</span>
                    <Text strong style={{ color: m.color }}>{m.label}</Text>
                    {e.topic && <Tag color="default">#{e.topic}</Tag>}
                  </Space>
                  <Tooltip title={fmt(e.created_at)}>
                    <Text type="secondary" style={{ fontSize: 12 }}>{fmt(e.created_at)}</Text>
                  </Tooltip>
                </Space>
                <Paragraph style={{ margin: "6px 0 0", whiteSpace: "pre-wrap" }}>
                  {e.content}
                </Paragraph>
              </Card>
            );
          })}
        </Space>
      )}
    </Card>
  );
}

export function AiBridge() {
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={13}><LivingMemory /></Col>
      <Col xs={24} lg={11}><Journal /></Col>
    </Row>
  );
}
