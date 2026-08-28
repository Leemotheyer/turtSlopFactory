"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import {
  addNote,
  updateNote,
  deleteNote,
  connectCursor,
  connectGithubToken,
  disconnectGithubToken,
  createProject,
  deleteProject,
  updateProjectRepo,
  fetchGithubRepos,
  deleteSecret,
  disconnectCursor,
  fetchArtifact,
  fetchDeployments,
  fetchCursorStatus,
  fetchCursorUsage,
  fetchDiscovery,
  startDiscovery,
  fetchEvents,
  fetchInputRequests,
  fetchLog,
  fetchNotes,
  fetchNotifications,
  fetchProgress,
  fetchProjectDetail,
  fetchProjectTasks,
  fetchProjects,
  fetchSecrets,
  fetchUnreadCount,
  getWebSocketUrl,
  markAllNotificationsRead,
  markNotificationRead,
  promoteProject,
  mergeToMain,
  respondToInput,
  runPipeline,
  stopPipeline,
  fetchAgentActivity,
  setSecret,
  submitIntake,
  updateAgentBackend,
  updateAgentModel,
  updateAgentModels,
  fetchCursorModels,
  agentBackendLabel,
  ensurePublicConfig,
  resolvePreviewUrl,
  completeSetup,
  fetchSetupStatus,
  updatePreviewHost,
  updateInstanceApiKey,
  verifyFactoryApiKey,
  hasStoredFactoryApiKey,
  type GithubRepository,
  type CursorModel,
  type AgentBackend,
  type AgentRoleModelKey,
  type AgentRoleModels,
  type SetupStatus,
  type CursorConnectionStatus,
  type CursorUsage,
  type Deployment,
  type DiscoverySession,
  type FactoryEvent,
  type InputRequest,
  type NoteType,
  type Notification,
  type ProgressDigest,
  type Project,
  type ProjectDetail,
  type ProjectNote,
  type ProjectSecrets,
  type Task,
  type AgentActivity,
} from "@/lib/api";
import { EmptyState } from "@/components/ui/EmptyState";
import { FieldError, inputInvalidClass } from "@/components/ui/FieldError";
import { DetailSkeleton, ProjectListSkeleton } from "@/components/ui/Skeleton";
import { Spinner } from "@/components/ui/Spinner";
import uiStyles from "@/components/ui/ui.module.css";
import styles from "./page.module.css";
import { IntakePanel } from "@/components/intake/IntakePanel";

const PIPELINE = [
  "REQUESTED",
  "DISCOVERY",
  "INTAKE_PENDING",
  "PLANNING",
  "IMPLEMENTING",
  "UNIT_TESTING",
  "INTEGRATION_TESTING",
  "DOCKER_BUILD",
  "STAGING_DEPLOY",
  "SMOKE_TESTING",
  "REVIEW",
  "PRODUCTION",
] as const;

const AUTO_START_PIPELINE_STATES = new Set([
  "PLANNING",
  "DIAGNOSING",
  "FIXING",
  "IMPLEMENTING",
  "UNIT_TESTING",
  "INTEGRATION_TESTING",
  "DOCKER_BUILD",
  "STAGING_DEPLOY",
  "SMOKE_TESTING",
]);

const STATE_COLORS: Record<string, string> = {
  REQUESTED: "#6b7280",
  DISCOVERY: "#5b8def",
  INTAKE_PENDING: "#f5a623",
  PLANNING: "#5b8def",
  IMPLEMENTING: "#5b8def",
  UNIT_TESTING: "#f5a623",
  INTEGRATION_TESTING: "#f5a623",
  DOCKER_BUILD: "#f5a623",
  STAGING_DEPLOY: "#f5a623",
  SMOKE_TESTING: "#f5a623",
  REVIEW: "#a78bfa",
  PRODUCTION: "#3dd68c",
  DIAGNOSING: "#f56565",
  FIXING: "#f5a623",
  AUTONOMOUSLY_BLOCKED: "#f56565",
};

type Tab = "overview" | "intake" | "guidance" | "secrets" | "tasks" | "artifacts" | "deployments" | "logs";
type MobilePanel = "projects" | "status" | "activity";

const NOTE_TYPES: { value: NoteType; label: string }[] = [
  { value: "instruction", label: "Instruction" },
  { value: "feature", label: "Add feature" },
  { value: "scope_out", label: "Out of scope" },
  { value: "general", label: "General" },
];

const PROJECT_NAME_MAX = 200;
const PROJECT_DESC_MAX = 10000;
const NOTE_CONTENT_MAX = 5000;

function confirmAction(message: string): boolean {
  return window.confirm(message);
}

