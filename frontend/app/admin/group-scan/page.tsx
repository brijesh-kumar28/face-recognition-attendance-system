"use client";

import { useState, useRef, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/use-toast";
import {
  ScanFace,
  Camera,
  Loader2,
  CheckCircle2,
  XCircle,
  Users,
  LogIn,
  LogOut,
  AlertCircle,
} from "lucide-react";
import api from "@/lib/axios";

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

export default function AdminGroupScanPage() {
  const [scanning, setScanning] = useState(false);
  const [results, setResults] = useState<GroupResult[]>([]);
  const [unrecognized, setUnrecognized] = useState(0);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { toast } = useToast();

  const startCamera = useCallback(async () => {
    try {
      const ms = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: 1280, height: 720 },
      });
      setStream(ms);
      if (videoRef.current) {
        videoRef.current.srcObject = ms;
        videoRef.current.play().catch(() => {});
      }
      setResults([]);
      setMessage("");
      setError("");
    } catch {
      toast({
        title: "Camera Error",
        description: "Could not access camera.",
        variant: "destructive",
      });
    }
  }, [toast]);

  const stopCamera = useCallback(() => {
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      setStream(null);
    }
  }, [stream]);

  const scan = async () => {
    if (!videoRef.current || !canvasRef.current) return;
    setScanning(true);
    setResults([]);
    setMessage("");
    setError("");

    const canvas = canvasRef.current;
    const video = videoRef.current;
    let width = video.videoWidth || 1280;
    let height = video.videoHeight || 720;

    if (width === 0 || height === 0) {
      setError("Camera frame not ready. Please wait a moment and try again.");
      setScanning(false);
      return;
    }

    // PERF: Optimize canvas size for faster processing
    const maxWidth = 800;
    const maxHeight = 600;
    if (width > maxWidth || height > maxHeight) {
      const ratio = Math.min(maxWidth / width, maxHeight / height);
      width = Math.round(width * ratio);
      height = Math.round(height * ratio);
    }

    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      setError("Canvas is not available.");
      setScanning(false);
      return;
    }

    ctx.drawImage(video, 0, 0, width, height);
    // PERF: Use 0.75 quality for faster transmission while maintaining face detection accuracy
    const imageData = canvas.toDataURL("image/jpeg", 0.75);

    if (!imageData || imageData.length < 100) {
      setError("Unable to capture image. Please try again.");
      setScanning(false);
      return;
    }

    try {
      const res = await api.post<GroupResponse>("/api/multi-attendance", {
        image: imageData,
      });
      setResults(res.data.results);
      setUnrecognized(res.data.unrecognized);
      setMessage(res.data.message);
      toast({ title: "Success", description: res.data.message });
    } catch (err: unknown) {
      const e = err as { response?: { data?: { error?: string } } };
      const msg = e?.response?.data?.error || "No faces recognized.";
      setError(msg);
      toast({ title: "Failed", description: msg, variant: "destructive" });
    } finally {
      setScanning(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">
          Group Attendance Scan
        </h1>
        <p className="text-muted-foreground">
          Point the camera at a group — all recognised faces will be checked
          in&nbsp;/&nbsp;out at once
        </p>
      </div>

      <div className="mx-auto max-w-3xl space-y-4">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Users className="h-5 w-5 text-primary" />
              Multi-Face Scanner
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Camera */}
            <div className="relative overflow-hidden rounded-lg bg-muted aspect-video flex items-center justify-center">
              {stream ? (
                <video
                  ref={videoRef}
                  autoPlay
                  playsInline
                  muted
                  className="w-full h-full object-cover rounded-lg"
                />
              ) : (
                <div className="flex flex-col items-center gap-3 text-muted-foreground">
                  <Camera className="h-16 w-16" />
                  <p className="text-sm">Camera preview will appear here</p>
                </div>
              )}

              {scanning && (
                <div className="absolute inset-0 flex items-center justify-center bg-black/50 rounded-lg">
                  <div className="flex flex-col items-center gap-3 text-white">
                    <Loader2 className="h-10 w-10 animate-spin" />
                    <p className="text-sm font-medium">
                      Scanning all faces...
                    </p>
                  </div>
                </div>
              )}

              {stream && !scanning && results.length === 0 && !error && (
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                  <div className="w-[85%] h-[75%] border-2 border-dashed border-emerald-500/60 rounded-xl flex items-end justify-center pb-3">
                    <span className="text-xs text-emerald-400 font-medium bg-black/40 px-2 py-1 rounded">
                      All faces in frame will be scanned
                    </span>
                  </div>
                </div>
              )}
            </div>

            <canvas ref={canvasRef} className="hidden" />

            {/* Success */}
            {message && results.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 rounded-lg bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200 p-3">
                  <CheckCircle2 className="h-5 w-5 shrink-0" />
                  <p className="text-sm font-medium">{message}</p>
                </div>

                <div className="divide-y rounded-lg border">
                  {results.map((r, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between px-4 py-3"
                    >
                      <div className="flex items-center gap-3">
                        {r.action === "check_in" ? (
                          <LogIn className="h-4 w-4 text-emerald-600" />
                        ) : r.action === "check_out" ? (
                          <LogOut className="h-4 w-4 text-blue-600" />
                        ) : (
                          <AlertCircle className="h-4 w-4 text-amber-500" />
                        )}
                        <span className="font-medium">{r.name}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        {r.time && (
                          <span className="text-xs text-muted-foreground">
                            {r.time}
                          </span>
                        )}
                        <Badge
                          variant={
                            r.action === "check_in"
                              ? "success"
                              : r.action === "check_out"
                              ? "default"
                              : "warning"
                          }
                        >
                          {r.action === "check_in"
                            ? "Checked In"
                            : r.action === "check_out"
                            ? "Checked Out"
                            : "Skipped"}
                        </Badge>
                      </div>
                    </div>
                  ))}
                </div>

                {unrecognized > 0 && (
                  <p className="text-xs text-muted-foreground text-center">
                    {unrecognized} unrecognized face
                    {unrecognized > 1 ? "s" : ""} in image
                  </p>
                )}
              </div>
            )}

            {/* Error */}
            {error && (
              <div className="flex items-center gap-2 rounded-lg p-3 bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-200">
                <XCircle className="h-5 w-5 shrink-0" />
                <p className="text-sm font-medium">{error}</p>
              </div>
            )}

            {/* Buttons */}
            <div className="flex gap-3">
              {!stream ? (
                <Button onClick={startCamera} className="flex-1">
                  <Camera className="mr-2 h-4 w-4" />
                  Start Camera
                </Button>
              ) : (
                <>
                  <Button
                    onClick={scan}
                    className="flex-1"
                    disabled={scanning}
                  >
                    {scanning ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <ScanFace className="mr-2 h-4 w-4" />
                    )}
                    Scan All Faces
                  </Button>
                  <Button variant="outline" onClick={stopCamera}>
                    Stop
                  </Button>
                </>
              )}
            </div>

            {(results.length > 0 || error) && (
              <Button
                variant="outline"
                className="w-full"
                onClick={() => {
                  setResults([]);
                  setMessage("");
                  setError("");
                  startCamera();
                }}
              >
                <Camera className="mr-2 h-4 w-4" />
                Scan Again
              </Button>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
