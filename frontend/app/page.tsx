"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/use-toast";
import { ThemeToggle } from "@/components/ThemeToggle";
import {
  ScanFace,
  Camera,
  Loader2,
  CheckCircle2,
  XCircle,
  LogIn,
  LogOut,
  AlertCircle,
  Shield,
  LayoutDashboard,
  RefreshCw,
  Zap,
  Users2,
  X,
} from "lucide-react";
import Link from "next/link";
import api from "@/lib/axios";
import axios from "axios";

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:5000").replace(/\/$/, "");
if (typeof window !== "undefined") {
  console.log("[Config] NEXT_PUBLIC_API_URL:", process.env.NEXT_PUBLIC_API_URL ?? "(not set — using localhost fallback)");
  console.log("[Config] API_BASE resolved to:", API_BASE);
}

type ScanState = "idle" | "scanning" | "success" | "error";
type ScanMode = "group" | "single";

interface GroupResult {
  name: string;
  action: "check_in" | "check_out" | "skipped";
  time?: string;
  status?: string;
  message?: string;
}

interface GroupResponse {
  results: GroupResult[];
  unrecognized: number;
  message: string;
}

interface SingleResponse {
  message: string;
}

interface LatestAttendanceItem {
  id: string;
  userId: string;
  userName: string;
  date: string;
  checkIn: string;
  checkOut: string | null;
  status: string;
}

/** Draw a rounded rectangle path on a canvas context */
function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