export default function DashboardPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [events, setEvents] = useState<FactoryEvent[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [logLoading, setLogLoading] = useState(false);
  const [secretErrors, setSecretErrors] = useState<{ key?: string; value?: string }>({});
  const [enrichmentError, setEnrichmentError] = useState<string | null>(null);
  const createFormRef = useRef<HTMLFormElement>(null);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [artifactView, setArtifactView] = useState<{ name: string; content: string } | null>(null);
  const [logView, setLogView] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressDigest | null>(null);
  const [agentActivity, setAgentActivity] = useState<AgentActivity | null>(null);
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [stoppingPipeline, setStoppingPipeline] = useState(false);
  const [notes, setNotes] = useState<ProjectNote[]>([]);
  const [inputRequests, setInputRequests] = useState<InputRequest[]>([]);
  const [noteText, setNoteText] = useState("");
  const [noteType, setNoteType] = useState<NoteType>("instruction");
  const [noteFormError, setNoteFormError] = useState<string | null>(null);
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null);
  const [editNoteText, setEditNoteText] = useState("");
  const [editNoteType, setEditNoteType] = useState<NoteType>("instruction");
  const [editProjectName, setEditProjectName] = useState("");
  const [editProjectDesc, setEditProjectDesc] = useState("");
  const [createFormErrors, setCreateFormErrors] = useState<{ name?: string; description?: string }>({});
  const [projectDetailsError, setProjectDetailsError] = useState<string | null>(null);
  const [inputResponses, setInputResponses] = useState<Record<string, string>>({});
  const [discovery, setDiscovery] = useState<DiscoverySession | null>(null);
  const [intakeAnswers, setIntakeAnswers] = useState<Record<string, string | string[]>>({});
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [showNotifications, setShowNotifications] = useState(false);
  const [secrets, setSecrets] = useState<ProjectSecrets | null>(null);
  const [secretKey, setSecretKey] = useState("");
  const [secretValue, setSecretValue] = useState("");
  const [secretDesc, setSecretDesc] = useState("");
  const [showCursor, setShowCursor] = useState(false);
  const [cursorStatus, setCursorStatus] = useState<CursorConnectionStatus | null>(null);
  const [cursorUsage, setCursorUsage] = useState<CursorUsage | null>(null);
  const [cursorApiKey, setCursorApiKey] = useState("");
  const [githubApiKey, setGithubApiKey] = useState("");
  const [cursorLoading, setCursorLoading] = useState(false);
  const [cursorFeedback, setCursorFeedback] = useState<{
    type: "success" | "error" | "info";
    message: string;
  } | null>(null);
  const [factoryKeyFeedback, setFactoryKeyFeedback] = useState<{
    type: "success" | "error" | "info";
    message: string;
  } | null>(null);
  const [githubFeedback, setGithubFeedback] = useState<{
    type: "success" | "error" | "info";
    message: string;
  } | null>(null);
  const [browserHasFactoryKey, setBrowserHasFactoryKey] = useState(false);
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null);
  const [setupPreviewHost, setSetupPreviewHost] = useState("");
  const [setupApiKey, setSetupApiKey] = useState("");
  const [instanceApiKey, setInstanceApiKey] = useState("");
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("status");
  const [newRepoUrl, setNewRepoUrl] = useState("");
  const [newBranch, setNewBranch] = useState("main");
  const [newIsolateBranch, setNewIsolateBranch] = useState(true);
  const [editRepoUrl, setEditRepoUrl] = useState("");
  const [editBranch, setEditBranch] = useState("main");
  const [editIsolateBranch, setEditIsolateBranch] = useState(true);
  const [editEnrichmentPasses, setEditEnrichmentPasses] = useState("");
  const [githubRepos, setGithubRepos] = useState<GithubRepository[]>([]);
  const [repoLoading, setRepoLoading] = useState(false);
  const [repoNote, setRepoNote] = useState<string | null>(null);
  const [cursorModels, setCursorModels] = useState<CursorModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);

  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const discoveryKickoff = useRef<string | null>(null);
  const pipelineKickoff = useRef<string | null>(null);
  const intakeInitializedFor = useRef<string | null>(null);

  function selectProject(id: string) {
    setSelectedId(id);
    setTab("overview");
    setArtifactView(null);
    setLogView(null);
    setMobilePanel("status");
    setDetailLoading(true);
  }

  const loadSetup = useCallback(async () => {
    await ensurePublicConfig();
    setBrowserHasFactoryKey(hasStoredFactoryApiKey());
    try {
      const status = await fetchSetupStatus();
      setSetupStatus(status);
      if (!setupPreviewHost) {
        setSetupPreviewHost(
          status.preview_host !== "localhost" && status.preview_host
            ? status.preview_host
            : typeof window !== "undefined"
              ? window.location.hostname
              : status.preview_host
        );
      }
    } catch {
      setSetupStatus(null);
    }
  }, [setupPreviewHost]);

  const refresh = useCallback(async () => {
    try {
      const p = await fetchProjects();
      setProjects(p);
      if (!selectedId && p.length > 0) setSelectedId(p[0].id);

      const [notifs, unread] = await Promise.all([
        fetchNotifications(),
        fetchUnreadCount(),
      ]);
      setNotifications(notifs);
      setUnreadCount(unread);

      if (selectedId) {
        setDetailLoading(true);
        try {
          const [d, t, dep, e, prog, n, inputs, disc, sec, activity] = await Promise.all([
            fetchProjectDetail(selectedId),
            fetchProjectTasks(selectedId),
            fetchDeployments(selectedId),
            fetchEvents(100, selectedId),
            fetchProgress(selectedId),
            fetchNotes(selectedId),
            fetchInputRequests(selectedId),
            fetchDiscovery(selectedId),
            fetchSecrets(selectedId),
            fetchAgentActivity(selectedId),
          ]);
          setDetail(d);
          setTasks(t);
          setDeployments(dep);
          setEvents(e);
          setProgress(prog);
          setAgentActivity(activity);
          setNotes(n);
          setInputRequests(inputs);
          setDiscovery(disc);
          setSecrets(sec);
        } finally {
          setDetailLoading(false);
        }
      } else {
        setDetail(null);
        setDetailLoading(false);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setInitialLoading(false);
    }
  }, [selectedId]);

  const loadCursor = useCallback(async () => {
    try {
      const [status, usage] = await Promise.all([fetchCursorStatus(), fetchCursorUsage()]);
      setCursorStatus(status);
      setCursorUsage(usage);
    } catch (err) {
      setCursorStatus({ connected: false });
      setCursorUsage(null);
      const message = err instanceof Error ? err.message : "Could not reach the factory API";
      if (setupStatus?.api_key_required && !hasStoredFactoryApiKey()) {
        setCursorFeedback({
          type: "error",
          message:
            "Factory API key is required. Enter it below under Deployment, then try connecting Cursor again.",
        });
      } else if (message.includes("Factory API key")) {
        setCursorFeedback({ type: "error", message });
      }
    }
  }, [setupStatus?.api_key_required]);

  useEffect(() => {
    setBrowserHasFactoryKey(hasStoredFactoryApiKey());
    loadSetup().then(() => refresh());
  }, []);

  useEffect(() => {
    loadCursor();
  }, [loadCursor]);

  const loadGithubRepos = useCallback(async (refresh = false) => {
    if (!cursorStatus?.connected) {
      setGithubRepos([]);
      return;
    }
    setRepoLoading(true);
    try {
      const data = await fetchGithubRepos(refresh);
      setGithubRepos(data.repositories ?? []);
      setRepoNote(data.note ?? data.error ?? null);
    } catch {
      setGithubRepos([]);
    } finally {
      setRepoLoading(false);
    }
  }, [cursorStatus?.connected]);

  useEffect(() => {
    loadGithubRepos();
  }, [loadGithubRepos]);

  useEffect(() => {
    if (detail) {
      setEditRepoUrl(detail.repo_url ?? "");
      setEditBranch(detail.base_branch ?? detail.branch ?? "main");
      setEditIsolateBranch(detail.isolate_branch ?? true);
      setEditEnrichmentPasses(
        detail.max_enrichment_passes != null ? String(detail.max_enrichment_passes) : ""
      );
      setEditProjectName(detail.name);
      setEditProjectDesc(detail.description);
      setProjectDetailsError(null);
    }
  }, [
    detail?.id,
    detail?.repo_url,
    detail?.branch,
    detail?.base_branch,
    detail?.isolate_branch,
    detail?.max_enrichment_passes,
  ]);

  useEffect(() => {
    if (showCursor) loadCursor();
  }, [showCursor, loadCursor]);

  const loadCursorModels = useCallback(async () => {
    setModelsLoading(true);
    try {
      const data = await fetchCursorModels();
      setCursorModels(data.models ?? []);
    } catch {
      setCursorModels([]);
    } finally {
      setModelsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (showCursor && cursorStatus?.connected) {
      loadCursorModels();
    }
  }, [showCursor, cursorStatus?.connected, loadCursorModels]);

  useEffect(() => {
    intakeInitializedFor.current = null;
    setIntakeAnswers({});
  }, [selectedId]);

  useEffect(() => {
    if (!discovery?.id || discovery.status !== "awaiting_user" || !discovery.form_fields.length) {
      return;
    }
    const initKey = `${discovery.id}:${discovery.form_fields.length}`;
    if (intakeInitializedFor.current === initKey) return;
    intakeInitializedFor.current = initKey;

    const initial: Record<string, string | string[]> = {};
    discovery.form_fields.forEach((f) => {
      const saved = discovery.responses?.[f.id];
      if (saved !== undefined && saved !== "") {
        initial[f.id] = saved as string | string[];
      } else if (f.default) {
        initial[f.id] = f.default;
      }
    });
    setIntakeAnswers(initial);
  }, [discovery?.id, discovery?.status, discovery?.form_fields, discovery?.responses]);

  useEffect(() => {
    if (detail?.state === "INTAKE_PENDING") {
      setTab("intake");
    }
  }, [detail?.state]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, detail?.pipeline_running ? 2000 : 10000);
    return () => clearInterval(interval);
  }, [refresh, detail?.pipeline_running]);

  useEffect(() => {
    if (!selectedId || detail?.state !== "REQUESTED") return;
    if (discoveryKickoff.current === selectedId) return;
    discoveryKickoff.current = selectedId;
    startDiscovery(selectedId)
      .then(() => refresh())
      .catch((err) => {
        discoveryKickoff.current = null;
        setError(err instanceof Error ? err.message : "Discovery failed to start");
      });
  }, [selectedId, detail?.state, refresh]);

  useEffect(() => {
    if (!selectedId || !detail) return;
    if (!AUTO_START_PIPELINE_STATES.has(detail.state) || detail.pipeline_running || detail.pipeline_paused) return;
    if (pipelineKickoff.current === selectedId) return;
    pipelineKickoff.current = selectedId;
    runPipeline(selectedId)
      .then(() => refresh())
      .catch((err) => {
        pipelineKickoff.current = null;
        setError(err instanceof Error ? err.message : "Failed to start pipeline");
      });
  }, [selectedId, detail?.state, detail?.pipeline_running, refresh]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let cancelled = false;

    ensurePublicConfig().then(() => {
      if (cancelled) return;
      ws = new WebSocket(`${getWebSocketUrl()}/ws/events`);
      ws.onopen = () => setConnected(true);
      ws.onclose = () => setConnected(false);
      ws.onmessage = (msg) => {
        const data = JSON.parse(msg.data);
        if (data.type === "ping") return;
        setEvents((prev) => [...prev.slice(-199), data]);
        if (refreshTimer.current) clearTimeout(refreshTimer.current);
        refreshTimer.current = setTimeout(() => refresh(), 400);
      };
    });

    return () => {
      cancelled = true;
      ws?.close();
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
    };
  }, [refresh]);

  async function handleDeleteProject() {
    if (!selectedId || !detail) return;
    const message = detail.repo_url
      ? "Delete this project from the factory? Local files will be removed but the GitHub repository will not be deleted."
      : "Delete this project and all local files? This cannot be undone.";
    if (!window.confirm(message)) return;
    setLoading(true);
    try {
      await deleteProject(selectedId);
      discoveryKickoff.current = null;
      pipelineKickoff.current = null;
      setSelectedId(null);
      setDetail(null);
      setDiscovery(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete project");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const name = newName.trim();
    const description = newDesc.trim();
    const errors: { name?: string; description?: string } = {};
    if (!name) errors.name = "Project name is required";
    else if (name.length > PROJECT_NAME_MAX) {
      errors.name = `Name must be at most ${PROJECT_NAME_MAX} characters`;
    }
    if (!description) errors.description = "Description is required";
    else if (description.length > PROJECT_DESC_MAX) {
      errors.description = `Description must be at most ${PROJECT_DESC_MAX} characters`;
    }
    if (Object.keys(errors).length > 0) {
      setCreateFormErrors(errors);
      return;
    }
    setCreateFormErrors({});
    setLoading(true);
    try {
      const p = await createProject(name, description, {
        repo_url: newRepoUrl || null,
        base_branch: newBranch || "main",
        isolate_branch: newRepoUrl ? newIsolateBranch : false,
      });
      setNewName("");
      setNewDesc("");
      setNewRepoUrl("");
      setNewBranch("main");
      setNewIsolateBranch(true);
      setSelectedId(p.id);
      setDetailLoading(true);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleSaveRepo(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedId) return;
    if (editEnrichmentPasses.trim() !== "") {
      const parsed = parseInt(editEnrichmentPasses, 10);
      if (Number.isNaN(parsed) || parsed < 0 || parsed > 20) {
        setEnrichmentError("Enter a whole number from 0 to 20, or leave blank for the factory default.");
        return;
      }
    }
    setEnrichmentError(null);
    setLoading(true);
    try {
      await updateProjectRepo(selectedId, {
        repo_url: editRepoUrl || null,
        base_branch: editBranch || "main",
        isolate_branch: editRepoUrl ? editIsolateBranch : false,
        clear_repo: !editRepoUrl,
        max_enrichment_passes:
          editEnrichmentPasses.trim() === ""
            ? null
            : Math.max(0, Math.min(20, parseInt(editEnrichmentPasses, 10) || 0)),
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save repository");
    } finally {
      setLoading(false);
    }
  }

  async function handleRun() {
    if (!selectedId) return;
    setLoading(true);
    try {
      const result = await runPipeline(selectedId);
      if (result.status === "already_running") {
        setError("Pipeline is already running for this project.");
      } else if (result.mode === "feedback") {
        setError(null);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Pipeline start failed");
    } finally {
      setLoading(false);
    }
  }

  const projectDetailsDirty =
    !!detail &&
    (editProjectName.trim() !== detail.name || editProjectDesc.trim() !== detail.description);

  async function handleSaveProjectDetails(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedId || !detail) return;
    const name = editProjectName.trim();
    const description = editProjectDesc.trim();
    if (!name) {
      setProjectDetailsError("Project name is required");
      return;
    }
    if (name.length > PROJECT_NAME_MAX) {
      setProjectDetailsError(`Name must be at most ${PROJECT_NAME_MAX} characters`);
      return;
    }
    if (!description) {
      setProjectDetailsError("Description is required");
      return;
    }
    if (description.length > PROJECT_DESC_MAX) {
      setProjectDetailsError(`Description must be at most ${PROJECT_DESC_MAX} characters`);
      return;
    }
    setProjectDetailsError(null);
    setLoading(true);
    try {
      await updateProjectRepo(selectedId, { name, description });
      await refresh();
    } catch (err) {
      setProjectDetailsError(err instanceof Error ? err.message : "Failed to save project details");
    } finally {
      setLoading(false);
    }
  }

  async function handleStop() {
    if (!selectedId) return;
    if (
      !confirmAction(
        "Stop the pipeline now? In-flight agent work on this project will be cancelled."
      )
    ) {
      return;
    }
    setStoppingPipeline(true);
    try {
      await stopPipeline(selectedId);
      pipelineKickoff.current = null;
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to stop pipeline");
    } finally {
      setStoppingPipeline(false);
    }
  }

  async function handlePromote() {
    if (!selectedId) return;
    setLoading(true);
    try {
      await promoteProject(selectedId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Promote failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleMergeToMain() {
    if (!selectedId || !detail) return;
    if (
      !confirmAction(
        `Merge factory branch ${detail.work_branch ?? "work branch"} into ${detail.base_branch ?? "main"}? This pushes to GitHub.`
      )
    ) {
      return;
    }
    setLoading(true);
    try {
      await mergeToMain(selectedId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Merge failed");
    } finally {
      setLoading(false);
    }
  }

  const repoSettingsDirty =
    !!detail &&
    (editRepoUrl !== (detail.repo_url ?? "") ||
      editBranch !== (detail.base_branch ?? detail.branch ?? "main") ||
      editIsolateBranch !== (detail.isolate_branch ?? true) ||
      editEnrichmentPasses !==
        (detail.max_enrichment_passes != null ? String(detail.max_enrichment_passes) : ""));

  const effectiveEnrichmentPasses =
    detail?.effective_enrichment_passes ??
    detail?.factory_default_enrichment_passes ??
    3;

  const enrichmentProgress = detail?.enrichment_progress;
  const pipelineSubstage = detail?.pipeline_substage;
  const enrichmentProgressLines =
    progress?.summary_lines.filter((line) => /enrichment pass/i.test(line)) ?? [];

  async function viewArtifact(name: string) {
    if (!selectedId) return;
    const content = await fetchArtifact(selectedId, name);
    setArtifactView({ name, content });
  }

  async function viewLog(name: string) {
    if (!selectedId) return;
    setLogLoading(true);
    setLogView(null);
    try {
      const content = await fetchLog(selectedId, name);
      setLogView(content);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load log");
    } finally {
      setLogLoading(false);
    }
  }

  async function handleAddNote(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedId) return;
    const content = noteText.trim();
    if (!content) {
      setNoteFormError("Note content is required");
      return;
    }
    if (content.length > NOTE_CONTENT_MAX) {
      setNoteFormError(`Note must be at most ${NOTE_CONTENT_MAX} characters`);
      return;
    }
    setNoteFormError(null);
    setLoading(true);
    try {
      await addNote(selectedId, content, noteType);
      setNoteText("");
      await refresh();
    } catch (err) {
      setNoteFormError(err instanceof Error ? err.message : "Failed to add note");
    } finally {
      setLoading(false);
    }
  }

  function startEditNote(note: ProjectNote) {
    setEditingNoteId(note.id);
    setEditNoteText(note.content);
    setEditNoteType(note.note_type);
    setNoteFormError(null);
  }

  function cancelEditNote() {
    setEditingNoteId(null);
    setEditNoteText("");
    setNoteFormError(null);
  }

  async function handleUpdateNote(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedId || !editingNoteId) return;
    const content = editNoteText.trim();
    if (!content) {
      setNoteFormError("Note content is required");
      return;
    }
    if (content.length > NOTE_CONTENT_MAX) {
      setNoteFormError(`Note must be at most ${NOTE_CONTENT_MAX} characters`);
      return;
    }
    setNoteFormError(null);
    setLoading(true);
    try {
      await updateNote(selectedId, editingNoteId, { content, note_type: editNoteType });
      cancelEditNote();
      await refresh();
    } catch (err) {
      setNoteFormError(err instanceof Error ? err.message : "Failed to update note");
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteNote(note: ProjectNote) {
    if (!selectedId) return;
    if (
      !confirmAction(
        `Delete this ${note.note_type.replace("_", " ")} note? Agents will no longer see it on the next step.`
      )
    ) {
      return;
    }
    setLoading(true);
    try {
      await deleteNote(selectedId, note.id);
      if (editingNoteId === note.id) cancelEditNote();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete note");
    } finally {
      setLoading(false);
    }
  }

  async function handleRespondInput(requestId: string) {
    if (!selectedId) return;
    const response = inputResponses[requestId]?.trim();
    if (!response) return;
    setLoading(true);
    try {
      await respondToInput(selectedId, requestId, response);
      setInputResponses((prev) => ({ ...prev, [requestId]: "" }));
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to respond");
    } finally {
      setLoading(false);
    }
  }

  function validateIntakeForm(): Record<string, string> {
    if (!discovery?.form_fields) return {};
    const errors: Record<string, string> = {};
    for (const field of discovery.form_fields) {
      if (!field.required) continue;
      const value = intakeAnswers[field.id];
      if (field.type === "multiselect") {
        const selected = Array.isArray(value) ? value : value ? [value] : [];
        if (selected.length === 0) {
          errors[field.id] = "Select at least one option";
        }
      } else if (!value || (typeof value === "string" && !value.trim())) {
        errors[field.id] = "This field is required";
      }
    }
    return errors;
  }

  async function handleSubmitIntake(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedId || !discovery) return;
    const errors = validateIntakeForm();
    if (Object.keys(errors).length > 0) {
      setError("Please complete all required intake fields.");
      return;
    }
    setLoading(true);
    try {
      await submitIntake(selectedId, intakeAnswers);
      pipelineKickoff.current = selectedId;
      await refresh();
      setTab("overview");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit intake");
    } finally {
      setLoading(false);
    }
  }

  async function handleSetSecret(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedId) return;
    const key = secretKey.trim();
    const value = secretValue.trim();
    const errors: { key?: string; value?: string } = {};
    if (!key) {
      errors.key = "Key name is required";
    } else if (!/^[A-Z][A-Z0-9_]*$/.test(key)) {
      errors.key = "Use UPPER_SNAKE_CASE (letters, numbers, underscores)";
    }
    if (!value) {
      errors.value = "Secret value is required";
    }
    if (Object.keys(errors).length > 0) {
      setSecretErrors(errors);
      return;
    }
    setSecretErrors({});
    setLoading(true);
    try {
      await setSecret(selectedId, key, value, secretDesc);
      setSecretKey("");
      setSecretValue("");
      setSecretDesc("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save secret");
    } finally {
      setLoading(false);
    }
  }

  async function handleDeleteSecret(keyName: string) {
    if (!selectedId) return;
    if (
      !confirmAction(
        `Remove secret ${keyName}? Agents will no longer have access to this value.`
      )
    ) {
      return;
    }
    setLoading(true);
    try {
      await deleteSecret(selectedId, keyName);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete secret");
    } finally {
      setLoading(false);
    }
  }

  async function handleNotificationClick(notif: Notification) {
    if (!notif.read) {
      await markNotificationRead(notif.id);
      setUnreadCount((c) => Math.max(0, c - 1));
      setNotifications((prev) =>
        prev.map((n) => (n.id === notif.id ? { ...n, read: true } : n))
      );
    }
    setShowNotifications(false);
    if (notif.project_id) {
      setSelectedId(notif.project_id);
      setMobilePanel("status");
    }
    if (notif.action === "secrets") setTab("secrets");
    else if (notif.action === "guidance") setTab("guidance");
    else if (notif.action === "intake") setTab("intake");
    else if (notif.action === "preview") setTab("overview");
    else setTab("overview");
  }

  async function handleMarkAllRead() {
    await markAllNotificationsRead();
    setUnreadCount(0);
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  }

  async function handleConnectGithub(e: React.FormEvent) {
    e.preventDefault();
    if (!githubApiKey.trim()) return;
    setCursorLoading(true);
    setGithubFeedback({ type: "info", message: "Verifying GitHub token…" });
    try {
      const status = await connectGithubToken(githubApiKey);
      setGithubApiKey("");
      setGithubFeedback({
        type: "success",
        message: status.message ?? `GitHub connected as ${status.github_login ?? "user"}.`,
      });
      await loadSetup();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to connect GitHub";
      setGithubFeedback({ type: "error", message });
      setError(message);
    } finally {
      setCursorLoading(false);
    }
  }

  async function handleDisconnectGithub() {
    if (
      !confirmAction(
        "Disconnect GitHub? The factory will not be able to push work branches until you connect again."
      )
    ) {
      return;
    }
    setCursorLoading(true);
    try {
      await disconnectGithubToken();
      setGithubFeedback({ type: "success", message: "GitHub token removed." });
      await loadSetup();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to disconnect GitHub");
    } finally {
      setCursorLoading(false);
    }
  }

  async function handleConnectCursor(e: React.FormEvent) {
    e.preventDefault();
    if (!cursorApiKey.trim()) return;
    setCursorLoading(true);
    setCursorFeedback({ type: "info", message: "Verifying API key with Cursor…" });
    try {
      const status = await connectCursor(cursorApiKey);
      setCursorApiKey("");
      setCursorStatus(status);
      setCursorFeedback({
        type: "success",
        message:
          status.message ??
          `Connected${status.user_email ? ` as ${status.user_email}` : ""}. API key saved securely.`,
      });
      await loadCursor();
      await loadCursorModels();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to connect Cursor";
      setCursorFeedback({ type: "error", message });
      setError(message);
    } finally {
      setCursorLoading(false);
    }
  }

  async function handleDisconnectCursor() {
    if (
      !confirmAction(
        "Disconnect Cursor? Running pipelines and agent tasks will fail until you connect again."
      )
    ) {
      return;
    }
    setCursorLoading(true);
    try {
      await disconnectCursor();
      setCursorStatus({ connected: false });
      setCursorUsage(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to disconnect");
    } finally {
      setCursorLoading(false);
    }
  }

  async function handleCompleteSetup(e: React.FormEvent) {
    e.preventDefault();
    setCursorLoading(true);
    try {
      const status = await completeSetup({
        preview_host: setupPreviewHost.trim() || undefined,
        api_key: setupApiKey.trim() || undefined,
      });
      if (setupApiKey.trim()) {
        localStorage.setItem("api_key", setupApiKey.trim());
      }
      setSetupStatus(status);
      setSetupApiKey("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Setup failed");
    } finally {
      setCursorLoading(false);
    }
  }

  async function handleSaveInstanceApiKey() {
    setCursorLoading(true);
    setFactoryKeyFeedback({ type: "info", message: "Saving factory API key…" });
    try {
      const key = instanceApiKey.trim();
      const result = await updateInstanceApiKey(key || null);
      if (key) {
        localStorage.setItem("api_key", key);
        setFactoryKeyFeedback({ type: "info", message: "Testing saved key…" });
        const verified = await verifyFactoryApiKey(key);
        setFactoryKeyFeedback({
          type: "success",
          message: verified.message ?? result.message ?? "Factory API key saved and verified in this browser.",
        });
      } else {
        localStorage.removeItem("api_key");
        setFactoryKeyFeedback({
          type: "success",
          message: result.message ?? "Factory API key removed.",
        });
      }
      setInstanceApiKey("");
      setBrowserHasFactoryKey(hasStoredFactoryApiKey());
      await loadSetup();
      await loadCursor();
      await refresh();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to save API key";
      setFactoryKeyFeedback({ type: "error", message });
      setError(message);
    } finally {
      setCursorLoading(false);
    }
  }

  async function handleSavePreviewHost() {
    if (!setupPreviewHost.trim()) return;
    setCursorLoading(true);
    try {
      const status = await updatePreviewHost(setupPreviewHost.trim());
      setSetupStatus(status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update host");
    } finally {
      setCursorLoading(false);
    }
  }

  async function handleRoleModelChange(role: AgentRoleModelKey, modelId: string) {
    setCursorLoading(true);
    try {
      const result = await updateAgentModels({ [role]: modelId });
      setCursorStatus((prev) =>
        prev
          ? {
              ...prev,
              agent_models: result.agent_models,
              agent_model: result.agent_model,
              cursor_model: result.agent_model,
            }
          : prev
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update agent model");
    } finally {
      setCursorLoading(false);
    }
  }

  async function handleSetAllRoleModels(modelId: string) {
    setCursorLoading(true);
    try {
      const result = await updateAgentModel(modelId);
      setCursorStatus((prev) =>
        prev
          ? {
              ...prev,
              agent_models: result.agent_models,
              agent_model: result.agent_model,
              cursor_model: result.agent_model,
            }
          : prev
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update agent models");
    } finally {
      setCursorLoading(false);
    }
  }

  async function handleAgentBackendChange(backend: AgentBackend) {
    setCursorLoading(true);
    try {
      const result = await updateAgentBackend(backend);
      setCursorStatus((prev) => (prev ? { ...prev, agent_backend: result.agent_backend } : prev));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update agent backend");
    } finally {
      setCursorLoading(false);
    }
  }

  function formatTokens(n: number | undefined): string {
    return (n ?? 0).toLocaleString();
  }

  function formatDollars(n: number | null | undefined): string {
    if (n == null) return "—";
    return `$${n.toFixed(2)}`;
  }

  function notificationIcon(type: Notification["type"]): string {
    switch (type) {
      case "env_required": return "🔐";
      case "agent_question": return "❓";
      case "project_finished": return "✅";
      case "intake_ready": return "📋";
      case "review_ready": return "👀";
      case "preview_ready": return "🌐";
      case "pipeline_blocked": return "🛑";
      default: return "🔔";
    }
  }

  function focusCreateForm() {
    setMobilePanel("projects");
    createFormRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    createFormRef.current?.querySelector("input")?.focus();
  }

  const openInputs = inputRequests.filter((r) => r.status === "open");
  const runningTasks = tasks.filter((t) => t.status === "RUNNING");
  const pendingSecrets = secrets?.pending_requirements.length ?? 0;
  const livePreviewUrl = resolvePreviewUrl(detail?.preview_url ?? detail?.staging_url);
  const currentIdx = detail ? PIPELINE.indexOf(detail.state as (typeof PIPELINE)[number]) : -1;

  const defaultAgentModel =
    cursorStatus?.default_agent_model ?? cursorStatus?.cursor_model ?? "composer-2";

  const roleModels: AgentRoleModels = cursorStatus?.agent_models ?? {
    architect: defaultAgentModel,
    developer: defaultAgentModel,
    reviewer: defaultAgentModel,
  };

  const ROLE_MODEL_CONFIG: { key: AgentRoleModelKey; label: string; hint: string }[] = [
    {
      key: "architect",
      label: "Architect",
      hint: "Planning, requirements, and system design.",
    },
    {
      key: "developer",
      label: "Developer",
      hint: "Implementation and parallel build streams.",
    },
    {
      key: "reviewer",
      label: "Reviewer",
      hint: "Code review and promotion gate.",
    },
  ];

  const modelOptions = (() => {
    const byId = new Map<string, CursorModel>();
    for (const model of cursorModels) {
      byId.set(model.id, model);
    }
    for (const modelId of Object.values(roleModels)) {
      if (modelId && !byId.has(modelId)) {
        byId.set(modelId, { id: modelId, display_name: modelId });
      }
    }
    return Array.from(byId.values()).sort((a, b) =>
      a.display_name.localeCompare(b.display_name)
    );
  })();

  function renderModelOptions(currentValue: string) {
    if (modelOptions.length === 0) {
      return <option value={currentValue}>{currentValue}</option>;
    }
    return modelOptions.map((model) => (
      <option key={model.id} value={model.id}>
        {model.display_name}
      </option>
    ));
  }

  function repoLabel(url: string): string {
    return url.replace(/^https:\/\/github\.com\//, "").replace(/\.git$/, "");
  }

  function renderRepoOptions(currentUrl = "") {
    const options = githubRepos.map((repo) => (
      <option key={repo.url} value={repo.url}>
        {repo.name}
      </option>
    ));
    if (currentUrl && !githubRepos.some((r) => r.url === currentUrl)) {
      options.unshift(
        <option key={currentUrl} value={currentUrl}>
          {repoLabel(currentUrl)} (linked)
        </option>
      );
    }
    return options;
  }

  function previewTypeLabel(type: string | null | undefined): string {
    switch (type) {
      case "dev": return "Live source preview";
      case "docker": return "Docker image";
      case "production": return "Production";
      case "simulated": return "Simulated";
      default: return "Live preview";
    }
  }

  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        <div className={styles.brand}>
          <div className={styles.logo}>🐢</div>
          <div>
            <h1>turtSlopFactory</h1>
            <p>Agentic software development platform</p>
          </div>
        </div>
        <div className={styles.headerRight}>
          <span className={connected ? styles.live : styles.offline}>
            <span className={styles.dot} />
            {connected ? "Live" : "Offline"}
          </span>
          <span className={styles.badge}>{projects.length} projects</span>
          <div className={styles.notifWrapper}>
            <button
              type="button"
              className={`${styles.cursorBtn} ${cursorStatus?.connected ? styles.cursorConnected : ""}`}
              onClick={() => {
                setShowCursor((v) => !v);
                setShowNotifications(false);
              }}
              aria-label="Cursor account"
            >
              Cursor
              {cursorStatus?.connected && cursorUsage?.tokens && (
                <span className={styles.cursorTokenBadge}>
                  {formatTokens(cursorUsage.tokens.total_tokens)}
                </span>
              )}
            </button>
            {showCursor && (
              <div className={styles.cursorDropdown}>
                <div className={styles.cursorHeader}>
                  <h3>Cursor account</h3>
                  {cursorStatus?.connected && (
                    <button
                      type="button"
                      className={styles.notifMarkAll}
                      onClick={loadCursor}
                      disabled={cursorLoading}
                    >
                      Refresh
                    </button>
                  )}
                </div>
                <div className={styles.cursorBackend}>
                  <label htmlFor="agent-backend">Agent backend</label>
                  <select
                    id="agent-backend"
                    value={cursorStatus?.agent_backend ?? "cursor_cloud"}
                    onChange={(e) => handleAgentBackendChange(e.target.value as AgentBackend)}
                    disabled={cursorLoading}
                  >
                    {(cursorStatus?.valid_backends ?? ["cursor_cloud", "cursor_local", "local"]).map(
                      (b) => (
                        <option key={b} value={b}>
                          {agentBackendLabel(b)}
                        </option>
                      )
                    )}
                  </select>
                  <p className={styles.cursorBackendHint}>
                    Default is Cursor Cloud Agents. Local Cursor runs in your workspace; scaffold mode needs no API key.
                  </p>
                </div>
                <div className={styles.cursorBackend}>
                  <div className={styles.roleModelsHeader}>
                    <label>Agent models by role</label>
                    <button
                      type="button"
                      className={styles.notifMarkAll}
                      onClick={() => handleSetAllRoleModels(roleModels.developer)}
                      disabled={
                        cursorLoading ||
                        modelsLoading ||
                        cursorStatus?.agent_backend === "local"
                      }
                      title="Apply the developer model to all roles"
                    >
                      Match developer
                    </button>
                  </div>
                  <div className={styles.roleModelGrid}>
                    {ROLE_MODEL_CONFIG.map(({ key, label, hint }) => (
                      <label key={key} className={styles.roleModelField}>
                        <span className={styles.roleModelLabel}>{label}</span>
                        <select
                          id={`agent-model-${key}`}
                          value={roleModels[key]}
                          onChange={(e) => handleRoleModelChange(key, e.target.value)}
                          disabled={
                            cursorLoading || modelsLoading || cursorStatus?.agent_backend === "local"
                          }
                        >
                          {renderModelOptions(roleModels[key])}
                        </select>
                        <span className={styles.roleModelHint}>{hint}</span>
                      </label>
                    ))}
                  </div>
                  <p className={styles.cursorBackendHint}>
                    Pick the best model per role — e.g. a reasoning model for architecture and a fast model for implementation.
                    {cursorStatus?.agent_backend === "local"
                      ? " Switch off scaffold mode to use Cursor models."
                      : !cursorStatus?.connected
                        ? " Connect Cursor to load your account's available models."
                        : modelsLoading
                          ? " Loading models…"
                          : ""}
                  </p>
                </div>
                {cursorStatus?.concurrency && (
                  <div className={styles.cursorBackend}>
                    <label>Parallel agents</label>
                    <p className={styles.concurrencySummary}>
                      Up to <strong>{cursorStatus.concurrency.max_parallel}</strong> factory agent
                      {cursorStatus.concurrency.max_parallel === 1 ? "" : "s"} at a time
                      {cursorStatus.concurrency.backend === "cursor_cloud" && (
                        <>
                          {" "}
                          · {cursorStatus.concurrency.active_cursor_agents}/
                          {cursorStatus.concurrency.cursor_slot_limit} Cursor runs in progress
                          {(cursorStatus.concurrency.idle_agents ?? 0) > 0 && (
                            <> · {cursorStatus.concurrency.idle_agents} idle ACTIVE agent(s) not counted</>
                          )}
                        </>
                      )}
                    </p>
                    {cursorStatus.concurrency.max_parallel === 0 && (
                      <p className={styles.cursorBackendHint}>
                        No Cursor slots free for factory agents right now. Running agents will finish first,
                        or archive idle cloud agents in Cursor to free capacity.
                      </p>
                    )}
                    <p className={styles.cursorBackendHint}>{cursorStatus.concurrency.strategy}</p>
                  </div>
                )}
                <div className={styles.cursorDeploy}>
                  <h4>GitHub</h4>
                  <p className={styles.cursorBackendHint}>
                    One token for the whole factory — used to push isolated work branches to GitHub.
                    Use a <strong>classic PAT</strong> with the <strong>repo</strong> scope, or a
                    fine-grained PAT with <strong>Contents: Read and write</strong> on your repositories.
                  </p>
                  {setupStatus?.github_token_configured ? (
                    <div className={styles.cursorAccount}>
                      <strong>{setupStatus.github_login ?? "GitHub connected"}</strong>
                      {setupStatus.masked_github_token && setupStatus.masked_github_token !== "env" && (
                        <span className={styles.cursorKeySaved}>
                          {setupStatus.masked_github_token} · saved
                        </span>
                      )}
                      {setupStatus.github_token_source === "environment" && (
                        <span className={styles.cursorKeyName}>Configured via environment variable</span>
                      )}
                      {!setupStatus.github_token_source && (
                        <button
                          type="button"
                          className={styles.btnDanger}
                          onClick={handleDisconnectGithub}
                          disabled={cursorLoading}
                        >
                          Disconnect
                        </button>
                      )}
                    </div>
                  ) : (
                    <>
                      <a
                        href="https://github.com/settings/tokens"
                        target="_blank"
                        rel="noreferrer"
                        className={styles.cursorDocsLink}
                      >
                        Create classic PAT (enable repo scope) ↗
                      </a>
                      <form className={styles.cursorConnect} onSubmit={handleConnectGithub}>
                        <input
                          type="password"
                          placeholder="ghp_…"
                          value={githubApiKey}
                          onChange={(e) => setGithubApiKey(e.target.value)}
                          autoComplete="off"
                          required
                        />
                        <button type="submit" className={styles.btnPrimary} disabled={cursorLoading}>
                          {cursorLoading ? "Verifying…" : "Connect GitHub"}
                        </button>
                      </form>
                    </>
                  )}
                  {githubFeedback && (
                    <div
                      className={`${styles.feedbackBanner} ${
                        githubFeedback.type === "success"
                          ? styles.feedbackSuccess
                          : githubFeedback.type === "error"
                            ? styles.feedbackError
                            : styles.feedbackInfo
                      }`}
                    >
                      {githubFeedback.message}
                    </div>
                  )}
                </div>
                <div className={styles.cursorDeploy}>
                  <h4>Deployment</h4>
                  <label>
                    Preview hostname
                    <div className={styles.inlineField}>
                      <input
                        type="text"
                        value={setupPreviewHost}
                        onChange={(e) => setSetupPreviewHost(e.target.value)}
                        placeholder={setupStatus?.preview_host ?? "localhost"}
                      />
                      <button
                        type="button"
                        className={styles.btnSecondary}
                        onClick={handleSavePreviewHost}
                        disabled={cursorLoading}
                      >
                        Save
                      </button>
                    </div>
                  </label>
                  <label>
                    Factory API key (optional)
                    <p className={styles.cursorBackendHint}>
                      {setupStatus?.api_key_configured
                        ? browserHasFactoryKey
                          ? "Server has a key and this browser is configured."
                          : "Server has a key — enter it below so this browser can call the API."
                        : "Optional — protect API access. Saved keys are encrypted on the server."}
                    </p>
                    <div className={styles.inlineField}>
                      <input
                        type="password"
                        value={instanceApiKey}
                        onChange={(e) => setInstanceApiKey(e.target.value)}
                        placeholder={setupStatus?.api_key_configured ? "Enter key to sync this browser" : "Protect API access"}
                        autoComplete="off"
                      />
                      <button
                        type="button"
                        className={styles.btnSecondary}
                        onClick={handleSaveInstanceApiKey}
                        disabled={cursorLoading}
                      >
                        {setupStatus?.api_key_configured ? "Save & verify" : "Set & verify"}
                      </button>
                    </div>
                  </label>
                  {factoryKeyFeedback && (
                    <div
                      className={`${styles.feedbackBanner} ${
                        factoryKeyFeedback.type === "success"
                          ? styles.feedbackSuccess
                          : factoryKeyFeedback.type === "error"
                            ? styles.feedbackError
                            : styles.feedbackInfo
                      }`}
                    >
                      {factoryKeyFeedback.message}
                    </div>
                  )}
                  {setupStatus?.auto_configured?.encryption_key && (
                    <p className={styles.cursorBackendHint}>Encryption key auto-generated and stored on the workspace volume.</p>
                  )}
                </div>
                {cursorFeedback && (
                  <div
                    className={`${styles.feedbackBanner} ${
                      cursorFeedback.type === "success"
                        ? styles.feedbackSuccess
                        : cursorFeedback.type === "error"
                          ? styles.feedbackError
                          : styles.feedbackInfo
                    }`}
                  >
                    {cursorFeedback.message}
                  </div>
                )}
                {!cursorStatus?.connected ? (
                  <div className={styles.cursorConnect}>
                    <p>
                      Connect your Cursor API key to see token usage, budget remaining, and cloud agents.
                      The key is tested against Cursor before it is saved.
                    </p>
                    <a
                      href="https://cursor.com/dashboard/api"
                      target="_blank"
                      rel="noreferrer"
                      className={styles.cursorDocsLink}
                    >
                      Get API key from Cursor Dashboard ↗
                    </a>
                    <form onSubmit={handleConnectCursor}>
                      <input
                        type="password"
                        placeholder="crsr_…"
                        value={cursorApiKey}
                        onChange={(e) => setCursorApiKey(e.target.value)}
                        autoComplete="off"
                        required
                      />
                      <button type="submit" className={styles.btnPrimary} disabled={cursorLoading}>
                        {cursorLoading ? "Verifying…" : "Connect account"}
                      </button>
                    </form>
                  </div>
                ) : (
                  <div className={styles.cursorBody}>
                    <div className={styles.cursorAccount}>
                      <strong>{cursorStatus.user_email ?? "Connected"}</strong>
                      {cursorStatus.api_key_name && (
                        <span className={styles.cursorKeyName}>{cursorStatus.api_key_name}</span>
                      )}
                      {cursorStatus.masked_api_key && (
                        <span className={styles.cursorKeySaved}>{cursorStatus.masked_api_key} · saved</span>
                      )}
                    </div>
                    {cursorStatus.connected_at && (
                      <p className={styles.cursorSavedNote}>
                        Cursor API key verified and stored on the server
                        {cursorStatus.models_available != null
                          ? ` · ${cursorStatus.models_available} models available`
                          : ""}
                        .
                      </p>
                    )}
                    {cursorUsage?.tokens && (
                      <div className={styles.cursorUsageGrid}>
                        <div className={styles.cursorStat}>
                          <span className={styles.cursorStatLabel}>Total tokens</span>
                          <span className={styles.cursorStatValue}>
                            {formatTokens(cursorUsage.tokens.total_tokens)}
                          </span>
                        </div>
                        <div className={styles.cursorStat}>
                          <span className={styles.cursorStatLabel}>Input</span>
                          <span className={styles.cursorStatValue}>
                            {formatTokens(cursorUsage.tokens.input_tokens)}
                          </span>
                        </div>
                        <div className={styles.cursorStat}>
                          <span className={styles.cursorStatLabel}>Output</span>
                          <span className={styles.cursorStatValue}>
                            {formatTokens(cursorUsage.tokens.output_tokens)}
                          </span>
                        </div>
                        {cursorUsage.enterprise_billing && (
                          <>
                            <div className={styles.cursorStat}>
                              <span className={styles.cursorStatLabel}>Spent (cycle)</span>
                              <span className={styles.cursorStatValue}>
                                {formatDollars((cursorUsage.spend_cents ?? 0) / 100)}
                              </span>
                            </div>
                            <div className={styles.cursorStat}>
                              <span className={styles.cursorStatLabel}>Remaining</span>
                              <span className={styles.cursorStatValue}>
                                {formatDollars(cursorUsage.remaining_budget_dollars)}
                              </span>
                            </div>
                          </>
                        )}
                      </div>
                    )}
                    {cursorUsage?.note && <p className={styles.cursorNote}>{cursorUsage.note}</p>}
                    {(cursorUsage?.agents?.length ?? 0) > 0 && (
                      <div className={styles.cursorAgents}>
                        <h4>Cloud agents</h4>
                        <ul>
                          {cursorUsage!.agents!.slice(0, 8).map((agent) => (
                            <li key={agent.id}>
                              <a href={agent.url ?? "#"} target="_blank" rel="noreferrer">
                                {agent.name ?? agent.id}
                              </a>
                              <span className={styles.cursorAgentMeta}>
                                {agent.status} · {formatTokens(agent.total_tokens)} tokens
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    <button
                      type="button"
                      className={styles.btnDanger}
                      onClick={handleDisconnectCursor}
                      disabled={cursorLoading}
                    >
                      Disconnect
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
          <div className={styles.notifWrapper}>
            <button
              type="button"
              className={styles.notifBell}
              onClick={() => {
                setShowNotifications((v) => !v);
                setShowCursor(false);
              }}
              aria-label="Notifications"
            >
              🔔
              {unreadCount > 0 && (
                <span className={styles.notifCount}>{unreadCount > 99 ? "99+" : unreadCount}</span>
              )}
            </button>
            {showNotifications && (
              <div className={styles.notifDropdown}>
                <div className={styles.notifHeader}>
                  <h3>Notifications</h3>
                  {unreadCount > 0 && (
                    <button type="button" className={styles.notifMarkAll} onClick={handleMarkAllRead}>
                      Mark all read
                    </button>
                  )}
                </div>
                <ul className={styles.notifList}>
                  {notifications.length === 0 ? (
                    <li className={styles.notifEmpty}>No notifications yet</li>
                  ) : (
                    notifications.slice(0, 20).map((n) => (
                      <li key={n.id}>
                        <button
                          type="button"
                          className={`${styles.notifItem} ${!n.read ? styles.notifUnread : ""}`}
                          onClick={() => handleNotificationClick(n)}
                        >
                          <span className={styles.notifIcon}>{notificationIcon(n.type)}</span>
                          <div className={styles.notifBody}>
                            <strong>{n.title}</strong>
                            <p>{n.message}</p>
                            <time>{new Date(n.created_at).toLocaleString()}</time>
                          </div>
                        </button>
                      </li>
                    ))
                  )}
                </ul>
              </div>
            )}
          </div>
          {(openInputs.length > 0 || pendingSecrets > 0) && (
            <span className={styles.alertBadge}>
              {openInputs.length > 0 && `${openInputs.length} question${openInputs.length > 1 ? "s" : ""}`}
              {openInputs.length > 0 && pendingSecrets > 0 && " · "}
              {pendingSecrets > 0 && `${pendingSecrets} secret${pendingSecrets > 1 ? "s" : ""} needed`}
            </span>
          )}
        </div>
      </header>

      {(showCursor || showNotifications) && (
        <button
          type="button"
          className={styles.dropdownBackdrop}
          aria-label="Close menu"
          onClick={() => {
            setShowCursor(false);
            setShowNotifications(false);
          }}
        />
      )}

      {error && (
        <div className={uiStyles.errorBanner} role="alert">
          <span className={uiStyles.errorBannerBody}>{error}</span>
          <div className={uiStyles.errorActions}>
            <button
              type="button"
              className={uiStyles.errorRetry}
              onClick={() => refresh()}
            >
              Retry
            </button>
            <button
              type="button"
              className={uiStyles.errorDismiss}
              onClick={() => setError(null)}
              aria-label="Dismiss error"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {setupStatus?.api_key_required && !browserHasFactoryKey && (
        <div className={styles.apiKeyBanner}>
          <strong>Factory API key required.</strong> Open the Cursor menu → Deployment and enter the same key
          you configured on the server. Without it, the dashboard cannot reach the API (failed to fetch).
        </div>
      )}

      {setupStatus && !setupStatus.setup_complete && setupStatus.preview_host === "localhost" && (
        <section className={styles.setupBanner}>
          <div>
            <h2>Quick setup</h2>
            <p>
              No .env file required — confirm how you reach this server so live preview links work.
              Connect Cursor and lock down API access anytime from the Cursor menu.
            </p>
          </div>
          <form className={styles.setupForm} onSubmit={handleCompleteSetup}>
            <label>
              Server hostname
              <input
                type="text"
                value={setupPreviewHost}
                onChange={(e) => setSetupPreviewHost(e.target.value)}
                placeholder="192.168.1.50 or factory.example.com"
              />
            </label>
            <label>
              API key (optional)
              <input
                type="password"
                value={setupApiKey}
                onChange={(e) => setSetupApiKey(e.target.value)}
                placeholder="Leave empty for open access"
                autoComplete="off"
              />
            </label>
            <button type="submit" className={styles.btnPrimary} disabled={cursorLoading}>
              Save &amp; continue
            </button>
          </form>
        </section>
      )}

      <div className={styles.body}>
        <aside
          className={`${styles.sidebar} ${mobilePanel !== "projects" ? styles.mobileHidden : ""}`}
        >
          <div className={styles.sidebarHeader}>
            <h2>Projects</h2>
          </div>
          <ul className={styles.projectList}>
            {initialLoading ? (
              <ProjectListSkeleton count={3} />
            ) : (
              projects.map((p) => (
                <li key={p.id}>
                  <button
                    className={p.id === selectedId ? styles.projectActive : styles.projectBtn}
                    onClick={() => selectProject(p.id)}
                  >
                    <span className={styles.projectName}>{p.name}</span>
                    <span className={styles.projectMeta}>
                      <span className={styles.stateTag}
                        style={{ background: STATE_COLORS[p.state] ?? "#6b7280" }}
                      >
                        {p.state.replace(/_/g, " ")}
                      </span>
                      {p.repo_url && (
                        <span className={styles.repoTag} title={p.repo_url}>
                          {repoLabel(p.repo_url)}
                        </span>
                      )}
                      {resolvePreviewUrl(p.preview_url) && (
                        <a
                          href={resolvePreviewUrl(p.preview_url)!}
                          target="_blank"
                          rel="noreferrer"
                          className={styles.previewLink}
                          onClick={(e) => e.stopPropagation()}
                          title="Open live preview"
                        >
                          ↗
                        </a>
                      )}
                    </span>
                  </button>
                </li>
              ))
            )}
            {!initialLoading && projects.length === 0 && (
              <EmptyState
                compact
                icon="📁"
                title="No projects yet"
                description="Describe what you want to build in the form below — discovery starts automatically."
                action={
                  <button type="button" className={styles.btnSecondary} onClick={focusCreateForm}>
                    Create your first project
                  </button>
                }
              />
            )}
          </ul>

          <form ref={createFormRef} className={styles.createForm} onSubmit={handleCreate}>
            <h3>New project</h3>
            <input
              placeholder="e.g. Invoice Manager"
              value={newName}
              onChange={(e) => {
                setNewName(e.target.value);
                if (createFormErrors.name) {
                  setCreateFormErrors((prev) => ({ ...prev, name: undefined }));
                }
              }}
              required
              maxLength={PROJECT_NAME_MAX}
              aria-invalid={Boolean(createFormErrors.name)}
              className={inputInvalidClass(!!createFormErrors.name)}
            />
            <FieldError message={createFormErrors.name} />
            <textarea
              placeholder="Describe what to build: a Docker-deployable web app with REST API..."
              value={newDesc}
              onChange={(e) => {
                setNewDesc(e.target.value);
                if (createFormErrors.description) {
                  setCreateFormErrors((prev) => ({ ...prev, description: undefined }));
                }
              }}
              rows={4}
              required
              maxLength={PROJECT_DESC_MAX}
              aria-invalid={Boolean(createFormErrors.description)}
              className={inputInvalidClass(!!createFormErrors.description)}
            />
            <FieldError message={createFormErrors.description} />
            <label className={styles.repoField}>
              GitHub repo (optional)
              <select
                value={newRepoUrl}
                onChange={(e) => setNewRepoUrl(e.target.value)}
                disabled={!cursorStatus?.connected || repoLoading}
              >
                <option value="">None — factory scaffold</option>
                {renderRepoOptions()}
              </select>
            </label>
            {!cursorStatus?.connected && (
              <p className={styles.repoHint}>
                Connect Cursor to pick repos from your GitHub account.
              </p>
            )}
            {newRepoUrl && (
              <>
                <label className={styles.repoField}>
                  Production branch
                  <input
                    type="text"
                    value={newBranch}
                    onChange={(e) => setNewBranch(e.target.value)}
                    placeholder="main"
                  />
                </label>
                <label className={styles.repoCheckbox}>
                  <input
                    type="checkbox"
                    checked={newIsolateBranch}
                    onChange={(e) => setNewIsolateBranch(e.target.checked)}
                  />
                  Develop on a separate factory branch (keeps production branch untouched)
                </label>
              </>
            )}
            <button type="submit" className={styles.btnPrimary} disabled={loading}>
              {loading ? (
                <>
                  <Spinner /> Creating…
                </>
              ) : (
                "Create project"
              )}
            </button>
          </form>
        </aside>

        <main
          className={`${styles.main} ${mobilePanel !== "status" ? styles.mobileHidden : ""}`}
        >
          {initialLoading || (selectedId && detailLoading && !detail) ? (
            <DetailSkeleton />
          ) : detail ? (
            <>
              <div className={styles.projectTop}>
                <div>
                  <h2>{detail.name}</h2>
                  <p>{detail.description}</p>
                </div>
                <div className={styles.actions}>
                  {detail.pipeline_running ? (
                    <>
                      <span className={styles.running}>
                        {agentActivity?.stop_requested ? "Stopping pipeline…" : "Pipeline running…"}
                      </span>
                      <button
                        type="button"
                        className={styles.btnDanger}
                        onClick={handleStop}
                        disabled={stoppingPipeline || agentActivity?.stop_requested}
                        title="Hard stop — cancels in-flight work on this project"
                      >
                        {stoppingPipeline || agentActivity?.stop_requested ? "Stopping…" : "Stop pipeline"}
                      </button>
                    </>
                  ) : detail.state === "REQUESTED" ? (
                    <span className={styles.running}>Starting discovery…</span>
                  ) : detail.state === "DISCOVERY" ? (
                    <span className={styles.running}>Discovery agent thinking…</span>
                  ) : detail.state === "INTAKE_PENDING" ? (
                    <button className={styles.btnPrimary} onClick={() => setTab("intake")}>
                      Complete intake form
                    </button>
                  ) : detail.pipeline_paused ? (
                    <>
                      <span className={styles.running}>Pipeline paused</span>
                      <button
                        type="button"
                        className={styles.btnPrimary}
                        onClick={handleRun}
                        disabled={loading}
                        title="Clear pause and continue the build pipeline"
                      >
                        Resume pipeline
                      </button>
                    </>
                  ) : AUTO_START_PIPELINE_STATES.has(detail.state) ? (
                    <span className={styles.running}>Build pipeline starting…</span>
                  ) : (
                    <>
                      {detail.state === "AUTONOMOUSLY_BLOCKED" && (
                        <button className={styles.btnPrimary} onClick={handleRun} disabled={loading}>
                          Resume pipeline
                        </button>
                      )}
                      {detail.state !== "PRODUCTION" && detail.state !== "AUTONOMOUSLY_BLOCKED" && (
                        <button className={styles.btnPrimary} onClick={handleRun} disabled={loading || detail.pipeline_running}>
                          {detail.state === "REVIEW" ? "Apply feedback & rebuild" : "Re-run pipeline"}
                        </button>
                      )}
                      {detail.state === "REVIEW" && (
                        <>
                          {detail.isolate_branch && detail.merge_status !== "merged" && (
                            <button
                              className={styles.btnSecondary}
                              onClick={handleMergeToMain}
                              disabled={loading}
                              title="Merge factory work branch into production"
                            >
                              Merge to main
                            </button>
                          )}
                          <button className={styles.btnSuccess} onClick={handlePromote} disabled={loading}>
                            Promote to production
                          </button>
                        </>
                      )}
                    </>
                  )}
                  <button
                    type="button"
                    className={styles.btnDanger}
                    onClick={handleDeleteProject}
                    disabled={loading || detail.pipeline_running}
                    title={
                      detail.repo_url
                        ? "Remove from factory (GitHub repo is kept)"
                        : "Delete project and local files"
                    }
                  >
                    Delete
                  </button>
                </div>
              </div>

              {detail.state === "AUTONOMOUSLY_BLOCKED" && (
                <p className={styles.repoHint}>
                  The build stopped after repeated failures
                  {detail.failed_gate ? ` at ${detail.failed_gate.replace(/_/g, " ").toLowerCase()}` : ""}.
                  Review the pipeline log, then click Resume pipeline to try again with a fresh fix budget.
                </p>
              )}

              {detail.state === "REVIEW" && !detail.pipeline_running && (
                <p className={styles.repoHint}>
                  Build passed review. Add notes or answer agent questions to request changes — the factory will
                  automatically rebuild from implementation. When you are happy with the preview, promote to production
                  or merge to main.
                </p>
              )}

              <div className={styles.meta}>
                {detail.image_tag && <span>Image: <code>{detail.image_tag}</code></span>}
                {detail.production_url && resolvePreviewUrl(detail.production_url) && (
                  <a
                    href={resolvePreviewUrl(detail.production_url)!}
                    target="_blank"
                    rel="noreferrer"
                    className={styles.prodLink}
                  >
                    Production ↗
                  </a>
                )}
              </div>

              {detail.repo_analysis && (
                <section className={styles.repoAnalysisBanner}>
                  <div>
                    <h3>Existing codebase detected</h3>
                    <p className={styles.repoHint}>
                      The factory will <strong>continue this project</strong> — extend what exists rather than
                      scaffolding from scratch. Intake questions focus on gaps and changes.
                    </p>
                    <ul className={styles.repoAnalysisMeta}>
                      {detail.repo_analysis.stack.length > 0 && (
                        <li>Stack: {detail.repo_analysis.stack.join(", ")}</li>
                      )}
                      <li>{detail.repo_analysis.source_file_count} source files scanned</li>
                      {detail.repo_analysis.has_backend && <li>Backend present</li>}
                      {detail.repo_analysis.has_frontend && <li>UI present</li>}
                      {detail.repo_analysis.has_tests && <li>Tests present</li>}
                    </ul>
                  </div>
                </section>
              )}

              <section className={styles.repoPanel}>
                <div className={styles.repoPanelHeader}>
                  <div>
                    <h3>GitHub repository</h3>
                    <p className={styles.repoHint}>
                      Link an empty or existing repo from your Cursor-connected GitHub account.
                      When branch isolation is on, agents work on a factory branch and only merge
                      to your production branch when you approve.
                    </p>
                  </div>
                  {cursorStatus?.connected && (
                    <button
                      type="button"
                      className={styles.btnSecondary}
                      onClick={() => loadGithubRepos(true)}
                      disabled={repoLoading}
                    >
                      {repoLoading ? "Loading…" : "Refresh repos"}
                    </button>
                  )}
                </div>
                <form className={styles.repoForm} onSubmit={handleSaveRepo}>
                  <label className={styles.repoField}>
                    Repository
                    <select
                      value={editRepoUrl}
                      onChange={(e) => setEditRepoUrl(e.target.value)}
                      disabled={!cursorStatus?.connected || repoLoading}
                    >
                      <option value="">None — factory scaffold</option>
                      {renderRepoOptions(editRepoUrl)}
                    </select>
                  </label>
                  <label className={styles.repoField}>
                    {editIsolateBranch ? "Production branch" : "Branch"}
                    <input
                      type="text"
                      value={editBranch}
                      onChange={(e) => setEditBranch(e.target.value)}
                      placeholder="main"
                      disabled={!editRepoUrl}
                    />
                  </label>
                  {editRepoUrl && (
                    <label className={styles.repoCheckbox}>
                      <input
                        type="checkbox"
                        checked={editIsolateBranch}
                        onChange={(e) => setEditIsolateBranch(e.target.checked)}
                      />
                      Isolate from production branch (factory work branch)
                    </label>
                  )}
                  {editRepoUrl && editIsolateBranch && detail.work_branch && (
                    <div className={styles.repoField}>
                      <span>Factory work branch</span>
                      <code className={styles.workBranch}>{detail.work_branch}</code>
                      {detail.merge_status === "merged" && (
                        <span className={styles.mergeBadge}>Merged to main</span>
                      )}
                    </div>
                  )}
                  <div className={styles.repoFormActions}>
                    <button
                      type="submit"
                      className={styles.btnPrimary}
                      disabled={loading || !repoSettingsDirty}
                    >
                      Save repository
                    </button>
                    {detail.repo_url && (
                      <a
                        href={detail.repo_url}
                        target="_blank"
                        rel="noreferrer"
                        className={styles.btnSecondary}
                      >
                        Open on GitHub ↗
                      </a>
                    )}
                  </div>
                </form>
                {!cursorStatus?.connected && (
                  <p className={styles.repoHint}>
                    Connect your Cursor API key (header menu) to browse repositories linked to your GitHub account.
                  </p>
                )}
                {repoNote && cursorStatus?.connected && (
                  <p className={styles.repoHint}>{repoNote}</p>
                )}
              </section>

              {livePreviewUrl && (
                <div className={styles.livePreview}>
                  <div className={styles.livePreviewInfo}>
                    <span className={styles.livePreviewBadge}>
                      {detail.preview_status === "running" ? "● Live" : detail.preview_status ?? "Preview"}
                    </span>
                    <div>
                      <h3>Live preview</h3>
                      <p>
                        {previewTypeLabel(detail.preview_type)}
                        {detail.pipeline_running ? " — updating as agents work" : ""}
                      </p>
                    </div>
                  </div>
                  <div className={styles.livePreviewActions}>
                    <a
                      href={livePreviewUrl}
                      target="_blank"
                      rel="noreferrer"
                      className={styles.btnPrimary}
                    >
                      Open web app ↗
                    </a>
                    {detail.preview_port && detail.preview_type !== "docker" && (
                      <span className={styles.previewPort} title="Internal process port (proxied via gateway)">
                        Internal {detail.preview_port}
                      </span>
                    )}
                  </div>
                </div>
              )}

              {progress && (
                <div className={styles.progressDigest}>
                  <div className={styles.progressHeader}>
                    <h3>What&apos;s done</h3>
                    {detail.pipeline_running && (
                      <span className={styles.running}>Building…</span>
                    )}
                  </div>
                  {progress.summary_lines.length === 0 ? (
                    <p className={styles.emptyHint}>
                      {detail.state === "PLANNING" && !detail.pipeline_running
                        ? "Build pipeline is starting — architect agent will plan the project first."
                        : detail.state === "PLANNING" || detail.pipeline_running
                          ? "Pipeline running — progress will appear here as agents work."
                          : "Pipeline not started yet — progress will appear here as agents work."}
                    </p>
                  ) : (
                    <ul className={styles.progressList}>
                      {progress.summary_lines.map((line, i) => (
                        <li key={i}>{line}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {agentActivity &&
                (agentActivity.pipeline_running ||
                  agentActivity.active_agents.length > 0 ||
                  agentActivity.activity_feed.length > 0) && (
                <div className={styles.agentActivityPanel}>
                  <div className={styles.progressHeader}>
                    <h3>Agent activity</h3>
                    {agentActivity.pipeline_running && (
                      <span className={styles.running}>Live</span>
                    )}
                  </div>

                  {agentActivity.active_agents.length > 0 ? (
                    <ul className={styles.agentActiveList}>
                      {agentActivity.active_agents.map((agent) => (
                        <li key={agent.task_id} className={styles.agentActiveItem}>
                          <div className={styles.agentActiveHeader}>
                            <span className={styles.roleBadge}>{agent.role}</span>
                            <strong>{agent.title}</strong>
                            {agent.cursor_url && (
                              <a href={agent.cursor_url} target="_blank" rel="noreferrer">
                                Open in Cursor ↗
                              </a>
                            )}
                          </div>
                          <p className={styles.agentActiveStatus}>
                            {agent.live_status
                              ? `${agent.live_status}${agent.live_detail ? ` — ${agent.live_detail}` : ""}`
                              : "Working…"}
                          </p>
                          {agent.description && (
                            <p className={styles.agentActiveDesc}>{agent.description}</p>
                          )}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className={styles.emptyHint}>
                      {detail.pipeline_running
                        ? "Agents are starting — activity will appear here shortly."
                        : "No active agents."}
                    </p>
                  )}

                  {agentActivity.activity_feed.length > 0 && (
                    <details className={styles.agentFeedDetails}>
                      <summary>Recent agent events ({agentActivity.activity_feed.length})</summary>
                      <ul className={styles.agentFeedList}>
                        {[...agentActivity.activity_feed].reverse().slice(0, 15).map((item) => (
                          <li key={item.id} className={styles.agentFeedItem}>
                            <time>{new Date(item.created_at).toLocaleTimeString()}</time>
                            <span>{item.summary}</span>
                            {item.detail && (
                              <pre className={styles.agentFeedDetail}>{item.detail}</pre>
                            )}
                            {item.cursor_url && (
                              <a href={item.cursor_url} target="_blank" rel="noreferrer">
                                View agent ↗
                              </a>
                            )}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              )}

              <div className={styles.tabs}>
                {(["overview", "intake", "guidance", "secrets", "tasks", "artifacts", "deployments", "logs"] as Tab[]).map((t) => (
                  <button
                    key={t}
                    className={tab === t ? styles.tabActive : styles.tab}
                    onClick={() => setTab(t)}
                  >
                    {t === "intake"
                      ? `Intake${detail.state === "INTAKE_PENDING" ? " •" : ""}`
                      : t === "guidance"
                        ? `Notes & Input${openInputs.length ? ` (${openInputs.length})` : ""}`
                        : t === "secrets"
                          ? `Secrets${pendingSecrets ? ` (${pendingSecrets})` : ""}`
                          : t === "tasks"
                            ? `Tasks${runningTasks.length ? ` (${runningTasks.length} active)` : ""}`
                          : t.charAt(0).toUpperCase() + t.slice(1)}
                  </button>
                ))}
              </div>

              {tab === "overview" && (
                <>
                  <div className={styles.pipeline}>
                    {PIPELINE.map((state, i) => {
                      const done = currentIdx > i;
                      const active = detail.state === state;
                      const failed = ["DIAGNOSING", "FIXING", "AUTONOMOUSLY_BLOCKED"].includes(detail.state) && i === currentIdx;
                      return (
                        <div
                          key={state}
                          className={`${styles.step} ${done ? styles.stepDone : ""} ${active ? styles.stepActive : ""} ${failed ? styles.stepFailed : ""}`}
                        >
                          <div className={styles.stepDot} />
                          <span>{state.replace(/_/g, " ")}</span>
                        </div>
                      );
                    })}
                  </div>

                  {(detail.state === "IMPLEMENTING" || pipelineSubstage?.step === "enrichment") && (
                    <div className={styles.substageTrack}>
                      <h4>Implementation substages</h4>
                      <div className={styles.substageSteps}>
                        {[
                          { id: "implement", label: "Build" },
                          { id: "unit_test", label: "Unit tests" },
                          { id: "enrichment", label: "Product enrichment" },
                        ].map((step) => {
                          const isEnrichment = step.id === "enrichment";
                          const active =
                            pipelineSubstage?.step === "enrichment"
                              ? isEnrichment
                              : detail.state === "IMPLEMENTING" &&
                                !pipelineSubstage?.step &&
                                step.id === "implement";
                          return (
                            <div
                              key={step.id}
                              className={`${styles.substageStep} ${active ? styles.substageStepActive : ""}`}
                            >
                              {step.label}
                              {isEnrichment && (
                                <span className={styles.substageMeta}>
                                  {detail.max_enrichment_passes != null
                                    ? `${detail.max_enrichment_passes} max`
                                    : `${effectiveEnrichmentPasses} max (factory default)`}
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {(enrichmentProgress || enrichmentProgressLines.length > 0) && (
                    <div className={styles.enrichmentPanel}>
                      <h4>Enrichment iterations</h4>
                      {enrichmentProgress && (
                        <p className={styles.enrichmentStatus}>
                          {enrichmentProgress.phase === "pre-review" ? "Pre-review polish" : "Autonomous enrichment"}
                          {" — "}
                          pass {enrichmentProgress.current_pass ?? enrichmentProgress.passes_completed ?? 0}
                          {" of "}
                          {enrichmentProgress.max_passes ?? effectiveEnrichmentPasses}
                          {enrichmentProgress.status ? ` (${enrichmentProgress.status})` : ""}
                        </p>
                      )}
                      {enrichmentProgressLines.length > 0 && (
                        <ul className={styles.enrichmentHistory}>
                          {enrichmentProgressLines.map((line, i) => (
                            <li key={i}>{line.replace(/^✓\s*/, "")}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}

                  <section className={styles.projectDetailsPanel}>
                    <h4>Project details</h4>
                    <form className={styles.projectDetailsForm} onSubmit={handleSaveProjectDetails}>
                      <label className={styles.repoField}>
                        Name
                        <input
                          type="text"
                          value={editProjectName}
                          onChange={(e) => {
                            setEditProjectName(e.target.value);
                            if (projectDetailsError) setProjectDetailsError(null);
                          }}
                          maxLength={PROJECT_NAME_MAX}
                          required
                        />
                      </label>
                      <label className={styles.repoField}>
                        Description
                        <textarea
                          value={editProjectDesc}
                          onChange={(e) => {
                            setEditProjectDesc(e.target.value);
                            if (projectDetailsError) setProjectDetailsError(null);
                          }}
                          rows={4}
                          maxLength={PROJECT_DESC_MAX}
                          required
                        />
                      </label>
                      {projectDetailsError && (
                        <p className={styles.fieldError}>{projectDetailsError}</p>
                      )}
                      <button
                        type="submit"
                        className={styles.btnSecondary}
                        disabled={loading || !projectDetailsDirty}
                      >
                        Save project details
                      </button>
                    </form>
                  </section>

                  <section className={styles.pipelineSettings}>
                    <h4>Pipeline settings</h4>
                    <form
                      className={styles.pipelineSettingsForm}
                      onSubmit={async (e) => {
                        e.preventDefault();
                        await handleSaveRepo(e);
                      }}
                    >
                      <label className={styles.repoField}>
                        Enrichment iterations
                        <input
                          type="number"
                          min={0}
                          max={20}
                          placeholder={`Factory default (${detail.factory_default_enrichment_passes ?? 3})`}
                          value={editEnrichmentPasses}
                          onChange={(e) => {
                            setEditEnrichmentPasses(e.target.value);
                            setEnrichmentError(null);
                          }}
                          aria-invalid={!!enrichmentError}
                          className={inputInvalidClass(!!enrichmentError)}
                        />
                      </label>
                      <FieldError message={enrichmentError ?? undefined} />
                      <p className={styles.repoHint}>
                        How many autonomous product-improvement passes run after the first working build.
                        Leave blank to use the factory default ({detail.factory_default_enrichment_passes ?? 3}).
                        Set to 0 to skip enrichment.
                      </p>
                      <button
                        type="submit"
                        className={styles.btnSecondary}
                        disabled={loading || !repoSettingsDirty}
                      >
                        Save pipeline settings
                      </button>
                    </form>
                  </section>
                </>
              )}

              {tab === "intake" && (
                <IntakePanel
                  discovery={discovery}
                  detailState={detail.state}
                  intakeAnswers={intakeAnswers}
                  loading={loading}
                  onChange={(fieldId, value) =>
                    setIntakeAnswers((prev) => ({ ...prev, [fieldId]: value }))
                  }
                  onSubmit={handleSubmitIntake}
                />
              )}

              {tab === "guidance" && (
                <div className={styles.guidancePanel}>
                  <section className={styles.guidanceSection}>
                    <h3>Your notes</h3>
                    <p className={styles.guidanceHint}>
                      Add instructions anytime — running or not. Agents read these on their next step.
                      Use &quot;Out of scope&quot; to block features.
                    </p>
                    <form className={styles.noteForm} onSubmit={handleAddNote}>
                      <select value={noteType} onChange={(e) => setNoteType(e.target.value as NoteType)}>
                        {NOTE_TYPES.map((t) => (
                          <option key={t.value} value={t.value}>{t.label}</option>
                        ))}
                      </select>
                      <textarea
                        placeholder="e.g. Don't add user auth — keep it simple. OR: Add export to CSV feature."
                        value={noteText}
                        onChange={(e) => {
                          setNoteText(e.target.value);
                          if (noteFormError) setNoteFormError(null);
                        }}
                        rows={3}
                        maxLength={NOTE_CONTENT_MAX}
                      />
                      {noteFormError && !editingNoteId && (
                        <p className={styles.fieldError}>{noteFormError}</p>
                      )}
                      <button type="submit" className={styles.btnPrimary} disabled={loading || !noteText.trim()}>
                        Add note
                      </button>
                    </form>
                    <ul className={styles.notesList}>
                      {notes.map((n) => (
                        <li key={n.id} className={styles.noteItem}>
                          {editingNoteId === n.id ? (
                            <form className={styles.noteEditForm} onSubmit={handleUpdateNote}>
                              <select
                                value={editNoteType}
                                onChange={(e) => setEditNoteType(e.target.value as NoteType)}
                              >
                                {NOTE_TYPES.map((t) => (
                                  <option key={t.value} value={t.value}>{t.label}</option>
                                ))}
                              </select>
                              <textarea
                                value={editNoteText}
                                onChange={(e) => {
                                  setEditNoteText(e.target.value);
                                  if (noteFormError) setNoteFormError(null);
                                }}
                                rows={3}
                                maxLength={NOTE_CONTENT_MAX}
                                autoFocus
                              />
                              {noteFormError && (
                                <p className={styles.fieldError}>{noteFormError}</p>
                              )}
                              <div className={styles.noteActions}>
                                <button type="submit" className={styles.btnPrimary} disabled={loading}>
                                  Save
                                </button>
                                <button
                                  type="button"
                                  className={styles.btnSecondary}
                                  onClick={cancelEditNote}
                                  disabled={loading}
                                >
                                  Cancel
                                </button>
                              </div>
                            </form>
                          ) : (
                            <>
                              <div className={styles.noteItemHeader}>
                                <span className={styles.noteTypeBadge}>{n.note_type.replace("_", " ")}</span>
                                <div className={styles.noteActions}>
                                  <button
                                    type="button"
                                    className={styles.btnSecondary}
                                    onClick={() => startEditNote(n)}
                                    disabled={loading}
                                  >
                                    Edit
                                  </button>
                                  <button
                                    type="button"
                                    className={styles.btnDanger}
                                    onClick={() => handleDeleteNote(n)}
                                    disabled={loading}
                                  >
                                    Delete
                                  </button>
                                </div>
                              </div>
                              <p>{n.content}</p>
                              <time>{new Date(n.created_at).toLocaleString()}</time>
                            </>
                          )}
                        </li>
                      ))}
                      {notes.length === 0 && (
                        <EmptyState
                          compact
                          icon="📝"
                          title="No notes yet"
                          description="Add instructions, features, or scope boundaries — agents read these on their next step."
                        />
                      )}
                    </ul>
                  </section>

                  <section className={styles.guidanceSection}>
                    <h3>Agent questions</h3>
                    <p className={styles.guidanceHint}>
                      Agents never pause the pipeline. They proceed with a default decision after
                      5 minutes if you don&apos;t respond. You can still override here.
                    </p>
                    {inputRequests.length === 0 ? (
                      <EmptyState
                        compact
                        icon="💬"
                        title="No agent questions"
                        description="Agents proceed with sensible defaults. Questions appear here when they need your input."
                      />
                    ) : (
                      <ul className={styles.inputList}>
                        {inputRequests.map((req) => (
                          <li key={req.id} className={`${styles.inputCard} ${req.status === "open" ? styles.inputOpen : ""}`}>
                            <div className={styles.inputHeader}>
                              <span className={styles.roleBadge}>{req.role}</span>
                              <span className={styles.inputStatus}>{req.status.replace("_", " ")}</span>
                            </div>
                            <p className={styles.inputQuestion}>{req.question}</p>
                            {req.context_detail && (
                              <p className={styles.inputContext}>{req.context_detail}</p>
                            )}
                            {req.options.length > 0 && (
                              <div className={styles.inputOptions}>
                                Options: {req.options.join(" · ")}
                              </div>
                            )}
                            <p className={styles.inputDefault}>
                              <strong>Proceeding with:</strong> {req.resolved_decision ?? req.default_decision}
                            </p>
                            {req.status === "open" && (
                              <div className={styles.inputRespond}>
                                <input
                                  placeholder="Your preference (optional — overrides default)"
                                  value={inputResponses[req.id] ?? ""}
                                  onChange={(e) =>
                                    setInputResponses((prev) => ({ ...prev, [req.id]: e.target.value }))
                                  }
                                />
                                <button
                                  className={styles.btnSecondary}
                                  onClick={() => handleRespondInput(req.id)}
                                  disabled={loading || !inputResponses[req.id]?.trim()}
                                >
                                  Send response
                                </button>
                                <span className={styles.inputExpiry}>
                                  Auto-decides {new Date(req.expires_at).toLocaleTimeString()}
                                </span>
                              </div>
                            )}
                            {req.human_response && (
                              <p className={styles.inputAnswer}>You said: {req.human_response}</p>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                </div>
              )}

              {tab === "secrets" && (
                <div className={styles.secretsPanel}>
                  <section className={styles.guidanceSection}>
                    <h3>Environment variables</h3>
                    <p className={styles.guidanceHint}>
                      Secrets are encrypted at rest. Agents see key names only — never values.
                      For GitHub push access, connect GitHub once in the Cursor menu (factory-wide).
                      Per-project overrides are still supported here if needed.
                    </p>

                    {(secrets?.pending_requirements.length ?? 0) > 0 && (
                      <div className={styles.pendingSecrets}>
                        <h4>Action required</h4>
                        <ul>
                          {secrets!.pending_requirements.map((req) => (
                            <li key={req.id} className={styles.pendingSecretItem}>
                              <strong>{req.key_name}</strong>
                              <p>{req.description}</p>
                              <span className={styles.pendingMeta}>Requested by {req.requested_by}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <form className={styles.secretForm} onSubmit={handleSetSecret}>
                      <div className={styles.secretFormRow}>
                        <input
                          placeholder="KEY_NAME (e.g. OPENAI_API_KEY)"
                          value={secretKey}
                          onChange={(e) => {
                            setSecretKey(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ""));
                            if (secretErrors.key) setSecretErrors((prev) => ({ ...prev, key: undefined }));
                          }}
                          aria-invalid={!!secretErrors.key}
                          className={inputInvalidClass(!!secretErrors.key)}
                        />
                        <input
                          type="password"
                          placeholder="Secret value"
                          value={secretValue}
                          onChange={(e) => {
                            setSecretValue(e.target.value);
                            if (secretErrors.value) setSecretErrors((prev) => ({ ...prev, value: undefined }));
                          }}
                          autoComplete="off"
                          aria-invalid={!!secretErrors.value}
                          className={inputInvalidClass(!!secretErrors.value)}
                        />
                      </div>
                      <FieldError message={secretErrors.key ?? secretErrors.value} />
                      <input
                        placeholder="Description (optional)"
                        value={secretDesc}
                        onChange={(e) => setSecretDesc(e.target.value)}
                      />
                      <button type="submit" className={styles.btnPrimary} disabled={loading}>
                        {loading ? (
                          <>
                            <Spinner /> Saving…
                          </>
                        ) : (
                          "Save secret"
                        )}
                      </button>
                    </form>
                    <ul className={styles.secretsList}>
                      {(secrets?.secrets ?? []).map((s) => (
                        <li
                          key={s.key_name}
                          className={`${styles.secretItem} ${s.needs_value ? styles.secretNeedsValue : ""}`}
                        >
                          <div>
                            <strong>{s.key_name}</strong>
                            <code>{s.masked_value}</code>
                            {s.needs_value && (
                              <p className={styles.secretNeedsHint}>
                                Placeholder created — enter a value above and save so preview testing can proceed.
                              </p>
                            )}
                            {s.description && <p>{s.description}</p>}
                          </div>
                          <button
                            type="button"
                            className={styles.btnDanger}
                            onClick={() => handleDeleteSecret(s.key_name)}
                            disabled={loading}
                          >
                            Remove
                          </button>
                        </li>
                      ))}
                      {(secrets?.secrets.length ?? 0) === 0 && (
                        <EmptyState
                          compact
                          icon="🔐"
                          title="No secrets configured"
                          description={
                            (secrets?.pending_requirements.length ?? 0) > 0
                              ? "Agents requested environment variables above — add values here so preview testing can proceed."
                              : "Add API keys or tokens agents need at runtime. Values are encrypted and never shown to agents."
                          }
                        />
                      )}
                    </ul>
                  </section>
                </div>
              )}

              {tab === "tasks" && (
                <div className={styles.table}>
                  {runningTasks.length > 0 && (
                    <p className={styles.parallelHint}>
                      {runningTasks.length} agent{runningTasks.length > 1 ? "s" : ""} running
                      {cursorStatus?.concurrency
                        ? ` (max ${cursorStatus.concurrency.max_parallel} parallel)`
                        : " in parallel"}
                    </p>
                  )}
                  {tasks.length === 0 ? (
                    <EmptyState
                      icon="🤖"
                      title="No agent tasks yet"
                      description="Tasks appear once discovery completes and the build pipeline starts. The factory runs agents automatically."
                      action={
                        detail.pipeline_running || AUTO_START_PIPELINE_STATES.has(detail.state) ? undefined : (
                          <button type="button" className={styles.btnPrimary} onClick={handleRun} disabled={loading}>
                            {loading ? (
                              <>
                                <Spinner /> Starting…
                              </>
                            ) : (
                              "Start pipeline"
                            )}
                          </button>
                        )
                      }
                    />
                  ) : (
                    <table>
                      <thead>
                        <tr>
                          <th>Task</th>
                          <th>Role</th>
                          <th>Status</th>
                          <th>Time</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {tasks.map((t) => {
                          const activityTask = agentActivity?.recent_tasks.find(
                            (a) => a.task_id === t.id
                          );
                          const expanded = expandedTaskId === t.id;
                          return (
                            <Fragment key={t.id}>
                              <tr>
                                <td>{t.title}</td>
                                <td><span className={styles.roleBadge}>{t.role}</span></td>
                                <td><span className={styles[`status_${t.status}`] ?? ""}>{t.status}</span></td>
                                <td>{new Date(t.created_at).toLocaleString()}</td>
                                <td>
                                  <button
                                    type="button"
                                    className={styles.btnSecondary}
                                    onClick={() => setExpandedTaskId(expanded ? null : t.id)}
                                  >
                                    {expanded ? "Hide" : "Details"}
                                  </button>
                                </td>
                              </tr>
                              {expanded && (
                                <tr className={styles.taskDetailRow}>
                                  <td colSpan={5}>
                                    <div className={styles.taskDetailPanel}>
                                      <p><strong>Description</strong> {t.description || "—"}</p>
                                      {activityTask?.live_status && (
                                        <p><strong>Live status</strong> {activityTask.live_status}</p>
                                      )}
                                      {activityTask?.output_preview && (
                                        <div>
                                          <strong>Output</strong>
                                          <pre className={styles.taskOutput}>{activityTask.output_preview}</pre>
                                        </div>
                                      )}
                                      {activityTask?.cursor_url && (
                                        <a href={activityTask.cursor_url} target="_blank" rel="noreferrer">
                                          Open Cursor agent ↗
                                        </a>
                                      )}
                                      {!activityTask?.output_preview && t.status === "RUNNING" && (
                                        <p className={styles.emptyHint}>
                                          Agent is working — check Agent activity on the overview tab for live updates.
                                        </p>
                                      )}
                                    </div>
                                  </td>
                                </tr>
                              )}
                            </Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {tab === "artifacts" && (
                <div className={styles.artifactGrid}>
                  {detail.artifacts.length === 0 ? (
                    <EmptyState
                      icon="📄"
                      title="No artifacts yet"
                      description="Plans, specs, and agent outputs will show up here as the pipeline progresses."
                    />
                  ) : (
                    detail.artifacts.map((a) => (
                      <button key={a} className={styles.artifactCard} onClick={() => viewArtifact(a)}>
                        📄 {a}
                      </button>
                    ))
                  )}
                  {artifactView && (
                    <div className={styles.modal}>
                      <div className={styles.modalContent}>
                        <div className={styles.modalHeader}>
                          <h3>{artifactView.name}</h3>
                          <button onClick={() => setArtifactView(null)}>✕</button>
                        </div>
                        <pre>{artifactView.content}</pre>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {tab === "deployments" && (
                <div className={styles.table}>
                  {deployments.length === 0 ? (
                    <EmptyState
                      icon="🚀"
                      title="No deployments yet"
                      description="Staging and production deploys appear here after Docker build and smoke tests pass."
                    />
                  ) : (
                    <table>
                      <thead>
                        <tr>
                          <th>Environment</th>
                          <th>Image</th>
                          <th>URL</th>
                          <th>Status</th>
                          <th>Deployed</th>
                        </tr>
                      </thead>
                      <tbody>
                        {deployments.map((d) => (
                          <tr key={d.id}>
                            <td><span className={d.environment === "production" ? styles.prodBadge : styles.stagingBadge}>{d.environment}</span></td>
                            <td><code>{d.image_tag}</code></td>
                            <td>{d.url ? <a href={d.url} target="_blank" rel="noreferrer">{d.url}</a> : "—"}</td>
                            <td>{d.status}</td>
                            <td>{new Date(d.created_at).toLocaleString()}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {tab === "logs" && (
                <div className={styles.logPanel}>
                  <button
                    className={styles.btnSecondary}
                    onClick={() => viewLog("pipeline.log")}
                    disabled={logLoading}
                  >
                    {logLoading ? (
                      <>
                        <Spinner /> Loading log…
                      </>
                    ) : (
                      "View pipeline.log"
                    )}
                  </button>
                  {logLoading && !logView && (
                    <div className={uiStyles.loadingCenter}>
                      <Spinner size="lg" />
                      <p>Loading pipeline log…</p>
                    </div>
                  )}
                  {logView && <pre className={styles.logContent}>{logView}</pre>}
                  {!logLoading && !logView && (
                    <EmptyState
                      compact
                      icon="📋"
                      title="No log loaded"
                      description="Open pipeline.log to inspect build output and agent activity."
                      action={
                        <button type="button" className={styles.btnSecondary} onClick={() => viewLog("pipeline.log")}>
                          View pipeline.log
                        </button>
                      }
                    />
                  )}
                </div>
              )}
            </>
          ) : (
            <div className={styles.welcome}>
              <h2>Welcome to turtSlopFactory</h2>
              <p>
                Create a project with a natural-language spec. The factory will plan, implement,
                test, build a Docker image, deploy to staging, and promote to production —
                autonomously.
              </p>
              <ol>
                <li>Describe your app in the sidebar</li>
                <li>Complete the intake form when discovery finishes</li>
                <li>Watch agents work in real time</li>
                <li>Approve promotion when review passes</li>
              </ol>
              <button type="button" className={styles.btnPrimary} onClick={focusCreateForm}>
                Create a project
              </button>
            </div>
          )}
        </main>

        <aside
          className={`${styles.events} ${mobilePanel !== "activity" ? styles.mobileHidden : ""}`}
        >
          <h2>Live events</h2>
          <ul>
            {[...events].reverse().slice(0, 50).map((ev) => (
              <li key={ev.id} className={styles.event}>
                <span className={styles.eventType}>{ev.type}</span>
                <span className={styles.eventBody}>
                  {formatEvent(ev)}
                </span>
                <time>{new Date(ev.created_at).toLocaleTimeString()}</time>
              </li>
            ))}
            {events.length === 0 && (
              <EmptyState
                compact
                icon="⚡"
                title={connected ? "Waiting for events" : "Reconnecting…"}
                description={
                  connected
                    ? "Pipeline transitions, agent updates, and deploys stream here in real time."
                    : "Live updates paused — check your connection or retry loading."
                }
                action={
                  !connected ? (
                    <button type="button" className={styles.btnSecondary} onClick={() => refresh()}>
                      Retry
                    </button>
                  ) : undefined
                }
              />
            )}
          </ul>
        </aside>
      </div>

      <nav className={styles.mobileNav} aria-label="Main navigation">
        <button
          type="button"
          className={mobilePanel === "projects" ? styles.mobileNavActive : styles.mobileNavBtn}
          onClick={() => setMobilePanel("projects")}
        >
          <span className={styles.mobileNavIcon}>📁</span>
          <span>Projects</span>
          {projects.length > 0 && (
            <span className={styles.mobileNavBadge}>{projects.length}</span>
          )}
        </button>
        <button
          type="button"
          className={mobilePanel === "status" ? styles.mobileNavActive : styles.mobileNavBtn}
          onClick={() => setMobilePanel("status")}
        >
          <span className={styles.mobileNavIcon}>📊</span>
          <span>{detail ? detail.name : "Status"}</span>
          {(openInputs.length > 0 || pendingSecrets > 0) && (
            <span className={styles.mobileNavAlert}>!</span>
          )}
        </button>
        <button
          type="button"
          className={mobilePanel === "activity" ? styles.mobileNavActive : styles.mobileNavBtn}
          onClick={() => setMobilePanel("activity")}
        >
          <span className={styles.mobileNavIcon}>⚡</span>
          <span>Activity</span>
          {events.length > 0 && (
            <span className={styles.mobileNavBadge}>{events.length > 99 ? "99+" : events.length}</span>
          )}
        </button>
      </nav>
    </div>
  );
}

function formatEvent(ev: FactoryEvent): string {
  const p = ev.payload;
  if (ev.type === "state.transition") return `${p.from ?? "—"} → ${p.to}`;
  if (ev.type === "task.status.changed") return String(p.title ?? p.status);
  if (ev.type === "test.completed") return `${p.stage}: ${p.passed ? "PASS" : "FAIL"}`;
  if (ev.type === "deployment.finished") {
    const env = String(p.environment ?? "");
    const url = String(p.url ?? "");
    return url ? `${env} preview: ${url}` : `${env} deploy`;
  }
  if (ev.type === "agent.command.started") {
    const role = String(p.role ?? "agent");
    const title = String(p.title ?? p.command ?? "task");
    return `${role} started: ${title}`;
  }
  if (ev.type === "agent.command.output") {
    const role = String(p.role ?? "agent");
    const status = String(p.status ?? "working");
    const detail = p.detail ? ` — ${String(p.detail).slice(0, 60)}` : "";
    return `${role} ${status}${detail}`;
  }
  if (ev.type === "agent.command.finished") return String(p.output ?? p.command ?? "").slice(0, 80);
  if (ev.type === "pipeline.stopped") return "Pipeline stopped by user";
  if (ev.type === "progress.updated") return `${p.title}: ${p.summary}`;
  if (ev.type === "note.added") return String(p.content ?? "").slice(0, 80);
  if (ev.type === "note.updated") return `Updated: ${String(p.content ?? "").slice(0, 72)}`;
  if (ev.type === "note.deleted") return `Deleted note: ${String(p.content ?? "").slice(0, 64)}`;
  if (ev.type === "input.requested") return String(p.question ?? "").slice(0, 80);
  if (ev.type === "input.resolved") return `${p.status}: ${p.decision ?? ""}`.slice(0, 80);
  if (ev.type === "discovery.started") return "Discovery agent started";
  if (ev.type === "discovery.completed") return `Intake form ready (${p.field_count} questions)`;
  if (ev.type === "intake.submitted") return "Scope locked in";
  if (ev.type === "notification.created") return String(p.title ?? "");
  if (ev.type === "env.required") return `Secret needed: ${p.key_name ?? ""}`;
  return JSON.stringify(p).slice(0, 80);
}
