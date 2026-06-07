import { SafetyCertificateFilled } from "@ant-design/icons";

export const Brand = ({ collapsed }: { collapsed: boolean }) => (
  <div className="mx-brand">
    <span className="mx-brand-logo">
      <SafetyCertificateFilled />
    </span>
    {!collapsed && (
      <span>
        MUNDIX <span className="mx-360">360</span>
      </span>
    )}
  </div>
);
