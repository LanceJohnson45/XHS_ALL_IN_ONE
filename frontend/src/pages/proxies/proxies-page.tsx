import {
  ApiOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  EditOutlined,
  GlobalOutlined,
  PlusOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useState } from "react";

import { PageHeader } from "../../components/layout/app-shell";
import {
  bulkImportProxies,
  createProxy,
  deleteProxy,
  fetchProxies,
  testAllProxies,
  testProxy,
  updateProxy,
} from "../../lib/api";
import { formatShanghaiTime } from "../../lib/time";
import type { ProxyEndpoint } from "../../types";

const { Text } = Typography;
const cardStyle = { background: "#1f1f1f", borderColor: "#303030" };

const protocolOptions = [
  { label: "HTTP", value: "http" },
  { label: "HTTPS", value: "https" },
  { label: "SOCKS4", value: "socks4" },
  { label: "SOCKS5", value: "socks5" },
  { label: "SOCKS5H", value: "socks5h" },
];

const statusMeta: Record<string, { color: string; label: string }> = {
  unknown: { color: "default", label: "未检测" },
  healthy: { color: "green", label: "可用" },
  unhealthy: { color: "red", label: "不可用" },
  disabled: { color: "orange", label: "已停用" },
};

type ProxyForm = {
  name?: string;
  protocol: string;
  host: string;
  port: number;
  username?: string;
  password?: string;
  note?: string;
};

