import { useCustom } from "@refinedev/core";
import { Card, Collapse, Tag, Spin, Typography, Empty } from "antd";

const { Text } = Typography;

export const RulesetPage = () => {
  const { data, isLoading } = useCustom<any>({
    url: "/api/firewall/ruleset",
    method: "get",
  });

  if (isLoading) {
    return (
      <div style={{ textAlign: "center", padding: 80 }}>
        <Spin size="large" />
      </div>
    );
  }

  const tables = data?.data?.tables ?? [];

  return (
    <div>
      <Typography.Title level={3} style={{ marginTop: 0 }}>
        Firewall — Ruleset (nftables)
      </Typography.Title>
      {tables.length === 0 && <Empty description="Nenhuma tabela" />}
      {tables.map((t: any) => (
        <Card
          key={`${t.family}-${t.name}`}
          title={
            <span>
              <Tag color="blue">{t.family}</Tag>
              <Text strong>{t.name}</Text>
            </span>
          }
          style={{ marginBottom: 16 }}
          bordered={false}
        >
          <Collapse
            items={(t.chains ?? []).map((c: any, i: number) => ({
              key: i,
              label: (
                <span>
                  <Text strong>{c.name}</Text>{" "}
                  <Tag>{c.type || c.hook || "regular"}</Tag>
                  <Text type="secondary">
                    {(c.rules ?? []).length} regra(s)
                  </Text>
                </span>
              ),
              children: (
                <div>
                  {(c.rules ?? []).map((r: any, j: number) => (
                    <div
                      key={j}
                      className="mx-mono"
                      style={{
                        padding: "4px 8px",
                        borderBottom: "1px solid #1f2a44",
                      }}
                    >
                      <Tag color="default">#{r.handle}</Tag> {r.expr}
                    </div>
                  ))}
                </div>
              ),
            }))}
          />
        </Card>
      ))}
    </div>
  );
};
