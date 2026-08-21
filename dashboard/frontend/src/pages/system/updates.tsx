import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Modal, Space, Spin, Tag, Typography, message } from "antd";
import {
  CheckCircleFilled,
  CloudDownloadOutlined,
  RocketOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import { api } from "../../api";
import { PageHeader } from "../../components/ui";

const { Text } = Typography;

type UpdateCheck = {
  current: string;
  latest: string | null;
  update_available: boolean;
  checked_at: string;
  error?: string;
};

type UpdateState = {
  state: "idle" | "running" | "success" | "failed";
  started_at?: string | null;
  finished_at?: string | null;
  log_tail?: string;
  error?: string;
};

const fmtDate = (s?: string | null) =>
  s ? new Date(s).toLocaleString("pt-BR") : "—";

export function UpdatesPage() {
  const [current, setCurrent] = useState<string | null>(null);
  const [lastCheck, setLastCheck] = useState<UpdateCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [applyState, setApplyState] = useState<UpdateState | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startPoll = useCallback(() => {
    stopPoll();
    pollRef.current = setInterval(async () => {
      try {
        const { data } = await api.get<UpdateState>("/api/system/updates/status");
        setReconnecting(false);
        setApplyState(data);
        if (data.state !== "running") {
          stopPoll();
          if (data.state === "success") {
            message.success("Atualização aplicada com sucesso");
            const ov = await api.get("/api/system/updates");
            setCurrent(ov.data.current);
            setLastCheck(ov.data.last_check);
          }
        }
      } catch {
        // A API reinicia durante o upgrade: mostra "reconectando" e segue o poll.
        setReconnecting(true);
      }
    }, 3000);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/api/system/updates");
        setCurrent(data.current);
        setLastCheck(data.last_check);
      } catch {
        /* interceptor global trata 401; demais erros aparecem no check manual */
      }
      try {
        const { data } = await api.get<UpdateState>("/api/system/updates/status");
        setApplyState(data.state === "idle" ? null : data);
        if (data.state === "running") startPoll();
      } catch {
        /* sem estado anterior */
      }
    })();
    return () => stopPoll();
  }, [startPoll]);

  const checkNow = async () => {
    setChecking(true);
    setCheckError(null);
    try {
      const { data } = await api.post<UpdateCheck>("/api/system/updates/check");
      setLastCheck(data);
      if (data.update_available) {
        message.success(`Nova versão estável disponível: ${data.latest}`);
      }
    } catch (e: any) {
      setCheckError(e?.message || "Falha ao verificar o canal de atualizações");
    } finally {
      setChecking(false);
    }
  };

  const apply = () => {
    Modal.confirm({
      title: "Aplicar atualização agora?",
      content:
        "O painel ficará indisponível por alguns segundos (ou minutos) enquanto " +
        "o pacote é atualizado e os serviços reiniciam. Não desligue o appliance " +
        "durante o processo.",
      okText: "Atualizar agora",
      cancelText: "Cancelar",
      onOk: async () => {
        try {
          const { data } = await api.post<UpdateState>("/api/system/updates/apply");
          setApplyState(data);
          startPoll();
        } catch (e: any) {
          message.error(e?.message || "Falha ao iniciar a atualização");
        }
      },
    });
  };

  const running = applyState?.state === "running";

  return (
    <div className="mx-page">
      <PageHeader
        eyebrow="Sistema · Atualizações"
        title="Atualizações"
        subtitle="Canal estável assinado (APT) com o pacote mundix360. A verificação é manual; aplicar reinicia os serviços do appliance."
        extra={
          <Button
            icon={<SyncOutlined />}
            loading={checking}
            disabled={running}
            onClick={checkNow}
          >
            Verificar atualizações
          </Button>
        }
      />

      {checkError && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message="Canal de atualizações inalcançável"
          description={checkError}
        />
      )}

      <Card title="Versão do sistema" bordered={false} className="mx-card" style={{ marginBottom: 16 }}>
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Space size={8} wrap>
            <Text type="secondary">Versão instalada:</Text>
            <Tag color="blue" className="mx-mono">{current ?? "…"}</Tag>
            {lastCheck?.latest && (
              <>
                <Text type="secondary">Canal estável:</Text>
                <Tag color={lastCheck.update_available ? "gold" : "green"} className="mx-mono">
                  {lastCheck.latest}
                </Tag>
              </>
            )}
          </Space>
          {lastCheck && !lastCheck.error && (
            <Alert
              type={lastCheck.update_available ? "warning" : "success"}
              showIcon
              message={
                lastCheck.update_available
                  ? `Há uma atualização estável disponível: ${lastCheck.latest}`
                  : "Você está na estável mais recente."
              }
              description={`Verificado em ${fmtDate(lastCheck.checked_at)}`}
            />
          )}
          {lastCheck?.update_available && (
            <div>
              <Button
                type="primary"
                icon={<RocketOutlined />}
                disabled={running}
                onClick={apply}
              >
                Atualizar agora
              </Button>
            </div>
          )}
        </Space>
      </Card>

      {applyState && applyState.state !== "idle" && (
        <Card
          title={
            <Space>
              <CloudDownloadOutlined />
              Aplicação da atualização
            </Space>
          }
          bordered={false}
          className="mx-card"
        >
          {running && (
            <Alert
              type="info"
              showIcon
              icon={<Spin size="small" />}
              style={{ marginBottom: 12 }}
              message={
                reconnecting
                  ? "Aplicando… reconectando ao painel"
                  : "Aplicando atualização…"
              }
              description={
                reconnecting
                  ? "A API está reiniciando — o acompanhamento retoma sozinho."
                  : `Iniciado em ${fmtDate(applyState.started_at)}`
              }
            />
          )}
          {applyState.state === "success" && (
            <Alert
              type="success"
              showIcon
              icon={<CheckCircleFilled />}
              style={{ marginBottom: 12 }}
              message="Atualização concluída com sucesso"
              description={`Finalizado em ${fmtDate(applyState.finished_at)}`}
            />
          )}
          {applyState.state === "failed" && (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 12 }}
              message="A atualização falhou"
              description={
                <>
                  {applyState.error && <div>{applyState.error}</div>}
                  <div>
                    Avalie o log abaixo (completo em /var/log/mundix-upgrade.log) e,
                    se necessário, faça rollback com{" "}
                    <Text code>scripts/ops/mundix-restore.sh</Text> ou restaure o
                    snapshot da VM.
                  </div>
                </>
              }
            />
          )}
          {applyState.log_tail && (
            <pre
              style={{
                background: "#0a1220",
                border: "1px solid #1b2942",
                borderRadius: 8,
                padding: 12,
                maxHeight: 320,
                overflow: "auto",
                fontSize: 12,
                whiteSpace: "pre-wrap",
                margin: 0,
              }}
            >
              {applyState.log_tail}
            </pre>
          )}
        </Card>
      )}
    </div>
  );
}
