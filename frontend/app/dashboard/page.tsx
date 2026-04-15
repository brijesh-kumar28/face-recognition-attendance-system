"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import Link from "next/link";
import { StatsCard } from "@/components/StatsCard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/use-toast";
import {
  CalendarCheck,
  CheckCircle2,
  XCircle,
  Flame,
  Clock,
  Camera,
  ScanFace,
  Loader2,
  AlertCircle,
} from "lucide-react";
import api from "@/lib/axios";
import type { UserStats, AttendanceRecord } from "@/lib/types";

export default function UserDashboard() {
  const [stats, setStats] = useState<UserStats | null>(null);
  const [recentRecords, setRecentRecords] = useState<AttendanceRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [isMarking, setIsMarking] = useState(false);
  const [markMessage, setMarkMessage] = useState("");
  const [markError, setMarkError] = useState("");

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { toast } = useToast();

  const fetchData = useCallback(async () => {
    try {
      const [statsRes, recordsRes] = await Promise.all([
        api.get("/api/user/stats"),
        api.get("/api/user/attendance", { params: { limit: 5 } }),
      ]);
      setStats(statsRes.data);
      setRecentRecords(recordsRes.data);
    } catch {
      setStats({
        todayStatus: "not_marked",
        totalPresent: 0,
        totalAbsent: 0,
        streak: 0,
      });
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (stream && videoRef.current) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);

  useEffect(() => {
    return () => {
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
      }
    };
  }, [stream]);

  const startCamera = useCallback(async () => {
    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: 640, height: 480 },
      });
      setStream(mediaStream);
      setMarkError("");
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

  const captureImage = (): string | null => {
    if (!videoRef.current || !canvasRef.current) return null;
    const canvas = canvasRef.current;
    const video = videoRef.current;

    // PERF: Optimize image size for faster transmission and processing
    const maxWidth = 640;
    const maxHeight = 480;
    let width = video.videoWidth;
    let height = video.videoHeight;
    
    // Scale down if larger than max dimensions
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

  const handleMarkAttendance = async () => {
    const imageData = captureImage();
    if (!imageData) return;

    setIsMarking(true);
    setMarkMessage("");
    setMarkError("");

    try {
      const res = await api.post<{ message: string }>("/api/user/mark-attendance", {
        image: imageData,
      });

      setMarkMessage(res.data.message);
      toast({ title: "Attendance updated", description: res.data.message });
      stopCamera();
      await fetchData();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { error?: string } } };
      const msg = err?.response?.data?.error || "Failed to mark attendance.";
      setMarkError(msg);
      toast({ title: "Failed", description: msg, variant: "destructive" });
    } finally {
      setIsMarking(false);
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-muted-foreground">Your attendance overview</p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="p-6">
                <Skeleton className="h-4 w-24 mb-3" />
                <Skeleton className="h-8 w-16" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  const getStatusDisplay = () => {
    switch (stats?.todayStatus) {
      case "present":
        return {
          label: "Present",
          variant: "success" as const,
          icon: CheckCircle2,
        };
      case "absent":
        return {
          label: "Absent",
          variant: "destructive" as const,
          icon: XCircle,
        };
      default:
        return {
          label: "Not Marked",
          variant: "secondary" as const,
          icon: Clock,
        };
    }
  };

  const statusDisplay = getStatusDisplay();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">Your attendance overview</p>
      </div>

      <Card>
        <CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-medium">Need full check-in and check-out history?</p>
            <p className="text-sm text-muted-foreground">
              Open My Records to view all your attendance activity.
            </p>
          </div>
          <Link href="/dashboard/records">
            <Button>View Full History</Button>
          </Link>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Quick Face Attendance</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="relative overflow-hidden rounded-lg border bg-muted aspect-video flex items-center justify-center">
            {stream ? (
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className="h-full w-full object-cover"
              />
            ) : (
              <div className="flex flex-col items-center gap-2 text-muted-foreground">
                <Camera className="h-8 w-8" />
                <p className="text-xs">Camera preview appears here</p>
              </div>
            )}
          </div>

          <canvas ref={canvasRef} className="hidden" />

          <div className="flex gap-3">
            {!stream ? (
              <Button onClick={startCamera} className="flex-1">
                <Camera className="mr-2 h-4 w-4" />
                Start Camera
              </Button>
            ) : (
              <>
                <Button onClick={handleMarkAttendance} className="flex-1" disabled={isMarking}>
                  {isMarking ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <ScanFace className="mr-2 h-4 w-4" />
                  )}
                  {isMarking ? "Marking..." : "Scan & Mark"}
                </Button>
                <Button variant="outline" onClick={stopCamera}>
                  Stop
                </Button>
              </>
            )}
          </div>

          {markMessage && (
            <div className="flex items-center gap-2 rounded-lg bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200 p-3">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <p className="text-sm font-medium">{markMessage}</p>
            </div>
          )}

          {markError && (
            <div className="flex items-center gap-2 rounded-lg p-3 bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-200">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <p className="text-sm font-medium">{markError}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatsCard
          title="Today Status"
          value={statusDisplay.label}
          icon={statusDisplay.icon}
          description={new Date().toLocaleDateString("en-US", {
            weekday: "long",
            year: "numeric",
            month: "long",
            day: "numeric",
          })}
        />
        <StatsCard
          title="Total Present"
          value={stats?.totalPresent ?? 0}
          icon={CalendarCheck}
          description="This month"
          trend={{ value: 5, isPositive: true }}
        />
        <StatsCard
          title="Total Absent"
          value={stats?.totalAbsent ?? 0}
          icon={XCircle}
          description="This month"
        />
        <StatsCard
          title="Streak"
          value={`${stats?.streak ?? 0} days`}
          icon={Flame}
          description="Consecutive present days"
        />
      </div>

      {/* Recent Records */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Recent Attendance</CardTitle>
        </CardHeader>
        <CardContent>
          {recentRecords.length === 0 ? (
            <p className="text-center text-muted-foreground py-8">
              No attendance records yet.
            </p>
          ) : (
            <div className="space-y-3">
              {recentRecords.map((record) => (
                <div
                  key={record.id}
                  className="flex items-center justify-between rounded-lg border p-3"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10">
                      <CalendarCheck className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                      <p className="text-sm font-medium">{record.date}</p>
                      <p className="text-xs text-muted-foreground">
                        {record.checkIn}
                        {record.checkOut ? ` - ${record.checkOut}` : ""}
                      </p>
                    </div>
                  </div>
                  <Badge
                    variant={
                      record.status === "present"
                        ? "success"
                        : record.status === "late"
                        ? "warning"
                        : "destructive"
                    }
                  >
                    {record.status}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
