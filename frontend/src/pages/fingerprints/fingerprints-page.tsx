import {
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  PlusOutlined,
  ReloadOutlined,
  SyncOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Spin,
  Switch,
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
  createFingerprints,
  deleteFingerprint,
  fetchFingerprints,
  regenerateFingerprint,
  updateFingerprint,
} from "../../lib/api";
import { formatShanghaiTime } from "../../lib/time";
import type { BrowserFingerprint, FingerprintTarget } from "../../types";

const { Text } = Typography;
const cardStyle = { background: "#1f1f1f", borderColor: "#303030" };

const targetLabel: Record<string, string> = {
  pc: "PC 网页端",
  creator: "Creator 创作端",
};

type GenerateForm = {
  target: FingerprintTarget;
  count: number;
  name_prefix?: string;
  seed?: number | null;
  note?: string;
  validate_profile: boolean;
};

function validationTag(fingerprint: BrowserFingerprint) {
  const validation = fingerprint.validation;
  if (!validation) {
    return <Tag>未校验</Tag>;
  }
  if (validation.unavailable) {
    return <Tag color="gold">跳过校验</Tag>;
  }
  if (validation.b1 && validation.profileData) {
    return <Tag color="green">算法校验通过</Tag>;
  }
  return <Tag color="red">校验失败</Tag>;
}

