/**
 * ToolManagementPanel — 动态工具管理侧边栏面板。
 *
 * 侧边栏覆盖层，展示所有动态工具列表（名称、描述、持久化 Badge、启用状态）。
 * 支持展开查看完整代码（Monaco Editor 只读）、Switch 启用/禁用、内联删除二次确认。
 *
 * 满足 DYN-15, DYN-16, DYN-17, DYN-18, DYN-19, DYN-20, DYN-21 需求。
 */

import { useState, useEffect, useCallback } from "react";
import { Hammer, X, Trash2, Loader2 } from "lucide-react";
import Editor from "@monaco-editor/react";
import { useUIStore } from "@/stores/uiStore";
import {
  fetchTools,
  fetchToolDetail,
  disableTool,
  enableTool,
  deleteTool,
  type ToolSummary,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";

function ToolManagementPanel() {
  const setToolPanelOpen = useUIStore((s) => s.setToolPanelOpen);

  // ── Local state ──────────────────────────────────────────────────────────
  const [tools, setTools] = useState<ToolSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedTool, setExpandedTool] = useState<string | null>(null);
  const [toolCodeMap, setToolCodeMap] = useState<Record<string, string>>({});
  const [codeLoading, setCodeLoading] = useState<string | null>(null);
  const [deleteConfirming, setDeleteConfirming] = useState<string | null>(null);
  const [deleteMessage, setDeleteMessage] = useState<string | null>(null);
  const [toggleLoading, setToggleLoading] = useState<string | null>(null);

  // ── Fetch tool list on mount ─────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchTools()
      .then((data) => {
        if (!cancelled) {
          setTools(data);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : "Failed to load tools";
          setError(msg);
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // ── Close panel ──────────────────────────────────────────────────────────

  const closePanel = useCallback(() => {
    setToolPanelOpen(false);
  }, [setToolPanelOpen]);

  // ── Toggle expand / fetch detail ─────────────────────────────────────────

  const toggleExpand = useCallback(
    async (toolName: string) => {
      if (expandedTool === toolName) {
        setExpandedTool(null);
        return;
      }

      setExpandedTool(toolName);
      setDeleteConfirming(null);

      // Fetch detail if not already cached
      if (!toolCodeMap[toolName]) {
        setCodeLoading(toolName);
        try {
          const detail = await fetchToolDetail(toolName);
          setToolCodeMap((prev) => ({
            ...prev,
            [toolName]: detail.code,
          }));
        } catch {
          setToolCodeMap((prev) => ({
            ...prev,
            [toolName]: "// Failed to load code",
          }));
        } finally {
          setCodeLoading(null);
        }
      }
    },
    [expandedTool, toolCodeMap],
  );

  // ── Toggle enable/disable ────────────────────────────────────────────────

  const handleToggle = useCallback(
    async (toolName: string, checked: boolean) => {
      setToggleLoading(toolName);
      try {
        if (checked) {
          await enableTool(toolName);
        } else {
          await disableTool(toolName);
        }
        // Refetch tool list to get updated state
        const data = await fetchTools();
        setTools(data);
      } catch {
        // Revert optimistic update by refetching
        const data = await fetchTools();
        setTools(data);
      } finally {
        setToggleLoading(null);
      }
    },
    [],
  );

  // ── Delete tool with confirmation ───────────────────────────────────────

  const handleDelete = useCallback(
    async (toolName: string) => {
      try {
        await deleteTool(toolName);
        setDeleteMessage(`已删除 ${toolName}，不可撤销`);
        setDeleteConfirming(null);

        // Remove from local state immediately
        setTools((prev) => prev.filter((t) => t.tool_name !== toolName));
        if (expandedTool === toolName) {
          setExpandedTool(null);
        }

        // Clear message after 3 seconds
        setTimeout(() => {
          setDeleteMessage(null);
        }, 3000);
      } catch {
        setDeleteConfirming(null);
      }
    },
    [expandedTool],
  );

  // ── Auto-reset delete confirmation after 3s idle ─────────────────────────

  useEffect(() => {
    if (deleteConfirming === null) return;
    const timer = setTimeout(() => {
      setDeleteConfirming(null);
    }, 3000);
    return () => clearTimeout(timer);
  }, [deleteConfirming]);

  // ── Persistence Badge variant ────────────────────────────────────────────

  function persistenceVariant(persistence: string): "default" | "secondary" | "outline" {
    switch (persistence) {
      case "project":
        return "default";
      case "sandbox":
        return "secondary";
      default:
        return "outline";
    }
  }

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Sidebar (left) */}
      <div className="w-80 bg-card border-r border-border shadow-lg overflow-y-auto">
        {/* Header */}
        <div className="p-4 border-b border-border">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">Dynamic Tools</h2>
            <Button variant="ghost" size="icon-sm" onClick={closePanel}>
              <X className="size-4" />
            </Button>
          </div>
        </div>

        {/* Loading state */}
        {loading && (
          <div className="p-4 space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="space-y-2">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-48" />
              </div>
            ))}
          </div>
        )}

        {/* Error state */}
        {error && (
          <div className="p-8 text-center space-y-2">
            <p className="text-sm text-destructive">{error}</p>
            <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
              Retry
            </Button>
          </div>
        )}

        {/* Empty state (D-02) */}
        {!loading && !error && tools.length === 0 && (
          <div className="p-8 text-center space-y-2">
            <Hammer className="size-8 mx-auto text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              暂无动态工具。当 Agent 在会话中创建工具并经你确认后，它们会出现在这里。
            </p>
          </div>
        )}

        {/* Tool list */}
        {!loading && !error && tools.length > 0 && (
          <div className="divide-y divide-border">
            {tools.map((tool) => (
              <div key={tool.tool_name}>
                {/* Tool row (collapsed) */}
                <div
                  className="flex items-center justify-between p-4 hover:bg-accent/50 cursor-pointer"
                  onClick={() => toggleExpand(tool.tool_name)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") toggleExpand(tool.tool_name);
                  }}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium truncate">{tool.tool_name}</span>
                      <Badge variant="secondary" className="text-[10px]">{tool.language}</Badge>
                      <Badge variant={persistenceVariant(tool.persistence)} className="text-[10px]">
                        {tool.persistence}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground truncate mt-0.5">
                      {tool.description}
                    </p>
                  </div>
                  {/* Switch toggle (D-07) — click stops propagation */}
                  <div className="flex items-center gap-2 shrink-0 ml-2">
                    {toggleLoading === tool.tool_name && (
                      <Loader2 className="size-3 animate-spin text-muted-foreground" />
                    )}
                    <Switch
                      checked={tool.enabled}
                      onCheckedChange={(checked) => handleToggle(tool.tool_name, checked)}
                      onClick={(e) => e.stopPropagation()}
                      aria-label={tool.enabled ? "Disable tool" : "Enable tool"}
                    />
                  </div>
                </div>

                {/* Expanded code view (D-16) */}
                {expandedTool === tool.tool_name && (
                  <div className="px-4 pb-4 space-y-3">
                    {/* Code (Monaco Editor read-only) */}
                    <div className="border rounded-md overflow-hidden">
                      {codeLoading === tool.tool_name ? (
                        <Skeleton className="h-[200px] w-full rounded-md" />
                      ) : (
                        <Editor
                          height="200px"
                          language={tool.language === "python" ? "python" : "shell"}
                          value={toolCodeMap[tool.tool_name] || "// Loading..."}
                          theme="vs-dark"
                          options={{
                            readOnly: true,
                            minimap: { enabled: false },
                            lineNumbers: "on",
                            scrollBeyondLastLine: false,
                            wordWrap: "on",
                            fontSize: 12,
                          }}
                        />
                      )}
                    </div>

                    {/* Delete button with in-line confirmation (D-12, D-14) */}
                    <div className="flex justify-end">
                      {deleteConfirming === tool.tool_name ? (
                        <div className="flex items-center gap-2 text-xs">
                          <span className="text-muted-foreground">
                            删除 {tool.tool_name}（{tool.persistence}级）？
                          </span>
                          <Button
                            variant="destructive"
                            size="sm"
                            className="h-7 text-xs"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDelete(tool.tool_name);
                            }}
                          >
                            是
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 text-xs"
                            onClick={(e) => {
                              e.stopPropagation();
                              setDeleteConfirming(null);
                            }}
                          >
                            否
                          </Button>
                        </div>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs text-destructive"
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeleteConfirming(tool.tool_name);
                          }}
                        >
                          <Trash2 className="size-3 mr-1" />
                          Delete
                        </Button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Success message (D-13) */}
        {deleteMessage && (
          <div className="p-3 bg-destructive/10 border-t border-destructive/20">
            <p className="text-xs text-destructive">{deleteMessage}</p>
          </div>
        )}
      </div>

      {/* Backdrop (D-01) */}
      <div className="flex-1 bg-black/20" onClick={closePanel} />
    </div>
  );
}

export default ToolManagementPanel;
