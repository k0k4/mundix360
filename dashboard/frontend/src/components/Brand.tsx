import { SafetyCertificateFilled } from "@ant-design/icons";

export const Brand = ({ collapsed }: { collapsed: boolean }) => (
  <div className="mx-brand">
    <SafetyCertificateFilled style={{ color: "#1668dc", fontSize: 22 }} />
    {!collapsed && (
      <span>
        MUNDIX <span style={{ color: "#1668dc" }}>360</span>
      </span>
    )}
  </div>
);
