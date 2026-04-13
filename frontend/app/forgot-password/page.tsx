"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Mail } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/use-toast";
import api from "@/lib/axios";

export default function ForgotPasswordPage() {
  const router = useRouter();
  const { toast } = useToast();
  const [email, setEmail] = useState("");
  const [resetToken, setResetToken] = useState("");
  const [tokenInput, setTokenInput] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [requestLoading, setRequestLoading] = useState(false);
  const [resetLoading, setResetLoading] = useState(false);
  const [requestDone, setRequestDone] = useState(false);

  const getErrorMessage = (error: unknown, fallback: string) => {
    if (
      typeof error === "object" &&
      error !== null &&
      "response" in error &&
      typeof (error as { response?: unknown }).response === "object" &&
      (error as { response?: { data?: unknown } }).response?.data &&
      typeof (error as { response: { data: { error?: unknown } } }).response.data.error ===
        "string"
    ) {
      return (error as { response: { data: { error: string } } }).response.data.error;
    }

    if (error instanceof Error) {
      return error.message;
    }

    return fallback;
  };

  const handleRequestReset = async (e: React.FormEvent) => {
    e.preventDefault();
    setRequestLoading(true);

    try {
      const res = await api.post<{ message: string; resetToken?: string }>(
        "/api/auth/forgot-password",
        { email }
      );

      const token = res.data.resetToken || "";
      setResetToken(token);
      setTokenInput(token);
      setRequestDone(true);

      toast({
        title: "Reset requested",
        description: token
          ? "Reset token generated. Use it below to set your new password."
          : "If this email exists, reset instructions were sent.",
      });
    } catch (error: unknown) {
      const message = getErrorMessage(error, "Failed to request password reset");
      toast({
        title: "Request failed",
        description: message,
        variant: "destructive",
      });
    } finally {
      setRequestLoading(false);
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!tokenInput.trim()) {
      toast({
        title: "Token required",
        description: "Please provide the reset token.",
        variant: "destructive",
      });
      return;
    }

    if (newPassword.length < 6) {
      toast({
        title: "Invalid password",
        description: "Password must be at least 6 characters.",
        variant: "destructive",
      });
      return;
    }

    if (newPassword !== confirmPassword) {
      toast({
        title: "Passwords do not match",
        description: "Please make sure both password fields are the same.",
        variant: "destructive",
      });
      return;
    }

    setResetLoading(true);
    try {
      await api.post("/api/auth/reset-password", {
        token: tokenInput,
        newPassword,
      });

      toast({
        title: "Password updated",
        description: "You can now sign in with your new password.",
      });

      router.push("/login");
    } catch (error: unknown) {
      const message = getErrorMessage(error, "Failed to reset password");
      toast({
        title: "Reset failed",
        description: message,
        variant: "destructive",
      });
    } finally {
      setResetLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-primary/5 via-background to-accent/5 px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-3 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10">
            <Mail className="h-6 w-6 text-primary" />
          </div>
          <div>
            <CardTitle className="text-2xl font-bold">Forgot Password</CardTitle>
            <CardDescription className="mt-1">
              Enter your email and request a password reset.
            </CardDescription>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <form onSubmit={handleRequestReset} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="name@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                disabled={requestLoading || requestDone}
              />
            </div>

            <Button
              type="submit"
              className="w-full"
              disabled={requestLoading || requestDone}
            >
              {requestLoading ? "Submitting..." : "Request Reset"}
            </Button>
          </form>

          {requestDone && (
            <form onSubmit={handleResetPassword} className="space-y-4 rounded-lg border p-4">
              <div className="space-y-2">
                <Label htmlFor="token">Reset Token</Label>
                <Input
                  id="token"
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  placeholder="Paste reset token"
                  required
                  disabled={resetLoading}
                />
              </div>

              {resetToken && (
                <p className="text-xs text-muted-foreground">
                  Token was auto-filled from server (development mode).
                </p>
              )}

              <div className="space-y-2">
                <Label htmlFor="new-password">New Password</Label>
                <Input
                  id="new-password"
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Enter new password"
                  required
                  disabled={resetLoading}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="confirm-password">Confirm Password</Label>
                <Input
                  id="confirm-password"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Confirm new password"
                  required
                  disabled={resetLoading}
                />
              </div>

              <Button type="submit" className="w-full" disabled={resetLoading}>
                {resetLoading ? "Updating..." : "Set New Password"}
              </Button>
            </form>
          )}

          <Link
            href="/login"
            className="flex items-center justify-center gap-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Login
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}