export function FingerprintsPage() {
  const [items, setItems] = useState<BrowserFingerprint[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [targetFilter, setTargetFilter] = useState<"all" | FingerprintTarget>("all");
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<BrowserFingerprint | null>(null);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [renaming, setRenaming] = useState<BrowserFingerprint | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [regeneratingId, setRegeneratingId] = useState<number | null>(null);
  const [form] = Form.useForm<GenerateForm>();

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetchFingerprints(targetFilter === "all" ? undefined : targetFilter);
      setItems(response.items);
    } catch {
      setError("指纹列表加载失败。");
    } finally {
      setIsLoading(false);
    }
  }, [targetFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const counts = useMemo(() => {
    return {
      pc: items.filter((item) => item.target === "pc").length,
      creator: items.filter((item) => item.target === "creator").length,
      bound: items.filter((item) => item.account_count > 0).length,
    };
  }, [items]);

  const handleGenerate = async () => {
    try {
      const values = await form.validateFields();
      setGenerating(true);
      const result = await createFingerprints({
        target: values.target,
        count: values.count,
        name_prefix: values.name_prefix,
        seed: values.seed ?? undefined,
        note: values.note,
        validate_profile: values.validate_profile,
      });
      message.success(`已生成 ${result.total} 个指纹`);
      setGenerateOpen(false);
      form.resetFields();
      await load();
    } catch (err) {
      if (err && typeof err === "object" && "errorFields" in err) {
        return;
      }
      message.error("指纹生成失败，请检查 Node 运行时与参数。");
    } finally {
      setGenerating(false);
    }
  };

  const handleRegenerate = async (record: BrowserFingerprint) => {
    setRegeneratingId(record.id);
    try {
      await regenerateFingerprint(record.id, { target: record.target, validate_profile: true });
      message.success("指纹已重新生成");
      await load();
    } catch {
      message.error("重新生成失败");
    } finally {
      setRegeneratingId(null);
    }
  };

  const handleRename = async () => {
    if (!renaming) {
      return;
    }
    try {
      await updateFingerprint(renaming.id, { name: renameValue.trim() || renaming.name });
      message.success("已更新指纹名称");
      setRenaming(null);
      await load();
    } catch {
      message.error("重命名失败");
    }
  };

  const handleDelete = async (record: BrowserFingerprint) => {
    try {
      await deleteFingerprint(record.id);
      message.success("指纹已删除，相关账号已解绑");
      if (detail?.id === record.id) {
        setDetail(null);
      }
      await load();
    } catch {
      message.error("删除失败");
    }
  };

  const columns: ColumnsType<BrowserFingerprint> = [
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
      render: (value: string, record) => (
        <Space direction="vertical" size={0}>
          <Text strong style={{ color: "rgba(255,255,255,0.88)" }}>
            {value || `指纹 #${record.id}`}
          </Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            seed {record.seed}
          </Text>
        </Space>
      ),
    },
    {
      title: "目标端",
      dataIndex: "target",
      key: "target",
      width: 120,
      render: (value: FingerprintTarget) => (
        <Tag color={value === "creator" ? "purple" : "blue"}>{targetLabel[value] || value}</Tag>
      ),
    },
    {
      title: "设备画像",
      key: "summary",
      render: (_, record) => {
        const summary = record.summary || {};
        return (
          <Space direction="vertical" size={0}>
            <Text style={{ fontSize: 13 }}>
              {summary.browser || "Chrome"} {summary.browserVersion || ""} · {summary.os || "-"}
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {summary.screen || "-"} · {summary.timezone || "-"} · {summary.hardwareConcurrency ?? "-"} 线程
            </Text>
          </Space>
        );
      },
    },
    {
      title: "算法校验",
      key: "validation",
      width: 130,
      render: (_, record) => validationTag(record),
    },
    {
      title: "绑定账号",
      dataIndex: "account_count",
      key: "account_count",
      width: 100,
      render: (value: number) => (value > 0 ? <Tag color="green">{value} 个</Tag> : <Text type="secondary">未绑定</Text>),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 170,
      render: (value: string) => <Text type="secondary">{formatShanghaiTime(value)}</Text>,
    },
    {
      title: "操作",
      key: "actions",
      width: 240,
      render: (_, record) => (
        <Space size={4}>
          <Tooltip title="查看详情">
            <Button size="small" icon={<EyeOutlined />} onClick={() => setDetail(record)} />
          </Tooltip>
          <Tooltip title="重命名">
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => {
                setRenaming(record);
                setRenameValue(record.name);
              }}
            />
          </Tooltip>
          <Tooltip title="重新生成">
            <Button
              size="small"
              icon={regeneratingId === record.id ? <SyncOutlined spin /> : <ThunderboltOutlined />}
              disabled={regeneratingId === record.id}
              onClick={() => void handleRegenerate(record)}
            />
          </Tooltip>
          <Popconfirm
            title="删除指纹"
            description="绑定该指纹的账号会自动解绑，确认删除？"
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
        eyebrow="Browser Fingerprints"
        title="指纹工坊"
        description="为每个账号生成独立、可复现的浏览器指纹。指纹会注入现有签名器的 release / b1 / webprofile 输入，无需修改签名算法。"
        action={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={isLoading}>
              刷新
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => {
                form.setFieldsValue({ target: "pc", count: 1, validate_profile: true });
                setGenerateOpen(true);
              }}
            >
              生成指纹
            </Button>
          </Space>
        }
      />

      <Space size={12} style={{ marginBottom: 16 }}>
        <Tag color="blue">PC {counts.pc}</Tag>
        <Tag color="purple">Creator {counts.creator}</Tag>
        <Tag color="green">已绑定 {counts.bound}</Tag>
      </Space>

      <Card
        title={<span style={{ fontWeight: 600 }}>指纹列表</span>}
        extra={
          <Segmented
            value={targetFilter}
            onChange={(value) => setTargetFilter(value as "all" | FingerprintTarget)}
            options={[
              { label: "全部", value: "all" },
              { label: "PC", value: "pc" },
              { label: "Creator", value: "creator" },
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
          <Empty description="还没有生成指纹。生成后可在「账号矩阵」中按账号绑定。">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setGenerateOpen(true)}>
              生成第一批指纹
            </Button>
          </Empty>
        ) : (
          <Table<BrowserFingerprint>
            rowKey="id"
            columns={columns}
            dataSource={items}
            pagination={{ pageSize: 20, showSizeChanger: false }}
          />
        )}
      </Card>

      <Modal
        title="生成浏览器指纹"
        open={generateOpen}
        onCancel={() => setGenerateOpen(false)}
        onOk={() => void handleGenerate()}
        okText="开始生成"
        cancelText="取消"
        confirmLoading={generating}
        destroyOnHidden
      >
        <Form<GenerateForm> form={form} layout="vertical" initialValues={{ target: "pc", count: 1, validate_profile: true }}>
          <Form.Item name="target" label="目标端" rules={[{ required: true }]}>
            <Select
              options={[
                { label: "PC 网页端（搜索 / 抓取 / 健康检查）", value: "pc" },
                { label: "Creator 创作端（发布 / 上传）", value: "creator" },
              ]}
            />
          </Form.Item>
          <Form.Item name="count" label="生成数量" rules={[{ required: true }]}>
            <InputNumber min={1} max={50} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="name_prefix" label="名称前缀（可选）" extra="留空则自动命名为「PC 指纹 01 · xxxxx」。">
            <Input placeholder="例如：矩阵号-" maxLength={64} />
          </Form.Item>
          <Form.Item name="seed" label="固定种子（可选）" extra="相同种子会生成完全相同的指纹，便于复现。">
            <InputNumber min={0} max={2147483647} style={{ width: "100%" }} placeholder="留空则随机" />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} maxLength={500} placeholder="例如：上海电信 家宽 / 指向代理 A 组" />
          </Form.Item>
          <Form.Item
            name="validate_profile"
            label="生成后调用本地 Node 算法做一次校验"
            valuePropName="checked"
            extra="需要项目已安装 Node 依赖（crypto-js）。校验失败不会阻断生成。"
          >
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="重命名指纹"
        open={renaming !== null}
        onCancel={() => setRenaming(null)}
        onOk={() => void handleRename()}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Input value={renameValue} onChange={(event) => setRenameValue(event.target.value)} maxLength={128} />
      </Modal>

      <Drawer
        title={detail ? detail.name || `指纹 #${detail.id}` : "指纹详情"}
        open={detail !== null}
        onClose={() => setDetail(null)}
        width={720}
      >
        {detail ? (
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="目标端">{targetLabel[detail.target] || detail.target}</Descriptions.Item>
              <Descriptions.Item label="种子">{detail.seed}</Descriptions.Item>
              <Descriptions.Item label="浏览器">
                {detail.summary?.browser} {detail.summary?.browserVersion}
              </Descriptions.Item>
              <Descriptions.Item label="系统">{detail.summary?.os || "-"}</Descriptions.Item>
              <Descriptions.Item label="分辨率">{detail.summary?.screen || "-"}</Descriptions.Item>
              <Descriptions.Item label="缩放">{detail.summary?.deviceScaleFactor ?? "-"}</Descriptions.Item>
              <Descriptions.Item label="时区">{detail.summary?.timezone || "-"}</Descriptions.Item>
              <Descriptions.Item label="语言">{detail.summary?.locale || "-"}</Descriptions.Item>
              <Descriptions.Item label="CPU 线程">{detail.summary?.hardwareConcurrency ?? "-"}</Descriptions.Item>
              <Descriptions.Item label="内存">{detail.summary?.deviceMemory ?? "-"} GB</Descriptions.Item>
              <Descriptions.Item label="算法校验" span={2}>
                {validationTag(detail)}
                {detail.validation?.errors?.length ? (
                  <Text type="danger" style={{ display: "block", fontSize: 12, marginTop: 4 }}>
                    {detail.validation.errors.join("; ").slice(0, 500)}
                  </Text>
                ) : null}
              </Descriptions.Item>
            </Descriptions>

            <div>
              <Text strong>完整 Profile JSON</Text>
              <pre
                style={{
                  marginTop: 8,
                  maxHeight: 420,
                  overflow: "auto",
                  background: "#141414",
                  border: "1px solid #303030",
                  borderRadius: 8,
                  padding: 12,
                  fontSize: 12,
                  lineHeight: 1.6,
                }}
              >
                {JSON.stringify(detail.profile, null, 2)}
              </pre>
            </div>
          </Space>
        ) : null}
      </Drawer>
    </div>
  );
}
