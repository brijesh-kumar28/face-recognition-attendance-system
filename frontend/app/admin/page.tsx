"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { StatsCard } from "@/components/StatsCard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Users,
  UserCheck,
  CalendarCheck,
  Database,
  Brain,
  ClipboardList,
  BarChart3,
} from "lucide-react";
import api from "@/lib/axios";
import type { AdminStats } from "@/lib/types";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
} from "recharts";

export default function AdminDashboard() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await api.get("/api/admin/stats");
        setStats(res.data);
      } catch {
        // Use fallback data on error
        setStats({
          totalUsers: 0,
          trainedUsers: 0,
          todayAttendance: 0,
          totalRecords: 0,
          weeklyTrend: [],
          userGrowth: [],
        });
      } finally {
        setIsLoading(false);
      }
    };
    fetchStats();
  }, []);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-muted-foreground">
            Overview of your attendance system
          </p>
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
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardContent className="p-6">
              <Skeleton className="h-[300px] w-full" />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-6">
              <Skeleton className="h-[300px] w-full" />
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">
          Overview of your attendance system
        </p>
      </div>

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatsCard
          title="Total Users"
          value={stats?.totalUsers ?? 0}
          icon={Users}
          description="Registered users"
          trend={{ value: 12, isPositive: true }}
        />
        <StatsCard
          title="Trained Users"
          value={stats?.trainedUsers ?? 0}
          icon={UserCheck}
          description="Face models trained"
          trend={{ value: 8, isPositive: true }}
        />
        <StatsCard
          title="Today Attendance"
          value={stats?.todayAttendance ?? 0}
          icon={CalendarCheck}
          description="Marked today"
        />
        <StatsCard
          title="Total Records"
          value={stats?.totalRecords ?? 0}
          icon={Database}
          description="All time records"
          trend={{ value: 5, isPositive: true }}
        />
      </div>

      {/* Quick Actions */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Link href="/admin/users">
          <Card className="h-full transition-colors hover:border-primary/40 hover:bg-primary/5">
            <CardContent className="flex items-center gap-3 p-5">
              <Users className="h-5 w-5 text-primary" />
              <div>
                <p className="font-medium">Registered Users</p>
                <p className="text-xs text-muted-foreground">Manage all users</p>
              </div>
            </CardContent>
          </Card>
        </Link>

        <Link href="/admin/train">
          <Card className="h-full transition-colors hover:border-primary/40 hover:bg-primary/5">
            <CardContent className="flex items-center gap-3 p-5">
              <Brain className="h-5 w-5 text-primary" />
              <div>
                <p className="font-medium">Train Dataset</p>
                <p className="text-xs text-muted-foreground">Train new users</p>
              </div>
            </CardContent>
          </Card>
        </Link>

        <Link href="/admin/attendance">
          <Card className="h-full transition-colors hover:border-primary/40 hover:bg-primary/5">
            <CardContent className="flex items-center gap-3 p-5">
              <ClipboardList className="h-5 w-5 text-primary" />
              <div>
                <p className="font-medium">Attendance Logs</p>
                <p className="text-xs text-muted-foreground">View check-in/out history</p>
              </div>
            </CardContent>
          </Card>
        </Link>

        <Link href="/admin/reports">
          <Card className="h-full transition-colors hover:border-primary/40 hover:bg-primary/5">
            <CardContent className="flex items-center gap-3 p-5">
              <BarChart3 className="h-5 w-5 text-primary" />
              <div>
                <p className="font-medium">Reports</p>
                <p className="text-xs text-muted-foreground">System insights</p>
              </div>
            </CardContent>
          </Card>
        </Link>
      </div>

      {/* Charts */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Weekly Attendance Trend</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={stats?.weeklyTrend ?? []}>
                <defs>
                  <linearGradient id="colorCount" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#1E3A8A" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#1E3A8A" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis
                  dataKey="day"
                  className="text-xs"
                  tick={{ fill: "hsl(var(--muted-foreground))" }}
                />
                <YAxis
                  className="text-xs"
                  tick={{ fill: "hsl(var(--muted-foreground))" }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "8px",
                    color: "hsl(var(--foreground))",
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="count"
                  stroke="#1E3A8A"
                  fill="url(#colorCount)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">User Growth</CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={stats?.userGrowth ?? []}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis
                  dataKey="month"
                  className="text-xs"
                  tick={{ fill: "hsl(var(--muted-foreground))" }}
                />
                <YAxis
                  className="text-xs"
                  tick={{ fill: "hsl(var(--muted-foreground))" }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "8px",
                    color: "hsl(var(--foreground))",
                  }}
                />
                <Bar
                  dataKey="users"
                  fill="#10B981"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