export default function Home() {
  const [scanState, setScanState] = useState<ScanState>("idle");
  const scanMode: ScanMode = "group";
  const [autoScanEnabled, setAutoScanEnabled] = useState(false);
  const [resultMessage, setResultMessage] = useState("");
  const [groupResults, setGroupResults] = useState<GroupResult[]>([]);
  const [unrecognizedCount, setUnrecognizedCount] = useState(0);
  const [healthStatus, setHealthStatus] = useState<"idle" | "loading" | "ok" | "error">("idle");
  const [healthMessage, setHealthMessage] = useState("");
  const [latestAttendance, setLatestAttendance] = useState<LatestAttendanceItem[]>([]);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [facesInFrame, setFacesInFrame] = useState(0);
  const [showModal, setShowModal] = useState(false);
  const [modalProgress, setModalProgress] = useState(100);

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);
  const captureAndScanRef = useRef<() => void>(() => {});
  const { toast } = useToast();

  // Set srcObject after the <video> element mounts (state update is async)
  useEffect(() => {
    if (stream && videoRef.current) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);

  // Real-time face bounding-box overlay using Chrome/Edge FaceDetector API
  useEffect(() => {
    if (!stream || typeof window === "undefined") return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const win = window as any;
    if (!("FaceDetector" in win)) return;

    const detector = new win.FaceDetector({ fastMode: true, maxDetectedFaces: 10 });
    let active = true;

    const loop = async () => {
      if (!active) return;
      const video = videoRef.current;
      const canvas = overlayRef.current;

      if (!video || !canvas || video.readyState < 2) {
        rafRef.current = requestAnimationFrame(loop);
        return;
      }

      const vW = video.videoWidth;
      const vH = video.videoHeight;
      const dW = video.clientWidth;
      const dH = video.clientHeight;

      if (vW === 0 || vH === 0) { rafRef.current = requestAnimationFrame(loop); return; }

      // Map from video-native coords → displayed pixels (object-cover scaling)
      const scale = Math.max(dW / vW, dH / vH);
      const offX = (dW - vW * scale) / 2;
      const offY = (dH - vH * scale) / 2;

      canvas.width = dW;
      canvas.height = dH;
      const ctx = canvas.getContext("2d");
      if (!ctx) { rafRef.current = requestAnimationFrame(loop); return; }
      ctx.clearRect(0, 0, dW, dH);

      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const faces: any[] = await detector.detect(video);
        setFacesInFrame(faces.length);

        const pad = 14;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        faces.forEach((face: any) => {
          const { left, top, width, height } = face.boundingBox;
          const x = left * scale + offX - pad;
          const y = top * scale + offY - pad;
          const w = width * scale + pad * 2;
          const h = height * scale + pad * 2;

          // Glowing border
          ctx.shadowColor = "rgba(52,211,153,0.55)";
          ctx.shadowBlur = 14;
          ctx.strokeStyle = "rgba(52,211,153,0.95)";
          ctx.lineWidth = 2;
          roundRect(ctx, x, y, w, h, 8);
          ctx.stroke();

          // Label badge
          ctx.shadowBlur = 0;
          ctx.fillStyle = "rgba(52,211,153,0.88)";
          roundRect(ctx, x, y - 22, 90, 18, 4);
          ctx.fill();
          ctx.fillStyle = "#fff";
          ctx.font = "bold 10px system-ui,sans-serif";
          ctx.fillText("Face Detected", x + 6, y - 8);
        });
      } catch { /* ignore per-frame errors */ }

      rafRef.current = requestAnimationFrame(loop);
    };

    rafRef.current = requestAnimationFrame(loop);
    return () => {
      active = false;
      cancelAnimationFrame(rafRef.current);
      setFacesInFrame(0);
    };
  }, [stream]);

  // Auto-dismiss modal + shrink progress bar over 5 s
  useEffect(() => {
    if (!showModal) {
      setModalProgress(100);
      return;
    }
    setModalProgress(100);
    // Trigger CSS transition on next tick
    const startT = setTimeout(() => setModalProgress(0), 50);
    const dismissT = setTimeout(() => setShowModal(false), 5050);
    return () => { clearTimeout(startT); clearTimeout(dismissT); };
  }, [showModal]);

  const startCamera = useCallback(async () => {
    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: 640, height: 480 },
      });
      setStream(mediaStream);
    } catch {
      toast({
        title: "Camera Error",
        description: "Could not access camera. Please allow camera permissions.",
        variant: "destructive",
      });
    }
  }, [toast]);

  const stopCamera = useCallback(() => {
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      setStream(null);
    }
  }, [stream]);

  const fetchHealthcheck = async () => {
    setHealthStatus("loading");
    const url = `${API_BASE}/health`;
    console.log("[Health] Checking:", url);

    const attempt = async (): Promise<boolean> => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 8000); // 8s for Render cold-start
      try {
        const res = await fetch(url, {
          method: "GET",
          cache: "no-store",
          signal: controller.signal,
        });
        clearTimeout(timer);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        console.log("[Health] Response:", data);
        return data?.status === "ok";
      } catch (err) {
        clearTimeout(timer);
        throw err;
      }
    };

    // Retry once to handle Render cold-start spin-up delay
    for (let i = 0; i < 2; i++) {
      try {
        const ok = await attempt();
        if (ok) {
          setHealthStatus("ok");
          setHealthMessage("Service available");
          return;
        }
        setHealthStatus("error");
        setHealthMessage("Unexpected response");
        return;
      } catch (err) {
        console.warn(`[Health] Attempt ${i + 1} failed:`, err);
        if (i < 1) await new Promise((r) => setTimeout(r, 3000)); // wait 3s before retry
      }
    }

    setHealthStatus("error");
    setHealthMessage("Backend unavailable");
  };

  const fetchLatestAttendance = async () => {
    try {
      const res = await axios.get<LatestAttendanceItem[]>(`${API_BASE}/api/public/latest-attendance?limit=7`);
      setLatestAttendance(res.data);
    } catch {
      setLatestAttendance([]);
    }
  };

  useEffect(() => {
    fetchHealthcheck();
    fetchLatestAttendance();
    // refresh every 30s lightly
    const timer = setInterval(() => {
      fetchLatestAttendance();
    }, 30000);
    return () => clearInterval(timer);
  }, []);

  const resetResults = () => {
    setScanState("idle");
    setResultMessage("");
    setGroupResults([]);
    setUnrecognizedCount(0);
  };

  useEffect(() => {
    if (!autoScanEnabled || !stream || scanState !== "idle") return;
    if (facesInFrame === 0) return;

    const timer = window.setTimeout(() => {
      captureAndScanRef.current();
    }, 1200);

    return () => window.clearTimeout(timer);
  }, [autoScanEnabled, facesInFrame, scanState, stream]);

  const captureImage = (): string | null => {
    if (!videoRef.current || !canvasRef.current) return null;
    const canvas = canvasRef.current;
    const video = videoRef.current;
    
    // PERF: Optimize image size for faster transmission and processing
    const maxWidth = 640;
    const maxHeight = 480;
    const videoWidth = video.videoWidth;
    const videoHeight = video.videoHeight;
    
    // Scale down if larger than max dimensions
    let width = videoWidth;
    let height = videoHeight;
    if (width > maxWidth || height > maxHeight) {
      const ratio = Math.min(maxWidth / width, maxHeight / height);
      width = Math.round(width * ratio);
      height = Math.round(height * ratio);
    }
    
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0, width, height);
    // PERF: Use 0.75 quality for faster transmission while maintaining face detection accuracy
    return canvas.toDataURL("image/jpeg", 0.75);
  };

  const captureAndScan = async () => {
    const imageData = captureImage();
    if (!imageData) return;

    setScanState("scanning");
    setResultMessage("");
    setGroupResults([]);
    setUnrecognizedCount(0);
    setShowModal(false);

    try {
      if (scanMode === "group") {
        const res = await api.post<GroupResponse>("/api/multi-attendance", {
          image: imageData,
        });
        const { results, unrecognized, message } = res.data;
        setScanState("success");
        setResultMessage(message);
        setGroupResults(results);
        setUnrecognizedCount(unrecognized);
        setShowModal(true);
        stopCamera();
      } else {
        const res = await api.post<SingleResponse>("/api/user/mark-attendance", {
          image: imageData,
        });
        setScanState("success");
        setResultMessage(res.data.message);
        stopCamera();
        toast({ title: "Attendance marked", description: res.data.message });
      }
    } catch (error: unknown) {
      setScanState("error");
      const err = error as { response?: { data?: { error?: string } } };
      const msg =
        err?.response?.data?.error ||
        (scanMode === "group"
          ? "No registered faces recognized. Try again."
          : "Face not recognized. Try again.");
      setResultMessage(msg);
      toast({ title: "Recognition Failed", description: msg, variant: "destructive" });
    }
  };

  captureAndScanRef.current = captureAndScan;

  const liveHint =
    scanMode === "group"
      ? facesInFrame > 0
        ? `${facesInFrame} face${facesInFrame > 1 ? "s" : ""} detected - tap Scan`
        : "Position face(s) in frame, then tap Scan"
      : facesInFrame > 0
      ? "Face detected - tap Scan"
      : "Position one face in frame, then tap Scan";

  return (
    <div className="h-screen overflow-hidden flex flex-col bg-background">

      {/* ── Success / Result Modal ── */}
      {showModal && groupResults.length > 0 && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="relative w-full max-w-sm rounded-2xl border bg-background shadow-2xl overflow-hidden">
            {/* Auto-dismiss progress bar */}
            <div className="h-1 bg-muted">
              <div
                className="h-full bg-primary"
                style={{
                  width: `${modalProgress}%`,
                  transition: modalProgress === 0 ? "width 5s linear" : "none",
                }}
              />
            </div>

            {/* Header */}
            <div className="flex items-center gap-3 px-5 pt-5 pb-4">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-emerald-100 dark:bg-emerald-900/60">
                <CheckCircle2 className="h-6 w-6 text-emerald-600 dark:text-emerald-400" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-bold text-base">Attendance Recorded!</p>
                <p className="text-xs text-muted-foreground mt-0.5 truncate">{resultMessage}</p>
              </div>
              <button
                onClick={() => setShowModal(false)}
                className="rounded-lg p-1.5 hover:bg-muted transition-colors shrink-0"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Per-user cards */}
            <div className="px-5 pb-3 space-y-2 max-h-64 overflow-y-auto">
              {groupResults.map((r, i) => (
                <div key={i} className="flex items-center gap-3 rounded-xl bg-muted/40 px-4 py-3">
                  <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${
                    r.action === "check_in"
                      ? "bg-emerald-100 dark:bg-emerald-900/60"
                      : r.action === "check_out"
                      ? "bg-blue-100 dark:bg-blue-900/60"
                      : "bg-amber-100 dark:bg-amber-900/60"
                  }`}>
                    {r.action === "check_in"
                      ? <LogIn className="h-4.5 w-4.5 text-emerald-600 dark:text-emerald-400" />
                      : r.action === "check_out"
                      ? <LogOut className="h-4.5 w-4.5 text-blue-600 dark:text-blue-400" />
                      : <AlertCircle className="h-4.5 w-4.5 text-amber-500" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-semibold text-sm truncate">{r.name}</p>
                    <p className={`text-xs font-medium mt-0.5 ${
                      r.action === "check_in"
                        ? "text-emerald-600 dark:text-emerald-400"
                        : r.action === "check_out"
                        ? "text-blue-600 dark:text-blue-400"
                        : "text-amber-500"
                    }`}>
                      {r.action === "check_in"
                        ? "✓ Checked In Successfully"
                        : r.action === "check_out"
                        ? "✓ Checked Out Successfully"
                        : r.message || "Session skipped"}
                    </p>
                  </div>
                  {r.time && (
                    <span className="text-xs text-muted-foreground shrink-0">{r.time}</span>
                  )}
                </div>
              ))}
              {unrecognizedCount > 0 && (
                <p className="text-xs text-center text-muted-foreground pt-1">
                  + {unrecognizedCount} unrecognized face{unrecognizedCount > 1 ? "s" : ""} in frame
                </p>
              )}
            </div>

            {/* Actions */}
            <div className="flex gap-2 px-5 pb-5 pt-2">
              <Button
                variant="outline"
                size="sm"
                className="flex-1"
                onClick={() => { setShowModal(false); resetResults(); startCamera(); }}
              >
                <RefreshCw className="mr-2 h-3.5 w-3.5" />
                Scan Again
              </Button>
              <Button size="sm" className="flex-1" onClick={() => setShowModal(false)}>
                Done
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Top Navigation */}
      <header className="flex h-14 shrink-0 items-center justify-between border-b bg-background/95 px-6 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary shadow-sm">
            <ScanFace className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="text-lg font-bold tracking-tight">FaceTrack</span>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Link href="/login">
            <Button variant="outline" size="sm" className="gap-2 h-8">
              <Shield className="h-3.5 w-3.5" />
              Portal Login
            </Button>
          </Link>
        </div>
      </header>

      {/* Two-column layout */}
      <div className="flex flex-1 overflow-hidden">

        {/* ── Left Panel ── */}
        <aside className="flex w-[340px] shrink-0 flex-col gap-4 border-r bg-muted/30 p-5 overflow-y-auto">

          <div>
            <h1 className="text-xl font-bold tracking-tight">Live Attendance</h1>
            <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
              One smart stream. No separate modes. Detects all faces and auto-checks in/out.
            </p>
          </div>



          <div className="space-y-3">
            <div className="flex items-center gap-3 rounded-lg border bg-background px-3 py-2.5 shadow-sm">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-emerald-100 dark:bg-emerald-900/60">
                <Users2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
              </div>
              <div>
                <p className="text-xs font-semibold">{scanMode === "group" ? "Multi-Face Detection" : "Single-Face Detection"}</p>
                <p className="text-xs text-muted-foreground">
                  {scanMode === "group" ? "Scan one or many users at once" : "Scan one user quickly"}
                </p>
              </div>
            </div>
            <div className="flex items-center justify-between rounded-lg border bg-background px-3 py-2.5 shadow-sm">
              <div className="flex items-center gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-blue-100 dark:bg-blue-900/60">
                  <Zap className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                </div>
                <div>
                  <p className="text-xs font-semibold">Auto Check-In / Check-Out</p>
                  <p className="text-xs text-muted-foreground">Smart detection based on your status</p>
                </div>
              </div>
              <span className="bg-indigo-100 text-indigo-700 text-[10px] font-semibold px-2 py-1 rounded-full">
                {scanMode.toUpperCase()}
              </span>
            </div>
            <div className="rounded-lg border bg-background p-2 text-xs">
              <div className="flex items-center justify-between mb-2">
                <p className="font-medium">Auto-scan</p>
                <Badge variant={autoScanEnabled ? "success" : "secondary"} className="text-[10px]">
                  {autoScanEnabled ? "Enabled" : "Disabled"}
                </Badge>
              </div>
              <p className="text-muted-foreground text-[11px]">
                When enabled, attendance will trigger automatically after face(s) are detected for 1.2s.
              </p>
              <Button
                variant={autoScanEnabled ? "destructive" : "default"}
                size="sm"
                className="mt-2 w-full"
                onClick={() => setAutoScanEnabled((x) => !x)}
              >
                {autoScanEnabled ? "Disable Auto-scan" : "Enable Auto-scan"}
              </Button>
            </div>
          </div>

          <div className="rounded-xl border bg-background p-3 shadow-sm mt-3">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold">Backend Health</p>
              <Badge
                variant={
                  healthStatus === "ok"
                    ? "success"
                    : healthStatus === "loading"
                    ? "secondary"
                    : "destructive"
                }
                className="text-[10px]"
              >
                {healthStatus === "loading" ? "Checking..." : healthStatus === "ok" ? "Healthy" : healthStatus === "error" ? "Offline" : "Idle"}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mb-2">{healthMessage || "Public endpoints available"}</p>
            <Button size="sm" className="w-full" onClick={fetchHealthcheck}>
              Refresh Health
            </Button>
          </div>

          <div className="rounded-xl border bg-background p-3 shadow-sm mt-3">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold">Latest Attendance</p>
              <Button variant="outline" size="sm" onClick={fetchLatestAttendance}>
                Refresh
              </Button>
            </div>
            {latestAttendance.length === 0 ? (
              <p className="text-xs text-muted-foreground">No recent attendance.</p>
            ) : (
              <div className="space-y-1 max-h-40 overflow-y-auto">
                {latestAttendance.map((item) => (
                  <div key={item.id} className="rounded-lg border p-1.5">
                    <p className="text-[11px] font-semibold">{item.userName}</p>
                    <p className="text-[10px] text-muted-foreground">
                      {item.date} {item.checkIn} {item.checkOut ? `- ${item.checkOut}` : ""} • {item.status}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Sidebar results (visible after modal is closed) */}
          {scanState === "success" && (groupResults.length > 0 || !!resultMessage) && !showModal && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2 rounded-lg bg-emerald-50 dark:bg-emerald-950/60 px-3 py-2">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                <p className="text-xs font-semibold text-emerald-800 dark:text-emerald-200 truncate">{resultMessage}</p>
              </div>
              {groupResults.length > 0 ? (
                <div className="space-y-1.5">
                  {groupResults.map((r, i) => (
                    <div key={i} className="flex items-center justify-between rounded-lg border bg-background px-3 py-2">
                      <div className="flex items-center gap-2">
                        {r.action === "check_in"
                          ? <LogIn className="h-3.5 w-3.5 text-emerald-600" />
                          : r.action === "check_out"
                          ? <LogOut className="h-3.5 w-3.5 text-blue-600" />
                          : <AlertCircle className="h-3.5 w-3.5 text-amber-500" />}
                        <span className="text-sm font-medium truncate max-w-[120px]">{r.name}</span>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {r.time && <span className="text-xs text-muted-foreground">{r.time}</span>}
                        <Badge
                          variant={r.action === "check_in" ? "success" : r.action === "check_out" ? "default" : "warning"}
                          className="text-xs px-1.5"
                        >
                          {r.action === "check_in" ? "In" : r.action === "check_out" ? "Out" : "Skip"}
                        </Badge>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="rounded-lg border bg-background px-3 py-2 text-xs text-muted-foreground">
                  Single-face scan completed successfully.
                </p>
              )}
              <Button
                variant="outline"
                size="sm"
                className="w-full"
                onClick={() => { resetResults(); startCamera(); }}
              >
                <RefreshCw className="mr-2 h-3.5 w-3.5" />
                Scan Again
              </Button>
            </div>
          )}

          {scanState === "error" && (
            <div className="space-y-2">
              <div className="flex items-start gap-2 rounded-lg bg-red-50 dark:bg-red-950/60 px-3 py-2">
                <XCircle className="h-4 w-4 mt-0.5 shrink-0 text-red-600 dark:text-red-400" />
                <p className="text-xs font-medium text-red-800 dark:text-red-200">{resultMessage}</p>
              </div>
              <Button
                variant="outline"
                size="sm"
                className="w-full"
                onClick={() => { resetResults(); startCamera(); }}
              >
                <RefreshCw className="mr-2 h-3.5 w-3.5" />
                Try Again
              </Button>
            </div>
          )}

          <div className="flex-1" />

          {/* Portal links */}
          <div className="space-y-2 border-t pt-4">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Portals</p>
            <Link
              href="/login"
              className="flex items-center gap-3 rounded-lg border bg-background px-3 py-3 hover:bg-muted/60 transition-colors group"
            >
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted group-hover:bg-primary/10 transition-colors">
                <LayoutDashboard className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium">User Portal</p>
                <p className="text-xs text-muted-foreground">View your attendance history</p>
              </div>
              <LogIn className="h-3.5 w-3.5 text-muted-foreground/50 group-hover:text-primary transition-colors" />
            </Link>
            <Link
              href="/login"
              className="flex items-center gap-3 rounded-lg border bg-background px-3 py-3 hover:bg-muted/60 transition-colors group"
            >
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 group-hover:bg-primary/20 transition-colors">
                <Shield className="h-4 w-4 text-primary" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium">Admin Portal</p>
                <p className="text-xs text-muted-foreground">Manage users &amp; reports</p>
              </div>
              <LogIn className="h-3.5 w-3.5 text-muted-foreground/50 group-hover:text-primary transition-colors" />
            </Link>
          </div>
        </aside>

        {/* ── Right Panel — Camera ── */}
        <main className="flex flex-1 flex-col gap-3 p-5">

          {/* Camera label row */}
          <div className="flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2">
              <ScanFace className="h-4 w-4 text-primary" />
              <span className="text-sm font-semibold">Live Camera Feed</span>
              <Badge variant="secondary" className="text-[10px] uppercase tracking-wide">
                {scanMode}
              </Badge>
            </div>
            {stream && scanState === "idle" && (
              <div className="flex items-center gap-2">
                {facesInFrame > 0 && (
                  <Badge variant="success" className="text-xs">
                    {facesInFrame} face{facesInFrame > 1 ? "s" : ""} detected
                  </Badge>
                )}
                <div className="flex items-center gap-1.5">
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                  </span>
                  <span className="text-xs text-emerald-600 dark:text-emerald-400 font-medium">Live</span>
                </div>
              </div>
            )}
          </div>

          {/* Camera viewport */}
          <div className="relative flex-1 overflow-hidden rounded-xl border bg-muted shadow-inner min-h-0">
            {stream ? (
              <>
                <video
                  ref={videoRef}
                  autoPlay
                  playsInline
                  muted
                  className="absolute inset-0 h-full w-full object-cover"
                />
                {/* Face detection bounding-box overlay canvas */}
                <canvas
                  ref={overlayRef}
                  className="absolute inset-0 h-full w-full pointer-events-none"
                />
              </>
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-4 text-muted-foreground">
                <div className="flex h-20 w-20 items-center justify-center rounded-full bg-muted-foreground/10">
                  <Camera className="h-9 w-9" />
                </div>
                <div className="text-center space-y-1">
                  <p className="font-semibold">Camera Inactive</p>
                  <p className="text-sm text-muted-foreground/70">Click <strong>Start Camera</strong> below to begin</p>
                </div>
              </div>
            )}

            {/* Scanning overlay */}
            {scanState === "scanning" && (
              <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-black/60 backdrop-blur-sm">
                <div className="flex flex-col items-center gap-3 text-white">
                  <div className="relative h-16 w-16">
                    <div className="absolute inset-0 rounded-full border-4 border-white/20 border-t-white animate-spin" />
                    <ScanFace className="absolute inset-0 m-auto h-7 w-7" />
                  </div>
                  <p className="text-sm font-semibold">Scanning faces…</p>
                  <p className="text-xs text-white/60">Hold still while we analyse the frame</p>
                </div>
              </div>
            )}

            {/* Guide brackets when live and idle */}
            {stream && scanState === "idle" && (
              <div className="absolute inset-0 pointer-events-none">
                <div className="absolute top-4 left-4 h-7 w-7 border-t-2 border-l-2 border-white/40 rounded-tl" />
                <div className="absolute top-4 right-4 h-7 w-7 border-t-2 border-r-2 border-white/40 rounded-tr" />
                <div className="absolute bottom-14 left-4 h-7 w-7 border-b-2 border-l-2 border-white/40 rounded-bl" />
                <div className="absolute bottom-14 right-4 h-7 w-7 border-b-2 border-r-2 border-white/40 rounded-br" />
                <div className="absolute bottom-4 left-0 right-0 flex justify-center">
                  <span className={`rounded-full px-3 py-1 text-xs font-medium text-white backdrop-blur-sm transition-colors ${
                    facesInFrame > 0 ? "bg-emerald-600/80" : "bg-black/50"
                  }`}>
                    {liveHint}
                  </span>
                </div>
              </div>
            )}

            {/* Success overlay (shown until modal opens) */}
            {scanState === "success" && !showModal && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 rounded-xl bg-emerald-900/60 backdrop-blur-sm">
                <CheckCircle2 className="h-14 w-14 text-emerald-300" />
                <p className="text-lg font-bold text-white">Attendance Marked!</p>
                <p className="text-sm text-white/70">See results in the left panel</p>
              </div>
            )}

            {/* Error overlay */}
            {scanState === "error" && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 rounded-xl bg-red-900/60 backdrop-blur-sm">
                <XCircle className="h-14 w-14 text-red-300" />
                <p className="text-lg font-bold text-white">Not Recognised</p>
                <p className="text-sm text-white/70">See details in the left panel</p>
              </div>
            )}
          </div>

          <canvas ref={canvasRef} className="hidden" />

          {/* Action buttons */}
          <div className="flex gap-3 shrink-0">
            {!stream ? (
              <Button onClick={startCamera} className="flex-1 h-11 text-sm font-semibold" size="lg">
                <Camera className="mr-2 h-4 w-4" />
                Start Camera
              </Button>
            ) : (
              <>
                <Button
                  onClick={captureAndScan}
                  className="flex-1 h-11 text-sm font-semibold"
                  size="lg"
                  disabled={scanState === "scanning"}
                >
                  {scanState === "scanning" ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <ScanFace className="mr-2 h-4 w-4" />
                  )}
                  {scanState === "scanning"
                    ? "Scanning..."
                    : scanMode === "group"
                    ? "Scan & Mark Group"
                    : "Scan & Mark Single"}
                </Button>
                <Button
                  variant="outline"
                  size="lg"
                  className="h-11 px-5"
                  onClick={() => { stopCamera(); resetResults(); }}
                >
                  Stop
                </Button>
              </>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
