"use client";

import { useState, useEffect, useRef } from "react";

interface LogMessage {
  id: string;
  status: string;
  message: string;
  timestamp: string;
}

export default function Home() {
  const [url, setUrl] = useState("https://the-internet.herokuapp.com/login");
  const [objective, setObjective] = useState("Log into the application using username 'tomsmith' and password 'SuperSecretPassword!'");
  const [isRunning, setIsRunning] = useState(false);
  const [logs, setLogs] = useState<LogMessage[]>([]);
  const [currentStep, setCurrentStep] = useState<number | null>(null);
  const [generatedPlaywrightCode, setGeneratedPlaywrightCode] = useState<string | null>(null);
  
  const socketRef = useRef<WebSocket | null>(null);
  const logEndRef = useRef<HTMLDivElement | null>(null);

  const exportToPlaywright = () => {
  if (!generatedPlaywrightCode) return;
  
  const blob = new Blob([generatedPlaywrightCode], { type: "text/typescript" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `autonomous-run.spec.ts`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

  const exportToJSON = () => {
  if (logs.length === 0) return;

  // Build a structured report payload
  const reportData = {
    testSuiteName: "HealFlow AI Autonomous Run",
    executionTimestamp: new Date().toISOString(),
    targetUrl: url,
    configuredObjective: objective,
    finalStatus: logs.some(log => log.message.includes("✅ Objective Achieved")) ? "PASSED" : "FAILED_OR_INCOMPLETE",
    rawExecutionStream: logs
  };

  // Create a blob and trigger a browser download
  const blob = new Blob([JSON.stringify(reportData, null, 2)], { type: "application/json" });
  const downloadUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = downloadUrl;
  
  // Create a clean filename format: test-report-2026-07-01.json
  const dateStr = new Date().toISOString().split('T')[0];
  link.download = `healflow-report-${dateStr}.json`;
  
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(downloadUrl);
};


  // Auto-scroll logs terminal window to the bottom on active streams
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  const addLog = (status: string, message: string) => {
    const newLog: LogMessage = {
      id: Math.random().toString(36).substring(7),
      status,
      message,
      timestamp: new Date().toLocaleTimeString(),
    };
    setLogs((prev) => [...prev, newLog]);
  };

  const startAgentStream = () => {
    if (!url || !objective) return alert("Please fill out both target parameters!");
    
    setIsRunning(true);
    setLogs([]);
    setCurrentStep(null);
    addLog("info", "🔌 Opening connection pipeline to automation server...");

    // Initialize native browser WebSocket connecting to our FastAPI instance
    const socket = new WebSocket("ws://localhost:8000/ws/run-agent");
    socketRef.current = socket;

    socket.onopen = () => {
      addLog("info", "🚀 Handshake completed. Deploying testing directives...");
      // Send execution instructions object as stringified JSON packet
      socket.send(JSON.stringify({ url, objective }));
    };

  socket.onmessage = (event) => {
  const packet = jsonParseSafe(event.data);
  if (!packet) return;

  switch (packet.status) {
    case "info":
    case "thinking":
    case "action_success":
    case "action_failed":
    case "error":
      addLog(packet.status, packet.message);
      break;
    case "step_start":
      setCurrentStep(packet.step);
      addLog("step", `🎬 Starting Execution Framework Step ${packet.step}`);
      break;
    case "decision":
      const decision = packet.data;
      addLog(
        "decision",
        `💡 AI Action: [${decision.action.toUpperCase()}] -> Element: ${decision.elementId || "N/A"}\nReason: ${decision.reason}`
      );
      break;
    case "completed":
      addLog("completed", packet.message);
      setIsRunning(false);
      // ✂️ REMOVED socket.close(); FROM HERE SO THE BACKEND CAN SEND THE CODE PACKET
      break;
    
    case "code_export_ready":
      // Now this hook will catch the code safely!
      setGeneratedPlaywrightCode(packet.playwright_code);
      break;
  }
};

    socket.onclose = () => {
      addLog("info", "🔒 Pipeline connection disconnected.");
      setIsRunning(false);
    };

    socket.onerror = () => {
      addLog("error", "⚠️ Network pipeline error encountered.");
      setIsRunning(false);
    };
  };

  const jsonParseSafe = (str: string) => {
    try { return JSON.parse(str); } catch { return null; }
  };

  const getLogStyles = (status: string) => {
    switch (status) {
      case "error": case "action_failed": return "text-red-400 font-semibold";
      case "action_success": return "text-emerald-400 font-medium";
      case "thinking": return "text-amber-400 italic animate-pulse";
      case "decision": return "text-sky-300 bg-sky-950/40 p-2 rounded my-1 whitespace-pre-wrap border border-sky-900/50";
      case "step": return "text-indigo-300 font-bold border-b border-indigo-900/30 pb-1 mt-2";
      case "completed": return "text-teal-300 bg-teal-950 font-bold p-3 rounded my-2 border border-teal-800 text-center uppercase tracking-wide";
      default: return "text-slate-300";
    }
  };

  return (
    <main className="min-h-screen p-8 max-w-5xl mx-auto flex flex-col gap-6">
      {/* Header Banner */}
      <header className="border-b border-slate-800 pb-4">
        <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-sky-400 via-indigo-400 to-purple-500 bg-clip-text text-transparent">
          HealFlow AI ⚡
        </h1>
        <p className="text-slate-400 text-sm mt-1">
          Autonomous Self-Healing Playwright Execution Hub
        </p>
      </header>

      {/* Target Settings Configuration Panels */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="flex flex-col gap-2">
          <label className="text-xs font-bold uppercase tracking-wider text-slate-400">Target Webpage Application Address</label>
          <input
            type="text"
            className="bg-slate-900 border border-slate-800 rounded p-2.5 text-sm focus:outline-none focus:border-sky-500 text-slate-200 transition-colors"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={isRunning}
          />
        </div>
        <div className="flex flex-col gap-2">
          <label className="text-xs font-bold uppercase tracking-wider text-slate-400">Automation Framework Objective</label>
          <input
            type="text"
            className="bg-slate-900 border border-slate-800 rounded p-2.5 text-sm focus:outline-none focus:border-sky-500 text-slate-200 transition-colors"
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            disabled={isRunning}
          />
        </div>
      </div>

      {/* Execution Deployment Controls */}
      <button
        onClick={startAgentStream}
        disabled={isRunning}
        className={`w-full py-3 rounded font-bold text-sm tracking-wide transition-all uppercase ${
          isRunning
            ? "bg-indigo-950 text-indigo-400 border border-indigo-800 cursor-not-allowed"
            : "bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white font-bold shadow-lg shadow-indigo-500/10 active:scale-[0.99]"
        }`}
      >
        {isRunning ? `Agent Active — Processing Sequence (Step ${currentStep || 1})` : "Deploy Autonomous Test Suite"}
      </button>
      <button
    onClick={exportToJSON}
    disabled={logs.length === 0}
    className="bg-slate-800 hover:bg-slate-700 disabled:opacity-40 disabled:hover:bg-slate-800 text-slate-300 font-medium py-3 px-6 rounded-lg border border-slate-700 transition duration-200 flex items-center justify-center"
    title="Export execution run to JSON file"
  >
    📦 Export JSON Report
  </button>
  {generatedPlaywrightCode && (
  <button
    onClick={exportToPlaywright}
    className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 transition-colors font-medium flex items-center gap-2"
  >
    ⚙️ Export Playwright Test
  </button>
)}
      <div className="flex gap-4">
  


  
</div>

      {/* Output Stream Logging Live Terminal */}
      <div className="flex flex-col flex-1 bg-black/50 border border-slate-800 rounded-lg overflow-hidden min-h-[400px]">
        <div className="bg-slate-900/80 px-4 py-2 border-b border-slate-800 flex justify-between items-center text-xs text-slate-400 font-mono">
          <span>CONSOLE LOG OUTPUT STREAM</span>
          {isRunning && <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-ping" />}
        </div>
        
        <div className="p-4 flex flex-col gap-2 font-mono text-sm overflow-y-auto flex-1 max-h-[500px]">
          {logs.length === 0 ? (
            <div className="text-slate-600 italic text-center my-auto">
              System idling. Configure metrics above and click run.
            </div>
          ) : (
            logs.map((log) => (
              <div key={log.id} className="flex gap-4 items-start leading-relaxed animate-fade-in">
                <span className="text-slate-600 select-none text-xs pt-0.5">{log.timestamp}</span>
                <pre className={`flex-1 whitespace-pre-wrap ${getLogStyles(log.status)}`}>
                  {log.message}
                </pre>
              </div>
            ))
          )}
          <div ref={logEndRef} />
        </div>
      </div>
    </main>
  );
}