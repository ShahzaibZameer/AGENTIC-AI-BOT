"use client";

import { useEffect, useRef, useState } from "react";
import {
  Activity, ArrowUp, Bot, CheckCircle2, Clock3, Github,
  LayoutDashboard, MessageSquare, Plug, Plus, Settings2,
  ShieldCheck, Sparkles, Workflow, Zap
} from "lucide-react";

type ChatMessage = { role: "user" | "assistant"; content: string };
type PendingApproval = {
  id: string;
  conversation_id: number;
  operation: string;
  summary: string;
  status: string;
};
type AgentFile = { filename: string; type: "docx" | "xlsx" };
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const suggestions = [
  "Help me plan a deployment workflow",
  "Create a note for my next project",
  "What automations should I set up first?"
];

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", content: "Hi! I'm your AgentOS assistant. Tell me what you'd like to accomplish. I can help plan workflows and save task notes in this starter version." }
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [files, setFiles] = useState<AgentFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [filesError, setFilesError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [approvalBusy, setApprovalBusy] = useState<string | null>(null);
  const [apiStatus, setApiStatus] = useState<"checking" | "online" | "offline">("checking");
  const uploadInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch(`${API}/health`)
      .then(r => { if (!r.ok) throw new Error("offline"); setApiStatus("online"); })
      .catch(() => setApiStatus("offline"));
    fetch(`${API}/api/approvals`)
      .then(async r => {
        if (!r.ok) throw new Error("Could not load pending approvals");
        setApprovals(await r.json());
      })
      .catch(() => setApprovals([]));
    fetch(`${API}/api/files`)
      .then(async r => {
        if (!r.ok) throw new Error("Could not load AgentOS files");
        setFiles(await r.json());
        setFilesError(null);
      })
      .catch(() => setFilesError("Files are temporarily unavailable."));
  }, []);

  async function send(text = input) {
    const message = text.trim();
    if (!message || busy) return;
    setMessages(prev => [...prev, { role: "user", content: message }]);
    setInput("");
    setBusy(true);
    try {
      const res = await fetch(`${API}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, conversation_id: conversationId })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Request failed");
      setConversationId(data.conversation_id);
      setApprovals(data.pending_approvals ?? []);
      fetch(`${API}/api/files`)
        .then(async r => {
          if (!r.ok) throw new Error("Could not refresh files");
          setFiles(await r.json());
          setFilesError(null);
        })
        .catch(() => setFilesError("Files are temporarily unavailable."));
      setMessages(prev => [...prev, { role: "assistant", content: data.response }]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      const hint = msg === "Failed to fetch"
        ? " Check that the backend is running and reachable."
        : "";
      setMessages(prev => [...prev, { role: "assistant", content: `I couldn't complete that request: ${msg}.${hint}` }]);
    } finally {
      setBusy(false);
    }
  }

  async function decideApproval(approvalId: string, action: "approve" | "reject") {
    if (approvalBusy) return;
    setApprovalBusy(approvalId);
    try {
      const res = await fetch(`${API}/api/approvals/${encodeURIComponent(approvalId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action })
      });
      const data = await res.json();
      if (!res.ok) {
        if (res.status === 409) {
          setApprovals(current => current.filter(approval => approval.id !== approvalId));
        }
        throw new Error(data.detail || "Could not update the approval");
      }
      setApprovals(current => current.filter(approval => approval.id !== approvalId));
      setMessages(current => [...current, { role: "assistant", content: data.message }]);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not update the approval";
      setMessages(current => [...current, { role: "assistant", content: `Approval error: ${message}` }]);
    } finally {
      setApprovalBusy(null);
    }
  }

  async function uploadFile(file?: File) {
    if (!file) return;
    setUploadError(null);
    if (!/\.(docx|xlsx)$/i.test(file.name)) {
      setUploadError("Choose a Word (.docx) or Excel (.xlsx) file.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setUploadError("Files must be 10 MB or smaller.");
      return;
    }

    setSelectedFile(null);
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${API}/api/files`, { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not upload the file");
      setFiles(current => [...current.filter(item => item.filename !== data.filename), {
        filename: data.filename,
        type: data.type
      }]);
      setSelectedFile(data.filename);
      setInput(`I uploaded ${data.filename}. Please inspect it and help me update it: `);
      setUploadError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not upload the file";
      setUploadError(message);
    } finally {
      setUploading(false);
      if (uploadInput.current) uploadInput.current.value = "";
    }
  }

  return (
    <main className="min-h-screen bg-[#090d16] text-slate-100 md:flex">
      <aside className="hidden w-[250px] shrink-0 border-r border-white/[0.07] bg-[#0c111d] p-5 md:flex md:flex-col">
        <div className="mb-10 flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-blue-600 shadow-lg shadow-blue-950/50"><Bot size={23}/></div>
          <div><div className="font-semibold tracking-wide">AgentOS</div><div className="text-xs text-slate-500">AUTOMATION WORKSPACE</div></div>
        </div>
        <button className="mb-7 flex items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-medium hover:bg-blue-500" onClick={() => { setMessages([{role:"assistant",content:"New conversation. What would you like me to do?"}]); setConversationId(null); setApprovals([]); }}>
          <Plus size={17}/> New task
        </button>
        <div className="mb-3 px-2 text-[10px] font-semibold uppercase tracking-[.18em] text-slate-600">Workspace</div>
        <nav className="space-y-1 text-sm">
          <Nav icon={<LayoutDashboard size={17}/>} label="Overview" active/>
          <Nav icon={<MessageSquare size={17}/>} label="AI Assistant"/>
          <Nav icon={<Workflow size={17}/>} label="Tasks"/>
          <Nav icon={<ShieldCheck size={17}/>} label="Approvals" suffix="0"/>
          <Nav icon={<Plug size={17}/>} label="Integrations"/>
        </nav>
        <div className="mb-3 mt-9 px-2 text-[10px] font-semibold uppercase tracking-[.18em] text-slate-600">Manage</div>
        <Nav icon={<Activity size={17}/>} label="Activity logs"/>
        <Nav icon={<Settings2 size={17}/>} label="Settings"/>
        <div className="mt-auto rounded-xl border border-white/[0.07] bg-white/[0.025] p-3">
          <div className="mb-2 flex items-center gap-2 text-xs font-medium"><Zap size={14} className="text-amber-400"/> Starter workspace</div>
          <div className="text-xs leading-5 text-slate-500">Connect integrations to unlock more automation capabilities.</div>
        </div>
      </aside>

      <section className="min-w-0 flex-1">
        <header className="flex h-[72px] items-center justify-between border-b border-white/[0.07] px-5 md:px-9">
          <div><div className="text-sm font-medium">Overview</div><div className="mt-1 text-xs text-slate-500">Your personal automation command center</div></div>
          <div className="flex items-center gap-3">
            <span className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs ${apiStatus === "online" ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300" : apiStatus === "offline" ? "border-rose-500/20 bg-rose-500/10 text-rose-300" : "border-white/10 text-slate-400"}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${apiStatus === "online" ? "bg-emerald-400" : apiStatus === "offline" ? "bg-rose-400" : "bg-slate-500"}`}/>{apiStatus === "online" ? "API connected" : apiStatus === "offline" ? "API offline" : "Connecting"}
            </span>
            <div className="grid h-9 w-9 place-items-center rounded-full border border-white/10 bg-slate-800 text-xs font-semibold">A</div>
          </div>
        </header>

        <div className="mx-auto max-w-6xl p-5 md:p-9">
          <div className="mb-8">
            <div className="mb-2 flex items-center gap-2 text-sm text-blue-300"><Sparkles size={15}/> AI WORKSPACE</div>
            <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">Make work happen<span className="text-blue-400">.</span></h1>
            <p className="mt-2 text-sm text-slate-400">Describe an outcome. Your agent will help you plan the steps.</p>
          </div>

          <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat icon={<Workflow size={17}/>} label="Active tasks" value="—" detail="Task tracking coming next"/>
            <Stat icon={<Clock3 size={17}/>} label="Awaiting approval" value={String(approvals.length)} detail="Review file changes below"/>
            <Stat icon={<CheckCircle2 size={17}/>} label="Completed" value="—" detail="Execution history planned"/>
            <Stat icon={<Plug size={17}/>} label="Integrations" value="0" detail="No services connected"/>
          </div>

          <div className="grid gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(260px,.8fr)]">
            <section className="overflow-hidden rounded-2xl border border-white/[0.08] bg-[#0d1422]">
              <div className="flex items-center justify-between border-b border-white/[0.07] px-5 py-4">
                <div className="flex items-center gap-3"><div className="grid h-9 w-9 place-items-center rounded-xl bg-blue-500/15 text-blue-300"><Bot size={19}/></div><div><div className="text-sm font-semibold">AgentOS Assistant</div><div className="text-xs text-slate-500">Ready to help</div></div></div>
                <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-[10px] text-emerald-300">ONLINE</span>
              </div>
              <div className="flex min-h-[330px] flex-col gap-4 p-5">
                {messages.map((m, i) => (
                  <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                    <div className={`max-w-[88%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-6 ${m.role === "user" ? "rounded-br-md bg-blue-600 text-white" : "rounded-bl-md border border-white/[0.07] bg-white/[0.035] text-slate-300"}`}>{m.content}</div>
                  </div>
                ))}
                {busy && <div className="text-xs text-blue-300 animate-pulse">Agent is thinking…</div>}
                {approvals.map(approval => (
                  <div key={approval.id} className="rounded-xl border border-amber-500/30 bg-amber-500/[0.06] p-4" role="group" aria-label="File change approval">
                    <div className="flex items-center gap-2 text-sm font-semibold text-amber-200"><ShieldCheck size={16}/> Approval required</div>
                    <p className="mt-2 text-sm leading-6 text-slate-300">{approval.summary}</p>
                    <p className="mt-1 text-xs text-slate-500">The file will not change unless you approve this request.</p>
                    <div className="mt-4 flex gap-2">
                      <button disabled={approvalBusy !== null} onClick={() => decideApproval(approval.id, "approve")} className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50">
                        {approvalBusy === approval.id ? "Working…" : "Approve change"}
                      </button>
                      <button disabled={approvalBusy !== null} onClick={() => decideApproval(approval.id, "reject")} className="rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-300 hover:bg-white/5 disabled:opacity-50">
                        Reject
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              <div className="border-t border-white/[0.07] p-4">
                <div className="flex items-end gap-2 rounded-xl border border-white/10 bg-[#080d17] p-2 focus-within:border-blue-500/50">
                  <input
                    ref={uploadInput}
                    type="file"
                    accept=".docx,.xlsx,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    className="hidden"
                    aria-label="Upload a Word or Excel file"
                    onChange={event => uploadFile(event.target.files?.[0])}
                  />
                  <button
                    type="button"
                    disabled={uploading || busy || apiStatus !== "online"}
                    onClick={() => uploadInput.current?.click()}
                    className="mb-1 grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-white/10 text-slate-300 hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40"
                    aria-label="Upload a Word or Excel file"
                    title="Upload a Word or Excel file"
                  >
                    <Plus size={19}/>
                  </button>
                  <textarea value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} placeholder="Tell your agent what you want to accomplish…" rows={2} className="max-h-36 min-h-12 flex-1 resize-y bg-transparent px-2 py-2 text-sm outline-none placeholder:text-slate-600"/>
                  <button disabled={busy || uploading || !input.trim() || apiStatus !== "online"} onClick={() => send()} className="mb-1 grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"><ArrowUp size={18}/></button>
                </div>
                {(uploading || uploadError) && (
                  <p className={`mt-2 px-1 text-xs ${uploadError ? "text-rose-300" : "text-blue-300"}`} role={uploadError ? "alert" : "status"}>
                    {uploadError ?? "Uploading file…"}
                  </p>
                )}
                {selectedFile && !uploadError && (
                  <p className="mt-2 px-1 text-xs text-slate-500">Selected file: {selectedFile}</p>
                )}
                <div className="mt-2 flex items-center justify-between px-1 text-[10px] text-slate-600"><span>Enter to send · Shift + Enter for new line</span><span>AI can make mistakes</span></div>
              </div>
            </section>

            <aside className="space-y-5">
              <div className="rounded-2xl border border-white/[0.08] bg-[#0d1422] p-5">
                <div className="mb-1 text-sm font-semibold">Your files</div>
                <p className="mb-4 text-xs leading-5 text-slate-500">Upload, update, and download your Word documents and Excel workbooks.</p>
                {filesError ? (
                  <p className="text-xs text-rose-300" role="status">{filesError}</p>
                ) : files.length === 0 ? (
                  <p className="text-xs text-slate-500">No Word or Excel files yet.</p>
                ) : (
                  <ul className="space-y-2">
                    {files.map(file => (
                      <li key={file.filename} className="flex items-center justify-between gap-3 rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2.5">
                        <span className="min-w-0 truncate text-xs text-slate-300" title={file.filename}>{file.filename}</span>
                        <div className="flex shrink-0 gap-2">
                          <button
                            type="button"
                            onClick={() => {
                              setSelectedFile(file.filename);
                              setInput(`Update ${file.filename}: `);
                            }}
                            className="rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-300 hover:bg-white/5"
                            aria-label={`Ask AgentOS to update ${file.filename}`}
                          >
                            Update
                          </button>
                          <a
                            href={`${API}/api/files/${encodeURIComponent(file.filename)}`}
                            download={file.filename}
                            className="rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-500"
                            aria-label={`Download ${file.filename}`}
                          >
                            Download
                          </a>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
                {selectedFile && (
                  <p className="mt-3 text-xs leading-5 text-slate-500">
                    Describe the exact change for {selectedFile} below. AgentOS will show you the proposed change to approve before editing.
                  </p>
                )}
              </div>
              <div className="rounded-2xl border border-white/[0.08] bg-[#0d1422] p-5">
                <div className="mb-4 text-sm font-semibold">Try asking</div>
                <div className="space-y-2">
                  {suggestions.map(s => <button key={s} onClick={() => send(s)} disabled={busy || apiStatus !== "online"} className="w-full rounded-xl border border-white/[0.07] bg-white/[0.02] p-3 text-left text-xs leading-5 text-slate-400 transition hover:border-blue-500/30 hover:bg-blue-500/[0.05] hover:text-slate-200 disabled:opacity-40">{s}</button>)}
                </div>
              </div>
              <div className="rounded-2xl border border-blue-500/20 bg-gradient-to-br from-blue-500/[0.12] to-[#0d1422] p-5">
                <div className="mb-3 grid h-9 w-9 place-items-center rounded-xl bg-blue-500/15 text-blue-300"><ShieldCheck size={19}/></div>
                <div className="text-sm font-semibold">You stay in control</div>
                <p className="mt-2 text-xs leading-5 text-slate-400">Word and Excel edits or renames wait for your approval. New files are created only in your private AgentOS files folder.</p>
              </div>
              <div className="rounded-2xl border border-white/[0.08] bg-[#0d1422] p-5">
                <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><Plug size={16}/> Integrations</div>
                <div className="space-y-3 text-xs text-slate-400">
                  <Integration icon={<Github size={15}/>} name="GitHub" state="Not connected"/>
                  <Integration icon={<MessageSquare size={15}/>} name="Telegram" state="Not connected"/>
                  <Integration icon={<Activity size={15}/>} name="Google Drive" state="Not connected"/>
                </div>
              </div>
            </aside>
          </div>
          <footer className="mt-8 text-center text-[11px] text-slate-600">AgentOS MVP · Built for controlled automation</footer>
        </div>
      </section>
    </main>
  );
}

function Nav({icon,label,active=false,suffix}:{icon:React.ReactNode;label:string;active?:boolean;suffix?:string}) {
  return <div className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm ${active ? "bg-blue-500/10 text-blue-300" : "text-slate-500 hover:bg-white/[0.03] hover:text-slate-200"}`}>{icon}<span>{label}</span>{suffix && <span className="ml-auto text-xs text-slate-600">{suffix}</span>}</div>;
}
function Stat({icon,label,value,detail}:{icon:React.ReactNode;label:string;value:string;detail:string}) {
  return <div className="rounded-xl border border-white/[0.08] bg-[#0d1422] p-4"><div className="mb-4 flex items-center justify-between text-slate-500"><span className="text-xs">{label}</span><span className="text-blue-300">{icon}</span></div><div className="text-2xl font-semibold">{value}</div><div className="mt-1 text-[10px] text-slate-600">{detail}</div></div>;
}
function Integration({icon,name,state}:{icon:React.ReactNode;name:string;state:string}) {
  return <div className="flex items-center gap-2"><span className="text-slate-500">{icon}</span><span>{name}</span><span className="ml-auto text-[10px] text-slate-600">{state}</span></div>;
}