export function ProxiesPage() {
  const [items, setItems] = useState<ProxyEndpoint[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<"all" | string>("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [editing, setEditing] = useState<ProxyEndpoint | null>(null);
  const [saving, setSaving] = useState(false);
  const [testingIds, setTestingIds] = useState<Set<number>>(() => new Set());
  const [testingAll, setTestingAll] = useState(false);
  const [importText, setImportText] = useState("");
  const [importProtocol, setImportProtocol] = useState("http");
  const [importPrefix, setImportPrefix] = useState("");
  const [importErrors, setImportErrors] = useState<{ line: number; value: string; error: string }[]>([]);
  const [form] = Form.useForm<ProxyForm>();

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetchProxies(statusFilter === "all" ? undefined : statusFilter);
      setItems(response.items);
    } catch {
      setError("代理列表加载失败。");
    } finally {
      setIsLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const stats = useMemo(() => {
    const healthy = items.filter((item) => item.status === "healthy").length;
    const unhealthy = items.filter((item) => item.status === "unhealthy").length;
    const bound = items.filter((item) => item.account_count > 0).length;
    return { total: items.length, healthy, unhealthy, bound };
  }, [items]);

  const openCreate = () => {
    form.setFieldsValue({ protocol: "http", host: "", port: 8080, username: "", password: "", name: "", note: "" });
    setCreateOpen(true);
  };

  const openEdit = (record: ProxyEndpoint) => {
    form.setFieldsValue({
      name: record.name,
      protocol: record.protocol,
      host: record.host,
      port: record.port,
      username: record.username,
      password: "",
      note: record.note,
    });
    setEditing(record);
  };

  const submitForm = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      if (editing) {
        await updateProxy(editing.id, {
          name: values.name,
          protocol: values.protocol,
          host: values.host,
          port: values.port,
          username: values.username,
          password: values.password ? values.password : undefined,
          note: values.note,
        });
        message.success("代理已更新");
        setEditing(null);
      } else {
        await createProxy({
          name: values.name,
          protocol: values.protocol,
          host: values.host,
          port: values.port,
          username: values.username,
          password: values.password,
          note: values.note,
        });
        message.success("代理已添加");
        setCreateOpen(false);
      }
      form.resetFields();
      await load();
    } catch (err) {
      if (err && typeof err === "object" && "errorFields" in err) {
        return;
      }
      message.error("保存代理失败");
    } finally {
      setSaving(false);
    }
  };

  const submitImport = async () => {
    if (!importText.trim()) {
      message.warning("请先粘贴代理列表");
      return;
    }
    setSaving(true);
    try {
      const result = await bulkImportProxies({
        text: importText,
        default_protocol: importProtocol,
        name_prefix: importPrefix,
      });
      setImportErrors(result.errors);
      message.success(`成功导入 ${result.created_count} 条代理`);
      setImportText("");
      await load();
    } catch {
      message.error("批量导入失败");
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async (record: ProxyEndpoint) => {
    if (testingIds.has(record.id)) {
      return;
    }
    setTestingIds((current) => new Set(current).add(record.id));
    try {
      const result = await testProxy(record.id);
      if (result.result.ok) {
        message.success(`${record.name} 可用，出口 IP ${result.result.exit_ip}（${result.result.latency_ms ?? "-"}ms）`);
      } else {
        message.error(`${record.name} 不可用：${result.result.message}`);
      }
      await load();
    } catch {
      message.error("代理检测失败");
    } finally {
      setTestingIds((current) => {
        const next = new Set(current);
        next.delete(record.id);
        return next;
      });
    }
  };

  const handleTestAll = async () => {
    setTestingAll(true);
    try {
      const result = await testAllProxies(50);
      message.success(`检测完成：${result.healthy}/${result.total} 条可用`);
      await load();
    } catch {
      message.error("批量检测失败");
    } finally {
      setTestingAll(false);
    }
  };

  const handleToggle = async (record: ProxyEndpoint) => {
    try {
      await updateProxy(record.id, { status: record.status === "disabled" ? "unknown" : "disabled" });
      await load();
    } catch {
      message.error("状态更新失败");
    }
  };

  const handleDelete = async (record: ProxyEndpoint) => {
    try {
      await deleteProxy(record.id);
      message.success("代理已删除，相关账号已解绑");
      await load();
    } catch {
      message.error("删除失败");
    }
  };

  const columns: ColumnsType<ProxyEndpoint> = [
    {
      title: "名称 / 地址",
      key: "address",
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text strong style={{ color: "rgba(255,255,255,0.88)" }}>
            {record.name || record.address}
          </Text>
          <Text type="secondary" style={{ fontSize: 12, fontFamily: "monospace" }}>
            {record.url_masked}
          </Text>
        </Space>
      ),
    },
    {
      title: "协议",
      dataIndex: "protocol",
      key: "protocol",
      width: 90,
      render: (value: string) => <Tag>{value.toUpperCase()}</Tag>,
    },
    {
      title: "状态",
      key: "status",
      width: 110,
      render: (_, record) => {
        const meta = statusMeta[record.status] || statusMeta.unknown;
        return (
          <Tooltip title={record.status_message || meta.label}>
            <Tag color={meta.color}>{meta.label}</Tag>
          </Tooltip>
        );
      },
    },
    {
      title: "出口 IP",
      key: "exit",
      width: 200,
      render: (_, record) =>
        record.exit_ip ? (
          <Space direction="vertical" size={0}>
            <Text style={{ fontFamily: "monospace" }}>{record.exit_ip}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {[record.exit_country, record.exit_region].filter(Boolean).join(" · ") || "-"}
            </Text>
          </Space>
        ) : (
          <Text type="secondary">未检测</Text>
        ),
    },
    {
      title: "延迟",
      dataIndex: "latency_ms",
      key: "latency_ms",
      width: 90,
      render: (value?: number | null) => (value ? `${value} ms` : "-"),
    },
    {
      title: "绑定账号",
      dataIndex: "account_count",
      key: "account_count",
      width: 100,
      render: (value: number) => (value > 0 ? <Tag color="green">{value} 个</Tag> : <Text type="secondary">未绑定</Text>),
    },
    {
      title: "最后检测",
      dataIndex: "last_checked_at",
      key: "last_checked_at",
      width: 170,
      render: (value?: string | null) => <Text type="secondary">{formatShanghaiTime(value)}</Text>,
    },
    {
      title: "操作",
      key: "actions",
      width: 260,
      render: (_, record) => (
        <Space size={4}>
          <Tooltip title="检测连通性">
            <Button
              size="small"
              icon={<ThunderboltOutlined spin={testingIds.has(record.id)} />}
              disabled={testingIds.has(record.id)}
              onClick={() => void handleTest(record)}
            />
          </Tooltip>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          <Button size="small" onClick={() => void handleToggle(record)}>
            {record.status === "disabled" ? "启用" : "停用"}
          </Button>
          <Popconfirm
            title="删除代理"
            description="绑定该代理的账号会自动回退为直连，确认删除？"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => void handleDelete(record)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: "0 0 32px" }}>
      <PageHeader
        eyebrow="Proxy Pool"
        title="代理管理"
        description="管理你逐条购买的静态 IP。支持批量粘贴导入、连通性检测，并可在账号矩阵中为每个账号绑定一条独立出口。"
        action={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={isLoading}>
              刷新
            </Button>
            <Button icon={<ApiOutlined />} onClick={() => void handleTestAll()} loading={testingAll}>
              全部检测
            </Button>
            <Button icon={<CloudUploadOutlined />} onClick={() => setImportOpen(true)}>
              批量导入
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              新增代理
            </Button>
          </Space>
        }
      />

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}>
          <Card size="small" style={cardStyle}>
            <Statistic title="代理总数" value={stats.total} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" style={cardStyle}>
            <Statistic title="可用" value={stats.healthy} valueStyle={{ color: "#52c41a" }} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" style={cardStyle}>
            <Statistic title="不可用" value={stats.unhealthy} valueStyle={{ color: "#ff4d4f" }} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" style={cardStyle}>
            <Statistic title="已绑定账号" value={stats.bound} />
          </Card>
        </Col>
      </Row>

      <Card
        title={<span style={{ fontWeight: 600 }}>代理列表</span>}
        extra={
          <Segmented
            value={statusFilter}
            onChange={(value) => setStatusFilter(String(value))}
            options={[
              { label: "全部", value: "all" },
              { label: "可用", value: "healthy" },
              { label: "不可用", value: "unhealthy" },
              { label: "未检测", value: "unknown" },
              { label: "已停用", value: "disabled" },
            ]}
          />
        }
        style={cardStyle}
        styles={{ body: { padding: 24 } }}
      >
        {error ? <Alert type="error" message={error} showIcon style={{ marginBottom: 16 }} /> : null}
        {isLoading ? (
          <div style={{ textAlign: "center", padding: "48px 0" }}>
            <Spin size="large" />
          </div>
        ) : items.length === 0 ? (
          <Empty
            image={<GlobalOutlined style={{ fontSize: 48, color: "rgba(255,255,255,0.25)" }} />}
            description="还没有代理。把你购买的 IP 一行一条粘贴进来即可批量导入。"
          >
            <Space>
              <Button type="primary" icon={<CloudUploadOutlined />} onClick={() => setImportOpen(true)}>
                批量导入
              </Button>
              <Button icon={<PlusOutlined />} onClick={openCreate}>
                手动新增
              </Button>
            </Space>
          </Empty>
        ) : (
          <Table<ProxyEndpoint>
            rowKey="id"
            columns={columns}
            dataSource={items}
            pagination={{ pageSize: 20, showSizeChanger: false }}
          />
        )}
      </Card>

      <Modal
        title={editing ? "编辑代理" : "新增代理"}
        open={createOpen || editing !== null}
        onCancel={() => {
          setCreateOpen(false);
          setEditing(null);
        }}
        onOk={() => void submitForm()}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        destroyOnHidden
      >
        <Form<ProxyForm> form={form} layout="vertical">
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="protocol" label="协议" rules={[{ required: true }]}>
                <Select options={protocolOptions} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="name" label="名称（可选）">
                <Input placeholder="例如：上海-家宽-01" maxLength={128} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={16}>
              <Form.Item name="host" label="主机 / IP" rules={[{ required: true }]}>
                <Input placeholder="1.2.3.4 或 proxy.example.com" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="port" label="端口" rules={[{ required: true }]}>
                <InputNumber min={1} max={65535} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="username" label="用户名（可选）">
                <Input autoComplete="off" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="password" label={editing ? "密码（留空保持不变）" : "密码（可选）"}>
                <Input.Password autoComplete="new-password" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} maxLength={500} placeholder="例如：A 组账号专用 / 到期 2026-12" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="批量导入代理"
        open={importOpen}
        onCancel={() => setImportOpen(false)}
        onOk={() => void submitImport()}
        okText="开始导入"
        cancelText="关闭"
        confirmLoading={saving}
        width={680}
        destroyOnHidden
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            message="支持一行一条，自动识别常见格式"
            description={
              <Text type="secondary" style={{ fontSize: 12 }}>
                http://user:pass@1.2.3.4:8080 · socks5://user:pass@host:1080 · 1.2.3.4:8080 · 1.2.3.4:8080:user:pass ·
                user:pass@1.2.3.4:8080
              </Text>
            }
          />
          <Space>
            <Select style={{ width: 140 }} value={importProtocol} onChange={setImportProtocol} options={protocolOptions} />
            <Input
              style={{ width: 260 }}
              placeholder="名称前缀（可选，如 A组-）"
              value={importPrefix}
              onChange={(event) => setImportPrefix(event.target.value)}
            />
          </Space>
          <Input.TextArea
            rows={10}
            value={importText}
            onChange={(event) => setImportText(event.target.value)}
            placeholder={"http://user:pass@1.2.3.4:8080\n1.2.3.5:8080:user:pass\nsocks5://1.2.3.6:1080"}
          />
          {importErrors.length > 0 ? (
            <Alert
              type="warning"
              showIcon
              message={`${importErrors.length} 行未导入`}
              description={
                <div style={{ maxHeight: 120, overflowY: "auto", fontSize: 12 }}>
                  {importErrors.slice(0, 20).map((item) => (
                    <div key={`${item.line}-${item.value}`}>
                      第 {item.line} 行：{item.value.slice(0, 80)} — {item.error}
                    </div>
                  ))}
                </div>
              }
            />
          ) : null}
          <Descriptions column={1} size="small">
            <Descriptions.Item label="说明">
              密码会使用与 Cookie 相同的 Fernet 密钥加密存储，接口不会回显明文。
            </Descriptions.Item>
          </Descriptions>
        </Space>
      </Modal>
    </div>
  );
}
