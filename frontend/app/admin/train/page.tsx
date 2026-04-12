"use client";

import { useEffect, useState, useCallback } from "react";
import { useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { useToast } from "@/components/ui/use-toast";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Brain, Loader2, CheckCircle2, UserCheck, Link2, Camera, ScanFace } from "lucide-react";
import api from "@/lib/axios";
import type { TrainingUser } from "@/lib/types";

export default function TrainModelPage() {
  const [users, setUsers] = useState<TrainingUser[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isTraining, setIsTraining] = useState(false);
  const [progress, setProgress] = useState(0);
  const [trainingComplete, setTrainingComplete] = useState(false);
  const [captureOpen, setCaptureOpen] = useState(false);
  const [usernameInput, setUsernameInput] = useState("");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [isCapturing, setIsCapturing] = useState(false);
  const [capturedImages, setCapturedImages] = useState<string[]>([]);
  const [captureProgress, setCaptureProgress] = useState(0);
  const [activeUsername, setActiveUsername] = useState("");

  const TARGET_CAPTURES = 20;
  const CAPTURE_INTERVAL_MS = 350;

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const captureTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const { toast } = useToast();

  const fetchUntrainedUsers = useCallback(async () => {
    try {
      setIsLoading(true);
      const res = await api.get("/api/admin/untrained-users");
      setUsers(res.data);
    } catch {
      toast({
        title: "Error",
        description: "Failed to fetch untrained users",
        variant: "destructive",
      });
    } finally {
      setIsLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    fetchUntrainedUsers();
  }, [fetchUntrainedUsers]);

  useEffect(() => {
    if (stream && videoRef.current) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);

  const stopCaptureSession = useCallback(() => {
    if (captureTimerRef.current) {
      clearInterval(captureTimerRef.current);
      captureTimerRef.current = null;
    }
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      setStream(null);
    }
    setIsCapturing(false);
  }, [stream]);

  useEffect(() => {
    return () => stopCaptureSession();
  }, [stopCaptureSession]);

  const captureFrame = () => {
    if (!videoRef.current || !canvasRef.current) return null;
    const video = videoRef.current;
    const canvas = canvasRef.current;

    if (video.videoWidth === 0 || video.videoHeight === 0) return null;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;

    ctx.drawImage(video, 0, 0);
    return canvas.toDataURL("image/jpeg", 0.9);
  };

  const completeCaptureAndTrain = async (images: string[], username: string) => {
    setIsTraining(true);
    setProgress(10);

    try {
      const captureRes = await api.post("/api/admin/capture-training-images", {
        username,
        images,
        replace: true,
      });

      setProgress(65);

      const userId = captureRes?.data?.userId;
      if (!userId) {
        throw new Error("Could not resolve user id for training");
      }

      await api.post("/api/admin/train", { userId });
      setProgress(100);
      setTrainingComplete(true);

      toast({
        title: "Training Complete",
        description: `Captured ${images.length} images and trained ${captureRes?.data?.username || username}.`,
      });

      setCaptureOpen(false);
      setCapturedImages([]);
      setCaptureProgress(0);
      setUsernameInput("");
      setActiveUsername("");
      fetchUntrainedUsers();
    } catch (error: unknown) {
      setProgress(0);
      const err = error as { response?: { data?: { error?: string } }; message?: string };
      toast({
        title: "Training Failed",
        description: err?.response?.data?.error || err?.message || "Failed during capture/training flow.",
        variant: "destructive",
      });
    } finally {
      setIsTraining(false);
    }
  };

  const beginAutoCapture = async () => {
    const username = usernameInput.trim();
    if (!username) {
      toast({
        title: "Username required",
        description: "Enter the username before starting camera capture.",
        variant: "destructive",
      });
      return;
    }

    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: 640, height: 480 },
      });
      setStream(mediaStream);
      setCapturedImages([]);
      setCaptureProgress(0);
      setActiveUsername(username);
      setIsCapturing(true);

      // Small warmup before first frame
      setTimeout(() => {
        captureTimerRef.current = setInterval(() => {
          const frame = captureFrame();
          if (!frame) return;

          setCapturedImages((prev) => {
            if (prev.length >= TARGET_CAPTURES) return prev;
            const next = [...prev, frame];
            setCaptureProgress(Math.round((next.length / TARGET_CAPTURES) * 100));

            if (next.length >= TARGET_CAPTURES) {
              stopCaptureSession();
              void completeCaptureAndTrain(next, username);
            }
            return next;
          });
        }, CAPTURE_INTERVAL_MS);
      }, 400);
    } catch {
      toast({
        title: "Camera Error",
        description: "Could not access camera. Please allow permissions.",
        variant: "destructive",
      });
    }
  };

  const openTrainingFlow = () => {
    setCaptureOpen(true);
    setTrainingComplete(false);
    setProgress(0);
    setCapturedImages([]);
    setCaptureProgress(0);
    setActiveUsername("");
    if (!usernameInput && users.length > 0) {
      setUsernameInput(users[0].name);
    }
  };

  const closeCaptureDialog = () => {
    stopCaptureSession();
    setCaptureOpen(false);
    setCapturedImages([]);
    setCaptureProgress(0);
    setActiveUsername("");
  };

  const handleTrain = async () => {
    if (isTraining || isCapturing) return;

    if (users.length === 0) {
      toast({
        title: "No untrained users",
        description: "All users are already trained.",
      });
      return;
    }

    openTrainingFlow();
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Train Model</h1>
        <p className="text-muted-foreground">
          Enter username, auto-capture 20 photos with camera, then train model automatically
        </p>
      </div>

      <Dialog open={captureOpen} onOpenChange={(open) => (!open ? closeCaptureDialog() : setCaptureOpen(true))}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ScanFace className="h-5 w-5 text-primary" />
              Capture Training Dataset
            </DialogTitle>
            <DialogDescription>
              Enter username, then camera auto-captures {TARGET_CAPTURES} images for dataset creation.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                value={usernameInput}
                onChange={(e) => setUsernameInput(e.target.value)}
                placeholder="Enter exact username (e.g. BRIJESH KUMAR)"
                disabled={isCapturing || isTraining}
              />
            </div>

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

            {(isCapturing || capturedImages.length > 0) && (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">
                    Capturing for: <strong>{activeUsername || usernameInput.trim()}</strong>
                  </span>
                  <span className="font-medium">
                    {capturedImages.length}/{TARGET_CAPTURES}
                  </span>
                </div>
                <Progress value={captureProgress} className="h-2" />
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={closeCaptureDialog} disabled={isTraining}>
              Cancel
            </Button>
            {!isCapturing ? (
              <Button onClick={beginAutoCapture} disabled={isTraining}>
                {isTraining ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Processing...
                  </>
                ) : (
                  <>
                    <Camera className="mr-2 h-4 w-4" />
                    Open Camera & Capture
                  </>
                )}
              </Button>
            ) : (
              <Button variant="destructive" onClick={stopCaptureSession}>
                Stop Capture
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Training Control */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Brain className="h-5 w-5 text-primary" />
            Model Training
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-muted-foreground">
                {users.length} untrained user(s) found
              </p>
            </div>
            <Button
              onClick={handleTrain}
              disabled={isTraining || users.length === 0}
              className="min-w-[160px]"
            >
              {isTraining ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Training...
                </>
              ) : trainingComplete ? (
                <>
                  <CheckCircle2 className="mr-2 h-4 w-4" />
                  Complete
                </>
              ) : (
                <>
                  <Brain className="mr-2 h-4 w-4" />
                  Start Training
                </>
              )}
            </Button>
          </div>

          {(isTraining || trainingComplete) && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">Progress</span>
                <span className="font-medium">{progress}%</span>
              </div>
              <Progress value={progress} className="h-2" />
            </div>
          )}
        </CardContent>
      </Card>

      {/* Upload Instructions */}
      <Card className="border-blue-200 bg-blue-50 dark:border-blue-900 dark:bg-blue-950/30">
        <CardHeader>
          <CardTitle className="text-base text-blue-900 dark:text-blue-100 flex items-center gap-2">
            <Link2 className="h-4 w-4" />
            New training flow
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-blue-800 dark:text-blue-200 space-y-2">
          <p>1. Click <strong>Start Training</strong></p>
          <p>2. Enter the <strong>username</strong> to train</p>
          <p>3. Camera opens and captures <strong>20 photos automatically</strong></p>
          <p>4. Images are saved to dataset and training starts for that user</p>
          <p className="text-xs text-blue-700 dark:text-blue-300 mt-3">Tip: Keep face centered and look slightly left/right naturally while capturing.</p>
        </CardContent>
      </Card>

      {/* Untrained Users List */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <UserCheck className="h-5 w-5 text-primary" />
            Untrained Users
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="flex items-center gap-4">
                  <Skeleton className="h-10 w-10 rounded-full" />
                  <div className="space-y-1.5">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-3 w-24" />
                  </div>
                </div>
              ))}
            </div>
          ) : users.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <CheckCircle2 className="h-12 w-12 text-emerald-500 mb-3" />
              <p className="text-lg font-medium">All users are trained!</p>
              <p className="text-sm text-muted-foreground">
                No pending training required.
              </p>
            </div>
          ) : (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Department</TableHead>
                    <TableHead className="text-center">Images</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((user) => {
                    const count = user.images || 0;
                    const hasEnoughImages = count >= 3;
                    return (
                      <TableRow key={user.id}>
                        <TableCell className="font-medium">{user.name}</TableCell>
                        <TableCell>{user.email}</TableCell>
                        <TableCell>{user.department}</TableCell>
                        <TableCell className="text-center">
                          <Badge
                            variant={
                              hasEnoughImages ? "success" : count > 0 ? "warning" : "secondary"
                            }
                          >
                            {count} photo{count !== 1 ? "s" : ""}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
