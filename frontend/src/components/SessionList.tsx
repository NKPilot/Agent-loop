import { useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Trash2, Download } from "lucide-react";
import { fetchSessions, fetchSession, deleteSession, exportSessionUrl } from "@/lib/api";
import type { SessionSummary } from "@/lib/api";
import type { Event } from "@/lib/eventTypes";
import { useUIStore } from "@/stores/uiStore";
import { useEventStore } from "@/stores/eventStore";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

// ── Status badge mapping ────────────────────────────────────────────────

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  running: "default",
  completed: "secondary",
  error: "destructive",
};

const STATUS_LABEL: Record<string, string> = {
  running: "Running",
  completed: "Completed",
  error: "Error",
};

function getStatusBadge(status: string) {
  const variant = STATUS_VARIANT[status] ?? "outline";
  const label = STATUS_LABEL[status] ?? status;
  return <Badge variant={variant}>{label}</Badge>;
}

// ── Session item ────────────────────────────────────────────────────────

interface SessionItemProps {
  session: SessionSummary;
  isActive: boolean;
  onSelect: (id: string) => void;
}

function SessionItem({ session, isActive, onSelect }: SessionItemProps) {
  const queryClient = useQueryClient();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleSelect = useCallback(async () => {
    onSelect(session.id);
    // Load historical events into the event store
    try {
      const detail = await fetchSession(session.id);
      if (detail.events && detail.events.length > 0) {
        useEventStore.getState().loadSessionEvents(
          session.id,
          detail.events as unknown as Event[]
        );
      }
    } catch {
      // Session might not exist yet or API unavailable — timeline stays empty
    }
  }, [session.id, onSelect]);

  const handleDelete = useCallback(async () => {
    setDeleting(true);
    try {
      await deleteSession(session.id);
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
      setDeleteOpen(false);
    } catch {
      // Keep dialog open on failure
    } finally {
      setDeleting(false);
    }
  }, [session.id, queryClient]);

  const handleExport = useCallback(() => {
    window.open(exportSessionUrl(session.id), "_blank");
  }, [session.id]);

  const truncatedId = session.id.length > 8 ? session.id.slice(0, 8) : session.id;
  const timestamp = session.created_at
    ? new Date(session.created_at).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

  return (
    <>
      <div
        className={`flex cursor-pointer items-center gap-3 border-l-2 px-4 py-2.5 transition-colors hover:bg-accent/50 ${
          isActive
            ? "border-primary bg-accent/40"
            : "border-transparent"
        }`}
        onClick={handleSelect}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") handleSelect();
        }}
      >
        <div className="flex flex-1 flex-col gap-0.5 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-mono text-foreground truncate">
              {truncatedId}
            </span>
            <span className="text-xs text-muted-foreground tabular-nums">
              {session.step_count} steps
            </span>
          </div>
          <div className="flex items-center gap-2">
            {getStatusBadge(session.status)}
            {timestamp && (
              <span className="text-xs text-muted-foreground">{timestamp}</span>
            )}
          </div>
        </div>

        <DropdownMenu>
          <DropdownMenuTrigger>
            <Button
              variant="ghost"
              size="icon-xs"
              className="shrink-0"
              onClick={(e) => e.stopPropagation()}
            >
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={handleExport}>
              <Download />
              Export JSONL
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              variant="destructive"
              onClick={(e) => {
                e.stopPropagation();
                setDeleteOpen(true);
              }}
            >
              <Trash2 />
              Delete Session
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Delete confirmation dialog */}
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Session?</DialogTitle>
            <DialogDescription>
              This session and all its recorded steps, tool results, and token
              data will be permanently removed. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleting}
            >
              {deleting ? "Deleting..." : "Delete Session"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

// ── Loading skeleton ─────────────────────────────────────────────────────

function SessionListSkeleton() {
  return (
    <div className="space-y-1 p-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 px-4 py-3">
          <div className="flex flex-1 flex-col gap-2">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-3 w-16" />
          </div>
          <Skeleton className="h-6 w-6 rounded-full" />
        </div>
      ))}
    </div>
  );
}

// ── SessionList ──────────────────────────────────────────────────────────

function SessionList() {
  const [search, setSearch] = useState("");
  const activeSessionId = useUIStore((s) => s.activeSessionId);
  const setActiveSession = useUIStore((s) => s.setActiveSession);

  const {
    data: sessions,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["sessions"],
    queryFn: fetchSessions,
    refetchInterval: 15_000, // Poll every 15s for session list updates
  });

  const handleSelectSession = useCallback(
    (id: string) => {
      setActiveSession(id);
    },
    [setActiveSession]
  );

  const filteredSessions = sessions
    ? search.trim()
      ? sessions.filter((s) =>
          s.id.toLowerCase().includes(search.toLowerCase())
        )
      : sessions
    : [];

  return (
    <div className="flex h-full flex-col">
      {/* Search input */}
      <div className="border-b border-border px-3 py-2">
        <Input
          placeholder="Search sessions..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-7 text-xs"
        />
      </div>

      {/* Session list */}
      <ScrollArea className="flex-1">
        {isLoading && <SessionListSkeleton />}

        {isError && (
          <div className="flex items-center justify-center p-6">
            <p className="text-xs text-destructive">
              Failed to load sessions. Retrying...
            </p>
          </div>
        )}

        {!isLoading && !isError && filteredSessions.length === 0 && (
          <div className="flex flex-1 items-center justify-center p-6">
            <div className="text-center space-y-2">
              <p className="text-sm font-medium text-foreground">
                No Agent Sessions Yet
              </p>
              <p className="text-xs text-muted-foreground">
                Start your first agent session to see real-time reasoning
                steps, tool calls, and token usage right here.
              </p>
            </div>
          </div>
        )}

        {!isLoading &&
          !isError &&
          filteredSessions.map((session) => (
            <SessionItem
              key={session.id}
              session={session}
              isActive={session.id === activeSessionId}
              onSelect={handleSelectSession}
            />
          ))}
      </ScrollArea>
    </div>
  );
}

export default SessionList;
