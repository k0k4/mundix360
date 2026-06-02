import { Refine } from "@refinedev/core";
import {
  ThemedLayoutV2,
  ThemedSiderV2,
  ErrorComponent,
  useNotificationProvider,
  RefineThemes,
} from "@refinedev/antd";
import routerProvider, {
  NavigateToResource,
  UnsavedChangesNotifier,
  DocumentTitleHandler,
} from "@refinedev/react-router-v6";
import { BrowserRouter, Routes, Route, Outlet } from "react-router-dom";
import { ConfigProvider, theme as antdTheme } from "antd";
import {
  DashboardOutlined,
  AlertOutlined,
  SafetyCertificateOutlined,
  ApiOutlined,
  StopOutlined,
  GlobalOutlined,
  ClusterOutlined,
  PartitionOutlined,
  NodeIndexOutlined,
  FileTextOutlined,
  CloudServerOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import "@refinedev/antd/dist/reset.css";

import { dataProvider } from "./dataProvider";
import { Brand } from "./components/Brand";
import { Overview } from "./pages/overview";
import { AlertList, AlertShow } from "./pages/alerts";
import { BlocklistPage } from "./pages/firewall/blocklist";
import { PortRulesPage } from "./pages/firewall/portRules";
import { RulesetPage } from "./pages/firewall/ruleset";
import { ZoneList, ZoneCreate, ZoneEdit } from "./pages/network/zones";
import { ReservationsPage } from "./pages/network/reservations";
import { LeasesPage } from "./pages/network/leases";
import { DomainsPage } from "./pages/content/domains";
import { FlowsPage } from "./pages/flows";
import { LogsPage } from "./pages/logs";
import { ServicesPage } from "./pages/system/services";
import { AssistantPage } from "./pages/assistant";

const Title = ({ collapsed }: { collapsed: boolean }) => (
  <Brand collapsed={collapsed} />
);

export default function App() {
  return (
    <BrowserRouter>
      <ConfigProvider
        theme={{
          ...RefineThemes.Blue,
          algorithm: antdTheme.darkAlgorithm,
          token: {
            ...RefineThemes.Blue.token,
            colorPrimary: "#1668dc",
            colorBgLayout: "#0b1220",
            colorBgContainer: "#111a2e",
            colorBgElevated: "#15203a",
            borderRadius: 8,
          },
        }}
      >
        <Refine
          dataProvider={dataProvider}
          routerProvider={routerProvider}
          notificationProvider={useNotificationProvider}
          options={{
            syncWithLocation: true,
            warnWhenUnsavedChanges: true,
            disableTelemetry: true,
          }}
          resources={[
            {
              name: "overview",
              list: "/",
              meta: { label: "Visão Geral", icon: <DashboardOutlined /> },
            },
            {
              name: "assistant",
              list: "/assistant",
              meta: { label: "Mundix AI", icon: <RobotOutlined /> },
            },
            {
              name: "alerts",
              list: "/siem",
              show: "/siem/:id",
              meta: { label: "SIEM / Alertas", icon: <AlertOutlined /> },
            },
            {
              name: "firewall-group",
              meta: {
                label: "Firewall",
                icon: <SafetyCertificateOutlined />,
              },
            },
            {
              name: "blocklist",
              list: "/firewall/blocklist",
              create: "/firewall/blocklist/new",
              meta: {
                parent: "firewall-group",
                label: "Bloqueio de IP",
                icon: <StopOutlined />,
              },
            },
            {
              name: "input-rules",
              list: "/firewall/ports",
              create: "/firewall/ports/new",
              meta: {
                parent: "firewall-group",
                label: "Regras de Porta",
                icon: <ApiOutlined />,
              },
            },
            {
              name: "ruleset",
              list: "/firewall/ruleset",
              meta: {
                parent: "firewall-group",
                label: "Ruleset (nft)",
                icon: <PartitionOutlined />,
              },
            },
            {
              name: "network-group",
              meta: { label: "Rede", icon: <ClusterOutlined /> },
            },
            {
              name: "zones",
              list: "/network/zones",
              create: "/network/zones/new",
              edit: "/network/zones/:id/edit",
              meta: {
                parent: "network-group",
                label: "VLANs / Zonas",
                icon: <PartitionOutlined />,
              },
            },
            {
              name: "reservations",
              list: "/network/reservations",
              create: "/network/reservations/new",
              meta: {
                parent: "network-group",
                label: "Reservas DHCP",
                icon: <NodeIndexOutlined />,
              },
            },
            {
              name: "dhcp-leases",
              list: "/network/leases",
              meta: {
                parent: "network-group",
                label: "Leases DHCP",
                icon: <NodeIndexOutlined />,
              },
            },
            {
              name: "domains",
              list: "/content",
              create: "/content/new",
              meta: { label: "Filtro de Conteúdo", icon: <GlobalOutlined /> },
            },
            {
              name: "flows",
              list: "/flows",
              meta: { label: "Flows (NetFlow)", icon: <PartitionOutlined /> },
            },
            {
              name: "logs",
              list: "/logs",
              meta: { label: "Logs", icon: <FileTextOutlined /> },
            },
            {
              name: "services",
              list: "/system",
              meta: { label: "Sistema", icon: <CloudServerOutlined /> },
            },
          ]}
        >
          <Routes>
            <Route
              element={
                <ThemedLayoutV2
                  Title={Title}
                  Sider={(props) => <ThemedSiderV2 {...props} fixed />}
                >
                  <Outlet />
                </ThemedLayoutV2>
              }
            >
              <Route index element={<Overview />} />

              <Route path="/assistant" element={<AssistantPage />} />

              <Route path="/siem">
                <Route index element={<AlertList />} />
                <Route path=":id" element={<AlertShow />} />
              </Route>

              <Route path="/firewall">
                <Route path="blocklist" element={<BlocklistPage />} />
                <Route path="blocklist/new" element={<BlocklistPage />} />
                <Route path="ports" element={<PortRulesPage />} />
                <Route path="ports/new" element={<PortRulesPage />} />
                <Route path="ruleset" element={<RulesetPage />} />
              </Route>

              <Route path="/network">
                <Route path="zones" element={<ZoneList />} />
                <Route path="zones/new" element={<ZoneCreate />} />
                <Route path="zones/:id/edit" element={<ZoneEdit />} />
                <Route path="reservations" element={<ReservationsPage />} />
                <Route
                  path="reservations/new"
                  element={<ReservationsPage />}
                />
                <Route path="leases" element={<LeasesPage />} />
              </Route>

              <Route path="/content">
                <Route index element={<DomainsPage />} />
                <Route path="new" element={<DomainsPage />} />
              </Route>

              <Route path="/flows" element={<FlowsPage />} />
              <Route path="/logs" element={<LogsPage />} />
              <Route path="/system" element={<ServicesPage />} />

              <Route path="*" element={<ErrorComponent />} />
            </Route>
          </Routes>

          <UnsavedChangesNotifier />
          <DocumentTitleHandler />
        </Refine>
      </ConfigProvider>
    </BrowserRouter>
  );
}
