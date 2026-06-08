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
  DeploymentUnitOutlined,
  PartitionOutlined,
  TagOutlined,
  NodeIndexOutlined,
  FileTextOutlined,
  CloudServerOutlined,
  RobotOutlined,
  FilterOutlined,
  SwapOutlined,
  TagsOutlined,
  SaveOutlined,
  ApartmentOutlined,
} from "@ant-design/icons";
import "@refinedev/antd/dist/reset.css";

import { dataProvider } from "./dataProvider";
import { Brand } from "./components/Brand";
import { Header } from "./components/Header";
import { Overview } from "./pages/overview";
import { AlertList, AlertShow } from "./pages/alerts";
import { FirewallOverview } from "./pages/firewall/overview";
import { BlocklistPage } from "./pages/firewall/blocklist";
import { RulesPage } from "./pages/firewall/rules";
import { NatPage } from "./pages/firewall/nat";
import { AliasesPage } from "./pages/firewall/aliases";
import { ZonesMatrixPage } from "./pages/firewall/zones-matrix";
import { RulesetPage } from "./pages/firewall/ruleset";
import { ZoneList, ZoneCreate, ZoneEdit } from "./pages/network/zones";
import { InterfacesPage } from "./pages/network/interfaces";
import { VlansPage } from "./pages/network/vlans";
import { MultiWanPage } from "./pages/network/multiwan";
import { ReservationsPage } from "./pages/network/reservations";
import { LeasesPage } from "./pages/network/leases";
import { DnsPage } from "./pages/network/dns";
import { DomainsPage } from "./pages/content/domains";
import { ContentFilterPage } from "./pages/content/filter";
import { ThreatIntelPage } from "./pages/threatintel";
import { WafPage } from "./pages/waf";
import { BackupPage } from "./pages/backup";
import { FlowsPage } from "./pages/flows";
import { LogsPage } from "./pages/logs";
import { ServicesPage } from "./pages/system/services";
import { AiConfigPage } from "./pages/ai-config";
import { AssistantDock } from "./components/AssistantDock";
import { SiderResizer } from "./components/SiderResizer";
import { RevertBanner } from "./components/RevertBanner";

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
            colorPrimary: "#2f81f7",
            colorInfo: "#2f81f7",
            colorBgLayout: "#060b16",
            colorBgContainer: "#0e1626",
            colorBgElevated: "#131f34",
            colorBorder: "#1b2942",
            colorBorderSecondary: "#15223a",
            colorText: "#e6edf6",
            colorTextSecondary: "#93a4c0",
            fontFamily:
              "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            fontSize: 14,
            borderRadius: 10,
            controlHeight: 36,
            wireframe: false,
          },
          components: {
            Menu: {
              darkItemBg: "transparent",
              darkSubMenuItemBg: "transparent",
              darkItemSelectedBg: "transparent",
            },
            Card: { colorBgContainer: "#0e1626" },
            Table: { headerBg: "#0d1525", rowHoverBg: "rgba(47,129,247,0.06)" },
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
              name: "firewall-overview",
              list: "/firewall",
              meta: {
                parent: "firewall-group",
                label: "Visão geral",
                icon: <DashboardOutlined />,
              },
            },
            {
              name: "rules",
              list: "/firewall/rules",
              meta: {
                parent: "firewall-group",
                label: "Regras de Filtro",
                icon: <FilterOutlined />,
              },
            },
            {
              name: "zones-matrix",
              list: "/firewall/zones",
              meta: {
                parent: "firewall-group",
                label: "Matriz de Zonas",
                icon: <ApartmentOutlined />,
              },
            },
            {
              name: "nat",
              list: "/firewall/nat",
              meta: {
                parent: "firewall-group",
                label: "NAT",
                icon: <SwapOutlined />,
              },
            },
            {
              name: "aliases",
              list: "/firewall/aliases",
              meta: {
                parent: "firewall-group",
                label: "Aliases",
                icon: <TagsOutlined />,
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
              name: "ruleset",
              list: "/firewall/ruleset",
              meta: {
                parent: "firewall-group",
                label: "Ruleset (nft)",
                icon: <PartitionOutlined />,
              },
            },
            {
              name: "threatintel",
              list: "/firewall/threats",
              meta: {
                parent: "firewall-group",
                label: "Threat Intelligence",
                icon: <SafetyCertificateOutlined />,
              },
            },
            {
              name: "waf",
              list: "/firewall/waf",
              meta: {
                parent: "firewall-group",
                label: "WAF",
                icon: <SafetyCertificateOutlined />,
              },
            },
            {
              name: "network-group",
              meta: { label: "Rede", icon: <ClusterOutlined /> },
            },
            {
              name: "interfaces",
              list: "/network/interfaces",
              meta: {
                parent: "network-group",
                label: "Interfaces",
                icon: <ApiOutlined />,
              },
            },
            {
              name: "vlans",
              list: "/network/vlans",
              meta: {
                parent: "network-group",
                label: "VLANs",
                icon: <TagOutlined />,
              },
            },
            {
              name: "multiwan",
              list: "/network/multiwan",
              meta: {
                parent: "network-group",
                label: "Multi-WAN",
                icon: <DeploymentUnitOutlined />,
              },
            },
            {
              name: "zones",
              list: "/network/zones",
              create: "/network/zones/new",
              edit: "/network/zones/:id/edit",
              meta: {
                parent: "network-group",
                label: "Zonas / Sub-redes",
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
              name: "dns",
              list: "/network/dns",
              meta: {
                parent: "network-group",
                label: "DNS",
                icon: <GlobalOutlined />,
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
            {
              name: "backup",
              list: "/system/backup",
              meta: { label: "Backup & Restauração", icon: <SaveOutlined /> },
            },
          ]}
        >
          <Routes>
            <Route
              element={
                <ThemedLayoutV2
                  Title={Title}
                  Header={Header}
                  Sider={(props) => <ThemedSiderV2 {...props} fixed />}
                >
                  <Outlet />
                  <SiderResizer />
                  <AssistantDock />
                  <RevertBanner />
                </ThemedLayoutV2>
              }
            >
              <Route index element={<Overview />} />

              <Route path="/assistant" element={<AiConfigPage />} />

              <Route path="/siem">
                <Route index element={<AlertList />} />
                <Route path=":id" element={<AlertShow />} />
              </Route>

              <Route path="/firewall">
                <Route index element={<FirewallOverview />} />
                <Route path="rules" element={<RulesPage />} />
                <Route path="zones" element={<ZonesMatrixPage />} />
                <Route path="nat" element={<NatPage />} />
                <Route path="aliases" element={<AliasesPage />} />
                <Route path="blocklist" element={<BlocklistPage />} />
                <Route path="blocklist/new" element={<BlocklistPage />} />
                <Route path="ruleset" element={<RulesetPage />} />
                <Route path="threats" element={<ThreatIntelPage />} />
                <Route path="waf" element={<WafPage />} />
              </Route>

              <Route path="/network">
                <Route path="interfaces" element={<InterfacesPage />} />
                <Route path="vlans" element={<VlansPage />} />
                <Route path="multiwan" element={<MultiWanPage />} />
                <Route path="zones" element={<ZoneList />} />
                <Route path="zones/new" element={<ZoneCreate />} />
                <Route path="zones/:id/edit" element={<ZoneEdit />} />
                <Route path="reservations" element={<ReservationsPage />} />
                <Route
                  path="reservations/new"
                  element={<ReservationsPage />}
                />
                <Route path="leases" element={<LeasesPage />} />
                <Route path="dns" element={<DnsPage />} />
              </Route>

              <Route path="/content">
                <Route index element={<ContentFilterPage />} />
                <Route path="manual" element={<DomainsPage />} />
                <Route path="new" element={<DomainsPage />} />
              </Route>

              <Route path="/flows" element={<FlowsPage />} />
              <Route path="/logs" element={<LogsPage />} />
              <Route path="/system" element={<ServicesPage />} />
              <Route path="/system/backup" element={<BackupPage />} />

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
