/**
 * AIConfigCard — AI 供应商设置卡片
 * 挂载在 /users 页面，per-user 配置 AI provider/model/key/base_url。
 */
import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Eye, EyeOff, CheckCircle2, XCircle } from "lucide-react";
import { apiGet, apiPost } from "../api/client";
import { queryKeys } from "../queries/queryClient";
import type {
  AIModelsResponse,
  AIConfigRequest,
  AIConfigResponse,
  AITestRequest,
  AITestResponse,
} from "../api/types";

// Design language tokens (Tailwind)
const inputCls =
  "w-full px-3 py-2 border border-border-default rounded-button text-sm " +
  "bg-surface-card text-text-primary placeholder-text-muted " +
  "focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/20";

const btnPrimary =
  "bg-accent text-white px-4 py-2 rounded-button text-sm font-medium " +
  "hover:bg-accent-hover transition-colors disabled:opacity-50";

const btnSecondary =
  "bg-accent-soft text-accent-hover px-4 py-2 rounded-button text-sm font-medium " +
  "hover:bg-accent/20 transition-colors disabled:opacity-50";

const cardCls =
  "bg-surface-card rounded-card border border-border-default shadow-card p-5";

interface Props {
  username: string;
  currentProvider?: string;
}

export default function AIConfigCard({ username, currentProvider }: Props) {
  const queryClient = useQueryClient();

  // Form state
  const [provider, setProvider] = useState(currentProvider || "");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [showKey, setShowKey] = useState(false);

  // Test result
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string; latency?: number } | null>(null);

  // Fetch provider presets
  const { data: modelsResponse } = useQuery({
    queryKey: ["ai-models", username],
    queryFn: () => apiGet<AIModelsResponse>(`/api/users/${username}/ai-models`),
  });

  const modelsData = modelsResponse?.data;
  const providers = modelsData?.providers || [];
  const selectedProvider = providers.find((p) => p.id === provider);
  const availableModels = selectedProvider?.models || [];

  // When provider changes, suggest first model; only auto-fill base_url for providers that require it
  useEffect(() => {
    if (selectedProvider) {
      if (selectedProvider.needs_base_url && selectedProvider.default_base_url) {
        setBaseUrl(selectedProvider.default_base_url);
      }
      if (selectedProvider.models.length > 0) {
        setModel(selectedProvider.models[0]);
      }
    } else {
      setModel("");
      setBaseUrl("");
    }
  }, [provider]);

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: (req: AIConfigRequest) =>
      apiPost<AIConfigResponse>(`/api/users/${username}/ai-config`, req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.users() });
      setTestResult(null);
    },
  });

  // Test mutation
  const testMutation = useMutation({
    mutationFn: (req: AITestRequest) =>
      apiPost<AITestResponse>(`/api/users/${username}/ai-test`, req),
    onSuccess: (response) => {
      const data = response.data;
      setTestResult({
        ok: data?.ok ?? false,
        message: data?.message ?? "未知结果",
        latency: data?.latency_ms,
      });
    },
    onError: (err: Error) => {
      setTestResult({ ok: false, message: err.message });
    },
  });

  const handleSave = () => {
    saveMutation.mutate({ provider, api_key: apiKey, model, base_url: baseUrl || undefined });
  };

  const handleTest = () => {
    setTestResult(null);
    testMutation.mutate({ provider, api_key: apiKey, model, base_url: baseUrl || undefined });
  };

  return (
    <div className={cardCls}>
      <h3 className="text-base font-medium text-text-primary mb-4">
        AI 供应商设置
      </h3>

      <div className="space-y-3">
        {/* Provider dropdown */}
        <div>
          <label className="block text-xs font-medium text-text-secondary mb-1">
            供应商
          </label>
          <select
            className={inputCls}
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
          >
            <option value="">选择供应商...</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {/* Model — combobox: 预设下拉 + 可自由输入 */}
        {provider && (
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1">
              模型
            </label>
            <input
              type="text"
              className={inputCls}
              list="ai-model-suggestions"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={availableModels[0] || "输入模型名称..."}
            />
            <datalist id="ai-model-suggestions">
              {availableModels.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
            <p className="text-xs text-text-muted mt-1">
              可从预设选择，也可输入自定义模型名
            </p>
          </div>
        )}

        {/* API Key */}
        {provider && (
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1">
              API Key
            </label>
            <div className="relative">
              <input
                type={showKey ? "text" : "password"}
                className={inputCls + " pr-10"}
                placeholder="sk-..."
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
                onClick={() => setShowKey(!showKey)}
              >
                {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>
        )}

        {/* Base URL — 所有供应商均可自定义（支持第三方代理/中转） */}
        {provider && (
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1">
              Base URL <span className="text-text-muted">(可选，支持第三方代理)</span>
            </label>
            <input
              type="text"
              className={inputCls}
              placeholder={selectedProvider?.default_base_url || "留空使用官方端点"}
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
            />
          </div>
        )}

        {/* Action buttons */}
        {provider && (
          <div className="flex gap-2 pt-2">
            <button
              className={btnPrimary}
              onClick={handleSave}
              disabled={saveMutation.isPending || !apiKey}
            >
              {saveMutation.isPending ? (
                <Loader2 size={14} className="animate-spin inline mr-1" />
              ) : null}
              保存
            </button>
            <button
              className={btnSecondary}
              onClick={handleTest}
              disabled={testMutation.isPending || !apiKey}
            >
              {testMutation.isPending ? (
                <Loader2 size={14} className="animate-spin inline mr-1" />
              ) : null}
              测试连接
            </button>
          </div>
        )}

        {/* Test result */}
        {testResult && (
          <div
            className={`flex items-center gap-2 text-sm mt-2 px-3 py-2 rounded-pill ${
              testResult.ok
                ? "bg-success-soft text-success"
                : "bg-error-soft text-error"
            }`}
          >
            {testResult.ok ? (
              <CheckCircle2 size={14} />
            ) : (
              <XCircle size={14} />
            )}
            <span>
              {testResult.message}
              {testResult.latency != null && ` (${Math.round(testResult.latency)}ms)`}
            </span>
          </div>
        )}

        {/* Save result */}
        {saveMutation.isSuccess && (
          <div className="flex items-center gap-2 text-sm mt-2 px-3 py-2 rounded-pill bg-success-soft text-success">
            <CheckCircle2 size={14} />
            <span>配置已保存</span>
          </div>
        )}
        {saveMutation.isError && (
          <div className="flex items-center gap-2 text-sm mt-2 px-3 py-2 rounded-pill bg-error-soft text-error">
            <XCircle size={14} />
            <span>保存失败: {saveMutation.error.message}</span>
          </div>
        )}
      </div>
    </div>
  );
}
